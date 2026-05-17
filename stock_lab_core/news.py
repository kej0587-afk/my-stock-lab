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

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    import plotly.graph_objects as _go
    _HAS_PLOTLY = True
except ImportError:
    _HAS_PLOTLY = False

from stock_lab_core.formatters import (
    clean_float,
    clean_int,
    escape_html_value,
    format_currency,
    normalize_ticker,
    strip_search_prefix,
)
from datetime import date as _date_cls, timedelta as _td_cls


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
NEWS_MAX_CANDIDATES = 18
NEWS_CATEGORY_SEARCH_LIMITS = {
    NEWS_CATEGORY_DIRECT: 10,
    NEWS_CATEGORY_SECTOR: 6,
    NEWS_CATEGORY_MARKET: 3,
}

LOW_QUALITY_NEWS_WORDS = [
    "주식 움직였습니다", "핵심 원인 공개", "어떤 신호인가요", "주가 움직였습니다",
    "stock moved", "why it moved", "price action", "what signal",
]

EARNINGS_NEWS_WORDS = [
    "earnings", "results", "quarterly results", "q1", "q2", "q3", "q4",
    "revenue", "eps", "profit", "operating margin", "guidance", "outlook",
    "conference call", "investor relations",
    "실적", "실적발표", "실적 발표", "분기 실적", "잠정실적", "매출",
    "영업이익", "순이익", "이익률", "가이던스", "컨퍼런스콜", "IR",
]

HIGH_VALUE_NEWS_WORDS = [
    "earnings", "results", "quarterly results", "revenue", "profit", "margin", "guidance", "outlook", "forecast",
    "eps", "operating margin", "record revenue", "record earnings", "investor relations",
    "analyst", "price target", "upgrade", "downgrade", "buy rating", "sell rating",
    "contract", "order", "approval", "regulatory", "antitrust", "lawsuit",
    "실적", "실적발표", "실적 발표", "분기 실적", "잠정실적", "매출", "영업이익", "순이익",
    "영업이익률", "가이던스", "전망", "목표가", "투자의견", "사상 최대", "역대 최대",
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
    ("record revenue", "매출 기록 경신은 실적 모멘텀 단서"),
    ("record earnings", "이익 기록 경신은 실적 모멘텀 단서"),
    ("contract", "계약/수주는 매출 가시성 개선 단서"),
    ("approval", "승인은 사업 진행에 우호적인 단서"),
    ("호실적", "호실적은 이익 기대를 높이는 단서"),
    ("깜짝 실적", "컨센서스 상회 가능성을 시사"),
    ("서프라이즈", "컨센서스 상회 가능성을 시사"),
    ("사상 최대", "사상 최대 실적은 실적 모멘텀 단서"),
    ("역대 최대", "역대 최대 실적은 실적 모멘텀 단서"),
    ("최대 실적", "최대 실적은 실적 모멘텀 단서"),
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
    "business wire": 3,
    "globenewswire": 3,
    "pr newswire": 2,
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
    "200710": ["반도체", "디자인하우스", "파운드리", "AI 반도체"],
    "042700": ["반도체", "HBM", "후공정", "AI 반도체"],
    "403870": ["반도체", "전공정", "장비", "AI 반도체"],
    "039030": ["반도체", "레이저", "장비", "AI 반도체"],
    "058470": ["반도체", "소켓", "부품", "AI 반도체"],
    "267260": ["전력인프라", "변압기", "전력기기", "AI 전력", "전력망"],
    "010120": ["전력인프라", "변압기", "전력기기", "AI 전력", "전력망"],
    "298040": ["전력인프라", "변압기", "전력기기", "AI 전력", "전력망"],
    "103590": ["전력인프라", "전선", "전력기기", "AI 전력", "전력망"],
    "033100": ["전력인프라", "변압기", "전력기기", "전력망"],
    "001440": ["전력인프라", "전선", "전력망"],
    "034020": ["원전", "원자력", "SMR", "전력", "에너지"],
    "052690": ["원전", "원자력", "SMR", "전력", "에너지"],
    "051600": ["원전", "원자력", "정비", "전력"],
    "278470": ["K-뷰티", "화장품", "뷰티", "인디브랜드", "올리브영"],
    "090430": ["K-뷰티", "화장품", "뷰티", "중국", "면세"],
    "161890": ["K-뷰티", "화장품", "ODM", "뷰티"],
    "192820": ["K-뷰티", "화장품", "ODM", "뷰티"],
    "329180": ["조선", "LNG선", "선박", "수주", "해양플랜트"],
    "009540": ["조선", "LNG선", "선박", "수주", "해양플랜트"],
    "010140": ["조선", "LNG선", "선박", "수주", "해양플랜트"],
    "042660": ["조선", "LNG선", "선박", "수주", "해양플랜트"],
    "012450": ["방산", "항공우주", "수출", "수주"],
    "047810": ["방산", "항공우주", "수출", "수주"],
    "064350": ["방산", "철도", "방산", "수주"],
    "079550": ["방산", "미사일", "수출", "수주"],
    "373220": ["2차전지", "배터리", "전기차", "ESS"],
    "006400": ["2차전지", "배터리", "전기차", "ESS"],
    "051910": ["2차전지", "배터리", "화학", "전기차"],
    "003670": ["2차전지", "양극재", "배터리", "전기차"],
    "247540": ["2차전지", "양극재", "배터리", "전기차"],
    "086520": ["2차전지", "양극재", "배터리", "전기차"],
    "066970": ["2차전지", "양극재", "배터리", "전기차"],
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


def _parse_kr_num(s):
    """Parse Korean-formatted number string → float (e.g. '12,345.67' → 12345.67)."""
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _select_krx_fundamental_row(df, code: str, allow_last_row: bool = False):
    """Return a KRX fundamental row for a single ticker from either by-date or by-ticker output."""
    if df is None or getattr(df, "empty", True):
        return None

    code = str(code).zfill(6)
    try:
        index_map = {str(idx).zfill(6): idx for idx in df.index}
        if code in index_map:
            return df.loc[index_map[code]]
    except Exception:
        pass

    if allow_last_row:
        try:
            return df.iloc[-1]
        except Exception:
            return None

    return None


def _fetch_krx_fundamental_row(pykrx_stock, date_text: str, code: str):
    """Try pykrx date-series and ticker-snapshot APIs because installed versions differ."""
    candidates = []

    if hasattr(pykrx_stock, "get_market_fundamental_by_date"):
        candidates.append(("by_date", lambda: pykrx_stock.get_market_fundamental_by_date(date_text, date_text, code), True))
    if hasattr(pykrx_stock, "get_market_fundamental"):
        candidates.append(("legacy_by_date", lambda: pykrx_stock.get_market_fundamental(date_text, date_text, code), True))
    if hasattr(pykrx_stock, "get_market_fundamental_by_ticker"):
        candidates.append(("by_ticker_all", lambda: pykrx_stock.get_market_fundamental_by_ticker(date_text, market="ALL"), False))
    if hasattr(pykrx_stock, "get_market_fundamental"):
        candidates.append(("legacy_by_ticker_all", lambda: pykrx_stock.get_market_fundamental(date_text, market="ALL"), False))

    for _, getter, allow_last_row in candidates:
        try:
            row = _select_krx_fundamental_row(getter(), code, allow_last_row=allow_last_row)
            if row is not None:
                return row
        except Exception:
            continue

    return None


_NAVER_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Accept": "application/json",
    "Referer": "https://m.stock.naver.com/",
}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_naver_kr_snapshot(ticker: str) -> dict:
    """
    네이버 증권 모바일 API에서 한국 종목 밸류/애널리스트 데이터를 가져옵니다.
    yfinance 키 규약과 동일한 data 딕셔너리를 반환합니다:
      trailingPE, priceToBook, returnOnEquity, profitMargins, operatingMargins,
      revenueGrowth, targetMeanPrice, numberOfAnalystOpinions, recommendationKey
    실패하거나 데이터가 없으면 ok=False 반환 (기존 동작 유지).
    """
    if not _HAS_REQUESTS:
        return {"ok": False, "reason": "requests 라이브러리 없음", "data": {}}
    if not str(ticker).upper().endswith((".KS", ".KQ")):
        return {"ok": False, "reason": "한국 종목 아님", "data": {}}

    code = str(ticker).upper().replace(".KS", "").replace(".KQ", "").strip()
    result = {}

    # ── 1. PER, PBR, EPS — KRX 공식 데이터 (pykrx 우선, 네이버 보조) ───────────
    _krx_ok = False
    try:
        from pykrx import stock as _pykrx
        from datetime import date as _date, timedelta as _td
        for _days_back in range(0, 8):  # 오늘부터 최대 7 거래일 전까지 시도
            _d = (_date.today() - _td(days=_days_back)).strftime("%Y%m%d")
            try:
                _row = _fetch_krx_fundamental_row(_pykrx, _d, code)
                if _row is not None:
                    _per = float(_row.get("PER") or 0)
                    _pbr = float(_row.get("PBR") or 0)
                    _eps = float(_row.get("EPS") or 0)
                    _bps = float(_row.get("BPS") or 0)
                    if _per > 0:
                        result["trailingPE"] = _per
                    if _pbr > 0:
                        result["priceToBook"] = _pbr
                    if _eps != 0:
                        result["trailingEps"] = _eps
                    if _bps > 0:
                        result["bookValue"] = _bps
                    _krx_ok = True
                    break
            except Exception:
                continue
    except ImportError:
        pass

    # pykrx 실패 시 네이버 basic API 보조
    if not _krx_ok and _HAS_REQUESTS:
        try:
            r = _requests.get(
                f"https://m.stock.naver.com/api/stock/{code}/basic",
                headers=_NAVER_MOBILE_HEADERS, timeout=6,
            )
            if r.status_code == 200:
                d = r.json()
                per = _parse_kr_num(d.get("per"))
                pbr = _parse_kr_num(d.get("pbr"))
                if per and per > 0:
                    result["trailingPE"] = per
                if pbr and pbr > 0:
                    result["priceToBook"] = pbr
        except Exception:
            pass

    # ── 2. Financial summary: ROE, margins, revenue growth ───────────────────
    try:
        r = _requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/summaryFinancial",
            headers=_NAVER_MOBILE_HEADERS, timeout=6,
        )
        if r.status_code == 200:
            d = r.json()
            roe = _parse_kr_num(d.get("roe") or d.get("returnOnEquity") or d.get("ROE"))
            op_margin = _parse_kr_num(
                d.get("operatingProfitMargin") or d.get("operatingMarginRatio") or d.get("opm")
            )
            net_margin = _parse_kr_num(
                d.get("netProfitMargin") or d.get("profitMargin") or d.get("npm")
            )
            rev_growth = _parse_kr_num(
                d.get("revenueGrowth") or d.get("salesGrowthRate") or d.get("revGrowth")
            )
            if roe:
                result["returnOnEquity"] = roe / 100.0
            if op_margin:
                result["operatingMargins"] = op_margin / 100.0
            if net_margin:
                result["profitMargins"] = net_margin / 100.0
            if rev_growth:
                result["revenueGrowth"] = rev_growth / 100.0
    except Exception:
        pass

    # ── 3. Analyst consensus: target price, opinion ───────────────────────────
    # Naver wraps FnGuide/WiseReport data. Try a few known endpoint paths.
    for analytics_path in ("analytics", "consensus", "opinion"):
        try:
            r = _requests.get(
                f"https://m.stock.naver.com/api/stock/{code}/{analytics_path}",
                headers=_NAVER_MOBILE_HEADERS, timeout=6,
            )
            if r.status_code != 200:
                continue
            d = r.json()
            # Consensus may be nested or flat; try common key patterns
            consensus = d if isinstance(d, dict) else {}
            for sub_key in ("consensus", "analystConsensus", "targetInfo"):
                if isinstance(d.get(sub_key), dict):
                    consensus = d[sub_key]
                    break

            target = _parse_kr_num(
                consensus.get("targetPrice")
                or consensus.get("meanTargetPrice")
                or consensus.get("avgTargetPrice")
                or consensus.get("targetPriceMean")
                or consensus.get("conensusPrice")
            )
            opinions_raw = (
                consensus.get("analystCount")
                or consensus.get("count")
                or consensus.get("numberOfAnalysts")
                or consensus.get("opinionCount")
            )
            rec_raw = (
                consensus.get("opinion")
                or consensus.get("recommendation")
                or consensus.get("opinionStr")
                or consensus.get("consensusOpinion")
            )
            if target and target > 0:
                result["targetMeanPrice"] = target
            if opinions_raw is not None:
                try:
                    result["numberOfAnalystOpinions"] = int(str(opinions_raw).replace(",", ""))
                except Exception:
                    pass
            if rec_raw:
                result["recommendationKey"] = str(rec_raw)
            if target:  # got what we need; stop trying other paths
                break
        except Exception:
            pass

    has_any = bool(result)
    return {
        "ok": has_any,
        "data": result,
        "reason": "" if has_any else "네이버 증권 데이터 없음",
    }


@st.cache_data(ttl=21600, show_spinner=False)
def get_analyst_snapshot(ticker):
    try:
        info = yf.Ticker(ticker).get_info()
    except Exception as e:
        info = {}

    if not isinstance(info, dict):
        info = {}

    keys = [
        "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
        "numberOfAnalystOpinions", "recommendationMean", "recommendationKey",
        "currentPrice", "regularMarketPrice",
    ]
    data = {key: info.get(key) for key in keys}
    has_any = any(data.get(key) not in [None, ""] for key in keys)

    # ── 한국 종목은 yfinance가 현재가만 주고 목표가/의견은 비우는 경우가 많아 네이버로 보완 ──
    is_kr = str(ticker).upper().endswith((".KS", ".KQ"))
    has_target = any(finite_num(data.get(key)) and clean_float(data.get(key), 0) > 0 for key in [
        "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
    ])
    has_opinion = (clean_int(data.get("numberOfAnalystOpinions"), 0) or 0) > 0 or bool(str(data.get("recommendationKey") or "").strip())

    if is_kr and (not has_target or not has_opinion):
        naver = fetch_naver_kr_snapshot(ticker)
        if naver.get("ok"):
            nd = naver.get("data", {})
            for key in keys:
                if data.get(key) in [None, ""] and nd.get(key) not in [None, ""]:
                    data[key] = nd[key]
            has_any = any(data.get(key) not in [None, ""] for key in keys)

    return {"ok": has_any, "data": data, "reason": "" if has_any else "목표가/투자의견 데이터 없음"}


def build_research_report_links(ticker, name):
    symbol = normalize_news_token(ticker).upper()
    display_name = strip_search_prefix(name or ticker)
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
    elif not finite_num(target_mean) and not opinions:
        st.caption(f"목표가 데이터 없음: {snapshot.get('reason', '제공 데이터 없음')}")

    links = build_research_report_links(ticker, name)
    link_cols = st.columns(min(len(links), 3))
    for i, item in enumerate(links):
        link_cols[i % len(link_cols)].link_button(item["label"], item["url"], use_container_width=True)

    is_kr = str(ticker).upper().endswith((".KS", ".KQ"))
    if is_kr:
        st.caption("목표가와 투자의견: yfinance → 네이버 증권 순서로 자동 보완합니다. 그래도 데이터가 없으면 리포트 검색 링크를 이용하세요.")
    else:
        st.caption("목표가와 투자의견은 yfinance 제공 데이터 기준입니다. 한국 종목은 제공되지 않는 경우가 많아 리포트 검색 링크를 함께 제공합니다.")


def normalize_news_token(text):
    return strip_search_prefix(text).replace(".KS", "").replace(".KQ", "").strip()

def clean_news_text(value):
    return html.unescape(str(value or "")).replace("<b>", "").replace("</b>", "").strip()

def get_news_company_names(ticker, name):
    symbol = normalize_news_token(ticker).upper()
    display_name = strip_search_prefix(name)

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
            f'"{main}" 실적 발표',
            f'"{main}" 분기 실적',
            f'"{main}" 매출 영업이익',
            f'"{main}" 잠정실적',
            f'"{main}" 주가 실적',
            f'"{main}" 증권',
            f'{symbol} 주가 실적',
        ]
    else:
        queries = [
            f'"{main}" earnings shares',
            f'"{main}" earnings results {symbol}',
            f'"{main}" quarterly results revenue guidance',
            f'"{symbol}" earnings results',
            f'"{main}" investor relations results',
            f'"{main}" {symbol} stock',
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
    display_name = strip_search_prefix(name)
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
    has_earnings_word = keyword_in_text(text, EARNINGS_NEWS_WORDS)
    has_market_word = keyword_in_text(text, ["nasdaq", "s&p", "fed", "yield", "rate", "inflation", "earnings", "증시", "코스피", "코스닥", "금리", "환율", "외국인"])
    is_low_quality = keyword_in_text(text, LOW_QUALITY_NEWS_WORDS)

    score = 0
    if has_company: score += 5
    if has_symbol: score += 4
    if has_theme: score += 3
    if has_high_value_word: score += 2
    if has_earnings_word and category == NEWS_CATEGORY_DIRECT: score += 4
    elif has_earnings_word: score += 2
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
        ok = (has_company or has_symbol) and (has_stock_word or has_high_value_word or has_earnings_word or not strict) and score >= 3
    elif category == NEWS_CATEGORY_SECTOR:
        ok = (has_company or has_symbol or has_theme) and score >= 2
    else:
        ok = has_market_word and score >= 1

    if is_low_quality and category == NEWS_CATEGORY_DIRECT and score < 5:
        ok = False

    if category == NEWS_CATEGORY_DIRECT and has_earnings_word and (has_company or has_symbol):
        relation = "실적 직접"
    elif score >= 7:
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
    elif category == NEWS_CATEGORY_DIRECT and has_earnings_word:
        sentiment, reason = "중립", "실적/가이던스 직접 뉴스입니다. 수치와 컨센서스 대비 여부를 확인하세요."
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
        "topic": "실적/IR" if has_earnings_word else "",
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
            "topic": assessment.get("topic", ""),
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

            if accepted_by_category.get(category, 0) >= NEWS_CATEGORY_SEARCH_LIMITS.get(category, NEWS_CATEGORY_LIMITS.get(category, 1)):
                break

        return len(items), accepted

    for plan in query_plan:
        q = plan["query"]
        category = plan["category"]
        strict = plan.get("strict", True)
        if accepted_by_category.get(category, 0) >= NEWS_CATEGORY_SEARCH_LIMITS.get(category, NEWS_CATEGORY_LIMITS.get(category, 1)):
            continue
        if sum(accepted_by_category.values()) >= NEWS_MAX_CANDIDATES:
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

        if accepted_by_category.get(category, 0) >= NEWS_CATEGORY_SEARCH_LIMITS.get(category, NEWS_CATEGORY_LIMITS.get(category, 1)):
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
            0 if x.get("topic") == "실적/IR" else 1,
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
            safe_topic = escape_html_value(item.get("topic", ""))
            date_part = f" | {safe_date}" if safe_date else ""
            safe_link = str(item.get("link", "#")).strip()
            if not safe_link.startswith(("http://", "https://")):
                safe_link = "#"
            safe_link_attr = html.escape(safe_link, quote=True)
            topic_chip = f"<span class='news-chip'>{safe_topic}</span>" if safe_topic else ""

            sentiment_class = news_sentiment_class(item.get("sentiment", "중립"))
            st.markdown(
                f"<div class='news-box news-{sentiment_class}'>"
                f"<a href='{safe_link_attr}' target='_blank'>🔗 {safe_title}</a>"
                f"<div class='news-meta-row'>"
                f"<span class='news-chip news-chip-category'>{safe_category}</span>"
                f"{topic_chip}"
                f"<span class='news-chip news-chip-{sentiment_class}'>{safe_sentiment}</span>"
                f"<span class='news-chip'>{safe_relation}</span>"
                f"출처: {safe_pub}{date_part} | 품질점수: {safe_score}"
                f"</div>"
                f"<div class='news-reason'>{safe_reason}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


_NAVER_PC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_investor_trend(ticker: str, days: int = 20) -> dict:
    """
    네이버 금융 frgn.naver HTML 파싱으로 외국인 일별 수급 데이터를 가져옵니다.
    반환: {ok, foreign_net, foreign_ratio, rows, reason}
    rows: list of {date, price, volume, foreign_net, foreign_ratio}
    """
    if not _HAS_REQUESTS:
        return {"ok": False, "reason": "requests 없음", "rows": []}
    if not str(ticker).upper().endswith((".KS", ".KQ")):
        return {"ok": False, "reason": "한국 종목만 지원", "rows": []}

    code = str(ticker).upper().replace(".KS", "").replace(".KQ", "").strip()

    try:
        import re as _re
        url = f"https://finance.naver.com/item/frgn.naver?code={code}"
        r = _requests.get(url, headers=_NAVER_PC_HEADERS, timeout=10)
        if r.status_code != 200:
            return {"ok": False, "reason": f"HTTP {r.status_code}", "rows": []}

        # 네이버 금융이 UTF-8로 전환됐으므로 UTF-8 우선 시도, 실패 시 EUC-KR 폴백
        try:
            content = r.content.decode("utf-8")
        except UnicodeDecodeError:
            content = r.content.decode("euc-kr", errors="replace")

        # <tr> 행에서 날짜 패턴(YYYY.MM.DD)이 있는 행만 추출
        tr_blocks = _re.findall(r"<tr[^>]*>(.*?)</tr>", content, _re.DOTALL)
        rows = []
        for block in tr_blocks:
            tds = _re.findall(r"<td[^>]*>(.*?)</td>", block, _re.DOTALL)
            # td 태그 내 HTML 제거 후 텍스트만 추출
            cells = [_re.sub(r"<[^>]+>", "", td).strip().replace("\xa0", "").replace(",", "") for td in tds]
            cells = [c for c in cells if c]
            # 날짜 셀(YYYY.MM.DD) + 9개 컬럼 확인
            if len(cells) >= 6 and _re.match(r"\d{4}\.\d{2}\.\d{2}", cells[0]):
                try:
                    price = int(float(cells[1])) if cells[1] else 0
                    volume = int(float(cells[4])) if len(cells) > 4 and cells[4] else 0
                    f_net_raw = cells[5] if len(cells) > 5 else ""
                    f_net = int(float(f_net_raw)) if f_net_raw and f_net_raw not in ("-", "") else 0
                    ratio = cells[8].replace("%", "").strip() if len(cells) > 8 else "-"
                    rows.append({
                        "date": cells[0],
                        "price": price,
                        "volume": volume,
                        "foreign_net": f_net,
                        "foreign_ratio": ratio,
                    })
                except (ValueError, IndexError):
                    continue
            if len(rows) >= days:
                break

        if not rows:
            return {"ok": False, "reason": "수급 행을 파싱하지 못했습니다", "rows": []}

        recent = rows[:5] if len(rows) >= 5 else rows
        return {
            "ok": True,
            "foreign_net": sum(row["foreign_net"] for row in recent),
            "foreign_ratio": rows[0]["foreign_ratio"],
            "rows": rows,
        }
    except Exception as e:
        return {"ok": False, "reason": str(e), "rows": []}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_naver_investor_flow(code: str) -> dict:
    """
    네이버 증권 모바일 API로 외국인·기관·개인 일별 순매수(주) 데이터를 반환합니다.
    반환: {ok, rows: [{date, foreign, inst, individual, price, volume}], reason}
    단위: 주(株)
    """
    if not _HAS_REQUESTS:
        return {"ok": False, "reason": "requests 없음", "rows": []}
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://m.stock.naver.com/",
        }
        r = _requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return {"ok": False, "reason": f"HTTP {r.status_code}", "rows": []}

        data = r.json()
        deal_infos = data.get("dealTrendInfos", [])
        if not deal_infos:
            return {"ok": False, "reason": "dealTrendInfos 없음", "rows": []}

        def _parse_qty(s: str) -> int:
            """'+10,257,346' → 10257346, '-8,855,741' → -8855741"""
            try:
                return int(str(s).replace(",", "").replace("+", ""))
            except Exception:
                return 0

        rows = []
        for item in deal_infos:
            biz = str(item.get("bizdate", ""))
            if len(biz) == 8:
                date_str = f"{biz[:4]}.{biz[4:6]}.{biz[6:]}"
            else:
                date_str = biz

            close_raw = str(item.get("closePrice", "0")).replace(",", "")
            vol_raw   = str(item.get("accumulatedTradingVolume", "0")).replace(",", "")

            rows.append({
                "date":       date_str,
                "foreign":    _parse_qty(item.get("foreignerPureBuyQuant", "0")),
                "inst":       _parse_qty(item.get("organPureBuyQuant",     "0")),
                "individual": _parse_qty(item.get("individualPureBuyQuant","0")),
                "price":      int(close_raw) if close_raw.lstrip("-").isdigit() else 0,
                "volume":     int(vol_raw)   if vol_raw.isdigit() else 0,
            })

        # 최신일 → 과거 순서로 정렬
        rows.sort(key=lambda r: r["date"], reverse=True)
        return {"ok": True, "rows": rows}
    except Exception as e:
        return {"ok": False, "reason": str(e), "rows": []}


def render_investor_trend_panel(ticker: str, name: str):
    """외국인·기관·개인 수급 현황 패널. (한국 종목 전용, 네이버 API)"""
    if not str(ticker).upper().endswith((".KS", ".KQ")):
        return

    code = str(ticker).upper().replace(".KS", "").replace(".KQ", "").strip()

    with st.spinner("수급 데이터 로딩 중…"):
        inv  = fetch_investor_trend(ticker)       # 네이버: 외국인 보유비율 20일
        flow = _fetch_naver_investor_flow(code)   # 네이버 모바일: 외국인·기관·개인 5일

    # ── 헬퍼 ──────────────────────────────────────────────────────────────────
    def _badge(v, unit="주"):
        if v == 0:
            return f"<span style='color:#94a3b8'>0 {unit}</span>"
        sign = "▲" if v > 0 else "▼"
        color = "#22c55e" if v > 0 else "#ef4444"
        return f"<span style='color:{color};font-weight:600'>{sign} {abs(v):,.0f} {unit}</span>"

    def _sum_all(rows, key):
        return sum(r.get(key, 0) for r in rows)

    flow_rows = flow.get("rows", []) if flow.get("ok") else []

    # ── 요약 메트릭 ───────────────────────────────────────────────────────────
    f_ratio      = inv.get("foreign_ratio", "-") if inv.get("ok") else "-"
    f_net_shares = inv.get("foreign_net", 0) or 0   # 외국인 최근 순매수(주)

    metric_items = [
        ("외국인 보유비율", f"{f_ratio}%", None, None),
    ]
    if flow.get("ok") and flow_rows:
        n = len(flow_rows)
        label_suffix = f"{n}일"
        metric_items += [
            (f"외국인 {label_suffix}", None, _sum_all(flow_rows, "foreign"),    "주"),
            (f"기관합계 {label_suffix}", None, _sum_all(flow_rows, "inst"),     "주"),
            (f"개인 {label_suffix}",   None, _sum_all(flow_rows, "individual"), "주"),
        ]
    else:
        metric_items += [
            ("외국인 5일 (주)", None, f_net_shares, "주"),
        ]

    cols = st.columns(len(metric_items))
    for col, (label, plain_val, badge_val, unit) in zip(cols, metric_items):
        with col:
            if plain_val is not None:
                st.metric(label, plain_val)
            else:
                st.markdown(
                    f"**{label}**<br>{_badge(badge_val, unit)}",
                    unsafe_allow_html=True,
                )

    if not flow.get("ok") or not flow_rows:
        st.caption(f"⚠️ 수급 상세 로드 실패: {flow.get('reason', '')}")
        return

    # ── 투자자별 순매수 바 차트 ───────────────────────────────────────────────
    if _HAS_PLOTLY:
        chart_rows = list(reversed(flow_rows))  # 날짜 오름차순
        dates = [r["date"] for r in chart_rows]

        _CHART_INVESTORS = [
            ("foreign",    "외국인",   "#22c55e", "#ef4444"),
            ("inst",       "기관합계", "#3b82f6", "#f97316"),
            ("individual", "개인",     "#f59e0b", "#64748b"),
        ]

        fig = _go.Figure()
        for key, label, pos_color, neg_color in _CHART_INVESTORS:
            vals = [r.get(key, 0) for r in chart_rows]
            if all(v == 0 for v in vals):
                continue
            colors = [pos_color if v >= 0 else neg_color for v in vals]
            fig.add_trace(_go.Bar(
                x=dates, y=vals, name=label,
                marker_color=colors,
                opacity=0.85,
            ))

        fig.update_layout(
            barmode="group",
            height=300,
            margin=dict(l=8, r=8, t=28, b=8),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis_title="순매수 (주)",
            xaxis_tickangle=-30,
            template="plotly_dark",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── 상세 테이블 ──────────────────────────────────────────────────────────
    _LABEL_MAP = {"foreign": "외국인", "inst": "기관합계", "individual": "개인"}

    def _fmt(v):
        if v == 0:
            return "-"
        return f"+{v:,.0f}" if v > 0 else f"{v:,.0f}"

    table_data = []
    for r in flow_rows:
        row_dict = {"날짜": r["date"]}
        for k, lbl in _LABEL_MAP.items():
            row_dict[lbl] = _fmt(r.get(k, 0))
        row_dict["종가"] = f"{r.get('price', 0):,}" if r.get("price") else "-"
        row_dict["거래량"] = f"{r.get('volume', 0):,}" if r.get("volume") else "-"
        table_data.append(row_dict)

    with st.expander("📋 투자자별 일별 순매수 상세 (주)", expanded=False):
        df_detail = pd.DataFrame(table_data)
        st.dataframe(df_detail, use_container_width=True, hide_index=True)
        st.caption("출처: 네이버 증권 | 단위: 주(株)")

    # ── 네이버 외국인 보유비율 상세 (기존 유지) ───────────────────────────────
    naver_rows = inv.get("rows", []) if inv.get("ok") else []
    if naver_rows:
        with st.expander("외국인 보유비율 상세 (주식 수 기준, 네이버)", expanded=False):
            df_inv = pd.DataFrame([
                {
                    "날짜": r["date"],
                    "현재가": f"{r['price']:,}",
                    "거래량": f"{r['volume']:,}",
                    "외국인순매수(주)": f"+{r['foreign_net']:,}" if r["foreign_net"] > 0 else f"{r['foreign_net']:,}",
                    "외국인비율": f"{r['foreign_ratio']}%",
                }
                for r in naver_rows
            ])
            st.dataframe(df_inv, use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────────────────────────────────────
# 오늘 투자자별 순매수 TOP 10
# ──────────────────────────────────────────────────────────────────────────────

def _krx_auth_available() -> bool:
    """
    KRX_ID / KRX_PW가 os.environ 또는 st.secrets에 있으면 True.
    st.secrets에 있을 경우 pykrx가 사용할 수 있도록 os.environ에 자동 복사합니다.
    """
    import os
    krx_id = os.getenv("KRX_ID", "")
    krx_pw = os.getenv("KRX_PW", "")

    # st.secrets 에서 보완
    if not (krx_id and krx_pw):
        try:
            krx_id = str(st.secrets.get("KRX_ID") or st.secrets.get("krx_id") or "")
            krx_pw = str(st.secrets.get("KRX_PW") or st.secrets.get("krx_pw") or "")
            if krx_id and krx_pw:
                # pykrx 는 os.getenv() 로 읽으므로 환경변수에 복사
                os.environ["KRX_ID"] = krx_id
                os.environ["KRX_PW"] = krx_pw
        except Exception:
            pass

    return bool(krx_id and krx_pw)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_investor_top10_pykrx(base_date_str: str) -> dict:
    """
    pykrx로 전체 시장(KOSPI+KOSDAQ) 투자자별 순매수 상위 종목을 가져옵니다.
    base_date_str 기준으로 데이터가 없으면 최대 5 거래일 전까지 자동 탐색합니다.
    KRX 인증(KRX_ID / KRX_PW)이 필요합니다.
    반환: {"연기금": df, "외국인": df, "기관합계": df, "개인": df}
    """
    try:
        from pykrx import stock as _pykrx
        from datetime import datetime as _dt, timedelta as _tdd

        # ── 직전 거래일 탐색 (오늘 포함 최대 7일 전까지) ──────────────────
        def _last_trading_day(from_str: str) -> str | None:
            d = _dt.strptime(from_str, "%Y%m%d")
            for _ in range(7):
                if d.weekday() < 5:  # 월~금
                    # 간단 테스트: KOSPI 연기금 데이터 있는지 확인
                    test = _pykrx.get_market_net_purchases_of_equities_by_ticker(
                        fromdate=d.strftime("%Y%m%d"),
                        todate=d.strftime("%Y%m%d"),
                        market="KOSPI", investor="연기금",
                    )
                    if test is not None and not test.empty:
                        return d.strftime("%Y%m%d")
                d -= _tdd(days=1)
            return None

        date_str = _last_trading_day(base_date_str)
        if not date_str:
            return {"ok": False, "reason": "최근 7일 내 거래 데이터 없음", "data": {}}

        # ── 병렬로 8개 (4투자자 × 2시장) API 호출 ────────────────────────────
        from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac

        def _fetch_krx_one(inv: str, market: str):
            df = _pykrx.get_market_net_purchases_of_equities_by_ticker(
                fromdate=date_str, todate=date_str,
                market=market, investor=inv,
            )
            return inv, market, df

        investor_list = ["연기금", "외국인", "기관합계", "개인"]
        raw: dict[str, list] = {inv: [] for inv in investor_list}

        with _TPE(max_workers=8) as ex:
            futs = {
                ex.submit(_fetch_krx_one, inv, market): (inv, market)
                for inv in investor_list
                for market in ["KOSPI", "KOSDAQ"]
            }
            for fut in _ac(futs):
                inv, market, df = fut.result()
                if df is None or df.empty:
                    continue
                net_val_col = next((c for c in df.columns if "순매수" in str(c) and "대금" in str(c)), None)
                net_qty_col = next((c for c in df.columns if "순매수" in str(c) and "량" in str(c)), None)
                name_col    = next((c for c in df.columns if "종목명" in str(c)), None)
                if net_val_col is None:
                    continue
                for ticker, row in df.iterrows():
                    net_val = float(row[net_val_col]) / 1_000_000
                    net_qty = int(float(row[net_qty_col])) if net_qty_col else 0
                    name    = str(row[name_col]) if name_col else str(ticker)
                    raw[inv].append({
                        "Ticker":        str(ticker),
                        "종목명":        name,
                        "순매수(백만원)": round(net_val, 0),
                        "순매수(주)":    net_qty,
                    })

        results = {}
        for inv, rows in raw.items():
            if rows:
                dff = (pd.DataFrame(rows)
                         .sort_values("순매수(백만원)", ascending=False)
                         .head(10)
                         .reset_index(drop=True))
                dff.index = dff.index + 1
                results[inv] = dff

        if not results:
            return {"ok": False, "reason": f"{date_str} 데이터 없음", "data": {}}
        return {"ok": True, "data": results, "source": "pykrx(KRX)", "date": date_str}
    except Exception as e:
        return {"ok": False, "reason": str(e), "data": {}}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_investor_top10_naver(ticker_list: tuple) -> dict:
    """
    네이버 모바일 API로 추적 종목 중 투자자별 순매수 TOP 10을 가져옵니다.
    단위: 주(株).
    반환: {"외국인": df, "기관합계": df, "개인": df}
    """
    if not _HAS_REQUESTS or not ticker_list:
        return {"ok": False, "reason": "requests 없음 또는 종목 없음", "data": {}}
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
        import threading

        naver_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://m.stock.naver.com/",
        }

        def _parse_qty(s: str) -> int:
            try:
                return int(str(s).replace(",", "").replace("+", ""))
            except Exception:
                return 0

        def _fetch_one(full_ticker: str):
            code = full_ticker.upper().replace(".KS", "").replace(".KQ", "").strip()
            try:
                url = f"https://m.stock.naver.com/api/stock/{code}/integration"
                r = _requests.get(url, headers=naver_headers, timeout=4)
                if r.status_code != 200:
                    return None
                data = r.json()
                deal = data.get("dealTrendInfos", [])
                if not deal:
                    return None
                item = deal[0]  # 최신일 데이터

                # 종목명 추출
                name = ""
                for ti in data.get("totalInfos", []):
                    if ti.get("code") == "lastClosePrice":
                        break
                name = data.get("stockName", code)

                return {
                    "Ticker":   full_ticker,
                    "code":     code,
                    "종목명":   name,
                    "date":     item.get("bizdate", ""),
                    "foreign":  _parse_qty(item.get("foreignerPureBuyQuant", "0")),
                    "inst":     _parse_qty(item.get("organPureBuyQuant", "0")),
                    "individual": _parse_qty(item.get("individualPureBuyQuant", "0")),
                }
            except Exception:
                return None

        rows = []
        with ThreadPoolExecutor(max_workers=15) as ex:  # workers 늘려서 병렬성 향상
            futures = {ex.submit(_fetch_one, t): t for t in ticker_list}
            for fut in _as_completed(futures):
                result = fut.result()
                if result:
                    rows.append(result)

        if not rows:
            return {"ok": False, "reason": "네이버 데이터 없음", "data": {}}

        df_all = pd.DataFrame(rows)

        def _make_top10(key: str, label: str) -> pd.DataFrame:
            tmp = df_all[["종목명", "Ticker", key]].copy()
            tmp = tmp.rename(columns={key: f"순매수(주)"})
            tmp = tmp.sort_values("순매수(주)", ascending=False).head(10).reset_index(drop=True)
            tmp.index = tmp.index + 1
            return tmp

        results = {
            "외국인":   _make_top10("foreign",    "외국인"),
            "기관합계": _make_top10("inst",        "기관합계"),
            "개인":     _make_top10("individual",  "개인"),
        }
        # 날짜 정보
        latest_date = df_all["date"].max() if not df_all.empty else ""
        return {"ok": True, "data": results, "source": "네이버", "date": latest_date}
    except Exception as e:
        return {"ok": False, "reason": str(e), "data": {}}


def render_investor_top10_panel(ticker_list: list):
    """오늘 투자자별 순매수 TOP 10 패널. 오늘 점검용."""
    st.markdown("#### 📊 오늘 투자자별 순매수 TOP 10")

    kr_tickers = tuple(
        t for t in ticker_list
        if str(t).upper().endswith((".KS", ".KQ"))
    )

    has_krx = _krx_auth_available()

    # ── KRX 자격증명 없을 때 안내 ──────────────────────────────────────
    if not has_krx:
        import os
        with st.expander("🔑 연기금 포함 전체 시장 TOP 10 활성화 방법"):
            st.markdown(
                "`.streamlit/secrets.toml` 파일에 아래 두 줄을 추가한 뒤 앱을 재시작하세요:\n\n"
                "```toml\n"
                "KRX_ID = \"data.krx.co.kr 아이디\"\n"
                "KRX_PW = \"data.krx.co.kr 비밀번호\"\n"
                "```\n\n"
                "계정이 없으면 [KRX 마켓데이터](https://data.krx.co.kr)에서 회원가입하세요."
            )
    result = None

    if has_krx:
        from datetime import date as _d
        today_str = _d.today().strftime("%Y%m%d")
        with st.spinner("KRX 투자자 순매수 로딩 중…"):
            result = fetch_investor_top10_pykrx(today_str)
        if result.get("ok"):
            _rd = result.get("date", "")
            _rd_label = f"{_rd[:4]}.{_rd[4:6]}.{_rd[6:]}" if len(_rd) == 8 else _rd
            st.caption(f"KRX 인증 · 전체 시장 기준 · 연기금/외국인/기관/개인 · 단위: 백만원 | 기준일: {_rd_label}")
            _investors = ["연기금", "외국인", "기관합계", "개인"]
            _val_col   = "순매수(백만원)"
        else:
            # pykrx 실패 → 네이버 폴백
            _fail_reason = result.get("reason", "")
            st.warning(
                f"⚠️ KRX 데이터 로드 실패 → 네이버 폴백\n\n"
                f"**원인:** `{_fail_reason}`\n\n"
                f"KRX 계정(data.krx.co.kr)이 올바른지 확인하고 앱을 재시작하세요."
            )
            result = None  # 아래에서 네이버로 재조회

    if result is None or not result.get("ok"):
        if not kr_tickers:
            st.info("한국 종목이 없습니다.")
            return
        if not has_krx:  # KRX 없을 때만 안내 caption 표시
            st.caption(
                f"추적 종목 {len(kr_tickers)}개 기준 · 외국인/기관/개인 · 단위: 주(株) · 네이버 출처 | "
                "연기금 포함 전체 시장 TOP 10은 KRX_ID/KRX_PW 설정 후 사용 가능"
            )
        with st.spinner(f"네이버 수급 조회 중… ({len(kr_tickers)}개 종목)"):
            result = fetch_investor_top10_naver(kr_tickers)
        _investors = ["외국인", "기관합계", "개인"]
        _val_col   = "순매수(주)"

    if not result.get("ok"):
        st.warning(f"수급 TOP 10 로드 실패: {result.get('reason', '')}")
        return

    data = result.get("data", {})
    date_label = result.get("date", "")
    if date_label and len(date_label) == 8:
        date_label = f"{date_label[:4]}.{date_label[4:6]}.{date_label[6:]}"

    cols = st.columns(len(_investors))
    for col, inv_name in zip(cols, _investors):
        df_top = data.get(inv_name)
        with col:
            st.markdown(f"**{inv_name}** 순매수↑")
            if df_top is None or df_top.empty:
                st.caption("데이터 없음")
                continue

            def _fmt_val(v):
                if v == 0:
                    return "-"
                return f"+{v:,.0f}" if v > 0 else f"{v:,.0f}"

            display = df_top[["종목명", _val_col]].copy()
            display[_val_col] = display[_val_col].apply(_fmt_val)
            st.dataframe(display, use_container_width=True, hide_index=False)

    if date_label:
        st.caption(f"기준일: {date_label} | 출처: {result.get('source', '-')}")

