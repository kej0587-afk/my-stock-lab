"""Frozen-input parity across Today, board and precision (no provider traffic)."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.dashboard_view import prepare_dashboard_display
from stock_lab_core.decision_workflow import attach_market_execution_context, build_decision_workflow
from stock_lab_core.execution_context import prepare_execution_context
from stock_lab_core.execution_gate import apply_execution_gate_columns
from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.today_enrichment import attach_today_analyst_context, build_today_analyst_upside_map


REPRESENTATIVE_TICKERS = ["379810.KS", "379800.KS", "418660.KS", "CIBR", "SOXL", "0167A0.KS",
                          "BITX", "0025N0.KS", "MAGS", "RAM", "GOOGL"]


def _no_price_lookup(*args):
    pytest.fail("Frozen price must be reused")


@pytest.mark.parametrize("ticker", REPRESENTATIVE_TICKERS)
@pytest.mark.parametrize("mode,target", [("정상", 120), ("위험", 120), ("정상", 90), ("", None)])
def test_held_views_preserve_frozen_dates_decisions_and_gates(app_module, monkeypatch, ticker, mode, target):
    app = app_module
    snapshot = {"fixture_id": "one-snapshot"}
    guard = {"us_stats": {"mode": mode}, "kr_stats": {"mode": mode}}
    basis = {"가격자료기준일": "2026-11-03", "지표마지막봉": "2026-11-03",
             "가격반영": "확정 종가", "계산시각": "2026-11-04 08:00 KST"}
    decision = dict(grade="A", t_score=8, dec="신규진입: 대장주 포착", decision_code="NEW_ENTRY_LEADER",
                    decision_group="buyish", cur_p=100, rr_stop=90, rr_target=120,
                    rr_ratio=2.0, ma20=98, atr=5, input_basis=basis, current_w=3, target_w=5)
    before = deepcopy(decision)

    def flow(frame, shortlist, *, snapshot):
        assert snapshot is frozen_snapshot
        frame["돈흐름_판정"] = "관찰"
        frame["돈흐름기준일"] = "2026-11-03"
        return frame

    def analyst(t):
        return {"ok": target is not None, "status": "ok" if target else "lookup_error",
                "data": {"targetMeanPrice": target}, "source": "fixture", "asof": "2026-11-03"}

    frozen_snapshot = snapshot
    monkeypatch.setattr(app, "get_auto_benchmark_info", lambda *a: {})
    monkeypatch.setattr(app, "get_benchmark_display_name", lambda t: t)
    monkeypatch.setattr(app, "get_cached_today_market_flow_snapshot", lambda: snapshot)
    monkeypatch.setattr(app, "build_today_flow_shortlist_df", lambda s: pd.DataFrame())
    monkeypatch.setattr(app, "build_today_market_guard", lambda *a: guard)
    monkeypatch.setattr(app, "attach_today_flow_context", flow)
    monkeypatch.setattr(app, "get_analyst_snapshot", analyst)
    monkeypatch.setattr(app, "load_latest_price", _no_price_lookup)
    is_etf = ticker != "GOOGL"
    precision = app.build_precision_execution_workflow(ticker, ticker, decision, is_etf, "", True)
    raw = build_decision_workflow(ticker, ticker, decision, is_etf=is_etf, has_pos=True,
                                 is_leveraged_product_fn=app.is_leveraged_or_inverse_product)
    frame = pd.DataFrame([{**raw, **basis, "종목명": ticker, "현재가원값": 100}])
    original = deepcopy(frame)
    board = prepare_dashboard_display(
        frame, snapshot=snapshot, flow_shortlist=pd.DataFrame(), market_guard=guard,
        attach_flow_context=flow, get_analyst_snapshot=analyst, load_latest_price=_no_price_lookup,
    )
    enriched = attach_today_analyst_context(frame, get_analyst_snapshot=analyst, load_latest_price=_no_price_lookup)
    upside = build_today_analyst_upside_map(enriched)
    # Before-refactor Today sequence remains the independent comparison oracle.
    expected = apply_execution_gate_columns(
        attach_market_execution_context(flow(enriched.copy(), pd.DataFrame(), snapshot=snapshot), guard),
        upside_value_map=upside,
    )
    today = prepare_execution_context(
        enriched, snapshot=snapshot, flow_shortlist=pd.DataFrame(), market_guard=guard,
        attach_flow=flow, attach_market=attach_market_execution_context,
        apply_gate=apply_execution_gate_columns, upside_map=upside,
    )
    pd.testing.assert_frame_equal(today, expected)
    keys = [*basis, "돈흐름기준일", "게이트상태", "게이트근거", "판정코드", "후보품질", "후보점수"]
    for row in (today.iloc[0], board.iloc[0]):
        for key in keys:
            assert row[key] == precision[key], (ticker, key)
        readiness = build_execution_readiness(row.to_dict(), {"execution_allowed": False,
            "block_count": 2, "core_missing_ids": [], "final_label": "매수 금지"})
        assert readiness["execution_allowed"] is False
    pd.testing.assert_frame_equal(frame, original)
    assert decision == before


@pytest.mark.parametrize("error", [TypeError, ValueError])
def test_flow_body_failure_is_not_retried_without_snapshot(error):
    calls = []
    def broken(frame, shortlist, *, snapshot=None):
        calls.append(snapshot)
        raise error("provider body failure")
    with pytest.raises(error, match="provider body failure"):
        prepare_execution_context(pd.DataFrame([{"티커": "RAM"}]), snapshot={"id": 1},
            flow_shortlist=pd.DataFrame(), market_guard={}, attach_flow=broken,
            attach_market=lambda *a: pytest.fail("Must not proceed"), apply_gate=None)
    assert calls == [{"id": 1}]


def test_legacy_flow_adapter_and_empty_frame_keep_contract():
    result = prepare_execution_context(pd.DataFrame([{"티커": "RAM"}]), snapshot={},
        flow_shortlist=pd.DataFrame(), market_guard={}, attach_flow=lambda f, s: f,
        attach_market=lambda f, g: f, apply_gate=lambda f, **kw: f)
    assert result.iloc[0]["티커"] == "RAM"
    empty = pd.DataFrame()
    empty.attrs["source"] = {"id": "frozen"}
    out = prepare_execution_context(empty, snapshot={}, flow_shortlist=None, market_guard=None,
        attach_flow=None, attach_market=None, apply_gate=None)
    out.attrs["source"]["id"] = "changed"
    assert empty.attrs["source"]["id"] == "frozen"


def test_keyword_adapter_receives_frozen_snapshot():
    calls = []
    def adapter(frame, shortlist, **kwargs):
        calls.append(kwargs)
        return frame
    snapshot = {"id": "one"}
    prepare_execution_context(pd.DataFrame([{"티커": "RAM"}]), snapshot=snapshot,
        flow_shortlist=None, market_guard={}, attach_flow=adapter,
        attach_market=lambda f, g: f, apply_gate=lambda f, **kw: f)
    assert calls == [{"snapshot": snapshot}]
    assert calls[0]["snapshot"] is snapshot


def test_precision_evaluation_order_remains_flow_guard_analyst_gate():
    calls = []
    def step(name, frame):
        calls.append(name)
        return frame
    prepare_execution_context(pd.DataFrame([{"티커": "RAM"}]), snapshot={},
        flow_shortlist=None, market_guard=lambda: step("guard", {}),
        attach_flow=lambda f, s: step("flow", f), attach_market=lambda f, g: step("market", f),
        enrich_analyst=lambda f: step("analyst", f), build_upside_map=lambda f: step("upside", {}),
        apply_gate=lambda f, **kw: step("gate", f))
    assert calls == ["flow", "guard", "market", "analyst", "upside", "gate"]
