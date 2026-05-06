"""News, research-report, and analyst snapshot helpers for Stock Lab."""

from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

from stock_lab_core.formatters import (
    clean_float,
    clean_int,
    escape_html_value,
    format_currency,
    normalize_ticker,
)


def finite_num(x):
    return x is not None and not pd.isna(x) and np.isfinite(float(x))

# -------------------------------------------------
# 3. 뉴스 듀얼 모터
# -------------------------------------------------
STOCK_NEWS_WORDS = [
    "stock", "stocks", "share", "shares", "market", "nasdaq", "nyse", "earnings",
    "revenue", "profit", "guidance", "analyst", "rating", "price target",
    "upgrade", "downgrade", "buy", "sell", "hold", "dividend", "etf",
    "주가", "증시", "주식", "실적", "매출", "영업이익", "순이익", "목표가",
    "투자의견", "상향", "하향", "매수", "매도", "보유", "배당", "ETF",
    "코스피", "코스닥", "나스닥", "뉴욕증시"
]

GENERAL_NOISE_WORDS = [
    "galaxy", "갤럭시", "iphone", "아이폰", "android", "안드로이드",
    "recipe", "beer", "game", "gaming", "movie", "music", "lyrics",
    "라이트급", "litecoin", "crypto", "코인", "맛집", "여행"
]

NEWS_CATEGORY_DIRECT = "종목 직접"
NEWS_CATEGORY_SECTOR = "섹터/테마"
NEWS_CATEGORY_MARKET = "시장/매크로"
NEWS_CATEGORY_ORDER = {
    NEWS_CATEGORY_DIRECT: 0,
    NEWS_CATEGORY_SECTOR: 1,
    NEWS_CATEGORY_MARKET: 2,
}
NEWS_CATEGORY_LIMITS = {
    NEWS_CATEGORY_DIRECT: 3,
    NEWS_CATEGORY_SECTOR: 2,
    NEWS_CATEGORY_MARKET: 1,
}
NEWS_MAX_ITEMS = 6

LOW_QUALITY_NEWS_WORDS = [
    "주식 움직였습니다", "핵심 원인 공개", "어떤 신호인가요", "주가 움직였습니다",
    "stock moved", "why it moved", "price action", "what signal",
]

HIGH_VALUE_NEWS_WORDS = [
    "earnings", "revenue", "profit", "margin", "guidance", "outlook", "forecast",
    "analyst", "price target", "upgrade", "downgrade", "buy rating", "sell rating",
    "contract", "order", "approval", "regulatory", "antitrust", "lawsuit",
    "실적", "매출", "영업이익", "순이익", "가이던스", "전망", "목표가", "투자의견",
    "상향", "하향", "수주", "계약", "승인", "규제", "소송", "조사",
]

POSITIVE_NEWS_SIGNALS = [
    ("beat", "실적이 예상보다 좋다는 단서"),
    ("beats", "실적이 예상보다 좋다는 단서"),
    ("strong", "수요나 실적 흐름이 강하다는 단서"),
    ("growth", "성장 흐름이 확인됐다는 단서"),
    ("grows", "성장 흐름이 확인됐다는 단서"),
    ("raises guidance", "가이던스 상향은 이익 기대를 높이는 단서"),
    ("upgrade", "투자의견 상향은 수급에 우호적인 단서"),
    ("price target raised", "목표가 상향은 기대치 개선 단서"),
    ("record", "사상 최대/기록 경신은 실적 모멘텀 단서"),
    ("contract", "계약/수주는 매출 가시성 개선 단서"),
    ("approval", "승인은 사업 진행에 우호적인 단서"),
    ("호실적", "호실적은 이익 기대를 높이는 단서"),
    ("깜짝 실적", "컨센서스 상회 가능성을 시사"),
    ("서프라이즈", "컨센서스 상회 가능성을 시사"),
    ("상향", "목표가/투자의견 상향은 수급에 우호적"),
    ("수주", "수주는 매출 가시성 개선 단서"),
    ("계약", "계약 체결은 사업 진행에 우호적"),
    ("승인", "승인은 사업 진행에 우호적"),
    ("성장", "성장 흐름이 확인됐다는 단서"),
    ("급증", "수요나 실적 모멘텀 강화 단서"),
]

NEGATIVE_NEWS_SIGNALS = [
    ("miss", "실적이 기대에 못 미쳤다는 단서"),
    ("cuts guidance", "가이던스 하향은 이익 기대를 낮추는 단서"),
    ("downgrade", "투자의견 하향은 수급에 부담"),
    ("price target cut", "목표가 하향은 기대치 약화 단서"),
    ("investigation", "조사/규제 이슈는 밸류에이션 부담"),
    ("lawsuit", "소송 이슈는 불확실성 확대 단서"),
    ("antitrust", "반독점/규제 이슈는 사업 리스크"),
    ("strike", "파업은 생산/운영 차질 가능성"),
    ("decline", "감소/둔화는 실적 모멘텀 약화 단서"),
    ("slump", "수요 둔화 가능성"),
    ("부진", "실적이나 수요 둔화 가능성"),
    ("적자", "수익성 악화 단서"),
    ("하향", "목표가/투자의견 하향은 수급 부담"),
    ("소송", "소송 이슈는 불확실성 확대 단서"),
    ("규제", "규제 이슈는 밸류에이션 부담"),
    ("조사", "조사 이슈는 불확실성 확대 단서"),
    ("파업", "파업은 생산/운영 차질 가능성"),
    ("감소", "실적 모멘텀 둔화 단서"),
    ("둔화", "성장률 둔화 가능성"),
    ("하락", "단기 투자심리 약화 단서"),
    ("급락", "단기 투자심리 악화 단서"),
]

NEWS_SOURCE_QUALITY = {
    "reuters": 3,
    "bloomberg": 3,
    "cnbc": 2,
    "marketwatch": 2,
    "seeking alpha": 2,
    "yahoo finance": 2,
    "nasdaq": 2,
    "investing.com": 1,
    "thelec": 2,
    "전자신문": 2,
    "연합뉴스": 2,
    "한국경제": 2,
    "매일경제": 2,
    "머니투데이": 1,
    "tradingkey": -3,
    "tokenpost": -2,
}

NEWS_THEME_TERMS_BY_SYMBOL = {
    "MSFT": ["Azure", "클라우드", "AI cloud", "Copilot", "OpenAI", "enterprise software", "cloud"],
    "GOOGL": ["Google Cloud", "AI", "advertising", "Gemini", "cloud"],
    "GOOG": ["Google Cloud", "AI", "advertising", "Gemini", "cloud"],
    "AMZN": ["AWS", "cloud", "AI demand", "retail", "advertising"],
    "NVDA": ["AI chip", "GPU", "data center", "semiconductor", "HBM"],
    "AMD": ["AI chip", "GPU", "data center", "semiconductor"],
    "AVGO": ["AI chip", "networking", "semiconductor", "VMware"],
    "TSM": ["foundry", "semiconductor", "AI chip", "TSMC"],
    "MU": ["DRAM", "HBM", "memory chip", "semiconductor"],
    "MRVL": ["AI infrastructure", "networking chip", "semiconductor"],
    "ANET": ["AI networking", "data center", "cloud networking"],
    "CIEN": ["optical networking", "data center", "AI infrastructure"],
    "VRT": ["AI data center", "power infrastructure", "cooling"],
    "LITE": ["optical", "AI data center", "networking"],
    "SOXX": ["semiconductor", "AI chip", "chip stocks", "Nvidia", "TSMC"],
    "SMH": ["semiconductor", "AI chip", "chip stocks", "Nvidia", "TSMC"],
    "DRAM": ["DRAM", "HBM", "memory chip", "semiconductor"],
    "QQQ": ["Nasdaq 100", "AI stocks", "megacap tech"],
    "QQQM": ["Nasdaq 100", "AI stocks", "megacap tech"],
    "QLD": ["Nasdaq 100", "AI stocks", "megacap tech"],
    "TQQQ": ["Nasdaq 100", "AI stocks", "megacap tech"],
    "379810": ["나스닥100", "미국 기술주", "AI 주식"],
    "379800": ["S&P500", "미국 대형주", "미국 증시"],
    "069500": ["코스피200", "한국 증시", "외국인 수급"],
    "000660": ["HBM", "DRAM", "반도체", "메모리", "AI 반도체"],
    "005930": ["HBM", "DRAM", "반도체", "메모리", "파운드리"],
    "267260": ["전력인프라", "변압기", "전력기기", "AI 전력", "전력망"],
    "034020": ["원전", "원자력", "SMR", "전력", "에너지"],
    "278470": ["K-뷰티", "화장품", "뷰티", "인디브랜드", "올리브영"],
    "329180": ["조선", "LNG선", "선박", "수주", "해양플랜트"],
    "012450": ["방산", "항공우주", "수출", "수주"],
    "487240": ["전력인프라", "변압기", "전력기기", "AI 전력"],
    "479850": ["K-뷰티", "화장품", "뷰티"],
    "434730": ["원전", "원자력", "SMR"],
}

NEWS_RECENT_DAYS = 14
NEWS_FALLBACK_DAYS = 90
KST = timezone(timedelta(hours=9))

def parse_rss_pub_dt(item):
    raw = item.findtext("pubDate", "") or item.findtext("published", "")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def is_news_within_days(pub_dt, days):
    if pub_dt is None:
        return False
    return pub_dt >= datetime.now(timezone.utc) - timedelta(days=days)

def format_news_pub_date(pub_dt):
    if pub_dt is None:
        return ""
    return pub_dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")

def news_sort_timestamp(pub_dt):
    try:
        return float(pub_dt.timestamp()) if pub_dt is not None else 0.0
    except Exception:
        return 0.0

GENERIC_TICKERS = {
    "lite", "on", "now", "snap", "spot", "snow", "mu", "arm", "path", "apps",
    "open", "ai", "u", "net", "shop", "coin", "hood", "sofi"
}

@st.cache_data(ttl=86400, show_spinner=False)
def get_yfinance_company_names(ticker):
    names = []
    try:
        info = yf.Ticker(ticker).get_info()
        for key in ["longName", "shortName", "displayName"]:
            value = str(info.get(key, "") or "").strip()
            if value and value.lower() not in [x.lower() for x in names]:
                names.append(value)
    except Exception:
        pass
    return names[:3]


@st.cache_data(ttl=21600, show_spinner=False)
def get_analyst_snapshot(ticker):
    try:
        info = yf.Ticker(ticker).get_info()
    except Exception as e:
        return {"ok": False, "reason": str(e)}

    if not isinstance(info, dict) or not info:
        return {"ok": False, "reason": "분석 데이터 없음"}

    keys = [
        "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
        "numberOfAnalystOpinions", "recommendationMean", "recommendationKey",
        "currentPrice", "regularMarketPrice",
    ]
    data = {key: info.get(key) for key in keys}
    has_any = any(data.get(key) not in [None, ""] for key in keys)
    return {"ok": has_any, "data": data, "reason": "" if has_any else "목표가/투자의견 데이터 없음"}


def build_research_report_links(ticker, name):
    symbol = normalize_news_token(ticker).upper()
    display_name = str(name or ticker).replace("탐색: ", "").strip()
    is_kr = str(ticker).upper().endswith((".KS", ".KQ"))

    if is_kr:
        query = urllib.parse.quote(f"{display_name} {symbol} 증권사 리포트 목표가")
        return [
            {"label": "네이버 리포트 검색", "url": f"https://search.naver.com/search.naver?where=news&query={query}"},
            {"label": "구글 리포트 검색", "url": f"https://www.google.com/search?q={query}"},
        ]

    query = urllib.parse.quote(f"{symbol} analyst report price target")
    nasdaq_symbol = urllib.parse.quote(symbol.lower())
    yahoo_symbol = urllib.parse.quote(str(ticker).upper())
    return [
        {"label": "Yahoo Analysis", "url": f"https://finance.yahoo.com/quote/{yahoo_symbol}/analysis"},
        {"label": "Nasdaq Analyst", "url": f"https://www.nasdaq.com/market-activity/stocks/{nasdaq_symbol}/analyst-research"},
        {"label": "Google Report", "url": f"https://www.google.com/search?q={query}"},
    ]


def render_research_report_panel(name, ticker, current_price, is_etf=False):
    st.markdown("### 🧾 리포트 / 목표가")
    if is_etf:
        st.info("ETF는 보통 애널리스트 목표가가 제공되지 않습니다. 목표가보다 돈흐름 레이더, 기초지수/섹터 흐름, NAV 괴리율은 증권사 앱 기준으로 확인하는 편이 더 적합합니다.")
        links = build_research_report_links(ticker, name)
        link_cols = st.columns(min(len(links), 3))
        for i, item in enumerate(links):
            link_cols[i % len(link_cols)].link_button(item["label"], item["url"], use_container_width=True)
        return

    snapshot = get_analyst_snapshot(ticker)
    data = snapshot.get("data", {}) if snapshot.get("ok") else {}

    target_mean = clean_float(data.get("targetMeanPrice"), np.nan)
    target_median = clean_float(data.get("targetMedianPrice"), np.nan)
    target_high = clean_float(data.get("targetHighPrice"), np.nan)
    target_low = clean_float(data.get("targetLowPrice"), np.nan)
    opinions = clean_int(data.get("numberOfAnalystOpinions"), 0) or 0
    rec_key = str(data.get("recommendationKey") or "-").upper()

    target_upside = np.nan
    cur = clean_float(current_price, np.nan)
    if finite_num(target_mean) and finite_num(cur) and cur > 0:
        target_upside = (float(target_mean) / float(cur) - 1) * 100

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("평균 목표가", format_currency(target_mean, ticker) if finite_num(target_mean) else "-")
    r2.metric("목표가 업사이드", f"{target_upside:.1f}%" if finite_num(target_upside) else "-")
    r3.metric("참여 애널리스트", f"{opinions}명" if opinions else "-")
    r4.metric("투자의견", rec_key if rec_key != "-" else "-")

    if finite_num(target_low) or finite_num(target_median) or finite_num(target_high):
        st.caption(
            "목표가 범위: "
            f"하단 {format_currency(target_low, ticker) if finite_num(target_low) else '-'} / "
            f"중앙 {format_currency(target_median, ticker) if finite_num(target_median) else '-'} / "
            f"상단 {format_currency(target_high, ticker) if finite_num(target_high) else '-'}"
        )
    elif not snapshot.get("ok"):
        st.caption(f"목표가 데이터 없음: {snapshot.get('reason', '제공 데이터 없음')}")

    links = build_research_report_links(ticker, name)
    link_cols = st.columns(min(len(links), 3))
    for i, item in enumerate(links):
        link_cols[i % len(link_cols)].link_button(item["label"], item["url"], use_container_width=True)

    st.caption("목표가와 투자의견은 yfinance 제공 데이터 기준입니다. 한국 종목은 제공되지 않는 경우가 많아 리포트 검색 링크를 함께 제공합니다.")


def normalize_news_token(text):
    return str(text or "").replace(".KS", "").replace(".KQ", "").strip()

def clean_news_text(value):
    return html.unescape(str(value or "")).replace("<b>", "").replace("</b>", "").strip()

def get_news_company_names(ticker, name):
    symbol = normalize_news_token(ticker).upper()
    display_name = str(name or "").replace("탐색: ", "").strip()

    names = []

    if display_name and display_name.upper() != symbol:
        names.append(display_name)

    for n in get_yfinance_company_names(ticker):
        if n and n.lower() not in [x.lower() for x in names]:
            names.append(n)

    cleaned = []
    for n in names:
        n = n.replace("Inc.", "").replace("Corporation", "").replace("Corp.", "").replace("Co., Ltd.", "").strip()
        if len(n) >= 2 and n.lower() not in [x.lower() for x in cleaned]:
            cleaned.append(n)

    return cleaned[:3]

def build_stock_news_queries(ticker, name):
    symbol = normalize_news_token(ticker).upper()
    company_names = get_news_company_names(ticker, name)
    is_kr = str(ticker).upper().endswith((".KS", ".KQ"))

    main = company_names[0] if company_names else symbol

    if is_kr:
        queries = [
            f'"{main}" 주가 실적',
            f'"{main}" 증권',
            f'{symbol} 주가 실적',
        ]
    else:
        queries = [
            f'"{main}" {symbol} stock',
            f'"{main}" earnings shares',
            f'"{main}" analyst price target',
        ]

    return queries, company_names

def keyword_in_text(text, keywords):
    lowered = str(text or "").lower()
    return any(str(k).lower() in lowered for k in keywords if str(k).strip())

def first_signal_reason(text, signals):
    lowered = str(text or "").lower()
    for keyword, reason in signals:
        if str(keyword).lower() in lowered:
            return keyword, reason
    return "", ""

def get_news_theme_terms(ticker, name):
    symbol = normalize_news_token(ticker).upper()
    key = normalize_ticker(ticker).upper()
    display_name = str(name or "").replace("탐색: ", "").strip()
    terms = []

    for lookup in [symbol, key]:
        for term in NEWS_THEME_TERMS_BY_SYMBOL.get(lookup, []):
            if term and term.lower() not in [x.lower() for x in terms]:
                terms.append(term)

    if display_name and display_name.upper() != symbol and display_name.lower() not in [x.lower() for x in terms]:
        terms.append(display_name)

    return terms[:6]

def build_news_query_plan(ticker, name):
    direct_queries, company_names = build_stock_news_queries(ticker, name)
    symbol = normalize_news_token(ticker).upper()
    is_kr = str(ticker).upper().endswith((".KS", ".KQ"))
    main = company_names[0] if company_names else symbol
    theme_terms = get_news_theme_terms(ticker, name)
    first_theme = theme_terms[0] if theme_terms else ""

    plan = [
        {"query": q, "category": NEWS_CATEGORY_DIRECT, "strict": True}
        for q in direct_queries
    ]

    if first_theme:
        if is_kr:
            plan.extend([
                {"query": f'"{first_theme}" "{main}" 증권 실적', "category": NEWS_CATEGORY_SECTOR, "strict": False},
                {"query": f'"{first_theme}" 수주 실적 주가', "category": NEWS_CATEGORY_SECTOR, "strict": False},
            ])
        else:
            plan.extend([
                {"query": f'"{main}" "{first_theme}" earnings stock', "category": NEWS_CATEGORY_SECTOR, "strict": False},
                {"query": f'"{first_theme}" stocks earnings demand', "category": NEWS_CATEGORY_SECTOR, "strict": False},
            ])

    if is_kr:
        plan.append({"query": "코스피 환율 금리 외국인 증시", "category": NEWS_CATEGORY_MARKET, "strict": False})
    else:
        plan.append({"query": "Nasdaq S&P 500 Fed yields AI stocks", "category": NEWS_CATEGORY_MARKET, "strict": False})

    deduped = []
    seen = set()
    for item in plan:
        key = (item["query"].lower(), item["category"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped, company_names, theme_terms

def symbol_appears_as_token(text, symbol):
    text = str(text or "").lower()
    symbol = str(symbol or "").lower()
    tokens = text.replace("(", " ").replace(")", " ").replace(":", " ").replace(",", " ").replace(".", " ").split()
    return symbol in tokens

def assess_news_item(title, publisher, ticker, company_names, theme_terms, category, strict=True):
    text = f"{title} {publisher}"
    text_l = text.lower()
    symbol = normalize_news_token(ticker).lower()

    if any(noise.lower() in text_l for noise in GENERAL_NOISE_WORDS):
        return {"ok": False, "score": -99, "relation": "무관", "sentiment": "중립", "reason": "주식 뉴스와 무관한 키워드"}

    has_company = any(str(n).lower() in text_l for n in company_names if str(n).strip())
    has_symbol = symbol_appears_as_token(text, symbol)
    has_theme = keyword_in_text(text, theme_terms)
    has_stock_word = keyword_in_text(text, STOCK_NEWS_WORDS)
    has_high_value_word = keyword_in_text(text, HIGH_VALUE_NEWS_WORDS)
    has_market_word = keyword_in_text(text, ["nasdaq", "s&p", "fed", "yield", "rate", "inflation", "earnings", "증시", "코스피", "코스닥", "금리", "환율", "외국인"])
    is_low_quality = keyword_in_text(text, LOW_QUALITY_NEWS_WORDS)

    score = 0
    if has_company: score += 5
    if has_symbol: score += 4
    if has_theme: score += 3
    if has_high_value_word: score += 2
    if has_stock_word: score += 1
    if has_market_word and category == NEWS_CATEGORY_MARKET: score += 2
    if is_low_quality: score -= 4

    pub_l = str(publisher or "").lower()
    for source, adj in NEWS_SOURCE_QUALITY.items():
        if source.lower() in pub_l:
            score += adj
            break

    if symbol in GENERIC_TICKERS and not has_company and category == NEWS_CATEGORY_DIRECT:
        score -= 4

    if category == NEWS_CATEGORY_DIRECT:
        ok = (has_company or has_symbol) and (has_stock_word or has_high_value_word or not strict) and score >= 3
    elif category == NEWS_CATEGORY_SECTOR:
        ok = (has_company or has_symbol or has_theme) and score >= 2
    else:
        ok = has_market_word and score >= 1

    if is_low_quality and category == NEWS_CATEGORY_DIRECT and score < 5:
        ok = False

    if score >= 7:
        relation = "관련도 높음"
    elif score >= 3:
        relation = "관련도 보통"
    elif ok:
        relation = "간접 관련"
    else:
        relation = "무관"

    pos_key, pos_reason = first_signal_reason(text, POSITIVE_NEWS_SIGNALS)
    neg_key, neg_reason = first_signal_reason(text, NEGATIVE_NEWS_SIGNALS)

    if pos_key and not neg_key:
        sentiment, reason = "호재", pos_reason
    elif neg_key and not pos_key:
        sentiment, reason = "악재", neg_reason
    elif pos_key and neg_key:
        sentiment, reason = "중립", "호재와 악재 단서가 함께 있어 추가 확인 필요"
    elif category == NEWS_CATEGORY_DIRECT:
        sentiment, reason = "중립", "종목 직접 뉴스지만 방향성 단서는 제한적"
    elif category == NEWS_CATEGORY_SECTOR:
        sentiment, reason = "중립", "섹터/테마 관련 뉴스로 종목에 간접 영향 가능"
    else:
        sentiment, reason = "중립", "시장 환경 관련 뉴스로 전체 투자심리에 영향 가능"

    if is_low_quality and ok:
        reason = "반복 시세성 기사라 우선순위를 낮춰 표시"

    return {
        "ok": ok,
        "score": score,
        "relation": relation,
        "sentiment": sentiment,
        "reason": reason,
    }

def is_relevant_stock_news(title, publisher, ticker, company_names, strict=True):
    text = f"{title} {publisher}".lower()
    symbol = normalize_news_token(ticker).lower()

    if any(noise in text for noise in GENERAL_NOISE_WORDS):
        return False

    has_company = any(str(n).lower() in text for n in company_names if str(n).strip())
    has_symbol = symbol_appears_as_token(text, symbol)
    has_stock_word = any(w.lower() in text for w in STOCK_NEWS_WORDS)

    if symbol in GENERIC_TICKERS:
        return has_company and has_stock_word

    if strict:
        return (has_company or has_symbol) and has_stock_word

    return has_company or (has_symbol and has_stock_word)
    
@st.cache_data(ttl=600)
def get_ticker_news(ticker, name, debug=False):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    query_plan, company_names, theme_terms = build_news_query_plan(ticker, name)
    logs = [
        f"회사명 후보: {company_names if company_names else '없음'}",
        f"테마 키워드: {theme_terms if theme_terms else '없음'}",
        f"검색어 후보: {[x['query'] for x in query_plan]}",
        f"뉴스 v2: 직접/섹터/시장 분류, 관련도/호재악재 태그 적용",
        f"최신 필터: 최근 {NEWS_RECENT_DAYS}일 우선, 없으면 {NEWS_FALLBACK_DAYS}일 fallback",
    ]

    recent_items = []
    fallback_items = []
    seen_links = set()
    accepted_by_category = {key: 0 for key in NEWS_CATEGORY_LIMITS}

    def add_item(title, link, publisher, pub_dt, category, strict=True):
        if not link or link in seen_links:
            return False

        assessment = assess_news_item(
            title=title,
            publisher=publisher,
            ticker=ticker,
            company_names=company_names,
            theme_terms=theme_terms,
            category=category,
            strict=strict,
        )
        if not assessment["ok"]:
            return False

        item_data = {
            "title": title,
            "link": link,
            "publisher": publisher,
            "published": format_news_pub_date(pub_dt),
            "category": category,
            "relation": assessment["relation"],
            "sentiment": assessment["sentiment"],
            "reason": assessment["reason"],
            "quality_score": assessment["score"],
            "_pub_dt": pub_dt,
        }

        if is_news_within_days(pub_dt, NEWS_RECENT_DAYS):
            seen_links.add(link)
            accepted_by_category[category] = accepted_by_category.get(category, 0) + 1
            recent_items.append(item_data)
            return True

        if is_news_within_days(pub_dt, NEWS_FALLBACK_DAYS):
            seen_links.add(link)
            accepted_by_category[category] = accepted_by_category.get(category, 0) + 1
            fallback_items.append(item_data)
            return True

        return False

    def read_rss(url, publisher_fallback, category, strict=True):
        req = urllib.request.Request(url, headers=headers)
        root = ET.fromstring(urllib.request.urlopen(req, timeout=4).read())
        items = root.findall("./channel/item")

        accepted = 0
        for item in items:
            title = clean_news_text(item.findtext("title", "제목 없음"))
            link = str(item.findtext("link", "#") or "#").strip()
            publisher = clean_news_text(item.findtext("source", publisher_fallback)) or publisher_fallback
            pub_dt = parse_rss_pub_dt(item)

            if add_item(title, link, publisher, pub_dt, category=category, strict=strict):
                accepted += 1

            if accepted_by_category.get(category, 0) >= NEWS_CATEGORY_LIMITS.get(category, 1):
                break

        return len(items), accepted

    for plan in query_plan:
        q = plan["query"]
        category = plan["category"]
        strict = plan.get("strict", True)
        if accepted_by_category.get(category, 0) >= NEWS_CATEGORY_LIMITS.get(category, 1):
            continue
        if sum(accepted_by_category.values()) >= NEWS_MAX_ITEMS:
            break

        google_query = f"{q} when:{NEWS_FALLBACK_DAYS}d"
        google_encoded = urllib.parse.quote(google_query)
        normal_encoded = urllib.parse.quote(q)

        try:
            google_url = f"https://news.google.com/rss/search?q={google_encoded}&hl=ko&gl=KR&ceid=KR:ko"
            if debug:
                logs.append(f"구글 URL: {google_url}")
            total, accepted = read_rss(google_url, "구글 뉴스", category=category, strict=strict)
            logs.append(f"구글 검색({category}): {google_query} / 원문 {total}건, 통과 {accepted}건")
        except Exception as e:
            logs.append(f"구글 뉴스 실패: {q} / {e}")

        if accepted_by_category.get(category, 0) >= NEWS_CATEGORY_LIMITS.get(category, 1):
            continue

        try:
            naver_url = f"https://newssearch.naver.com/search.naver?where=rss&query={normal_encoded}&sort=1"
            if debug:
                logs.append(f"네이버 URL: {naver_url}")
            total, accepted = read_rss(naver_url, "네이버 뉴스", category=category, strict=strict)
            logs.append(f"네이버 검색({category}): {q} / 원문 {total}건, 통과 {accepted}건")
        except Exception as e:
            logs.append(f"네이버 뉴스 실패: {q} / {e}")

    selected = recent_items if recent_items else fallback_items

    if not selected:
        logs.append("최근 주식 관련 뉴스 없음")
        return [], logs

    selected = sorted(
        selected,
        key=lambda x: (
            NEWS_CATEGORY_ORDER.get(x.get("category"), 9),
            -float(x.get("quality_score") or 0),
            -news_sort_timestamp(x.get("_pub_dt")),
        )
    )

    limited = []
    final_counts = {}
    for item in selected:
        category = item.get("category", NEWS_CATEGORY_DIRECT)
        if final_counts.get(category, 0) >= NEWS_CATEGORY_LIMITS.get(category, 1):
            continue
        final_counts[category] = final_counts.get(category, 0) + 1
        limited.append(item)
        if len(limited) >= NEWS_MAX_ITEMS:
            break
    selected = limited

    for item in selected:
        item.pop("_pub_dt", None)

    if not recent_items and fallback_items:
        logs.append(f"최근 {NEWS_RECENT_DAYS}일 뉴스가 없어 {NEWS_FALLBACK_DAYS}일 이내 기사로 대체 표시")

    return selected, logs

def news_sentiment_class(sentiment):
    if sentiment == "호재":
        return "positive"
    if sentiment == "악재":
        return "negative"
    return "neutral"

def render_news_cards(news_items):
    grouped = {}
    for item in news_items:
        grouped.setdefault(item.get("category", NEWS_CATEGORY_DIRECT), []).append(item)

    for category in [NEWS_CATEGORY_DIRECT, NEWS_CATEGORY_SECTOR, NEWS_CATEGORY_MARKET]:
        items = grouped.get(category, [])
        if not items:
            continue

        st.markdown(f"#### {category}")
        for item in items:
            safe_title = escape_html_value(item.get("title", "제목 없음"))
            safe_pub = escape_html_value(item.get("publisher", ""))
            safe_date = escape_html_value(item.get("published", ""))
            safe_category = escape_html_value(item.get("category", category))
            safe_relation = escape_html_value(item.get("relation", "관련도 보통"))
            safe_sentiment = escape_html_value(item.get("sentiment", "중립"))
            safe_reason = escape_html_value(item.get("reason", "추가 확인 필요"))
            safe_score = escape_html_value(item.get("quality_score", ""))
            date_part = f" | {safe_date}" if safe_date else ""
            safe_link = str(item.get("link", "#")).strip()
            if not safe_link.startswith(("http://", "https://")):
                safe_link = "#"
            safe_link_attr = html.escape(safe_link, quote=True)

            sentiment_class = news_sentiment_class(item.get("sentiment", "중립"))
            st.markdown(
                f"<div class='news-box news-{sentiment_class}'>"
                f"<a href='{safe_link_attr}' target='_blank'>🔗 {safe_title}</a>"
                f"<div class='news-meta-row'>"
                f"<span class='news-chip news-chip-category'>{safe_category}</span>"
                f"<span class='news-chip news-chip-{sentiment_class}'>{safe_sentiment}</span>"
                f"<span class='news-chip'>{safe_relation}</span>"
                f"출처: {safe_pub}{date_part} | 품질점수: {safe_score}"
                f"</div>"
                f"<div class='news-reason'>{safe_reason}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )



