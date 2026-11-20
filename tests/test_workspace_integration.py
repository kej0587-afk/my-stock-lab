"""Framework changes preserve calculations and avoid hidden data refresh."""

import ast
from pathlib import Path
import subprocess

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_stress_calculator_extraction_is_identical_to_approved_body():
    previous = subprocess.check_output(
        ["git", "show", "2fbf3134:app.py"], cwd=ROOT,
    ).decode("utf-8-sig")
    old = next(node for node in ast.parse(previous).body
               if isinstance(node, ast.FunctionDef) and node.name == "render_scenario_check_tab")
    current = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    new = next(node for node in current.body
               if isinstance(node, ast.FunctionDef) and node.name == "render_portfolio_stress_scenario")
    assert ast.dump(old.args) == ast.dump(new.args)
    assert [ast.dump(n) for n in old.body[1:]] == [ast.dump(n) for n in new.body]


def test_shared_brief_is_connected_to_four_views_and_both_precision_paths():
    app = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    assert 'source="오늘점검", key="today_decision_brief_ticker"' in app
    assert 'source="전광판", key="dashboard_decision_brief_ticker"' in app
    assert app.count('c.get("execution_workflow"), source="정밀관측소"') == 2
    portfolio = (ROOT / "stock_lab_core/portfolio_holding_review.py").read_text(encoding="utf-8")
    renderer = next(node for node in ast.parse(portfolio).body
                    if isinstance(node, ast.FunctionDef) and node.name == "render_portfolio_holding_review")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "render_decision_brief" for n in ast.walk(renderer))


def test_macro_snapshot_controls_fetch_only_on_explicit_refresh():
    app = AppTest.from_string('''
import streamlit as st
import pandas as pd
from unittest.mock import patch
from stock_lab_core import macro_monitor as m
st.session_state.setdefault("requests", 0)
st.session_state.setdefault("original_gate", {"score": 9, "decision": "blocked"})
def load(*args):
    st.session_state.requests += 1
    return {x.symbol: (pd.Series([10., 11.], index=pd.to_datetime(["2026-11-18", "2026-11-19"])), "fixture") for x in m.METRICS}
with patch.object(m, "load_group", side_effect=load):
    m.render_macro_monitor(st, explicit_refresh=True, now=pd.Timestamp("2026-11-20T13:00+09:00"))
''').run()
    assert not app.exception and app.session_state["requests"] == 0
    app.button(key="macro_monitor_refresh").click().run()
    assert not app.exception and app.session_state["requests"] == 1
    assert all("저장 시점 기준" in value and "현재 미재검증" in value
               for value in app.dataframe[0].value["상태"])
    app.selectbox(key="macro_monitor_주요 시장_symbol").set_value("^IXIC").run()
    app.radio(key="macro_monitor_mode").set_value("기간 내 고점 대비").run()
    assert not app.exception and app.session_state["requests"] == 1
    app.radio(key="macro_monitor_group").set_value("연준·재무부").run()
    assert not app.exception and app.session_state["requests"] == 1
    app.button(key="macro_monitor_refresh").click().run()
    assert app.session_state["requests"] == 2
    app.radio(key="macro_monitor_group").set_value("주요 시장").run()
    assert not app.exception and app.session_state["requests"] == 2
    assert len(app.get("plotly_chart")) == 1
    app.selectbox(key="macro_monitor_years").set_value(3).run()
    assert app.session_state["requests"] == 2 and not app.get("plotly_chart")
    assert app.session_state["original_gate"] == {"score": 9, "decision": "blocked"}


def test_precision_raw_gate_is_labelled_screening_not_final_permission():
    from stock_lab_core.decision_governance import role_rows
    row = role_rows({}, {"게이트상태": "실행가능"}, 4, {})[-1]
    assert row["구분"] == "종목 선별 게이트 · 최종 체크 전"
    assert row["평가"] == "실행가능"
