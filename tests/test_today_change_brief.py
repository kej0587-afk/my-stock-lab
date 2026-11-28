from copy import deepcopy
from datetime import date, timedelta
import json

import pytest

from stock_lab_core.report_latest import account_key
from stock_lab_core.today_change_brief import (
    build_today_change_brief, make_today_change_session, merge_today_briefs,
    refresh_today_change_brief,
)


OWNER = "owner@example.test"
ACCOUNTS = ["test account"]
ACCOUNT = account_key(ACCOUNTS)
CONTEXT = {"version": "test_v1", "count_basis": "existing_today_mask"}
ROWS = [{"티커": "AAA", "입력출처": "등록", "보유여부": True,
         "최종읽기": "유지", "게이트상태": "방어우선"},
        {"티커": "BBB", "입력출처": "등록", "보유여부": False,
         "최종읽기": "관찰", "게이트상태": "방어우선"}]


def session(day="2026-11-27", **facts):
    return make_today_change_session(
        ROWS, dates={"US": day, "KR": day}, generated_at=day + "T23:00:00+09:00",
        account_key=ACCOUNT, comparison_context=CONTEXT, **facts,
    )


def brief(current, saved=(), **options):
    return build_today_change_brief(
        current, saved, owner_scope=OWNER, history_owner_scope=OWNER, account_key=ACCOUNT,
        today_action="기존 실행 조건 확인", **options,
    )


def test_current_only_never_reconstructs_old_headlines_or_embeds_static_policy():
    current = session(sector_leaders={"US": "반도체"}, execution_count=0)
    result = brief(current, static_policy=["장기코어 적립 유지"])
    assert result["headline"] == "현재 US 섹터 선두 반도체 · 오늘은 기존 실행 조건 확인"
    assert result["status"] == "current_only"
    assert result["static_policy"] == ["장기코어 적립 유지"]
    assert "장기코어" not in result["headline"]
    assert result["audit"]["available"] == 0


@pytest.mark.parametrize("field,old,new,wording", [
    ("sector_leaders", {"US": "금융"}, {"US": "반도체"}, "금융 → 반도체"),
    ("recovery_watch", ["AAA"], ["BBB"], "BBB 편입 / AAA 제외"),
    ("execution_count", 0, 2, "0개 → 2개"),
    ("held_actions", {"AAA": "유지"}, {"AAA": "축소 검토"}, "유지 → 축소 검토"),
])
def test_changes_come_from_real_prior_inputs(field, old, new, wording):
    prior, current = session("2026-11-25", **{field: old}), session(**{field: new})
    original = deepcopy((prior, current))
    result = brief(current, [prior], previous_sessions=prior["dates"])
    assert result["change_kind"] == field
    assert result["headline"].startswith("전 거래일 대비 ")
    assert wording in result["headline"]
    assert (prior, current) == original
    assert result["comparison_generated_at"] == prior["generated_at"]


def test_one_change_priority_does_not_recommend_execution():
    prior = session("2026-11-25", sector_leaders={"US": "금융"}, recovery_watch=[],
                    execution_count=0, held_actions={"AAA": "유지"})
    current = session(sector_leaders={"US": "반도체"}, recovery_watch=["BBB"],
                      execution_count=1, held_actions={"AAA": "축소 검토"})
    result = brief(current, [prior])
    assert result["change_kind"] == "sector_leaders"
    assert "실행후보" not in result["headline"]
    assert "매수" not in result["headline"]


def test_no_calendar_guess_for_thanksgiving_or_weekend():
    prior, current = session("2026-11-25"), session()
    result = brief(current, [prior])
    assert result["headline"].startswith("직전 저장 기준일과 동일")
    result = brief(current, [prior], previous_sessions=prior["dates"])
    assert result["headline"].startswith("전 거래일과 동일")
    assert result["comparison_dates"] == prior["dates"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda s: s.pop("account_key"), "account_scope_unknown_or_different"),
    (lambda s: s.update(account_key="acc_other"), "account_scope_unknown_or_different"),
    (lambda s: s.pop("comparison_context"), "observation_context_unknown_or_different"),
    (lambda s: s.update(comparison_context={"version": "different"}), "observation_context_unknown_or_different"),
    (lambda s: s.update(owner_scope="other@example.test"), "owner_scope_different"),
    (lambda s: s.update(generated_at="2026-11-28T23:00:00+09:00"), "future_generation"),
    (lambda s: s.update(generated_at="2026-11-25 23:00:00"), "dates_or_timestamp_unknown"),
])
def test_unknown_or_different_scope_time_context_cannot_say_same(mutation, reason):
    prior = session("2026-11-25")
    mutation(prior)
    result = brief(session(), [prior])
    assert result["status"] == "current_only"
    assert result["audit"]["excluded"][reason] == 1
    assert "동일" not in result["headline"]


def test_different_loader_owner_is_rejected():
    result = build_today_change_brief(session(), [session("2026-11-25")],
                                     owner_scope=OWNER, history_owner_scope="another@example.test", account_key=ACCOUNT)
    assert result["audit"]["excluded"] == {"unverified_scope": 1}


def test_same_source_day_runs_and_crossed_market_dates_are_not_previous_days():
    rerun = session()
    rerun["generated_at"] = "2026-11-27T10:00:00+09:00"
    crossed = session("2026-11-25")
    crossed["dates"]["KR"] = "2026-11-28"
    result = brief(session(), [rerun, crossed])
    assert result["audit"]["excluded"] == {"same_source_dates": 1, "future_source_date": 1}


def test_latest_saved_version_of_pair_wins_and_cannot_fill_missing_old_fields():
    older = session("2026-11-25", sector_leaders={"US": "금융"})
    newer = deepcopy(older)
    newer["generated_at"] = "2026-11-26T00:00:00+09:00"
    newer["brief_inputs"] = {}
    result = brief(session(sector_leaders={"US": "반도체"}), [older, newer])
    assert result["change_kind"] == ""
    assert "섹터 선두" not in result["headline"]
    assert "sector_leaders" not in result["audit"]["sessions"][0]["inputs"]


def test_population_changes_do_not_claim_count_or_membership_action_change():
    prior = session("2026-11-25", execution_count=2, recovery_watch=["BBB"], held_actions={"AAA": "유지"})
    current = session(execution_count=0, recovery_watch=[], held_actions={"CCC": "유지"})
    current["rows"] = [{**ROWS[0], "티커": "CCC"}]
    result = brief(current, [prior])
    assert result["status"] == "current_only"
    assert "동일" not in result["headline"]


def test_missing_inputs_are_not_zero_or_unchanged():
    current, prior = session(), session("2026-11-25")
    for item in (current, prior):
        item["rows"] = [{"티커": "AAA"}]
    result = brief(current, [prior])
    assert result["status"] == "current_only"
    assert "0개" not in result["headline"]


def test_last20_distinct_saved_pairs_are_not_claimed_as_20_consecutive_trading_days():
    history = [session((date(2026, 11, 26) - timedelta(days=n)).isoformat()) for n in range(30)]
    result = brief(session(), history + [history[0]])
    assert result["audit"]["available"] == 20
    assert result["audit"]["available_saved_prior_pairs"] == 30
    assert result["audit"]["eligible_comparison_pairs"] == 20
    assert result["audit"]["consecutive_trading_days_verified"] is False
    assert result["audit"]["sessions"][0]["dates"]["US"] == "2026-11-26"
    assert len({tuple(s["dates"].values()) for s in result["audit"]["sessions"]}) == 20


def test_one_line_collapses_untrusted_newlines_and_does_not_escape_html_itself():
    result = build_today_change_brief(session(), today_action="<test>\n확인")
    assert "\n" not in result["headline"]
    assert "<test> 확인" in result["headline"]


class Store:
    def __init__(self, sessions=()):
        self.sessions = {"/".join((s["dates"]["US"], s["dates"]["KR"])): deepcopy(s) for s in sessions}
        self.reads = self.writes = 0
        self.fail_read = self.fail_write = False

    def load_sessions(self, dates, *, owner_scope):
        assert owner_scope == OWNER
        self.reads += 1
        if self.fail_read:
            raise RuntimeError("DO_NOT_EXPOSE_OWNER_OR_CREDENTIALS")
        return deepcopy(self.sessions)

    def upsert_session(self, session, *, owner_scope):
        assert owner_scope == OWNER
        self.writes += 1
        if self.fail_write:
            raise RuntimeError("DO_NOT_EXPOSE_OWNER_OR_CREDENTIALS")
        self.sessions["/".join((session["dates"]["US"], session["dates"]["KR"]))] = deepcopy(session)


def refresh(state, current, store, tmp_path, **kwargs):
    return refresh_today_change_brief(state, current, owner_scope=OWNER, accounts=ACCOUNTS,
                                      store=store, path=tmp_path / "history.json", **kwargs)


def report(observation):
    return {"dates": observation["dates"], "generated_at": observation["generated_at"], "rows": deepcopy(ROWS),
            "today_briefs": {ACCOUNT: deepcopy(observation)}}


def test_adapter_read_save_and_repeat_render_are_once_per_calculation(tmp_path):
    store, state = Store([report(session("2026-11-25", execution_count=2))]), {}
    current = session(execution_count=0)
    first = refresh(state, current, store, tmp_path)
    second = refresh(state, current, store, tmp_path, today_action="새 행동 문구")
    assert first["change_kind"] == "execution_count"
    assert second["headline"].endswith("오늘은 새 행동 문구")
    assert (store.reads, store.writes) == (1, 1)
    assert second["persistence"]["cache_hit"] is True
    current["generated_at"] = "2026-11-28T01:00:00+09:00"
    refresh(state, current, store, tmp_path)
    assert (store.reads, store.writes) == (2, 2)


def test_adapter_preserves_other_accounts_report_rows_macro_and_timestamp(tmp_path):
    current = session()
    other = deepcopy(current)
    other["account_key"] = "acc_other"
    original = {"dates": current["dates"], "rows": [{"티커": "ORIGINAL"}],
                "generated_at": "2026-11-27T20:00:00+09:00", "macro_data": {"observed": 1},
                "source_provenance": {"observed": 2}, "today_briefs": {"acc_other": other}}
    store = Store([original])
    refresh({}, current, store, tmp_path)
    saved = store.sessions["2026-11-27/2026-11-27"]
    for key in ("rows", "generated_at", "macro_data", "source_provenance"):
        assert saved[key] == original[key]
    assert saved["today_briefs"]["acc_other"] == other
    assert saved["today_briefs"][ACCOUNT] == current


def test_legacy_owner_only_history_never_gets_current_account_stamped(tmp_path):
    prior = session("2026-11-25")
    prior.pop("account_key")
    prior.pop("comparison_context")
    store = Store([prior])
    result = refresh({}, session(), store, tmp_path)
    assert result["status"] == "current_only"
    assert result["audit"]["excluded"]["account_scope_unknown_or_different"] == 1
    assert result["audit"]["available_saved_prior_pairs"] == 1
    assert result["audit"]["eligible_comparison_pairs"] == 0
    assert store.sessions["2026-11-25/2026-11-25"] == prior


def test_remote_read_failure_never_blindly_overwrites_and_does_not_leak_error(tmp_path):
    store = Store()
    store.fail_read = True
    result = refresh({}, session(), store, tmp_path)
    assert store.writes == 0
    assert result["persistence"]["local_saved"] is True
    assert "DO_NOT_EXPOSE" not in json.dumps(result)
    assert result["persistence"]["read_status"] == "remote_unavailable_local_fallback"
    assert "원격 가용 일수 미확인" in result["audit"]["coverage_note"]


def test_local_fallback_round_trip_compares_only_scoped_saved_observation(tmp_path):
    refresh({}, session("2026-11-25", execution_count=2), None, tmp_path)
    result = refresh({}, session(execution_count=0), None, tmp_path)
    assert result["change_kind"] == "execution_count"
    assert result["persistence"]["backend"] == "local"


def test_invalid_context_or_anonymous_owner_never_reads_or_saves(tmp_path):
    store = Store()
    current = session()
    current.pop("comparison_context")
    result = refresh({}, current, store, tmp_path)
    assert result["persistence"]["read_status"] == "invalid_context"
    assert (store.reads, store.writes) == (0, 0)


def test_newer_observation_is_retained_on_older_run(tmp_path):
    newest = session(execution_count=2)
    newest["generated_at"] = "2026-11-28T01:00:00+09:00"
    store = Store([report(newest)])
    refresh({}, session(execution_count=0), store, tmp_path)
    assert store.sessions["2026-11-27/2026-11-27"]["today_briefs"][ACCOUNT] == newest


def test_report_regeneration_preserves_observations_for_all_accounts(tmp_path, monkeypatch):
    from stock_lab_core import report_history
    from tests.test_report_history_store import FakeClient
    from stock_lab_core.report_history_store import SupabaseReportHistoryStore

    monkeypatch.setattr(report_history, "_public_names", lambda: {})
    client = FakeClient()
    store = SupabaseReportHistoryStore(client, owner_scope=OWNER)
    current = session()
    other = deepcopy(current)
    other["account_key"] = "acc_other"
    payload = report(current)
    payload["today_briefs"]["acc_other"] = other
    store.upsert_session(payload, owner_scope=OWNER)
    result = report_history.update_report_history(
        ROWS, current["dates"], owner_scope=OWNER, store=store, path=tmp_path / "report.json",
        generated_at="2026-11-28T02:00:00+09:00", macro_data={"new": 1})
    saved = store.load_sessions(current["dates"], owner_scope=OWNER)
    assert result["history_durable"]
    assert saved["2026-11-27/2026-11-27"]["today_briefs"] == payload["today_briefs"]
    assert saved["2026-11-27/2026-11-27"]["macro_data"] == {"new": 1}


def test_merge_map_is_pure_and_newest_account_observation_wins():
    first, second = report(session()), report(session(execution_count=2))
    second["today_briefs"][ACCOUNT]["generated_at"] = "2026-11-28T02:00:00+09:00"
    before = deepcopy((first, second))
    assert merge_today_briefs(second, first)[ACCOUNT] == second["today_briefs"][ACCOUNT]
    assert (first, second) == before


def test_incomplete_other_account_metadata_is_preserved_without_becoming_comparable(tmp_path):
    payload = report(session())
    unknown = {"account_key": "acc_other", "older_schema": "keep verbatim"}
    payload["today_briefs"]["acc_other"] = unknown
    store = Store([payload])
    refresh({}, session(execution_count=1), store, tmp_path)
    assert store.sessions["2026-11-27/2026-11-27"]["today_briefs"]["acc_other"] == unknown
