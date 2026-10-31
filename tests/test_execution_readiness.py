"""One presentation authority, without changing scores or re-running checks."""

from copy import deepcopy
import io
import json
import zipfile

import pandas as pd
import pytest

from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT, apply_execution_gate_columns,
)
from stock_lab_core.execution_readiness import (
    build_execution_readiness, execution_guidance_fields, precision_display_context,
)
from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.precision_review_export import build_precision_review_export_zip
from tests.test_decision_governance import _decision
from tests.test_precision_plan_panel import display_app


def _passed(**overrides):
    return {"final_label": "분할 가능", "execution_allowed": True, "block_count": 0,
            "core_missing_ids": [], "action": "분할 검토", **overrides}


@pytest.mark.parametrize("gate", [GATE_EXECUTABLE, GATE_DEFENSE, GATE_DATA_CHECK, GATE_WAIT, "", None])
@pytest.mark.parametrize("final", [None, {}, {"final_label": "분할 가능"},
    _passed(execution_allowed=False), _passed(execution_allowed="True"),
    _passed(block_count=1), _passed(core_missing_ids=["overheat"]), _passed()])
def test_only_both_computed_permissions_can_be_review_ready(gate, final):
    workflow = {"게이트상태": gate, "게이트근거": "기존 제한", "실행메모": "분할 가능"}
    before = deepcopy((workflow, final))
    result = build_execution_readiness(workflow, final)
    expected = gate == GATE_EXECUTABLE and final == _passed()
    assert result["execution_allowed"] is expected
    assert (result["display_workflow"]["게이트상태"] == GATE_EXECUTABLE) is expected
    assert (workflow, final) == before


def test_queue_guidance_preserves_original_memo_and_conditions_without_allowing_entry():
    raw = pd.DataFrame([{
        "티커": "GOOGL", "판정분류": "buyish", "최종읽기": "✅정밀확인", "R/R": 2.0,
        "실행메모": "분할 가능", "1차조건": "현재 보유분 유지, 추가 1차는 소액만",
        "시장실행상태": "시장방어: 신규매수 중단",
    }], index=[7])
    before = raw.copy(deep=True)
    out = apply_execution_gate_columns(raw)
    assert out.loc[7, "게이트상태"] == GATE_DEFENSE
    assert out.loc[7, "현재실행안내"].startswith("실행 보류")
    assert "시장방어" in out.loc[7, "현재실행안내"]
    assert out.loc[7, "실행메모"] == before.loc[7, "실행메모"]
    assert out.loc[7, "1차조건"] == before.loc[7, "1차조건"]
    pd.testing.assert_frame_equal(raw, before)
    pd.testing.assert_frame_equal(apply_execution_gate_columns(out), out)
    out.loc[7, "시장실행상태"] = "정상"
    released = apply_execution_gate_columns(out)
    assert released.loc[7, "게이트상태"] == GATE_EXECUTABLE
    assert "최종 체크 전" in released.loc[7, "현재실행안내"]
    assert not build_execution_readiness(released.loc[7].to_dict())["execution_allowed"]


def test_display_context_is_not_used_to_rewrite_the_captured_gate():
    decision = {"execution_workflow": {"게이트상태": GATE_EXECUTABLE, "RR값": 2.0},
                "chart_final_check": _passed(execution_allowed=False, final_label="대기"), "grade": "A", "t_score": 8}
    before = deepcopy(decision)
    displayed = precision_display_context(decision)
    assert displayed["execution_workflow"]["게이트상태"] == GATE_WAIT
    assert displayed["grade"] == "A" and displayed["t_score"] == 8
    assert decision == before


@pytest.mark.parametrize("workflow", [None, {}, {"유형": "ETF"}])
def test_final_check_without_its_gate_is_not_permission(workflow):
    decision = {"execution_workflow": workflow, "chart_final_check": _passed()}
    before = deepcopy(decision)
    displayed = precision_display_context(decision)
    assert displayed["execution_workflow"]["게이트상태"] == GATE_DATA_CHECK
    assert decision == before


@pytest.mark.parametrize("missing", ["mfi", "rsi", "pct_b"])
def test_real_final_veto_controls_plan_narrative_and_export(display_app, monkeypatch, missing):
    app, ui = display_app
    monkeypatch.setattr(app, "get_valuation_headline_for_final_check",
                        lambda *args, **kwargs: ("가격매력 우수", "", 20.0))
    decision = _decision()
    decision.pop(missing)
    decision["execution_workflow"] = build_decision_workflow("Test", "TEST", decision)
    assert decision["execution_workflow"]["게이트상태"] == GATE_EXECUTABLE
    rows, summary = app.build_pre_buy_final_checks("Test", "TEST", False, decision, 4, False, 0)
    assert summary["execution_allowed"] is False and "overheat" in summary["core_missing_ids"]
    decision["chart_final_check"] = summary
    decision["execution_readiness"] = build_execution_readiness(decision["execution_workflow"], summary)
    before = deepcopy(decision)
    plan = app.render_entry_execution_plan("Test", "TEST", decision)
    assert plan["display_status"] == "실행 보류"
    assert "실행 보류" in plan["rows"][1]["조건"]
    assert "실행 보류" in app.build_precision_narrative("Test", "TEST", decision, 4, False, 0)
    payload = build_precision_review_export_zip(
        selected_ticker="TEST", result_ticker="TEST", decision=decision,
        final_check={"rows": rows, "summary": summary}, entry_plan=plan,
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        sections = json.loads(archive.read("snapshot.json"))["sections"]
    assert sections["execution_readiness"]["execution_allowed"] is False
    assert "display_workflow" not in sections["execution_readiness"]
    assert sections["execution_workflow"]["게이트상태"] == GATE_EXECUTABLE
    assert "execution_readiness" not in sections["main_decision"]
    assert decision == before


def test_no_final_check_does_not_publish_an_executable_plan(display_app):
    app, _ = display_app
    decision = _decision()
    decision["execution_workflow"] = build_decision_workflow("Test", "TEST", decision)
    plan = app.render_entry_execution_plan("Test", "TEST", decision)
    assert plan["display_status"] == "실행 보류"
    assert "최종 체크 결과 미확인" in plan["display_note"]


def test_unknown_guidance_does_not_turn_into_an_entry_command():
    assert "실행 보류" in execution_guidance_fields({})["현재실행안내"]


@pytest.mark.parametrize("final", [None, _passed(execution_allowed=False), _passed()])
def test_leveraged_hold_branch_uses_the_same_permission(display_app, monkeypatch, final):
    app, ui = display_app
    monkeypatch.setattr(ui, "caption", lambda *args, **kwargs: None, raising=False)
    class Metric:
        def metric(self, *args, **kwargs):
            pass
    monkeypatch.setattr(ui, "columns", lambda n: [Metric() for _ in range(n)], raising=False)
    state = {"dca_stage": "약하락 DCA 후보", "dca_note": "소액 회차만 열고, MA50 아래에서는 확대하지 않습니다."}
    monkeypatch.setattr(app, "build_leveraged_precision_state", lambda *args: state)
    decision = _decision(execution_workflow={"게이트상태": GATE_EXECUTABLE}, chart_final_check=final)
    original = deepcopy(decision)
    held = app.render_hold_or_cut_panel("SOXL", "SOXL", True, 0, {}, decision, 100, True)
    assert ("현재 신규·추가매수는 실행 보류" in held["action"]) is (final != _passed())
    assert held["action"] in ui.markdowns[-1]
    assert state["dca_note"] in held["action"] and decision == original
