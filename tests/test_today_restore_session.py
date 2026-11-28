"""New browser restoration preserves the original calculation, not current quotes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from stock_lab_core.today_queue import build_today_queue_signature as signature
from stock_lab_core.today_queue_session import (
    EXPECTED_CONTEXT_KEY, LAST_RUN_KEY, SIGNATURE_KEY, SUMMARY_KEY, restore_cached_summary,
)
from stock_lab_core.today_restore_session import (
    capture_discovery_context, restore_discovery_context, save_completed_display, saved_display_for_context,
)
from stock_lab_core.today_result_observation import result_metadata
from stock_lab_core.today_snapshot import load_today_queue_summary_snapshot, save_today_queue_summary_snapshot


def fixture(tmp_path, *, age=0):
    base = tuple({"ticker": f"T{i}", "name": f"Company {i}", "qty": 0} for i in range(92))
    auto = tuple({"ticker": f"T{i}", "name": f"Company {i}", "bucket": "flow_candidate"} for i in range(92, 104))
    items = base + auto
    at = (datetime.now(timezone(timedelta(hours=9))) - timedelta(minutes=age)).strftime("%Y-%m-%d %H:%M")
    frame = pd.DataFrame({"티커": [x["ticker"] for x in items], "게이트상태": ["방어우선"] * 103 + ["데이터확인"],
                          "판정코드": ["KEEP"] * 104, "Adj점수": range(104), "금액": [1.123456789123456] * 104})
    frame.attrs.update(portfolio_signal_context="account-context", portfolio_signal_at=at)
    flow = {"flow_df": pd.DataFrame({"티커": ["QQQ"], "점수": [3.25]}), "original_at": at}
    sig = signature(items, "계좌", logic_version="test")
    state = {SUMMARY_KEY: frame, SIGNATURE_KEY: sig, LAST_RUN_KEY: at}
    capture_discovery_context(state, frame, mode="계좌", raw_watch_items=base, base_items=base,
        watch_items=items, flow_auto_items=auto, logic_version="test", refresh_flow_candidates=True,
        flow_snapshot=flow, calculated_at=at)
    path = tmp_path / "snapshot.json"
    def save(*args, **kwargs):
        save_today_queue_summary_snapshot(*args, path=path, **kwargs)
    save_completed_display(state, frame, frame, signature=sig, owner="user", save=save)
    def load(**kwargs):
        return load_today_queue_summary_snapshot(path=path, **kwargs)
    return base, auto, frame, flow, sig, at, load


def restore(state, base, load, *, context="account-context", snapshot=None, owner="user"):
    return restore_discovery_context(state, owner=owner, raw_watch_items=base, mode="계좌",
        logic_version="test", account_context=context, flow_snapshot=snapshot,
        build_items=lambda items: items, signature=signature, load=load)


def test_new_browser_104_exact_original_values_csv_time_and_zero_calculations(tmp_path):
    base, auto, original, flow, sig, at, load = fixture(tmp_path)
    state = {EXPECTED_CONTEXT_KEY: "account-context"}
    items, restored_auto = restore(state, base, load)
    assert len(items) == 104 and restored_auto == auto
    raw = restore_cached_summary(state, "user", sig, load_today_queue_summary_snapshot=lambda **kw: pytest.fail("loaded twice"))
    meta = result_metadata(raw, state, run_summary=False, signature=sig, account_context="account-context")
    shown = saved_display_for_context(raw, meta)
    assert meta["점검결과출처"] == "저장 결과 복원" and meta["점검원계산시각"] == at
    assert meta["점검입력맥락"] == "일치"
    # No display rewrite, repricing, amount recalculation, or decimal truncation.
    pd.testing.assert_frame_equal(shown[original.columns], original, check_exact=True)
    assert shown[original.columns].to_csv(index=False) == original.to_csv(index=False)
    pd.testing.assert_frame_equal(state["today_market_flow_snapshot"]["flow_df"], flow["flow_df"])
    assert state.get("_today_full_calculation_count", 0) == 0


@pytest.mark.parametrize("kind", ["watch", "quantity", "account", "expired", "disabled"])
def test_actual_change_or_expiry_remains_recalculation_needed(tmp_path, kind):
    base, _, _, _, sig, _, load = fixture(tmp_path, age=121 if kind == "expired" else 0)
    state = {EXPECTED_CONTEXT_KEY: "changed" if kind == "account" else "account-context"}
    current = deepcopy(base)
    if kind == "watch":
        current = current[:-1]
    elif kind == "quantity":
        current[0]["qty"] = 1
    elif kind == "disabled":
        state["today_queue_refresh_flow_candidates"] = False
    assert restore(state, current, load, context=state[EXPECTED_CONTEXT_KEY]) is None
    raw = restore_cached_summary(state, "user", sig, load_today_queue_summary_snapshot=load)
    meta = result_metadata(raw, state, run_summary=False, signature=sig, account_context=state[EXPECTED_CONTEXT_KEY])
    assert meta["점검입력맥락"] != "일치"
    assert saved_display_for_context(raw, meta) is None
    assert raw["게이트상태"].eq("데이터확인").all()


def test_newer_flow_and_other_account_are_not_replaced(tmp_path):
    base, _, _, _, _, _, load = fixture(tmp_path)
    state = {}
    assert restore(state, base, load, snapshot={"new": True}) is None
    assert state == {}
    assert restore(state, base, load, owner="someone-else") is None
    assert state == {}


def test_newer_flow_same_candidates_invalidates_saved_gate(tmp_path):
    base, _, _, flow, sig, _, load = fixture(tmp_path)
    state = {EXPECTED_CONTEXT_KEY: "account-context"}
    assert restore(state, base, load)
    state["today_market_flow_snapshot"] = deepcopy(flow)
    state["today_market_flow_snapshot"]["flow_df"].loc[0, "점수"] = -50
    raw = restore_cached_summary(state, "user", sig, load_today_queue_summary_snapshot=load)
    meta = result_metadata(raw, state, run_summary=False, signature=sig, account_context="account-context")
    assert "돈흐름 입력 변경" in meta["점검재계산사유"]
    assert saved_display_for_context(raw, meta) is None


def test_dedupe_with_nested_saved_frames_preserves_values_and_source_attrs(app_module):
    frame = pd.DataFrame({"티커": ["A", "A", ""], "금액": [1.123456789123456, 2., 3.]})
    frame.attrs["today_restore_inputs"] = {"flow_snapshot": {"flow_df": pd.DataFrame({"x": [1, 2]})}}
    source = deepcopy(frame)
    result = app_module.dedupe_dashboard_summary_df(frame)
    assert result["금액"].tolist() == [1.123456789123456, 3.]
    pd.testing.assert_frame_equal(frame, source)
    pd.testing.assert_frame_equal(result.attrs["today_restore_inputs"]["flow_snapshot"]["flow_df"],
                                  source.attrs["today_restore_inputs"]["flow_snapshot"]["flow_df"])


def test_basic_run_without_flow_restores_no_extra_candidates(tmp_path):
    base, _, original, _, _, _, _ = fixture(tmp_path)
    original = original.iloc[:92].copy()
    original.attrs = {"portfolio_signal_context": "account-context"}
    state = {}
    at = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    capture_discovery_context(state, original, mode="계좌", raw_watch_items=base, base_items=base,
        watch_items=base, flow_auto_items=(), logic_version="test", refresh_flow_candidates=False,
        flow_snapshot=None, calculated_at=at)
    result = restore(state, base, lambda **kwargs: (original, signature(base, "계좌", logic_version="test"), at))
    assert result == (base, ())
    assert state["today_queue_refresh_flow_candidates"] is False


def test_disk_restore_reuses_full_observation_without_rounding_or_replay(tmp_path, monkeypatch):
    """Exercise the app's post-restore observation call, not just frozen display loading."""
    from stock_lab_core import today_result_observation as observation

    at = datetime.now(timezone(timedelta(hours=9))).isoformat()
    base = ({"ticker": "EXAMPLE", "name": "Synthetic", "qty": 0},)
    sig = signature(base, "계좌", logic_version="test")
    original = pd.DataFrame([{
        "티커": "EXAMPLE", "종목명": "Synthetic", "판정분류": "buyish", "판정코드": "TEST_ENTRY",
        "최종읽기": "정밀확인", "실행메모": "정찰", "🔥기술적 타점": "진입",
        "계산시각": at, "가격입력ID": "synthetic-price-id", "가격자료기준일": "2026-11-27",
        "지표마지막봉": "2026-11-27", "가격신선도": "current", "가격신선도검증대상": True,
        "데이터상태": "OK", "RR값": .512345678912345, "R/R성격": "차트구조",
        "RSI": 50., "MFI": 50., "볼린저 %B": .5, "후보점수": 88,
        "부족액": "1000", "금액": 1.123456789123456,
        "게이트상태": "실행가능", "게이트근거": "original", "qty": 0., "has_pos": False,
    }])
    original.attrs = {"portfolio_signal_context": "account-context", "portfolio_signal_at": at}
    state = {SUMMARY_KEY: original, SIGNATURE_KEY: sig, LAST_RUN_KEY: at}
    flow = {"flow_df": pd.DataFrame({"티커": ["EXAMPLE"], "점수": [3.25]})}
    capture_discovery_context(
        state, original, mode="계좌", raw_watch_items=base, base_items=base,
        watch_items=base, flow_auto_items=(), logic_version="test", refresh_flow_candidates=True,
        flow_snapshot=flow, calculated_at=at,
    )
    fresh_meta = result_metadata(original, state, run_summary=True, signature=sig,
                                 account_context="account-context")
    raw = observation.attach_result_metadata(original, fresh_meta)
    displayed = raw.copy(deep=True)
    displayed["시장실행상태"] = "시장방어: 신규매수 중단"
    displayed["게이트상태"] = "방어우선"
    displayed["게이트근거"] = "시장방어"
    frozen = observation.reuse_or_build_market_observation(
        displayed, raw, fresh_meta, state, signature=sig, context="account-context",
    )
    assert frozen["시장만모의해제"].tolist() == ["다른 조건도 차단"]
    path = tmp_path / "exact-observation.json"

    def save(*args, **kwargs):
        save_today_queue_summary_snapshot(*args, path=path, **kwargs)

    def load(**kwargs):
        return load_today_queue_summary_snapshot(path=path, **kwargs)

    save_completed_display(state, raw, frozen, signature=sig, owner="user", save=save)
    cold_state = {EXPECTED_CONTEXT_KEY: "account-context"}
    assert restore(cold_state, base, load) == (base, ())
    restored = restore_cached_summary(cold_state, "user", sig, load_today_queue_summary_snapshot=load)
    assert restored["RR값"].iloc[0] == .512345678912345
    assert restored.attrs["portfolio_signal_at"] == at
    pd.testing.assert_frame_equal(cold_state["today_market_flow_snapshot"]["flow_df"], flow["flow_df"])
    restored_meta = result_metadata(restored, cold_state, run_summary=False, signature=sig,
                                    account_context="account-context")
    assert restored_meta["점검입력맥락"] == "일치"
    assert restored_meta["점검결과출처"] == "저장 결과 복원"
    assert restored_meta["점검원계산시각"] == at
    restored_raw = observation.attach_result_metadata(restored, restored_meta)
    restored_display = saved_display_for_context(restored_raw, restored_meta)
    assert restored_display is not None

    def forbid_replay(*args, **kwargs):
        pytest.fail("Same original disk inputs must reuse evidence without replaying checks")

    monkeypatch.setattr(observation, "attach_market_observation", forbid_replay)
    shown = observation.reuse_or_build_market_observation(
        restored_display, restored_raw, restored_meta, cold_state,
        signature=sig, context="account-context",
    )
    expected = observation.attach_result_metadata(frozen, restored_meta)
    expected["시장만모의해제_증거출처"] = "동일 계산ID·서명·계좌맥락의 관찰 재사용"
    pd.testing.assert_frame_equal(shown, expected, check_exact=True)
    assert shown.to_csv(index=False) == expected.to_csv(index=False)
    assert shown["게이트상태"].tolist() == ["방어우선"]
    assert shown["시장만모의해제_실행가능"].tolist() == ["미확인"]


@pytest.mark.parametrize("groups", [
    ("price_defense", "rapid_drop", "structure"),  # CSV 06
    ("overheat", "data_issue", "other_caution"),  # CSV 07
])
def test_review_csv_concat_keeps_rows_and_original_snapshot_attrs(app_module, groups):
    from stock_lab_core.today_restore_inputs import encode_snapshot_value

    source = pd.DataFrame({"티커": ["SYN_A", "SYN_B"], "게이트상태": ["방어우선"] * 2,
                           "group": [groups[1], groups[0]], "금액": [1.123456789123456, 2.]})
    source.attrs = {
        "portfolio_signal_context": "synthetic-account",
        "today_saved_display": source.copy(deep=True),
        "today_restore_inputs": {"flow_snapshot": {"flow_df": pd.DataFrame({"score": [3.25]})}},
    }
    before = encode_snapshot_value(source)
    whole = app_module._today_review_frame(source)
    assert whole is not source and whole.attrs == {}
    assert whole.to_csv(index=False) == source.to_csv(index=False)
    parts = [app_module._today_review_frame(source, source["group"].eq(group)) for group in groups]
    assert all(part.attrs == {} for part in parts)
    assert parts[-1].empty  # Empty export categories must also be safe to concatenate.
    combined = pd.concat(parts, ignore_index=True)
    expected = whole.iloc[[1, 0]].reset_index(drop=True)
    pd.testing.assert_frame_equal(combined, expected, check_exact=True)
    assert combined.to_csv(index=False) == expected.to_csv(index=False)
    assert encode_snapshot_value(source) == before
