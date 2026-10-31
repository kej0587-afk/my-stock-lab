"""Unrounded R/R must reach every execution predicate and its display."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.decision_engine import build_rr_context
from stock_lab_core.decision_workflow import attach_market_execution_context, build_decision_workflow
from stock_lab_core.execution_gate import GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT, apply_execution_gate_columns
from stock_lab_core.formatters import format_rr_ratio
from stock_lab_core.today_queue import build_today_queue_execution_snapshot


@pytest.mark.parametrize("ratio", [.994, .995, .996, .9999, .9999999, 1., 1.004, 1.5, 2.])
def test_rr_context_and_workflow_preserve_boundary_precision(ratio):
    frame = pd.DataFrame({"High": [102.5] * 20, "Low": [97.5] * 20, "Close": [100.] * 20})
    target = 100 + 10 * ratio
    context = build_rr_context(frame, 100, {"int_high": target, "ext_high": target + 20})
    assert context["rr_ratio"] == pytest.approx(ratio)
    decision = dict(grade="A", t_score=8, dec="신규진입: 대장주 포착", decision_code="NEW_ENTRY_LEADER",
                    decision_group="buyish", cur_p=100, rr_stop=90, rr_target=target,
                    rr_ratio=context["rr_ratio"], ma20=98, atr=5)
    original = deepcopy(decision)
    snapshot = build_today_queue_execution_snapshot("Test", "TEST", decision)
    assert snapshot["RR값"] == pytest.approx(ratio)
    assert (snapshot["RR값"] < 1) is (ratio < 1)
    row = build_decision_workflow("Test", "TEST", decision)
    normal = {"us_stats": {"mode": "정상"}}
    result = apply_execution_gate_columns(attach_market_execution_context(pd.DataFrame([row]), normal)).iloc[0]
    assert result["게이트상태"] == (GATE_WAIT if ratio < 1 else GATE_EXECUTABLE)
    if ratio < 1:
        assert snapshot["R/R"] != "1.00"
        assert "R/R 1.00 < 1" not in result["게이트근거"]
    danger = apply_execution_gate_columns(attach_market_execution_context(
        pd.DataFrame([row]), {"mode": "위험", **normal})).iloc[0]
    assert danger["게이트상태"] == GATE_DEFENSE
    assert decision == original


@pytest.mark.parametrize("number,expected", [(None, "-"), (float("nan"), "-"),
    (2, "2.00"), (.5, "0.50"), (.996, "0.9960"), (.9999999, "<1.00"), (1, "1.00")])
def test_rr_display_never_rounds_up_a_sub_one_ratio(number, expected):
    assert format_rr_ratio(number) == expected
