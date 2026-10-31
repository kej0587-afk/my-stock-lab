"""Offline contracts for core DCA codes and execution restrictions."""

import pandas as pd
import pytest

from stock_lab_core.decision_engine import build_core_dca_outcome
from stock_lab_core.decision_workflow import attach_market_execution_context, build_decision_workflow
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK,
    GATE_DEFENSE,
    GATE_EXECUTABLE,
    GATE_WAIT,
    apply_execution_gate_columns,
    build_execution_gate,
)


def _workflow(rate=1.5, label="하락장 150% 분할"):
    outcome = build_core_dca_outcome("코어", rate, label)
    decision = {
        "cur_p": 100, "rr_stop": 90, "rr_target": 120, "rr_ratio": 2,
        "ma20": 98, "atr": 5, "grade": "ETF", "t_score": 6,
        "target_w": 10, "current_w": 5, "weight_gap": 5,
        "dec": outcome.label, "decision_code": outcome.code, "decision_group": outcome.group,
    }
    return build_decision_workflow("Vanguard S&P500 ETF", "VOO", decision, is_etf=True, has_pos=True)


def _row(**overrides):
    return {
        "판정코드": "CORE_DRAWDOWN_DCA", "판정분류": "buyish", "R/R": 2,
        "최종읽기": "정밀확인", "🔥기술적 타점": "코어 하락: 하락장 150% 분할",
        **overrides,
    }


def test_normal_drawdown_dca_passes_workflow_and_known_normal_market():
    row = _workflow()
    assert row["판정코드"] == "CORE_DRAWDOWN_DCA"
    assert row["게이트상태"] == GATE_EXECUTABLE
    frame = attach_market_execution_context(pd.DataFrame([row]), {"us_stats": {"mode": "정상"}})
    result = apply_execution_gate_columns(frame).iloc[0]
    assert result["게이트상태"] == GATE_EXECUTABLE
    assert result["🔥기술적 타점"] == row["🔥기술적 타점"]


@pytest.mark.parametrize("override", [
    {"시장실행상태": "시장방어: 신규매수 중단"},
    {"판정코드": "HARD_BLOCK_FINANCIAL_F"},
    {"판정코드": "HARD_BLOCK_OVERWEIGHT"},
    {"판정코드": "HARD_BLOCK_TARGET_FILLED"},
    {"최종읽기": "비중 초과: 추매금지"},
    {"실행메모": "시장위험: 추매중단/보유점검"},
    {"실행메모": "하드차단: 신규진입 금지"},
    {"실행메모": "추매금지"},
    {"🔥기술적 타점": "추세방어"},
    {"🔥기술적 타점": "추세훼손"},
    {"🔥기술적 타점": "역배열 하락추세"},
    {"패턴타점": "STRUCTURE_DAMAGE"},
    {"패턴타점": "구조훼손"},
    {"상위시간대상태": "상위 시간대 경고"},
    {"원천최종읽기": "방어우선"},
])
def test_drawdown_dca_cannot_override_explicit_defense(override):
    assert build_execution_gate(_row(**override))["게이트상태"] == GATE_DEFENSE


@pytest.mark.parametrize("code", ["DRAWDOWN_20_NO_ENTRY", "CORE_DRAWDOWN_DCA_OTHER", "HARD_BLOCK_MACRO_STORM"])
def test_other_drawdown_and_storm_block_codes_remain_defensive(code):
    assert build_execution_gate(_row(**{"판정코드": code}))["게이트상태"] == GATE_DEFENSE


@pytest.mark.parametrize("rate,label", [
    (1, "미국지수 퍼펙트스톰 100% 거치 적립"),
    (0.25, "국장 퍼펙트스톰 25% 방어적 적립"),
])
def test_core_storm_workflow_remains_caution_and_wait(rate, label):
    row = _workflow(rate, label)
    assert row["판정코드"] == "CORE_STORM_DCA"
    assert row["판정분류"] == "caution"
    assert row["게이트상태"] == GATE_WAIT


@pytest.mark.parametrize("override,expected", [
    ({"R/R": 0.5}, GATE_WAIT),
    ({"R/R": float("nan")}, GATE_DATA_CHECK),
    ({"R/R성격": "투영상단"}, GATE_WAIT),
    ({"판정분류": "caution"}, GATE_WAIT),
    ({"시장실행상태": "시장정보 확인 필요: 미국 지수 데이터 미확인"}, GATE_DATA_CHECK),
])
def test_drawdown_dca_still_requires_remaining_execution_checks(override, expected):
    assert build_execution_gate(_row(**override))["게이트상태"] == expected


@pytest.mark.parametrize("rr,display", [(0.996, "0.9960"), (0.42, "0.42")])
def test_rr_below_one_reason_preserves_boundary_and_ordinary_display(rr, display):
    gate = build_execution_gate(_row(**{"R/R": rr}))
    assert gate["게이트상태"] == GATE_WAIT
    assert gate["게이트근거"] == f"R/R {display} < 1"
