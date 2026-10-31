"""Public screenshot-price replay; no login, holdings, database or live I/O."""

from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from stock_lab_core.report_dashboard import current_state_lines
from stock_lab_core.report_intraday import extended_quote_text
from stock_lab_core.report_quotes import extended_quote_observation
from stock_lab_core.report_session import market_session_states


st.set_page_config(page_title="Stock Lab 새벽 수치 검증", layout="wide")
st.title("새벽 수치 검증")
st.caption("10/31 첨부 화면 가격 재현입니다. 현재 시세·실제 계좌가 아니며 네트워크 조회를 하지 않습니다.")

now = datetime.fromisoformat("2026-10-31T07:16:00+09:00")
context = {"sessions": {"KR": "2026-10-30", "US": "2026-10-30"}, "prices": {}, "extended_prices": {}}
rows = []
for ticker, previous, closed, latest in (("SOXX", 513.86, 471.51, 472.21), ("DRAM", 51.75, 48.01, 48.14)):
    quote = {"symbol": ticker, "regularMarketPrice": closed, "regularMarketPreviousClose": previous,
             "regularMarketTime": datetime.fromisoformat("2026-10-30T16:00:00-04:00").timestamp(),
             "postMarketPrice": latest, "postMarketTime": (now - timedelta(minutes=1)).timestamp(),
             "postMarketChangePercent": (latest / closed - 1) * 100}
    context["extended_prices"][ticker] = extended_quote_observation(quote, ticker, now)
    context["prices"][ticker] = {"date": "2026-10-30", "previous_date": "2026-10-29",
                                  "price": closed, "return": closed / previous - 1}
    rows.append(f"{ticker} | ${previous:.2f} | ${closed:.2f} | ${latest:.2f} | {(latest / previous - 1) * 100:+.2f}% | {(latest / closed - 1) * 100:+.2f}%")

st.subheader("미국 현재 · 애프터마켓")
st.markdown(current_state_lines(context, market_session_states(now), now, {})[1])
st.markdown("종목 | 전일 종가(10/29) | 정규장 종가(10/30) | 시간외 관측 | 전일 종가 대비 | 마감 후 추가 등락\n"
            "--- | --- | --- | --- | --- | ---\n" + "\n".join(rows))
for ticker in context["extended_prices"]:
    st.markdown(f"**{ticker}** · " + extended_quote_text(context, ticker, now))
st.caption("마감 후 상승은 정규장 종가 대비입니다. 전일 종가 대비 하락과 동시에 나타날 수 있습니다.")
