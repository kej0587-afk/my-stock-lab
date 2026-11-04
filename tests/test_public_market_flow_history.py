"""Offline investor-history contracts, distinct from the OHLCV history feed."""

from copy import deepcopy
from datetime import date, datetime, timedelta
import socket

import pytest

from stock_lab_core import public_market_flow_history as history
from stock_lab_core.public_market_data import KST, parse_indicators
from stock_lab_core.report_market_summary import korean_flow_tables


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("History must not fetch network data")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    history._session_closes.cache_clear()
    yield
    history._session_closes.cache_clear()


def snapshot(day, value=100_000_000, *, hour=16):
    at = datetime.combine(date.fromisoformat(day), datetime.min.time(), KST).replace(hour=hour)
    payload = {"domesticIndex": {market: {
        "itemCode": market,
        "meta": {"marketCode": market, "exchangeCode": "KRX", "currencyCode": "KRW"},
        "investorTrendBaseDate": day, "investorTrendExchangeType": "KRX",
        "investorTrends": [{"investorType": identity, "netBuyAmount": str(raw)} for identity, raw in
                           (("foreigner", value), ("organization", -value), ("individual", 0))],
    } for market in ("KOSPI", "KOSDAQ")}}
    return dict(parse_indicators(payload, at.date(), at), checked_at=at.isoformat())


@pytest.fixture
def context():
    pytest.importorskip("exchange_calendars")
    days = sorted(history._session_closes(date(2026, 11, 4)))[-21:]
    snapshots = [snapshot(day, -100_000_000 if index == 0 else 100_000_000)
                 for index, day in enumerate(days)]
    return {"public_market_evidence": snapshots[-1], "public_market_flow_history": snapshots[:-1],
            "market_evidence_checked_at": snapshots[-1]["checked_at"]}


def summarize(context):
    return history.summarize_public_flow_history(
        context["public_market_evidence"], context.get("public_market_flow_history"),
        session_date="2026-11-04", checked_at=context["market_evidence_checked_at"])


def test_complete_windows_sign_runs_zero_and_inputs_unchanged(context):
    before = deepcopy(context)
    rows = summarize(context)
    foreign, institution, individual = rows[:3]
    assert (foreign["sum_5"], foreign["sum_20"], foreign["streak_days"], foreign["streak_direction"]) == (5, 20, 20, "buy")
    assert (institution["sum_5"], institution["sum_20"], institution["streak_days"], institution["streak_direction"]) == (-5, -20, 20, "sell")
    assert individual["sum_20"] == 0 and individual["streak_days"] == 0
    assert individual["streak_direction"] == "neutral"
    assert all(row["provisional"] is True and row["history_reason"] == "available" for row in rows)
    assert context == before


def test_weekends_and_exchange_holiday_are_not_missing_sessions(context):
    closes = history._session_closes(date(2026, 11, 4))
    assert "2026-10-09" not in closes and "2026-10-10" not in closes
    assert "2026-10-08" in closes and "2026-10-12" in closes
    assert summarize(context)[0]["sum_20"] == 20


@pytest.mark.parametrize("index,expected_five", [(-1, None), (-8, 5)])
def test_missing_session_is_not_skipped_or_zero_filled(context, index, expected_five):
    removed = context["public_market_flow_history"].pop(index)
    day = removed["flows"]["KOSPI"]["foreign"]["asof"]
    row = summarize(context)[0]
    assert row["sum_5"] == expected_five and row["sum_20"] is None
    assert row["streak_days"] is None and day in row["missing_dates"]["20"]


def test_unknown_run_start_is_not_an_exact_twenty_day_run(context):
    context["public_market_flow_history"].pop(0)
    row = summarize(context)[0]
    assert row["sum_20"] == 20 and row["streak_days"] is None


def test_gap_before_known_run_boundary_does_not_invalidate_short_run(context):
    prior = context["public_market_flow_history"][-2]
    day = prior["flows"]["KOSPI"]["foreign"]["asof"]
    context["public_market_flow_history"][-2] = snapshot(day, 0)
    context["public_market_flow_history"].pop(-4)
    row = summarize(context)[0]
    assert row["streak_days"] == 2 and row["sum_5"] is None


def test_duplicate_order_latest_revision_and_equal_time_conflicts(context):
    prior = context["public_market_flow_history"][-1]
    day = prior["flows"]["KOSPI"]["foreign"]["asof"]
    context["public_market_flow_history"] += [deepcopy(prior), snapshot(day, 200_000_000, hour=17)]
    context["public_market_flow_history"].reverse()
    assert summarize(context)[0]["sum_5"] == 6
    context["public_market_flow_history"].append(snapshot(day, 300_000_000, hour=17))
    assert summarize(context)[0]["sum_5"] is None


@pytest.mark.parametrize("field,value", [
    ("raw_value", None), ("raw_value", True), ("value", float("nan")), ("value", 99),
    ("unit", "KRW"), ("raw_unit", "USD"), ("exchange", "NXT"), ("market", "KOSDAQ"),
    ("source_url", "https://example.invalid"), ("data_url", "https://example.invalid"),
    ("source", "unverified"), ("is_mock", True), ("provisional", False),
    ("date_basis", "quote_date"), ("ok", False), ("asof", "invalid"),
])
def test_bad_history_row_only_invalidates_its_own_identity(context, field, value):
    context["public_market_flow_history"][-1]["flows"]["KOSPI"]["foreign"][field] = value
    rows = summarize(context)
    assert rows[0]["sum_5"] is None
    assert rows[1]["sum_5"] == -5 and rows[3]["sum_5"] == 5


def test_prior_intraday_data_excluded_but_current_provisional_data_allowed(context):
    prior = context["public_market_flow_history"][-1]
    day = prior["flows"]["KOSPI"]["foreign"]["asof"]
    context["public_market_flow_history"][-1] = snapshot(day, hour=14)
    assert summarize(context)[0]["sum_5"] is None
    context["public_market_flow_history"][-1] = prior
    context["public_market_evidence"] = snapshot("2026-11-04", hour=14)
    context["market_evidence_checked_at"] = context["public_market_evidence"]["checked_at"]
    assert summarize(context)[0]["sum_5"] == 5


@pytest.mark.parametrize("offset", [-1, 301])
def test_current_freshness_gate_is_unchanged(context, offset):
    at = datetime.fromisoformat(context["market_evidence_checked_at"]) + timedelta(seconds=offset)
    context["market_evidence_checked_at"] = at.isoformat()
    assert summarize(context) == []


def test_future_saved_collection_and_future_rows_not_used(context):
    context["public_market_flow_history"][-1]["checked_at"] = "2026-11-05T16:00:00+09:00"
    context["public_market_flow_history"].append(snapshot("2026-11-05"))
    assert summarize(context)[0]["sum_5"] is None


def test_saved_freshness_is_checked_at_original_clock(context):
    prior = context["public_market_flow_history"][-1]
    at = datetime.fromisoformat(prior["checked_at"]) + timedelta(seconds=301)
    prior["checked_at"] = at.isoformat()
    assert summarize(context)[0]["sum_5"] is None


@pytest.mark.parametrize("failure", [ImportError(), ValueError("calendar_coverage")])
def test_calendar_unavailable_fails_closed_without_hiding_current(context, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(history, "_exchange_schedule", fail)
    history._session_closes.cache_clear()
    rows = summarize(context)
    assert all(row["history_reason"] == "calendar_unavailable" and row["sum_5"] is None for row in rows)
    lines = "\n".join(korean_flow_tables(context, {"date": "2026-11-04"}))
    assert "KOSPI | +0.00 | +1.00 | -1.00 | 2026-11-04" in lines
    assert "거래소 달력 미확보" in lines
    assert "시장 | 투자자 | 연속 순매수·순매도" not in lines


@pytest.mark.parametrize("supplied", [None, [], {}, [None] * 129])
def test_missing_malformed_and_bounded_history(context, supplied):
    context["public_market_flow_history"] = supplied
    assert summarize(context)[0]["sum_5"] is None


def test_report_wiring_missing_data_labels_and_no_gate_mutation(context):
    before = deepcopy(context)
    lines = "\n".join(korean_flow_tables(context, {"date": "2026-11-04"}))
    assert "KOSPI | 외국인 | 순매수 20거래일 | +5.00 | +20.00 | 2026-11-04" in lines
    assert "잠정/정정 가능" in lines and "기준일 포함" in lines
    assert context == before
    context.pop("public_market_flow_history")
    lines = "\n".join(korean_flow_tables(context, {"date": "2026-11-04"}))
    assert "KOSPI | 외국인 | 자료 부족 | 자료 부족 | 자료 부족" in lines
    assert korean_flow_tables(context, {"date": "2026-11-03"}) == []


def test_all_history_metrics_unknown_show_short_notice_and_keep_daily_flows(context):
    context.pop("public_market_flow_history")
    for group in context["public_market_evidence"]["flows"].values():
        group.pop("individual")
    before = deepcopy(context)
    assert history.public_flow_history_lines(context, session_date="2026-11-04") == [
        "", "한국 투자자 수급 이력 부족: 5·20거래일 합계·연속일수 미확인."]
    lines = "\n".join(korean_flow_tables(context, {"date": "2026-11-04"}))
    assert "KOSPI | — | +1.00 | -1.00 | 2026-11-04" in lines
    assert "시장 | 투자자 | 연속 순매수·순매도" not in lines
    assert context == before


@pytest.mark.parametrize("key", ["sum_5", "sum_20", "streak_days"])
def test_any_known_history_metric_including_zero_keeps_table(monkeypatch, key):
    row = dict(market="KOSPI", label="외국인", asof="2026-11-04", sum_5=None,
               sum_20=None, streak_days=None, streak_direction="neutral", history_reason="insufficient_history")
    row[key] = 0
    monkeypatch.setattr(history, "summarize_public_flow_history", lambda *args, **kwargs: [row])
    lines = "\n".join(history.public_flow_history_lines({}, session_date="2026-11-04"))
    assert "시장 | 투자자 | 연속 순매수·순매도" in lines
    assert "한국 투자자 수급 이력 부족:" not in lines


def test_archive_projection_excludes_intraday_and_unknown_fields():
    pytest.importorskip("exchange_calendars")
    evidence = snapshot("2026-11-04")
    evidence["extra_private_field"] = "not_for_storage"
    evidence["flows"]["KOSPI"]["foreign"]["extra_private_field"] = "not_for_storage"
    before = deepcopy(evidence)
    saved = history.validated_flow_snapshot(evidence, checked_at=evidence["checked_at"])
    assert set(saved) == {"flows", "checked_at"}
    assert "extra_private_field" not in saved["flows"]["KOSPI"]["foreign"]
    assert evidence == before
    intraday = snapshot("2026-11-04", hour=14)
    assert history.validated_flow_snapshot(intraday, checked_at=intraday["checked_at"]) is None
    stale = (datetime.fromisoformat(evidence["checked_at"]) + timedelta(seconds=301)).isoformat()
    assert history.validated_flow_snapshot(evidence, checked_at=stale) is None


def test_real_persistence_path_restores_twenty_sessions_after_restart(context, tmp_path, monkeypatch):
    from stock_lab_core import report_history
    from tests.test_report_history_store import FakeClient, run

    monkeypatch.setattr(report_history, "_public_names", lambda: {})
    client = FakeClient()
    snapshots = context["public_market_flow_history"] + [context["public_market_evidence"]]
    for index, evidence in enumerate(snapshots):
        day = evidence["flows"]["KOSPI"]["foreign"]["asof"]
        # Each call uses an empty local path: prior data must come from the store.
        result = run(client, tmp_path / str(index), dates={"US": day, "KR": day},
                     public_market_evidence=evidence, market_evidence_checked_at=evidence["checked_at"],
                     generated_at=evidence["checked_at"])
    assert result["history_durable"] and len(client.database) == 21
    assert len(client.calls) == 42  # Existing one read/one write only, no extra calls.
    restored = dict(context, public_market_flow_history=result["public_market_flow_history"])
    assert summarize(restored)[0]["sum_20"] == 20
    assert summarize(restored)[0]["streak_days"] == 20
    stored = list(client.database.values())[-1]["payload"]["public_market_flows"]
    assert stored["flows"]["KOSPI"]["foreign"]["asof"] == "2026-11-04"
    assert stored["checked_at"] == context["market_evidence_checked_at"]
    other = run(client, tmp_path / "other", owner="bob@example.test", dates={"US": day, "KR": day},
                generated_at=context["market_evidence_checked_at"])
    assert not other.get("public_market_flow_history")


def test_local_fallback_and_missing_refresh_preserve_valid_same_pair(context, tmp_path, monkeypatch):
    from stock_lab_core import report_history
    from tests.test_report_history_store import DatabaseFailure, FakeClient, run

    monkeypatch.setattr(report_history, "_public_names", lambda: {})
    client = FakeClient()
    client.read_error = DatabaseFailure("unavailable")
    evidence = context["public_market_evidence"]
    kwargs = dict(dates={"US": "2026-11-04", "KR": "2026-11-04"},
                  market_evidence_checked_at=evidence["checked_at"], generated_at=evidence["checked_at"])
    first = run(client, tmp_path, public_market_evidence=evidence, **kwargs)
    assert first["history_backend"] == "local" and not first["history_durable"]
    failed = dict(evidence, flows={})
    again = run(client, tmp_path, public_market_evidence=failed, **kwargs)
    assert again["public_market_flow_history"]
    assert again["public_market_flow_history"][0] == first["public_market_flow_history"][0]
    assert not any(call[0] == "upsert" for call in client.calls)


def test_invalid_and_intraday_collection_do_not_create_daily_archive(tmp_path, monkeypatch):
    from stock_lab_core import report_history
    from tests.test_report_history_store import FakeClient, run

    monkeypatch.setattr(report_history, "_public_names", lambda: {})
    client = FakeClient()
    evidence = snapshot("2026-11-04", hour=14)
    result = run(client, tmp_path, dates={"US": "2026-11-04", "KR": "2026-11-04"},
                 public_market_evidence=evidence, market_evidence_checked_at=evidence["checked_at"],
                 generated_at=evidence["checked_at"])
    assert result["public_market_flow_history"] == []
    assert "public_market_flows" not in list(client.database.values())[0]["payload"]


def test_explicit_collection_passes_public_snapshot_into_existing_store():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    collect = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "_collect_today_report_context")
    call = next(node for node in ast.walk(collect) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "update_report_history")
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
    assert keywords["public_market_evidence"] == "context.get('public_market_evidence')"
    assert keywords["market_evidence_checked_at"] == "context.get('market_evidence_checked_at')"
