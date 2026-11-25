"""C-4 (2026-11-25, user decision A''+): bearish patterns are tech-review context; only a close break with
major price-structure damage keeps the pattern hold. Bullish '패턴유효: 정밀확인' never erases independent blocks."""
import pytest

from stock_lab_core.chart_patterns import (
    BEARISH_STAGE_BREAK, BEARISH_STAGE_OBSERVED, BEARISH_STAGE_STRUCTURE, BEARISH_STAGE_VOLUME_BREAK,
    build_chart_pattern_timing_note, classify_bearish_pattern_stage, summarize_chart_pattern_for_dashboard,
)
from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.execution_gate import build_execution_gate


def _pattern(direction="bearish", lifecycle="현재유효", **kw):
    return {"name": "쌍봉" if direction == "bearish" else "쌍바닥", "direction": direction, "lifecycle": lifecycle,
            "trigger_price": 100.0, "invalid_price": 120.0, **kw}


def _decision(**kw):
    d = {"decision_code": "QUALITY_RECOVERY_SCOUT", "dec": "🟢우량주 회복초입: 1차 정찰", "decision_group": "buyish",
         "cur_p": 98.0, "ma50": 95.0, "ext_structure": "Bullish", "structure_risk": False, "rr_ratio": 2.0,
         "rsi": 45.0, "mfi": 45.0, "atr": 2.0, "rr_stop": 92.0, "rr_target": 110.0, "pct_b": 0.4, "data_state": "OK", "mtf_bias_label": "중립 확인"}
    d.update(kw)
    return d


def _gate(decision, pattern):
    timing, reason, bucket = summarize_chart_pattern_for_dashboard([pattern], decision)
    w = build_decision_workflow("T", "T", decision, pattern_timing=timing, pattern_bucket=bucket, pattern_reason=reason)
    return timing, bucket, build_execution_gate(w)


def _gate_without_pattern(decision):
    w = build_decision_workflow("T", "T", decision, pattern_timing="-", pattern_bucket="", pattern_reason="")
    return build_execution_gate(w)


@pytest.mark.parametrize("pattern,stage", [
    (_pattern(lifecycle="관찰"), BEARISH_STAGE_OBSERVED),
    (_pattern(), BEARISH_STAGE_BREAK),
    (_pattern(breakdown_volume_ratio=1.8), BEARISH_STAGE_VOLUME_BREAK),
])
def test_bearish_without_structure_damage_is_reference_only(pattern, stage):
    d = _decision()
    assert classify_bearish_pattern_stage(pattern, d) == stage
    timing, bucket, gate = _gate(d, pattern)
    assert bucket == "" and "하락패턴" not in timing and "참고" in timing
    assert gate == _gate_without_pattern(d)


@pytest.mark.parametrize("damage", [{"structure_risk": True}, {"cur_p": 90.0, "ma50": 95.0, "ext_structure": "Bearish"}])
def test_break_with_structure_damage_keeps_the_hold(damage):
    d = _decision(**damage)
    p = _pattern(breakdown_volume_ratio=0.8)
    assert classify_bearish_pattern_stage(p, d) == BEARISH_STAGE_STRUCTURE
    timing, bucket, gate = _gate(d, p)
    assert timing == "🛑하락패턴 유효" and bucket == "risk"
    assert gate["게이트상태"] != "실행가능"
    assert "구조훼손" in build_chart_pattern_timing_note([p], d)["title"]


def test_observed_shape_with_structure_flag_does_not_block_by_itself():
    d = _decision(structure_risk=True)
    p = _pattern(lifecycle="관찰")
    assert classify_bearish_pattern_stage(p, d) == BEARISH_STAGE_OBSERVED
    assert _gate(d, p)[2] == _gate_without_pattern(d)


def test_engine_and_mtf_defense_stay_with_any_bearish_stage():
    for extra in ({"mtf_bias_label": "상위 시간대 경고"}, {"decision_code": "STRUCTURE_DAMAGE_NO_ENTRY", "dec": "⚠️구조훼손: 신규진입 보류",
                                                       "decision_group": "caution"}):
        d = _decision(**extra)
        for p in (_pattern(lifecycle="관찰"), _pattern(), _pattern(breakdown_volume_ratio=2.0)):
            assert _gate(d, p)[2]["게이트상태"] == "방어우선"


BULL = _pattern(direction="bullish", lifecycle="현재유효", trigger_price=95.0, invalid_price=90.0)
REBOUND = dict(decision_code="A_GRADE_TECH_REBOUND", dec="🎯A급: 기술적 반등", decision_group="neutral")


@pytest.mark.parametrize("extra,row_extra,state", [
    ({"rr_ratio": 0.8}, {}, "대기/관찰"),
    ({"data_state": "가격 확인 필요"}, {}, "데이터확인"),
    ({"mtf_bias_label": "상위 시간대 경고"}, {}, "방어우선"),
    ({"decision_code": "STRUCTURE_DAMAGE_NO_ENTRY", "dec": "⚠️구조훼손: 신규진입 보류", "decision_group": "caution"}, {}, "방어우선"),
    ({"decision_code": "HARD_BLOCK_TARGET_FILLED", "dec": "목표비중 충족", "decision_group": "caution"}, {}, "방어우선"),
    ({"macro_state": "UNKNOWN", "macro_missing_components": ("VIX",)}, {}, "데이터확인"),
    ({}, {"시장실행상태": "시장방어: 신규매수 중단"}, "방어우선"),
])
def test_bullish_precision_confirm_does_not_erase_independent_blocks(extra, row_extra, state):
    d = _decision(**{**REBOUND, **extra})
    timing, reason, bucket = summarize_chart_pattern_for_dashboard([BULL], d)
    w = build_decision_workflow("T", "T", d, pattern_timing=timing, pattern_bucket=bucket, pattern_reason=reason)
    w.update(row_extra)
    g = build_execution_gate(w)
    assert g["게이트상태"] == state, (timing, w.get("최종읽기"), g)


def test_bullish_precision_confirm_still_promotes_without_blocks():
    d = _decision(**REBOUND)
    timing, reason, bucket = summarize_chart_pattern_for_dashboard([BULL], d)
    w = build_decision_workflow("T", "T", d, pattern_timing=timing, pattern_bucket=bucket, pattern_reason=reason)
    assert timing == "✅패턴유효: 정밀확인" and build_execution_gate(w)["게이트상태"] == "실행가능"
    assert _gate_without_pattern(d)["게이트상태"] != "실행가능"
