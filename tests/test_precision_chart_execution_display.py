"""Exercise the actual chart boundary offline, without importing the app script."""

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import pytest

from stock_lab_core import chart_structure
from stock_lab_core.chart_execution import build_chart_execution_check_rows, build_chart_execution_guide, chart_latest_close
from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE
from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.precision_chart_view import build_price_figure, finish_price_figure
from tests.test_chart_structure import event_context, wave


@pytest.fixture(scope="module")
def renderer_nodes():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig")
    return [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in {
        "render_precision_candlestick_chart", "render_precision_execution_state",
    }]


def passed(**changes):
    return dict(execution_allowed=True, block_count=0, core_missing_ids=[], action="최종 확인 통과", **changes)


@pytest.mark.parametrize("final,gate", [
    (None, GATE_EXECUTABLE),
    ({}, GATE_EXECUTABLE),
    ({"execution_allowed": True}, GATE_EXECUTABLE),
    ({**passed(), "execution_allowed": False, "action": "최종 체크 대기"}, GATE_EXECUTABLE),
    ({**passed(), "core_missing_ids": ["overheat"], "action": "과열 자료 확인"}, GATE_EXECUTABLE),
    ({**passed(), "block_count": 1, "action": "최종 체크 차단"}, GATE_EXECUTABLE),
    (passed(), GATE_EXECUTABLE),
    (passed(), GATE_DEFENSE),
])
def test_final_readiness_controls_headline_event_caption_and_checklist(renderer_nodes, monkeypatch, final, gate):
    captions, messages, tables = [], [], []
    ui = SimpleNamespace(caption=captions.append, info=messages.append, warning=messages.append,
                         error=messages.append, markdown=lambda *a, **k: None,
                         dataframe=lambda frame, **kwargs: tables.append(frame), plotly_chart=lambda *a, **k: None)
    structure = dict(event_context(), channel={}, patterns=[{
        "name": "쌍바닥", "direction": "bullish", "trigger_price": 105, "lifecycle": "현재유효",
    }])
    original_structure = deepcopy(structure)
    namespace = dict(pd=pd, go=go, st=ui, GATE_DATA_CHECK=GATE_DATA_CHECK, GATE_DEFENSE=GATE_DEFENSE,
                     GATE_EXECUTABLE=GATE_EXECUTABLE, build_price_figure=build_price_figure,
                     finish_price_figure=finish_price_figure,
                     build_chart_execution_check_rows=build_chart_execution_check_rows,
                     build_chart_execution_guide=build_chart_execution_guide, chart_latest_close=chart_latest_close,
                     _cached_chart_structure=lambda _: structure,
                     detect_chart_pattern_candidates=lambda _: pytest.fail("Already computed"),
                     _build_recent_trendline_guides=lambda _: [],
                     _add_recent_trendline_guides=lambda *a, **k: None,
                     _add_chart_pattern_overlays=lambda *a: None,
                     _trendline_guides_caption=lambda _: "", _chart_pattern_caption=lambda _: "")
    exec(compile(ast.Module(body=renderer_nodes, type_ignores=[]), "app.py", "exec"), namespace)
    monkeypatch.setattr(chart_structure, "last_bar_is_provisional", lambda *a: False)
    monkeypatch.setattr(chart_structure, "latest_completed_chart_session", lambda *a: "2026-10-21")
    monkeypatch.setattr(chart_structure, "chart_date_breaks", lambda *a: [])
    decision = {"execution_workflow": {"게이트상태": gate, "게이트근거": "선별 단계 근거"},
                "chart_final_check": final, "chart_price_asof": "2026-10-21",
                "rr_ratio": 2, "rr_stop": 90, "rr_target": 120, "grade": "A", "t_score": 8}
    original = deepcopy(decision)
    frame = wave(60)
    frame.index = pd.bdate_range(end="2026-10-21", periods=len(frame))
    original_frame = frame.copy(deep=True)
    expected = build_execution_readiness(decision["execution_workflow"], final)
    namespace["render_precision_execution_state"](decision["execution_workflow"], final)
    result = namespace["render_precision_candlestick_chart"](
        frame, ticker="TEST", key="audit_day", decision_context=decision,
        show_liquidity=False, show_smc=False, show_channel=False,
    )
    assert messages[0] == f"현재 실행 판단: {expected['label']} · {expected['reason']}"
    assert f"현재 실행: {expected['display_workflow']['게이트상태']} · {expected['reason']}" in captions
    event = result["events"][0]
    assert event["execution_allowed"] is expected["execution_allowed"]
    if not expected["execution_allowed"]:
        assert event["label"] == "매수형·보류" and event["execution"] == expected["reason"]
    rows = tables[-1].to_dict("records")
    assert (rows[0]["상태"] == "통과") is expected["execution_allowed"]
    assert rows[0]["해석"] == expected["reason"]
    if not expected["execution_allowed"]:
        assert next(row for row in rows if row["조건"] == "기준선 돌파")["다음 행동"] == expected["reason"]
    assert "R/R 2.00" in next(row for row in rows if row["조건"] == "손익비 확인")["기준"]
    assert decision == original and structure == original_structure
    pd.testing.assert_frame_equal(frame, original_frame)


def test_direct_checklist_call_qualifies_a_copy_without_hiding_technical_pass():
    decision = {"execution_workflow": {"게이트상태": GATE_EXECUTABLE, "게이트근거": "선별 통과"},
                "chart_final_check": {**passed(), "execution_allowed": False, "action": "최종 체크 대기"}}
    original = deepcopy(decision)
    rows = build_chart_execution_check_rows(
        wave(), [{"name": "쌍바닥", "direction": "bullish", "trigger_price": 100}], [], {}, None, "TEST", decision,
    )
    assert rows[0]["상태"] == "대기"
    trigger = next(row for row in rows if row["조건"] == "기준선 돌파")
    assert trigger["상태"] == "통과" and trigger["다음 행동"] == "최종 체크 대기"
    assert decision == original
