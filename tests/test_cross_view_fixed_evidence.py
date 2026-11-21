"""Three fixed workflow handoffs; no provider calls, new scores or account writes."""

from copy import deepcopy
import math
import socket

import pandas as pd
import pytest

from stock_lab_core.decision_brief import build_decision_brief
from stock_lab_core.decision_workflow import build_decision_workflow, attach_market_execution_context
from stock_lab_core.execution_context import prepare_execution_context
from stock_lab_core.execution_gate import apply_execution_gate_columns
from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.portfolio_holding_review import (
    PRECISION_KEY, build_holding_review, capture_precision_review,
)
from stock_lab_core.portfolio_signal_cache import select_portfolio_signals
from tests.test_decision_workflow import _candidate


@pytest.fixture
def fixed_workflow(app_module, monkeypatch):
    from stock_lab_core import data_freshness

    def no_network(*args, **kwargs):
        raise AssertionError("fixed workflow must not fetch")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(data_freshness, "session_reference", lambda *a, **kw: {
        "completed": "2026-11-20", "active": "", "source": "fixed fixture",
    })
    benchmark = {"sector_rs_label": "-", "sector_bench": "", "sector_rs_asof": ""}
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: dict(benchmark))
    monkeypatch.setattr(app_module, "get_benchmark_display_name", lambda value: value)
    monkeypatch.setattr(app_module, "get_cached_today_market_flow_snapshot", lambda: {})
    monkeypatch.setattr(app_module, "build_today_flow_shortlist_df", lambda snap: pd.DataFrame())
    guard = {"action": "신규매수 중단"}
    monkeypatch.setattr(app_module, "build_today_market_guard", lambda *a: dict(guard))
    monkeypatch.setattr(app_module, "attach_today_flow_context", lambda frame, shortlist, **kw: frame.copy(deep=True))
    monkeypatch.setattr(app_module, "attach_today_analyst_context", lambda frame, **kw: frame.copy(deep=True))
    monkeypatch.setattr(app_module, "build_today_analyst_upside_map", lambda frame: {})
    monkeypatch.setattr(app_module, "usdkrw", 1400., raising=False)
    return app_module, guard


@pytest.mark.parametrize("ticker,is_etf,code,label,current,target", [
    ("GOOGL", False, "STOCK_CRISIS_CAUSE_CHECK", "🚫개별주 위기: 원인점검", 0., 0.),
    ("379810.KS", True, "HARD_BLOCK_OVERWEIGHT", "🛑하드차단: 비중 초과", 31.623, 25.),
    ("SOXL", True, "LEVERAGED_RECOVERY_DCA_BLOCK", "레버리지 추매중단", 1.2, 10.),
])
def test_fixed_decision_and_context_survive_three_views(fixed_workflow, ticker, is_etf, code, label, current, target):
    app, guard = fixed_workflow
    decision = _candidate(
        dec=label, decision_code=code, decision_group="caution", current_w=current, target_w=target,
        input_basis={"가격입력ID": "synthetic-" + ticker, "가격자료기준일": "2026-11-20",
                     "계산시각": "2026-11-21 09:00:00 KST", "재무자료기간": "fixture-period"},
    )
    before = deepcopy(decision)
    # Same adapters and already-frozen financial/market/price inputs as precision.
    raw = build_decision_workflow("Fixture", ticker, decision, is_etf=is_etf, has_pos=True,
                                  is_leveraged_product_fn=app.is_leveraged_or_inverse_product)
    raw.update(현재비중=round(current, 2), 목표비중=round(target, 2))
    today = prepare_execution_context(
        pd.DataFrame([raw]), snapshot={}, flow_shortlist=pd.DataFrame(), market_guard=guard,
        attach_flow=app.attach_today_flow_context, attach_market=attach_market_execution_context,
        apply_gate=apply_execution_gate_columns, upside_map={},
    )
    precision = app.build_precision_execution_workflow("Fixture", ticker, decision, is_etf, "fixture", True)
    for key, value in today.iloc[0].items():
        actual = precision[key]
        assert (pd.isna(actual) and pd.isna(value)) or actual == value, key
    today.attrs.update(portfolio_signal_context="synthetic", portfolio_signal_at="2026-11-21T00:00:00Z")
    state = {"portfolio_today_signal_df": today}
    final = {"final_label": "매수 금지", "execution_allowed": False, "block_count": 2, "core_missing_ids": []}
    capture_precision_review(state, "synthetic", ticker, dict(decision, execution_workflow=precision), final,
                             captured_at="2026-11-21T00:00:00Z")
    signals = select_portfolio_signals(state, "synthetic", detailed=True)
    for key in ("판정코드", "후보품질", "후보점수", "게이트상태", "게이트근거", "가격입력ID", "현재비중", "목표비중"):
        assert signals.iloc[0][key] == precision[key]
    _, details = build_holding_review(pd.DataFrame([{"티커": ticker, "보유량": 1}]), signals,
                                      state[PRECISION_KEY], "synthetic")
    detail = next(iter(details.values()))
    assert detail["ready"] == build_execution_readiness(precision, final)
    assert not detail["ready"]["execution_allowed"]
    brief = build_decision_brief(precision, source="정밀", final_check=final)
    assert brief["layers"][-1]["확인"].startswith(f"현재 {current:.1f}% / 목표 {target:.1f}%")
    assert decision == before


@pytest.mark.parametrize("current,target", [(None, None), (float("nan"), float("inf")), (0., 0.)])
def test_weights_are_display_evidence_after_gate_not_permission(fixed_workflow, current, target):
    app, _ = fixed_workflow
    decision = _candidate(current_w=current, target_w=target)
    before = deepcopy(decision)
    out = app.build_precision_execution_workflow("Fixture", "GOOGL", decision, False, "us_stock", False)
    assert out["게이트상태"] == "방어우선" and out["게이트근거"] == "시장방어: 신규매수 중단"
    text = build_decision_brief(out, source="정밀")["layers"][-1]["확인"]
    assert ("현재 0.0% / 목표 0.0%" if current == 0 else "현재 미확인 / 목표 미확인") in text
    for key in decision:
        assert decision[key] is before[key] or decision[key] == before[key] or (
            isinstance(decision[key], float) and math.isnan(decision[key]) and math.isnan(before[key]))
