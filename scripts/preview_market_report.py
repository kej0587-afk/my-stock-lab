"""Offline web preview of the public example, never loads account data."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from stock_lab_core.chart_scorecard import render_chart_scorecard, render_volume_review

st.set_page_config(page_title="Stock Lab 리포트 미리보기", layout="wide")
report_tab, chart_tab = st.tabs(["리포트", "차트 지표 예시"])
with report_tab:
    st.markdown((ROOT / "docs/samples/market_report_20261018_v3.md").read_text(encoding="utf-8"))
with chart_tab:
    st.caption("화면 확인용 합성 가격·재무 데이터. 실제 종목/매매 판단 자료가 아닙니다.")
    close = 100 + np.arange(300) * .1 + np.sin(np.arange(300) / 8) * 3
    frame = pd.DataFrame({"Open": close - .3, "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": 1000 + (np.arange(300) % 17) * 90},
                         index=pd.bdate_range("2025-08-25", periods=300))
    render_chart_scorecard(st, frame, info={"returnOnEquity": .18, "profitMargins": .12,
        "revenueGrowth": .15, "trailingPE": 20, "currentRatio": 1.8,
        "trailingAnnualDividendYield": .02, "payoutRatio": .3}, source="합성 예시")
    st.plotly_chart(go.Figure(go.Candlestick(x=frame.index, open=frame.Open, high=frame.High,
                    low=frame.Low, close=frame.Close)).update_layout(height=360, xaxis_rangeslider_visible=False), width="stretch")
    render_volume_review(st, frame, "TEST")
