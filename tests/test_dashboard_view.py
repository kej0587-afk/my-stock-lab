"""Dashboard input identity and display gates, with no external providers."""

import ast
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_lab_core.dashboard_view import (
    build_dashboard_signature, cached_dashboard_analyst_loader, dashboard_cache_matches, dashboard_tables,
    prepare_dashboard_display, render_dashboard_group_summary,
)
from stock_lab_core.decision_workflow import attach_market_execution_context, build_decision_workflow
from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT, apply_execution_gate_columns
from stock_lab_core.formatters import clean_float, normalize_ticker, sanitize_ticker_value


APP = Path(__file__).resolve().parents[1] / "app.py"


def _tree():
    return ast.parse(APP.read_text(encoding="utf-8-sig"))


def _candidate(ticker="MSFT", **changes):
    decision = dict(grade="A", t_score=8, dec="신규진입: 대장주 포착", decision_code="NEW_ENTRY_LEADER",
                    decision_group="buyish", cur_p=100, rr_stop=90, rr_target=120,
                    rr_ratio=2.0, ma20=98, atr=5)
    row = build_decision_workflow(ticker, ticker, decision, is_etf=ticker == "SOXL")
    return dict(row, 종목명=ticker, 현재가="$100.00", 전광판그룹="미국 개별주", **changes)


def _prepare(raw, guard=None, *, flow=None, analyst=None):
    def attach(frame, shortlist, *, snapshot):
        if flow:
            frame["돈흐름_판정"] = flow
        return frame

    return prepare_dashboard_display(
        raw, snapshot={}, flow_shortlist=pd.DataFrame(), market_guard=guard or {},
        attach_flow_context=attach,
        get_analyst_snapshot=analyst or (lambda ticker: {"ok": False, "status": "lookup_error", "data": {}}),
        load_latest_price=lambda ticker: pytest.fail("Displayed price must not trigger a new price lookup"),
    )


@pytest.mark.parametrize("ticker,guard", [
    ("MSFT", {"action": "신규매수 중단"}),
    ("MSFT", {"us_stats": {"mode": "위험"}, "kr_stats": {"mode": "정상"}}),
    ("SOXL", {"us_stats": {"mode": "방어"}}),
])
def test_display_matches_shared_gate_and_does_not_mutate_raw(ticker, guard):
    raw = pd.DataFrame([_candidate(ticker)])
    raw.attrs["measurement"] = {"id": "original"}
    original = deepcopy(raw)
    assert raw.iloc[0]["게이트상태"] == GATE_EXECUTABLE
    view = _prepare(raw, guard)
    expected = apply_execution_gate_columns(attach_market_execution_context(raw, guard))
    assert view.iloc[0]["게이트상태"] == expected.iloc[0]["게이트상태"] == GATE_DEFENSE
    assert view.iloc[0]["게이트근거"] == expected.iloc[0]["게이트근거"]
    for column in ("판정코드", "후보품질", "후보점수", "📌후보등급", "현재가", "🔥기술적 타점"):
        pd.testing.assert_series_equal(view[column], raw[column])
    pd.testing.assert_frame_equal(raw, original)
    assert raw.attrs == original.attrs
    view.attrs["measurement"]["id"] = "changed"
    assert raw.attrs["measurement"]["id"] == "original"


def test_same_cached_row_rechecks_changed_regional_guard():
    raw = pd.DataFrame([_candidate()])
    assert _prepare(raw, {"kr_stats": {"mode": "위험"}}).iloc[0]["게이트상태"] == GATE_DATA_CHECK
    assert _prepare(raw, {"kr_stats": {"mode": "위험"}, "us_stats": {"mode": "정상"}}).iloc[0]["게이트상태"] == GATE_EXECUTABLE
    assert _prepare(raw, {"us_stats": {"mode": "위험"}}).iloc[0]["게이트상태"] == GATE_DEFENSE
    assert raw.iloc[0]["게이트상태"] == GATE_EXECUTABLE


def test_existing_flow_wait_and_missing_analyst_are_not_invented_consensus():
    raw = pd.DataFrame([_candidate()])
    guard = {"us_stats": {"mode": "정상"}}
    view = _prepare(raw, guard, flow="눌림대기")
    assert view.iloc[0]["게이트상태"] == GATE_WAIT
    assert view.iloc[0]["애널목표상태"] == "lookup_error"
    assert pd.isna(view.iloc[0]["애널목표Upside값"])
    assert view.iloc[0]["애널목표Upside"] == "-"
    assert _prepare(raw, guard).iloc[0]["게이트상태"] == GATE_EXECUTABLE


def test_analyst_uses_existing_loader_once_and_preserves_price_grade():
    calls = []

    def analyst(ticker):
        calls.append(ticker)
        return {"ok": True, "data": {"targetMeanPrice": 120}, "source": "fixture", "asof": "2026-10-28"}

    view = _prepare(pd.DataFrame([_candidate(), _candidate()]), analyst=analyst)
    assert calls == ["MSFT"]
    assert view["애널목표Upside값"].tolist() == pytest.approx([20, 20])
    assert view["현재가"].eq("$100.00").all()
    assert view["후보품질"].eq("A").all()


def _inputs():
    return dict(items=[dict(ticker="MSFT", name="Microsoft", qty=2, avg_price=100,
                            target_weight=10, is_etf=False, asset_class="us_stock", bucket="manual")],
                mode="개인모드", fin_score_map={"MSFT": 3},
                holdings=pd.DataFrame([{"티커": "MSFT", "보유량": 2, "매입가": 100, "현재비중": 5, "목표비중": 10}]),
                account_inputs={"krw_cash": 300, "usd_cash": 100},
                owner="fixture", logic_version="fixture")


@pytest.mark.parametrize("field,value", [("qty", 0), ("avg_price", 200), ("target_weight", 0),
                                         ("bucket", "core"), ("asset_class", "us_etf"), ("is_etf", True)])
def test_signature_tracks_same_ticker_inputs(field, value):
    before = _inputs()
    after = deepcopy(before)
    after["items"][0][field] = value
    assert build_dashboard_signature(**before) != build_dashboard_signature(**after)


@pytest.mark.parametrize("part", ["holdings", "fin_score_map", "krw_cash", "usd_cash", "owner", "logic_version"])
def test_signature_tracks_runtime_and_holdings_context(part):
    before = _inputs()
    after = deepcopy(before)
    if part == "holdings":
        after[part].loc[0, "보유량"] = 12
    elif part == "fin_score_map":
        after[part]["MSFT"] = 4
    elif part in {"owner", "logic_version"}:
        after[part] = "changed"
    else:
        after["account_inputs"][part] = 900
    assert build_dashboard_signature(**before) != build_dashboard_signature(**after)


def test_signature_normalizes_missing_values_and_reordering():
    args = _inputs()
    args["items"].append(dict(args["items"][0], ticker="MAGS"))
    args["holdings"] = pd.concat([args["holdings"], args["holdings"].assign(티커="MAGS")])
    args["account_inputs"]["optional"] = float("nan")
    reordered = deepcopy(args)
    reordered["items"].reverse()
    reordered["holdings"] = reordered["holdings"].iloc[::-1]
    reordered["account_inputs"]["optional"] = None
    reordered["holdings"]["현재비중"] = 99
    reordered["holdings"]["원화환산"] = 9999999
    assert build_dashboard_signature(**args) == build_dashboard_signature(**reordered)
    frame = pd.DataFrame([_candidate()])
    assert dashboard_cache_matches(frame, "same", "same")
    assert not dashboard_cache_matches(frame, None, "same")
    assert not dashboard_cache_matches(frame, "old", "new")
    assert not dashboard_cache_matches(pd.DataFrame(), "same", "same")


def test_actual_holdings_merge_includes_mags_ram_without_flow_nominations():
    fn = next(n for n in _tree().body if isinstance(n, ast.FunctionDef) and n.name == "build_today_queue_items")
    tickers = ["379810.KS", "379800.KS", "418660.KS", "CIBR", "SOXL", "0167A0.KS", "BITX", "0025N0.KS", "MAGS", "RAM"]
    holdings = pd.DataFrame([{"티커": ticker, "자산명": ticker, "보유량": 1, "매입가": 100,
                              "현재비중": 5, "목표비중": 10, "bucket": "manual", "is_etf": True}
                             for ticker in tickers])
    env = dict(pd=pd, holdings_table=holdings, sanitize_watchlist_item=lambda item: dict(item),
               sanitize_ticker_value=sanitize_ticker_value, normalize_ticker=normalize_ticker,
               clean_float=clean_float, infer_bucket=lambda ticker, bucket: bucket,
               is_reserve_or_cash_bucket=lambda bucket: bucket in {"reserve", "cash"},
               sanitize_asset_name=lambda name, ticker: name, is_fin_score_exempt_asset=lambda *args: True,
               infer_asset_class_for_ticker=lambda ticker, asset_class: asset_class)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(APP), "exec"), env)
    items = env["build_today_queue_items"]([{"ticker": "CIBR", "qty": 0}, {"ticker": "WATCH"}])
    assert set(item["ticker"] for item in items) == set(tickers) | {"WATCH"}
    assert next(item for item in items if item["ticker"] == "CIBR")["qty"] == 1
    assert len(items) == 11


class State(dict):
    __getattr__ = dict.__getitem__


@pytest.mark.parametrize("cached,valid,fail", [(False, False, False), (True, False, False), (True, True, False), (True, False, True)])
def test_real_dashboard_branch_invalidates_recomputes_and_keeps_raw(cached, valid, fail):
    tree = _tree()
    dashboard = next(n for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) == "main_page == 'dashboard'")
    start = next(i for i, n in enumerate(dashboard.body) if isinstance(n, ast.If) and ast.unparse(n.test) == "_run_dash or not _dash_valid")
    end = next(i for i in range(start + 1, len(dashboard.body)) if isinstance(dashboard.body[i], ast.If)
               and ast.unparse(dashboard.body[i].test) == "summary_df.empty")
    raw = pd.DataFrame([_candidate()])
    state = State(fin_score_map={"MSFT": 3})
    if cached:
        state.update(raw=raw.copy(), sig="old", last="old")
    calls = []

    def compute(scores, mode, items):
        calls.append(items)
        assert "raw" not in state and "sig" not in state and "last" not in state
        if fail:
            raise RuntimeError("fixture failure")
        state.fin_score_map["MSFT"] = 4
        return raw.copy()

    items = ({"ticker": "MSFT"}, {"ticker": "MAGS"}, {"ticker": "RAM"})
    env = dict(st=SimpleNamespace(session_state=state, spinner=lambda *args: nullcontext()),
               _DASH_KEY="raw", _DASH_SIG_KEY="sig", _DASH_LAST_KEY="last", _run_dash=False,
               _dash_valid=valid, _dash_cached=raw.copy() if cached else pd.DataFrame(),
               _dash_items=items, app_mode="fixture", get_all_summary=compute,
               _current_dashboard_signature=lambda: str(state.fin_score_map["MSFT"]),
               _d3=SimpleNamespace(caption=lambda text: None), cached_dashboard_analyst_loader=cached_dashboard_analyst_loader,
               dedupe_dashboard_summary_df=lambda frame: frame.copy(),
               datetime=datetime, timezone=timezone, timedelta=timedelta,
               get_cached_today_market_flow_snapshot=lambda: {}, build_today_flow_shortlist_df=lambda snapshot: pd.DataFrame(),
               build_today_market_guard=lambda snapshot, summary: {"action": "신규매수 중단"},
               attach_today_flow_context=lambda frame, shortlist, **kwargs: frame,
               get_analyst_snapshot=lambda ticker: {"data": {}, "ok": False}, load_latest_price=lambda ticker: 100,
               prepare_dashboard_display=prepare_dashboard_display)
    code = compile(ast.Module(body=dashboard.body[start:end], type_ignores=[]), str(APP), "exec")
    if fail:
        with pytest.raises(RuntimeError, match="fixture failure"):
            exec(code, env)
        assert "raw" not in state and "sig" not in state
        return
    exec(code, env)
    assert calls == ([] if valid else [items])
    assert state["raw"].iloc[0]["게이트상태"] == GATE_EXECUTABLE
    assert env["summary_df"].iloc[0]["게이트상태"] == GATE_DEFENSE
    if not valid:
        assert state["sig"] == "4"


def test_dashboard_wiring_uses_holdings_builder_and_cached_providers():
    tree = _tree()
    dashboard = next(n for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) == "main_page == 'dashboard'")
    source = ast.unparse(dashboard)
    assert "_dash_items = build_today_queue_items(tuple(st.session_state.watchlist))" in source
    assert "build_today_queue_items_with_flow_candidates" not in source
    assert "get_analyst_snapshot=_dash_analyst" in source
    assert "get_analyst_snapshot()" not in source
    assert "resolve_decision_runtime_inputs()" not in source
    assert "get_cached_today_market_flow_snapshot()" in source
    wrapper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_dashboard_group_summary")
    assert len(wrapper.body) == 2


def test_compact_table_separates_raw_candidates_gates_and_source_dates():
    frame = _prepare(pd.DataFrame([_candidate(가격자료기준일="2026-10-28", 가격반영="일봉 종가",
                                             지표마지막봉="2026-10-28", 수급자료기준="거래량 원자료",
                                             자료주의="", 계산시각="2026-10-29 10:00")]), {"action": "신규매수 중단"})
    primary, detail, counts = dashboard_tables(frame, "전체")
    assert counts["원시 후보 신호"] == 1 and counts["실행가능"] == 0
    assert primary.iloc[0]["가격자료기준일"] == "2026-10-28"
    assert primary.iloc[0]["가격반영"] == "일봉 종가"
    assert "후보품질" not in primary and "후보품질" in detail
    assert all(column in detail for column in ["지표마지막봉", "수급자료기준", "자료주의", "계산시각"])
    missing = dashboard_tables(pd.DataFrame([_candidate(계산시각="2026-10-29", 섹터RS기준일="2026-10-28")]), "전체")[0]
    assert missing.iloc[0]["가격자료기준일"] == "미확인"
    assert dashboard_tables(frame, "한국 ETF")[0].empty


def test_details_are_collapsed_and_fingerprint_registered():
    from stock_lab_core.report_build import _LOADED
    assert "stock_lab_core.dashboard_view" in _LOADED
    calls = []
    st = SimpleNamespace(columns=lambda n: [SimpleNamespace(metric=lambda *args: None) for _ in range(n)],
                         dataframe=lambda frame, **kwargs: calls.append(frame), info=lambda text: None,
                         expander=lambda label, **kwargs: calls.append(kwargs) or nullcontext())
    render_dashboard_group_summary(st, pd.DataFrame([_candidate()]), "전체")
    assert calls[1] == {"expanded": False}
    assert "후보품질" not in calls[0] and "기존 종합후보" in calls[2]
    assert "기업품질" in calls[0] and "🔥기술적 타점" in calls[0]


@pytest.mark.parametrize("age", [None, -1, 21600, 90000])
def test_display_cache_rejects_unknown_future_expired_analyst_without_fetch(age):
    now = datetime(2026, 10, 29, 3, tzinfo=timezone.utc)
    frame = pd.DataFrame([_candidate()])
    snapshot = {"ok": True, "data": {"targetMeanPrice": 200}}
    if age is not None:
        snapshot["fetched_at"] = (now - timedelta(seconds=age)).isoformat()
    frame.attrs["today_analyst_snapshots"] = {"MSFT": snapshot}
    loader = cached_dashboard_analyst_loader([frame], now=now)
    view = _prepare(frame, analyst=loader)
    assert view.iloc[0]["애널목표상태"] == "lookup_error"
    assert pd.isna(view.iloc[0]["애널목표Upside값"])


def test_display_cache_uses_fresh_observation_with_original_source_timestamp():
    now = datetime(2026, 10, 29, 3, tzinfo=timezone.utc)
    frame = pd.DataFrame([_candidate()])
    original = {"ok": True, "data": {"targetMeanPrice": 120}, "source": "fixture",
                "fetched_at": (now - timedelta(seconds=30)).isoformat(), "asof": "2026-10-28"}
    frame.attrs["today_analyst_snapshots"] = {"MSFT": original}
    loader = cached_dashboard_analyst_loader([frame], now=now)
    view = _prepare(frame, analyst=loader)
    assert view.iloc[0]["애널목표상태"] == "available"
    assert view.iloc[0]["애널목표기준일"] == "2026-10-28"
    assert view.iloc[0]["애널목표조회시각"] == original["fetched_at"]
    assert loader("UNKNOWN")["ok"] is False
