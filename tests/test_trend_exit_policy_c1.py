"""C-1 step 1 (2026-11-25, user-approved): EXCEPTION_ENTRY = 1/3 scout + trend-following exit.

Rule table: docs/maintenance/20261125_c1_step1_exception_trend_exit.md
"""

import math

import pytest

from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.execution_gate import GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT
from stock_lab_core.precision_plan_rows import build_trend_exit_rows
from stock_lab_core.today_queue import build_dashboard_final_read, build_today_queue_execution_snapshot
from stock_lab_core.trend_exit_policy import (
    INITIAL_STOP_ATR, SCOUT_FRACTION, TRAIL_ATR, TREND_SCOUT_ENTRY_CODES, trailing_stop, uses_trend_exit,
)

EXC_LABEL = "🟣예외승인: 정찰대 진입(MA5/FVG)"


def decision(**overrides):
    base = {
        "decision_code": "EXCEPTION_ENTRY", "dec": EXC_LABEL, "decision_group": "buyish",
        "cur_p": 100.0, "rr_stop": 90.0, "rr_target": 115.0, "rr_ratio": 1.5, "atr": 5.0,
        "ma5": 99.0, "ma20": 95.0, "rsi": 55.0, "mfi": 55.0, "pct_b": 0.6, "grade": "A",
        "target_w": 10.0, "current_w": 0.0, "buy_amt": 1_000_000.0, "mtf_bias_label": "상승 우위",
        "decision_reasons": ("MA5/FVG 눌림",),
    }
    base.update(overrides)
    return base


def workflow(d, has_pos=False):
    return build_decision_workflow("Test", "TEST", d, has_pos=has_pos)


# ── scope ──────────────────────────────────────────────────────────────────────

def test_scope_is_exception_entry_only_and_unheld_only():
    assert TREND_SCOUT_ENTRY_CODES == frozenset({"EXCEPTION_ENTRY"})
    assert uses_trend_exit("EXCEPTION_ENTRY")
    assert not uses_trend_exit("EXCEPTION_ENTRY", has_pos=True)
    for code in ("NEW_ENTRY_LEADER", "BREAKOUT_52W_ENTRY", "LEADER_MA5_PULLBACK_ENTRY", "S_PULLBACK_ENTRY",
                 "QUALITY_PULLBACK_ENTRY", "QUALITY_RECOVERY_SCOUT", "MTF_OVERHEAT_SCOUT_ONLY", "EXCEPTION_ADD_ON"):
        assert not uses_trend_exit(code)


def test_constants_match_the_compared_rule():
    assert (INITIAL_STOP_ATR, TRAIL_ATR, SCOUT_FRACTION) == (2.0, 3.0, 0.33)


# ── trailing stop ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("highest, expected", [(100.0, 90.0), (105.0, 90.0), (110.0, 95.0), (130.0, 115.0)])
def test_trailing_stop_never_below_initial_and_trails_highest_close(highest, expected):
    assert trailing_stop(90.0, highest, 5.0) == expected


def test_trailing_stop_with_missing_atr_keeps_initial_stop():
    assert trailing_stop(90.0, 130.0, math.nan) == 90.0
    assert trailing_stop(90.0, 130.0, 0.0) == 90.0


# ── 1. label word "정찰" ────────────────────────────────────────────────────────

def test_exception_entry_scout_word_is_not_a_wait():
    d = decision()
    assert build_dashboard_final_read(d, EXC_LABEL, "A") == "✅정밀확인"


def test_other_codes_keep_scout_word_as_wait():
    d = decision(decision_code="QUALITY_RECOVERY_SCOUT_X", dec="🟢1차 정찰")
    assert build_dashboard_final_read(d, "🟢1차 정찰", "A") == "⏳눌림대기"


def test_exception_entry_low_rr_still_waits():
    d = decision(rr_target=105.0, rr_ratio=0.5)
    assert build_dashboard_final_read(d, f"{EXC_LABEL} / R/R<1 정찰", "A") == "⏳눌림대기"
    w = workflow(d)
    assert w["게이트상태"] == GATE_WAIT and "R/R 0.50 < 1" in w["게이트근거"]


# ── 2. trend-following exit ─────────────────────────────────────────────────────

def test_exception_entry_executes_with_trend_exit_and_scout_memo():
    w = workflow(decision())
    assert w["게이트상태"] == GATE_EXECUTABLE, w["게이트근거"]
    assert w["R/R성격"] == "추세추적"
    assert "최고 종가-3ATR" in w["R/R출처"]
    assert w["실행메모"] == "1/3 정찰 · 추세추적"
    assert w["1차조건"] == "현재가 부근 1차 정찰 (목표비중의 1/3까지만)"


def test_projected_target_does_not_block_trend_exit():
    d = decision(rr_target=120.0, rr_ratio=2.0, rr_target_is_projection=True)
    w = workflow(d)
    assert w["게이트상태"] == GATE_EXECUTABLE, w["게이트근거"]
    assert "투영상단" not in w["R/R성격"]


def test_projected_target_still_blocks_other_codes():
    d = decision(decision_code="NEW_ENTRY_LEADER", dec="🔥신규진입: 대장주 포착", rr_target=120.0,
                 rr_ratio=2.0, rr_target_is_projection=True)
    w = workflow(d)
    assert w["게이트상태"] == GATE_WAIT and "투영상단" in w["게이트근거"]


# ── upper safety guards stay ───────────────────────────────────────────────────

def test_mtf_trend_damage_still_blocks():
    w = workflow(decision(mtf_bias_label="상위 시간대 경고"))
    assert w["게이트상태"] == GATE_DEFENSE


def test_mtf_overheat_conversion_is_not_relaxed():
    d = decision(decision_code="MTF_OVERHEAT_SCOUT_ONLY", dec="🟡상위과열 눌림: 1차 정찰만", mtf_bias_label="정찰만 적합")
    w = workflow(d)
    assert w["게이트상태"] == GATE_WAIT
    assert w["R/R성격"] != "추세추적"


@pytest.mark.parametrize("field, value", [("시장실행상태", "시장방어: 신규 축소"), ("매크로상태", "UNKNOWN")])
def test_market_and_macro_guards_still_win(field, value):
    from stock_lab_core.execution_gate import build_execution_gate
    row = dict(workflow(decision()))
    row[field] = value
    assert build_execution_gate(row)["게이트상태"] != GATE_EXECUTABLE


def test_held_position_is_unchanged():
    snap = build_today_queue_execution_snapshot("Test", "TEST", decision(), has_pos=True)
    assert snap["R/R성격"] == "차트구조"
    assert snap["실행메모"] != "1/3 정찰 · 추세추적"


# ── 3. precision exit rows ─────────────────────────────────────────────────────

def test_trend_exit_rows_have_no_fixed_target():
    rows = build_trend_exit_rows(ticker="TEST", stop=90.0, atr=5.0, format_currency=lambda v, t: f"${v:,.2f}")
    assert [r["단계"] for r in rows] == ["추세추적 정리", "초기 손절"]
    assert "최고 종가 - 3ATR" in rows[0]["가격"] and "$15.00" in rows[0]["가격"]
    assert rows[1]["가격"] == "$90.00"
    assert not any("익절" in r["단계"] for r in rows)
