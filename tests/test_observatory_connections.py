"""Cross-view wiring preserves source periods and common execution restrictions."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.execution_gate import build_execution_gate


@pytest.mark.parametrize("market", ["한국", "미국"])
def test_global_stop_cannot_be_overridden_by_normal_region(app_module, market):
    guard = {"mode": "전시장 비상", "action": "신규매수 중단",
             "kr_stats": {"mode": "정상"}, "us_stats": {"mode": "정상"}}
    before = deepcopy(guard)
    assert app_module._flow_stat_market_mode(guard, market) == "전시장 비상"
    assert guard == before


@pytest.mark.parametrize("state", ["자료부족", "상위 시간대 자료부족", "상위시간대 조회 실패"])
def test_unknown_upper_timeframes_are_not_passes(state):
    row = {"판정분류": "buyish", "RR값": 2.5, "데이터상태": "OK", "상위시간대상태": state}
    assert build_execution_gate(row)["게이트상태"] == "데이터확인"


def test_flow_context_preserves_original_source_dates(app_module, monkeypatch):
    app = app_module
    frame = pd.DataFrame([{"Ticker": "MSFT", "_검토키": "msft", "_flow_context_priority": 1,
                           "돈흐름점수": 3, "기준일": "2026-10-30", "source_asof": "2026-10-30"}])
    monkeypatch.setattr(app, "_normalize_today_flow_context_frame", lambda *args: frame.copy())
    result = app.build_today_flow_context_df(snapshot={}, flow_shortlist_df=frame)
    assert result.iloc[0]["기준일"] == "2026-10-30"
    assert result.iloc[0]["source_asof"] == "2026-10-30"


def test_chart_scorecard_receives_extended_history_and_same_session_benchmark(app_module, monkeypatch):
    import stock_lab_core.chart_scorecard as module
    app = app_module
    full = pd.DataFrame({"Close": range(1, 601)}, index=pd.bdate_range(end="2026-10-30", periods=600))
    seen = {}
    def render(st, frame, *, benchmark=None, **kwargs):
        seen.update(frame=frame, benchmark=benchmark, **kwargs)
    monkeypatch.setattr(module, "render_chart_scorecard", render)
    monkeypatch.setattr(app, "load_price_df", lambda *args: full.copy())
    monkeypatch.setattr(app, "get_rs_benchmark", lambda *args: "SPY")
    monkeypatch.setattr(app, "fetch_valuation_snapshot", lambda *args: {
        "data": {"revenueGrowth": .02}, "sources": ["fixture"]})
    monkeypatch.setattr(app.st, "caption", lambda *args: None)
    result = app.render_precision_scorecard(full.tail(200), "MSFT", {}, False)
    assert len(seen["frame"]) == 600 and len(seen["benchmark"]) == 600
    assert result["data"]["revenueGrowth"] == .02
    assert seen["info"] == result["data"] and seen["source"] == result["source"]
