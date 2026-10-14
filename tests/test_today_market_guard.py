"""Exercise the actual macro-table/market-guard boundary without network I/O."""

import pandas as pd
import pytest


@pytest.fixture
def guard_app(app_module, monkeypatch):
    app = app_module

    def benchmark_row(ticker, label, region):
        return {
            "지역": region, "시장": label, "티커": ticker, "데이터": "정상",
            "1일": 0.005, "5일": 0.01, "20일": 0.02,
            "20일고점대비": -0.01, "MA20": "상회", "MA50": "상회", "연속하락": 0,
        }

    monkeypatch.setattr(app, "_build_today_benchmark_guard_rows", lambda: [
        benchmark_row(ticker, label, region)
        for ticker, label, region in app.TODAY_MARKET_GUARD_BENCHMARKS
    ])
    monkeypatch.setattr(app, "build_macro_event_risk_table", lambda: (pd.DataFrame(), 0.0, 0))
    monkeypatch.setattr(app, "final_macro_risk", 1.5)
    return app


@pytest.mark.parametrize("with_summary", [False, True])
@pytest.mark.parametrize("macro_data,pressure,relief,expected", [
    ({}, 0, 0, "미수집: 10Y 금리, 환율, VIX, MOVE, 유가"),
    ({
        "10Y 금리": {"val": 4.0}, "환율": {"val": 1350}, "VIX": {"val": 19},
        "MOVE": {"val": 95}, "유가": {"val": 80},
    }, 0, 0, "부담: 확인된 항목 없음 · 완화: 확인된 항목 없음"),
    ({
        "10Y 금리": {"val": 5.27}, "환율": {"val": 1340},
        "VIX": {"val": 15.01, "icon": "🔻"}, "MOVE": {"val": 105.2},
        "유가": {"val": 90.23, "icon": "🔻"},
    }, 3, 2, "부담: 10Y 금리, MOVE · 완화: VIX, 유가"),
])
def test_guard_uses_macro_labels_not_numeric_counts(
    guard_app, monkeypatch, with_summary, macro_data, pressure, relief, expected,
):
    app = guard_app
    monkeypatch.setattr(app, "macro_res", macro_data)
    summary = pd.DataFrame([{"티커": "TEST", "판정코드": "HARD_BLOCK_OVERWEIGHT"}]) if with_summary else pd.DataFrame()

    guard = app.build_today_market_guard({"flow_df": pd.DataFrame()}, summary)

    assert guard["macro_pressure"] == pressure
    assert guard["macro_relief"] == relief
    assert isinstance(guard["macro_pressure"], int)
    assert isinstance(guard["macro_relief"], int)
    assert guard["score"] == (1 if pressure >= 2 else 0)
    assert expected in guard["macro_note"]
    assert guard["macro_note"].endswith("통합 시장판정: " + guard["mode"])
    assert "신규매수는 정찰·분할" not in guard["macro_note"]
    if macro_data:
        assert "미수집:" not in guard["macro_note"]


def test_risk_mode_does_not_publish_independent_buy_advice(guard_app, monkeypatch):
    app = guard_app
    monkeypatch.setattr(app, "macro_res", {"10Y 금리": {"val": 5.27}})
    snapshot = {"flow_df": pd.DataFrame({
        "구분": ["섹터"], "3개월수익률": [-10.0], "가속도": [-1.0],
    })}
    original_stats = app._today_benchmark_guard_stats

    def defensive_stats(frame):
        stats = original_stats(frame)
        return {**stats, "score": 5, "mode": "방어"}

    monkeypatch.setattr(app, "_today_benchmark_guard_stats", defensive_stats)
    guard = app.build_today_market_guard(snapshot, pd.DataFrame())

    assert guard["mode"] == "위험"
    assert "신규매수 중단" in guard["action"]
    assert "통합 시장판정: 위험" in guard["macro_note"]
    assert "정찰·분할" not in guard["macro_note"]
    assert "정찰·분할" in guard["macro_independent_note"]


@pytest.mark.parametrize("with_watchlist", [False, True])
def test_pending_today_queue_builds_real_guard(guard_app, monkeypatch, with_watchlist):
    app = guard_app
    items = ({"ticker": "SPY", "name": "S&P500", "bucket": "core"},) if with_watchlist else ()
    monkeypatch.setattr(app.st, "session_state", {"watchlist": list(items)})
    monkeypatch.setattr(app, "macro_res", {"10Y 금리": {"val": 5.27}})
    monkeypatch.setattr(app, "get_cached_today_market_flow_snapshot", lambda: {})
    monkeypatch.setattr(app, "build_today_queue_items_with_flow_candidates", lambda *args: (items, ()))
    monkeypatch.setattr(app, "build_today_queue_signature", lambda *args, **kwargs: "test")
    monkeypatch.setattr(app, "load_today_queue_summary_snapshot", lambda **kwargs: (pd.DataFrame(), "", ""))
    monkeypatch.setattr(app, "get_cash_available_for_dca", lambda mode: 0)
    monkeypatch.setattr(app, "get_reserve_available_for_crash_buy", lambda mode: 0)
    monkeypatch.setattr(app, "render_data_basis_caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "render_today_candidate_tools", lambda *args, **kwargs: None)
    rendered = []
    monkeypatch.setattr(app, "render_today_unified_briefing_panel", lambda summary, guard, **kwargs: rendered.append((summary, guard, kwargs)))

    app.render_today_queue_tab("자유모드")

    assert len(rendered) == 1
    summary, guard, options = rendered[0]
    assert summary.empty and options["pending"]
    assert guard["macro_pressure"] == 2
    assert "부담: 10Y 금리" in guard["macro_note"]
