"""Offline UI fixture: no broker credentials, network, or investment signals."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from stock_lab_core.browser_safety import install_translation_guard
from stock_lab_core.kiwoom_market import normalize_market_rows
from stock_lab_core.kiwoom_us import normalize_us_market_rows
from stock_lab_core.market_evidence_panel import render_market_evidence_panel


st.set_page_config(page_title="Market evidence test", layout="wide")
install_translation_guard(st)
st.caption("OFFLINE TEST DATA")
fail = st.checkbox("조회 실패 테스트")
news_ok = st.checkbox("뉴스 성공 테스트")


def fetch(kind, theme_code=""):
    if fail and kind == "turnover":
        return {"ok": False, "status": "timeout", "rows": []}
    samples = {
        "turnover": {"trde_prica_upper": [{"stk_cd": "005930", "stk_nm": "삼성전자", "cur_prc": "70000",
                      "flu_rt": "+1.2", "trde_prica": "10000", "now_trde_qty": "100000", "now_rank": "1"}]},
        "themes": {"thema_grp": [{"thema_grp_cd": "100", "thema_nm": "반도체", "flu_rt": "+2.5",
                    "dt_prft_rt": "8", "stk_num": "10", "rising_stk_num": "7", "fall_stk_num": "2", "main_stk": "삼성전자"},
                   {"thema_grp_cd": "200", "thema_nm": "전력설비", "flu_rt": "-0.5", "stk_num": "10"}]},
        "theme_members": {"thema_comp_stk": [{"stk_cd": "005930", "stk_nm": "삼성전자", "flu_rt": "+1.2",
                             "dt_prft_rt_n": "4.5", "acc_trde_qty": "100000"}]},
        "sector_kospi": {"inds_netprps": [{"inds_cd": "001", "inds_nm": "코스피", "flu_rt": "+0.8",
                            "frgnr_netprps": "120", "orgn_netprps": "-50", "ind_netprps": "-70"}]},
        "sector_kosdaq": {"inds_netprps": []},
    }
    return {**normalize_market_rows(samples[kind], kind), "fetched_at": "2026-10-13T02:00:00+00:00",
            "source": "OFFLINE FIXTURE", "has_more": True}


def fetch_us(kind, ticker="", exchange="ND"):
    st.session_state["us_requests"] = st.session_state.get("us_requests", 0) + 1
    quote = {"stk_cd": ticker or "NVDA", "stex_tp": exchange, "stk_nm": "미국 테스트종목",
             "stk_enm": "TEST CORP", "cur_prc": "-123.45", "flu_rt": "-1.2", "acc_trde_qty": "1200"}
    payload = {"result_list": [quote]}
    if kind == "us_quote":
        payload = quote
    elif kind == "us_sectors":
        payload = {"result_list": [{"inds_cd": "10", "inds_nm": "에너지", "perf_1d": "-2.1"}]}
    return {**normalize_us_market_rows(payload, kind, ticker=ticker, exchange=exchange),
            "fetched_at": "2026-10-14T02:00:00+00:00", "source": "OFFLINE FIXTURE", "is_mock": True}


def get_news(*args):
    st.session_state["news_requests"] = st.session_state.get("news_requests", 0) + 1
    if news_ok:
        return [{"title": "테스트 종목 실적 발표", "category": "종목 직접"}], ["정상 RSS 응답"]
    return [], ["뉴스 수집 실패: 테스트 연결 오류"]


def clear_news(*args):
    st.session_state["news_clear_args"] = args


get_news.clear = clear_news
fetch.clear = lambda *args: None
fetch_us.clear = lambda *args: None
render_market_evidence_panel(st, status="ready", fetch_snapshot=fetch, fetch_us=fetch_us, get_news=get_news,
                             render_news=lambda items: st.write(items[0]["title"]), key_prefix="test")
