"""Guard data-quality fixes, without changing risk bands or trade permission."""

from contextlib import nullcontext
from copy import deepcopy
import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.market_basis import positive_observation_fraction
from stock_lab_core.market_guard_explanation import guard_explanation_lines


@pytest.mark.parametrize("values,ratio,valid,missing", [
    ([1, 2, np.nan, None, float("inf"), "bad"], 1.0, 2, 4),
    ([0, -1, np.nan], 0.0, 2, 1),
    (["1", "-1", "0", True, False], 1/3, 3, 2),
    ([None, np.nan, -np.inf], None, 0, 3),
    ([], None, 0, 0),
])
def test_fraction_uses_observed_values_including_real_zero(values, ratio, valid, missing):
    original = list(values)
    result = positive_observation_fraction(values)
    assert result["valid"] == valid and result["missing"] == missing
    assert np.isnan(result["fraction"]) if ratio is None else result["fraction"] == pytest.approx(ratio)
    assert repr(values) == repr(original)


def test_nullable_numeric_missing_values_are_counted_as_missing():
    result = positive_observation_fraction(pd.Series([1, pd.NA, 0], dtype="Float64"))
    assert result == {"fraction": .5, "valid": 2, "missing": 1}


@pytest.fixture
def guard_app(app_module, monkeypatch):
    app = app_module
    rows = [{"지역": region, "시장": label, "티커": ticker, "데이터": "정상",
             "1일": .01, "5일": .02, "20일": .03, "MA20": "상회", "MA50": "상회", "연속하락": 0}
            for ticker, label, region in app.TODAY_MARKET_GUARD_BENCHMARKS]
    monkeypatch.setattr(app, "_build_today_benchmark_guard_rows", lambda: deepcopy(rows))
    monkeypatch.setattr(app, "build_macro_event_risk_table", lambda: (pd.DataFrame(), 0.0, 0))
    monkeypatch.setattr(app, "macro_res", {})
    monkeypatch.setattr(app, "final_macro_risk", 0.0)
    return app


def test_missing_flow_does_not_create_three_points_of_fabricated_weakness(guard_app):
    frame = pd.DataFrame({"구분": ["섹터"] * 10, "3개월수익률": [1, 2] + [np.nan] * 8,
                          "가속도": [1, 2] + [np.nan] * 8})
    original = frame.copy(deep=True)
    guard = guard_app.build_today_market_guard({"flow_df": frame})
    assert guard["flow_breadth"] == guard["flow_accel"] == 1.0
    assert guard["flow_score"] == 0
    assert guard["flow_input_counts"] == {"rows": 10, "breadth_valid": 2, "breadth_missing": 8,
                                          "accel_valid": 2, "accel_missing": 8}
    pd.testing.assert_frame_equal(frame, original)
    explanation = "\n".join(guard_explanation_lines(guard))
    assert "3M 2/10개" in explanation and "3M 결측 8개" in explanation


def test_all_missing_is_unavailable_not_zero_percent_weak(guard_app):
    guard = guard_app.build_today_market_guard({"flow_df": pd.DataFrame({
        "구분": ["섹터", "섹터"], "3개월수익률": [None, np.nan], "가속도": [np.inf, "unknown"]})})
    assert np.isnan(guard["flow_breadth"]) and np.isnan(guard["flow_accel"])
    assert guard["flow_score"] == 0
    assert guard["flow_input_counts"]["breadth_valid"] == 0


def test_missing_columns_and_macro_rows_are_not_flow_samples(guard_app):
    frame = pd.DataFrame({"구분": ["섹터", "매크로"], "3개월수익률": [1, -99]})
    guard = guard_app.build_today_market_guard({"flow_df": frame})
    assert guard["flow_breadth"] == 1.0 and np.isnan(guard["flow_accel"])
    assert guard["flow_input_counts"]["rows"] == 1
    assert guard["flow_input_counts"]["accel_missing"] == 1


@pytest.mark.parametrize("moves,accels,expected", [([1, 2], [1, 2], 0),
    ([0, -1], [0, -1], 3), ([1, 0, -1], [1, 2, -1], 2)])
def test_complete_observations_keep_existing_thresholds(guard_app, moves, accels, expected):
    guard = guard_app.build_today_market_guard({"flow_df": pd.DataFrame({
        "구분": ["섹터"] * len(moves), "3개월수익률": moves, "가속도": accels})})
    assert guard["flow_score"] == expected
    assert guard["flow_breadth"] == pytest.approx(np.mean(np.asarray(moves) > 0))
    assert guard["flow_input_counts"]["breadth_missing"] == 0


def test_oct30_benchmark_scores_and_matching_flow_ratios_reproduce_twelve(guard_app, monkeypatch):
    # Public benchmark observations; the 11 flow samples reproduce ratios only.
    observations = [
        (-.034849, .032510, "하회"), (-.038302, -.036331, "하회"),
        (-.038797, .044254, "하회"), (-.041449, -.042605, "하회"),
        (-.018175, -.005720, "하회"), (-.028556, -.019971, "하회"),
        (-.010933, -.008520, "하회"), (-.017729, -.005592, "하회"),
        (-.034739, -.019747, "하회"), (-.016478, .012983, "상회"),
    ]
    rows = [{"지역": region, "시장": label, "티커": ticker, "데이터": "정상",
             "1일": day, "5일": week, "MA20": ma20, "MA50": "하회", "연속하락": 2}
            for (ticker, label, region), (day, week, ma20)
            in zip(guard_app.TODAY_MARKET_GUARD_BENCHMARKS, observations)]
    monkeypatch.setattr(guard_app, "_build_today_benchmark_guard_rows", lambda: deepcopy(rows))
    monkeypatch.setattr(guard_app, "macro_res", {"10Y 금리": {"val": 4.93}, "MOVE": {"val": 100.2},
        "유가": {"val": 102.9, "icon": "🔺"}, "환율": {"val": 1338, "icon": "🔻"}, "VIX": {"val": 19.4}})
    monkeypatch.setattr(guard_app, "final_macro_risk", 1.8)
    monkeypatch.setattr(guard_app, "build_macro_event_risk_table", lambda: (pd.DataFrame(), .8, 2))
    frame = pd.DataFrame({"구분": ["섹터"] * 11, "3개월수익률": [1] * 2 + [-1] * 9,
                          "가속도": [1] * 4 + [-1] * 7})
    guard = guard_app.build_today_market_guard({"flow_df": frame})
    assert guard["kr_stats"]["score"] == 7 and guard["us_stats"]["score"] == 5
    assert guard["mode_score_parts"] == {"regional": 7, "flow": 2, "macro": 2, "event": 0, "combined": 1}
    assert guard["score"] == 12 and guard["mode"] == "위험"
    assert "신규매수 중단" in guard["action"]


@pytest.mark.parametrize("length", [25, 49, 50, 65])
def test_fifty_day_average_requires_fifty_observed_bars(guard_app, monkeypatch, length):
    close = pd.Series(np.arange(length, 0, -1), index=pd.bdate_range("2026-01-01", periods=length), dtype=float)
    monkeypatch.setattr(guard_app, "load_price_df", lambda *args: pytest.fail("No network needed"))
    row = guard_app._calc_today_benchmark_guard_row("TEST", "Test", "US", close=close)
    assert row["MA20"] == "하회"
    assert row["MA50"] == ("-" if length < 50 else "하회")


@pytest.mark.parametrize("whole,action,expect_stop", [
    ("위험", "신규매수 중단 · 현금/리스크 점검", True),
    ("전시장 비상", "국장·미장 신규/추매 중단", True),
    ("방어", "국장 주의/방어 · 미장 별도 타점", False),
])
def test_panel_respects_global_stop_before_describing_a_normal_region(guard_app, monkeypatch, whole, action, expect_stop):
    captions = []
    metric = SimpleNamespace(metric=lambda *args, **kwargs: None)
    ui = SimpleNamespace(markdown=lambda *args, **kwargs: None, columns=lambda *args: [metric] * 5,
                         caption=captions.append, expander=lambda *args, **kwargs: nullcontext(),
                         info=lambda *args: None, dataframe=lambda *args, **kwargs: None)
    monkeypatch.setattr(guard_app, "st", ui)
    guard_app.render_today_market_guard_panel({"mode": whole, "level": "danger", "action": action,
        "kr_stats": {"mode": "위험"}, "us_stats": {"mode": "정상"}})
    assert any("지역 모드가 정상이어도 신규매수 중단이 우선" in caption for caption in captions) is expect_stop
    assert any("미장 후보는 정밀관측소" in caption for caption in captions) is (not expect_stop)


@pytest.mark.parametrize("mode,action,stopped", [("위험", "", True), ("전시장 비상", "", True),
    ("방어", "신규매수 중단", True), ("방어", "", False)])
def test_brief_market_phase_does_not_offer_other_region_entries_during_global_stop(guard_app, monkeypatch, mode, action, stopped):
    monkeypatch.setattr(guard_app, "_build_market_regime_context", lambda frame: {})
    result = guard_app._brief_market_phase(pd.DataFrame(), {"mode": mode, "action": action,
        "kr_stats": {"mode": "방어", "avg_day": -.03}, "us_stats": {"mode": "정상", "avg_day": .01}})
    assert ("통합 신규매수 중단" in result["headline"]) is stopped
    assert ("별도 타점" in result["headline"]) is (not stopped)
    assert ("지역 모드가 정상이어도 신규매수 중단이 우선" in result["note"]) is stopped


def test_active_unified_briefing_renders_guard_coverage_and_stop_explanation():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "render_today_unified_briefing_panel")
    body = ast.unparse(function)
    assert "flow_input_counts" in body
    assert "돈흐름 유효 표본:" in body
    assert "기존 보유 전량 매도 지시가 아니며" in body
