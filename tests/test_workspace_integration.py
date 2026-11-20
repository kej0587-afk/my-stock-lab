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


def test_scenario_selection_survives_widget_cleanup_and_scope_changes():
    app = AppTest.from_string('''
import streamlit as st
from unittest.mock import patch
from stock_lab_core import decision_workspace as w
from stock_lab_core.decision_brief import build_decision_brief
page = st.radio("Page", ["scenario", "chart"], key="page")
scope = st.selectbox("Account", ["one", "two"], key="scope")
st.session_state.setdefault("raw_gate", {"score": 9, "decision": "blocked"})
if page == "scenario":
    tickers = ["MSFT", "SOXL"] if scope == "one" else ["QQQ"]
    briefs = [build_decision_brief({"티커": t}, source=s,
        calculated_at="2026-11-20T05:00:00Z")
        for t in tickers for s in ["오늘점검", "정밀관측소"]]
    with patch.object(w, "collect_decision_briefs", return_value=briefs):
        w.render_scenario_workspace(st, context=scope)
''').run()
    app.selectbox(key="scenario_decision_ticker").set_value("SOXL").run()
    app.radio(key="scenario_decision_source").set_value("정밀관측소").run()
    app.radio(key="page").set_value("chart").run()
    assert "scenario_decision_ticker" not in app.session_state.filtered_state
    app.radio(key="page").set_value("scenario").run()
    assert not app.exception
    assert app.selectbox(key="scenario_decision_ticker").value == "SOXL"
    assert app.radio(key="scenario_decision_source").value == "정밀관측소"
    app.selectbox(key="scope").set_value("two").run()
    assert not app.exception
    assert app.selectbox(key="scenario_decision_ticker").value == "QQQ"
    assert app.radio(key="scenario_decision_source").value == "오늘점검"
    assert app.session_state["raw_gate"] == {"score": 9, "decision": "blocked"}


def test_clock_format_converts_only_timezone_aware_instants():
    from stock_lab_core.formatters import format_zoned_timestamp
    assert format_zoned_timestamp("2026-11-20T05:16:13.709717+00:00") == "2026-11-20 14:16:13 KST"
    assert format_zoned_timestamp("2026-11-20 14:17:51 KST") == "2026-11-20 14:17:51 KST"
    assert format_zoned_timestamp("2026-11-20 05:00:00") == "2026-11-20 05:00:00"
    assert format_zoned_timestamp(None) == "미확인"
