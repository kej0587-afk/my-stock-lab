"""Exercise the production timing wrapper without account or provider initialization."""

import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest


def app_source():
    path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_today_queue_tab")
    return '''
import inspect
import json
import logging
from contextlib import nullcontext
from time import perf_counter
import numpy as np
import pandas as pd
import streamlit as st
from stock_lab_core.performance import PerformanceTrace, measure
SCRIPT_RUN_STARTED = perf_counter()
KR_CLUSTER_SCOPED_PREFETCH_AVAILABLE = True
IS_PUBLIC_DEMO = True
CURRENT_USER_EMAIL = None
kr_cluster_snapshot_scope = lambda **kwargs: nullcontext()
get_report_build_info = lambda *args: {}
if st.session_state.get("old_trace", False):
    class LegacyTrace(PerformanceTrace):
        def __init__(self, *, scope):
            super().__init__(scope=scope)
    PerformanceTrace = LegacyTrace

def _render_today_queue_tab(mode):
    if st.session_state.get("fail", False):
        with measure("phase", "price_history_10y"):
            raise ValueError("controlled provider failure")
    if st.session_state.get("calculate", False):
        with measure("phase", "summary"):
            with measure("prices", "local_frame"):
                pass
''' + ast.unparse(wrapper) + '''
try:
    render_today_queue_tab("test")
except ValueError as exc:
    st.warning(str(exc))
'''


def test_first_cached_render_does_not_hide_timing_panel():
    app = AppTest.from_string(app_source()).run(timeout=15)
    assert not app.exception
    assert any(item.label == "계산 시간 상세" for item in app.expander)
    assert len(app.metric) == 3
    assert any("종목 신호는 재계산하지 않았습니다" in item.value for item in app.caption)
    assert app.session_state["today_queue_last_attempt_performance"]["measurement_status"] == "completed"


def test_failed_attempt_keeps_diagnostics_and_downloads_them_on_next_render():
    app = AppTest.from_string(app_source())
    app.session_state["fail"] = True
    app.run(timeout=15)
    assert not app.exception
    attempt = app.session_state["today_queue_last_attempt_performance"]
    assert attempt["measurement_status"] == "failed"
    assert attempt["current_phase"] == "price_history_10y"
    assert any("진행: 장기 시세 조회" in item.value for item in app.caption)
    app.session_state["fail"] = False
    app.run(timeout=15)
    assert not app.exception
    assert len(app.get("download_button")) == 1
    assert any("직전 실행: failed" in item.value for item in app.caption)


def test_previous_calculation_and_legacy_trace_remain_compatible():
    app = AppTest.from_string(app_source())
    app.session_state["calculate"] = True
    app.run(timeout=15)
    assert not app.exception
    completed = dict(app.session_state["today_queue_performance"])
    app.session_state["calculate"] = False
    app.session_state["old_trace"] = True
    app.run(timeout=15)
    assert not app.exception
    assert app.session_state["today_queue_performance"] == completed
    assert any("이전 계산의 측정값" in item.value for item in app.caption)
