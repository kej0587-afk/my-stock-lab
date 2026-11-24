"""Behavior groups (행동군) for decision codes: display and management only.

User decision 2026-11-24: keep every decision_code; group them into nine behavior groups
for display, counting and review. Nothing here feeds a score, gate, sizing or multiplier.
Record: docs/maintenance/20261124_decision_policy_proposal.md Appendix A.
"""

BEHAVIOR_GROUP_LABELS = {
    "NEW_ENTRY_BASIC": "1. 신규진입·기본",
    "NEW_ENTRY_MOMENTUM": "2. 신규진입·상승장/대장주",
    "RECOVERY_ENTRY": "3. 회복 진입",
    "HOLDING_ADD": "4. 보유 추매·평단관리",
    "HOLDING_KEEP": "5. 보유 유지·비중·익절",
    "RISK_CHECK": "6. 위험·축소·손절 점검",
    "ETF_CORE_DCA": "7. ETF 적립·코어 DCA·위기 매수",
    "LEVERAGED": "8. 레버리지 전용",
    "WAIT_OVERHEAT_DATA": "9. 실행대기·과열·데이터확인",
}

BEHAVIOR_GROUP_CODES = {
    "NEW_ENTRY_BASIC": (
        "S_PULLBACK_ENTRY",
        "QUALITY_PULLBACK_ENTRY",
        "TREND_PULLBACK_EXPLORE",
        "OVERSOLD_NEW_ENTRY",
        "OVERSOLD_DCA",
    ),
    "NEW_ENTRY_MOMENTUM": (
        "NEW_ENTRY_LEADER",
        "BREAKOUT_52W_ENTRY",
        "EARLY_ENTRY",
        "EARLY_REVERSAL_ENTRY",
        "EXCEPTION_ENTRY",
        "LEADER_MA5_PULLBACK_ENTRY",
        "LEADER_MA5_FAST_PULLBACK_ENTRY",
        "MTF_OVERHEAT_SCOUT_ONLY",
    ),
    "RECOVERY_ENTRY": (
        "QUALITY_RECOVERY_SCOUT",
        "QUALITY_RECOVERY_CANDIDATE",
        "QUALITY_RECOVERY_WATCH",
    ),
    "HOLDING_ADD": (
        "S_PULLBACK_ADD_ON",
        "OVERSOLD_ADD_ON",
        "S_GRADE_OVERSOLD_BUY",
        "A_GRADE_TECH_REBOUND",
        "UPTREND_PULLBACK_DCA",
        "COST_MINUS_3_7_DCA",
        "COST_MINUS_7_15_CONDITIONAL_DCA",
        "STRENGTH_ADD_ON_OK",
        "S_GRADE_ADD_ON_OK",
        "A_GRADE_ADD_ON_REVIEW",
        "EXCEPTION_ADD_ON",
        "FUND_OVERSOLD_REBALANCE_REVIEW",
        "HOLDING_S_PULLBACK_ADD_REVIEW",
        "HOLDING_QUALITY_PULLBACK_ADD_REVIEW",
        "HOLDING_TREND_PULLBACK_ADD_REVIEW",
        "HOLDING_OVERSOLD_ADD_REVIEW",
        "HOLDING_LEADER_ADD_REVIEW",
        "HOLDING_EARLY_ADD_REVIEW",
        "HOLDING_EARLY_REVERSAL_ADD_REVIEW",
        "HOLDING_EXCEPTION_ADD_REVIEW",
        "HOLDING_QUALITY_RECOVERY_SCOUT",
        "HOLDING_QUALITY_RECOVERY_CANDIDATE",
        "HOLDING_BREAKOUT_TRAIL",
    ),
    "HOLDING_KEEP": (
        "ABOVE_COST_HOLD",
        "ABOVE_COST_WAIT",
        "ABOVE_COST_WAIT_PULLBACK",
        "NEAR_COST_WAIT",
        "HOLD_WAIT_SIGNAL",
        "HOLDING_PULLBACK_WAIT_CLOSE",
        "S_GRADE_OVERHEAT_WAIT",
        "OVERHEAT_WAIT",
        "HOLDING_DCA_CONDITION_MISS",
        "TARGET_FILLED_HOLD",
        "TARGET_FILLED_S_GRADE_WAIT",
        "BELOW_COST_TARGET_FILLED",
        "HARD_BLOCK_TARGET_FILLED",
        "HARD_BLOCK_OVERWEIGHT",
        "PROFIT_TAKE_REVIEW",
    ),
    "RISK_CHECK": (
        "HARD_BLOCK_FINANCIAL_F",
        "TARGET_ZERO_NO_ADD",
        "SAFETY_RED_NO_NEW_ENTRY",
        "MACRO_STORM_HOLDING_CAUTION",
        "STRUCTURE_DAMAGE_NO_ENTRY",
        "STRUCTURE_DAMAGE_HOLDING_CHECK",
        "PRICE_DRAWDOWN_NO_ENTRY",
        "PRICE_DRAWDOWN_HOLDING_CHECK",
        "SINGLE_DAY_BREAKDOWN_NO_ENTRY",
        "SINGLE_DAY_BREAKDOWN_HOLDING_CHECK",
        "DRAWDOWN_20_NO_ENTRY",
        "DRAWDOWN_20_HOLDING_CAUSE_CHECK",
        "DRAWDOWN_20_HOLDING_STOP_CHECK",
        "LIVE_GAP_SHOCK_HOLDING_CHECK",
        "DOWNTREND_NO_ENTRY",
        "REVERSE_TREND_NO_ENTRY",
        "MTF_DAMAGE_NO_ADD",
        "CRISIS_PANIC_SELL_OFF",
        "COST_MINUS_15_CAUSE_CHECK",
        "COST_MINUS_15_TREND_RISK",
        "TREND_RISK_CAUSE_CHECK",
        "STOCK_PANIC_CAUSE_CHECK",
        "STOCK_DRAWDOWN_CAUSE_CHECK",
        "STOCK_CRISIS_CAUSE_CHECK",
        "NON_CORE_ETF_PANIC_CAUSE_CHECK",
        "NON_CORE_ETF_DRAWDOWN_CAUSE_CHECK",
        "NON_CORE_ETF_CRISIS_CAUSE_CHECK",
    ),
    "ETF_CORE_DCA": (
        "ETF_DCA_OK",
        "ETF_LARGE_GAP_DCA_OK",
        "CONCENTRATED_ETF_UPPER_WAIT",
        "NEW_ETF_BELOW_COST_DCA",
        "NEW_ETF_DATA_ACCUMULATION",
        "NEW_ETF_MIN_DATA_WATCH",
        "NEW_ETF_NEAR_COST_ADD",
        "NEW_ETF_PULLBACK_BUY",
        "NEW_ETF_SHORT_OVERHEAT",
        "NEW_ETF_TARGET_FILLED",
        "NEW_ETF_UPPER_WAIT",
        "NEW_ETF_WATCH_BUY",
        "CORE_NEUTRAL_DCA",
        "CORE_PULLBACK_DCA",
        "CORE_DRAWDOWN_DCA",
        "CORE_CRASH_DCA",
        "CORE_OVERHEAT_DCA",
        "CORE_STORM_DCA",
        "PANIC_CASH_DEPLOY",
        "PANIC_FINAL_DEPLOY",
    ),
    "LEVERAGED": (
        "LEVERAGED_DAILY_DROP_NO_ADD",
        "LEVERAGED_DCA_CONDITIONAL",
        "LEVERAGED_DCA_OVERHEAT_PASS",
        "LEVERAGED_RECOVERY_DCA_BLOCK",
        "LEVERAGED_RECOVERY_DCA_CONDITIONAL",
        "LEVERAGED_TARGET_FILLED_DCA_EXCLUDED",
        "LEVERAGED_TARGET_ZERO_DCA_EXCLUDED",
        "LEVERAGED_WATCH_NO_POSITION",
    ),
    "WAIT_OVERHEAT_DATA": (
        "SEARCH_NEW_ENTRY",
        "WATCH_WAIT_ENTRY",
        "UPTREND_PULLBACK_CONFIRM",
        "S_UPTREND_WAIT_PULLBACK",
        "A_UPTREND_SEARCH_ENTRY",
        "NEAR_UPPER_WAIT",
        "BAND_UPPER_WAIT",
        "HARD_BLOCK_MFI_OVERHEAT",
        "HARD_BLOCK_BOLLINGER_UPPER",
        "EXTREME_OVERHEAT_NO_CHASE",
        "OVERHEAT_EXTENSION_WAIT_MA5",
        "SHORT_OVERHEAT_NO_ENTRY",
        "SHORT_OVERHEAT_NO_ADD",
        "LIVE_GAP_SHOCK_WAIT",
        "PREMARKET_REBOUND_WAIT",
        "PREMARKET_REBOUND_HOLDING_WAIT",
        "DATA_ERROR",
        "DATA_UNAVAILABLE",
    ),
}

# Codes outside the 127 emitted ones: dictionary-only and label-inferred generic codes.
EXTRA_CODES = {
    "HARD_BLOCK_MACRO_STORM": "RISK_CHECK",       # dictionary only, no current path emits it
    "CRISIS_CORE_FOCUS": "ETF_CORE_DCA",          # dictionary only
    "CORE_DCA": "ETF_CORE_DCA",                   # infer_decision_code fallback
    "NEW_ETF_WATCH": "ETF_CORE_DCA",              # infer_decision_code fallback
}
UNCLASSIFIED = "UNCLASSIFIED"
UNCLASSIFIED_LABEL = "미분류"

BEHAVIOR_GROUP_BY_CODE = {code: key for key, codes in BEHAVIOR_GROUP_CODES.items() for code in codes}
BEHAVIOR_GROUP_BY_CODE.update(EXTRA_CODES)


def behavior_group_key(decision_code) -> str:
    return BEHAVIOR_GROUP_BY_CODE.get(str(decision_code or "").strip().upper(), UNCLASSIFIED)


def behavior_group_label(decision_code) -> str:
    """Display label such as '2. 신규진입·상승장/대장주'; generic/unknown codes are '미분류'."""
    return BEHAVIOR_GROUP_LABELS.get(behavior_group_key(decision_code), UNCLASSIFIED_LABEL)


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
