"""Present existing gate/final-check results without scoring them again."""

from collections.abc import Mapping
from copy import deepcopy
from numbers import Real

from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT,
)
from stock_lab_core.report_build import register_loaded_source


def build_execution_readiness(workflow, final_check=None):
    workflow = dict(workflow) if isinstance(workflow, Mapping) else {}
    gate = workflow.get("게이트상태")
    gate = gate if isinstance(gate, str) else None
    final = final_check if isinstance(final_check, Mapping) else {}
    checked = bool(final)
    # Consume the computed permission, never infer it from a positive label.
    blocks = final.get("block_count")
    allowed = (gate == GATE_EXECUTABLE and final.get("execution_allowed") is True
               and isinstance(blocks, Real) and not isinstance(blocks, bool)
               and blocks == 0 and isinstance(final.get("core_missing_ids"), list)
               and not final["core_missing_ids"])
    if gate != GATE_EXECUTABLE:
        state, label = "restricted", "실행 보류"
        reason = workflow.get("게이트근거") or "실행 게이트 재확인 필요"
        display_gate = gate or GATE_DATA_CHECK
    elif not checked:
        state, label = "pending", "정밀확인 대상 · 최종 체크 전"
        reason = "최종 체크 결과 미확인"
        display_gate = GATE_DATA_CHECK
    elif allowed:
        state, label = "review_ready", final.get("final_label") or "정밀확인"
        reason = final.get("action") or "최종 체크 통과 · 사용자 최종 판단"
        display_gate = gate
    else:
        state, label = "restricted", "실행 보류"
        reason = final.get("action") or "최종 체크 실행 허용 미확인"
        display_gate = GATE_DATA_CHECK if final.get("core_missing_ids") or "execution_allowed" not in final else GATE_WAIT
        if final.get("final_label") == "매수 금지":
            display_gate = GATE_DEFENSE
    display_workflow = dict(workflow)
    display_workflow.update({"게이트상태": display_gate, "게이트근거": reason})
    return {
        "state": state, "execution_allowed": allowed,
        "label": label, "reason": reason,
        "screening_gate": gate or "미확인",
        "final_check_label": final.get("final_label") or "미점검",
        "display_workflow": display_workflow,
    }


def execution_guidance_fields(workflow):
    """Queue screening is a nomination, not a completed precision check."""
    ready = build_execution_readiness(workflow)
    return {
        "현재실행안내": ready["label"] + " · " + ready["reason"],
        "현재진입조건": "정밀관측소 최종 체크 후 원계획 재검토" if ready["state"] == "pending"
        else "실행 제한 해소 후 원계획 재검토",
    }


def precision_display_context(decision):
    """Copy only the presentation context; preserve captured decisions/plans."""
    workflow = decision.get("execution_workflow")
    if "chart_final_check" not in decision and (
        not isinstance(workflow, Mapping) or "게이트상태" not in workflow
    ):
        return decision
    out = dict(decision)
    ready = build_execution_readiness(workflow, out.get("chart_final_check"))
    out["execution_workflow"] = deepcopy(ready["display_workflow"])
    return out


register_loaded_source(__name__, __file__)
