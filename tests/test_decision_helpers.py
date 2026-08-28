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


# ---------------------------------------------------------------------------
# Today queue display helpers
# ---------------------------------------------------------------------------

def test_dashboard_final_read_downgrades_quality_recovery_when_bearish_pattern_valid(helpers):
    final_read = helpers.build_dashboard_final_read(
        {"decision_code": "QUALITY_RECOVERY_CANDIDATE", "decision_group": "buyish"},
        dashboard_timing="✅우량주 회복 후보: 분할 검토",
        dashboard_grade="✅우량주 회복후보",
        pattern_timing="🛑하락패턴 유효",
    )
    assert final_read == "👀회복관찰"


def test_today_wait_mask_keeps_overheat_hard_block_visible_as_wait_watch(helpers):
    pd = helpers.pd
    summary_df = pd.DataFrame([{
        "종목명": "FCX",
        "티커": "FCX",
        "🔥기술적 타점": "🚫하드차단: 볼린상단 이탈",
        "패턴타점": "🚦패턴성공: 눌림대기",
        "최종읽기": "🚫추격금지",
        "📌후보등급": "🚫상단과열(추격금지)",
        "핵심근거": "%B 1.08 / MFI 74 / RSI 73",
        "판정코드": "HARD_BLOCK_BOLLINGER_UPPER",
    }])
    buyish_mask = pd.Series([False], index=summary_df.index)

    mask = helpers._today_queue_wait_mask(summary_df, buyish_mask)

    assert bool(mask.iloc[0])


def test_today_wait_mask_still_hides_non_timing_hard_blocks(helpers):
    pd = helpers.pd
    summary_df = pd.DataFrame([{
        "종목명": "FILLED",
        "티커": "FILLED",
        "🔥기술적 타점": "🚫하드차단: 목표비중 충족",
        "패턴타점": "🚦패턴성공: 눌림대기",
        "최종읽기": "🛡️방어우선",
        "📌후보등급": "⛔비중관리",
        "핵심근거": "목표비중 충족",
        "판정코드": "HARD_BLOCK_TARGET_FILLED",
    }])
    buyish_mask = pd.Series([False], index=summary_df.index)

    mask = helpers._today_queue_wait_mask(summary_df, buyish_mask)

    assert not bool(mask.iloc[0])
