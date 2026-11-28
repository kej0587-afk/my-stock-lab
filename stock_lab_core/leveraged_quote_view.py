"""Read-only quote evidence, separate from scalar decision inputs."""

from datetime import datetime, timezone
import json
import re

import pandas as pd

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_quotes import (
    extended_quote_observation, extended_quote_status, load_us_report_quote,
    quote_audit,
)

PRODUCTS = frozenset({"SOXL", "RAM", "BITX", "418660.KS"})
VERSION = "quote-evidence-v2"


def supports_quote_evidence(ticker):
    # Only US equity/ETF symbols: do not send KR, FX, futures or crypto to this path.
    return isinstance(ticker, str) and re.fullmatch(r"[A-Z]{1,6}(?:-[A-Z])?", ticker) is not None


def quote_evidence(ticker, quote, now):
    """Missing/old/another-session observations never acquire a current price."""
    if ticker == "418660.KS":
        return {"status": "한국 상장 상품: 미국 데이마켓·애프터 시세를 적용하지 않음"}
    audit = quote_audit(ticker, quote, now)
    observation = audit["extended"]
    if not observation:
        return {"status": audit["status"], "audit": audit}
    return {
        "status": "연결됨", "session": observation["kind"],
        "price": observation["price"], "change": observation["return"] * 100,
        "as_of": pd.Timestamp(observation["as_of"]).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S KST"),
        "base": observation["previous_date"], "source": observation["source"], "audit": audit,
    }


def render_quote_evidence(st, ticker, *, manual_price=0, now=None, fetch_quote=load_us_report_quote):
    if ticker != "418660.KS" and not supports_quote_evidence(ticker):
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
        audit = evidence.get("audit", {})
        regular = audit.get("regular", {})
        if regular:
            st.markdown(f"**직전 정규장 종가 · USD {regular['price']:,.2f} · 미국 {regular['date']}**")
            st.caption("종가 체결시각 " + pd.Timestamp(regular['as_of']).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S KST") + " · Yahoo")
        elif ticker != "418660.KS":
            st.caption("직전 정규장 종가: 제공처 시세의 기준일·시각 검증 미완료")
        if audit:
            if audit.get("retrieved_at"):
                retrieved = pd.Timestamp(audit["retrieved_at"]).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S KST")
                st.caption("공급처 조회 " + retrieved + " · 캐시 60초/실패 15초 · 체결시각과 별개")
            st.download_button("시세 연결 검토 JSON", json.dumps(audit, ensure_ascii=False, indent=2),
                               file_name=f"quote_review_{ticker}.json", mime="application/json",
                               key=f"quote_review_{ticker}", on_click="ignore")
        if evidence["status"] != "연결됨":
            from stock_lab_core.report_session import us_extended_session
            window = us_extended_session(clock)
            delayed = audit.get("delayed_reference", {})
            if delayed.get("delayed"):
                st.markdown(f"**지연 시세 · {delayed['kind']} USD {delayed['price']:,.2f} · {delayed['return'] * 100:+.2f}%**")
                st.caption("마지막 확인 체결 " + pd.Timestamp(delayed['as_of']).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S KST") + " · 이 패널에서는 지연 참고값으로 표시합니다. 판정·차트의 현재가 반영 여부는 ‘가격 기준’ 표에서 확인합니다.")
            st.caption(((window['label'] + " 미수신 · ") if window and not delayed else "") + evidence["status"])
            if ticker != "418660.KS":
                st.caption("현재 세션의 신선한 시간외 가격 미연결 · 0원이나 정규장 가격으로 대체하지 않음")
            return evidence
        st.markdown(f"**{evidence['session']} · USD {evidence['price']:,.2f} · {evidence['change']:+.2f}%**")
        st.caption(f"관측 {evidence['as_of']} · 비교: 미국 {evidence['base']} 정규장 종가")
        st.caption(evidence["source"] + " · 이 패널의 별도 참고값입니다. 판정·차트의 현재가 반영 여부는 ‘가격 기준’ 표에서 확인합니다.")
    return evidence


register_loaded_source(__name__, __file__)
