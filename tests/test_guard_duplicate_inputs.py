"""Duplicate evidence must not create a second market or event shock."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.market_guard_explanation import guard_explanation_lines
from tests.test_market_guard_input_quality import guard_app


def benchmark(ticker, day=-.06):
    return {"티커": ticker, "지역": "US", "시장": ticker, "데이터": "정상",
            "1일": day, "5일": 0, "연속하락": 0, "MA20": "상회", "MA50": "상회"}


@pytest.mark.parametrize("tickers", [["SPY", "^GSPC"], ["^GSPC", "SPY"]])
def test_same_sp500_shock_is_not_two_panic_indices(guard_app, tickers):
    frame = pd.DataFrame([benchmark(ticker) for ticker in tickers])
    original = frame.copy(deep=True)
    result = guard_app._today_benchmark_guard_stats(frame)
    assert result["panic_day"] == 1
    assert result["mode"] != "비상"
    assert result["benchmark_tickers"] == ["^GSPC"]
    assert result["excluded_duplicate_tickers"] == ["SPY"]
    pd.testing.assert_frame_equal(frame, original)


def test_spy_remains_fallback_and_distinct_indices_still_count(guard_app):
    result = guard_app._today_benchmark_guard_stats(pd.DataFrame([benchmark("SPY"), benchmark("QQQ")]))
    assert result["panic_day"] == 2 and result["mode"] == "비상"
    result = guard_app._today_benchmark_guard_stats(pd.DataFrame([benchmark("^IXIC"), benchmark("QQQ")]))
    assert result["panic_day"] == 2


def test_event_uses_captured_macro_base_not_fresh_event_subtraction(guard_app, monkeypatch):
    monkeypatch.setattr(guard_app, "final_macro_risk", 4.5)
    monkeypatch.setattr(guard_app, "macro_res", {"VIX": {"val": 15,
        "guard_macro_base": 2.5, "guard_event_risk": 2.0, "as_of": "2026-11-12"}})
    monkeypatch.setattr(guard_app, "build_macro_event_risk_table", lambda: (pd.DataFrame(), 1.0, 1))
    result = guard_app.build_today_market_guard()
    assert result["macro_risk"] == 2.5
    assert result["macro_score"] == 0 and result["event_score"] == 1
    assert result["score"] == 1
    assert guard_app.final_macro_risk == 4.5  # Existing stock penalty is unchanged.
    assert result["macro_risk_input"]["event_included"] == 2.0


def test_legacy_snapshot_is_not_adjusted_using_an_unrelated_event(guard_app, monkeypatch):
    monkeypatch.setattr(guard_app, "final_macro_risk", 4.5)
    result = guard_app.build_today_market_guard()
    assert result["macro_risk"] == 4.5
    assert result["macro_risk_input"]["status"] == "legacy_unverified"


def test_suppressed_points_are_not_displayed_as_applied():
    guard = {"score": 5, "mode_score_parts": {"regional": 5, "flow": 0, "macro": 0, "event": 0, "combined": 0},
             "macro_score": 1, "event_score": 1, "macro_pressure": 2, "macro_risk": 1, "event_risk": 1}
    original = deepcopy(guard)
    lines = "\n".join(guard_explanation_lines(guard))
    assert "원점수 1 / 실제 반영 0" in lines
    assert "지역 5 이상에서는 원점수 1은 직접 반영하지 않음" in lines
    assert guard == original


def test_current_screen_nine_is_not_forced_into_normal(guard_app, monkeypatch):
    rows = [benchmark(ticker, .01) | {"지역": region, "MA20": "하회", "MA50": "하회"}
            for ticker, _, region in guard_app.TODAY_MARKET_GUARD_BENCHMARKS]
    monkeypatch.setattr(guard_app, "_build_today_benchmark_guard_rows", lambda: rows)
    monkeypatch.setattr(guard_app, "macro_res", {"10Y 금리": {"val": 5.1,
        "guard_macro_base": 0, "guard_event_risk": 1, "as_of": "2026-11-12"}})
    monkeypatch.setattr(guard_app, "final_macro_risk", 1.0)
    monkeypatch.setattr(guard_app, "build_macro_event_risk_table", lambda: (pd.DataFrame(), 1.0, 1))
    flow = pd.DataFrame({"구분": ["섹터"] * 99, "3개월수익률": [1] * 15 + [-1] * 83 + [None],
                         "가속도": [1] * 30 + [-1] * 67 + [None] * 2,
                         "기준일": ["2026-11-12"] * 99})
    guard = guard_app.build_today_market_guard({"flow_df": flow})
    assert guard["mode_score_parts"] == {"regional": 4, "flow": 3, "macro": 1, "event": 1, "combined": 0}
    assert guard["score"] == 9 and guard["mode"] == "위험"
    assert guard["input_dates"]["flow"] == ["2026-11-12"]


@pytest.mark.parametrize("bad", [None, float("nan"), True, "2"])
def test_untrusted_or_inconsistent_macro_decomposition_is_not_subtracted(bad):
    from stock_lab_core.market_basis import guard_macro_input
    data = {"one": {"guard_macro_base": 2, "guard_event_risk": 1},
            "two": {"guard_macro_base": bad, "guard_event_risk": 1}}
    assert guard_macro_input(data, 3)["status"] == "legacy_unverified"


def test_macro_analysis_keeps_legacy_penalty_and_attaches_same_snapshot_base(guard_app, monkeypatch):
    from stock_lab_core.market_basis import guard_macro_input
    close = pd.Series([5.0] * 25, index=pd.bdate_range("2026-10-01", periods=25))
    data = pd.concat({"^TNX": pd.DataFrame({"Close": close})}, axis=1)
    monkeypatch.setattr(guard_app.yf, "download", lambda *args, **kwargs: data)
    monkeypatch.setattr(guard_app, "build_macro_event_risk_table", lambda: (pd.DataFrame(), 2.0, 1))
    guard_app.get_macro_analysis.clear()
    results, risk, penalty, move = guard_app.get_macro_analysis()
    assert risk == 3.5 and penalty == 1.5
    assert guard_macro_input(results, risk)["risk"] == 1.5
    assert results["10Y 금리"]["as_of"] == str(close.index[-1].date())
    guard_app.get_macro_analysis.clear()


def test_only_exact_reviewed_app_edits_differ_from_parent():
    import ast
    from pathlib import Path
    import subprocess
    from tests.guard_input_ast_contract import before_guard_input_repair
    root = Path(__file__).resolve().parents[1]
    old = subprocess.check_output(['git', 'show', 'a7e34691:app.py'], cwd=root, encoding='utf-8-sig')
    new = (root / 'app.py').read_text(encoding='utf-8-sig')
    def functions(source, restore=False):
        return {node.name: ast.dump(before_guard_input_repair(node) if restore else node)
                for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    assert functions(old) == functions(new, restore=True)


def test_macro_union_index_does_not_redate_us_close_to_fx_session(guard_app, monkeypatch):
    import numpy as np
    dates = pd.bdate_range(end="2026-11-13", periods=25)
    rates = pd.Series(list(np.linspace(4.8, 5.1, 24)) + [np.nan], index=dates)
    fx = pd.Series([1332.] * 25, index=dates)
    data = pd.concat({"^TNX": pd.DataFrame({"Close": rates}),
                      "USDKRW=X": pd.DataFrame({"Close": fx})}, axis=1)
    monkeypatch.setattr(guard_app.yf, "download", lambda *args, **kwargs: data)
    monkeypatch.setattr(guard_app, "build_macro_event_risk_table", lambda: (pd.DataFrame(), 0., 0))
    guard_app.get_macro_analysis.clear()
    results, *_ = guard_app.get_macro_analysis()
    assert results["10Y 금리"]["as_of"] == "2026-11-12"
    assert results["환율"]["as_of"] == "2026-11-13"
    observed = rates.dropna()
    assert results["10Y 금리"]["chg"] == pytest.approx((observed.iloc[-1] / observed.iloc[-22] - 1) * 100)
    guard_app.get_macro_analysis.clear()
