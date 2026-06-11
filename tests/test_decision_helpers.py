"""Focused unit tests for the small helper functions extracted from
`calc_scores_and_decision` in step 3 of the guard -> policy -> signal ->
sizing decomposition.

These complement the golden-snapshot tests
(tests/test_decision_golden_snapshot.py). The golden snapshots freeze
whatever the synthetic price scenarios happen to produce end-to-end, but
synthetic price data struggles to land on some specific branches (e.g.
SAFETY_RED + an aggressive new-entry code at the same time). Now that
`_apply_safety_state_override` and `_compute_sizing_hint` are standalone
functions, we can drive those branches directly with hand-picked inputs.
"""
import pytest


@pytest.fixture(scope="module")
def helpers(app_module):
    return app_module


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
