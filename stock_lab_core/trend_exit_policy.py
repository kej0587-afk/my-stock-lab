"""Trend-following exit and 1/3 scout sizing (C-1 step 1, 2026-11-25, user-approved).

Scope is one decision code at a time. Step 1 covers EXCEPTION_ENTRY only, an unheld entry
(held positions get HOLDING_EXCEPTION_ADD_REVIEW instead). It changes three things:

1. Its own label word "정찰" (scouting) no longer turns the final read into a pullback wait.
   The code was designed as a scout entry, so the word describes the size, not a wait.
2. Exit is trend-following instead of a fixed target: initial stop = entry - 2ATR (the engine
   stop), then the stop trails the highest close since entry - 3ATR, exit on a close below it.
   Because there is no fixed target, a projected upper target ("투영상단") does not block entry.
   The current R/R >= 1 floor stays; the C-1 comparison was measured with that floor.
3. Size is the existing first scout tranche: 1/3 of the target weight, not the whole shortfall.

Everything above the R/R check still applies unchanged: data checks, the higher-timeframe
trend-damage block, the higher-timeframe overheat scout conversion, market defense, macro
hard guards, weight limits, overheat codes and flow checks.
"""

from __future__ import annotations

import math

TREND_SCOUT_ENTRY_CODES = frozenset({"EXCEPTION_ENTRY"})
# C-1 step 2 (2026-11-25, user-approved): NEW_ENTRY_LEADER uses the trend exit only in 상승장
# (benchmark regime, stock_lab_core.market_regime). Its size and entry rules are unchanged, and
# in 횡보/하락/미확인 everything stays as before (fixed target, a projected target still waits).
TREND_EXIT_REGIME_CODES = {"NEW_ENTRY_LEADER": frozenset({"상승"})}
SCOUT_FRACTION = 0.33  # the existing first scout tranche (build_position_sizing_hint: targ_w * 0.33)
INITIAL_STOP_ATR = 2.0
TRAIL_ATR = 3.0
RR_KIND_TREND = "추세추적"
EXECUTION_MEMO = "1/3 정찰 · 추세추적"


def uses_trend_exit(decision_code: str, *, has_pos: bool = False) -> bool:
    """True when this decision is executed as a 1/3 scout with a trend-following exit."""
    return not has_pos and str(decision_code or "").strip() in TREND_SCOUT_ENTRY_CODES


def uses_regime_trend_exit(decision_code: str, regime: str, *, has_pos: bool = False) -> bool:
    """True when a regime-limited code (step 2) takes the trend exit in this regime."""
    allowed = TREND_EXIT_REGIME_CODES.get(str(decision_code or "").strip())
    return not has_pos and allowed is not None and str(regime or "") in allowed


def trend_exit_applies(decision: dict | None, ticker: str, *, has_pos: bool = False) -> bool:
    """Either rule: the 1/3-scout codes always, the regime-limited codes in their regime."""
    code = str((decision or {}).get("decision_code", "") or "").strip()
    if uses_trend_exit(code, has_pos=has_pos):
        return True
    if has_pos or code not in TREND_EXIT_REGIME_CODES:
        return False
    from stock_lab_core.market_regime import regime_for
    return uses_regime_trend_exit(code, regime_for(ticker, decision), has_pos=has_pos)


def trailing_stop(initial_stop: float, highest_close: float, atr: float) -> float:
    """Stop for the next day: never below the initial stop, else highest close - 3ATR."""
    if not all(math.isfinite(v) for v in (initial_stop, highest_close, atr)) or atr <= 0:
        return initial_stop
    return max(initial_stop, highest_close - TRAIL_ATR * atr)


def trend_exit_source_text() -> str:
    return (f"추세추적 exit: 초기 손절 진입가-{INITIAL_STOP_ATR:g}ATR, "
            f"이후 진입 후 최고 종가-{TRAIL_ATR:g}ATR 추적, 종가 이탈 시 정리 (고정 목표가 없음)")


def scout_condition_text(has_pos: bool = False) -> str:
    return "현재가 부근 1차 정찰 (목표비중의 1/3까지만)"
