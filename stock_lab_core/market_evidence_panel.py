"""Read-only provider evidence UI, isolated from portfolio/execution policy."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from stock_lab_core.kiwoom_market import market_evidence_summary
from stock_lab_core.news_evidence import render_price_news_evidence


STATUS_TEXT = {
    "disabled": "키움 조회가 꺼져 있습니다. [kiwoom] enabled 설정을 확인하세요.",
    "missing_configuration": "키움 appkey / secretkey 설정이 필요합니다.",
    "invalid_configuration": "키움 설정 형식 또는 운영/모의 구분을 확인하세요.",
    "auth_error": "인증 실패: 키·운영/모의 구분·서버 허용 IP를 확인하세요.",
    "rate_limited": "키움 조회 한도에 도달했습니다. 잠시 후 다시 조회하세요.",
    "timeout": "키움 응답 시간이 초과되었습니다.",
    "network_error": "키움 서버 연결에 실패했습니다.",
    "api_error": "키움이 조회를 거절했습니다. API 권한과 설정을 확인하세요.",
    "http_error": "키움 서버가 정상 응답하지 않았습니다.",
    "invalid_response": "키움 응답 형식이 맞지 않아 수치 해석을 보류했습니다.",
    "no_data": "이번 조회에 제공된 자료가 없습니다.",
    "busy": "다른 키움 조회가 진행 중입니다.",
}


def render_snapshot(st, snapshot, *, limit=30):
    if not snapshot.get("ok"):
        status = snapshot.get("status")
        st.info(STATUS_TEXT.get(status, "키움 자료를 확인하지 못했습니다."))
        return []
    rows = snapshot.get("rows", [])
    if not rows:
        st.info(STATUS_TEXT["no_data"])
        return []
    if snapshot.get("is_mock"):
        st.caption("키움 모의환경 시세 조회 · 주문/계좌 자료 아님 · 실행판정 자동 반영 없음")
    try:
        timestamp = datetime.fromisoformat(snapshot["fetched_at"]).astimezone(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M:%S KST")
    except (KeyError, ValueError, TypeError):
        timestamp = "조회시각 미확인"
    coverage = "후속 페이지 있음" if snapshot.get("has_more") else "후속 페이지 없음"
    st.caption(f"{snapshot.get('source', 'Kiwoom REST')} · 조회 {timestamp} · 시세 기준시각 미제공 · 첫 페이지 {len(rows)}행 중 {min(limit, len(rows))}행 표시, {coverage}")
    frame = pd.DataFrame(rows[:limit])
    text_columns = {"코드", "종목명", "업종", "테마", "주요종목(키움)", "구분"}
    for column in frame.columns:
        if column not in text_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    st.dataframe(frame, hide_index=True, width="stretch")
    return rows


def render_market_evidence_panel(st, *, status, fetch_snapshot, get_news, render_news, key_prefix):
    st.markdown("**키움 시장근거 · 국내 KRX**")
    if status != "ready":
        st.info(STATUS_TEXT.get(status, "키움 연결 설정을 확인하세요."))
        return
    state_key = key_prefix + "_loaded"
    if st.button("키움 시장자료 조회/갱신", key=key_prefix + "_refresh"):
        fetch_snapshot.clear()
        st.session_state[state_key] = True
    if not st.session_state.get(state_key):
        st.caption("연결 설정 있음 · 아직 조회하지 않음")
        return
    turnover = fetch_snapshot("turnover")
    themes = fetch_snapshot("themes")
    for line in market_evidence_summary(turnover, themes):
        st.write(line)
    st.caption("관찰자료 · 매수 승인 아님 · 기존 오늘점검의 시장·비중·손익비 판정은 유지")
    st.markdown("**거래대금 상위**")
    stock_rows = render_snapshot(st, turnover)
    st.markdown("**테마 등락과 상승종목 비율**")
    theme_rows = render_snapshot(st, themes)
    if theme_rows:
        names = {row["코드"]: row["테마"] for row in theme_rows}
        theme = st.selectbox("구성종목 테마", list(names), format_func=lambda code: names[code], key=key_prefix + "_theme")
        # Demand-loaded: changing selection must never display the old theme's rows.
        if st.button("구성종목 조회", key=key_prefix + "_members"):
            st.session_state[key_prefix + "_loaded_theme"] = theme
        if st.session_state.get(key_prefix + "_loaded_theme") == theme:
            member_rows = render_snapshot(st, fetch_snapshot("theme_members", theme))
            stock_rows = [*member_rows, *stock_rows]
    st.markdown("**업종별 투자자 순매수**")
    market = st.radio("수급 시장", ["KOSPI", "KOSDAQ"], horizontal=True, key=key_prefix + "_market")
    if st.button("업종 수급 조회", key=key_prefix + "_flow"):
        st.session_state[key_prefix + "_loaded_market"] = market
    if st.session_state.get(key_prefix + "_loaded_market") == market:
        render_snapshot(st, fetch_snapshot("sector_" + market.lower()))
    stocks = {row["코드"]: row for row in stock_rows}
    if stocks:
        code = st.selectbox("관련 뉴스 종목", list(stocks),
                            format_func=lambda value: f"{stocks[value]['종목명']} ({value})", key=key_prefix + "_stock")
        if st.button("종목 관련 뉴스 조회", key=key_prefix + "_news"):
            st.session_state[key_prefix + "_news_code"] = code
        if st.session_state.get(key_prefix + "_news_code") == code:
            row = stocks[code]
            items, _ = get_news(code, row["종목명"], False)
            render_price_news_evidence(st, items, row.get("등락률(%)"))
            if items:
                render_news(items)
