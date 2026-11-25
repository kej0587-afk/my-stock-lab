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


# ── C-1 step 2: NEW_ENTRY_LEADER trend exit in 상승장 only ───────────────────────

import pandas as pd

from stock_lab_core import market_regime as mr
from stock_lab_core.trend_exit_policy import TREND_EXIT_REGIME_CODES, trend_exit_applies, uses_regime_trend_exit

LEADER_LABEL = "🔥신규진입: 대장주 포착"


def leader(**overrides):
    return decision(decision_code="NEW_ENTRY_LEADER", dec=LEADER_LABEL, **overrides)


def test_step2_scope_is_leader_in_uptrend_only():
    assert TREND_EXIT_REGIME_CODES == {"NEW_ENTRY_LEADER": frozenset({"상승"})}
    assert uses_regime_trend_exit("NEW_ENTRY_LEADER", "상승")
    for regime in ("횡보", "하락", "미확인", ""):
        assert not uses_regime_trend_exit("NEW_ENTRY_LEADER", regime)
    assert not uses_regime_trend_exit("NEW_ENTRY_LEADER", "상승", has_pos=True)
    for code in ("BREAKOUT_52W_ENTRY", "LEADER_MA5_PULLBACK_ENTRY", "S_PULLBACK_ENTRY", "QUALITY_RECOVERY_SCOUT"):
        assert not uses_regime_trend_exit(code, "상승")


def _series(values):
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)))


def test_classify_regime_matches_compared_definition():
    up = _series([100 + i * 0.5 for i in range(300)])
    down = _series([300 - i * 0.5 for i in range(300)])
    assert mr.classify_regime(up) == "상승"
    assert mr.classify_regime(down) == "하락"
    # above MA200 while MA200 still falls → 횡보
    dip = _series([300 - i * 0.5 for i in range(295)] + [225] * 5)
    assert mr.classify_regime(dip) == "횡보"
    assert mr.classify_regime(up.tail(219)) == "미확인"
    assert mr.classify_regime(None) == "미확인"


def test_regime_benchmark_by_market():
    assert mr.regime_benchmark("AAPL") == "SPY"
    assert mr.regime_benchmark("005930") == "^KS11"
    assert mr.regime_benchmark("005930.KS") == "^KS11"


def test_regime_for_prefers_attached_value_and_fails_to_unknown(monkeypatch):
    monkeypatch.setitem(mr._PROVIDER, "fn", lambda t: "상승")
    assert mr.regime_for("AAPL") == "상승"
    assert mr.regime_for("AAPL", {"market_regime": "하락"}) == "하락"

    def boom(t):
        raise RuntimeError("no data")
    monkeypatch.setitem(mr._PROVIDER, "fn", boom)
    assert mr.regime_for("AAPL") == "미확인"
    monkeypatch.setitem(mr._PROVIDER, "fn", None)
    assert mr.regime_for("AAPL") == "미확인"


def test_leader_in_uptrend_uses_trend_exit_and_projection_does_not_block():
    w = workflow(leader(market_regime="상승", rr_target=120.0, rr_ratio=2.0, rr_target_is_projection=True))
    assert w["게이트상태"] == GATE_EXECUTABLE, w["게이트근거"]
    assert w["R/R성격"] == "추세추적" and "상승장 한정" in w["R/R출처"]
    assert w["실행메모"] != "1/3 정찰 · 추세추적"  # size is unchanged for the leader


@pytest.mark.parametrize("regime", ["횡보", "하락", "미확인"])
def test_leader_outside_uptrend_is_unchanged(regime):
    w = workflow(leader(market_regime=regime, rr_target=120.0, rr_ratio=2.0, rr_target_is_projection=True))
    assert w["게이트상태"] == GATE_WAIT and "투영상단" in w["게이트근거"]
    assert w["R/R성격"] == "투영상단"


def test_leader_uptrend_keeps_rr_floor_and_guards():
    w = workflow(leader(market_regime="상승", rr_target=105.0, rr_ratio=0.5))
    assert w["게이트상태"] == GATE_WAIT and "R/R 0.50 < 1" in w["게이트근거"]
    w = workflow(leader(market_regime="상승", mtf_bias_label="상위 시간대 경고"))
    assert w["게이트상태"] == GATE_DEFENSE


def test_leader_held_or_other_code_in_uptrend_is_unchanged():
    assert not trend_exit_applies(leader(market_regime="상승"), "TEST", has_pos=True)
    assert not trend_exit_applies(decision(decision_code="BREAKOUT_52W_ENTRY", market_regime="상승"), "TEST")
    assert trend_exit_applies(leader(market_regime="상승"), "TEST")


def test_trend_exit_rows_size_text():
    rows = build_trend_exit_rows(ticker="T", stop=90.0, atr=5.0, format_currency=lambda v, t: f"${v:,.2f}",
                                 size_text="진입분 전량")
    assert {r["금액/수량"] for r in rows} == {"진입분 전량"}


# ── C-1c option C: 상승장 EXCEPTION_ENTRY under MTF overheat → 1/3 scout ───────────

from stock_lab_core.trend_exit_policy import (
    MTF_OVERHEAT_SCOUT_REASON, is_mtf_overheat_scout, mtf_overheat_scout_allowed, mtf_overheat_scout_roles,
)


def pack(weekly="상승 과열권", monthly="상승 유지"):
    return {"주봉": {"snapshot": {"state": weekly}}, "월봉": {"snapshot": {"state": monthly}}}


def guarded(app_module, d, p=None, has_pos=False, ticker="TEST"):
    return app_module.apply_precision_mtf_decision_guard(d, p or pack(), has_pos=has_pos, ticker=ticker)


def test_c1c_allowed_scope():
    assert mtf_overheat_scout_allowed(decision(market_regime="상승"), "TEST")
    for regime in ("횡보", "하락", "미확인"):
        assert not mtf_overheat_scout_allowed(decision(market_regime=regime), "TEST")
    assert not mtf_overheat_scout_allowed(decision(market_regime="상승"), "TEST", has_pos=True)
    assert not mtf_overheat_scout_allowed(leader(market_regime="상승"), "TEST")
    assert not mtf_overheat_scout_allowed(decision(), "")  # no ticker, no regime → never 상승장


def test_c1c_uptrend_exception_stays_scout_entry_and_executes(app_module):
    g = guarded(app_module, decision(market_regime="상승"))
    assert g["decision_code"] == "EXCEPTION_ENTRY" and g["mtf_overheat_scout"] is True
    assert g["mtf_bias_label"] == "정찰만 적합"
    assert is_mtf_overheat_scout(g)
    w = workflow(g)
    assert w["게이트상태"] == GATE_EXECUTABLE, w["게이트근거"]
    assert w["게이트근거"] == MTF_OVERHEAT_SCOUT_REASON
    assert w["실행메모"] == "정찰 실행(1/3) · 추세추적"
    assert "정찰 실행(1/3)" in w["🔥기술적 타점"] and "과열" not in w["🔥기술적 타점"]
    assert "상위 시간대 상승 과열" in w["핵심근거"] and "추세훼손 아님" in w["핵심근거"]
    assert w["R/R성격"] == "추세추적"


def test_c1c_roles_text():
    assert mtf_overheat_scout_roles() == [("현장소장", "예외승인 정찰 진입"), ("상위시간대", "상승 과열"),
                                          ("실행판단", "1/3 정찰 허용"), ("사유", "상승장 + EXCEPTION_ENTRY, MTF 추세훼손 아님")]


@pytest.mark.parametrize("regime", ["횡보", "하락", "미확인"])
def test_c1c_outside_uptrend_still_converts_and_waits(app_module, regime):
    g = guarded(app_module, decision(market_regime=regime))
    assert g["decision_code"] == "MTF_OVERHEAT_SCOUT_ONLY" and not g.get("mtf_overheat_scout")
    assert workflow(g)["게이트상태"] == GATE_WAIT


def test_c1c_call_without_ticker_still_converts(app_module):
    g = app_module.apply_precision_mtf_decision_guard(decision(), pack(), has_pos=False)
    assert g["decision_code"] == "MTF_OVERHEAT_SCOUT_ONLY"


@pytest.mark.parametrize("weekly, monthly", [("추세훼손", "상승 과열권"), ("상승 과열권", "추세훼손"), ("추세훼손", "상승 유지")])
def test_c1c_trend_damage_is_never_relaxed(app_module, weekly, monthly):
    g = guarded(app_module, decision(market_regime="상승"), pack(weekly, monthly))
    assert g["decision_code"] == "MTF_DAMAGE_NO_ADD" and not g.get("mtf_overheat_scout")
    assert workflow(g)["게이트상태"] == GATE_DEFENSE


def test_c1c_leader_overheat_is_unchanged(app_module):
    g = guarded(app_module, leader(market_regime="상승"))
    assert g["decision_code"] == "MTF_OVERHEAT_SCOUT_ONLY"


def test_c1c_held_position_is_unchanged(app_module):
    g = guarded(app_module, decision(market_regime="상승"), has_pos=True)
    assert not g.get("mtf_overheat_scout")
    assert not is_mtf_overheat_scout(dict(g, mtf_overheat_scout=True), has_pos=True)


def test_c1c_rr_floor_still_waits(app_module):
    g = guarded(app_module, decision(market_regime="상승", rr_target=105.0, rr_ratio=0.5))
    w = workflow(g)
    assert w["게이트상태"] == GATE_WAIT and "R/R 0.50 < 1" in w["게이트근거"]


@pytest.mark.parametrize("field, value, expected", [
    ("시장실행상태", "시장방어: 신규매수 중단", GATE_DEFENSE),
    ("매크로상태", "UNKNOWN", "데이터확인"),
    ("데이터상태", "가격 조회 실패", "데이터확인"),
    ("판정코드", "HARD_BLOCK_OVERWEIGHT", GATE_DEFENSE),
])
def test_c1c_upper_guards_still_win(app_module, field, value, expected):
    from stock_lab_core.execution_gate import build_execution_gate
    row = dict(workflow(guarded(app_module, decision(market_regime="상승"))))
    row[field] = value
    assert build_execution_gate(row)["게이트상태"] == expected


def test_c1c_macro_hard_guard_code_still_blocks():
    from stock_lab_core.execution_gate import build_execution_gate
    row = dict(workflow(decision(market_regime="상승", mtf_overheat_scout=True, mtf_bias_label="정찰만 적합")))
    row["판정코드"] = "HARD_BLOCK_MACRO_STORM"
    assert build_execution_gate(row)["게이트상태"] == GATE_DEFENSE
