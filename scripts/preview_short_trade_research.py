"""Local visual QA of the real generic renderer; public data, no account writes."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from stock_lab_core.short_trade_view import render_symbol_research

st.set_page_config(page_title="단기 검증 공통 화면", layout="wide")
st.title("단기 전략 검증")
st.caption("로컬 화면 검증 · 실제 공개 가격 조회 · 계좌/주문 연결 없음")
ticker = st.selectbox("종목", ["MSFT", "005930.KS", "418660.KS", "RAM", "BITX", "SOXL"])
render_symbol_research(st, ticker, {"execution_workflow": {
    "게이트상태": "방어우선", "게이트근거": "기존 판정 유지(화면 검증용)"}})
