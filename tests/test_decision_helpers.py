"""Focused unit tests for decision helpers extracted from app.py.

Most helpers now live in stock_lab_core.decision_engine so they can be
tested without importing the full Streamlit app. A small app-level fixture is
kept only for helpers that still belong to app.py.
"""
import pandas as pd
import pytest

from stock_lab_core.decision_engine import (
    apply_safety_state_override,
    build_decision_outcome,
    build_sideways_quality_state,
    compute_sizing_hint,
    has_down_session_pressure,
    translate_new_entry_decision_for_holding,
)

class _DecisionHelperAdapter:
    build_decision_outcome = staticmethod(build_decision_outcome)
    _apply_safety_state_override = staticmethod(apply_safety_state_override)
    _translate_new_entry_decision_for_holding = staticmethod(translate_new_entry_decision_for_holding)
    _has_down_session_pressure = staticmethod(has_down_session_pressure)
    build_sideways_quality_state = staticmethod(build_sideways_quality_state)
    _compute_sizing_hint = staticmethod(compute_sizing_hint)


@pytest.fixture(scope="module")
def helpers():
    return _DecisionHelperAdapter


def _outcome(app_module, label, color, code):
    return app_module.build_decision_outcome(label, color, code)


# ---------------------------------------------------------------------------
# _apply_safety_state_override
# ---------------------------------------------------------------------------

def test_safety_red_downgrades_aggressive_new_entry(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
    )
    dec, col, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=False,
        tech_total=0.0, main_score=4.0, adj_tech_score=4.0,
    )
    assert outcome.code == "SAFETY_RED_NO_NEW_ENTRY"
    assert dec == outcome.label
    assert col == outcome.color
    assert outcome.group == "caution"
    # The original signal should be referenced in the reasons.
    assert any("S_PULLBACK_ENTRY" in r or "탑승 찬스" in r for r in outcome.reasons)


@pytest.mark.parametrize("code", [
    "BREAKOUT_52W_ENTRY", "S_PULLBACK_ENTRY", "OVERSOLD_NEW_ENTRY", "EARLY_ENTRY",
    "EARLY_REVERSAL_ENTRY", "NEW_ENTRY_LEADER", "QUALITY_PULLBACK_ENTRY",
    "TREND_PULLBACK_EXPLORE", "EXCEPTION_ENTRY",
    "LEADER_MA5_FAST_PULLBACK_ENTRY", "LEADER_MA5_PULLBACK_ENTRY",
])
def test_safety_red_downgrades_all_aggressive_codes(helpers, code):
    decision_outcome = _outcome(helpers, "테스트", "#000000", code)
    _, _, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=False,
        tech_total=0.0, main_score=0.0, adj_tech_score=0.0,
    )
    assert outcome.code == "SAFETY_RED_NO_NEW_ENTRY"


def test_safety_red_does_not_downgrade_when_holding_position(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
    )
    _, _, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=True,
        tech_total=0.0, main_score=4.0, adj_tech_score=4.0,
    )
    assert outcome.code == "S_PULLBACK_ENTRY"


def test_safety_yellow_or_green_does_not_downgrade(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
    )
    for safety_state in ("YELLOW", "GREEN"):
        _, _, outcome = helpers._apply_safety_state_override(
            decision_outcome, decision_outcome.label, decision_outcome.color,
            safety_state=safety_state, has_pos=False,
            tech_total=2.0, main_score=4.0, adj_tech_score=4.0,
        )
        assert outcome.code == "S_PULLBACK_ENTRY"


def test_safety_red_does_not_touch_non_aggressive_code(helpers):
    decision_outcome = _outcome(
        helpers, "🚨위기/패닉: 투매 포착", "#dc2626", "CRISIS_PANIC_SELL_OFF",
    )
    _, _, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=False,
        tech_total=0.0, main_score=3.0, adj_tech_score=2.0,
    )
    assert outcome.code == "CRISIS_PANIC_SELL_OFF"


def test_holding_position_translates_new_entry_leader_label(helpers):
    decision_outcome = _outcome(
        helpers, "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
    )

    outcome = helpers._translate_new_entry_decision_for_holding(
        decision_outcome, has_pos=True, weight_gap=4.02,
    )

    assert outcome.code == "HOLDING_LEADER_ADD_REVIEW"
    assert "신규진입" not in outcome.label
    assert "보유" in outcome.label
    assert outcome.group == "caution"
    assert any("4.0%p" in r for r in outcome.reasons)


def test_non_holding_position_keeps_new_entry_leader_label(helpers):
    decision_outcome = _outcome(
        helpers, "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
    )

    outcome = helpers._translate_new_entry_decision_for_holding(
        decision_outcome, has_pos=False, weight_gap=4.02,
    )

    assert outcome.code == "NEW_ENTRY_LEADER"
    assert outcome.label == "🆕신규진입: 대장주 포착"


def test_today_market_guard_reasons_name_triggering_indexes(app_module):
    stats = app_module._today_benchmark_guard_stats(pd.DataFrame([
        {"시장": "KOSPI", "티커": "^KS11", "1일": 0.046, "5일": 0.026, "20일": 0.118, "MA20": "상회", "MA50": "상회", "연속하락": 0},
        {"시장": "KOSDAQ", "티커": "^KQ11", "1일": 0.011, "5일": -0.015, "20일": 0.029, "MA20": "하회", "MA50": "상회", "연속하락": 0},
        {"시장": "KOSPI200 ETF", "티커": "069500.KS", "1일": 0.048, "5일": 0.030, "20일": 0.130, "MA20": "상회", "MA50": "상회", "연속하락": 0},
        {"시장": "KOSDAQ150 ETF", "티커": "229200.KS", "1일": 0.015, "5일": -0.024, "20일": 0.031, "MA20": "하회", "MA50": "상회", "연속하락": 0},
    ]))

    reason_text = " · ".join(stats["reasons"])

    assert stats["score"] == 1
    assert "주요지수 2개" in reason_text
    assert "KOSDAQ(^KQ11)" in reason_text
    assert "KOSDAQ150 ETF(229200.KS)" in reason_text


def test_down_session_pressure_detects_regular_or_live_drop(helpers):
    assert helpers._has_down_session_pressure(
        day_ret=-0.025,
        regular_day_ret=-0.025,
        live_ref_ret=-0.007,
        live_gap_move=-0.007,
        live_price_used=True,
    )
    assert not helpers._has_down_session_pressure(
        day_ret=-0.012,
        regular_day_ret=-0.012,
        live_ref_ret=-0.004,
        live_gap_move=-0.004,
        live_price_used=True,
    )


def test_holding_pullback_wait_code_is_caution(helpers):
    outcome = _outcome(
        helpers,
        "🟡보유주 단기하락: 추매는 종가 확인",
        "#d97706",
        "HOLDING_PULLBACK_WAIT_CLOSE",
    )

    assert outcome.group == "caution"


def test_sideways_quality_blocks_leveraged_overheat_even_after_recovery(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 17.58,
            "rsi": 70.7,
            "mfi": 63.7,
            "pct_b": 0.81,
            "ma5": 17.2,
            "ma20": 14.3,
            "ma50": 12.8,
            "ma120": 15.4,
            "rr_ratio": 2.0,
            "dd": -0.738,
            "trend": "⏳혼조세",
            "rs_label": "🚀강함",
            "macd": "📈추세유지(상승중)",
            "vol_ratio": 1.0,
        },
        is_leveraged_product=True,
    )

    assert state["status"] == "차단"
    assert "레버리지" in state["label"]


def test_sideways_quality_allows_stable_ma20_support_for_normal_asset(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 102.0,
            "rsi": 55.0,
            "mfi": 58.0,
            "pct_b": 0.55,
            "ma5": 101.5,
            "ma20": 100.0,
            "ma50": 98.0,
            "ma120": 90.0,
            "rr_ratio": 2.1,
            "dd": -0.04,
            "trend": "🚀정배열(상승)",
            "rs_label": "🚀강함",
            "macd": "📈추세유지(상승중)",
            "vol_ratio": 1.0,
            "bucket": "swing",
        },
        is_leveraged_product=False,
    )

    assert state["status"] == "통과"
    assert "매수 가능 횡보" in state["label"]


def test_sideways_quality_blocks_poor_rr_despite_uptrend(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 135.86,
            "rsi": 63.0,
            "mfi": 64.0,
            "pct_b": 0.73,
            "ma5": 145.2,
            "ma20": 94.93,
            "ma50": 76.75,
            "rr_ratio": 0.64,
            "dd": -0.231,
            "trend": "🚀정배열(상승)",
            "rs_label": "🚀강함",
            "macd": "📈추세유지(상승중)",
            "vol_ratio": 0.8,
        },
        is_leveraged_product=False,
    )

    assert state["status"] == "차단"
    assert "손익비" in state["label"]


def test_sideways_quality_keeps_core_dca_as_rate_limited_not_blocked(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 98.0,
            "rsi": 38.0,
            "mfi": 43.0,
            "pct_b": 0.30,
            "ma5": 99.0,
            "ma20": 100.0,
            "ma50": 104.0,
            "rr_ratio": 0.8,
            "dd": -0.12,
            "trend": "🌊역배열(하락)",
            "rs_label": "➖보통",
            "bucket": "core",
            "core_dca_rate": 1.0,
        },
        is_leveraged_product=False,
    )

    assert state["status"] == "주의"
    assert "코어" in state["label"]


def test_none_decision_outcome_is_normalized(helpers):
    dec, col, outcome = helpers._apply_safety_state_override(
        None, "그냥 보유", "#6b7280",
        safety_state="GREEN", has_pos=True,
        tech_total=3.0, main_score=2.0, adj_tech_score=3.0,
    )
    assert outcome is not None
    assert dec == "그냥 보유"
    assert col == "#6b7280"


# ---------------------------------------------------------------------------
# _compute_sizing_hint
# ---------------------------------------------------------------------------

def test_sizing_hint_for_new_entry_signal(helpers):
    decision_outcome = _outcome(
        helpers, "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=False, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=10.0, ticker="TST.KS",
    )
    assert hint  # build_position_sizing_hint should produce a non-empty hint


def test_sizing_hint_ma5_pullback_addon_kr_stock(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 추매", "#8b5cf6", "LEADER_MA5_PULLBACK_ENTRY",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=5.0, ticker="TST.KS",
    )
    assert "MA5 눌림" in hint
    assert "원" in hint  # KR ticker -> KRW formatting
    assert "5.0%p" in hint


def test_sizing_hint_ma5_pullback_addon_us_ticker(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 추매", "#8b5cf6", "LEADER_MA5_FAST_PULLBACK_ENTRY",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=100.0,
        is_etf=False, weight_gap=5.0, ticker="AAPL",
    )
    assert "MA5 눌림" in hint
    assert "$" in hint  # US ticker -> USD formatting


def test_sizing_hint_no_addon_when_weight_gap_small(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 추매", "#8b5cf6", "LEADER_MA5_PULLBACK_ENTRY",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=0.5, ticker="TST.KS",
    )
    assert hint == ""

def test_sizing_hint_no_addon_for_unrelated_code(helpers):
    decision_outcome = _outcome(
        helpers, "📈A급 비중여유: 소액 추가 검토", "#22c55e", "A_GRADE_ADD_ON_REVIEW",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=5.0, ticker="TST.KS",
    )
    assert hint == ""
