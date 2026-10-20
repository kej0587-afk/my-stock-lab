"""Offline UI checks using public test fixtures, never account initialization."""

import ast
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from stock_lab_core.decision_workflow import align_precision_final_check_rows
from stock_lab_core.execution_gate import GATE_DEFENSE, GATE_DATA_CHECK, GATE_EXECUTABLE, GATE_WATCH_ONLY
from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_view import render_market_report


st.set_page_config(page_title="Stock Lab 검증 미리보기", layout="wide")
tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
names = {"_safe_execution_workflow_row", "render_precision_execution_state"}
for function in tree.body:
    if isinstance(function, ast.FunctionDef) and function.name in names:
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), globals())

sample_path = ROOT / "docs/samples/market_report_readability_20261021.md"
if sample_path.exists():
    report = sample_path.read_text(encoding="utf-8")
else:
    fixture = runpy.run_path(str(ROOT / "tests/test_report_critique_readability.py"))
    context, summary_rows = fixture["report_case"]()
    report = build_auto_market_memo(report_context=context, summary_rows=summary_rows, now=fixture["NOW"])
precision_fixture = runpy.run_path(str(ROOT / "tests/test_precision_workflow_review.py"))
precision = precision_fixture["msft_review"].__wrapped__()
report_tab, precision_tab = st.tabs(["시황 표 검증", "MSFT 설명 검증"])
with report_tab:
    st.caption("회귀 테스트용 입력으로 생성한 표시 검증 예시입니다. 실제 계좌 리포트나 최신 시세가 아닙니다.")
    render_market_report(report)
with precision_tab:
    st.caption("첨부 MSFT 검토 자료의 문제를 재현한 회귀 테스트 입력입니다. 판정과 가격은 변경하지 않았습니다.")
    decision = precision["decision"]
    render_precision_execution_state(decision["execution_workflow"])
    st.dataframe(pd.DataFrame([{"후보품질": decision["grade"], "기술적 원신호": decision["dec"],
                               "R/R": decision["rr_ratio"], "최종 체크": precision["final_check"]["summary"]["final_label"]}]),
                 hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame(align_precision_final_check_rows(
        precision["final_check"]["rows"], decision["execution_workflow"])), hide_index=True, width="stretch",
        row_height=64, height=754)
