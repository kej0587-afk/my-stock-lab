"""Holding suitability never independently authorizes a blocked entry."""

from copy import deepcopy

import pytest

from stock_lab_core.decision_workflow import qualify_hold_action_plan
from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT


@pytest.mark.parametrize("gate", [GATE_DATA_CHECK, GATE_DEFENSE, GATE_WAIT, "관망", ""])
def test_hold_plan_retains_assessment_but_defers_to_entry_gate(gate):
    action = "장기 보유 유효 (목표 비중까지 분할 매수 가능)"
    workflow = {"게이트상태": gate, "게이트근거": "시장방어: 신규매수 중단"}
    original = deepcopy(workflow)
    result = qualify_hold_action_plan(action, workflow)
    assert result.startswith("현재 신규·추가매수는 실행 보류")
    assert "시장방어: 신규매수 중단" in result
    assert "현재 매수 허가가 아닙니다" in result
    assert action in result
    assert workflow == original


def test_executable_hold_plan_is_unchanged_and_missing_gate_is_not_permission():
    action = "장기 보유 유효 (목표 비중까지 분할 매수 가능)"
    assert qualify_hold_action_plan(action, {"게이트상태": GATE_EXECUTABLE}) == action
    assert "실행 게이트 미확인" in qualify_hold_action_plan(action, None)


def test_split_hold_and_entry_reads_separately():
    from stock_lab_core.decision_workflow import split_hold_and_entry
    action = "장기 보유 유효 (목표 비중까지 분할 매수 가능)"
    blocked = split_hold_and_entry(action, {"게이트상태": GATE_WAIT, "게이트근거": "과열/추격금지"})
    assert blocked == {"hold": "장기 보유 유효", "entry": "보류 · 과열/추격금지", "entry_executable": False}
    assert split_hold_and_entry(action, None)["entry"] == "보류 · 실행 게이트 미확인"
    ok = split_hold_and_entry("비중 축소 검토", {"게이트상태": GATE_EXECUTABLE}, reduce_side=True)
    assert ok["entry_executable"] and "보유분 점검이 먼저" in ok["entry"]
