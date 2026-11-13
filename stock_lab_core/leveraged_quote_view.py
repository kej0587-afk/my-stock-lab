"""Read-only quote evidence, separate from scalar decision inputs."""

from datetime import datetime, timezone

import pandas as pd

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_quotes import (
    extended_quote_observation, extended_quote_status, load_us_report_quote,
)

PRODUCTS = frozenset({"SOXL", "RAM", "BITX", "418660.KS"})
VERSION = "quote-evidence-v1"


def quote_evidence(ticker, quote, now):
    """Missing/old/another-session observations never acquire a current price."""
    if ticker == "418660.KS":
        return {"status": "한국 상장 상품: 미국 데이마켓·애프터 시세를 적용하지 않음"}
    observation = extended_quote_observation(quote, ticker, now)
    if not observation:
        return {"status": extended_quote_status(quote, ticker, now)}
    return {
        "status": "연결됨", "session": observation["kind"],
        "price": observation["price"], "change": observation["return"] * 100,
        "as_of": pd.Timestamp(observation["as_of"]).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S KST"),
        "base": observation["previous_date"], "source": observation["source"],
    }


def render_quote_evidence(st, ticker, *, manual_price=0, now=None, fetch_quote=load_us_report_quote):
    if ticker not in PRODUCTS:
        return
    # Only the selected US product is fetched, using the existing 60s/15s cache.
    quote = fetch_quote(ticker) if ticker != "418660.KS" else {}
    clock = now or datetime.now(timezone.utc)
    evidence = quote_evidence(ticker, quote, clock)
    with st.expander("시세 시각·세션 확인", expanded=True):
        if manual_price > 0:
            st.caption("상단 현재가는 수동 보정값입니다. 아래 공급자 시세와 별개입니다.")
        else:
            st.caption("상단 현재가는 기존 계산 입력값입니다. 관측 시각 없는 값의 세션은 확정하지 않습니다.")
        if evidence["status"] != "연결됨":
            st.caption(evidence["status"])
            if ticker != "418660.KS":
                st.caption("검증된 시간외 가격 미연결 · 0원이나 정규장 가격으로 대체하지 않음")
            return
        st.markdown(f"**{evidence['session']} · USD {evidence['price']:,.2f} · {evidence['change']:+.2f}%**")
        st.caption(f"관측 {evidence['as_of']} · 비교: 미국 {evidence['base']} 정규장 종가")
        st.caption(evidence["source"] + " · 판정·차트 입력에 반영하지 않는 별도 참고값")


register_loaded_source(__name__, __file__)
