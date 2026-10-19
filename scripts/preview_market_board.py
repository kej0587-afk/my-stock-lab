"""Offline UI verification; optional actual public price lookup, no account access."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import streamlit as st

from stock_lab_core.market_board import market_instruments, render_market_board

st.set_page_config(page_title="Stock Lab 시장판", layout="wide")
mode = st.radio("자료", ("화면 검증(합성)", "실제 조회"), horizontal=True)
frames = None
if mode == "화면 검증(합성)":
    st.warning("화면 검증용 합성 가격입니다. 실제 시세·수익률 또는 투자 판단 자료가 아닙니다.")
    dates = pd.bdate_range(end=pd.Timestamp.now(tz="UTC").tz_localize(None).normalize(), periods=100)
    frames = {}
    for market in ("KR", "US", "CRYPTO"):
        for scope in ("basket", "stocks"):
            for index, item in enumerate(market_instruments(market, scope)):
                move = (index % 11 - 5) * .008
                values = 100 + np.arange(len(dates)) * .04
                values[-1] = values[-2] * (1 + move)
                frames[item.ticker] = pd.DataFrame({"Close": values}, index=dates)
render_market_board(st, key="preview", frames=frames)
