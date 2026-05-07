from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import io
import zipfile
import requests
import json
import base64
import numpy as np
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import html
import re
from supabase import create_client
from stock_lab_core.backup import (
    RECOVERY_KIND_INFO,
    add_recovery_issue,
    build_portfolio_backup_zip,
    collect_recovery_frames,
    count_valid_rows,
    dataframe_to_csv_bytes,
    get_duplicate_recovery_values,
)
from stock_lab_core.config import (
    DEFAULT_WATCHLIST,
    DIVIDENDS_COLUMNS,
    FIN_SCORE_COLUMNS,
    HOLDINGS_COLUMNS,
    MONTHLY_LOG_COLUMNS,
    RESERVE_BUCKETS,
    RESERVE_TICKERS,
    SETTINGS_COLUMNS,
    SWING_EDITOR_COLUMNS,
    SWING_RADAR_COLUMNS,
    SWING_TEMPLATE_TEXT_FIELDS,
    WATCHLIST_COLUMNS,
)
from stock_lab_core.formatters import (
    clean_bool,
    clean_float,
    clean_int,
    dataframe_from_rows,
    escape_html_value,
    format_currency,
    normalize_text,
    normalize_ticker,
    parse_num,
    sanitize_ticker_value,
    strip_search_prefix,
)
from stock_lab_core.news import (
    get_analyst_snapshot,
    get_ticker_news,
    render_news_cards,
    render_research_report_panel,
)
from stock_lab_core.money_flow import (
    calculate_money_flow_df,
    download_money_flow_prices,
)
from stock_lab_core.kr_etf_data import (
    KR_ETF_DATA_PATH,
    build_kr_etf_lab_from_excel_files,
    derive_kr_etf_tags,
    load_kr_etf_lab_dataframe,
    save_kr_etf_lab_dataframe,
)
from stock_lab_core.prices import (
    clear_latest_price_cache,
    clear_selected_price_cache,
    load_latest_price,
    load_latest_prices_batch,
    load_price_df,
    normalize_price_lookup_key,
)
try:
    from stock_lab_core.prices import load_usdkrw_rate
except ImportError:
    @st.cache_data(ttl=3600, show_spinner=False)
    def load_usdkrw_rate():
        try:
            df = yf.download("USDKRW=X", period="5d", interval="1d", progress=False, auto_adjust=False)
            if df is None or df.empty:
                return 0.0
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.ffill().dropna()
            if df.empty or "Close" not in df.columns:
                return 0.0
            return float(df["Close"].iloc[-1])
        except Exception:
            return 0.0
from stock_lab_core.portfolio import (
    append_cash_rows,
    apply_holdings_weight_columns,
    build_benchmark_return_df,
    calc_portfolio_summary,
    calc_reserve_summary,
    get_holding_row_by_ticker,
    make_cash_rows,
    parse_month_end_date,
    prepare_monthly_performance_df,
)

# -------------------------------------------------
# 1. 기본 설정 및 CSS
# -------------------------------------------------
st.set_page_config(page_title="최종 관제실", layout="wide")
KST = timezone(timedelta(hours=9))

def get_secret_value(name, fallback_name=None):
    value = st.secrets.get(name, "")
    if (not value) and fallback_name:
        value = st.secrets.get(fallback_name, "")
    return str(value).strip()


def get_secret_emails(name):
    value = st.secrets.get(name, [])
    if isinstance(value, str):
        value = [x.strip() for x in value.split(",")]
    return {str(x).strip().lower() for x in value if str(x).strip()}


def get_auth_mode():
    mode = get_secret_value("AUTH_MODE", "auth_mode").strip().lower()

    if mode in ["password", "pass", "local"]:
        return "password"
    if mode in ["google", "oauth"]:
        return "google"

    # Keep Google as the default. Password login is emergency-only and must be explicit.
    return "google"


def get_owner_email_for_password_login():
    allowed_emails = get_secret_emails("ALLOWED_EMAILS") | get_secret_emails("ADMIN_EMAILS")
    if allowed_emails:
        return sorted(allowed_emails)[0]

    fallback_email = get_secret_value("FALLBACK_OWNER_EMAIL")
    if fallback_email:
        return fallback_email.lower()

    st.error("Set ALLOWED_EMAILS, ADMIN_EMAILS, or FALLBACK_OWNER_EMAIL in Streamlit Secrets.")
    st.stop()


def require_password_login():
    app_password = get_secret_value("APP_PASSWORD")

    if not app_password:
        st.error("Set APP_PASSWORD in Streamlit Secrets or change AUTH_MODE back to google.")
        st.stop()

    if "password_ok" not in st.session_state:
        st.session_state.password_ok = False

    if not st.session_state.password_ok:
        st.title("Stock Lab")
        st.info("Enter the emergency password.")
        password = st.text_input("Password", type="password")

        if st.button("Log in"):
            if password == app_password:
                st.session_state.password_ok = True
                st.rerun()
            else:
                st.error("Wrong password.")

        st.stop()

    return get_owner_email_for_password_login()


def logout_current_user():
    if get_auth_mode() == "password":
        st.session_state.password_ok = False
        st.rerun()
    else:
        st.logout()


def require_login():
    if get_auth_mode() == "password":
        return require_password_login()

    if not st.user.is_logged_in:
        st.title("Stock Lab")
        st.info("Log in with your allowed Google account.")
        st.button("Log in with Google", on_click=st.login)
        st.stop()

    email = str(st.user.email or "").strip().lower()
    allowed_emails = get_secret_emails("ALLOWED_EMAILS") | get_secret_emails("ADMIN_EMAILS")

    if not allowed_emails:
        st.error("Set ALLOWED_EMAILS or ADMIN_EMAILS in Streamlit Secrets.")
        st.stop()

    if email not in allowed_emails:
        st.error("This Google account is not allowed to use this app.")
        st.write(f"Signed in as: {email}")
        st.button("Log out", on_click=logout_current_user)
        st.stop()

    return email


CURRENT_USER_EMAIL = require_login()


st.markdown("""
<style>
    .stApp { background-color: #0b0f19; }
    [data-testid="stSidebar"] { background-color: #111827 !important; border-right: 1px solid #1f2937; }
    h1, h2, h3, h4 { color: #f8fafc !important; font-weight: 800 !important; }
    .signal-box { padding: 20px; border-radius: 12px; text-align: center; margin-bottom: 15px; color: white !important; font-weight: bold; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5); }
    .macro-panel { background-color: #1e293b; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-top: 4px solid #e74c3c; font-size: 0.95em; color: #f8fafc; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .info-panel { background-color: #1e293b; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #3b82f6; color: #f8fafc; box-shadow: 0 4px 6px rgba(0,0,0,0.3); line-height: 1.7; }
    .smc-tag { font-size: 0.85em; color: #60a5fa; font-weight: bold; background-color: #111827; padding: 2px 6px; border-radius: 4px; border: 1px solid #334155; }
    .highlight { font-size: 1.4em; font-weight: bold; color: #fbbf24; text-shadow: 1px 1px 2px #000; }
    .score-detail { font-size: 0.9em; font-weight: normal; color: #cbd5e1; margin-top: 10px; }
    .news-box { background-color: #1e293b; padding: 12px; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #10b981; font-size: 0.9em; }
    .news-box a { color: #60a5fa; text-decoration: none; font-weight: bold; }
    .news-box a:hover { text-decoration: underline; }
    .news-box.news-positive { border-left-color: #22c55e; }
    .news-box.news-negative { border-left-color: #ef4444; }
    .news-box.news-neutral { border-left-color: #64748b; }
    .news-meta-row { margin-top: 7px; color: #94a3b8; font-size: 0.82em; line-height: 1.55; }
    .news-reason { margin-top: 5px; color: #cbd5e1; font-size: 0.86em; line-height: 1.55; }
    .news-chip { display: inline-block; padding: 2px 7px; border-radius: 999px; margin-right: 5px; font-size: 0.78em; font-weight: 800; border: 1px solid #334155; color: #e5e7eb; background: #111827; }
    .news-chip-positive { color: #bbf7d0; border-color: #166534; background: rgba(22, 101, 52, 0.35); }
    .news-chip-negative { color: #fecaca; border-color: #991b1b; background: rgba(153, 27, 27, 0.35); }
    .news-chip-neutral { color: #e5e7eb; border-color: #475569; background: rgba(71, 85, 105, 0.35); }
    .news-chip-category { color: #bfdbfe; border-color: #1d4ed8; background: rgba(29, 78, 216, 0.28); }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("🛠️ 관제탑 세팅")
    app_mode = st.radio("사용 모드", ["개인모드", "범용모드"], index=0, help="개인모드는 앱 내부 자산 연동, 범용모드는 직접 입력 방식입니다.")
    news_debug = st.checkbox("뉴스 디버그 보기", value=False)
    st.caption(f"Signed in: {CURRENT_USER_EMAIL}")
    st.button("Log out", on_click=logout_current_user, key="logout_sidebar")

st.title(f"🚀 REALTIME DIGITAL DASHBOARD v13.1 ({app_mode})")

def normalize_bucket(value):
    raw = str(value or "").strip().lower()
    if raw in ["core", "swing", "reserve", "cash"]:
        return raw
    return "core"

def infer_bucket(ticker, value=""):
    key = normalize_ticker(ticker)
    raw = str(value or "").strip().lower()

    if key in RESERVE_TICKERS and raw in ["", "core", "nan", "none"]:
        return "reserve"
    if raw in ["core", "swing", "reserve", "cash"]:
        return raw
    return "core"

def is_reserve_or_cash_bucket(bucket):
    return normalize_bucket(bucket) in RESERVE_BUCKETS

def get_sqz_status(last_sqz_on: bool, prev_sqz_on: bool) -> str:
    if last_sqz_on and not prev_sqz_on: return "⏳재압축"
    elif last_sqz_on and prev_sqz_on: return "⏳압축중"
    elif (not last_sqz_on) and prev_sqz_on: return "🚀해제직후"
    return "➡️해제유지"

def get_macd_state(last_macd, last_sig, prev_macd, prev_sig):
    if last_macd > last_sig and prev_macd <= prev_sig: return "🔥매수신호(골든크로스)"
    elif last_macd > last_sig: return "📈추세유지(상승중)"
    elif last_macd < last_sig and prev_macd >= prev_sig: return "📉하락주의(데드크로스)"
    return "⏳추세관망"

def get_fin_label_map():
    return {
        0: "해당없음 (ETF/ETN/레버리지)",
        1: "1점 (🚨F급/처분)",
        2: "2점 (⚠️불안정/주의)",
        3: "3점 (✅회복형/중간형)",
        4: "4점 (💎완성형 우량)"
    }

KNOWN_US_SP_ETFS = {"SPY", "VOO", "IVV", "SPLG", "SPYM", "VTI"}
KNOWN_US_NASDAQ_ETFS = {"QQQ", "QQQM", "QLD", "TQQQ"}
KNOWN_US_OTHER_ETFS = {
    "DIA", "IWM", "SCHD", "JEPI", "JEPQ", "SMH", "SOXX", "SOXL", "DRAM",
    "XLE", "XLF", "XLK", "XLC", "XLV", "XLI", "XLB", "XLY", "XLP", "XLU",
    "VNQ", "IBB", "ICLN", "SHLD", "PAVE", "ITA", "IGV", "URA", "IAU", "TLT",
    "IYW", "SSO", "UPRO", "SPXL", "SPXS", "SH", "SDS", "SQQQ", "QID", "PSQ",
    "TECL", "TECS", "SOXS", "LABU", "LABD", "TNA", "TZA", "FNGU", "FNGD",
    "NVDL", "NVDU", "NVDQ", "TSLL", "TSLQ",
}
KNOWN_KR_ETF_SYMBOLS = {
    "379810", "379800", "458730", "069500", "229200", "396500", "139260",
    "305540", "487240", "0117V0", "434730", "433500", "494670", "449450",
    "479850", "139250", "139270", "244580", "329200", "139220", "491010",
    "487230",
}

FIN_SCORE_EXEMPT_ASSET_CLASS_KEYWORDS = ("etf", "etn", "fund", "lever", "inverse", "인버스", "레버리지")
KR_ETF_NAME_KEYWORDS = (
    "ETF", "ETN", "KODEX", "TIGER", "ACE", "SOL", "RISE", "KBSTAR",
    "HANARO", "KOSEF", "ARIRANG", "TIMEFOLIO", "히어로즈", "액티브", "레버리지", "인버스"
)

KNOWN_TICKER_DISPLAY_NAMES = {
    "010120": "LS ELECTRIC",
    "267260": "HD현대일렉트릭",
    "298040": "효성중공업",
    "103590": "일진전기",
    "033100": "제룡전기",
    "001440": "대한전선",
    "006260": "LS",
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "200710": "에이디테크놀러지",
    "042700": "한미반도체",
    "403870": "HPSP",
    "039030": "이오테크닉스",
    "058470": "리노공업",
    "034020": "두산에너빌리티",
    "052690": "한전기술",
    "051600": "한전KPS",
    "329180": "HD현대중공업",
    "009540": "HD한국조선해양",
    "010140": "삼성중공업",
    "042660": "한화오션",
    "012450": "한화에어로스페이스",
    "047810": "한국항공우주",
    "064350": "현대로템",
    "079550": "LIG넥스원",
    "278470": "에이피알",
    "090430": "아모레퍼시픽",
    "161890": "한국콜마",
    "192820": "코스맥스",
    "373220": "LG에너지솔루션",
    "006400": "삼성SDI",
    "051910": "LG화학",
    "003670": "포스코퓨처엠",
    "247540": "에코프로비엠",
    "086520": "에코프로",
    "066970": "엘앤에프",
}


def is_ticker_like_text(value):
    text = sanitize_ticker_value(value)
    symbol = text.replace(".KS", "").replace(".KQ", "")
    return bool(symbol) and (
        symbol.isdigit()
        or text.endswith((".KS", ".KQ"))
        or (symbol.isascii() and symbol.replace(".", "").isalnum() and " " not in str(value or ""))
    )


def clean_symbol(ticker):
    return sanitize_ticker_value(ticker).replace(".KS", "").replace(".KQ", "")


def get_known_display_name(ticker, fallback=""):
    symbol = clean_symbol(ticker)
    return KNOWN_TICKER_DISPLAY_NAMES.get(symbol, str(fallback or sanitize_ticker_value(ticker)).strip())


def clean_resolved_display_name(value, ticker=""):
    text = html.unescape(str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*[-:|]\s*(Naver|NAVER|Yahoo Finance|네이버페이 증권|네이버 금융).*$", "", text, flags=re.I).strip()
    text = re.sub(r"\b(Co\.,?\s*Ltd\.?|Corporation|Corp\.?|Inc\.?|Limited|PLC|LLC)\b\.?", "", text, flags=re.I).strip(" -:|")
    if not text:
        return ""

    symbol = clean_symbol(ticker)
    if clean_symbol(text) == symbol:
        return ""
    return text


@st.cache_data(ttl=86400, show_spinner=False)
def lookup_naver_stock_name(symbol):
    symbol = clean_symbol(symbol)
    if not (symbol.isdigit() and len(symbol) == 6):
        return ""

    try:
        req = urllib.request.Request(
            f"https://finance.naver.com/item/main.naver?code={symbol}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        raw = urllib.request.urlopen(req, timeout=4).read()
        page = raw.decode("euc-kr", errors="ignore")
    except Exception:
        return ""

    patterns = [
        r"<title>\s*([^:<|]+?)\s*[:|]",
        r"<div[^>]*class=[\"']wrap_company[\"'][\s\S]*?<h2[^>]*>\s*<a[^>]*>(.*?)</a>",
        r"<h2[^>]*>\s*<a[^>]*>(.*?)</a>",
    ]
    for pattern in patterns:
        matched = re.search(pattern, page, flags=re.I)
        if not matched:
            continue
        name = re.sub(r"<[^>]+>", "", matched.group(1))
        name = clean_resolved_display_name(name, symbol)
        if name:
            return name
    return ""


@st.cache_data(ttl=86400, show_spinner=False)
def lookup_kr_etf_display_name(symbol):
    symbol = clean_symbol(symbol)
    if not (symbol.isdigit() and len(symbol) == 6):
        return ""

    try:
        df = load_kr_etf_lab_dataframe()
    except Exception:
        return ""

    if df is None or df.empty or "code" not in df.columns or "name" not in df.columns:
        return ""

    matched = df[df["code"].astype(str).str.zfill(6) == symbol]
    if matched.empty:
        return ""

    return clean_resolved_display_name(matched.iloc[0].get("name", ""), symbol)


@st.cache_data(ttl=86400, show_spinner=False)
def lookup_yfinance_info(ticker):
    ticker = sanitize_ticker_value(ticker)
    if not ticker:
        return {}

    try:
        info = yf.Ticker(ticker).get_info()
    except Exception:
        return {}

    if not isinstance(info, dict):
        return {}

    keys = ["shortName", "longName", "displayName", "quoteType", "sector", "industry"]
    return {key: info.get(key, "") for key in keys}


def lookup_yfinance_display_name(ticker):
    info = lookup_yfinance_info(ticker)
    if not info:
        return ""

    for field in ["shortName", "longName", "displayName", "quoteType"]:
        name = clean_resolved_display_name(info.get(field, ""), ticker)
        if name and name.upper() not in {"EQUITY", "ETF", "MUTUALFUND"}:
            return name
    return ""


def resolve_display_name_for_ticker(ticker, fallback=""):
    ticker_clean = sanitize_ticker_value(ticker)
    symbol = clean_symbol(ticker_clean)
    if not ticker_clean:
        return str(fallback or "").strip()

    known_name = KNOWN_TICKER_DISPLAY_NAMES.get(symbol, "")
    if known_name:
        return known_name

    if ticker_clean.endswith((".KS", ".KQ")) or (symbol.isdigit() and len(symbol) == 6):
        for resolver in [lookup_kr_etf_display_name, lookup_naver_stock_name]:
            name = resolver(symbol)
            if name:
                return name

    name = lookup_yfinance_display_name(ticker_clean)
    if name:
        return name

    fallback_name = strip_search_prefix(fallback).strip()
    if fallback_name and not (is_ticker_like_text(fallback_name) and clean_symbol(fallback_name) == symbol):
        return fallback_name

    return ticker_clean


def sanitize_asset_name(name, ticker=""):
    ticker_clean = sanitize_ticker_value(ticker)
    symbol = clean_symbol(ticker_clean)
    raw_name = str(name or "").strip()
    cleaned_name = strip_search_prefix(raw_name).strip()
    known_name = KNOWN_TICKER_DISPLAY_NAMES.get(symbol, "")

    if not cleaned_name or cleaned_name.startswith((":","：")):
        return resolve_display_name_for_ticker(ticker_clean, known_name or ticker_clean)

    if is_ticker_like_text(cleaned_name) and clean_symbol(cleaned_name) == symbol:
        return resolve_display_name_for_ticker(ticker_clean, known_name or ticker_clean)

    if known_name and clean_symbol(cleaned_name) == symbol:
        return known_name

    return cleaned_name

def is_kr_listed(ticker):
    return sanitize_ticker_value(ticker).endswith((".KS", ".KQ"))


def sanitize_watchlist_item(item):
    data = dict(item) if isinstance(item, dict) else {}
    ticker = sanitize_ticker_value(data.get("ticker", ""))
    return {
        **data,
        "ticker": ticker,
        "name": sanitize_asset_name(data.get("name", ""), ticker),
    }

def is_known_etf_ticker(ticker):
    raw = sanitize_ticker_value(ticker)
    symbol = clean_symbol(raw)
    return (
        symbol in KNOWN_US_SP_ETFS
        or symbol in KNOWN_US_NASDAQ_ETFS
        or symbol in KNOWN_US_OTHER_ETFS
        or symbol in KNOWN_KR_ETF_SYMBOLS
        or raw.endswith("ETF")
    )

def asset_class_marks_fin_score_exempt(asset_class):
    text = str(asset_class or "").strip().lower()
    return any(keyword in text for keyword in FIN_SCORE_EXEMPT_ASSET_CLASS_KEYWORDS)

def is_fin_score_exempt_asset(ticker, is_etf=False, asset_class="", name=""):
    if clean_bool(is_etf) or is_known_etf_ticker(ticker) or asset_class_marks_fin_score_exempt(asset_class):
        return True

    # 국내 ETF/ETN은 신규 상품이 많아 티커 목록만으로는 누락될 수 있다.
    # 이름에 ETF 브랜드/레버리지/인버스 단서가 있으면 재무점수 대상에서 제외한다.
    name_upper = str(name or "").strip().upper()
    if is_kr_listed(ticker) and any(keyword in name_upper for keyword in KR_ETF_NAME_KEYWORDS):
        return True

    return False

def infer_asset_class_for_ticker(ticker, current_asset_class=""):
    current = str(current_asset_class or "").strip()
    if not is_known_etf_ticker(ticker) and not asset_class_marks_fin_score_exempt(current):
        return current

    symbol = clean_symbol(ticker)
    if is_kr_listed(ticker):
        if symbol == "379810":
            return "us_etf_nasdaq"
        if symbol in {"379800", "458730"}:
            return "us_etf_sp"
        return current if asset_class_marks_fin_score_exempt(current) else "kr_etf"

    if symbol in KNOWN_US_SP_ETFS:
        return "us_etf_sp"
    if asset_class_marks_fin_score_exempt(current):
        return current
    return "us_etf_nasdaq"

def encode_watchlist(watchlist):
    raw = json.dumps(watchlist, ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

def decode_watchlist(value):
    try:
        raw = base64.urlsafe_b64decode(value.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception:
        return None

def load_watchlist_from_query():
    raw = st.query_params.get("wl", "")
    if not raw:
        return [sanitize_watchlist_item(x) for x in DEFAULT_WATCHLIST]
    loaded = decode_watchlist(raw)
    source = loaded if loaded else DEFAULT_WATCHLIST
    return [sanitize_watchlist_item(x) for x in source]

def sync_watchlist_to_query():
    desired = encode_watchlist(st.session_state.watchlist)
    current = st.query_params.get("wl", "")
    if current != desired:
        st.query_params["wl"] = desired

def is_in_watchlist(ticker):
    t_norm = normalize_ticker(ticker)
    for item in st.session_state.watchlist:
        if normalize_ticker(item["ticker"]) == t_norm:
            return True
    return False

def get_watchlist_item(ticker):
    t_norm = normalize_ticker(ticker)
    for item in st.session_state.watchlist:
        if normalize_ticker(item["ticker"]) == t_norm:
            return item
    return None

def build_ai_analysis_prompt(name, ticker, macro_res, final_macro_risk, c):
    macro_lines = []
    for k, v in macro_res.items():
        macro_lines.append(f"- {k}: {v['val']} ({v['icon']}, storm={v['storm']})")

    macro_text = "\n".join(macro_lines) if macro_lines else "- 거시 데이터 없음"

    return f"""
You are a top-tier macro strategist and technical analyst for public markets.
당신의 임무는 내가 입력한 **{name} ({ticker})**에 대해, 현시점에서 비중 확대를 위한 매수진입이 적정한지 여부를 판단하는 것이다.

반드시 아래 기준으로 분석하라.
• 거시경제 분석
• 현재 금리 방향성
• 인플레이션 흐름
• 경기 사이클
• 유동성 환경
• 달러 방향성
• 중앙은행 정책 스탠스
• 위 요소들이 {name}에 우호적인지, 중립인지, 비우호적인지 판단
• 기술적 분석
• 단기 / 중기 / 장기 추세
• 이동평균선 배열
• 주요 지지선 / 저항선
• 거래량 변화
• RSI, MACD 등 주요 모멘텀 지표
• 현재 구간이 돌파 매수, 눌림목 매수, 관망 구간 중 어디에 해당하는지 판단
• 종합 판단
• 거시경제와 기술적 분석을 통합해 현재 시점의 비중 확대 매수 적정성을 평가하라.
• 단순 낙관론이 아니라 손익비와 리스크까지 포함해 판단하라.
• 애매하면 “조건부 적정”으로 판정하고, 어떤 조건이 충족되어야 하는지 명확히 써라.

답변 형식은 반드시 아래 형식으로만 작성하라.
별점: ★{{별점}}
최종 판정: {{매수 적정 / 조건부 적정 / 관망 / 부적정}}
한줄 결론:
• {name}에 대한 현시점 비중 확대 매수 적정성을 1문장으로 요약
• 거시경제 분석
• 핵심 거시 변수 요약
• 현재 환경이 {name}에 미치는 영향
• 우호 / 중립 / 비우호 판단
• 기술적 분석
• 추세 판단
• 핵심 지지선 / 저항선
• 거래량 / RSI / MACD 해석
• 현재 진입 타점의 매력도 평가
• 종합 판단
• 왜 지금 매수진입이 적절한지 또는 부담스러운지 설명
• 비중 확대, 분할매수, 눌림목 대기, 관망 중 가장 합리적인 선택 제시
• 실행 전략
• 공격형 투자자 전략
• 중립형 투자자 전략
• 보수형 투자자 전략
• 리스크 요인
• 이 판단 무효화할 수 있는 변수 3가지 이상 제시
• 최종 한줄 판정

추가 규칙:
• 최신 기준으로 해석하되, 최신 데이터 확인이 불완전하면 그 한계를 먼저 명시하라.
• 확실한 것과 불확실한 것을 구분하라.
• 투자 권유가 아니라 분석 및 의사결정 보조 목적의 답변으로 작성하라.
• 개별 종목이면 실적, 밸류에이션, 섹터 모멘텀을 보조적으로 반영하라.
• 지수라면 정책, 유동성, 경기 방향성의 비중을 더 높게 반영하라.
• 반드시 한국어로 작성하라.

입력 데이터:
[거시환경]
매크로 리스크 점수: {final_macro_risk}
{macro_text}

[기술/전술 데이터]
종목명: {name}
티커: {ticker}
현재가: {c['cur_p']}
후보등급: {c['grade']}
최종판정: {c['dec']}
Adj 점수: {c['adj']}
RS 라벨: {c['rs_label']}
RSI: {c['rsi']}
MFI: {c['mfi']}
볼린저 %B: {c['pct_b']}
추세: {c['trend']}
MACD 상태: {c['macd']}
실시간 MACD: {c['rt_macd']}
SQZ: {c['sqz']}
외부구조: {c['ext_structure']}
내부구조: {c['int_structure']}
내부 이벤트: {c['int_event']}
외부 이벤트: {c['ext_event']}
유동성 상태: {c['liq_state']}
FVG 타입: {c['fvg_type']}
FVG active: {c['fvg_active']}
P/D Zone: {c['pd_zone']}
MA5: {c['ma5']}
MA20: {c['ma20']}
MA50: {c['ma50']}
MA120: {c['ma120']}
3개월 수익률: {c['ret_3m']}
6개월 수익률: {c['ret_6m']}
MDD: {c['dd']}
기술점수: {c['tech_total']}
재무점수: {c['fin_score']}
종합 해석: {c['smc_action']}
보조 해석: {c['smc_insight']}
""".strip()

def call_llm_analysis(prompt: str) -> str:
    return prompt

# -------------------------------------------------
# 2-1. Supabase persistent storage
# -------------------------------------------------
@st.cache_resource
def get_supabase_client():
    url = get_secret_value("SUPABASE_URL")
    key = get_secret_value("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY")

    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Streamlit Secrets.")

    return create_client(url, key)


def get_supabase():
    try:
        return get_supabase_client()
    except Exception as e:
        st.error(f"Supabase connection configuration error: {e}")
        st.stop()


supabase = get_supabase()


def run_supabase(query, action="Supabase operation", stop_on_error=True):
    try:
        return query.execute()
    except Exception as e:
        message = f"{action} failed: {e}"
        if stop_on_error:
            st.error(message)
            st.info("Check that Supabase tables were created and Streamlit Secrets are correct.")
            st.stop()
        warn_key = f"soft_supabase_error_{action}"
        if not st.session_state.get(warn_key, False):
            st.warning(f"{message} 저장은 건너뛰고 앱은 계속 실행합니다.")
            st.session_state[warn_key] = True
        return None


def init_db():
    res = run_supabase(
        supabase.table("settings").select("owner_email").eq("owner_email", CURRENT_USER_EMAIL),
        "load default settings row",
    )
    if not res.data:
        run_supabase(
            supabase.table("settings").insert({
                "owner_email": CURRENT_USER_EMAIL,
                "seed_money": 0,
                "krw_cash": 0,
                "usd_cash": 0,
                "usdkrw": 1400,
                "reserve_target_weight": 10,
            }),
            "create default settings row",
        )


def load_settings_db():
    res = run_supabase(
        supabase.table("settings").select("*").eq("owner_email", CURRENT_USER_EMAIL),
        "load settings",
    )

    if not res.data:
        return {
            "seed_money": 0.0,
            "krw_cash": 0.0,
            "usd_cash": 0.0,
            "usdkrw": 1400.0,
            "reserve_target_weight": 10.0,
        }

    row = res.data[0]
    return {
        "seed_money": clean_float(row.get("seed_money"), 0.0),
        "krw_cash": clean_float(row.get("krw_cash"), 0.0),
        "usd_cash": clean_float(row.get("usd_cash"), 0.0),
        "usdkrw": clean_float(row.get("usdkrw"), 1400.0),
        "reserve_target_weight": clean_float(row.get("reserve_target_weight"), 10.0),
    }


def save_settings_db(seed_money, krw_cash, usd_cash, usdkrw, reserve_target_weight=10.0):
    run_supabase(
        supabase.table("settings").upsert({
            "owner_email": CURRENT_USER_EMAIL,
            "seed_money": clean_float(seed_money),
            "krw_cash": clean_float(krw_cash),
            "usd_cash": clean_float(usd_cash),
            "usdkrw": clean_float(usdkrw, 1400.0),
            "reserve_target_weight": clean_float(reserve_target_weight, 10.0),
        }, on_conflict="owner_email"),
        "save settings",
    )


def load_holdings_db():
    res = run_supabase(
        supabase.table("holdings").select(",".join(HOLDINGS_COLUMNS)).eq("owner_email", CURRENT_USER_EMAIL),
        "load holdings",
    )
    df = dataframe_from_rows(res.data, HOLDINGS_COLUMNS)
    if not df.empty:
        df["ticker"] = df["ticker"].apply(sanitize_ticker_value)
        df["name"] = df.apply(lambda row: sanitize_asset_name(row.get("name", ""), row.get("ticker", "")), axis=1)
    return df


def save_holdings_db(df):
    rows = []
    for _, row in df.iterrows():
        ticker_value = sanitize_ticker_value(row.get("ticker", ""))
        if not ticker_value:
            continue

        name_value = sanitize_asset_name(row.get("name", ""), ticker_value)
        asset_class = str(row.get("asset_class", "")).strip()
        is_fin_exempt = is_fin_score_exempt_asset(
            ticker_value,
            row.get("is_etf", False),
            asset_class,
            name_value,
        )
        if is_fin_exempt:
            asset_class = infer_asset_class_for_ticker(ticker_value, asset_class)

        rows.append({
            "owner_email": CURRENT_USER_EMAIL,
            "ticker": ticker_value,
            "name": name_value,
            "qty": clean_float(row.get("qty")),
            "avg_price": clean_float(row.get("avg_price")),
            "target_weight": clean_float(row.get("target_weight")),
            "asset_class": asset_class,
            "is_etf": is_fin_exempt,
            "bucket": infer_bucket(ticker_value, row.get("bucket", "core")),
        })

    if not rows:
        st.warning("No holdings rows to save. Existing holdings were kept unchanged.")
        return False

    run_supabase(
        supabase.table("holdings").delete().eq("owner_email", CURRENT_USER_EMAIL),
        "delete existing holdings",
    )
    run_supabase(supabase.table("holdings").insert(rows), "save holdings")
    return True


def load_dividends_db():
    res = run_supabase(
        supabase.table("dividends").select(",".join(DIVIDENDS_COLUMNS)).eq("owner_email", CURRENT_USER_EMAIL),
        "load dividends",
    )
    rows = sorted(res.data or [], key=lambda r: (str(r.get("date") or ""), int(r.get("id") or 0)), reverse=True)
    return dataframe_from_rows(rows, DIVIDENDS_COLUMNS)


def save_dividends_db(df):
    rows = []
    for _, row in df.iterrows():
        if not str(row.get("date", "")).strip() and not str(row.get("ticker", "")).strip():
            continue
        rows.append({
            "owner_email": CURRENT_USER_EMAIL,
            "date": str(row.get("date", "")).strip(),
            "ticker": sanitize_ticker_value(row.get("ticker", "")),
            "amount": clean_float(row.get("amount")),
            "currency": str(row.get("currency", "KRW")).strip().upper() or "KRW",
        })

    if not rows:
        st.warning("No dividend rows to save. Existing dividends were kept unchanged.")
        return False

    run_supabase(
        supabase.table("dividends").delete().eq("owner_email", CURRENT_USER_EMAIL),
        "delete existing dividends",
    )
    run_supabase(supabase.table("dividends").insert(rows), "save dividends")
    return True


def load_monthly_logs_db():
    res = run_supabase(
        supabase.table("monthly_logs").select(",".join(MONTHLY_LOG_COLUMNS)).eq("owner_email", CURRENT_USER_EMAIL),
        "load monthly logs",
    )
    rows = sorted(res.data or [], key=lambda r: str(r.get("month") or ""))
    return dataframe_from_rows(rows, MONTHLY_LOG_COLUMNS)


def save_monthly_logs_db(df):
    rows = []
    for _, row in df.iterrows():
        month = str(row.get("month", "")).strip()
        if not month:
            continue
        rows.append({
            "owner_email": CURRENT_USER_EMAIL,
            "month": month,
            "total_invested": clean_float(row.get("total_invested")),
            "evaluated_value": clean_float(row.get("evaluated_value")),
            "dividend": clean_float(row.get("dividend")),
        })

    if not rows:
        st.warning("No monthly log rows to save. Existing monthly logs were kept unchanged.")
        return False

    run_supabase(
        supabase.table("monthly_logs").delete().eq("owner_email", CURRENT_USER_EMAIL),
        "delete existing monthly logs",
    )
    run_supabase(supabase.table("monthly_logs").insert(rows), "save monthly logs")
    return True


def load_fin_scores_db():
    res = run_supabase(
        supabase.table("fin_scores").select(",".join(FIN_SCORE_COLUMNS)).eq("owner_email", CURRENT_USER_EMAIL),
        "load financial scores",
    )
    return dataframe_from_rows(res.data, FIN_SCORE_COLUMNS)


def load_watchlist_db():
    res = run_supabase(
        supabase.table("watchlist").select("name,ticker,is_etf,asset_class,sort_order,fin_score").eq("owner_email", CURRENT_USER_EMAIL),
        "load watchlist",
    )

    rows = sorted(res.data or [], key=lambda r: (int(r.get("sort_order") or 0), str(r.get("name") or "")))
    items = []
    for row in rows:
        ticker = sanitize_ticker_value(row.get("ticker", ""))
        name = sanitize_asset_name(row.get("name", ""), ticker)
        asset_class = str(row.get("asset_class", "")).strip()
        is_fin_exempt = is_fin_score_exempt_asset(ticker, row.get("is_etf", False), asset_class, name)
        if is_fin_exempt:
            asset_class = infer_asset_class_for_ticker(ticker, asset_class)

        items.append({
            "name": name,
            "ticker": ticker,
            "is_etf": is_fin_exempt,
            "asset_class": asset_class,
            "fin_score": 0 if is_fin_exempt else clean_int(row.get("fin_score")),
        })
    return [x for x in items if x["ticker"]]


def save_watchlist_db(watchlist):
    rows = []
    for idx, item in enumerate(watchlist):
        item = sanitize_watchlist_item(item)
        ticker = item.get("ticker", "")
        if not ticker:
            continue

        name = item.get("name", "")
        asset_class = str(item.get("asset_class", "")).strip()
        is_fin_exempt = is_fin_score_exempt_asset(ticker, item.get("is_etf", False), asset_class, name)
        if is_fin_exempt:
            asset_class = infer_asset_class_for_ticker(ticker, asset_class)

        rows.append({
            "owner_email": CURRENT_USER_EMAIL,
            "ticker": ticker,
            "name": name,
            "is_etf": is_fin_exempt,
            "asset_class": asset_class,
            "sort_order": idx,
            "fin_score": 0 if is_fin_exempt else clean_int(item.get("fin_score")),
        })

    if not rows:
        st.warning("No watchlist rows to save. Existing watchlist was kept unchanged.")
        return False

    run_supabase(
        supabase.table("watchlist").delete().eq("owner_email", CURRENT_USER_EMAIL),
        "delete existing watchlist",
    )
    run_supabase(supabase.table("watchlist").insert(rows), "save watchlist")
    return True


def load_watchlist_persistent():
    db_items = load_watchlist_db()
    if db_items:
        return db_items

    query_items = load_watchlist_from_query()
    save_watchlist_db(query_items)
    return query_items


def persist_watchlist():
    save_watchlist_db(st.session_state.watchlist)


def get_swing_radar_create_sql():
    return """
create table if not exists swing_radar (
  owner_email text not null,
  ticker text not null,
  name text,
  asset_class text default '',
  idea text default '',
  check_1 text default '',
  check_2 text default '',
  check_3 text default '',
  risk_1 text default '',
  risk_2 text default '',
  risk_3 text default '',
  entry_rule text default '',
  exit_rule text default '',
  next_event text default '',
  status text default '대기',
  decision text default '관망',
  importance text default '중',
  reference_link text default '',
  last_checked text default '',
  memo text default '',
  primary key (owner_email, ticker)
);
""".strip()


def load_swing_radar_db_safe():
    try:
        res = supabase.table("swing_radar").select(",".join(SWING_RADAR_COLUMNS)).eq("owner_email", CURRENT_USER_EMAIL).execute()
        return dataframe_from_rows(res.data, SWING_RADAR_COLUMNS), None
    except Exception as e:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS), str(e)


def save_swing_radar_db_safe(df):
    try:
        rows = []
        for _, row in df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue

            item = {"owner_email": CURRENT_USER_EMAIL, "ticker": ticker}
            for col in SWING_RADAR_COLUMNS:
                if col == "ticker":
                    continue
                value = row.get(col, "")
                item[col] = "" if value is None or pd.isna(value) else str(value).strip()
            rows.append(item)

        if not rows:
            return False, "저장할 스윙 레이더 행이 없습니다."

        supabase.table("swing_radar").delete().eq("owner_email", CURRENT_USER_EMAIL).execute()
        supabase.table("swing_radar").insert(rows).execute()
        return True, ""
    except Exception as e:
        return False, str(e)


FEEDBACK_COLUMNS = [
    "id",
    "owner_email",
    "category",
    "title",
    "body",
    "priority",
    "status",
    "created_at",
]


def get_feedback_create_sql():
    return """
create table if not exists feedback (
  id bigint generated by default as identity primary key,
  owner_email text not null,
  category text not null default '개선 제안',
  title text not null default '',
  body text not null default '',
  priority text not null default '보통',
  status text not null default '접수',
  created_at timestamptz not null default now()
);

create index if not exists feedback_owner_email_idx on feedback(owner_email);
create index if not exists feedback_created_at_idx on feedback(created_at desc);
""".strip()


def is_admin_user():
    return normalize_text(CURRENT_USER_EMAIL) in get_secret_emails("ADMIN_EMAILS")


def load_feedback_db_safe(limit=200):
    try:
        query = supabase.table("feedback").select(",".join(FEEDBACK_COLUMNS))
        if not is_admin_user():
            query = query.eq("owner_email", CURRENT_USER_EMAIL)
        res = query.order("created_at", desc=True).limit(int(limit)).execute()
        return dataframe_from_rows(res.data, FEEDBACK_COLUMNS), None
    except Exception as e:
        return dataframe_from_rows([], FEEDBACK_COLUMNS), str(e)


def save_feedback_db_safe(category, title, body, priority):
    try:
        payload = {
            "owner_email": CURRENT_USER_EMAIL,
            "category": str(category or "개선 제안").strip(),
            "title": str(title or "").strip(),
            "body": str(body or "").strip(),
            "priority": str(priority or "보통").strip(),
            "status": "접수",
        }
        supabase.table("feedback").insert(payload).execute()
        return True, ""
    except Exception as e:
        return False, str(e)


def build_recovery_preflight_report(frames, unknown_files=None, read_errors=None):
    frames = frames or {}
    unknown_files = unknown_files or []
    read_errors = read_errors or []
    summary_rows = []
    issues = []

    for error in read_errors:
        add_recovery_issue(issues, "차단", "파일 읽기", "", error, "파일 형식이나 인코딩을 확인한 뒤 다시 업로드하세요.")

    for filename in unknown_files:
        add_recovery_issue(issues, "주의", "미인식 파일", filename, "복구 가능한 CSV 구조로 인식하지 못했습니다.", "파일명이 아니라 컬럼 구조로 판별합니다. 필요한 컬럼이 있는지 확인하세요.")

    if not frames:
        add_recovery_issue(issues, "차단", "업로드", "", "복구 가능한 데이터를 찾지 못했습니다.", "Stock Lab 백업 ZIP 또는 인식 가능한 CSV를 업로드하세요.")

    for kind, df in frames.items():
        info = RECOVERY_KIND_INFO.get(kind, {})
        label = info.get("label", kind)
        key_columns = info.get("key_columns", [])
        required = info.get("required", [])
        valid_rows = count_valid_rows(df, key_columns)

        summary_rows.append({
            "데이터": label,
            "행수": len(df),
            "유효행": valid_rows,
            "복구 방식": info.get("restore_mode", "복구"),
        })

        missing_cols = [col for col in required if col not in df.columns]
        if missing_cols:
            add_recovery_issue(issues, "차단", label, "", f"필수 컬럼이 없습니다: {', '.join(missing_cols)}", "백업 파일 컬럼을 확인하세요.")

        if df.empty or valid_rows == 0:
            add_recovery_issue(issues, "주의", label, "", "유효한 행이 없습니다.", "이 데이터는 복구해도 반영되지 않을 수 있습니다.")

        unique_column = info.get("unique_column")
        if unique_column:
            for value, count in get_duplicate_recovery_values(df, unique_column):
                add_recovery_issue(issues, "차단", label, value, f"중복 키가 {count}번 들어 있습니다.", "중복 행을 하나로 합친 뒤 복구하세요.")

        if kind == "settings" and len(df) > 1:
            add_recovery_issue(issues, "참고", label, "", "설정 행이 여러 개입니다.", "복구 시 마지막 행을 기준으로 저장합니다.")

        if kind == "holdings":
            for idx, row in df.fillna("").iterrows():
                ticker = str(row.get("ticker", "")).strip()
                name = str(row.get("name", "")).strip()
                if not ticker:
                    add_recovery_issue(issues, "주의", label, f"row {idx + 1}", "티커가 비어 있어 복구 시 건너뜁니다.", "필요한 행이면 티커를 입력하세요.")
                    continue

                qty = clean_float(row.get("qty"), 0.0)
                avg_price = clean_float(row.get("avg_price"), 0.0)
                target_weight = clean_float(row.get("target_weight"), 0.0)
                asset_class = str(row.get("asset_class", "")).strip()
                saved_is_etf = clean_bool(row.get("is_etf", False))
                if qty < 0:
                    add_recovery_issue(issues, "주의", label, ticker, "보유량이 음수입니다.", "수량을 확인하세요.")
                if avg_price < 0:
                    add_recovery_issue(issues, "주의", label, ticker, "매입가가 음수입니다.", "평균 매입가를 확인하세요.")
                if target_weight < 0 or target_weight > 100:
                    add_recovery_issue(issues, "주의", label, ticker, "목표비중이 0~100 범위를 벗어났습니다.", "목표비중을 확인하세요.")
                if is_fin_score_exempt_asset(ticker, saved_is_etf, asset_class, name) and not saved_is_etf:
                    add_recovery_issue(issues, "참고", label, ticker, "ETF/ETN/레버리지로 보이지만 ETF 체크가 꺼져 있습니다.", "복구 후 ETF/ETN/레버리지 분류를 확인하세요.")

        if kind == "watchlist":
            for idx, row in df.fillna("").iterrows():
                ticker = str(row.get("ticker", "")).strip()
                if not ticker:
                    add_recovery_issue(issues, "주의", label, f"row {idx + 1}", "티커가 비어 있어 복구 시 건너뜁니다.", "필요한 행이면 티커를 입력하세요.")

        if kind == "monthly_logs":
            for idx, row in df.fillna("").iterrows():
                month = str(row.get("month", "")).strip()
                if not month:
                    add_recovery_issue(issues, "주의", label, f"row {idx + 1}", "월 값이 비어 있어 복구 시 건너뜁니다.", "YYYY-MM 형식으로 입력하세요.")
                    continue
                if pd.isna(pd.to_datetime(month, errors="coerce")):
                    add_recovery_issue(issues, "주의", label, month, "월 형식을 날짜로 읽지 못했습니다.", "YYYY-MM 형식으로 입력하세요.")

        if kind == "dividends":
            for idx, row in df.fillna("").iterrows():
                ticker = str(row.get("ticker", "")).strip()
                date_text = str(row.get("date", "")).strip()
                if not ticker and not date_text:
                    add_recovery_issue(issues, "주의", label, f"row {idx + 1}", "티커와 날짜가 모두 비어 있어 복구 시 건너뜁니다.", "필요한 행이면 티커와 날짜를 입력하세요.")
                    continue
                if date_text and pd.isna(pd.to_datetime(date_text, errors="coerce")):
                    add_recovery_issue(issues, "주의", label, ticker, "배당일 형식을 날짜로 읽지 못했습니다.", "YYYY-MM-DD 형식으로 입력하세요.")
                if clean_float(row.get("amount"), 0.0) < 0:
                    add_recovery_issue(issues, "주의", label, ticker, "배당금이 음수입니다.", "정정 목적이 아니라면 금액을 확인하세요.")

    summary_df = pd.DataFrame(summary_rows, columns=["데이터", "행수", "유효행", "복구 방식"])
    issue_df = pd.DataFrame(issues, columns=["등급", "데이터", "대상", "문제", "확인/조치"])
    if issue_df.empty:
        return summary_df, issue_df

    severity_order = {"차단": 0, "주의": 1, "참고": 2}
    issue_df["_order"] = issue_df["등급"].map(severity_order).fillna(9)
    issue_df = issue_df.sort_values(["_order", "데이터", "대상"]).drop(columns="_order").reset_index(drop=True)
    return summary_df, issue_df


def has_recovery_blockers(issue_df):
    return issue_df is not None and not issue_df.empty and bool((issue_df["등급"] == "차단").any())


def parse_fin_score_notes_for_restore(value):
    try:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return {}
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {"messages": parsed}
    except Exception:
        return {"messages": [str(value)]}


def restore_from_uploaded_csvs(uploaded_files):
    frames, unknown_files, read_errors, _ = collect_recovery_frames(uploaded_files)
    _, issue_df = build_recovery_preflight_report(frames, unknown_files, read_errors)
    if has_recovery_blockers(issue_df):
        return [], unknown_files + ["복구 차단: 사전 점검의 차단 항목을 먼저 해결하세요."]

    restored = []

    if "settings" in frames and not frames["settings"].empty:
        settings_row = frames["settings"].iloc[-1]
        save_settings_db(
            settings_row.get("seed_money", 0.0),
            settings_row.get("krw_cash", 0.0),
            settings_row.get("usd_cash", 0.0),
            settings_row.get("usdkrw", 1400.0),
            settings_row.get("reserve_target_weight", 10.0),
        )
        restored.append("settings")

    if "dashboard" in frames:
        dash = frames["dashboard"].copy()
        current_settings = load_settings_db()

        seed_money = current_settings.get("seed_money", 0.0)
        krw_cash = current_settings.get("krw_cash", 0.0)
        usd_cash = current_settings.get("usd_cash", 0.0)
        usdkrw = current_settings.get("usdkrw", 1400.0)
        reserve_target_weight = current_settings.get("reserve_target_weight", 10.0)

        if "monthly_logs" in frames and not frames["monthly_logs"].empty:
            latest_month = frames["monthly_logs"].sort_values("month").iloc[-1]
            seed_money = clean_float(latest_month.get("total_invested"), seed_money)

        krw_rows = dash[dash["티커"].astype(str).str.upper() == "KRW_CASH"]
        if not krw_rows.empty:
            krw_cash = clean_float(krw_rows.iloc[0].get("원화환산"), krw_cash)

        usd_rows = dash[dash["티커"].astype(str).str.upper() == "USD_CASH"]
        if not usd_rows.empty:
            usd_cash = clean_float(usd_rows.iloc[0].get("보유량"), usd_cash)
            usdkrw = clean_float(usd_rows.iloc[0].get("매입가"), usdkrw)

        save_settings_db(seed_money, krw_cash, usd_cash, usdkrw, reserve_target_weight)
        restored.append("settings/cash")

    if "holdings" in frames:
        holdings = frames["holdings"].copy()
        if save_holdings_db(holdings.fillna("")):
            restored.append(f"holdings {len(holdings)} rows")

    if "dividends" in frames:
        dividends = frames["dividends"].copy()
        dividends = dividends.fillna("")
        dividends = dividends[
            dividends["date"].astype(str).str.strip().ne("") |
            dividends["ticker"].astype(str).str.strip().ne("")
        ]
        if save_dividends_db(dividends):
            restored.append(f"dividends {len(dividends)} rows")

    if "monthly_logs" in frames:
        monthly_logs = frames["monthly_logs"].copy()
        if save_monthly_logs_db(monthly_logs.fillna("")):
            restored.append(f"monthly_logs {len(monthly_logs)} rows")

    if "watchlist" in frames:
        watchlist_rows = []
        for _, row in frames["watchlist"].fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            watchlist_rows.append({
                "name": str(row.get("name", "")).strip(),
                "ticker": ticker,
                "is_etf": clean_bool(row.get("is_etf", False)),
                "asset_class": str(row.get("asset_class", "")).strip(),
                "fin_score": clean_int(row.get("fin_score")),
            })
        if watchlist_rows and save_watchlist_db(watchlist_rows):
            st.session_state.watchlist = watchlist_rows
            restored.append(f"watchlist {len(watchlist_rows)} rows")

    if "fin_scores" in frames:
        restored_fin_scores = 0
        for _, row in frames["fin_scores"].fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            upsert_fin_score_db(
                ticker=ticker,
                auto_score=clean_int(row.get("auto_score")),
                manual_score=clean_int(row.get("manual_score")),
                final_score=clean_int(row.get("final_score")),
                source=str(row.get("source", "restore") or "restore"),
                notes=parse_fin_score_notes_for_restore(row.get("notes_json")),
            )
            restored_fin_scores += 1
        if restored_fin_scores:
            restored.append(f"fin_scores {restored_fin_scores} rows")

    if "swing_radar" in frames:
        ok, message = save_swing_radar_db_safe(frames["swing_radar"].fillna(""))
        if ok:
            restored.append(f"swing_radar {len(frames['swing_radar'])} rows")
        else:
            unknown_files.append(f"swing_radar restore failed: {message}")

    return restored, unknown_files


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) or np.isinf(obj) else float(obj)
    if isinstance(obj, float):
        return None if np.isnan(obj) or np.isinf(obj) else obj
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    return obj


def upsert_fin_score_db(ticker, auto_score, manual_score, final_score, source, notes, stop_on_error=False):
    res = run_supabase(
        supabase.table("fin_scores").upsert({
            "owner_email": CURRENT_USER_EMAIL,
            "ticker": normalize_ticker(ticker),
            "auto_score": clean_int(auto_score),
            "manual_score": clean_int(manual_score),
            "final_score": clean_int(final_score),
            "source": str(source),
            "notes_json": json.dumps(to_jsonable(notes), ensure_ascii=False),
        }, on_conflict="owner_email,ticker"),
        "save financial score",
        stop_on_error=stop_on_error,
    )
    return res is not None


def mark_fin_score_not_applicable_db(ticker, reason="ETF/ETN/레버리지 상품"):
    return upsert_fin_score_db(
        ticker=ticker,
        auto_score=0,
        manual_score=None,
        final_score=0,
        source="not_applicable",
        notes={
            "mode": "not_applicable",
            "messages": [f"{reason}: 재무점수 해당없음", "기존 수동 재무점수는 적용하지 않습니다."],
            "annual_judgements": {},
            "quarter_judgements": {},
            "weighted_scores": {},
        },
        stop_on_error=False,
    )


def delete_manual_fin_score_db(ticker):
    key = normalize_ticker(ticker)
    fin_scores_df = load_fin_scores_db()
    matched = fin_scores_df[fin_scores_df["ticker"] == key]

    if matched.empty:
        return

    row = matched.iloc[0]
    run_supabase(
        supabase.table("fin_scores").upsert({
            "owner_email": CURRENT_USER_EMAIL,
            "ticker": key,
            "auto_score": clean_int(row.get("auto_score")),
            "manual_score": None,
            "final_score": clean_int(row.get("auto_score")),
            "source": str(row.get("source") or "saved"),
            "notes_json": str(row.get("notes_json") or "{}"),
        }, on_conflict="owner_email,ticker"),
        "reset manual financial score",
    )


init_db()

# -------------------------------------------------
# 2-2. 자동 재무제표 로드 + 구글시트식 판정 점수화
# -------------------------------------------------
ORDER_BASED_TICKERS = {
    "012450",
    "329180",
}

DART_REPORT_LABELS = {
    "11011": "사업보고서",
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
}

DART_QUARTER_NO_BY_REPORT = {
    "11013": 1,  # 1분기 누적
    "11012": 2,  # 반기 누적
    "11014": 3,  # 3분기 누적
    "11011": 4,  # 연간 누적
}

DART_CUMULATIVE_FLOW_FIELDS = ["revenue", "op_income", "net_income", "ocf"]

FIN_S_KEYS = [
    "annual_3y_revenue_uptrend",
    "annual_op_income_uptrend",
    "annual_recent_high_growth",
    "annual_profitability_good",
    "annual_ocf_strength",
    "quarter_revenue_momentum",
    "quarter_profit_momentum",
    "quarter_cashflow_quality",
]

FIN_A_KEYS = [
    "annual_recent_revenue_growth",
    "annual_net_income_positive",
    "annual_cash_increase",
    "annual_cash_buffer",
    "annual_equity_growth",
    "annual_debt_stability",
    "quarter_revenue_increase",
    "quarter_profit_increase",
    "quarter_ocf_positive",
    "quarter_margin_good",
    "quarter_debt_stability",
    "quarter_equity_maintained",
]

FIN_B_KEYS = [
    "annual_average_scale_maintained",
    "annual_growth_slowdown",
    "annual_scale_loss",
    "annual_body_decline",
    "annual_margin_quality",
    "annual_roe_quality",
    "annual_debt_ratio_quality",
    "annual_hard_risk",
    "quarter_revenue_quality",
    "quarter_profit_quality",
    "quarter_cash_quality",
    "quarter_margin_quality",
    "quarter_debt_ratio_quality",
    "quarter_warning",
]

FIN_DATA_TTL_SECONDS = 21600

AUTO_FIN_FAIL_SCORE = 3
UNCALCULATED_FIN_DEFAULT_SCORE = 3

KR_MARKET_BENCHMARK = "069500.KS"
KR_US_NASDAQ_BENCHMARK = "379810.KS"
KR_US_SP_BENCHMARK = "379800.KS"
US_TECH_BENCHMARK = "QQQM"
US_BROAD_BENCHMARK = "SPY"
RS_LOOKBACK_DAYS = 20

US_TECH_OR_GROWTH_TICKERS = {
    "MSFT", "AAPL", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "AMD", "AVGO", "MU", "MRVL", "ANET", "CIEN", "VRT", "TSM",
    "NBIS", "SNDK", "ADBE", "CRM", "ORCL", "NOW", "SNOW", "PLTR",
    "ASML", "LRCX", "KLAC", "AMAT", "INTC", "QCOM", "ARM", "SMCI",
    "LITE"
}

def get_dart_api_key():
    return str(st.secrets.get("dart_api_key", "")).strip()

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_dart_corp_code_map():
    api_key = get_dart_api_key()
    if not api_key:
        return {}

    url = "https://opendart.fss.or.kr/api/corpCode.xml"

    res = requests.get(url, params={"crtfc_key": api_key}, timeout=15)
    res.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    xml_name = zf.namelist()[0]
    root = ET.fromstring(zf.read(xml_name))

    code_map = {}
    for item in root.findall("list"):
        corp_code = (item.findtext("corp_code") or "").strip()
        stock_code = (item.findtext("stock_code") or "").strip()

        if corp_code and stock_code:
            code_map[stock_code] = corp_code

    return code_map

def get_dart_corp_code(stock_code):
    stock_code = normalize_stock_code(stock_code)
    code_map = fetch_dart_corp_code_map()
    return code_map.get(stock_code)

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_dart_finstate_all_raw(stock_code, fiscal_year, report_code):
    api_key = get_dart_api_key()
    if not api_key:
        raise RuntimeError("DART API 키 없음")

    corp_code = get_dart_corp_code(stock_code)
    if not corp_code:
        raise RuntimeError(f"DART corp_code 매핑 실패: {stock_code}")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    last_message = ""

    for fs_div in ["CFS", "OFS"]:
        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(fiscal_year),
            "reprt_code": report_code,
            "fs_div": fs_div,
        }

        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()

        data = res.json()
        status = str(data.get("status", ""))
        message = data.get("message", "")
        last_message = message

        if status == "000" and data.get("list"):
            df = pd.DataFrame(data["list"])
            df["fs_div"] = fs_div
            return df

    return pd.DataFrame()

def is_order_based_ticker(ticker: str) -> bool:
    return normalize_ticker(ticker) in ORDER_BASED_TICKERS

def safe_float(x, default=np.nan):
    try:
        if x is None or pd.isna(x):
            return default
        s = str(x).strip()
        if s in ["", "-", "nan", "None"]:
            return default
        s = (
            s.replace(",", "")
            .replace("%", "")
            .replace("₩", "")
            .replace("$", "")
            .replace("−", "-")
        )
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return float(s)
    except Exception:
        return default

def finite_num(x):
    return x is not None and not pd.isna(x) and np.isfinite(float(x))

def pct_change(new, old):
    if not finite_num(new) or not finite_num(old) or float(old) == 0:
        return np.nan
    return (float(new) - float(old)) / abs(float(old)) * 100

def calc_ratio(numer, denom, multiplier=100):
    if not finite_num(numer) or not finite_num(denom) or float(denom) == 0:
        return np.nan
    return float(numer) / float(denom) * multiplier

def fmt_num(v):
    if not finite_num(v):
        return "-"
    v = float(v)
    if abs(v) >= 1_000_000_000_000:
        return f"{v / 1_000_000_000_000:.2f}조"
    if abs(v) >= 100_000_000:
        return f"{v / 100_000_000:.1f}억"
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}백만"
    return f"{v:,.0f}"

def fmt_pct(v):
    if not finite_num(v):
        return "-"
    return f"{float(v):.1f}%"

def normalize_stock_code(ticker: str) -> str:
    t = str(ticker).strip().upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return t.split(".")[0]
    return t

def pick_account_amount(df, keywords, amount_cols=None, exclude_keywords=None):
    if df is None or df.empty:
        return np.nan

    amount_cols = amount_cols or [
        "thstrm_amount", "thstrmAmount",
        "thstrm_add_amount", "thstrmAddAmount",
        "frmtrm_amount", "frmtrmAmount",
    ]
    exclude_keywords = exclude_keywords or []

    work = df.copy()

    if "fs_div" in work.columns and (work["fs_div"].astype(str) == "CFS").any():
        work = work[work["fs_div"].astype(str) == "CFS"]

    name_cols = [c for c in ["account_nm", "accountNm", "account_id", "accountId"] if c in work.columns]
    if not name_cols:
        return np.nan

    for kw in keywords:
        kw_norm = str(kw).replace(" ", "")
        for name_col in name_cols:
            names = work[name_col].astype(str).str.replace(" ", "", regex=False)
            mask = names.str.contains(kw_norm, case=False, na=False, regex=False)

            for ex in exclude_keywords:
                ex_norm = str(ex).replace(" ", "")
                mask = mask & ~names.str.contains(ex_norm, case=False, na=False, regex=False)

            matched = work[mask]
            if matched.empty:
                continue

            for amount_col in amount_cols:
                if amount_col in matched.columns:
                    vals = matched[amount_col].apply(safe_float).dropna()
                    if not vals.empty:
                        return float(vals.iloc[0])

    return np.nan

def enrich_fin_record(record):
    record = dict(record)
    revenue = record.get("revenue", np.nan)
    op_income = record.get("op_income", np.nan)
    net_income = record.get("net_income", np.nan)
    ocf = record.get("ocf", np.nan)
    equity = record.get("equity", np.nan)
    liabilities = record.get("liabilities", np.nan)

    record["op_margin"] = calc_ratio(op_income, revenue)
    record["net_margin"] = calc_ratio(net_income, revenue)
    record["roe"] = calc_ratio(net_income, equity)
    record["debt_ratio"] = calc_ratio(liabilities, equity)
    record["ocf_margin"] = calc_ratio(ocf, revenue)
    return record

def dart_flow_amount_cols(report_code):
    if report_code == "11011":
        return ["thstrm_amount", "thstrmAmount", "thstrm_add_amount", "thstrmAddAmount"]
    return ["thstrm_add_amount", "thstrmAddAmount", "thstrm_amount", "thstrmAmount"]

def dart_point_amount_cols():
    return ["thstrm_amount", "thstrmAmount"]

def extract_dart_metrics(df, fiscal_year, report_code):
    quarter_no = DART_QUARTER_NO_BY_REPORT.get(report_code)
    flow_cols = dart_flow_amount_cols(report_code)
    point_cols = dart_point_amount_cols()
    
    record = {
        "period": "annual" if report_code == "11011" else "quarter_cumulative",
        "fiscal_year": str(fiscal_year),
        "fiscal_quarter": quarter_no,
        "report_code": report_code,
        "report_label": DART_REPORT_LABELS.get(report_code, report_code),
        "date": f"{fiscal_year}-{report_code}",
        "is_cumulative_ytd": True,
        "revenue": pick_account_amount(
            df,
            ["매출액", "수익(매출액)", "영업수익"],
            amount_cols=flow_cols,
            exclude_keywords=["매출원가", "매출채권", "판매비", "관리비"]
        ),
        "op_income": pick_account_amount(df, ["영업이익", "영업이익손실"], amount_cols=flow_cols),
        "net_income": pick_account_amount(df, ["당기순이익", "연결당기순이익", "분기순이익", "반기순이익"], amount_cols=flow_cols),
        "ocf": pick_account_amount(df, ["영업활동현금흐름", "영업활동으로인한현금흐름", "영업에서창출된현금"], amount_cols=flow_cols),
        "equity": pick_account_amount(df, ["자본총계"], amount_cols=point_cols),
        "liabilities": pick_account_amount(df, ["부채총계"], amount_cols=point_cols),
        "assets": pick_account_amount(df, ["자산총계"], amount_cols=point_cols),
        "cash": pick_account_amount(df, ["현금및현금성자산", "현금및현금등가물"], amount_cols=point_cols),
    }
    return enrich_fin_record(record)

def has_dart_core_values(record):
    return any(
        finite_num(record.get(k))
        for k in ["revenue", "op_income", "net_income", "ocf"]
    )

def make_dart_single_quarter_record(current_cum, previous_cum=None, fiscal_quarter=None):
    rec = dict(current_cum)
    q_no = fiscal_quarter or DART_QUARTER_NO_BY_REPORT.get(str(current_cum.get("report_code")))

    rec["source_report_code"] = current_cum.get("report_code")
    rec["source_report_label"] = current_cum.get("report_label")
    rec["period"] = "quarter"
    rec["fiscal_quarter"] = q_no
    rec["report_code"] = f"Q{q_no}"
    rec["report_label"] = f"{q_no}분기(단일)"
    rec["date"] = f"{rec.get('fiscal_year')}-Q{q_no}"
    rec["is_cumulative_ytd"] = False
    rec["is_single_quarter"] = True
    rec["single_quarter_adjusted"] = False

    if q_no == 1:
        rec["single_quarter_adjusted"] = True
        rec["conversion_note"] = "1분기 누적값은 단일 분기값과 동일"
    elif previous_cum is not None and str(previous_cum.get("fiscal_year")) == str(current_cum.get("fiscal_year")):
        for field in DART_CUMULATIVE_FLOW_FIELDS:
            cur_val = current_cum.get(field)
            prev_val = previous_cum.get(field)
            if finite_num(cur_val) and finite_num(prev_val):
                rec[field] = float(cur_val) - float(prev_val)
            else:
                rec[field] = np.nan

        rec["single_quarter_adjusted"] = True
        rec["conversion_note"] = (
            f"{current_cum.get('report_label')} 누적값 - "
            f"{previous_cum.get('report_label')} 누적값으로 단일 분기 보정"
        )
    else:
        rec["conversion_note"] = "직전 누적 보고서가 없어 원본 누적값 사용"

    return enrich_fin_record(rec)

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_kr_financials_auto(ticker: str):
    stock_code = normalize_stock_code(ticker)
    current_year = pd.Timestamp.today().year
    annual_records = []

    try:
        for year in range(current_year, current_year - 7, -1):
            if len(annual_records) >= 3:
                break
            try:
                fs = fetch_dart_finstate_all_raw(stock_code, year, "11011")
                if fs is not None and not fs.empty:
                    rec = extract_dart_metrics(fs, year, "11011")
                    rec["period"] = "annual"
                    rec["report_label"] = "사업보고서"
                    rec["date"] = str(year)
                    if has_dart_core_values(rec):
                        annual_records.append(rec)
            except Exception:
                continue

        annual_records = sorted(annual_records, key=lambda r: str(r.get("fiscal_year")))
        annual_map = {
            int(r.get("fiscal_year")): r
            for r in annual_records
            if str(r.get("fiscal_year", "")).isdigit()
        }

        quarter_cum_by_year = {}
        for year in range(current_year, current_year - 4, -1):
            for report_code in ["11013", "11012", "11014"]:
                try:
                    fs = fetch_dart_finstate_all_raw(stock_code, year, report_code)
                    if fs is not None and not fs.empty:
                        rec = extract_dart_metrics(fs, year, report_code)
                        if has_dart_core_values(rec):
                            quarter_cum_by_year.setdefault(int(year), {})[report_code] = rec
                except Exception:
                    continue

        single_quarter_candidates = []
        for year, reports in quarter_cum_by_year.items():
            q1 = reports.get("11013")
            q2 = reports.get("11012")
            q3 = reports.get("11014")
            annual = annual_map.get(year)

            if q1 is not None:
                single_quarter_candidates.append(make_dart_single_quarter_record(q1, None, fiscal_quarter=1))
            if q2 is not None and q1 is not None:
                single_quarter_candidates.append(make_dart_single_quarter_record(q2, q1, fiscal_quarter=2))
            if q3 is not None and q2 is not None:
                single_quarter_candidates.append(make_dart_single_quarter_record(q3, q2, fiscal_quarter=3))
            if annual is not None and q3 is not None:
                single_quarter_candidates.append(make_dart_single_quarter_record(annual, q3, fiscal_quarter=4))

        quarter_records = sorted(
            single_quarter_candidates,
            key=lambda r: (int(r.get("fiscal_year", 0)), int(r.get("fiscal_quarter", 0) or 0))
        )

        if len(annual_records) < 2:
            return {"ok": False, "source": "dart", "reason": "DART 최근 연간 재무 2개년 이상 확보 실패"}

        if len(quarter_records) < 1:
            return {"ok": False, "source": "dart", "reason": "DART 단일 분기 재무 확보 실패"}

        return {
            "ok": True,
            "source": "dart",
            "ticker": ticker,
            "annual": annual_records[-3:],
            "quarter": quarter_records[-4:],
        }

    except Exception as e:
        return {"ok": False, "source": "dart", "reason": f"DART 오류: {e}"}

def fmp_request(endpoint, ticker, period, limit, api_key):
    url = f"https://financialmodelingprep.com/stable/{endpoint}"
    params = {"symbol": ticker, "period": period, "limit": limit}
    headers = {"apikey": api_key}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=15)
    except Exception as e:
        raise RuntimeError(f"FMP 요청 실패: {endpoint}, {ticker}, {period}, {e}")

    if res.status_code in [402, 403]:
        try: err = res.json()
        except Exception: err = res.text[:300]
        raise RuntimeError(f"FMP 구독/권한 제한: {ticker} {endpoint} {period} (HTTP {res.status_code}). 원문: {err}")

    if res.status_code == 429:
        raise RuntimeError(f"FMP 호출 제한 초과: {ticker} {endpoint} {period}")

    if res.status_code != 200:
        try: err = res.json()
        except Exception: err = res.text[:300]
        raise RuntimeError(f"FMP HTTP {res.status_code}: {ticker} {endpoint} {period}. 원문: {err}")

    try: data = res.json()
    except Exception: raise RuntimeError(f"FMP JSON 파싱 실패: {ticker} {endpoint} {period}")

    if isinstance(data, dict):
        msg = data.get("Error Message") or data.get("error") or data.get("message")
        if msg: raise RuntimeError(f"FMP 응답 오류: {ticker} {endpoint} {period}. {msg}")
        return []

    return data if isinstance(data, list) else []

def find_fmp_match(records, income_row):
    if not records: return {}
    date = income_row.get("date")
    fiscal_year = str(income_row.get("calendarYear") or income_row.get("fiscalYear") or "")[:4]
    period = str(income_row.get("period", ""))

    for r in records:
        if date and r.get("date") == date: return r
    for r in records:
        r_year = str(r.get("calendarYear") or r.get("fiscalYear") or "")[:4]
        if fiscal_year and r_year == fiscal_year and str(r.get("period", "")) == period: return r
    for r in records:
        r_year = str(r.get("calendarYear") or r.get("fiscalYear") or "")[:4]
        if fiscal_year and r_year == fiscal_year: return r

    return records[0]

def extract_fmp_metrics(inc, bal, cf, period_type):
    fiscal_year = str(inc.get("calendarYear") or inc.get("fiscalYear") or "")[:4]
    record = {
        "period": period_type,
        "fiscal_year": fiscal_year,
        "report_code": inc.get("period", ""),
        "report_label": inc.get("period", period_type),
        "date": inc.get("date", ""),
        "revenue": safe_float(inc.get("revenue")),
        "op_income": safe_float(inc.get("operatingIncome")),
        "net_income": safe_float(inc.get("netIncome")),
        "ocf": safe_float(cf.get("netCashProvidedByOperatingActivities", cf.get("operatingCashFlow"))),
        "equity": safe_float(bal.get("totalStockholdersEquity", bal.get("totalEquity", bal.get("totalShareholderEquity")))),
        "liabilities": safe_float(bal.get("totalLiabilities")),
        "assets": safe_float(bal.get("totalAssets")),
        "cash": safe_float(bal.get("cashAndCashEquivalents", bal.get("cashAndShortTermInvestments"))),
    }
    return enrich_fin_record(record)

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_us_financials_auto(ticker: str):
    api_key = st.secrets.get("fmp_api_key", "")
    if not api_key: return {"ok": False, "source": "fmp", "reason": "FMP API 키 없음"}

    symbol = str(ticker).strip().upper()
    try:
        annual_income = fmp_request("income-statement", symbol, "annual", 5, api_key)
        annual_balance = fmp_request("balance-sheet-statement", symbol, "annual", 5, api_key)
        annual_cashflow = fmp_request("cash-flow-statement", symbol, "annual", 5, api_key)
        quarter_income = fmp_request("income-statement", symbol, "quarter", 5, api_key)
        quarter_balance = fmp_request("balance-sheet-statement", symbol, "quarter", 5, api_key)
        quarter_cashflow = fmp_request("cash-flow-statement", symbol, "quarter", 5, api_key)

        if not annual_income: return {"ok": False, "source": "fmp", "reason": "FMP 연간 손익계산서 없음"}
        if not annual_balance: return {"ok": False, "source": "fmp", "reason": "FMP 연간 재무상태표 없음"}
        if not annual_cashflow: return {"ok": False, "source": "fmp", "reason": "FMP 연간 현금흐름표 없음"}
        if not quarter_income: return {"ok": False, "source": "fmp", "reason": "FMP 분기 손익계산서 없음"}
        if not quarter_balance: return {"ok": False, "source": "fmp", "reason": "FMP 분기 재무상태표 없음"}
        if not quarter_cashflow: return {"ok": False, "source": "fmp", "reason": "FMP 분기 현금흐름표 없음"}

        annual_records = []
        for inc in annual_income[:3]:
            bal = find_fmp_match(annual_balance, inc)
            cf = find_fmp_match(annual_cashflow, inc)
            annual_records.append(extract_fmp_metrics(inc, bal, cf, "annual"))

        quarter_records = []
        for inc in quarter_income[:4]:
            bal = find_fmp_match(quarter_balance, inc)
            cf = find_fmp_match(quarter_cashflow, inc)
            quarter_records.append(extract_fmp_metrics(inc, bal, cf, "quarter"))

        annual_records = sorted(annual_records, key=lambda r: str(r.get("date")))
        quarter_records = sorted(quarter_records, key=lambda r: str(r.get("date")))

        if len(annual_records) < 2: return {"ok": False, "source": "fmp", "reason": "FMP 최근 연간 재무 2개년 이상 확보 실패"}

        return {
            "ok": True,
            "source": "fmp",
            "ticker": ticker,
            "annual": annual_records[-3:],
            "quarter": quarter_records[-4:],
        }
    except Exception as e:
        return {"ok": False, "source": "fmp", "reason": f"FMP 오류: {e}"}

def getsymbol_score(symbol: str) -> int:
    s = str(symbol)
    if "🚨" in s: return 0
    if "💎" in s or "✅" in s: return 1
    if "⚠️" in s or "❌" in s: return -1
    return 0

def judge_text(ok_icon, bad_icon, title, body):
    return f"{ok_icon} {title}: {body}"

def build_fin_judgements(fin: dict, order_profile: bool = False):
    annual = fin.get("annual", []) or []
    quarter = fin.get("quarter", []) or []

    latest_a = annual[-1] if annual else {}
    prev_a = annual[-2] if len(annual) >= 2 else {}
    old_a = annual[-3] if len(annual) >= 3 else {}
    latest_q = quarter[-1] if quarter else {}
    prev_q = quarter[-2] if len(quarter) >= 2 else {}

    rev_growth = pct_change(latest_a.get("revenue"), prev_a.get("revenue"))
    prev_rev_growth = pct_change(prev_a.get("revenue"), old_a.get("revenue"))
    op_growth = pct_change(latest_a.get("op_income"), prev_a.get("op_income"))
    net_growth = pct_change(latest_a.get("net_income"), prev_a.get("net_income"))
    ocf_growth = pct_change(latest_a.get("ocf"), prev_a.get("ocf"))
    cash_growth = pct_change(latest_a.get("cash"), prev_a.get("cash"))
    equity_growth = pct_change(latest_a.get("equity"), prev_a.get("equity"))
    liability_growth = pct_change(latest_a.get("liabilities"), prev_a.get("liabilities"))

    q_rev_growth = pct_change(latest_q.get("revenue"), prev_q.get("revenue"))
    q_op_growth = pct_change(latest_q.get("op_income"), prev_q.get("op_income"))
    q_net_growth = pct_change(latest_q.get("net_income"), prev_q.get("net_income"))
    q_ocf_growth = pct_change(latest_q.get("ocf"), prev_q.get("ocf"))
    q_equity_growth = pct_change(latest_q.get("equity"), prev_q.get("equity"))

    op_margin_min = 4 if order_profile else 8
    q_margin_min = 2 if order_profile else 5
    debt_limit = 250 if order_profile else 180
    q_debt_limit = 300 if order_profile else 220
    revenue_drop_limit = -25 if order_profile else -15
    high_growth_min = 10 if order_profile else 20
    op_growth_min = 15 if order_profile else 25
    scale_floor = 0.75 if order_profile else 0.85

    annual_j = {}
    quarter_j = {}

    revenues = [r.get("revenue") for r in annual[-3:]]
    op_incomes = [r.get("op_income") for r in annual[-3:]]
    avg_revenue = np.nanmean([x for x in revenues if finite_num(x)]) if any(finite_num(x) for x in revenues) else np.nan

    if len(revenues) >= 3 and all(finite_num(x) for x in revenues):
        if revenues[0] < revenues[1] < revenues[2]:
            annual_j["annual_3y_revenue_uptrend"] = judge_text("💎", "⚠️", "3년연속우상향", "최근 3개년 매출이 연속 증가")
        elif order_profile and revenues[2] > revenues[0] and revenues[2] >= revenues[1] * 0.9:
            annual_j["annual_3y_revenue_uptrend"] = judge_text("✅", "⚠️", "3년연속우상향", "수주형 완화 기준 통과")
        else:
            annual_j["annual_3y_revenue_uptrend"] = judge_text("⚠️", "⚠️", "3년연속우상향", "최근 3개년 매출 연속 증가 실패")
    else:
        annual_j["annual_3y_revenue_uptrend"] = "➖ 3년연속우상향: 데이터 부족"

    if len(op_incomes) >= 3 and all(finite_num(x) for x in op_incomes):
        if op_incomes[0] < op_incomes[1] < op_incomes[2]:
            annual_j["annual_op_income_uptrend"] = "💎 영업이익우상향: 최근 3개년 영업이익 연속 증가"
        elif latest_a.get("op_income", np.nan) > 0 and (order_profile or finite_num(op_growth) and op_growth >= 0):
            annual_j["annual_op_income_uptrend"] = "✅ 영업이익우상향: 최근 영업이익 양호"
        else:
            annual_j["annual_op_income_uptrend"] = "⚠️ 영업이익우상향: 영업이익 추세 둔화"
    else:
        annual_j["annual_op_income_uptrend"] = "➖ 영업이익우상향: 데이터 부족"

    if (finite_num(rev_growth) and rev_growth >= high_growth_min) or (finite_num(op_growth) and op_growth >= op_growth_min) or (finite_num(latest_a.get("op_margin")) and latest_a.get("op_margin") >= op_margin_min + 4):
        annual_j["annual_recent_high_growth"] = f"✅ 최근고성장: 매출성장 {fmt_pct(rev_growth)}, 영업이익성장 {fmt_pct(op_growth)}"
    else:
        annual_j["annual_recent_high_growth"] = f"⚠️ 최근고성장: 고성장 기준 미달, 매출성장 {fmt_pct(rev_growth)}"

    annual_j["annual_profitability_good"] = (
        f"✅ 수익성 양호: 영업이익률 {fmt_pct(latest_a.get('op_margin'))}"
        if finite_num(latest_a.get("op_margin")) and latest_a.get("op_margin") >= op_margin_min and latest_a.get("net_income", 0) >= 0
        else f"⚠️ 수익성 양호: 영업이익률 {fmt_pct(latest_a.get('op_margin'))}"
    )

    annual_j["annual_ocf_strength"] = (
        f"✅ 영업현금흐름 양호: OCF {fmt_num(latest_a.get('ocf'))}"
        if finite_num(latest_a.get("ocf")) and latest_a.get("ocf") > 0
        else f"❌ 영업현금흐름 양호: OCF {fmt_num(latest_a.get('ocf'))}"
    )

    annual_j["annual_recent_revenue_growth"] = (
        f"✅ 최근매출증가: 전년 대비 {fmt_pct(rev_growth)}"
        if finite_num(rev_growth) and rev_growth > 0
        else f"⚠️ 최근매출증가: 전년 대비 {fmt_pct(rev_growth)}"
    )

    annual_j["annual_net_income_positive"] = (
        f"✅ 순이익흑자: 순이익 {fmt_num(latest_a.get('net_income'))}"
        if finite_num(latest_a.get("net_income")) and latest_a.get("net_income") > 0
        else f"❌ 순이익흑자: 순이익 {fmt_num(latest_a.get('net_income'))}"
    )

    annual_j["annual_cash_increase"] = (
        f"✅ 현금증가: 현금성자산 증가율 {fmt_pct(cash_growth)}"
        if finite_num(cash_growth) and cash_growth > 0
        else ("➖ 현금증가: 현금성자산 데이터 부족" if not finite_num(cash_growth) else f"⚠️ 현금증가: 현금성자산 증가율 {fmt_pct(cash_growth)}")
    )

    cash_buffer_ratio = calc_ratio(latest_a.get("cash"), latest_a.get("revenue"))
    annual_j["annual_cash_buffer"] = (
        f"✅ 현금확보(유지): 현금/매출 {fmt_pct(cash_buffer_ratio)}"
        if (finite_num(cash_buffer_ratio) and cash_buffer_ratio >= 8) or (finite_num(latest_a.get("ocf")) and latest_a.get("ocf") > 0)
        else f"⚠️ 현금확보(유지): 현금/매출 {fmt_pct(cash_buffer_ratio)}"
    )

    annual_j["annual_equity_growth"] = (
        f"✅ 자본증가: 자본 증가율 {fmt_pct(equity_growth)}"
        if finite_num(equity_growth) and equity_growth >= 0
        else f"⚠️ 자본증가: 자본 증가율 {fmt_pct(equity_growth)}"
    )

    annual_j["annual_debt_stability"] = (
        f"✅ 부채안정: 부채비율 {fmt_pct(latest_a.get('debt_ratio'))}"
        if finite_num(latest_a.get("debt_ratio")) and latest_a.get("debt_ratio") <= debt_limit
        else f"⚠️ 부채안정: 부채비율 {fmt_pct(latest_a.get('debt_ratio'))}"
    )

    annual_j["annual_average_scale_maintained"] = (
        f"✅ 평균규모유지: 최근 매출 {fmt_num(latest_a.get('revenue'))}, 3년 평균 {fmt_num(avg_revenue)}"
        if finite_num(avg_revenue) and finite_num(latest_a.get("revenue")) and latest_a.get("revenue") >= avg_revenue * scale_floor
        else f"⚠️ 평균규모유지: 최근 매출 {fmt_num(latest_a.get('revenue'))}, 3년 평균 {fmt_num(avg_revenue)}"
    )

    annual_j["annual_growth_slowdown"] = (
        f"⚠️ 성장둔화: 최근 성장률 {fmt_pct(rev_growth)}, 직전 성장률 {fmt_pct(prev_rev_growth)}"
        if finite_num(rev_growth) and finite_num(prev_rev_growth) and rev_growth < prev_rev_growth - 10 and rev_growth < 5
        else f"✅ 성장둔화: 뚜렷한 둔화 없음, 최근 성장률 {fmt_pct(rev_growth)}"
    )

    annual_j["annual_scale_loss"] = (
        f"❌ 매출규모감소: 매출 증가율 {fmt_pct(rev_growth)}"
        if finite_num(rev_growth) and rev_growth <= revenue_drop_limit
        else f"✅ 매출규모감소: 급격한 매출 감소 없음, 증가율 {fmt_pct(rev_growth)}"
    )

    annual_j["annual_body_decline"] = (
        f"❌ 체력감소: 순이익성장 {fmt_pct(net_growth)}, OCF성장 {fmt_pct(ocf_growth)}"
        if finite_num(net_growth) and finite_num(ocf_growth) and net_growth < 0 and ocf_growth < 0
        else f"✅ 체력감소: 순이익/OCF 동반 악화 아님"
    )

    annual_j["annual_margin_quality"] = (
        f"✅ 이익률유지: 순이익률 {fmt_pct(latest_a.get('net_margin'))}"
        if finite_num(latest_a.get("net_margin")) and latest_a.get("net_margin") >= 3
        else f"⚠️ 이익률유지: 순이익률 {fmt_pct(latest_a.get('net_margin'))}"
    )

    annual_j["annual_roe_quality"] = (
        f"✅ ROE양호: ROE {fmt_pct(latest_a.get('roe'))}"
        if finite_num(latest_a.get("roe")) and latest_a.get("roe") >= 6
        else f"⚠️ ROE양호: ROE {fmt_pct(latest_a.get('roe'))}"
    )

    annual_j["annual_debt_ratio_quality"] = (
        f"✅ 부채비율품질: 부채비율 {fmt_pct(latest_a.get('debt_ratio'))}, 부채증가율 {fmt_pct(liability_growth)}"
        if finite_num(latest_a.get("debt_ratio")) and latest_a.get("debt_ratio") <= debt_limit
        else f"⚠️ 부채비율품질: 부채비율 {fmt_pct(latest_a.get('debt_ratio'))}"
    )

    hard_risk = (
        finite_num(latest_a.get("net_income")) and latest_a.get("net_income") < 0 and
        finite_num(latest_a.get("ocf")) and latest_a.get("ocf") < 0
    ) or (
        finite_num(latest_a.get("equity")) and latest_a.get("equity") <= 0
    ) or (
        finite_num(latest_a.get("debt_ratio")) and latest_a.get("debt_ratio") >= 500
    )

    annual_j["annual_hard_risk"] = (
        "🚨 하드리스크: 순이익 적자와 영업현금흐름 적자 또는 자본잠식/초고부채"
        if hard_risk else "✅ 하드리스크: 핵심 하드리스크 미발생"
    )

    quarter_j["quarter_revenue_momentum"] = (
        f"✅ 최근분기매출증가: 직전분기 대비 {fmt_pct(q_rev_growth)}"
        if finite_num(q_rev_growth) and q_rev_growth >= (-5 if order_profile else 0)
        else f"⚠️ 최근분기매출증가: 직전분기 대비 {fmt_pct(q_rev_growth)}"
    )

    quarter_j["quarter_profit_momentum"] = (
        f"✅ 최근분기이익증가: 영업이익 증가율 {fmt_pct(q_op_growth)}"
        if finite_num(q_op_growth) and q_op_growth >= (-10 if order_profile else 0)
        else f"⚠️ 최근분기이익증가: 영업이익 증가율 {fmt_pct(q_op_growth)}"
    )

    quarter_j["quarter_cashflow_quality"] = (
        f"✅ 최근분기현금흐름양호: OCF {fmt_num(latest_q.get('ocf'))}"
        if finite_num(latest_q.get("ocf")) and latest_q.get("ocf") > 0
        else f"⚠️ 최근분기현금흐름양호: OCF {fmt_num(latest_q.get('ocf'))}"
    )

    quarter_j["quarter_revenue_increase"] = quarter_j["quarter_revenue_momentum"]
    quarter_j["quarter_profit_increase"] = quarter_j["quarter_profit_momentum"]

    quarter_j["quarter_ocf_positive"] = (
        f"✅ 최근분기OCF흑자: OCF {fmt_num(latest_q.get('ocf'))}"
        if finite_num(latest_q.get("ocf")) and latest_q.get("ocf") > 0
        else f"❌ 최근분기OCF흑자: OCF {fmt_num(latest_q.get('ocf'))}"
    )

    quarter_j["quarter_margin_good"] = (
        f"✅ 최근분기수익성양호: 영업이익률 {fmt_pct(latest_q.get('op_margin'))}"
        if finite_num(latest_q.get("op_margin")) and latest_q.get("op_margin") >= q_margin_min
        else f"⚠️ 최근분기수익성양호: 영업이익률 {fmt_pct(latest_q.get('op_margin'))}"
    )

    quarter_j["quarter_debt_stability"] = (
        f"✅ 최근분기부채안정: 부채비율 {fmt_pct(latest_q.get('debt_ratio'))}"
        if finite_num(latest_q.get("debt_ratio")) and latest_q.get("debt_ratio") <= q_debt_limit
        else f"⚠️ 최근분기부채안정: 부채비율 {fmt_pct(latest_q.get('debt_ratio'))}"
    )

    quarter_j["quarter_equity_maintained"] = (
        f"✅ 최근분기자본유지: 자본증가율 {fmt_pct(q_equity_growth)}"
        if not finite_num(q_equity_growth) or q_equity_growth >= -5
        else f"⚠️ 최근분기자본유지: 자본증가율 {fmt_pct(q_equity_growth)}"
    )

    quarter_j["quarter_revenue_quality"] = (
        f"✅ 분기매출품질: 매출 {fmt_num(latest_q.get('revenue'))}"
        if finite_num(latest_q.get("revenue")) and latest_q.get("revenue") > 0
        else f"❌ 분기매출품질: 매출 {fmt_num(latest_q.get('revenue'))}"
    )

    quarter_j["quarter_profit_quality"] = (
        f"✅ 분기이익품질: 순이익 {fmt_num(latest_q.get('net_income'))}"
        if finite_num(latest_q.get("net_income")) and latest_q.get("net_income") >= 0
        else f"⚠️ 분기이익품질: 순이익 {fmt_num(latest_q.get('net_income'))}"
    )

    quarter_j["quarter_cash_quality"] = (
        f"✅ 분기현금품질: OCF 증가율 {fmt_pct(q_ocf_growth)}"
        if finite_num(latest_q.get("ocf")) and latest_q.get("ocf") > 0
        else f"⚠️ 분기현금품질: OCF 증가율 {fmt_pct(q_ocf_growth)}"
    )

    quarter_j["quarter_margin_quality"] = quarter_j["quarter_margin_good"]
    quarter_j["quarter_debt_ratio_quality"] = quarter_j["quarter_debt_stability"]

    quarter_hard_risk = (
        finite_num(latest_q.get("net_income")) and latest_q.get("net_income") < 0 and
        finite_num(latest_q.get("ocf")) and latest_q.get("ocf") < 0
    ) or (
        finite_num(q_rev_growth) and q_rev_growth <= -25 and finite_num(latest_q.get("op_income")) and latest_q.get("op_income") < 0
    )

    quarter_j["quarter_warning"] = (
        "🚨 분기경고: 분기 순이익 적자와 OCF 적자 또는 급격한 매출감소"
        if quarter_hard_risk else "✅ 분기경고: 중대 분기 경고 없음"
    )

    all_j = {}
    all_j.update(annual_j)
    all_j.update(quarter_j)

    metrics = {
        "annual_latest": latest_a,
        "annual_previous": prev_a,
        "quarter_latest": latest_q,
        "quarter_previous": prev_q,
        "derived": {
            "rev_growth": rev_growth,
            "prev_rev_growth": prev_rev_growth,
            "op_growth": op_growth,
            "net_growth": net_growth,
            "ocf_growth": ocf_growth,
            "cash_growth": cash_growth,
            "equity_growth": equity_growth,
            "liability_growth": liability_growth,
            "q_rev_growth": q_rev_growth,
            "q_op_growth": q_op_growth,
            "q_net_growth": q_net_growth,
            "q_ocf_growth": q_ocf_growth,
            "q_equity_growth": q_equity_growth,
            "order_profile": order_profile,
        },
        "annual_judgements": annual_j,
        "quarter_judgements": quarter_j,
    }

    return annual_j, quarter_j, all_j, metrics

def calc_weighted_fin_total(judgements: dict, danger_limit: int):
    danger_count = sum(1 for v in judgements.values() if "🚨" in str(v))

    s_sum = sum(getsymbol_score(judgements.get(k, "")) for k in FIN_S_KEYS) * 3
    a_sum = sum(getsymbol_score(judgements.get(k, "")) for k in FIN_A_KEYS) * 2
    b_sum = sum(getsymbol_score(judgements.get(k, "")) for k in FIN_B_KEYS) * 1

    weighted = s_sum + a_sum + b_sum

    if danger_count >= danger_limit: total = 1
    elif weighted >= 45: total = 4
    elif weighted >= 25: total = 3
    elif weighted >= 5: total = 2
    else: total = 1

    return total, {
        "s_sum": s_sum,
        "a_sum": a_sum,
        "b_sum": b_sum,
        "weighted_net_score": weighted,
        "danger_count": danger_count,
        "danger_limit": danger_limit,
    }

def calc_generic_fin_total(judgements: dict):
    return calc_weighted_fin_total(judgements, danger_limit=1)

def calc_order_fin_total(judgements: dict):
    return calc_weighted_fin_total(judgements, danger_limit=2)

def round_half_up(x):
    return int(np.floor(float(x) + 0.5))

def calc_middle_fin_total(judgements: dict):
    generic_score, generic_weighted = calc_generic_fin_total(judgements)
    order_score, order_weighted = calc_order_fin_total(judgements)

    if generic_score == 1 and order_score == 1: middle_score = 1
    else: middle_score = round_half_up((generic_score + order_score) / 2)

    return middle_score, {
        "generic_score": generic_score,
        "order_score": order_score,
        "middle_score": middle_score,
        "generic_weighted": generic_weighted,
        "order_weighted": order_weighted,
        "weighted_net_score": generic_weighted["weighted_net_score"],
        "s_sum": generic_weighted["s_sum"],
        "a_sum": generic_weighted["a_sum"],
        "b_sum": generic_weighted["b_sum"],
        "danger_count": generic_weighted["danger_count"],
    }

def get_auto_fin_score_for_ticker(ticker: str, is_etf: bool):
    if is_etf:
        notes = {
            "ok": True, "source": "etf", "mode": "ETF", "reason": "ETF는 재무점수 미합산",
            "annual_judgements": {}, "quarter_judgements": {}, "weighted_scores": {},
        }
        return 0, {"ok": True, "source": "etf"}, notes, {}

    is_kr = str(ticker).upper().endswith(".KS") or str(ticker).upper().endswith(".KQ")
    fin = fetch_kr_financials_auto(ticker) if is_kr else fetch_us_financials_auto(ticker)

    if not fin.get("ok", False):
        metrics = {}
        notes = {
            "ok": False, "source": fin.get("source", "unknown"), "mode": "fallback",
            "reason": fin.get("reason", "원인 미상"), "annual_judgements": {}, "quarter_judgements": {},
            "weighted_scores": {}, "messages": [f"자동 재무 조회 실패 -> 보수 임시 {AUTO_FIN_FAIL_SCORE}점", f"사유: {fin.get('reason', '원인 미상')}"],
        }
        return AUTO_FIN_FAIL_SCORE, fin, notes, metrics

    order_profile = is_order_based_ticker(ticker)
    annual_j, quarter_j, all_j, metrics = build_fin_judgements(fin, order_profile=order_profile)

    generic_score, generic_detail = calc_generic_fin_total(all_j)
    order_score, order_detail = calc_order_fin_total(all_j)
    middle_score, middle_detail = calc_middle_fin_total(all_j)

    if order_profile:
        selected_score = order_score
        selected_mode = "수주판단"
    else:
        selected_score = middle_score
        selected_mode = "중간형판단"

    weighted_scores = {
        "selected_mode": selected_mode, "selected_score": selected_score, "generic_score": generic_score,
        "order_score": order_score, "middle_score": middle_score, "generic_detail": generic_detail,
        "order_detail": order_detail, "middle_detail": middle_detail, "weighted_net_score": generic_detail["weighted_net_score"],
        "s_sum": generic_detail["s_sum"], "a_sum": generic_detail["a_sum"], "b_sum": generic_detail["b_sum"],
        "danger_count": generic_detail["danger_count"], "s_keys": FIN_S_KEYS, "a_keys": FIN_A_KEYS, "b_keys": FIN_B_KEYS,
    }

    metrics["annual_records"] = fin.get("annual", [])
    metrics["quarter_records"] = fin.get("quarter", [])
    metrics["weighted_scores"] = weighted_scores

    notes = {
        "ok": True, "source": fin.get("source", "unknown"), "mode": selected_mode,
        "order_profile": order_profile, "annual_judgements": annual_j, "quarter_judgements": quarter_j,
        "weighted_scores": weighted_scores, "messages": [
            f"source: {fin.get('source', 'unknown')}", f"mode: {selected_mode}",
            f"weighted_score: {weighted_scores['weighted_net_score']}",
            f"S_sum: {weighted_scores['s_sum']}, A_sum: {weighted_scores['a_sum']}, B_sum: {weighted_scores['b_sum']}",
            f"범용판단: {generic_score}, 수주판단: {order_score}, 중간형판단: {middle_score}",
        ],
    }

    return int(selected_score), fin, notes, metrics

def get_final_fin_score(ticker, is_etf, asset_class):
    key = normalize_ticker(ticker)
    auto_score, fin_auto, fin_notes, fin_metrics = get_auto_fin_score_for_ticker(ticker, is_etf)

    manual_score = None
    if not is_etf:
        fin_scores_df = load_fin_scores_db()
        matched = fin_scores_df[fin_scores_df["ticker"] == key]
        if not matched.empty:
            row = matched.iloc[0]
            if pd.notna(row["manual_score"]):
                manual_score = int(row["manual_score"])

    final_score = 0 if is_etf else (manual_score if manual_score is not None else int(auto_score))

    stored_notes = dict(fin_notes) if isinstance(fin_notes, dict) else {"messages": fin_notes}
    stored_notes["metrics"] = fin_metrics

    upsert_fin_score_db(
        ticker=key, auto_score=int(auto_score), manual_score=manual_score,
        final_score=int(final_score), source=fin_auto.get("source", "unknown"), notes=stored_notes
    )

    return int(final_score), {
        "auto_score": int(auto_score), "manual_score": manual_score, "final_score": int(final_score),
        "source": fin_auto.get("source", "unknown"), "mode": stored_notes.get("mode", "unknown"),
        "notes": stored_notes, "metrics": fin_metrics,
    }

def set_manual_fin_score(ticker, score):
    key = normalize_ticker(ticker)
    fin_scores_df = load_fin_scores_db()
    matched = fin_scores_df[fin_scores_df["ticker"] == key]

    if matched.empty:
        upsert_fin_score_db(
            ticker=key, auto_score=None, manual_score=int(score), final_score=int(score),
            source="manual", notes={"messages": ["수동 재무점수 저장"]}
        )
        return

    row = matched.iloc[0]
    notes = {}
    try: notes = json.loads(row["notes_json"]) if pd.notna(row["notes_json"]) else {}
    except Exception: notes = {}

    upsert_fin_score_db(
        ticker=key, auto_score=int(row["auto_score"]) if pd.notna(row["auto_score"]) else None,
        manual_score=int(score), final_score=int(score),
        source=row["source"] if pd.notna(row["source"]) else "manual", notes=notes
    )

def reset_manual_fin_score(ticker):
    delete_manual_fin_score_db(ticker)

def parse_notes_json(value):
    try:
        if value is None or pd.isna(value) or str(value).strip() == "": return {}
        data = json.loads(value)
        if isinstance(data, dict): return data
        if isinstance(data, list): return {"messages": data}
        return {"messages": [str(data)]}
    except Exception:
        return {"messages": ["notes_json 파싱 실패"]}

def load_fin_score_meta_fast(ticker, is_etf):
    key = normalize_ticker(ticker)

    if is_etf:
        return 0, {
            "auto_score": 0, "manual_score": None, "final_score": 0,
            "source": "etf", "mode": "ETF", "metrics": {},
            "notes": {"mode": "ETF", "messages": ["ETF/ETN/레버리지 상품은 재무점수 해당없음"], "annual_judgements": {}, "quarter_judgements": {}, "weighted_scores": {}},
        }

    fin_scores_df = load_fin_scores_db()
    matched = fin_scores_df[fin_scores_df["ticker"] == key]

    if matched.empty:
        return UNCALCULATED_FIN_DEFAULT_SCORE, {
            "auto_score": None, "manual_score": None, "final_score": UNCALCULATED_FIN_DEFAULT_SCORE,
            "source": "not_calculated", "mode": "manual_or_default", "metrics": {},
            "notes": {"mode": "manual_or_default", "messages": ["자동 재무점수 미계산 상태입니다."], "annual_judgements": {}, "quarter_judgements": {}, "weighted_scores": {}},
        }

    row = matched.iloc[0]
    notes = parse_notes_json(row.get("notes_json"))
    metrics = notes.get("metrics", {}) if isinstance(notes, dict) else {}

    auto_score = int(row["auto_score"]) if pd.notna(row["auto_score"]) else None
    manual_score = int(row["manual_score"]) if pd.notna(row["manual_score"]) else None
    db_final_score = int(row["final_score"]) if pd.notna(row["final_score"]) else None

    if manual_score is not None: final_score = manual_score
    elif db_final_score is not None: final_score = db_final_score
    elif auto_score is not None: final_score = auto_score
    else: final_score = 3

    return int(final_score), {
        "auto_score": auto_score, "manual_score": manual_score, "final_score": int(final_score),
        "source": row["source"] if pd.notna(row["source"]) else "saved",
        "mode": notes.get("mode", "saved") if isinstance(notes, dict) else "saved",
        "notes": notes, "metrics": metrics,
    }

def get_fin_meta_parts(fin_meta):
    notes = fin_meta.get("notes", {}) if isinstance(fin_meta, dict) else {}
    if not isinstance(notes, dict):
        notes = {"messages": notes if isinstance(notes, list) else [str(notes)]}

    metrics = fin_meta.get("metrics", {}) if isinstance(fin_meta, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    if not metrics and isinstance(notes.get("metrics"), dict):
        metrics = notes.get("metrics", {})

    weighted = notes.get("weighted_scores", {})
    if not isinstance(weighted, dict) or not weighted:
        weighted = metrics.get("weighted_scores", {}) if isinstance(metrics.get("weighted_scores", {}), dict) else {}

    return notes, metrics, weighted

def get_fin_latest_record(metrics, latest_key, records_key):
    latest = metrics.get(latest_key, {}) if isinstance(metrics, dict) else {}
    if isinstance(latest, dict) and latest:
        return latest

    records = metrics.get(records_key, []) if isinstance(metrics, dict) else []
    if isinstance(records, list):
        for record in reversed(records):
            if isinstance(record, dict) and record:
                return record
    return {}

def fin_status_from_score(fin_score, is_etf=False):
    if is_etf:
        return "해당없음"
    try:
        score = int(fin_score)
    except Exception:
        return "미계산"
    if score >= 4:
        return "양호"
    if score == 3:
        return "보통"
    if score == 2:
        return "주의"
    return "위험"

def fin_status_chip(status):
    color_map = {
        "양호": "#16a34a",
        "보통": "#64748b",
        "주의": "#d97706",
        "위험": "#dc2626",
        "해당없음": "#64748b",
        "미계산": "#64748b",
    }
    color = color_map.get(str(status), "#64748b")
    return (
        f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
        f"background:{color};color:white;font-size:.82rem;font-weight:700;'>"
        f"{escape_html_value(status)}</span>"
    )

def fin_fmt_pct(v):
    return fmt_pct(v)

def fin_fmt_num(v):
    return fmt_num(v)

def fin_pick_status(good, warn):
    if warn:
        return "주의"
    if good:
        return "양호"
    return "보통"

def build_fin_health_rows(fin_score, fin_meta, is_etf=False):
    notes, metrics, weighted = get_fin_meta_parts(fin_meta)
    derived = metrics.get("derived", {}) if isinstance(metrics.get("derived", {}), dict) else {}
    annual = get_fin_latest_record(metrics, "annual_latest", "annual_records")
    quarter = get_fin_latest_record(metrics, "quarter_latest", "quarter_records")

    if is_etf:
        return [{
            "영역": "재무점수",
            "상태": "해당없음",
            "핵심 지표": "ETF/ETN/레버리지 상품",
            "해석": "개별 기업 재무제표가 아니라 구성자산을 담는 상품이라 재무점수 합산에서 제외합니다.",
        }]

    if not annual and not quarter and not weighted:
        return [{
            "영역": "재무점수",
            "상태": "미계산",
            "핵심 지표": "자동 재무점수 미계산",
            "해석": "버튼을 누르면 DART/FMP 재무 데이터를 불러와 자동으로 판정합니다.",
        }]

    rev_growth = derived.get("rev_growth")
    q_rev_growth = derived.get("q_rev_growth")
    growth_status = fin_pick_status(
        finite_num(rev_growth) and float(rev_growth) >= 10 and (not finite_num(q_rev_growth) or float(q_rev_growth) >= -5),
        (finite_num(rev_growth) and float(rev_growth) <= -10) or (finite_num(q_rev_growth) and float(q_rev_growth) <= -15),
    )

    op_margin = annual.get("op_margin")
    net_margin = annual.get("net_margin")
    roe = annual.get("roe")
    q_op_margin = quarter.get("op_margin")
    profitability_status = fin_pick_status(
        (finite_num(op_margin) and float(op_margin) >= 8) or (finite_num(q_op_margin) and float(q_op_margin) >= 8),
        (finite_num(op_margin) and float(op_margin) < 0) or (finite_num(net_margin) and float(net_margin) < 0),
    )

    ocf = annual.get("ocf")
    ocf_margin = annual.get("ocf_margin")
    q_ocf_growth = derived.get("q_ocf_growth")
    cashflow_status = fin_pick_status(
        finite_num(ocf) and float(ocf) > 0 and (not finite_num(q_ocf_growth) or float(q_ocf_growth) > -30),
        finite_num(ocf) and float(ocf) < 0,
    )

    debt_ratio = annual.get("debt_ratio")
    equity_growth = derived.get("equity_growth")
    cash = annual.get("cash")
    revenue = annual.get("revenue")
    cash_to_revenue = calc_ratio(cash, revenue, multiplier=100)
    stability_status = fin_pick_status(
        (not finite_num(debt_ratio) or float(debt_ratio) <= 180) and (not finite_num(equity_growth) or float(equity_growth) >= 0),
        (finite_num(debt_ratio) and float(debt_ratio) >= 300) or (finite_num(equity_growth) and float(equity_growth) <= -10),
    )

    danger_count = weighted.get("danger_count")
    weighted_net = weighted.get("weighted_net_score")
    annual_judgements = notes.get("annual_judgements", {}) if isinstance(notes.get("annual_judgements", {}), dict) else {}
    quarter_judgements = notes.get("quarter_judgements", {}) if isinstance(notes.get("quarter_judgements", {}), dict) else {}
    judgement_values = [str(v) for v in list(annual_judgements.values()) + list(quarter_judgements.values())]
    hard_risks = [v for v in judgement_values if "🚨" in v or "위험" in v]
    trend_status = "위험" if (finite_num(danger_count) and float(danger_count) >= 1) or hard_risks else fin_status_from_score(fin_score)

    return [
        {
            "영역": "성장성",
            "상태": growth_status,
            "핵심 지표": f"연매출 {fin_fmt_pct(rev_growth)} / 최근분기 매출 {fin_fmt_pct(q_rev_growth)}",
            "해석": "매출이 꾸준히 늘고 최근 분기도 꺾이지 않는지 봅니다.",
        },
        {
            "영역": "수익성",
            "상태": profitability_status,
            "핵심 지표": f"영업이익률 {fin_fmt_pct(op_margin)} / 순이익률 {fin_fmt_pct(net_margin)} / ROE {fin_fmt_pct(roe)}",
            "해석": "팔아서 실제로 이익을 남기는 구조인지 봅니다.",
        },
        {
            "영역": "현금흐름",
            "상태": cashflow_status,
            "핵심 지표": f"영업현금흐름 {fin_fmt_num(ocf)} / OCF마진 {fin_fmt_pct(ocf_margin)} / 분기 OCF {fin_fmt_pct(q_ocf_growth)}",
            "해석": "회계상 이익보다 실제 현금이 들어오는지를 확인합니다.",
        },
        {
            "영역": "안정성",
            "상태": stability_status,
            "핵심 지표": f"부채비율 {fin_fmt_pct(debt_ratio)} / 자본증가 {fin_fmt_pct(equity_growth)} / 현금-매출 {fin_fmt_pct(cash_to_revenue)}",
            "해석": "부채 부담과 버틸 체력이 과하지 않은지 봅니다.",
        },
        {
            "영역": "종합 위험",
            "상태": trend_status,
            "핵심 지표": f"가중점수 {weighted_net if finite_num(weighted_net) else '-'} / 위험신호 {int(danger_count) if finite_num(danger_count) else 0}개",
            "해석": "강한 위험 문구가 있으면 최종 점수보다 보수적으로 봅니다.",
        },
    ]

def render_fin_health_summary(fin_score, fin_meta, is_etf=False):
    notes, metrics, weighted = get_fin_meta_parts(fin_meta)
    source = fin_meta.get("source", "-") if isinstance(fin_meta, dict) else "-"
    mode = fin_meta.get("mode", "-") if isinstance(fin_meta, dict) else "-"
    auto_score = fin_meta.get("auto_score", "-") if isinstance(fin_meta, dict) else "-"
    manual_score = fin_meta.get("manual_score", None) if isinstance(fin_meta, dict) else None
    danger_count = weighted.get("danger_count", 0)
    weighted_net = weighted.get("weighted_net_score", np.nan)
    status = fin_status_from_score(fin_score, is_etf=is_etf)

    cols = st.columns(4)
    card_items = [
        ("종합상태", status, f"최종 {fin_score}/4" if not is_etf else "재무점수 제외"),
        ("판정모드", str(mode), f"자동 {auto_score}" + (f" / 수동 {manual_score}" if manual_score is not None else "")),
        ("위험신호", f"{int(danger_count) if finite_num(danger_count) else 0}개", f"가중점수 {weighted_net if finite_num(weighted_net) else '-'}"),
        ("데이터", str(source), "DART/FMP 기준" if not is_etf else "ETF 기준"),
    ]
    for col, (title, value, detail) in zip(cols, card_items):
        with col:
            st.markdown(
                f"<div class='info-panel'><b>{escape_html_value(title)}</b><br>"
                f"<span class='highlight'>{fin_status_chip(value) if title == '종합상태' else escape_html_value(value)}</span><br>"
                f"<span class='score-detail'>{escape_html_value(detail)}</span></div>",
                unsafe_allow_html=True,
            )

    rows = build_fin_health_rows(fin_score, fin_meta, is_etf=is_etf)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    messages = notes.get("messages", []) if isinstance(notes.get("messages", []), list) else []
    if messages and not is_etf:
        st.caption(" · ".join(str(m) for m in messages[:3]))

    if not is_etf:
        st.caption("자동 재무점수는 투자 추천이 아니라 재무제표 기반 체크리스트입니다. 데이터 공백이나 최근 이벤트는 별도 확인이 필요합니다.")

def clear_financial_api_cache():
    for fn_name in ["fetch_us_financials_auto", "fetch_kr_financials_auto", "fetch_dart_finstate_all_raw"]:
        fn = globals().get(fn_name)
        if fn is not None and hasattr(fn, "clear"):
            fn.clear()


# -------------------------------------------------
# 2-3. 보유자산 계산
# -------------------------------------------------
def build_holdings_table(holdings_df, krw_cash, usd_cash, usdkrw):
    if holdings_df.empty:
        return pd.DataFrame(columns=[
            "자산명", "티커", "보유량", "매입가", "현재가", "평가금액", "평가손익",
            "수익률", "원화환산", "현재비중", "목표비중", "비중차이", "is_etf", "asset_class", "bucket", "운용대상", "리밸런싱목표비중"
        ])

    price_tickers = tuple(
        str(ticker).strip()
        for ticker in holdings_df.get("ticker", pd.Series(dtype=str)).tolist()
        if str(ticker).strip()
    )
    latest_price_map = load_latest_prices_batch(price_tickers)

    rows = []
    for _, row in holdings_df.iterrows():
        name = row.get("name", "")
        ticker = row.get("ticker", "")
        qty = float(row.get("qty", 0) or 0)
        avg_price = float(row.get("avg_price", 0) or 0)
        target_weight = float(row.get("target_weight", 0) or 0)
        asset_class = row.get("asset_class", "us_stock")

        bucket = infer_bucket(ticker, row.get("bucket", "core"))

        is_etf = is_fin_score_exempt_asset(ticker, row.get("is_etf", False), asset_class, name)
        asset_class = infer_asset_class_for_ticker(ticker, asset_class) if is_etf else asset_class

        cur_price = clean_float(latest_price_map.get(normalize_price_lookup_key(ticker)), 0.0)
        if cur_price <= 0:
            cur_price = load_latest_price(ticker)

        eval_amt = qty * cur_price
        pnl = qty * (cur_price - avg_price)
        ret = ((cur_price / avg_price) - 1) if avg_price > 0 else 0.0

        is_kr = str(ticker).upper().endswith(".KS") or str(ticker).upper().endswith(".KQ")
        krw_eval = eval_amt if is_kr else eval_amt * usdkrw

        rows.append({
            "자산명": name, "티커": ticker, "보유량": qty, "매입가": avg_price,
            "현재가": cur_price, "평가금액": eval_amt, "평가손익": pnl, "수익률": ret,
            "원화환산": krw_eval, "목표비중": target_weight, "is_etf": is_etf, "asset_class": asset_class,
            "bucket": bucket
        })

    return apply_holdings_weight_columns(pd.DataFrame(rows), krw_cash, usd_cash, usdkrw)

# 돈흐름 데이터 로직은 stock_lab_core.money_flow 모듈로 분리

def fmt_flow_pct(v):
    if not finite_num(v):
        return "-"
    return f"{float(v) * 100:.1f}%"


def get_plotly_selected_ticker(event):
    if not event:
        return ""
    try:
        selection = event.get("selection", {})
    except AttributeError:
        selection = getattr(event, "selection", {}) or {}
    try:
        points = selection.get("points", [])
    except AttributeError:
        points = getattr(selection, "points", []) or []
    if not points:
        return ""

    point = points[0]
    if not isinstance(point, dict):
        point = dict(point)

    customdata = point.get("customdata")
    if isinstance(customdata, (list, tuple)) and customdata:
        return str(customdata[0] or "").strip()

    point_id = str(point.get("id", "") or "")
    if "|" in point_id:
        return point_id.rsplit("|", 1)[-1].strip()

    label = str(point.get("label", "") or "")
    if "<br>" in label:
        return label.split("<br>")[-1].strip()
    return ""


def get_kr_etf_composition(ticker):
    kr_etf_df = load_cached_kr_etf_lab_data()
    if kr_etf_df.empty:
        return pd.DataFrame(), None

    ticker_key = str(ticker or "").strip().upper()
    matched = kr_etf_df[kr_etf_df["ticker"].astype(str).str.upper() == ticker_key]
    if matched.empty:
        return pd.DataFrame(), None

    row = matched.iloc[0]
    rows = []
    for idx in range(1, 6):
        name = str(row.get(f"top_{idx}", "") or "").strip()
        weight = str(row.get(f"top_{idx}_weight_pct", "") or "").strip()
        if not name:
            continue
        rows.append({
            "순위": idx,
            "구성종목": name,
            "비중(%)": clean_float(weight, np.nan),
        })
    return pd.DataFrame(rows), row


def render_money_flow_composition_panel(view_df, selected_ticker=""):
    if view_df is None or view_df.empty:
        return

    option_rows = view_df[["구분", "섹터", "Ticker", "ETF 이름"]].drop_duplicates("Ticker").reset_index(drop=True)
    option_labels = [
        f"{row['구분']} · {row['섹터']} | {row['Ticker']}"
        for _, row in option_rows.iterrows()
    ]
    ticker_by_label = {
        label: str(row["Ticker"]).strip()
        for label, (_, row) in zip(option_labels, option_rows.iterrows())
    }

    selected_key = str(selected_ticker or st.session_state.get("money_flow_selected_ticker", "") or "").strip().upper()
    default_index = 0
    for idx, row in option_rows.iterrows():
        if str(row["Ticker"]).strip().upper() == selected_key:
            default_index = idx
            break

    selected_label = st.selectbox(
        "구성종목 확인",
        option_labels,
        index=default_index,
        key="money_flow_composition_target",
        help="히트맵 블록을 클릭하거나 여기서 ETF를 선택하면 국내상장 ETF의 TOP 구성종목을 확인합니다.",
    )
    ticker = ticker_by_label.get(selected_label, "")
    st.session_state["money_flow_selected_ticker"] = ticker

    selected_flow = option_rows[option_rows["Ticker"] == ticker]
    flow_name = selected_flow.iloc[0]["ETF 이름"] if not selected_flow.empty else ticker
    comp_df, etf_row = get_kr_etf_composition(ticker)

    st.markdown("#### ETF 구성종목")
    if etf_row is None:
        st.info(f"{flow_name} ({ticker})는 국내 ETF 1020 데이터에 없어 구성종목 TOP5를 표시할 수 없습니다.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ETF", str(etf_row.get("name", flow_name))[:18])
    c2.metric("대유형", str(etf_row.get("etf_big_type", "-") or "-"))
    c3.metric("운용규모", f"{clean_float(etf_row.get('aum_krw_100m'), 0.0):,.0f}억")
    c4.metric("실부담", f"{clean_float(etf_row.get('real_fee_pct'), 0.0):.3f}%")

    if comp_df.empty:
        st.info("이 ETF는 TOP 구성종목 데이터가 비어 있습니다.")
    else:
        show_comp = comp_df.copy()
        show_comp["비중(%)"] = show_comp["비중(%)"].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.2f}")
        st.dataframe(show_comp, use_container_width=True, hide_index=True)

    st.caption(
        f"기초지수: {etf_row.get('underlying_index', '-') or '-'} | "
        f"운용사: {etf_row.get('manager', '-') or '-'} | "
        f"분류: {etf_row.get('tags', '-') or '-'}"
    )


def render_money_flow_tab():
    st.subheader("돈흐름 레이더")
    st.caption("미국/한국 섹터, 국내상장 대표 ETF, 월배당 ETF 대표군의 3개월/6개월 흐름과 가속도를 비교해 돈이 어디로 향하는지 봅니다.")

    if not should_run_heavy_analysis(
        "money_flow_lazy",
        "돈흐름 레이더는 여러 ETF 가격을 한 번에 조회하므로 필요할 때만 실행합니다.",
    ):
        return

    with st.spinner("ETF 돈흐름 계산 중..."):
        flow_df = calculate_money_flow_df()

    if flow_df.empty:
        st.warning("돈흐름 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return

    groups = ["전체"] + list(flow_df["구분"].drop_duplicates())
    selected_group = st.radio("보기 범위", groups, horizontal=True, key="money_flow_group")
    view_df = flow_df if selected_group == "전체" else flow_df[flow_df["구분"] == selected_group]

    if view_df.empty:
        st.info("선택한 범위에 표시할 데이터가 없습니다.")
        return

    top_us = flow_df[flow_df["구분"] == "미국 섹터"].head(1)
    top_kr = flow_df[flow_df["구분"] == "한국 섹터"].head(1)
    top_global = flow_df[flow_df["구분"] == "글로벌"].head(1)
    top_income = flow_df[flow_df["구분"] == "월배당 ETF"].head(1)
    top_accel = flow_df.sort_values("가속도", ascending=False).head(1)

    s1, s2, s3, s4, s5 = st.columns(5)
    if not top_us.empty:
        r = top_us.iloc[0]
        s1.metric("미국 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    if not top_kr.empty:
        r = top_kr.iloc[0]
        s2.metric("한국 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    if not top_global.empty:
        r = top_global.iloc[0]
        s3.metric("글로벌 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    if not top_income.empty:
        r = top_income.iloc[0]
        s4.metric("월배당 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    if not top_accel.empty:
        r = top_accel.iloc[0]
        s5.metric("가속도 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["가속도"]))

    leader = view_df.iloc[0]
    accel_leader = view_df.sort_values("가속도", ascending=False).iloc[0]
    weak = view_df.sort_values("돈흐름점수", ascending=True).iloc[0]
    st.markdown(
        f"""
<div class='info-panel'>
<b>해석</b><br>
현재 선택 범위의 돈흐름 1위는 <b>{leader['섹터']} ({leader['Ticker']})</b>입니다.
최근 새로 힘이 붙는 쪽은 <b>{accel_leader['섹터']} ({accel_leader['Ticker']})</b>,
상대적으로 약한 쪽은 <b>{weak['섹터']} ({weak['Ticker']})</b>입니다.
<br><span style='color:#94a3b8;'>가속도는 3개월수익률 - 6개월수익률입니다. 양수면 최근 힘이 새로 붙는 쪽, 음수면 기존 흐름이 둔화되는 쪽으로 해석합니다.</span>
</div>
        """,
        unsafe_allow_html=True,
    )

    m1, m2 = st.columns([1.05, 1])
    tree_event = None

    with m1:
        tree_df = view_df.reset_index(drop=True).copy()
        tree_df["tree_id"] = tree_df["구분"] + "|" + tree_df["섹터"] + "|" + tree_df["Ticker"]
        tree_df["tree_label"] = np.where(
            selected_group == "전체",
            tree_df["구분"] + "<br>" + tree_df["섹터"] + "<br>" + tree_df["Ticker"],
            tree_df["섹터"] + "<br>" + tree_df["Ticker"],
        )
        fig_tree = go.Figure(go.Treemap(
            ids=tree_df["tree_id"],
            labels=tree_df["tree_label"],
            parents=[""] * len(tree_df),
            values=tree_df["히트맵크기"].astype(float).clip(lower=1),
            marker=dict(
                colors=tree_df["돈흐름점수"],
                colorscale=[[0, "#dc2626"], [0.5, "#64748b"], [1, "#16a34a"]],
                cmid=0,
                colorbar=dict(title="돈흐름")
            ),
            customdata=tree_df[["Ticker", "ETF 이름", "3개월수익률", "6개월수익률", "가속도", "상태"]],
            hovertemplate=
                "<b>%{label}</b><br>" +
                "%{customdata[1]}<br>" +
                "3개월: %{customdata[2]:.1%}<br>" +
                "6개월: %{customdata[3]:.1%}<br>" +
                "가속도: %{customdata[4]:.1%}<br>" +
                "상태: %{customdata[5]}<extra></extra>"
        ))
        fig_tree.update_layout(template="plotly_dark", height=470, title="돈흐름 히트맵", margin=dict(t=45, l=4, r=4, b=4))
        tree_event = st.plotly_chart(
            fig_tree,
            use_container_width=True,
            key="money_flow_heatmap_select",
            on_select="rerun",
            selection_mode="points",
        )
        st.caption("블록이 클수록 최근 3개월 움직임이 크고, 초록색일수록 3개월/6개월 흐름과 가속도가 좋다는 뜻입니다. 블록을 클릭하면 아래에서 구성종목을 확인합니다.")

    with m2:
        fig_quad = go.Figure(go.Scatter(
            x=view_df["6개월수익률"] * 100,
            y=view_df["3개월수익률"] * 100,
            mode="markers+text",
            text=view_df["섹터"],
            textposition="top center",
            marker=dict(
                size=np.clip(view_df["가격수준"].fillna(0.5) * 28, 12, 34),
                color=view_df["가속도"] * 100,
                colorscale="RdYlGn",
                cmid=0,
                showscale=True,
                colorbar=dict(title="가속도")
            ),
            customdata=view_df[["Ticker", "상태", "돈흐름점수"]],
            hovertemplate=
                "<b>%{text}</b> (%{customdata[0]})<br>" +
                "6개월: %{x:.1f}%<br>" +
                "3개월: %{y:.1f}%<br>" +
                "상태: %{customdata[1]}<br>" +
                "돈흐름점수: %{customdata[2]:.1f}<extra></extra>"
        ))
        fig_quad.add_vline(x=0, line_dash="dash", line_color="#94a3b8")
        fig_quad.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
        fig_quad.update_layout(
            template="plotly_dark",
            height=470,
            title="로테이션 사분면",
            xaxis_title="6개월 수익률 %",
            yaxis_title="3개월 수익률 %",
        )
        st.plotly_chart(fig_quad, use_container_width=True)

    clicked_ticker = get_plotly_selected_ticker(tree_event)
    if clicked_ticker:
        st.session_state["money_flow_selected_ticker"] = clicked_ticker
    render_money_flow_composition_panel(view_df, clicked_ticker)

    b1, b2 = st.columns(2)
    with b1:
        top_3m = view_df.sort_values("3개월수익률", ascending=False).head(12)
        fig_3m = go.Figure(go.Bar(
            y=top_3m["섹터"] + " (" + top_3m["Ticker"] + ")",
            x=top_3m["3개월수익률"] * 100,
            orientation="h",
            marker_color="#22d3ee",
            hovertemplate="%{y}<br>3개월: %{x:.1f}%<extra></extra>"
        ))
        fig_3m.update_layout(template="plotly_dark", height=430, title="3개월 수익률 랭킹", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_3m, use_container_width=True)

    with b2:
        top_accel_df = view_df.sort_values("가속도", ascending=False).head(12)
        accel_colors = np.where(top_accel_df["가속도"] >= 0, "#16a34a", "#dc2626")
        fig_accel = go.Figure(go.Bar(
            y=top_accel_df["섹터"] + " (" + top_accel_df["Ticker"] + ")",
            x=top_accel_df["가속도"] * 100,
            orientation="h",
            marker_color=accel_colors,
            hovertemplate="%{y}<br>가속도: %{x:.1f}%p<extra></extra>"
        ))
        fig_accel.add_vline(x=0, line_color="#94a3b8")
        fig_accel.update_layout(template="plotly_dark", height=430, title="가속도 랭킹", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_accel, use_container_width=True)

    show_df = view_df.copy()
    for col in ["가격수준", "기간수익률", "1개월수익률", "3개월수익률", "6개월수익률", "가속도"]:
        show_df[col] = show_df[col].apply(fmt_flow_pct)
    show_df["현재가"] = show_df.apply(lambda r: format_currency(r["현재가"], r["Ticker"]), axis=1)
    show_df["돈흐름점수"] = show_df["돈흐름점수"].map(lambda x: f"{x:.1f}")
    st.markdown("#### 돈흐름 상세 테이블")
    st.dataframe(
        show_df[["구분", "섹터", "Ticker", "ETF 이름", "현재가", "가격수준", "기간수익률", "1개월수익률", "3개월수익률", "6개월수익률", "가속도", "돈흐름점수", "상태"]],
        use_container_width=True,
        hide_index=True,
        height=520,
    )

# -------------------------------------------------
# 3. 뉴스/리포트 로직은 stock_lab_core.news 모듈로 분리
# -------------------------------------------------
# -------------------------------------------------
# 4. 데이터 로드 (외부 의존성 제거)
# -------------------------------------------------
def cache_clear(fn):
    if fn is not None and hasattr(fn, "clear"):
        fn.clear()


def get_kst_now():
    return datetime.now(KST)


def format_kst_now():
    return get_kst_now().strftime("%Y-%m-%d %H:%M:%S")


def record_refresh_event(key):
    st.session_state[key] = format_kst_now()


def get_refresh_event_time(key):
    return st.session_state.get(key, "-")


def clear_price_and_chart_cache():
    clear_latest_price_cache()
    cache_clear(load_price_df)


def clear_news_report_cache():
    cache_clear(get_ticker_news)
    cache_clear(get_analyst_snapshot)


def clear_market_context_cache():
    cache_clear(get_macro_analysis)
    cache_clear(download_money_flow_prices)
    cache_clear(load_usdkrw_rate)


def get_market_status_label(ticker=""):
    ticker_text = str(ticker or "").upper()
    is_kr = ticker_text.endswith((".KS", ".KQ"))

    if is_kr:
        now = get_kst_now()
        minutes = now.hour * 60 + now.minute
        if now.weekday() >= 5:
            return "한국장 휴장/주말"
        if 9 * 60 <= minutes < 15 * 60 + 30:
            return "한국장 장중"
        if 8 * 60 <= minutes < 9 * 60:
            return "한국장 개장 전"
        if 15 * 60 + 30 <= minutes < 18 * 60:
            return "한국장 마감 직후"
        return "한국장 마감"

    try:
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now(timezone.utc) - timedelta(hours=5)

    minutes = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return "미국장 휴장/주말"
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "미국장 프리"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "미국장 본장"
    if 16 * 60 <= minutes < 20 * 60:
        return "미국장 애프터"
    return "미국장 마감"


def render_data_basis_caption(area, ticker="", include_news=False, include_fin=False):
    parts = [
        f"{area} 기준시각: {format_kst_now()}",
        f"시장상태: {get_market_status_label(ticker)}",
        "현재가 TTL 60초",
        "차트/기술 TTL 5분",
    ]
    if include_news:
        parts.append("뉴스 TTL 10분")
        parts.append("리포트/목표가 TTL 6시간")
    if include_fin:
        parts.append("재무점수 TTL 6시간")
    st.caption(" | ".join(parts))


def render_refresh_control_panel():
    with st.sidebar.expander("전체 새로고침 메뉴", expanded=False):
        st.caption("앱 전체 캐시 기준입니다. 빠른 것과 무거운 것을 분리했습니다.")

        if st.button("전체 현재가 새로고침", key="refresh_panel_latest_price", use_container_width=True):
            clear_latest_price_cache()
            record_refresh_event("latest_price_refresh_time")
            st.toast("현재가 캐시를 비웠습니다.")
            st.rerun()

        if st.button("전체 차트/기술 새로고침", key="refresh_panel_chart_price", use_container_width=True):
            clear_price_and_chart_cache()
            record_refresh_event("chart_price_refresh_time")
            st.toast("차트/기술 캐시를 비웠습니다.")
            st.rerun()

        if st.button("전체 뉴스/리포트 새로고침", key="refresh_panel_news_report", use_container_width=True):
            clear_news_report_cache()
            record_refresh_event("news_report_refresh_time")
            st.toast("뉴스/리포트 캐시를 비웠습니다.")
            st.rerun()

        if st.button("전체 재무점수/매크로 새로고침", key="refresh_panel_fin_macro", use_container_width=True):
            clear_financial_api_cache()
            clear_market_context_cache()
            record_refresh_event("fin_macro_refresh_time")
            st.toast("재무점수/매크로 캐시를 비웠습니다.")
            st.rerun()

        st.caption(f"현재가: {get_refresh_event_time('latest_price_refresh_time')}")
        st.caption(f"차트/기술: {get_refresh_event_time('chart_price_refresh_time')}")
        st.caption(f"뉴스/리포트: {get_refresh_event_time('news_report_refresh_time')}")
        st.caption(f"재무/매크로: {get_refresh_event_time('fin_macro_refresh_time')}")


@st.cache_data(ttl=300)
def get_macro_analysis():
    tickers = {"10Y 금리": "^TNX", "유가": "CL=F", "환율": "USDKRW=X", "MOVE": "^MOVE", "VIX": "^VIX"}
    results = {}; macro_trend = 0; storm_count = 0

    try:
        data = yf.download(
            list(tickers.values()),
            period="2mo",
            interval="1d",
            progress=False,
            group_by="ticker",
            threads=True,
            auto_adjust=False,
        )
    except Exception:
        data = pd.DataFrame()

    if data.empty:
        return results, 0, 0, 0

    for name, tkr in tickers.items():
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if tkr in data.columns.get_level_values(0):
                    ticker_df = data[tkr]
                elif tkr in data.columns.get_level_values(-1):
                    ticker_df = data.xs(tkr, axis=1, level=-1)
                else:
                    continue
            else:
                ticker_df = data

            close = ticker_df["Close"].ffill().dropna()
            if close.empty:
                continue

            cur = float(close.iloc[-1])
            prev_m = float(close.iloc[-22]) if len(close) >= 22 else float(close.iloc[0])
            if prev_m == 0:
                continue
        except Exception:
            continue

        chg = ((cur - prev_m) / prev_m) * 100
        icon = "🔺" if chg > 0.5 else ("🔻" if chg < -0.5 else "➖")
        if name in ["10Y 금리", "유가", "환율"]:
            if icon == "🔺": macro_trend += 0.5
            elif icon == "🔻": macro_trend -= 0.5
        is_storm = ((name == "VIX" and cur > 30) or (name == "환율" and cur > 1400) or (name == "10Y 금리" and cur > 4.7))
        if is_storm: storm_count += 1
        results[name] = {"val": cur, "icon": icon, "storm": is_storm}
    move_val = results.get("MOVE", {"val": 0})["val"]
    move_score = 1.5 if move_val >= 120 else (0.5 if move_val >= 100 else 0)
    final_macro_risk = storm_count + macro_trend + move_score
    macro_penalty = 2 if final_macro_risk >= 4 else (1.5 if final_macro_risk >= 2.5 else (0.5 if final_macro_risk >= 1.5 else 0))
    return results, final_macro_risk, macro_penalty, move_val

if "fin_score_map" not in st.session_state: st.session_state.fin_score_map = {}
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist_persistent()
else:
    st.session_state.watchlist = [sanitize_watchlist_item(item) for item in st.session_state.watchlist]

persist_watchlist()

# -------------------------------------------------
# 5. SMC 헬퍼 및 엔진 로직
# -------------------------------------------------
def get_pivot_highs_lows(df, l=3, r=3):
    highs, lows = [], []
    for i in range(l, len(df)-r):
        if df["High"].iloc[i] == df["High"].iloc[i-l:i+r+1].max(): highs.append((i, float(df["High"].iloc[i])))
        if df["Low"].iloc[i] == df["Low"].iloc[i-l:i+r+1].min(): lows.append((i, float(df["Low"].iloc[i])))
    return highs, lows

def get_recent_levels(df):
    ih, il = get_pivot_highs_lows(df, 3, 3)
    eh, el = get_pivot_highs_lows(df, 10, 10)
    return {
        "int_high": ih[-1][1] if ih else df["High"].tail(20).max(),
        "int_low": il[-1][1] if il else df["Low"].tail(20).min(),
        "ext_high": eh[-1][1] if eh else df["High"].tail(120).max(),
        "ext_low": el[-1][1] if el else df["Low"].tail(120).min()
    }

def detect_structure_event(df, levels):
    c_now, c_prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    ie, ee = "None", "None"
    if c_prev <= levels["int_high"] < c_now: ie = "Bullish BoS"
    elif c_prev >= levels["int_low"] > c_now: ie = "Bearish BoS"
    if c_prev <= levels["ext_high"] < c_now: ee = "Bullish BoS"
    elif c_prev >= levels["ext_low"] > c_now: ee = "Bearish BoS"
    m20, m50 = float(df["MA20"].iloc[-1]), float(df["MA50"].iloc[-1])
    if not finite_num(m20) or not finite_num(m50):
        return ie, ee
    if "Bullish" in ee and m20 < m50: ee = "Bullish CHoCH"
    if "Bearish" in ee and m20 > m50: ee = "Bearish CHoCH"
    return ie, ee

def detect_liquidity_grab(df, levels, tol=0.002):
    c, h, l = float(df["Close"].iloc[-1]), float(df["High"].iloc[-1]), float(df["Low"].iloc[-1])
    if h > levels["int_high"]*(1+tol) and c < levels["int_high"]: return "상단 유동성 청산"
    if l < levels["int_low"]*(1-tol) and c > levels["int_low"]: return "하단 유동성 청산"
    return "없음"

def detect_recent_fvg(df):
    for i in range(len(df)-1, 1, -1):
        h2, l2, h0, l0 = float(df["High"].iloc[i-2]), float(df["Low"].iloc[i-2]), float(df["High"].iloc[i]), float(df["Low"].iloc[i])
        if l0 > h2: return {"type": "Bullish FVG", "top": l0, "bottom": h2, "active": float(df["Low"].iloc[-1]) > h2}
        if h0 < l2: return {"type": "Bearish FVG", "top": l2, "bottom": h0, "active": float(df["High"].iloc[-1]) < l2}
    return {"type": "없음", "top": None, "bottom": None, "active": False}

def get_pd_zone(df):
    c, m, s = float(df["Close"].iloc[-1]), df["Close"].rolling(200).mean().iloc[-1], df["Close"].rolling(200).std().iloc[-1]
    if pd.isna(m): return "Neutral"
    if c >= m + 2*s: return "Premium"
    if c <= m - 2*s: return "Discount"
    return "Neutral"

def summarize_smc_action(ext, int_s, ie, ee, liq, fvg, pdz):
    if "CHoCH" in ee: return "구조적 반전 포착: 방향 재설정 필요"
    if liq == "상단 유동성 청산" and pdz == "Premium": return "상단 유동성 청산 후 조정 경계"
    if fvg["type"] == "Bullish FVG" and fvg["active"] and ext == "Bullish": return "상승 FVG 유지: 눌림 매수 유리"
    if ext == "Bullish": return "상승 추세 유지: 눌림 대기"
    return "구조 혼조: 관망"

def get_rs_benchmark(ticker, asset_class):
    symbol = clean_symbol(ticker)
    ac = str(asset_class).strip().lower()

    etf_market_benchmark_map = {
        "QQQ": US_BROAD_BENCHMARK,
        "QQQM": US_BROAD_BENCHMARK,
        "QLD": US_BROAD_BENCHMARK,
        "TQQQ": US_BROAD_BENCHMARK,
        "SOXX": US_BROAD_BENCHMARK,
        "SOXL": US_BROAD_BENCHMARK,
        "SMH": US_BROAD_BENCHMARK,
        "DRAM": US_BROAD_BENCHMARK,
        "SPY": US_TECH_BENCHMARK,
        "VOO": US_TECH_BENCHMARK,
        "IVV": US_TECH_BENCHMARK,
        "SPLG": US_TECH_BENCHMARK,
        "SPYM": US_TECH_BENCHMARK,
        "VTI": US_TECH_BENCHMARK,
        "379810": KR_US_SP_BENCHMARK,
        "379800": KR_US_NASDAQ_BENCHMARK,
        "069500": "^KS11",
    }
    if symbol in etf_market_benchmark_map:
        return etf_market_benchmark_map[symbol]

    if ac in ["kr_stock", "kr_etf"]: return KR_MARKET_BENCHMARK
    if is_kr_listed(ticker) and ac == "us_etf_nasdaq": return KR_US_SP_BENCHMARK
    if is_kr_listed(ticker) and ac == "us_etf_sp": return KR_US_NASDAQ_BENCHMARK
    if ac == "us_etf_nasdaq": return US_BROAD_BENCHMARK
    if ac == "us_etf_sp": return US_TECH_BENCHMARK
    if ac in ["us_stock_tech", "us_stock_growth"]: return US_TECH_BENCHMARK
    if ac == "us_stock": return US_TECH_BENCHMARK if symbol in US_TECH_OR_GROWTH_TICKERS else US_BROAD_BENCHMARK
    return US_BROAD_BENCHMARK

def get_rs_score(ticker, asset_class):
    bench = get_rs_benchmark(ticker, asset_class)
    if normalize_ticker(ticker) == normalize_ticker(bench): return 1, "➖보통"

    s_df = load_price_df(ticker, "3mo")
    b_df = load_price_df(bench, "3mo")
    need_len = RS_LOOKBACK_DAYS + 1

    if len(s_df) < need_len or len(b_df) < need_len: return 1, "➖보통"

    s_now = float(s_df["Close"].iloc[-1])
    s_then = float(s_df["Close"].iloc[-need_len])
    b_now = float(b_df["Close"].iloc[-1])
    b_then = float(b_df["Close"].iloc[-need_len])

    if s_then <= 0 or b_then <= 0 or b_now <= 0: return 1, "➖보통"

    rs_now = s_now / b_now
    rs_then = s_then / b_then

    if rs_now > rs_then * 1.03: return 2, "🚀강함"
    elif rs_now < rs_then * 0.97: return 0, "🐢약함"
    return 1, "➖보통"


BENCHMARK_LABELS = {
    "069500.KS": "KODEX 200",
    "379810.KS": "나스닥100(국내상장)",
    "379800.KS": "S&P500(국내상장)",
    "QQQM": "QQQM(나스닥100)",
    "SPY": "SPY(S&P500)",
    "^KS11": "KOSPI 종합지수",
    "SMH": "SMH(반도체)",
    "XLK": "XLK(미국 기술)",
    "XLI": "XLI(미국 산업재)",
    "XLC": "XLC(미국 커뮤니케이션)",
    "XLV": "XLV(미국 헬스케어)",
    "XLF": "XLF(미국 금융)",
    "XLE": "XLE(미국 에너지)",
    "XLY": "XLY(미국 경기소비재)",
    "XLP": "XLP(미국 필수소비재)",
    "XLB": "XLB(미국 소재)",
    "XLU": "XLU(미국 유틸리티)",
    "VNQ": "VNQ(미국 리츠/부동산)",
    "396500.KS": "한국 반도체",
    "487240.KS": "전력인프라",
    "494670.KS": "조선",
    "449450.KS": "방산",
    "305540.KS": "2차전지",
    "139260.KS": "IT/기술",
    "434730.KS": "HANARO 원자력iSelect",
    "479850.KS": "HANARO K-뷰티",
    "139250.KS": "에너지화학",
    "139270.KS": "금융",
    "244580.KS": "바이오",
    "329200.KS": "리츠/부동산",
    "139220.KS": "건설/유틸",
}

SECTOR_BENCHMARK_MAP = {
    "005930": ("396500.KS", "반도체"),
    "000660": ("396500.KS", "반도체"),
    "200710": ("396500.KS", "반도체"),
    "042700": ("396500.KS", "반도체"),
    "403870": ("396500.KS", "반도체"),
    "039030": ("396500.KS", "반도체"),
    "058470": ("396500.KS", "반도체"),
    "095340": ("396500.KS", "반도체"),
    "000990": ("396500.KS", "반도체"),
    "267260": ("487240.KS", "전력인프라"),
    "010120": ("487240.KS", "전력인프라"),
    "298040": ("487240.KS", "전력인프라"),
    "103590": ("487240.KS", "전력인프라"),
    "033100": ("487240.KS", "전력인프라"),
    "001440": ("487240.KS", "전력인프라"),
    "006260": ("487240.KS", "전력인프라"),
    "278470": ("479850.KS", "K-뷰티"),
    "090430": ("479850.KS", "K-뷰티"),
    "161890": ("479850.KS", "K-뷰티"),
    "192820": ("479850.KS", "K-뷰티"),
    "034020": ("434730.KS", "원자력"),
    "052690": ("434730.KS", "원자력"),
    "051600": ("434730.KS", "원자력"),
    "329180": ("494670.KS", "조선"),
    "009540": ("494670.KS", "조선"),
    "010140": ("494670.KS", "조선"),
    "042660": ("494670.KS", "조선"),
    "012450": ("449450.KS", "방산"),
    "047810": ("449450.KS", "방산"),
    "064350": ("449450.KS", "방산"),
    "079550": ("449450.KS", "방산"),
    "373220": ("305540.KS", "2차전지"),
    "006400": ("305540.KS", "2차전지"),
    "051910": ("305540.KS", "2차전지"),
    "003670": ("305540.KS", "2차전지"),
    "247540": ("305540.KS", "2차전지"),
    "086520": ("305540.KS", "2차전지"),
    "066970": ("305540.KS", "2차전지"),
    "MSFT": ("XLK", "미국 기술"),
    "LITE": ("XLK", "미국 기술"),
    "CIEN": ("XLK", "미국 기술"),
    "ANET": ("XLK", "미국 기술"),
    "NBIS": ("QQQM", "미국 성장/AI"),
    "VRT": ("XLI", "미국 산업재/AI인프라"),
    "TSM": ("SMH", "미국 반도체"),
    "AVGO": ("SMH", "미국 반도체"),
    "MRVL": ("SMH", "미국 반도체"),
    "MU": ("SMH", "미국 반도체"),
    "SNDK": ("SMH", "미국 반도체"),
    "AMD": ("SMH", "미국 반도체"),
    "NVDA": ("SMH", "미국 반도체"),
    "ASML": ("SMH", "미국 반도체"),
    "ARM": ("SMH", "미국 반도체"),
    "QCOM": ("SMH", "미국 반도체"),
}

SECTOR_BENCHMARK_SOURCE_ETFS = {
    "396500.KS": "반도체",
    "487240.KS": "전력인프라",
    "494670.KS": "조선",
    "449450.KS": "방산",
    "305540.KS": "2차전지",
    "139260.KS": "IT/기술",
    "434730.KS": "원자력",
    "479850.KS": "K-뷰티",
    "139250.KS": "에너지화학",
    "139270.KS": "금융",
    "244580.KS": "바이오",
    "329200.KS": "리츠/부동산",
    "139220.KS": "건설/유틸",
}

SECTOR_BENCHMARK_KEYWORD_RULES = [
    (("전력인프라", "전력기기", "전력설비", "변압", "전선", "송배전", "ELECTRIC", "일렉트릭", "효성중공업", "일진전기", "제룡전기", "대한전선"), ("487240.KS", "전력인프라")),
    (("반도체", "HBM", "DRAM", "하이닉스", "한미반도체", "HPSP", "리노공업", "이오테크닉스", "ISC", "DB하이텍"), ("396500.KS", "반도체")),
    (("2차전지", "이차전지", "배터리", "에너지솔루션", "삼성SDI", "LG화학", "포스코퓨처엠", "에코프로", "엘앤에프"), ("305540.KS", "2차전지")),
    (("원자력", "원전", "SMR", "두산에너빌리티", "한전기술", "한전KPS"), ("434730.KS", "원자력")),
    (("조선", "조선해양", "한화오션", "현대미포", "HD현대중공업", "삼성중공업"), ("494670.KS", "조선")),
    (("방산", "항공우주", "에어로스페이스", "현대로템", "LIG넥스원", "한국항공우주"), ("449450.KS", "방산")),
    (("K뷰티", "K-뷰티", "화장품", "뷰티", "에이피알", "아모레", "한국콜마", "코스맥스", "파마리서치"), ("479850.KS", "K-뷰티")),
    (("바이오", "제약", "헬스케어", "셀트리온", "삼성바이오로직스", "알테오젠", "유한양행"), ("244580.KS", "바이오")),
    (("금융", "은행", "지주", "보험", "증권", "KB금융", "신한지주", "하나금융", "메리츠금융"), ("139270.KS", "금융")),
    (("에너지", "화학", "정유", "SK이노베이션", "S-OIL", "LG화학", "롯데케미칼"), ("139250.KS", "에너지화학")),
    (("리츠", "부동산", "인프라", "맥쿼리", "롯데리츠"), ("329200.KS", "리츠/부동산")),
    (("건설", "유틸", "전기가스", "한국전력", "현대건설", "GS건설"), ("139220.KS", "건설/유틸")),
]

US_YFINANCE_SECTOR_BENCHMARKS = {
    "Technology": ("XLK", "미국 기술"),
    "Communication Services": ("XLC", "미국 커뮤니케이션"),
    "Industrials": ("XLI", "미국 산업재"),
    "Healthcare": ("XLV", "미국 헬스케어"),
    "Health Care": ("XLV", "미국 헬스케어"),
    "Financial Services": ("XLF", "미국 금융"),
    "Financial": ("XLF", "미국 금융"),
    "Energy": ("XLE", "미국 에너지"),
    "Consumer Cyclical": ("XLY", "미국 경기소비재"),
    "Consumer Defensive": ("XLP", "미국 필수소비재"),
    "Basic Materials": ("XLB", "미국 소재"),
    "Utilities": ("XLU", "미국 유틸리티"),
    "Real Estate": ("VNQ", "미국 리츠/부동산"),
}


def normalize_sector_match_text(value):
    text = strip_search_prefix(value).upper()
    return "".join(ch for ch in text if ch.isalnum())


@st.cache_data(ttl=3600, show_spinner=False)
def get_sector_benchmark_holdings_name_map():
    mapping = {}
    try:
        df = load_kr_etf_lab_dataframe()
    except Exception:
        return mapping

    if df is None or df.empty:
        return mapping

    ticker_series = df.get("ticker", pd.Series(dtype=str)).astype(str).str.upper()
    for benchmark_ticker, label in SECTOR_BENCHMARK_SOURCE_ETFS.items():
        matched = df[ticker_series == benchmark_ticker.upper()]
        if matched.empty:
            continue

        row = matched.iloc[0]
        for idx in range(1, 6):
            key = normalize_sector_match_text(row.get(f"top_{idx}", ""))
            if key:
                mapping.setdefault(key, (benchmark_ticker, label))

    return mapping


def infer_sector_benchmark_by_name(name):
    key = normalize_sector_match_text(name)
    if not key:
        return None

    holding_map = get_sector_benchmark_holdings_name_map()
    if key in holding_map:
        return holding_map[key]

    for holding_key, benchmark in holding_map.items():
        if len(holding_key) >= 3 and (holding_key in key or key in holding_key):
            return benchmark

    for keywords, benchmark in SECTOR_BENCHMARK_KEYWORD_RULES:
        for keyword in keywords:
            kw = normalize_sector_match_text(keyword)
            if kw and kw in key:
                return benchmark

    return None


def infer_us_sector_benchmark(ticker, asset_class):
    if is_kr_listed(ticker):
        return None

    ac = str(asset_class or "").strip().lower()
    if ac and "stock" not in ac and ac != "us":
        return None

    info = lookup_yfinance_info(ticker)
    sector = str(info.get("sector", "") or "").strip()
    if sector in US_YFINANCE_SECTOR_BENCHMARKS:
        return US_YFINANCE_SECTOR_BENCHMARKS[sector]

    industry = str(info.get("industry", "") or "")
    industry_key = industry.lower()
    if any(word in industry_key for word in ["semiconductor", "chip"]):
        return ("SMH", "미국 반도체")
    if any(word in industry_key for word in ["software", "information technology", "computer hardware"]):
        return ("XLK", "미국 기술")
    if any(word in industry_key for word in ["aerospace", "defense"]):
        return ("XLI", "미국 산업재")

    return None


UNDERLYING_BENCHMARK_MAP = {
    "QQQ": ("QQQM", "나스닥100"),
    "QQQM": ("QQQM", "나스닥100"),
    "QLD": ("QQQM", "나스닥100"),
    "TQQQ": ("QQQM", "나스닥100"),
    "379810": ("QQQM", "나스닥100"),
    "SOXX": ("SMH", "반도체"),
    "SOXL": ("SMH", "반도체"),
    "SMH": ("SMH", "반도체"),
    "DRAM": ("SMH", "메모리/반도체"),
    "SPY": ("SPY", "S&P500"),
    "VOO": ("SPY", "S&P500"),
    "IVV": ("SPY", "S&P500"),
    "SPLG": ("SPY", "S&P500"),
    "SPYM": ("SPY", "S&P500"),
    "VTI": ("SPY", "미국 전체시장"),
    "379800": ("SPY", "S&P500"),
    "069500": ("069500.KS", "KOSPI200"),
}


def get_benchmark_display_name(ticker):
    if not ticker:
        return "-"
    return BENCHMARK_LABELS.get(str(ticker).upper(), str(ticker).upper())


def get_underlying_benchmark_info(ticker, asset_class):
    symbol = clean_symbol(ticker)
    if symbol in UNDERLYING_BENCHMARK_MAP:
        return UNDERLYING_BENCHMARK_MAP[symbol]

    ac = str(asset_class).strip().lower()
    if ac == "us_etf_nasdaq":
        return US_TECH_BENCHMARK, "나스닥100"
    if ac == "us_etf_sp":
        return US_BROAD_BENCHMARK, "S&P500"
    if ac == "kr_etf":
        return KR_MARKET_BENCHMARK, "KOSPI200"
    return "", "-"


def get_sector_benchmark_info(ticker, asset_class, name=""):
    key = normalize_ticker(ticker)
    if key in SECTOR_BENCHMARK_MAP:
        return SECTOR_BENCHMARK_MAP[key]
    symbol = clean_symbol(ticker)
    if symbol in SECTOR_BENCHMARK_MAP:
        return SECTOR_BENCHMARK_MAP[symbol]

    us_inferred = infer_us_sector_benchmark(ticker, asset_class)
    if us_inferred:
        return us_inferred

    for candidate_name in [name, get_known_display_name(ticker, "")]:
        inferred = infer_sector_benchmark_by_name(candidate_name)
        if inferred:
            return inferred

    return "", "-"


def get_rs_score_against_benchmark(ticker, benchmark):
    if not benchmark:
        return 1, "-"
    if normalize_ticker(ticker) == normalize_ticker(benchmark):
        return 1, "➖보통"

    s_df = load_price_df(ticker, "3mo")
    b_df = load_price_df(benchmark, "3mo")
    need_len = RS_LOOKBACK_DAYS + 1

    if len(s_df) < need_len or len(b_df) < need_len:
        return 1, "➖보통"

    s_now = float(s_df["Close"].iloc[-1])
    s_then = float(s_df["Close"].iloc[-need_len])
    b_now = float(b_df["Close"].iloc[-1])
    b_then = float(b_df["Close"].iloc[-need_len])

    if s_then <= 0 or b_then <= 0 or b_now <= 0:
        return 1, "➖보통"

    rs_now = s_now / b_now
    rs_then = s_then / b_then

    if rs_now > rs_then * 1.03:
        return 2, "🚀강함"
    if rs_now < rs_then * 0.97:
        return 0, "🐢약함"
    return 1, "➖보통"

def build_indicators(df):
    df = df.copy()
    df["MA5"] = df["Close"].rolling(5).mean(); df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean(); df["MA120"] = df["Close"].rolling(120).mean()
    df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
    df["MFI"] = ta.volume.MFIIndicator(df["High"], df["Low"], df["Close"], df["Volume"]).money_flow_index()
    macd = ta.trend.MACD(df["Close"]); df["MACD"] = macd.macd(); df["MACD_Sig"] = macd.macd_signal()
    bb = ta.volatility.BollingerBands(df["Close"], 20, 2); df["%B"] = (df["Close"] - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband())
    kc = ta.volatility.KeltnerChannel(df["High"], df["Low"], df["Close"], 20, 20, 1.5)
    df["SQZ_ON"] = (bb.bollinger_hband() < kc.keltner_channel_hband()) & (bb.bollinger_lband() > kc.keltner_channel_lband())
    return df

def get_trend_label(last):
    ma20 = last.get("MA20")
    ma50 = last.get("MA50")
    ma120 = last.get("MA120")

    if not finite_num(ma20) or not finite_num(ma50) or not finite_num(ma120):
        return "🆕신규상장/자료부족"

    if ma20 > ma50 > ma120:
        return "🚀정배열(상승)"
    if ma20 > ma50:
        return "⏳혼조세"
    return "🌊역배열(하락)"

# -------------------------------------------------
# 6. 범용화 인터페이스 함수
# -------------------------------------------------
def get_sheet_current_weight(name, ticker):
    row = get_holding_row_by_ticker(holdings_table, ticker)
    if row is None: return 0.0
    return float(row.get("현재비중", 0.0) or 0.0)

def get_target_weight_from_sheet(name, ticker):
    row = get_holding_row_by_ticker(holdings_table, ticker)
    if row is None: return 0.0
    return float(row.get("목표비중", 0.0) or 0.0)

def get_my_price(name, ticker):
    row = get_holding_row_by_ticker(holdings_table, ticker)
    if row is None: return 0.0
    return float(row.get("매입가", 0.0) or 0.0)

def has_position(name, ticker):
    row = get_holding_row_by_ticker(holdings_table, ticker)
    if row is None: return False
    return float(row.get("보유량", 0.0) or 0.0) > 0

def get_effective_total_asset(mode, user_asset, sheet_eval):
    return sheet_eval if mode == "개인모드" else (float(user_asset) if user_asset > 0 else 0.0)

def get_effective_weights(mode, name, ticker, u_curr_w, u_targ_w):
    if mode == "개인모드":
        cw = get_sheet_current_weight(name, ticker)
        tw = get_target_weight_from_sheet(name, ticker)
        return cw, tw
    return float(u_curr_w), float(u_targ_w)

def get_effective_buy_amount(mode, name, ticker, eff_total, u_curr_w, u_targ_w):
    cw, tw = get_effective_weights(mode, name, ticker, u_curr_w, u_targ_w)
    return round(eff_total * (max(tw - cw, 0) / 100), 0)

# -------------------------------------------------
# 7. 기술적 분석 메인 엔진
# -------------------------------------------------
def calc_scores_and_decision(name, ticker, is_etf, asset_class, df, my_price, has_pos, fin_score, 
                             is_free=False, app_mode="개인모드", user_total_asset=0.0, user_curr_w=0.0, user_targ_w=0.0):
    last, prev, cur_p = df.iloc[-1], df.iloc[-2], float(df.iloc[-1]["Close"])
    p3m = df["Close"].iloc[-61] if len(df) >= 61 else df["Close"].iloc[0]
    p6m = df["Close"].iloc[-121] if len(df) >= 121 else df["Close"].iloc[0]
    ret_3m, ret_6m = (cur_p / p3m) - 1, (cur_p / p6m) - 1
    prev_close = float(prev["Close"]) if finite_num(prev["Close"]) else 0.0
    day_ret = (cur_p / prev_close) - 1 if prev_close > 0 else 0.0
    high_52w = df["High"].rolling(252).max().iloc[-1] if len(df) >= 252 else df["High"].max()
    current_dd = (cur_p / high_52w) - 1 if high_52w > 0 else 0.0

    short_history = len(df) < 60 or not finite_num(last["MA50"]) or not finite_num(last["MA120"])
    trend_label = get_trend_label(last)
    macd_state = get_macd_state(last["MACD"], last["MACD_Sig"], prev["MACD"], prev["MACD_Sig"])
    rt_macd_label = "📈상승추세" if last["MACD"] > prev["MACD"] else ("📉하락추세" if last["MACD"] < prev["MACD"] else "⏳관망")
    rsi_now, mfi_now, pct_b_now = float(last["RSI"]), float(last["MFI"]), float(last["%B"])
    _, rs_label = get_rs_score(ticker, asset_class)
    sqz_status = get_sqz_status(bool(last["SQZ_ON"]), bool(prev["SQZ_ON"]))

    rs_s = 2 if rs_label == "🚀강함" else (1 if rs_label == "➖보통" else 0)
    mfi_s = 2 if mfi_now < 30 else (-1 if mfi_now > 80 else 0)
    trend_s = 2 if trend_label == "🚀정배열(상승)" else 0
    macd_s = 2 if macd_state == "🔥매수신호(골든크로스)" else (1 if macd_state == "📈추세유지(상승중)" else (-2 if macd_state == "📉하락주의(데드크로스)" else 0))
    sqz_s = 1 if (sqz_status == "🚀해제직후" and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]) else 0

    tech_total = rs_s + mfi_s + trend_s + macd_s + sqz_s
    vol_ma20 = float(df["Volume"].rolling(20).mean().iloc[-1]) if pd.notna(df["Volume"].rolling(20).mean().iloc[-1]) else 1
    vol_ratio = float(last["Volume"]) / vol_ma20 if vol_ma20 > 0 else 0
    ma20_now = float(last["MA20"]) if finite_num(last["MA20"]) else 0.0
    ma50_now = float(last["MA50"]) if finite_num(last["MA50"]) else 0.0
    below_ma20 = ma20_now > 0 and cur_p < ma20_now * 0.98
    below_ma50 = ma50_now > 0 and cur_p < ma50_now
    is_single_day_breakdown = (not is_etf) and day_ret <= -0.06 and vol_ratio >= 1.2

    main_score = (
        (2 if trend_label == "🚀정배열(상승)" else (1 if trend_label == "⏳혼조세" else 0)) +
        (2 if macd_state == "🔥매수신호(골든크로스)" else 0) +
        (2 if rsi_now < 35 else (1 if rsi_now < 45 else 0)) +
        (1 if vol_ratio > 1.2 else 0)
    )
    adj_tech_score = (main_score + rs_s + mfi_s) - macro_penalty

    if is_etf:
        t_score = tech_total
        if tech_total < 1: grade = "⏳ETF 관망"
        elif tech_total < 3: grade = "⚖️ETF 보통"
        elif tech_total < 5: grade = "✅ETF 양호"
        else: grade = "💎ETF 우수"
    else:
        t_score = tech_total + fin_score
        if fin_score == 1: grade = "🚨F급 (재무위험/처분)"
        elif t_score < 3: grade = "🚨F급 (기술/재무 부진)"
        elif t_score < 5: grade = "⏳C급 (주의/대기)"
        elif t_score < 7: grade = "⚖️B급 (신중/관망)"
        elif t_score < 9: grade = "✅A급 (분할 매수)"
        else: grade = "💎S급 (강력 매수)"

    levels = get_recent_levels(df)
    ext_structure = "Bullish" if trend_label == "🚀정배열(상승)" else ("Bearish" if trend_label == "🌊역배열(하락)" else "Neutral")

    int_structure = (
        "Bullish" if rs_label == "🚀강함" and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]
        else ("Bearish" if trend_label == "🌊역배열(하락)" or rs_label == "🐢약함" else "Mixed")
    )

    int_event, ext_event = detect_structure_event(df, levels)
    liq_state = detect_liquidity_grab(df, levels)
    fvg_info = detect_recent_fvg(df)
    pd_zone = get_pd_zone(df)
    smc_action = summarize_smc_action(ext_structure, int_structure, int_event, ext_event, liq_state, fvg_info, pd_zone)

    if rsi_now <= 30: smc_insight = "과매도 극단. 유동성 청산 후 구조적 반등(CHoCH) 여부 관찰."
    elif mfi_now >= 80: smc_insight = "스마트머니 익절 가능성이 높은 단기 과열 구간."
    elif trend_label == "🆕신규상장/자료부족": smc_insight = "상장 초기라 MA50/MA120 기반 추세 판정은 보류. 단기 흐름과 거래량만 참고."
    elif 0.45 < pct_b_now < 0.8 and sqz_status == "🚀해제직후": smc_insight = "응축 후 발산 초기. 모멘텀 실리는 타점 구간."
    elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함": smc_insight = "구조적 상승(BoS) 진행 중. MA20 눌림 여부 확인 필요."
    elif trend_label == "🌊역배열(하락)": smc_insight = "하락 구조 우세. 추세 전환 전까지 보수적 접근 권장."
    else: smc_insight = "주요 매물대(FVG/Order Block) 소화 중. 방향성 확정 대기."

    eff_total = get_effective_total_asset(app_mode, user_total_asset, total_eval)
    curr_w, targ_w = get_effective_weights(app_mode, name, ticker, user_curr_w, user_targ_w)
    buy_amount = get_effective_buy_amount(app_mode, name, ticker, eff_total, user_curr_w, user_targ_w)
                                 
    price_vs_avg = ((cur_p / my_price) - 1) if my_price > 0 else 0.0
    weight_gap = targ_w - curr_w


    is_stock_add_on_strength = (
        (not is_etf) and
        has_pos and
        my_price > 0 and
        targ_w > 0 and
        weight_gap >= 2 and
        0.00 < price_vs_avg <= 0.05 and
        trend_label in ["🚀정배열(상승)", "⏳혼조세"] and
        rs_label in ["🚀강함", "➖보통"] and
        last["MACD"] > prev["MACD"] and
        mfi_now < 80 and
        rsi_now < 70 and
        pct_b_now < 1.00 and
        vol_ratio < 2.5 and
        final_macro_risk < 4.5
    )
                             
    is_early_entry = (trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and last["MACD"] > prev["MACD"] and 
                      macd_state in ["📉하락주의(데드크로스)", "⏳추세관망"] and mfi_now < 80 and pct_b_now < 0.85 and 50 <= rsi_now <= 65 and adj_tech_score >= 4.0)
    is_breakout_extreme = (not is_etf) and fin_score == 4 and adj_tech_score >= 4.0 and pct_b_now > 1.02 and rs_label == "🚀강함"
    is_breakout_normal = (not is_etf) and fin_score == 4 and adj_tech_score >= 4.0 and 0.95 <= pct_b_now <= 1.02 and rs_label == "🚀강함"

    # -------------------------------
    # 예외 승인 프로세스 (정교화된 로직 적용)
    # -------------------------------
    ma5_now = float(last["MA5"]) if pd.notna(last["MA5"]) else 0.0
    low_now = float(last["Low"])

    is_leader_base = (
        (not is_etf) and
        fin_score == 4 and
        trend_label == "🚀정배열(상승)" and
        rs_label == "🚀강함" and
        macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"] and
        adj_tech_score >= 4.0
    )

    ma5_gap = ((cur_p - ma5_now) / ma5_now) if ma5_now > 0 else np.nan

    is_ma5_pullback = (
        ma5_now > 0 and
        low_now <= ma5_now * 1.01 and
        cur_p <= ma5_now * 1.025 and
        (not finite_num(ma5_gap) or ma5_gap >= -0.02)
    )

    is_bullish_fvg_pullback = (
        fvg_info["type"] == "Bullish FVG" and
        fvg_info["bottom"] is not None and
        fvg_info["top"] is not None and
        float(fvg_info["bottom"]) * 0.995 <= cur_p <= float(fvg_info["top"]) * 1.01
    )

    is_exception_not_chasing = (
        mfi_now < 82 and
        pct_b_now < 1.00 and
        rsi_now < 70 and
        vol_ratio < 2.5
    )

    is_exception_entry = (
        is_leader_base and
        (is_ma5_pullback or is_bullish_fvg_pullback) and
        is_exception_not_chasing
    )

    is_structure_damage_entry_risk = (
        (not is_etf) and
        (not short_history) and
        (
            current_dd <= -0.15 or
            below_ma50 or
            (below_ma20 and rs_label != "🚀강함") or
            is_single_day_breakdown
        )
    )

    is_clean_leader_entry = (
        (not is_etf) and
        adj_tech_score >= 4.5 and
        rs_label == "🚀강함" and
        trend_label == "🚀정배열(상승)" and
        day_ret > -0.04 and
        current_dd > -0.15 and
        (ma20_now <= 0 or cur_p >= ma20_now * 0.98) and
        not is_structure_damage_entry_risk
    )
 
    is_etf_accumulation_ok = (
        is_etf and
        has_pos and
        targ_w > 0 and
        weight_gap >= 3 and
        (trend_label != "🌊역배열(하락)" or weight_gap >= 10) and
        mfi_now < 85 and
        rsi_now < 75 and
        pct_b_now < 1.03 and
        final_macro_risk < 4.5
    )

    if is_free:
        if is_etf and short_history: dec, col = "🆕신규ETF: 데이터 축적 대기", "#64748b"
        elif mfi_now >= 85: dec, col = "🚫극단과열: 추격금지", "#dc2626"
        elif is_breakout_extreme: dec, col = "⚠️과열확장: 추격금지, MA5 대기", "#d97706"
        elif is_breakout_normal: dec, col = "🔥불뿜는 대장주: 초단기 눌림(MA5) 진입", "#ec4899"
        elif pct_b_now >= 0.95: dec, col = "⚠️밴드상단: 눌림 대기", "#d97706"
        elif current_dd <= -0.2: dec, col = "🚨위기/패닉: 투매 포착", "#dc2626"
        elif is_structure_damage_entry_risk: dec, col = "⚠️구조훼손: 신규진입 보류", "#d97706"
        elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
        elif rsi_now <= 30: dec, col = "🔥낙폭과대: 신규 진입", "#16a34a"
        elif is_early_entry: dec, col = "🟢선진입 가능 구간", "#16a34a"
        elif is_clean_leader_entry: dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
        elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5: dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
        elif ret_3m < 0 and trend_label in ["🌊역배열(하락)", "⏳혼조세"]: dec, col = "⚠️하락추세: 진입보류", "#dc2626"
        elif trend_label == "🌊역배열(하락)": dec, col = "🚫역배열: 진입 보류", "#dc2626"
        else: dec, col = "🔍관망: 타점 대기", "#64748b"
    else:
        if not is_etf and fin_score <= 1:
            dec, col = "🚨하드차단: 재무F급(처분)", "#dc2626"
        elif is_etf and short_history:
            dec, col = "🆕신규ETF: 데이터 축적 대기", "#64748b"
        elif curr_w > targ_w and targ_w > 0: dec, col = "🛑하드차단: 비중 초과", "#dc2626"
        elif curr_w >= targ_w and targ_w > 0: dec, col = "⏸️하드차단: 비중 충족(관망)", "#d97706"
        elif current_dd <= -0.5: dec, col = "💣패닉(-50%↓): 최종투입", "#7f1d1d"
        elif current_dd <= -0.4: dec, col = "💣패닉(-40%↓): 현금 투입", "#991b1b"
        elif current_dd <= -0.3: dec, col = "🚨위기(-30%↓): 코어 집중", "#b91c1c"
        elif is_structure_damage_entry_risk and not has_pos:
            dec, col = "⚠️구조훼손: 신규진입 보류", "#d97706"
        elif current_dd <= -0.2 and has_pos and is_structure_damage_entry_risk:
            dec, col = "⚠️고점대비 -20%: 추매금지/손절기준 점검", "#d97706"
        elif current_dd <= -0.2 and has_pos:
            dec, col = "⚠️고점대비 -20%: 추매금지/원인점검", "#d97706"
        elif current_dd <= -0.2:
            dec, col = "⚠️고점대비 -20%: 신규진입 보류", "#d97706"
        
        elif final_macro_risk >= 4.5:
            dec, col = "🛑하드차단: 퍼펙트스톰(대피)", "#dc2626"
        elif is_structure_damage_entry_risk and has_pos:
            dec, col = "⚠️구조훼손: 추매금지/손절기준 점검", "#d97706"
        elif is_structure_damage_entry_risk:
            dec, col = "⚠️구조훼손: 신규진입 보류", "#d97706"
        elif (
            is_exception_entry and
            has_pos and
            my_price > 0 and
            cur_p <= my_price * 1.02 and
            targ_w > 0 and
            curr_w < targ_w
        ):
            dec, col = "🟣예외승인: 정찰대 추매(MA5/FVG)", "#7c3aed"
        elif is_exception_entry and (not has_pos):
            dec, col = "🟣예외승인: 정찰대 진입(MA5/FVG)", "#7c3aed"

        elif mfi_now >= 85: dec, col = "🚫하드차단: MFI 극단 과열", "#dc2626"
        elif is_breakout_extreme: dec, col = "⚠️과열확장: 추격금지, MA5 대기", "#d97706"
        elif is_breakout_normal: dec, col = "🔥불뿜는 대장주: MA5 눌림 진입", "#ec4899"
        elif (not is_etf) and pct_b_now >= 0.95:
            dec, col = "🚫하드차단: 볼린상단 이탈", "#dc2626"
        elif is_etf_accumulation_ok and weight_gap >= 10:
            dec, col = "✅ETF 비중부족 큼: 소액 적립 허용", "#16a34a"
        elif is_etf_accumulation_ok:
            dec, col = "✅ETF 목표비중 미달: 적립식 매수 가능", "#16a34a"
        elif is_stock_add_on_strength:
            dec, col = "✅상승확인: 2차 정찰 추매 가능", "#16a34a"    
        elif has_pos and my_price > 0 and cur_p > my_price * 1.02:
            dec, col = "⏳평단이상: 추매 대기(보유)", "#d97706"
        elif has_pos:
            if trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 추매", "#8b5cf6"
            elif mfi_now >= 80: dec, col = "⚠️단기과열: 추매 보류", "#d97706"
            elif rsi_now <= 30: dec, col = "🔥낙폭과대: 줍줍 찬스", "#16a34a"
            elif rs_label == "🚀강함" and mfi_now < 35: dec, col = "💎S급: 과매도(풀매수)", "#16a34a"
            elif adj_tech_score >= 4 and cur_p <= my_price: dec, col = "🎯A급: 기술적 반등", "#16a34a"
            elif (trend_label == "🚀정배열(상승)" and pct_b_now < 0.8 and rsi_now < 60 and price_vs_avg <= -0.03 and price_vs_avg > -0.15 and curr_w < targ_w): dec, col = "📈정배열: -3% 이상 눌림 분할매수", "#16a34a"
            elif cur_p > my_price: dec, col = "⏳평단이상: 하락대기(보유)", "#d97706"
            elif cur_p <= my_price:
                if curr_w >= targ_w and targ_w > 0:
                    dec, col = "⏸️평단이하: 비중 충족(추매 보류)", "#d97706"
                elif price_vs_avg > -0.03:
                    dec, col = "⏳평단근처: 추가 하락 대기", "#64748b"
                elif price_vs_avg >= -0.07 and trend_label != "🌊역배열(하락)" and mfi_now < 80:
                    dec, col = "✅평단 -3~-7%: 소액 분할매수", "#16a34a"
                elif price_vs_avg >= -0.15 and fin_score >= 3 and final_macro_risk < 4.5:
                    dec, col = "🎯평단 -7~-15%: 조건부 분할매수", "#8b5cf6"
                else: 
                    dec, col = "🚫평단 -15%↓/추세위험: 원인 점검", "#dc2626"
            else: dec, col = "⏳보유중(신호대기)", "#64748b"
        else:
            if 0.85 <= pct_b_now < 0.95: dec, col = "⚠️상단부근: 눌림 대기", "#d97706"
            elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
            elif mfi_now >= 80: dec, col = "⚠️단기과열: 진입 보류", "#d97706"
            elif rsi_now <= 30: dec, col = "🔥낙폭과대: 신규 진입", "#16a34a"
            elif is_early_entry: dec, col = "🟢선진입 가능: 반전 초입", "#16a34a"
            elif is_clean_leader_entry: dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
            elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5: dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
            elif ret_3m < 0 and trend_label in ["🌊역배열(하락)", "⏳혼조세"]: dec, col = "⚠️하락추세: 진입보류", "#dc2626"
            elif trend_label == "🌊역배열(하락)": dec, col = "🚫진입보류: 역배열 대기", "#dc2626"
            else: dec, col = "🔍대기: 신규 타점 탐색", "#64748b"

    return {
        "cur_p": cur_p, "rsi": rsi_now, "mfi": mfi_now, "pct_b": pct_b_now, "rs_label": rs_label, "adj": adj_tech_score, "dec": dec, "col": col,
        "grade": grade, "t_score": tech_total + (0 if is_etf else fin_score), "tech_total": tech_total, "fin_score": fin_score,
        "dd": current_dd, "ret_3m": ret_3m, "ret_6m": ret_6m, "target_w": targ_w, "current_w": curr_w, "buy_amt": buy_amount,
        "day_ret": day_ret, "vol_ratio": vol_ratio, "structure_risk": is_structure_damage_entry_risk,
        "ext_structure": ext_structure, "int_structure": int_structure, "pd_zone": pd_zone, "smc_action": smc_action,
        "ma5": last["MA5"], "ma20": last["MA20"], "ma50": last["MA50"], "ma120": last["MA120"], "sqz": sqz_status, "macd": macd_state, "rt_macd": rt_macd_label,
        "trend": trend_label, "fvg_type": fvg_info["type"], "fvg_active": fvg_info["active"], "fvg_top": fvg_info["top"], "fvg_bottom": fvg_info["bottom"],
        "liq_state": liq_state, "int_event": int_event, "ext_event": ext_event, 
        "main_s": main_score, "rs_s": rs_s, "mfi_s": mfi_s, 
        "trend_s": trend_s, "macd_s": macd_s, "sqz_s": sqz_s, 
        "smc_insight": smc_insight
    }

TICKER_MAP = {
    "나스닥": ("379810.KS", True, "us_etf_nasdaq"), "QQQM": ("QQQM", True, "us_etf_nasdaq"), "QLD": ("QLD", True, "us_etf_nasdaq"), "TQQQ": ("TQQQ", True, "us_etf_nasdaq"),
    "DRAM": ("DRAM", True, "us_etf_nasdaq"),
    "s&p500": ("379800.KS", True, "us_etf_sp"), "다우존스": ("458730.KS", True, "us_etf_sp"), "kodex 200": ("069500.KS", True, "kr_etf"),
    "MSFT": ("MSFT", False, "us_stock"), "네비우스": ("NBIS", False, "us_stock"), "시에나": ("CIEN", False, "us_stock"), "아리스타 네트웍스": ("ANET", False, "us_stock"),
    "샌디스크": ("SNDK", False, "us_stock"), "TSM": ("TSM", False, "us_stock"), "브로드컴": ("AVGO", False, "us_stock"), "MRVL": ("MRVL", False, "us_stock"),
    "버티브홀딩스": ("VRT", False, "us_stock"), "마이크론": ("MU", False, "us_stock"), "삼성전자": ("005930.KS", False, "kr_stock"),
    "두산에너빌리티": ("034020.KS", False, "kr_stock"), "하이닉스": ("000660.KS", False, "kr_stock"), "한화에어로스페이스": ("012450.KS", False, "kr_stock"),
    "HD현대중공업": ("329180.KS", False, "kr_stock"), "에이피알": ("278470.KS", False, "kr_stock"), "HD현대일렉트릭": ("267260.KS", False, "kr_stock"),
    "LS ELECTRIC": ("010120.KS", False, "kr_stock"), "LS일렉트릭": ("010120.KS", False, "kr_stock"),
    "에이디테크놀러지": ("200710.KQ", False, "kr_stock"), "SPYM": ("SPYM", True, "us_etf_sp"),
}

FREE_SEARCH_OPTION = "🆓 자유 종목 탐색 (티커 입력)"


def build_precision_select_options():
    options = [FREE_SEARCH_OPTION]
    option_map = {FREE_SEARCH_OPTION: {"type": "free"}}
    seen_labels = set(options)

    for item in st.session_state.get("watchlist", []):
        item = sanitize_watchlist_item(item)
        ticker = item.get("ticker", "")
        if not ticker:
            continue

        name = sanitize_asset_name(item.get("name", ticker), ticker)
        label = f"⭐ {name} ({ticker})"
        base_label = label
        suffix = 2
        while label in seen_labels:
            label = f"{base_label} #{suffix}"
            suffix += 1

        options.append(label)
        seen_labels.add(label)
        option_map[label] = {"type": "watchlist", "item": dict(item)}

    for label in TICKER_MAP.keys():
        if label in seen_labels:
            continue
        options.append(label)
        seen_labels.add(label)
        option_map[label] = {"type": "preset"}

    return options, option_map


def find_precision_select_label_by_ticker(ticker, option_map):
    target = normalize_ticker(ticker)
    if not target:
        return None

    for label, meta in option_map.items():
        if meta.get("type") != "watchlist":
            continue
        item = meta.get("item", {})
        if normalize_ticker(item.get("ticker", "")) == target:
            return label

    for label, meta in option_map.items():
        if meta.get("type") == "free":
            continue
        if label in TICKER_MAP and normalize_ticker(TICKER_MAP[label][0]) == target:
            return label
        if normalize_ticker(label) == target:
            return label

    return None


def get_saved_fin_score_fast(ticker, is_etf):
    if is_etf: return 0
    key = normalize_ticker(ticker)
    if key in st.session_state.fin_score_map: return int(st.session_state.fin_score_map[key])

    fin_scores_df = load_fin_scores_db()
    matched = fin_scores_df[fin_scores_df["ticker"] == key]

    if not matched.empty:
        row = matched.iloc[0]
        if pd.notna(row["final_score"]):
            score = int(row["final_score"])
            st.session_state.fin_score_map[key] = score
            return score

    return 3


def get_dashboard_market_label(ticker):
    return "한국" if str(ticker).upper().endswith((".KS", ".KQ")) else "미국"


def get_dashboard_type_label(is_etf):
    return "ETF" if clean_bool(is_etf) else "개별주"


def get_dashboard_group_label(ticker, is_etf):
    return f"{get_dashboard_market_label(ticker)} {get_dashboard_type_label(is_etf)}"


def get_dashboard_swing_status_maps():
    swing_df, _ = load_swing_radar_db_safe()
    status_map = {}
    decision_map = {}

    if swing_df is None or swing_df.empty:
        return status_map, decision_map

    for _, row in swing_df.iterrows():
        key = normalize_ticker(row.get("ticker", ""))
        if not key:
            continue
        status_map[key] = str(row.get("status", "") or "").strip() or "-"
        decision_map[key] = str(row.get("decision", "") or "").strip() or "-"

    return status_map, decision_map


def render_dashboard_group_summary(df, group_label):
    if group_label != "전체":
        view_df = df[df["전광판그룹"] == group_label].copy()
    else:
        view_df = df.copy()

    if view_df.empty:
        st.info(f"{group_label}에 표시할 종목이 없습니다.")
        return

    adj = pd.to_numeric(view_df["Adj점수"], errors="coerce")
    signal_text = view_df["🔥기술적 타점"].astype(str)
    buyish_count = signal_text.str.contains("매수|진입|추매|눌림|대장주|정찰|적립", na=False).sum()
    caution_count = signal_text.str.contains("차단|금지|위기|패닉|역배열|하락|주의", na=False).sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("표시 종목", f"{len(view_df)}개")
    m2.metric("평균 ADJ", "-" if adj.dropna().empty else f"{adj.mean():.1f}")
    m3.metric("매수/관심 신호", f"{buyish_count}개")
    m4.metric("차단/주의 신호", f"{caution_count}개")

    if "ETF" in group_label:
        show_cols = [
            "시장", "유형", "종목명", "티커", "현재가", "MDD",
            "📌후보등급", "RS", "시장벤치", "기초자산", "기초벤치", "RSI", "MFI", "볼린저 %B",
            "스윙상태", "내결정", "🔥기술적 타점", "Adj점수"
        ]
    elif "개별주" in group_label:
        show_cols = [
            "시장", "유형", "종목명", "티커", "현재가", "MDD", "재무점수",
            "📌후보등급", "RS", "시장벤치", "섹터RS", "섹터벤치",
            "스윙상태", "내결정", "🔥기술적 타점", "Adj점수"
        ]
    else:
        show_cols = [
            "시장", "유형", "종목명", "티커", "현재가", "MDD", "재무점수",
            "📌후보등급", "RS", "시장벤치", "기초자산", "기초벤치", "섹터RS", "섹터벤치",
            "스윙상태", "내결정", "🔥기술적 타점", "Adj점수"
        ]
    st.dataframe(view_df[[c for c in show_cols if c in view_df.columns]], use_container_width=True, height=640, hide_index=True)


def render_personal_stock_analysis_panel(name, ticker, is_etf, asset_class, c, fin_score, fin_meta, has_pos, my_price):
    st.markdown("### 🧭 개인 주식분석")
    st.caption("스윙 신호를 장기 보유 후보로 바꿔도 되는지 점검하는 보조 패널입니다. 투자 권유가 아니라 의사결정 체크리스트입니다.")

    cur_p = clean_float(c.get("cur_p"), 0.0)
    my_price = clean_float(my_price, 0.0)
    price_vs_avg = (cur_p / my_price - 1) if has_pos and my_price > 0 else np.nan
    structure_risk = bool(c.get("structure_risk"))
    dd = clean_float(c.get("dd"), 0.0)
    ret_3m = clean_float(c.get("ret_3m"), 0.0)
    ret_6m = clean_float(c.get("ret_6m"), 0.0)
    trend = str(c.get("trend", ""))
    rs_label = str(c.get("rs_label", ""))
    decision = str(c.get("dec", ""))

    if is_etf:
        suitability_score = 0
        suitability_score += 1 if "🚀" in rs_label or "➖" in rs_label else 0
        suitability_score += 1 if "역배열" not in trend else 0
        suitability_score += 1 if dd > -0.2 else 0
        suitability_score += 1 if ret_3m >= -0.03 else 0
        suitability_score += 1 if not structure_risk else 0
    else:
        suitability_score = 0
        suitability_score += 2 if int(fin_score) >= 4 else (1 if int(fin_score) >= 3 else 0)
        suitability_score += 1 if "역배열" not in trend else 0
        suitability_score += 1 if "🚀" in rs_label or "➖" in rs_label else 0
        suitability_score += 1 if not structure_risk else 0
        suitability_score += 1 if dd > -0.2 else 0

    suitability_score = min(int(suitability_score), 5)
    if suitability_score >= 4:
        long_label, long_color = "장기 후보", "#16a34a"
    elif suitability_score >= 3:
        long_label, long_color = "조건부 장기 후보", "#d97706"
    else:
        long_label, long_color = "스윙/관망 우선", "#64748b"

    if not has_pos:
        position_label = "미보유"
        position_note = "신규 매수는 구조훼손/과열 해소 후 검토"
    elif structure_risk or dd <= -0.2:
        position_label = "보유 점검"
        position_note = "추매 금지, 손절/장투 기준 재확인"
    elif clean_float(c.get("current_w"), 0.0) >= clean_float(c.get("target_w"), 0.0) > 0:
        position_label = "비중 충족"
        position_note = "추가매수보다 보유/리스크 관리 우선"
    else:
        position_label = "보유 가능"
        position_note = "시스템 신호와 목표비중 안에서만 분할 접근"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("장기 적합도", f"{suitability_score}/5", long_label)
    m2.metric("내 손익률", "-" if not finite_num(price_vs_avg) else f"{price_vs_avg * 100:.1f}%")
    m3.metric("고점대비 MDD", f"{dd * 100:.1f}%")
    m4.metric("포지션 판단", position_label)

    rows = [
        {
            "점검항목": "핵심 결론",
            "상태": long_label,
            "해석": f"{escape_html_value(name)}({escape_html_value(ticker)})는 현재 {long_label}입니다. {position_note}",
        },
        {
            "점검항목": "재무/기초체력",
            "상태": "ETF 해당없음" if is_etf else f"{fin_score}/4",
            "해석": "ETF는 재무점수보다 기초지수/돈흐름 중심으로 봅니다." if is_etf else ("장기 보유 후보로 볼 수 있는 점수입니다." if int(fin_score) >= 3 else "장기 보유 전 재무 훼손 여부를 먼저 확인해야 합니다."),
        },
        {
            "점검항목": "추세/상대강도",
            "상태": f"{trend} / {rs_label}",
            "해석": f"3개월 {ret_3m * 100:.1f}%, 6개월 {ret_6m * 100:.1f}%입니다.",
        },
        {
            "점검항목": "구조위험",
            "상태": "주의" if structure_risk else "정상",
            "해석": "구조훼손 구간에서는 신규/추매보다 원인 점검이 우선입니다." if structure_risk else "기술 구조상 즉시 하드 경고는 없습니다.",
        },
        {
            "점검항목": "현재 시스템 신호",
            "상태": decision,
            "해석": "앱 판정 문구입니다. 장기 전환은 이 신호와 재무/뉴스/비중을 함께 봅니다.",
        },
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("장기 전환 체크리스트", expanded=False):
        checklist_rows = [
            {"구분": "장기 전환 가능", "조건": "재무 3점 이상, 추세 훼손 제한적, 투자 아이디어가 실적/수요로 설명 가능"},
            {"구분": "추매 금지", "조건": "고점대비 -20% 이하, MA50 이탈, RS 약화, 급락+거래량 증가"},
            {"구분": "손절/축소 점검", "조건": "처음 산 이유가 사라짐, 실적/가이던스 훼손, 손실 한도 초과"},
            {"구분": "다시 매수 검토", "조건": "MA20/MA50 회복, RS 회복, 과열 해소 후 거래량 동반 반등"},
        ]
        st.dataframe(pd.DataFrame(checklist_rows), use_container_width=True, hide_index=True)


def get_all_summary(fin_score_map_items, mode, watchlist_items):
    swing_status_map, swing_decision_map = get_dashboard_swing_status_maps()
    rows = []
    for item in watchlist_items:
        tkr = sanitize_ticker_value(item.get("ticker", ""))
        name = sanitize_asset_name(item.get("name", ""), tkr)
        if not tkr:
            continue
        is_etf = is_fin_score_exempt_asset(tkr, item.get("is_etf", False), item.get("asset_class", ""), name)
        a_class = infer_asset_class_for_ticker(tkr, item.get("asset_class", "")) if is_etf else item.get("asset_class", "")

        df = load_price_df(tkr, "1y")
        if df.empty: continue
        df = build_indicators(df)

        final_fin_score, _ = load_fin_score_meta_fast(tkr, is_etf)
        f_score = int(final_fin_score)
        st.session_state.fin_score_map[normalize_ticker(tkr)] = f_score

        my_p = get_my_price(name, tkr)
        has_p = has_position(name, tkr)

        c = calc_scores_and_decision(
            name=name, ticker=tkr, is_etf=is_etf, asset_class=a_class, df=df,
            my_price=my_p, has_pos=has_p, fin_score=f_score, is_free=False, app_mode=mode
        )

        market_bench = get_rs_benchmark(tkr, a_class)
        underlying_bench, underlying_asset = get_underlying_benchmark_info(tkr, a_class) if is_etf else ("", "-")
        sector_bench, _ = get_sector_benchmark_info(tkr, a_class, name)
        _, sector_rs_label = get_rs_score_against_benchmark(tkr, sector_bench)
        swing_key = normalize_ticker(tkr)

        rows.append({
            "시장": get_dashboard_market_label(tkr), "유형": get_dashboard_type_label(is_etf),
            "전광판그룹": get_dashboard_group_label(tkr, is_etf),
            "종목명": name, "티커": tkr, "현재가": format_currency(c["cur_p"], tkr), "MDD": f"{c['dd']*100:.1f}%",
            "재무점수": "해당없음" if is_etf else f"{f_score}/4", "📌후보등급": c["grade"], "RS": c["rs_label"],
            "시장벤치": get_benchmark_display_name(market_bench),
            "기초자산": underlying_asset if underlying_bench else "-",
            "기초벤치": get_benchmark_display_name(underlying_bench) if underlying_bench else "-",
            "섹터벤치": get_benchmark_display_name(sector_bench) if sector_bench else "-",
            "섹터RS": sector_rs_label if sector_bench else "-",
            "스윙상태": swing_status_map.get(swing_key, "-"),
            "내결정": swing_decision_map.get(swing_key, "-"),
            "RSI": round(c["rsi"], 1), "MFI": round(c["mfi"], 1), "볼린저 %B": round(c["pct_b"], 2),
            "🔥기술적 타점": c["dec"], "Adj점수": round(c["adj"], 1)
        })

    return pd.DataFrame(rows)


SWING_TEMPLATE_MAP = {
    "267260": {
        "idea": "전력기기 슈퍼사이클, 북미 전력망 투자, 수주/마진 성장 모멘텀",
        "check_1": "수주잔고와 신규수주 흐름이 유지되는지",
        "check_2": "영업이익률이 둔화되지 않는지",
        "check_3": "전력 인프라/변압기 수요 뉴스가 계속 나오는지",
        "risk_1": "실적 쇼크 또는 마진 둔화",
        "risk_2": "수주 피크아웃 우려",
        "risk_3": "고밸류 구간에서 장기 이평선 이탈",
        "entry_rule": "시스템 승인 + 과열 해소 + 목표비중 미달",
        "exit_rule": "시스템 차단, 추세 훼손, 실적/마진 둔화 확인",
        "next_event": "분기 실적/수주 업데이트",
    },
    "278470": {
        "idea": "뷰티 디바이스/화장품 성장, 해외 확장, 실적 모멘텀",
        "check_1": "해외 매출 성장률이 유지되는지",
        "check_2": "영업이익률과 마케팅비 부담이 관리되는지",
        "check_3": "신제품/채널 확장 뉴스가 이어지는지",
        "risk_1": "성장률 둔화",
        "risk_2": "밸류 부담과 수급 이탈",
        "risk_3": "보호예수/대주주/경쟁 심화 이슈",
        "entry_rule": "시스템 승인 + 눌림목 + 과열 신호 해소",
        "exit_rule": "시스템 차단, 추세 훼손, 성장률 둔화 확인",
        "next_event": "분기 실적/해외 매출 업데이트",
    },
}


DEFAULT_SWING_TEMPLATE = {
    "idea": "시스템 승인 기반 단기/중기 스윙 후보",
    "check_1": "실적 또는 가이던스가 훼손되지 않는지",
    "check_2": "섹터 돈흐름과 상대강도가 유지되는지",
    "check_3": "추세와 수급이 급격히 꺾이지 않는지",
    "risk_1": "실적 쇼크 또는 주요 뉴스 악화",
    "risk_2": "MFI 과열 뒤 수급 이탈",
    "risk_3": "MA50/MA120 등 주요 추세선 이탈",
    "entry_rule": "시스템 승인 + 목표비중 미달 + 과열 해소",
    "exit_rule": "시스템 차단, 추세 훼손, 투자 아이디어 무효화",
    "next_event": "다음 실적/주요 뉴스 확인",
}


DEFAULT_SWING_ETF_TEMPLATE = {
    "idea": "섹터/지수 흐름 기반 ETF 스윙 후보",
    "check_1": "돈흐름 레이더에서 해당 ETF나 관련 섹터 흐름이 유지되는지",
    "check_2": "시장벤치 대비 RS가 약해지지 않는지",
    "check_3": "MFI/RSI 과열 뒤 수급 이탈이 나오지 않는지",
    "risk_1": "기초지수 추세 훼손",
    "risk_2": "레버리지/테마 ETF의 변동성 확대",
    "risk_3": "매크로 리스크 상승 또는 금리/환율 급변",
    "entry_rule": "돈흐름 우호 + 시스템 승인 + 과열 해소",
    "exit_rule": "시스템 차단, 기초지수 추세 훼손, 돈흐름 둔화",
    "next_event": "돈흐름 레이더/시장벤치 RS 주간 확인",
}


def get_swing_template(ticker, is_etf=False, asset_class=""):
    key = normalize_ticker(ticker)
    if key in SWING_TEMPLATE_MAP:
        return dict(SWING_TEMPLATE_MAP[key])
    if is_fin_score_exempt_asset(ticker, is_etf, asset_class):
        return dict(DEFAULT_SWING_ETF_TEMPLATE)
    return dict(DEFAULT_SWING_TEMPLATE)


def make_swing_candidate_row(name, ticker, asset_class="", is_etf=False):
    template = get_swing_template(ticker, is_etf=is_etf, asset_class=asset_class)
    row = {col: "" for col in SWING_RADAR_COLUMNS}
    row.update(template)
    row.update({
        "ticker": str(ticker).strip(),
        "name": str(name or ticker).strip(),
        "asset_class": str(asset_class or "").strip(),
        "status": "진행",
        "decision": "관망",
        "importance": "중",
        "last_checked": pd.Timestamp.today().strftime("%Y-%m-%d"),
    })
    return row


def infer_swing_row_is_etf(row):
    ticker = str(row.get("ticker", "")).strip()
    asset_class = str(row.get("asset_class", "")).strip()
    name = str(row.get("name", "")).strip()
    return is_fin_score_exempt_asset(ticker, False, asset_class, name)


def fill_empty_swing_templates(df):
    if df is None or df.empty:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS)

    work = dataframe_from_rows(df, SWING_RADAR_COLUMNS).copy()
    today = pd.Timestamp.today().strftime("%Y-%m-%d")

    for idx, row in work.iterrows():
        ticker = str(row.get("ticker", "")).strip()
        if not ticker:
            continue

        asset_class = str(row.get("asset_class", "")).strip()
        template = get_swing_template(
            ticker,
            is_etf=infer_swing_row_is_etf(row),
            asset_class=asset_class,
        )

        for col in SWING_TEMPLATE_TEXT_FIELDS:
            if not str(work.at[idx, col] or "").strip():
                work.at[idx, col] = template.get(col, "")

        if not str(work.at[idx, "status"] or "").strip():
            work.at[idx, "status"] = "진행"
        if not str(work.at[idx, "decision"] or "").strip():
            work.at[idx, "decision"] = "관망"
        if not str(work.at[idx, "importance"] or "").strip():
            work.at[idx, "importance"] = "중"
        if not str(work.at[idx, "last_checked"] or "").strip():
            work.at[idx, "last_checked"] = today

    return dataframe_from_rows(work, SWING_RADAR_COLUMNS)


def set_swing_row_status(df, ticker, status):
    work = dataframe_from_rows(df, SWING_RADAR_COLUMNS).copy()
    key = normalize_ticker(ticker)
    mask = work["ticker"].apply(normalize_ticker) == key
    if mask.any():
        work.loc[mask, "status"] = status
        work.loc[mask, "last_checked"] = pd.Timestamp.today().strftime("%Y-%m-%d")
    return dataframe_from_rows(work, SWING_RADAR_COLUMNS)


def remove_swing_row(df, ticker):
    work = dataframe_from_rows(df, SWING_RADAR_COLUMNS).copy()
    key = normalize_ticker(ticker)
    work = work[work["ticker"].apply(normalize_ticker) != key]
    return dataframe_from_rows(work, SWING_RADAR_COLUMNS)


SWING_EXCLUDED_TICKERS = {"krw_cash", "usd_cash", "cash"}


def is_swing_excluded_ticker(ticker):
    key = normalize_ticker(ticker)
    return (not key) or key in RESERVE_TICKERS or key in SWING_EXCLUDED_TICKERS


def is_swing_candidate_allowed(ticker, is_etf=False, bucket="", asset_class="", include_etf=False):
    if is_swing_excluded_ticker(ticker):
        return False
    if is_reserve_or_cash_bucket(infer_bucket(ticker, bucket)):
        return False
    asset_class_text = str(asset_class or "").strip().lower()
    if asset_class_text in ["cash", "reserve", "krw_cash", "usd_cash"]:
        return False
    if (not include_etf) and is_fin_score_exempt_asset(ticker, is_etf, asset_class_text):
        return False
    return True


def is_known_non_swing_asset(ticker, asset_class="", include_etf=False):
    if is_swing_excluded_ticker(ticker):
        return True
    if (not include_etf) and is_fin_score_exempt_asset(ticker, False, asset_class):
        return True

    if holdings_df is not None and not holdings_df.empty:
        key = normalize_ticker(ticker)
        matched = holdings_df[holdings_df["ticker"].apply(normalize_ticker) == key] if "ticker" in holdings_df.columns else pd.DataFrame()
        if not matched.empty:
            row = matched.iloc[0]
            return not is_swing_candidate_allowed(
                ticker,
                is_etf=row.get("is_etf", False),
                bucket=row.get("bucket", "core"),
                asset_class=row.get("asset_class", ""),
                include_etf=include_etf,
            )

    item = get_watchlist_item(ticker)
    if item:
        return not is_swing_candidate_allowed(
            ticker,
            is_etf=item.get("is_etf", False),
            bucket=item.get("bucket", "core"),
            asset_class=item.get("asset_class", ""),
            include_etf=include_etf,
        )

    return False


def get_current_stock_candidates(include_etf=False):
    candidates = {}

    if "watchlist" in st.session_state:
        for item in st.session_state.watchlist:
            ticker = str(item.get("ticker", "")).strip()
            is_etf = is_fin_score_exempt_asset(ticker, item.get("is_etf", False), item.get("asset_class", ""), item.get("name", ""))
            asset_class = infer_asset_class_for_ticker(ticker, item.get("asset_class", "")) if is_etf else str(item.get("asset_class", "")).strip()
            if not is_swing_candidate_allowed(
                ticker,
                is_etf=is_etf,
                bucket=item.get("bucket", "core"),
                asset_class=asset_class,
                include_etf=include_etf,
            ):
                continue
            candidates[normalize_ticker(ticker)] = {
                "name": str(item.get("name", ticker)).strip(),
                "ticker": ticker,
                "asset_class": asset_class,
                "is_etf": is_etf,
            }

    if holdings_df is not None and not holdings_df.empty:
        for _, row in holdings_df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            is_etf = is_fin_score_exempt_asset(ticker, row.get("is_etf", False), row.get("asset_class", ""), row.get("name", ""))
            asset_class = infer_asset_class_for_ticker(ticker, row.get("asset_class", "")) if is_etf else str(row.get("asset_class", "")).strip()
            if not is_swing_candidate_allowed(
                ticker,
                is_etf=is_etf,
                bucket=row.get("bucket", "core"),
                asset_class=asset_class,
                include_etf=include_etf,
            ):
                continue
            candidates[normalize_ticker(ticker)] = {
                "name": str(row.get("name", ticker)).strip(),
                "ticker": ticker,
                "asset_class": asset_class,
                "is_etf": is_etf,
            }

    return candidates


def build_swing_radar_df(saved_df, include_hidden=False, include_etf=False, include_auto=True):
    rows_by_key = {}

    if saved_df is not None and not saved_df.empty:
        for _, row in saved_df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker or is_swing_excluded_ticker(ticker):
                continue
            item = {col: row.get(col, "") for col in SWING_RADAR_COLUMNS}
            rows_by_key[normalize_ticker(ticker)] = item

    if include_auto:
        for key, item in get_current_stock_candidates(include_etf=include_etf).items():
            if key not in rows_by_key:
                rows_by_key[key] = make_swing_candidate_row(item["name"], item["ticker"], item["asset_class"], item.get("is_etf", False))
            else:
                if not str(rows_by_key[key].get("name", "")).strip():
                    rows_by_key[key]["name"] = item["name"]
                if not str(rows_by_key[key].get("asset_class", "")).strip():
                    rows_by_key[key]["asset_class"] = item["asset_class"]

    df = pd.DataFrame(list(rows_by_key.values()))
    for col in SWING_RADAR_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    if df.empty:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS)

    if not include_hidden:
        df = df[df["status"].astype(str).str.strip() != "숨김"]

    if df.empty:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS)

    return df[SWING_RADAR_COLUMNS].sort_values(["importance", "name"], ascending=[True, True])


def merge_swing_editor_with_saved(saved_df, edited_df, visible_df):
    rows_by_key = {}

    if saved_df is not None and not saved_df.empty:
        for _, row in saved_df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker or is_swing_excluded_ticker(ticker):
                continue
            rows_by_key[normalize_ticker(ticker)] = {col: row.get(col, "") for col in SWING_RADAR_COLUMNS}

    visible_keys = {
        normalize_ticker(row.get("ticker", ""))
        for _, row in visible_df.iterrows()
        if str(row.get("ticker", "")).strip()
    } if visible_df is not None and not visible_df.empty else set()

    edited_keys = {
        normalize_ticker(row.get("ticker", ""))
        for _, row in edited_df.iterrows()
        if str(row.get("ticker", "")).strip()
    } if edited_df is not None and not edited_df.empty else set()

    for key in visible_keys - edited_keys:
        rows_by_key.pop(key, None)

    if edited_df is not None and not edited_df.empty:
        for _, row in edited_df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker or is_swing_excluded_ticker(ticker):
                continue
            rows_by_key[normalize_ticker(ticker)] = {col: row.get(col, "") for col in SWING_RADAR_COLUMNS}

    merged = pd.DataFrame(list(rows_by_key.values()))
    for col in SWING_RADAR_COLUMNS:
        if col not in merged.columns:
            merged[col] = ""
    return dataframe_from_rows(merged, SWING_RADAR_COLUMNS) if not merged.empty else dataframe_from_rows([], SWING_RADAR_COLUMNS)


def get_swing_editor_base_key(df, show_hidden, include_auto, include_etf):
    if df is None or df.empty:
        ticker_part = "empty"
    else:
        ticker_part = "|".join(
            df["ticker"].astype(str).apply(normalize_ticker).fillna("").tolist()
        )
    return f"{show_hidden}|{include_auto}|{include_etf}|{ticker_part}"


def reset_swing_editor_draft():
    for key in ["swing_radar_editor_draft_df", "swing_radar_editor_base_key", "swing_radar_editor"]:
        st.session_state.pop(key, None)


def get_swing_editor_draft(base_df, base_key):
    if (
        st.session_state.get("swing_radar_editor_base_key") != base_key
        or "swing_radar_editor_draft_df" not in st.session_state
    ):
        st.session_state["swing_radar_editor_base_key"] = base_key
        st.session_state["swing_radar_editor_draft_df"] = base_df.fillna("").copy()
        st.session_state.pop("swing_radar_editor", None)

    draft_df = st.session_state["swing_radar_editor_draft_df"].copy()
    for col in SWING_RADAR_COLUMNS:
        if col not in draft_df.columns:
            draft_df[col] = ""
    return draft_df[SWING_RADAR_COLUMNS]


def get_swing_item_context(row):
    ticker = str(row.get("ticker", "")).strip()
    name = str(row.get("name", ticker)).strip()
    asset_class = str(row.get("asset_class", "")).strip()
    avg_price = 0.0
    has_pos = False
    is_etf = is_fin_score_exempt_asset(ticker, False, asset_class, name)

    holding_row = get_holding_row_by_ticker(holdings_table, ticker)
    if holding_row is not None:
        name = str(holding_row.get("자산명", name)).strip() or name
        asset_class = str(holding_row.get("asset_class", asset_class)).strip() or asset_class
        is_etf = is_fin_score_exempt_asset(ticker, holding_row.get("is_etf", False), asset_class, name)
        asset_class = infer_asset_class_for_ticker(ticker, asset_class) if is_etf else asset_class
        avg_price = clean_float(holding_row.get("매입가"), 0.0)
        has_pos = clean_float(holding_row.get("보유량"), 0.0) > 0
    else:
        item = get_watchlist_item(ticker)
        if item:
            name = str(item.get("name", name)).strip() or name
            asset_class = str(item.get("asset_class", asset_class)).strip() or asset_class
            is_etf = is_fin_score_exempt_asset(ticker, item.get("is_etf", False), asset_class, name)
            asset_class = infer_asset_class_for_ticker(ticker, asset_class) if is_etf else asset_class

    return name, ticker, asset_class, avg_price, has_pos, is_etf


def build_swing_system_df(swing_df):
    rows = []
    if swing_df is None or swing_df.empty:
        return pd.DataFrame(rows)

    for _, row in swing_df.iterrows():
        name, ticker, asset_class, avg_price, has_pos, is_etf = get_swing_item_context(row)

        try:
            px = load_price_df(ticker, "1y")
            if px.empty or len(px) < 2:
                raise RuntimeError("가격 데이터 없음")

            px = build_indicators(px)
            fin_score, _ = load_fin_score_meta_fast(ticker, is_etf)
            c = calc_scores_and_decision(
                name=name,
                ticker=ticker,
                is_etf=is_etf,
                asset_class=asset_class or ("us_etf_nasdaq" if is_etf else "kr_stock"),
                df=px,
                my_price=avg_price,
                has_pos=has_pos,
                fin_score=int(fin_score),
                is_free=False,
                app_mode="개인모드",
            )

            rows.append({
                "ticker": ticker,
                "종목명": name,
                "시스템판정": c["dec"],
                "후보등급": c["grade"],
                "ADJ": round(c["adj"], 1),
                "RS": c["rs_label"],
                "RSI": round(c["rsi"], 1),
                "MFI": round(c["mfi"], 1),
                "추세": c["trend"],
                "현재비중": round(c["current_w"], 2),
                "목표비중": round(c["target_w"], 2),
                "현재가": format_currency(c["cur_p"], ticker),
            })
        except Exception as e:
            rows.append({
                "ticker": ticker,
                "종목명": name,
                "시스템판정": f"계산 실패: {e}",
                "후보등급": "-",
                "ADJ": np.nan,
                "RS": "-",
                "RSI": np.nan,
                "MFI": np.nan,
                "추세": "-",
                "현재비중": 0,
                "목표비중": 0,
                "현재가": "-",
            })

    return pd.DataFrame(rows)


def render_swing_radar_tab():
    st.subheader("스윙 레이더")
    st.caption("스윙 레이더는 개별주와 ETF의 보유 이유, 진입 조건, 위험 신호를 잊지 않게 관리하는 영역입니다.")

    saved_df, load_error = load_swing_radar_db_safe()
    if load_error:
        st.warning("스윙 레이더 저장 테이블이 아직 없어서 저장 기능은 비활성입니다. 아래 SQL을 Supabase SQL Editor에서 한 번만 실행하면 저장됩니다.")
        with st.expander("Supabase swing_radar 테이블 생성 SQL"):
            st.code(get_swing_radar_create_sql(), language="sql")

    opt1, opt2, opt3 = st.columns(3)
    with opt1:
        show_hidden = st.checkbox("숨김 후보도 보기", value=False, key="swing_show_hidden")
    with opt2:
        include_auto_candidates = st.checkbox("보유/전광판 자동 후보 불러오기", value=True, key="swing_include_auto")
    with opt3:
        include_etf_candidates = st.checkbox("ETF도 자동 후보에 포함", value=False, key="swing_include_etf")

    with st.expander("스윙 후보 직접 추가"):
        st.caption("자동 후보에 없거나 ETF를 따로 스윙 관리하고 싶을 때 사용합니다. 숨김 처리한 기존 후보는 새 후보 추가 시에도 유지됩니다.")
        add_cols = st.columns([1, 1, 1, 1])
        with add_cols[0]:
            new_swing_ticker = st.text_input("티커", "", key="new_swing_ticker").strip().upper()
        with add_cols[1]:
            new_swing_name = st.text_input("이름", "", key="new_swing_name").strip()
        with add_cols[2]:
            new_swing_is_etf = st.checkbox("ETF", value=False, key="new_swing_is_etf")
        with add_cols[3]:
            new_swing_asset_class = st.selectbox(
                "분류",
                ["us_stock", "kr_stock", "us_etf_nasdaq", "us_etf_sp", "us_etf_other", "kr_etf", "kr_etn", "us_etn", "fund"],
                index=2 if new_swing_is_etf else 0,
                key="new_swing_asset_class",
            )

        if st.button("스윙 후보 추가", key="add_swing_candidate"):
            if not new_swing_ticker:
                st.warning("추가할 티커를 입력해 주세요.")
            elif is_swing_excluded_ticker(new_swing_ticker):
                st.warning("현금/대기자금/파킹자산은 스윙 후보에 추가하지 않습니다.")
            else:
                inferred_is_etf = is_fin_score_exempt_asset(new_swing_ticker, new_swing_is_etf, new_swing_asset_class, new_swing_name)
                inferred_asset_class = infer_asset_class_for_ticker(new_swing_ticker, new_swing_asset_class) if inferred_is_etf else new_swing_asset_class
                new_row = make_swing_candidate_row(
                    new_swing_name or new_swing_ticker,
                    new_swing_ticker,
                    inferred_asset_class,
                    inferred_is_etf,
                )
                append_df = pd.concat([saved_df, pd.DataFrame([new_row])], ignore_index=True) if saved_df is not None and not saved_df.empty else pd.DataFrame([new_row])
                dedup_df = merge_swing_editor_with_saved(saved_df, append_df, pd.DataFrame(columns=SWING_RADAR_COLUMNS))
                ok, message = save_swing_radar_db_safe(dedup_df)
                if ok:
                    reset_swing_editor_draft()
                    st.success("스윙 후보 추가 완료")
                    st.rerun()
                else:
                    st.error(f"스윙 후보 추가 실패: {message}")
                    with st.expander("테이블이 없을 때 실행할 SQL"):
                        st.code(get_swing_radar_create_sql(), language="sql")

    swing_df = build_swing_radar_df(
        saved_df,
        include_hidden=show_hidden,
        include_etf=include_etf_candidates,
        include_auto=include_auto_candidates,
    )
    if swing_df.empty:
        st.info("스윙 후보가 없습니다. 관심종목/보유종목에 개별주를 추가하거나, ETF 후보를 직접 추가해 주세요. ETF 자동 후보는 체크박스를 켜면 포함됩니다.")
        return

    editor_base_key = get_swing_editor_base_key(
        swing_df,
        show_hidden=show_hidden,
        include_auto=include_auto_candidates,
        include_etf=include_etf_candidates,
    )
    editor_draft_df = get_swing_editor_draft(swing_df, editor_base_key)

    system_df = build_swing_system_df(swing_df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("스윙 후보", f"{len(swing_df)}개")
    c2.metric("진행", f"{(swing_df['status'] == '진행').sum()}개")
    c3.metric("위험 표시", f"{(swing_df['status'] == '위험').sum()}개")
    c4.metric("종료/보류/숨김", f"{swing_df['status'].isin(['종료', '보류', '숨김']).sum()}개")

    st.markdown("#### 시스템 신호 요약")
    if system_df.empty:
        st.dataframe(system_df, use_container_width=True, hide_index=True)
    else:
        system_hide_df = system_df.copy()
        system_hide_df.insert(0, "숨김 선택", False)
        system_hide_key = f"swing_system_hide_editor_{abs(hash(editor_base_key))}"
        edited_system_hide_df = st.data_editor(
            system_hide_df,
            use_container_width=True,
            hide_index=True,
            key=system_hide_key,
            disabled=[col for col in system_hide_df.columns if col != "숨김 선택"],
            column_config={
                "숨김 선택": st.column_config.CheckboxColumn(
                    "숨김",
                    help="여러 후보를 체크한 뒤 한 번에 숨김 처리합니다.",
                    default=False,
                )
            },
        )

        batch_hide_mask = edited_system_hide_df["숨김 선택"].fillna(False).astype(bool)
        batch_hide_tickers = (
            edited_system_hide_df.loc[batch_hide_mask, "ticker"].astype(str).str.strip().tolist()
        )
        batch_cols = st.columns([1, 3])
        with batch_cols[0]:
            if st.button(
                f"체크한 {len(batch_hide_tickers)}개 숨김",
                key="batch_hide_swing_candidates",
                disabled=len(batch_hide_tickers) == 0,
            ):
                action_df = editor_draft_df.copy()
                for ticker_to_hide in batch_hide_tickers:
                    action_df = set_swing_row_status(action_df, ticker_to_hide, "숨김")

                merged_swing_df = merge_swing_editor_with_saved(saved_df, action_df, swing_df)
                ok, message = save_swing_radar_db_safe(merged_swing_df)
                if ok:
                    reset_swing_editor_draft()
                    st.success(f"{len(batch_hide_tickers)}개 후보를 숨김 처리했습니다.")
                    st.rerun()
                else:
                    st.error(f"일괄 숨김 처리 실패: {message}")
        with batch_cols[1]:
            st.caption("여러 후보를 한 번에 숨기면 저장/재실행을 한 번만 하므로 훨씬 덜 버벅입니다.")

    selected = st.selectbox(
        "상세 확인 종목",
        swing_df["ticker"].tolist(),
        format_func=lambda t: f"{swing_df[swing_df['ticker'] == t].iloc[0]['name']} ({t})",
        key="swing_selected_ticker",
    )

    selected_row = swing_df[swing_df["ticker"] == selected].iloc[0]
    selected_safe = {col: escape_html_value(selected_row.get(col, "")) for col in SWING_RADAR_COLUMNS}
    selected_system = system_df[system_df["ticker"].apply(normalize_ticker) == normalize_ticker(selected)]

    action_cols = st.columns([1.15, 0.9, 1])
    with action_cols[0]:
        if st.button("빈칸 자동문구 채우기", key="fill_empty_swing_templates"):
            editor_draft_df = fill_empty_swing_templates(editor_draft_df)
            st.session_state["swing_radar_editor_draft_df"] = editor_draft_df.fillna("").copy()
            st.success("비어있는 체크리스트 문구만 자동으로 채웠습니다.")

    with action_cols[1]:
        delete_confirm = st.checkbox("삭제 확인", value=False, key=f"delete_confirm_{normalize_ticker(selected)}")

    with action_cols[2]:
        if st.button("선택 후보 삭제", key=f"delete_swing_{normalize_ticker(selected)}"):
            if not delete_confirm:
                st.warning("삭제하려면 먼저 '삭제 확인'을 체크해 주세요.")
            else:
                action_df = remove_swing_row(editor_draft_df, selected)

                auto_candidates = get_current_stock_candidates(include_etf=include_etf_candidates) if include_auto_candidates else {}
                selected_key = normalize_ticker(selected)
                if selected_key in auto_candidates:
                    auto_item = auto_candidates[selected_key]
                    hidden_row = make_swing_candidate_row(
                        auto_item.get("name", selected),
                        auto_item.get("ticker", selected),
                        auto_item.get("asset_class", ""),
                        auto_item.get("is_etf", False),
                    )
                    hidden_row["status"] = "숨김"
                    hidden_row["decision"] = "관망"
                    hidden_row["memo"] = "삭제 버튼으로 자동 후보 숨김 처리"
                    action_df = pd.concat([action_df, pd.DataFrame([hidden_row])], ignore_index=True)

                merged_swing_df = merge_swing_editor_with_saved(saved_df, action_df, swing_df)
                ok, message = save_swing_radar_db_safe(merged_swing_df)
                if ok:
                    reset_swing_editor_draft()
                    st.success("선택 후보를 삭제했습니다. 자동 후보였던 경우 다시 뜨지 않도록 숨김 처리했습니다.")
                    st.rerun()
                else:
                    st.error(f"삭제 실패: {message}")

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown(
            f"""
<div class='info-panel'>
<b>{selected_safe['name']} ({selected_safe['ticker']})</b><br>
<span class='smc-tag'>보유 이유</span> {selected_safe['idea']}<br><br>
<b>확인할 것</b><br>
1. {selected_safe['check_1']}<br>
2. {selected_safe['check_2']}<br>
3. {selected_safe['check_3']}<br><br>
<b>위험 신호</b><br>
1. {selected_safe['risk_1']}<br>
2. {selected_safe['risk_2']}<br>
3. {selected_safe['risk_3']}
</div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        if not selected_system.empty:
            s = selected_system.iloc[0]
            st.markdown(
                f"""
<div class='info-panel'>
<b>시스템 판정</b><br>
<span class='highlight' style='font-size:1.0em;'>{s['시스템판정']}</span><br>
후보등급: {s['후보등급']}<br>
ADJ: {s['ADJ']} | RS: {s['RS']}<br>
RSI: {s['RSI']} | MFI: {s['MFI']}<br>
추세: {s['추세']}<br>
현재/목표 비중: {s['현재비중']}% / {s['목표비중']}%
</div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown(
            f"""
<div class='info-panel'>
<b>운영 규칙</b><br>
진입/추매: {selected_safe['entry_rule']}<br>
종료/축소: {selected_safe['exit_rule']}<br>
다음 확인: {selected_safe['next_event']}<br>
현재 결정: <b>{selected_safe['decision']}</b> | 상태: <b>{selected_safe['status']}</b>
</div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("선택 종목 뉴스 빠르게 보기"):
        if st.button("관련 뉴스 불러오기", key=f"swing_news_{normalize_ticker(selected)}"):
            news_items, news_logs = get_ticker_news(selected, str(selected_row["name"]), news_debug)
            if news_items:
                render_news_cards(news_items)
            else:
                st.info("현재 제공되는 관련 뉴스가 없습니다.")
                if news_debug:
                    for log in news_logs:
                        st.write(log)

    st.markdown("#### 스윙 체크리스트 편집")
    st.caption("입력 중인 내용은 화면 재실행 중에도 임시 보존됩니다. 최종 반영은 아래 저장 버튼을 눌러야 완료됩니다.")
    edited_swing_df = st.data_editor(
        editor_draft_df[SWING_EDITOR_COLUMNS].fillna(""),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="swing_radar_editor",
        disabled=["ticker"],
        column_config={
            "status": st.column_config.SelectboxColumn("상태", options=["대기", "진행", "완료", "위험", "보류", "종료", "숨김"]),
            "decision": st.column_config.SelectboxColumn("내 결정", options=["관망", "정찰", "추매대기", "유지", "일부익절", "축소", "종료"]),
            "importance": st.column_config.SelectboxColumn("중요도", options=["상", "중", "하"]),
            "reference_link": st.column_config.LinkColumn("참고 링크"),
        },
    )
    st.session_state["swing_radar_editor_draft_df"] = edited_swing_df.fillna("").copy()

    if st.button("스윙 레이더 저장"):
        merged_swing_df = merge_swing_editor_with_saved(saved_df, edited_swing_df, swing_df)
        ok, message = save_swing_radar_db_safe(merged_swing_df)
        if ok:
            reset_swing_editor_draft()
            st.success("스윙 레이더 저장 완료")
            st.rerun()
        else:
            st.error(f"스윙 레이더 저장 실패: {message}")
            with st.expander("테이블이 없을 때 실행할 SQL"):
                st.code(get_swing_radar_create_sql(), language="sql")


def render_feedback_tab():
    st.subheader("Q&A / 피드백")
    st.caption("사용하면서 불편한 점, 오류, 개선 아이디어를 남기는 공간입니다. 작은 의견도 장기 운영 품질을 올리는 데 도움이 됩니다.")

    with st.form("feedback_form", clear_on_submit=True):
        c1, c2 = st.columns([1, 1])
        with c1:
            category = st.selectbox(
                "분류",
                ["개선 제안", "오류 신고", "사용 질문", "기능 요청", "장기투자 아이디어"],
                key="feedback_category",
            )
        with c2:
            priority = st.selectbox(
                "우선순위",
                ["보통", "높음", "낮음"],
                key="feedback_priority",
            )
        title = st.text_input("제목", "", key="feedback_title")
        body = st.text_area(
            "내용",
            "",
            height=160,
            key="feedback_body",
            placeholder="예: 자산관리 탭에서 월별 수익률 설명이 헷갈립니다. / 전광판을 ETF만 따로 보고 싶습니다.",
        )
        submitted = st.form_submit_button("피드백 보내기")

    if submitted:
        if not str(body or "").strip():
            st.warning("내용을 한 줄 이상 적어주세요.")
        else:
            safe_title = str(title or "").strip() or str(body).strip()[:40]
            ok, message = save_feedback_db_safe(category, safe_title, body, priority)
            if ok:
                st.success("피드백이 접수됐습니다. 고마워요, 이게 앱을 오래 버티게 만드는 재료입니다.")
                st.rerun()
            else:
                st.error(f"피드백 저장 실패: {message}")
                with st.expander("피드백 테이블이 없을 때 실행할 SQL", expanded=True):
                    st.code(get_feedback_create_sql(), language="sql")

    feedback_df, feedback_error = load_feedback_db_safe()
    if feedback_error:
        st.warning("피드백 테이블이 아직 없거나 접근할 수 없습니다. 아래 SQL을 Supabase SQL Editor에서 한 번만 실행하면 저장 기능이 열립니다.")
        st.code(get_feedback_create_sql(), language="sql")
        return

    st.markdown("### 접수된 피드백")
    if feedback_df.empty:
        st.info("아직 접수된 피드백이 없습니다.")
    else:
        show_df = feedback_df.copy()
        if not is_admin_user() and "owner_email" in show_df.columns:
            show_df = show_df.drop(columns=["owner_email"])
        preferred_cols = [col for col in ["created_at", "category", "priority", "status", "title", "body", "owner_email"] if col in show_df.columns]
        st.dataframe(show_df[preferred_cols], use_container_width=True, hide_index=True, height=360)

    with st.expander("관리자용: 피드백 테이블 생성 SQL"):
        st.caption("이 SQL은 Supabase 프로젝트에서 한 번만 실행하면 됩니다. 같은 프로젝트를 쓰는 모든 사용자에게 적용됩니다.")
        st.code(get_feedback_create_sql(), language="sql")


# -------------------------------------------------
# 7-1. 판정 매뉴얼 데이터 + 렌더러
# -------------------------------------------------
MANUAL_SECTIONS = {
    "핵심 지표": [
        {"항목": "RS", "정의": "벤치마크 대비 상대강도", "코드 기준": "20거래일 상대강도 +3% 초과 강함, -3% 미만 약함", "해석": "강하면 시장보다 앞서는 종목"},
        {"항목": "RSI", "정의": "가격 모멘텀 과열/침체", "코드 기준": "30 이하 과매도, 70 이상 과열권", "해석": "낮으면 반등 후보, 높으면 추격주의"},
        {"항목": "MFI", "정의": "거래량 포함 자금흐름", "코드 기준": "30 미만 +2점, 80 초과 -1점, 85 이상 하드차단", "해석": "자금 유입/과열 판단"},
        {"항목": "볼린저 %B", "정의": "볼린저밴드 내 현재 위치", "코드 기준": "0.95 이상 상단권, 1.02 초과 과열확장", "해석": "상단권은 눌림 대기 우선"},
        {"항목": "MACD", "정의": "추세 전환/유지", "코드 기준": "골든크로스 +2, 상승유지 +1, 데드크로스 -2", "해석": "매수 타점의 핵심 모멘텀"},
        {"항목": "SQZ", "정의": "변동성 압축/해제", "코드 기준": "해제직후 + MACD 양호 시 +1", "해석": "압축 후 방향성 분출 체크"},
        {"항목": "MDD", "정의": "52주 고점 대비 낙폭", "코드 기준": "-20%는 추매금지/원인점검, -30% 이하는 위기 단계", "해석": "내 손익률이 아니라 최근 고점 대비 구조 훼손 정도를 보는 보조 지표"},
        {"항목": "ADJ점수", "정의": "매크로 패널티 반영 기술점수", "코드 기준": "메인점수 + RS점수 + MFI점수 - 매크로패널티", "해석": "높을수록 현재 타점 우호"},
    ],
    "점수 계산": [
        {"항목": "RS 점수", "계산": "강함 +2, 보통 +1, 약함 0", "용도": "기술점수/ADJ점수"},
        {"항목": "MFI 점수", "계산": "30 미만 +2, 80 초과 -1, 그 외 0", "용도": "자금흐름 반영"},
        {"항목": "추세 점수", "계산": "MA20 > MA50 > MA120 정배열이면 +2", "용도": "중기 추세 반영"},
        {"항목": "MACD 점수", "계산": "골든크로스 +2, 상승유지 +1, 데드크로스 -2", "용도": "모멘텀 반영"},
        {"항목": "SQZ 점수", "계산": "SQZ 해제직후 + MACD 양호하면 +1", "용도": "변동성 발산 초입 반영"},
        {"항목": "기술점수", "계산": "RS + MFI + 추세 + MACD + SQZ", "용도": "후보등급 계산"},
        {"항목": "개별주 총점", "계산": "기술점수 + 재무점수", "용도": "F/C/B/A/S 등급"},
        {"항목": "ETF 총점", "계산": "기술점수만 사용", "용도": "ETF 관망/보통/양호/우수"},
        {"항목": "매크로 패널티", "계산": "리스크 1.5 이상 -0.5, 2.5 이상 -1.5, 4 이상 -2", "용도": "ADJ점수 차감"},
    ],
    "후보 등급": [
        {"구분": "ETF", "기준": "기술점수 < 1", "등급": "ETF 관망"},
        {"구분": "ETF", "기준": "기술점수 1~2", "등급": "ETF 보통"},
        {"구분": "ETF", "기준": "기술점수 3~4", "등급": "ETF 양호"},
        {"구분": "ETF", "기준": "기술점수 5 이상", "등급": "ETF 우수"},
        {"구분": "개별주", "기준": "재무점수 1", "등급": "F급 재무위험/처분"},
        {"구분": "개별주", "기준": "기술점수 + 재무점수 < 3", "등급": "F급"},
        {"구분": "개별주", "기준": "3~4점", "등급": "C급 주의/대기"},
        {"구분": "개별주", "기준": "5~6점", "등급": "B급 신중/관망"},
        {"구분": "개별주", "기준": "7~8점", "등급": "A급 분할매수"},
        {"구분": "개별주", "기준": "9점 이상", "등급": "S급 강력매수"},
    ],
    "기술적 타점": [
        {"타점": "하드차단: 재무F급", "조건": "개별주 재무점수 1 이하", "의미": "기술 신호와 무관하게 매수 차단"},
        {"타점": "하드차단: 비중 초과", "조건": "현재비중 > 목표비중", "의미": "추가매수 금지"},
        {"타점": "하드차단: 비중 충족", "조건": "현재비중 >= 목표비중", "의미": "목표 도달, 관망"},
        {"타점": "퍼펙트스톰", "조건": "매크로 리스크 4.5 이상", "의미": "시장 위험 우선 회피"},
        {"타점": "MFI 극단 과열", "조건": "MFI 85 이상", "의미": "추격매수 금지"},
        {"타점": "과열확장", "조건": "재무 4점 + ADJ 4 이상 + %B 1.02 초과 + RS 강함", "의미": "대장주지만 MA5 눌림 대기"},
        {"타점": "불뿜는 대장주", "조건": "재무 4점 + ADJ 4 이상 + %B 0.95~1.02 + RS 강함", "의미": "강한 종목, 단기 눌림 진입 후보"},
        {"타점": "볼린상단 이탈", "조건": "개별주 %B 0.95 이상", "의미": "단기 과열로 신규/추매 차단"},
        {"타점": "예외승인: MA5/FVG", "조건": "재무 4점 + 정배열 + RS 강함 + MACD 양호 + MA5/FVG 눌림", "의미": "우량 대장주 예외 진입"},
        {"타점": "ETF 목표비중 미달", "조건": "ETF 보유 + 목표비중 부족 + 과열 아님", "의미": "적립식 매수 가능"},
        {"타점": "상승확인: 2차 정찰 추매", "조건": "평단 대비 0~5% 상승 + 비중부족 + 추세 양호", "의미": "상승 확인 후 제한적 추매"},
        {"타점": "S급 눌림목", "조건": "정배열 + RS 강함 + RSI 45~58 + %B 0.45~0.8", "의미": "가장 선호하는 눌림 매수 구간"},
        {"타점": "낙폭과대", "조건": "RSI 30 이하 또는 하락추세 속 ADJ 높음", "의미": "반등 가능성은 있으나 분할 접근"},
        {"타점": "평단 -3~-7%", "조건": "평단 이하, 추세 훼손 크지 않음, MFI 80 미만", "의미": "소액 분할매수 후보"},
        {"타점": "평단 -7~-15%", "조건": "손실 확대 + 재무 3점 이상 + 매크로 위험 낮음", "의미": "조건부 분할매수"},
        {"타점": "평단 -15%↓", "조건": "평단 대비 큰 손실 또는 추세위험", "의미": "원인 점검 우선"},
        {"타점": "고점대비 -20%", "조건": "52주 고점 대비 -20% 이하", "의미": "보유 중이면 추매 금지와 원인 점검, 미보유면 신규진입 보류"},
        {"타점": "구조훼손: 신규진입 보류", "조건": "개별주 MDD -15% 이하, MA50 이탈, 급락+거래량, MA20 하단 이탈 중 하나", "의미": "점수가 좋아도 차트 구조 확인 전 신규매수 보류"},
        {"타점": "신규진입: 대장주 포착", "조건": "ADJ 4.5 이상 + RS 강함 + 정배열 + MA20 근처 이상 + MDD -15% 이내 + 급락 아님", "의미": "구조가 살아있는 신규 후보"},
        {"타점": "관망/대기", "조건": "명확한 우위 없음", "의미": "타점 대기"},
    ],
    "SMC 구조": [
        {"항목": "외부구조", "기준": "정배열 Bullish, 역배열 Bearish, 그 외 Neutral", "의미": "큰 추세 방향"},
        {"항목": "내부구조", "기준": "RS/MACD/추세 조합", "의미": "단기 구조 강도"},
        {"항목": "BoS", "기준": "최근 피벗 고점/저점 돌파", "의미": "구조적 돌파"},
        {"항목": "CHoCH", "기준": "기존 추세와 반대 방향 구조 변화", "의미": "추세 전환 가능성"},
        {"항목": "Liquidity Grab", "기준": "고점/저점 훼이크 돌파 후 종가 회귀", "의미": "유동성 청산 가능성"},
        {"항목": "FVG", "기준": "최근 캔들 간 가격 공백", "의미": "눌림/저항 후보 구간"},
        {"항목": "P/D Zone", "기준": "200일 평균과 표준편차 기준 Premium/Discount", "의미": "비싼 구간/싼 구간 판단"},
    ],
}

def render_manual_tab():
    st.subheader("판정 매뉴얼")
    st.caption("판정 문구는 투자 권유가 아니라, 기술/재무/비중/매크로 조건을 함께 점검하는 보조 신호입니다.")

    guide_tab, table_tab, faq_tab = st.tabs(["해설 가이드", "기준표", "자주 묻는 질문"])

    with guide_tab:
        st.markdown("""
### 판정이 만들어지는 순서

1. 가격 데이터를 불러오고 이동평균, RSI, MFI, MACD, 볼린저 %B, SQZ를 계산합니다.
2. 종목이 벤치마크보다 강한지 RS로 비교합니다.
3. 개별주는 재무점수를 더하고, ETF/ETN/레버리지 상품은 재무점수 해당없음으로 봅니다.
4. 금리, 환율, VIX, MOVE 같은 매크로 위험을 패널티로 반영합니다.
5. 마지막으로 보유 여부, 평단가, 현재비중, 목표비중을 보고 최종 타점 문구를 정합니다.

핵심은 하드차단 조건이 먼저라는 점입니다. 아무리 차트가 좋아도 재무F급, 비중초과, 극단과열, 퍼펙트스톰 같은 조건이 있으면 매수 가능 문구보다 금지/관망 문구가 먼저 나옵니다.
        """)

        with st.expander("하드차단/금지 문구 자세히 보기", expanded=True):
            st.markdown("""
**하드차단: 재무F급**  
개별주 재무점수가 1점 이하일 때 뜹니다. 기술적 반등 신호가 있어도 재무 리스크를 우선해서 신규매수/추매를 막습니다.

**하드차단: 비중 초과**  
현재비중이 목표비중보다 높을 때 뜹니다. 종목이 나쁘다는 뜻이 아니라, 이미 목표보다 많이 들고 있으니 추가매수를 막는다는 뜻입니다.

**하드차단: 비중 충족**  
현재비중이 목표비중에 도달했을 때 뜹니다. 목표를 채웠으니 더 사기보다 관망하라는 뜻입니다.

**하드차단: 퍼펙트스톰**  
매크로 리스크가 4.5 이상일 때 뜹니다. 이때는 개별 종목보다 시장 전체 위험이 우선입니다.

**하드차단: MFI 극단 과열**  
MFI가 85 이상일 때 뜹니다. 거래량을 동반한 단기 과열이 심해서 추격매수를 막습니다.

**하드차단: 볼린상단 이탈**  
개별주가 볼린저 %B 0.95 이상일 때 뜹니다. 단기 상단권이라 신규매수/추매보다 눌림 대기가 우선입니다.
            """)

        with st.expander("매수 가능/관망 문구 자세히 보기", expanded=True):
            st.markdown("""
**불뿜는 대장주**  
재무 4점, RS 강함, ADJ점수 양호, 볼린저 상단권 조건을 만족한 강한 종목입니다. 다만 이미 강하게 오른 구간이라 초단기 눌림을 기다리는 해석이 붙습니다.

**과열확장: 추격금지, MA5 대기**  
우량 종목이어도 볼린저 %B가 1.02를 넘으면 너무 뻗은 상태로 봅니다. 따라붙기보다 MA5 근처 눌림을 기다립니다.

**예외승인: 정찰대 진입/추매**  
재무 4점 우량주가 정배열, RS 강함, MACD 양호 조건을 갖추고 MA5 또는 상승 FVG 근처로 눌렸을 때 제한적으로 허용하는 신호입니다.

**ETF 목표비중 미달**  
ETF는 개별 기업 리스크가 낮아 적립식 접근을 더 허용합니다. 목표비중이 부족하고 과열이 심하지 않으면 소액 적립 가능으로 봅니다.

**상승확인: 2차 정찰 추매 가능**  
이미 보유 중인 개별주가 평단 대비 0~5% 위에 있고, 목표비중이 부족하며 추세가 양호할 때 뜹니다. 큰 매수보다는 제한적 추매 성격입니다.

**S급 눌림목**  
정배열, RS 강함, RSI 45~58, 볼린저 %B 0.45~0.8이면 상승 추세 속 눌림 후보로 봅니다.

**낙폭과대**  
RSI 30 이하이거나 하락 추세 속 ADJ가 높을 때 뜹니다. 반등 가능성은 있지만 원인 확인과 분할 접근이 필요합니다.
            """)

        with st.expander("점수 체계 한눈에 보기"):
            st.markdown("""
**재무점수**  
- ETF/ETN/레버리지 상품: 해당없음
- 1점: F급/처분 후보
- 2점: 불안정/주의
- 3점: 회복형/중간형
- 4점: 완성형 우량

**기술점수 구성**  
- RS 강함 +2, 보통 +1, 약함 0
- MFI 30 미만 +2, 80 초과 -1
- MA20 > MA50 > MA120 정배열 +2
- MACD 골든크로스 +2, 상승유지 +1, 데드크로스 -2
- SQZ 해제직후 + MACD 양호 +1

**ADJ점수**  
현재 타점 점수에서 매크로 패널티를 뺀 값입니다. 매크로 리스크가 높을수록 같은 종목도 점수가 낮아집니다.
            """)

        with st.expander("SMC 구조 해석"):
            st.markdown("""
**외부구조**는 큰 추세입니다. 정배열이면 Bullish, 역배열이면 Bearish, 그 외에는 Neutral입니다.

**내부구조**는 단기 구조입니다. RS와 MACD가 좋으면 Bullish, RS가 약하거나 역배열이면 Bearish, 애매하면 Mixed입니다.

**BoS**는 최근 구조적 고점/저점 돌파입니다. 추세 지속 신호로 봅니다.

**CHoCH**는 기존 추세와 반대 방향의 구조 변화입니다. 추세 전환 가능성을 봅니다.

**Liquidity Grab**은 고점/저점을 살짝 뚫고 다시 돌아온 움직임입니다. 단기 훼이크 돌파 또는 청산 가능성으로 해석합니다.

**FVG**는 캔들 사이 가격 공백입니다. 상승 FVG는 눌림 지지 후보, 하락 FVG는 저항 후보로 봅니다.

**P/D Zone**은 200일 평균과 표준편차로 Premium, Discount, Neutral을 나눕니다.
            """)

    with table_tab:
        q = st.text_input("매뉴얼 검색", "", key="manual_search").strip().lower()

        manual_tabs = st.tabs(list(MANUAL_SECTIONS.keys()))

        for tab, (section_name, rows) in zip(manual_tabs, MANUAL_SECTIONS.items()):
            with tab:
                df = pd.DataFrame(rows)

                if q:
                    mask = df.astype(str).apply(
                        lambda col: col.str.lower().str.contains(q, na=False)
                    ).any(axis=1)
                    df = df[mask]

                st.dataframe(df, use_container_width=True, hide_index=True)

    with faq_tab:
        st.markdown("""
### 개별주 금지는 종목이 망했다는 뜻인가요?

아닙니다. 앱 기준에서 현재 신규매수나 추매가 위험하다는 뜻입니다. 재무F급, 과열, 비중초과, 매크로 위험 등 이유가 다릅니다.

### ETF는 왜 개별주보다 덜 막나요?

ETF는 개별 기업 리스크가 낮고 적립식 운용 대상이기 때문입니다. 그래도 MFI, RSI, 볼린저, 매크로 위험이 너무 높으면 제한됩니다.

### 재무점수는 무조건 믿어도 되나요?

아닙니다. DART/FMP 데이터 기반 자동 계산이므로 누락이나 업종 특성이 있을 수 있습니다. 필요하면 수동 점수로 보정할 수 있습니다.

### S급이면 무조건 사나요?

아닙니다. S급은 후보 등급입니다. 최종 타점 문구, 목표비중, 현재비중, 매크로 리스크를 함께 봐야 합니다.

### 하드차단인데 차트가 좋아 보이면요?

하드차단은 리스크 우선 규칙입니다. 차트가 좋아 보여도 재무, 비중, 과열, 매크로 조건 중 하나가 우선 위험으로 잡힌 상태입니다.

### 평단이상 추매 대기는 왜 뜨나요?

평단보다 2% 이상 위에 있는데 확실한 2차 정찰 조건을 만족하지 못하면 추격매수보다 눌림 대기를 우선합니다.

### 비중 충족인데 더 사고 싶으면요?

목표비중을 먼저 수정해야 합니다. 앱은 목표비중을 기준으로 리스크를 제어합니다.

### 낙폭과대는 매수 신호인가요?

반등 후보라는 뜻에 가깝습니다. 하락 원인, 재무점수, 매크로 위험, 추세 전환 여부를 같이 봐야 합니다.
        """)

    with st.expander("운영 메모"):
        st.markdown("""
- 이 매뉴얼은 `calc_scores_and_decision()`의 판정 로직을 사람이 읽기 쉽게 요약한 것입니다.
- 실제 매수/관망 문구를 바꾸면 `MANUAL_SECTIONS["기술적 타점"]`도 같이 수정하면 됩니다.
- 점수 기준을 바꾸면 `MANUAL_SECTIONS["점수 계산"]`, `MANUAL_SECTIONS["후보 등급"]`을 같이 수정하면 됩니다.
- 앱 화면에서는 이 데이터를 보여주기만 하므로, 나중에 관리가 쉽습니다.
        """)


def render_user_guide_tab():
    st.subheader("사용 가이드")
    st.caption("처음 쓰는 사용자를 위한 안내입니다. 앱은 투자 권유가 아니라 포트폴리오 점검과 의사결정 보조 도구입니다.")

    start_tab, flow_tab, signal_tab, faq_tab = st.tabs(["처음 시작", "탭 사용법", "문구 해석", "공유/주의"])

    with start_tab:
        st.markdown("""
### 처음 5분 세팅

1. **로그인**
   허용된 계정으로 로그인합니다. 계정별로 자산, 관심종목, 스윙 레이더가 분리 저장됩니다.

2. **자산 현황/관리 입력**
   `💼 자산 현황` 탭에서 시드머니, 원화/달러 예수금, 환율, 보유 종목을 입력합니다.

3. **보유 종목 저장**
   보유 종목 표에는 `ticker`, `name`, `qty`, `avg_price`, `target_weight`, `asset_class`, `is_etf`, `bucket`을 입력합니다.

4. **전광판 확인**
   `📋 전광판`에서 한국 ETF, 한국 개별주, 미국 ETF, 미국 개별주를 나눠 봅니다.

5. **정밀 관측소에서 한 종목 확인**
   관심 종목을 하나 골라 현재가, 추세, RS, RSI, MFI, MACD, 볼린저 위치, 최종 판정을 확인합니다.
        """)

        st.info("자산관리만 쓰는 사용자는 자산 현황 탭만 봐도 충분합니다. 매수/추매 고민이 생긴 종목만 전광판이나 정밀관측소에서 확인하면 됩니다.")

        with st.expander("보유 종목 입력 예시", expanded=True):
            st.markdown("""
- `ticker`: 미국 주식은 `MSFT`, 한국 주식은 `005930.KS` 형식
- `qty`: 보유 수량
- `avg_price`: 평균 매입가
- `target_weight`: 목표비중
- `asset_class`: `us_stock`, `kr_stock`, `us_etf_nasdaq`, `us_etf_sp`, `kr_etf`
- `is_etf`: ETF면 체크
- `bucket`: `core` 장기, `swing` 스윙, `reserve` 대기자금/파킹
            """)

    with flow_tab:
        st.markdown("""
### 각 탭은 이렇게 씁니다

**💼 자산 현황**  
총자산, 손익, 대기자금, 보유자산 상세표를 보는 기본 화면입니다. 입력/수정 영역은 필요할 때만 펼쳐서 사용합니다.

**📊 포트폴리오 분석**  
내 자산 전체의 변동성, MDD, 집중도, 상관관계, 대기자금 비중을 확인합니다.

**📋 전광판**  
등록된 종목을 한 번에 보는 첫 화면입니다. 한국/미국, ETF/개별주를 나눠서 보고 `기술적 타점`, `ADJ점수`, `RS`, `시장벤치`, `섹터RS`를 확인합니다.

**🔍 정밀관측소**  
한 종목을 깊게 보는 곳입니다. 차트, 추세, MACD, SQZ, SMC 구조, 뉴스, AI 분석용 프롬프트를 확인합니다.

**📉 시나리오 점검**  
전체 하락, 개별 자산 충격, 대기자금 확대 같은 가정을 넣어 손실 규모를 미리 계산해 봅니다.

**📈 단기 흐름 점검**  
보유자산과 관심종목의 2~4주 단기 흐름을 상승우위/중립/하락주의로 점검합니다.

**💸 돈흐름 레이더**  
섹터와 ETF 흐름을 보는 곳입니다. 돈흐름 1위는 “이 섹터에서 후보를 먼저 찾아보라”는 뜻이지 즉시 매수 신호가 아닙니다.

**🎯 스윙 레이더**  
스윙 후보의 투자 아이디어, 체크포인트, 리스크, 진입/청산 기준을 메모하는 곳입니다.

**📘 판정 매뉴얼**  
하드차단, S급 눌림목, ETF 적립 가능 같은 문구가 왜 나오는지 확인하는 곳입니다.
        """)

        with st.expander("추천 사용 순서", expanded=True):
            st.markdown("""
1. 자산 현황에서 총자산, 손익, 대기자금, 보유자산 표를 확인
2. 필요할 때만 입력/수정 영역을 열어 보유종목, 예수금, 배당, 월별 로그 수정
3. 포트폴리오 분석에서 집중도, 변동성, 대기자금 비중 확인
4. 전광판에서 관심종목을 한국/미국, ETF/개별주로 나눠 확인
5. 정밀관측소에서 매수/추매 고민이 있는 종목만 깊게 확인
6. 돈흐름 레이더와 스윙 레이더는 고급 분석이 필요할 때만 사용
7. 시나리오 점검과 단기 흐름 점검은 시장이 흔들릴 때 보조로 확인
            """)

    with signal_tab:
        st.markdown("""
### 자주 나오는 문구 해석

**하드차단: 비중 초과 / 비중 충족**  
종목이 나쁘다는 뜻이 아니라 목표비중 기준으로 더 사지 말라는 뜻입니다.

**하드차단: 재무F급**  
개별주 재무점수가 낮아 기술 신호보다 재무 리스크를 우선한 상태입니다.

**MFI 극단 과열 / 볼린상단 이탈**  
단기 추격매수를 막는 문구입니다. 좋은 종목이어도 눌림을 기다리라는 의미입니다.

**신규ETF: 데이터 축적 대기**  
상장한 지 얼마 안 돼 MA50/MA120 같은 장기 이평선이 없습니다. 정배열/역배열 판정을 보류합니다.

**ETF 목표비중 미달**  
ETF가 목표비중보다 부족하고 과열이 심하지 않을 때 적립식 접근 가능으로 봅니다.

**S급 눌림목**  
강한 종목이 상승 추세 안에서 과열을 식힌 후보 구간입니다. 그래도 비중과 매크로 리스크는 같이 봐야 합니다.

**돈흐름 1위**  
해당 섹터가 강하다는 뜻입니다. 그 섹터 안에서 개별 종목 타점을 다시 찾아야 합니다.
        """)

        st.warning("앱 문구는 매수/매도 명령이 아닙니다. 최종 결정은 사용자가 직접 해야 합니다.")

    with faq_tab:
        st.markdown("""
### 공유 사용자에게 꼭 알려줄 것

- 이 앱은 **투자 권유 앱이 아니라 분석 보조 앱**입니다.
- 가격 데이터는 yfinance 기반이라 일시적으로 누락되거나 지연될 수 있습니다.
- 신규 ETF는 데이터가 짧아 정배열 점수가 붙지 않을 수 있습니다.
- 돈흐름 레이더는 실제 ETF 자금 유입액이 아니라 가격 기반 모멘텀입니다.
- 목표비중을 입력하지 않으면 비중 기반 판정이 약해집니다.
- 개별주는 재무점수와 섹터 흐름을 함께 봐야 합니다.
- ETF/ETN/레버리지 상품은 재무점수 해당없음이고, 기술/돈흐름/비중 중심으로 봅니다.

### 질문이 많을 때 답변 템플릿

**왜 매수금지예요?**  
판정 매뉴얼 탭에서 해당 문구를 검색해보면 이유가 나옵니다. 대개 비중초과, 과열, 재무위험, 매크로위험 중 하나입니다.

**돈흐름 1위면 사도 되나요?**  
아니요. 돈흐름 1위는 섹터 후보를 찾는 신호입니다. 종목 타점은 전광판/정밀 관측소에서 따로 봐야 합니다.

**ETF인데 개별주처럼 보여요.**  
자산관리에서 `is_etf` 체크와 `asset_class`를 확인하세요. 일부 신규 ETF는 앱 업데이트가 필요할 수 있습니다.

**내 자산이 다른 사람에게 보이나요?**  
앱은 로그인 이메일 기준으로 데이터를 분리합니다. 허용 이메일과 Supabase 저장값이 맞아야 본인 데이터가 보입니다.
        """)

        st.markdown("""
### 카톡 공지용 짧은 안내문

아래 문구를 그대로 공유해도 됩니다.

> 사용 전 앱 오른쪽 `📖 사용 가이드` 탭을 먼저 읽어주세요.  
> 전광판은 전체 후보 확인, 정밀 관측소는 한 종목 상세 확인, 돈흐름 레이더는 강한 섹터 확인용입니다.  
> 앱의 매수/관망 문구는 투자 권유가 아니라 판단 보조 신호입니다. 최종 매수/매도 결정은 본인이 직접 해야 합니다.
        """)

def calc_series_mdd(series):
    series = pd.Series(series).dropna()
    if series.empty:
        return 0.0

    running_max = series.cummax()
    drawdown = series / running_max - 1
    return float(drawdown.min()) if not drawdown.empty else 0.0


def get_active_portfolio_rows(holdings_table):
    if holdings_table is None or holdings_table.empty:
        return pd.DataFrame()

    df = holdings_table.copy()
    if "원화환산" not in df.columns or "티커" not in df.columns:
        return pd.DataFrame()

    df["원화환산"] = df["원화환산"].apply(clean_float)
    df = df[df["원화환산"] > 0].copy()

    if "bucket" in df.columns:
        df = df[~df["bucket"].apply(lambda v: normalize_bucket(v) in ["reserve", "cash"])]
    if "운용대상" in df.columns:
        df = df[df["운용대상"].apply(clean_bool)]

    df = df[~df["티커"].astype(str).str.upper().isin(["KRW_CASH", "USD_CASH"])]
    return df.reset_index(drop=True)


def add_portfolio_risk_note(notes, level, area, detail, suggestion):
    notes.append({
        "등급": level,
        "영역": area,
        "내용": detail,
        "확인/조치": suggestion,
    })


def classify_portfolio_risk(risk_index):
    if risk_index >= 70:
        return "공격/위험", "#dc2626"
    if risk_index >= 50:
        return "주의", "#f59e0b"
    if risk_index >= 30:
        return "균형", "#10b981"
    return "방어", "#3b82f6"


def classify_corr_value(value):
    if value >= 0.8:
        return "매우 높음", "거의 같은 방향으로 움직입니다. 분산 효과가 낮습니다."
    if value >= 0.5:
        return "높음", "비슷한 방향으로 움직이는 편입니다."
    if value > 0.3:
        return "보통", "어느 정도 같은 방향성이 있습니다."
    if value >= -0.3:
        return "낮음", "서로 크게 묶여 움직이지 않습니다."
    return "반대", "반대로 움직이는 경향이 있어 변동성 완충에 도움이 될 수 있습니다."


def annualize_period_return(period_return_decimal, observation_count):
    if not finite_num(period_return_decimal) or observation_count <= 0:
        return np.nan
    growth = 1 + float(period_return_decimal)
    if growth <= 0:
        return -1.0
    return float(growth ** (252 / observation_count) - 1)


def calc_downside_volatility(returns, target=0.0):
    returns = pd.Series(returns).dropna()
    if returns.empty:
        return np.nan
    downside = returns[returns < target] - target
    if downside.empty:
        return 0.0
    return float(downside.std() * np.sqrt(252))


def calc_var_cvar(returns, confidence=0.95):
    returns = pd.Series(returns).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 20:
        return np.nan, np.nan

    tail_cut = float(returns.quantile(1 - confidence))
    tail = returns[returns <= tail_cut]
    cvar = float(tail.mean()) if not tail.empty else tail_cut
    return tail_cut * 100, cvar * 100


def ratio_or_nan(numer, denom):
    if not finite_num(numer) or not finite_num(denom) or float(denom) == 0:
        return np.nan
    return float(numer) / float(denom)


def build_risk_contribution_df(asset_df, aligned_returns, weights):
    columns = ["자산명", "티커", "운용비중", "연환산변동성", "리스크기여도", "비중대비리스크"]
    if asset_df is None or asset_df.empty or aligned_returns is None or aligned_returns.empty or weights is None or weights.empty:
        return pd.DataFrame(columns=columns)

    cols = [col for col in weights.index if col in aligned_returns.columns]
    if len(cols) < 2:
        return pd.DataFrame(columns=columns)

    returns = aligned_returns[cols].replace([np.inf, -np.inf], np.nan).dropna(how="all").fillna(0.0)
    weights = weights[cols].astype(float)
    weight_sum = float(weights.sum())
    if weight_sum <= 0 or returns.empty:
        return pd.DataFrame(columns=columns)
    weights = weights / weight_sum

    cov = returns.cov() * 252
    portfolio_var = float(weights.T @ cov @ weights)
    if not np.isfinite(portfolio_var) or portfolio_var <= 0:
        return pd.DataFrame(columns=columns)

    marginal = cov.dot(weights)
    contribution = (weights * marginal / portfolio_var) * 100
    vol = returns.std() * np.sqrt(252) * 100

    name_map = {
        str(row.get("티커", "")): str(row.get("자산명", "") or row.get("티커", ""))
        for _, row in asset_df.iterrows()
    }

    rows = []
    for ticker in cols:
        weight_pct = float(weights.get(ticker, 0.0) * 100)
        contrib_pct = float(contribution.get(ticker, np.nan))
        rows.append({
            "자산명": name_map.get(ticker, ticker),
            "티커": ticker,
            "운용비중": weight_pct,
            "연환산변동성": float(vol.get(ticker, np.nan)),
            "리스크기여도": contrib_pct,
            "비중대비리스크": ratio_or_nan(contrib_pct, weight_pct),
        })

    return pd.DataFrame(rows, columns=columns).sort_values("리스크기여도", ascending=False).reset_index(drop=True)


def build_asset_label_map(asset_df):
    if asset_df is None or asset_df.empty or "티커" not in asset_df.columns:
        return {}

    base_by_ticker = {}
    label_counts = {}
    for _, row in asset_df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        if not ticker:
            continue
        name = str(row.get("자산명", "")).strip()
        base_label = name if name else ticker
        base_by_ticker[ticker] = base_label
        label_counts[base_label] = label_counts.get(base_label, 0) + 1

    label_map = {}
    used_labels = set()
    for ticker, base_label in base_by_ticker.items():
        label = f"{base_label} ({ticker})" if label_counts.get(base_label, 0) > 1 else base_label
        if label in used_labels:
            label = f"{base_label} ({ticker})"
        label_map[ticker] = label
        used_labels.add(label)

    return label_map


def build_correlation_pair_summary(corr_df):
    if corr_df is None or corr_df.empty or len(corr_df.columns) < 2:
        return pd.DataFrame(columns=["자산 A", "자산 B", "상관계수", "구분", "해석"])

    rows = []
    cols = list(corr_df.columns)
    for i, left in enumerate(cols):
        for j in range(i + 1, len(cols)):
            right = cols[j]
            value = clean_float(corr_df.loc[left, right], np.nan)
            if not np.isfinite(value):
                continue
            label, meaning = classify_corr_value(value)
            rows.append({
                "자산 A": left,
                "자산 B": right,
                "상관계수": value,
                "구분": label,
                "해석": meaning,
            })

    if not rows:
        return pd.DataFrame(columns=["자산 A", "자산 B", "상관계수", "구분", "해석"])

    df = pd.DataFrame(rows)
    df["_abs"] = df["상관계수"].abs()
    return df.sort_values(["상관계수", "_abs"], ascending=[False, False]).drop(columns="_abs").reset_index(drop=True)


def render_correlation_interpretation(corr_df, avg_corr):
    st.markdown("""
**읽는 법**
- 화면 표시는 티커가 아니라 자산명 기준입니다. 같은 자산명이 있으면 뒤에 티커를 붙여 구분합니다.
- 빨강에 가까울수록 같이 움직입니다. 여러 종목을 들고 있어도 한 방향으로 크게 흔들릴 수 있습니다.
- 흰색에 가까울수록 관계가 약합니다. 분산 효과가 상대적으로 있습니다.
- 파랑에 가까울수록 반대로 움직입니다. 하락 방어에 도움이 될 수 있지만 수익도 서로 상쇄될 수 있습니다.
    """)

    if np.isfinite(avg_corr):
        if avg_corr >= 0.7:
            st.warning(f"평균 상관계수는 {avg_corr:.2f}입니다. 포트폴리오가 한 방향으로 같이 움직이는 편입니다.")
        elif avg_corr >= 0.4:
            st.info(f"평균 상관계수는 {avg_corr:.2f}입니다. 일부 분산은 있지만 같은 방향성도 있습니다.")
        else:
            st.success(f"평균 상관계수는 {avg_corr:.2f}입니다. 자산 간 움직임이 비교적 덜 묶여 있습니다.")

    pair_df = build_correlation_pair_summary(corr_df)
    if not pair_df.empty:
        st.markdown("##### 상관관계 높은 조합")
        top_pairs = pair_df.head(5).copy()
        top_pairs["상관계수"] = top_pairs["상관계수"].apply(lambda v: f"{v:.2f}")
        st.dataframe(top_pairs, use_container_width=True, hide_index=True)


def build_portfolio_analysis_report(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight, period="1y"):
    total_asset = (
        float(holdings_table["원화환산"].sum()) if holdings_table is not None and not holdings_table.empty and "원화환산" in holdings_table.columns else 0.0
    ) + clean_float(krw_cash) + clean_float(usd_cash) * clean_float(usdkrw, 1400.0)

    full_df = append_cash_rows(
        holdings_table.copy() if holdings_table is not None else pd.DataFrame(),
        krw_cash,
        usd_cash,
        usdkrw,
        total_asset,
    )
    reserve_summary = calc_reserve_summary(full_df, reserve_target_weight)
    active_df = get_active_portfolio_rows(full_df)

    asset_rows = []
    price_series = {}
    notes = []

    if active_df.empty:
        add_portfolio_risk_note(notes, "참고", "분석 대상", "운용대상 보유자산이 없습니다.", "보유 종목을 등록하면 포트폴리오 분석이 표시됩니다.")

    active_value = float(active_df["원화환산"].sum()) if not active_df.empty else 0.0
    for _, row in active_df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        name = str(row.get("자산명", "")).strip()
        value_krw = clean_float(row.get("원화환산"), 0.0)
        weight_total = value_krw / total_asset * 100 if total_asset > 0 else 0.0
        weight_active = value_krw / active_value * 100 if active_value > 0 else 0.0

        row_info = {
            "자산명": name,
            "티커": ticker,
            "원화환산": value_krw,
            "전체비중": weight_total,
            "운용비중": weight_active,
            "기간수익률": np.nan,
            "연환산변동성": np.nan,
            "MDD": np.nan,
            "데이터": "부족",
        }

        try:
            px_df = load_price_df(ticker, period)
        except Exception:
            px_df = pd.DataFrame()

        if px_df is not None and not px_df.empty and "Close" in px_df.columns:
            close = pd.Series(px_df["Close"]).dropna()
            if len(close) >= 20:
                returns = close.pct_change().dropna()
                row_info["기간수익률"] = (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100 if close.iloc[0] else np.nan
                row_info["연환산변동성"] = float(returns.std() * np.sqrt(252) * 100) if not returns.empty else np.nan
                row_info["MDD"] = calc_series_mdd(close) * 100
                row_info["데이터"] = "정상"
                price_series[ticker] = close.rename(ticker)

        if row_info["데이터"] == "부족":
            add_portfolio_risk_note(notes, "참고", "가격 데이터", ticker, "가격 데이터가 부족해 변동성/MDD 계산에서 제외했습니다.")

        asset_rows.append(row_info)

    asset_df = pd.DataFrame(asset_rows, columns=[
        "자산명", "티커", "원화환산", "전체비중", "운용비중", "기간수익률", "연환산변동성", "MDD", "데이터"
    ])

    if not asset_df.empty:
        asset_df = asset_df.sort_values("전체비중", ascending=False).reset_index(drop=True)
    asset_label_map = build_asset_label_map(asset_df)

    top1_weight = float(asset_df["전체비중"].max()) if not asset_df.empty else 0.0
    top3_weight = float(asset_df["전체비중"].head(3).sum()) if not asset_df.empty else 0.0
    hhi = float(((asset_df["전체비중"] / 100) ** 2).sum()) if not asset_df.empty else 0.0

    portfolio_returns = pd.Series(dtype=float)
    portfolio_curve = pd.Series(dtype=float)
    corr_df = pd.DataFrame()
    portfolio_vol = np.nan
    portfolio_mdd = np.nan
    portfolio_period_return = np.nan
    portfolio_annual_return = np.nan
    portfolio_downside_vol = np.nan
    sharpe_ratio = np.nan
    sortino_ratio = np.nan
    calmar_ratio = np.nan
    daily_var_95 = np.nan
    daily_cvar_95 = np.nan
    monthly_var_95 = np.nan
    active_var_95_krw = np.nan
    active_cvar_95_krw = np.nan
    risk_contrib_df = pd.DataFrame()
    avg_corr = np.nan

    if price_series:
        prices = pd.concat(price_series.values(), axis=1).sort_index().ffill(limit=3)
        returns_df = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="all").fillna(0.0)

        usable_cols = [col for col in returns_df.columns if col in set(asset_df["티커"])]
        if usable_cols:
            weight_map = {
                str(row["티커"]): clean_float(row["운용비중"], 0.0) / 100
                for _, row in asset_df.iterrows()
                if str(row["티커"]) in usable_cols
            }
            weight_sum = sum(weight_map.values())
            if weight_sum > 0:
                weights = pd.Series({ticker: weight / weight_sum for ticker, weight in weight_map.items()})
                aligned_returns = returns_df[weights.index].copy()
                portfolio_returns = aligned_returns.mul(weights, axis=1).sum(axis=1)
                if not portfolio_returns.empty:
                    portfolio_curve = (1 + portfolio_returns).cumprod()
                    portfolio_vol_decimal = float(portfolio_returns.std() * np.sqrt(252))
                    portfolio_vol = portfolio_vol_decimal * 100
                    portfolio_mdd_decimal = calc_series_mdd(portfolio_curve)
                    portfolio_mdd = portfolio_mdd_decimal * 100
                    portfolio_period_return = (float(portfolio_curve.iloc[-1]) - 1) * 100
                    annual_return_decimal = annualize_period_return(portfolio_period_return / 100, len(portfolio_returns))
                    downside_vol_decimal = calc_downside_volatility(portfolio_returns)
                    portfolio_annual_return = annual_return_decimal * 100 if np.isfinite(annual_return_decimal) else np.nan
                    portfolio_downside_vol = downside_vol_decimal * 100 if np.isfinite(downside_vol_decimal) else np.nan
                    sharpe_ratio = ratio_or_nan(annual_return_decimal, portfolio_vol_decimal)
                    sortino_ratio = ratio_or_nan(annual_return_decimal, downside_vol_decimal)
                    calmar_ratio = ratio_or_nan(annual_return_decimal, abs(portfolio_mdd_decimal))
                    daily_var_95, daily_cvar_95 = calc_var_cvar(portfolio_returns, 0.95)
                    monthly_var_95 = daily_var_95 * np.sqrt(21) if np.isfinite(daily_var_95) else np.nan
                    active_var_95_krw = active_value * abs(daily_var_95) / 100 if np.isfinite(daily_var_95) else np.nan
                    active_cvar_95_krw = active_value * abs(daily_cvar_95) / 100 if np.isfinite(daily_cvar_95) else np.nan
                    risk_contrib_df = build_risk_contribution_df(asset_df, aligned_returns, weights)

                if len(weights.index) >= 2:
                    corr_df = aligned_returns.corr()
                    upper = corr_df.where(np.triu(np.ones(corr_df.shape), k=1).astype(bool))
                    avg_corr = float(np.nanmean(upper.values)) if np.isfinite(upper.values).any() else np.nan
                    corr_df = corr_df.rename(index=asset_label_map, columns=asset_label_map)

    vol_component = min(max(float(portfolio_vol) if np.isfinite(portfolio_vol) else 0.0, 0.0) * 1.1, 30)
    mdd_component = min(abs(float(portfolio_mdd)) if np.isfinite(portfolio_mdd) else 0.0, 30)
    concentration_component = min(top1_weight * 0.45 + top3_weight * 0.2 + hhi * 100 * 0.6, 25)
    corr_component = min(max(float(avg_corr) if np.isfinite(avg_corr) else 0.0, 0.0) * 15, 15)
    reserve_gap = max(float(reserve_target_weight) - float(reserve_summary.get("waiting_pct", 0.0)), 0.0)
    reserve_component = min(reserve_gap * 1.5, 15)
    risk_index = min(vol_component + mdd_component + concentration_component + corr_component + reserve_component, 100)
    risk_grade, risk_color = classify_portfolio_risk(risk_index)

    if top1_weight >= 35:
        add_portfolio_risk_note(notes, "주의", "집중도", f"1위 자산 비중이 {top1_weight:.1f}%입니다.", "단일 종목/ETF 의존도가 높은지 확인하세요.")
    if top3_weight >= 65:
        add_portfolio_risk_note(notes, "주의", "집중도", f"상위 3개 자산 비중이 {top3_weight:.1f}%입니다.", "의도한 집중 투자라면 괜찮지만, 분산 목적이면 비중을 나눠보세요.")
    if np.isfinite(portfolio_vol) and portfolio_vol >= 28:
        add_portfolio_risk_note(notes, "주의", "변동성", f"연환산 변동성이 {portfolio_vol:.1f}%입니다.", "매수 규모와 현금 비중을 보수적으로 점검하세요.")
    if np.isfinite(portfolio_mdd) and portfolio_mdd <= -25:
        add_portfolio_risk_note(notes, "주의", "낙폭", f"분석기간 MDD가 {portfolio_mdd:.1f}%입니다.", "큰 하락을 견딜 수 있는 포지션 크기인지 확인하세요.")
    if np.isfinite(avg_corr) and avg_corr >= 0.7:
        add_portfolio_risk_note(notes, "참고", "상관관계", f"평균 상관계수가 {avg_corr:.2f}입니다.", "종목 수가 많아도 비슷하게 움직일 수 있습니다.")
    if reserve_summary.get("waiting_pct", 0.0) + 0.1 < float(reserve_target_weight):
        add_portfolio_risk_note(notes, "참고", "방어력", f"대기자금 비중이 목표보다 {reserve_gap:.1f}%p 낮습니다.", "시장 변동성이 클 때 투입 여력을 따로 확보할지 확인하세요.")
    if np.isfinite(sharpe_ratio) and sharpe_ratio < 0:
        add_portfolio_risk_note(notes, "참고", "위험대비수익", f"Sharpe가 {sharpe_ratio:.2f}입니다.", "분석기간에는 변동성 대비 수익 보상이 낮았습니다.")
    if np.isfinite(daily_cvar_95) and daily_cvar_95 <= -4:
        add_portfolio_risk_note(notes, "주의", "꼬리위험", f"95% CVaR 기준 나쁜 날 평균 손실이 {daily_cvar_95:.1f}%입니다.", "급락일에 감내 가능한 손실 규모인지 확인하세요.")
    if risk_contrib_df is not None and not risk_contrib_df.empty:
        top_risk = risk_contrib_df.iloc[0]
        if clean_float(top_risk.get("리스크기여도"), 0.0) >= 45:
            add_portfolio_risk_note(notes, "주의", "리스크기여도", f"{top_risk.get('자산명')} 리스크 기여도가 {clean_float(top_risk.get('리스크기여도')):.1f}%입니다.", "비중보다 실제 변동성 영향이 큰 자산인지 확인하세요.")

    notes_df = pd.DataFrame(notes, columns=["등급", "영역", "내용", "확인/조치"])
    metrics = {
        "risk_index": risk_index,
        "risk_grade": risk_grade,
        "risk_color": risk_color,
        "portfolio_vol": portfolio_vol,
        "portfolio_mdd": portfolio_mdd,
        "portfolio_period_return": portfolio_period_return,
        "portfolio_annual_return": portfolio_annual_return,
        "portfolio_downside_vol": portfolio_downside_vol,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "daily_var_95": daily_var_95,
        "daily_cvar_95": daily_cvar_95,
        "monthly_var_95": monthly_var_95,
        "active_var_95_krw": active_var_95_krw,
        "active_cvar_95_krw": active_cvar_95_krw,
        "avg_corr": avg_corr,
        "top1_weight": top1_weight,
        "top3_weight": top3_weight,
        "hhi": hhi,
        "active_value": active_value,
        "total_asset": total_asset,
        "reserve_summary": reserve_summary,
        "usable_asset_count": len(price_series),
    }

    return metrics, asset_df, notes_df, corr_df, portfolio_curve, risk_contrib_df


def format_metric_pct(value, digits=1):
    return "-" if not np.isfinite(clean_float(value, np.nan)) else f"{clean_float(value):.{digits}f}%"


def format_metric_ratio(value, digits=2):
    return "-" if not np.isfinite(clean_float(value, np.nan)) else f"{clean_float(value):.{digits}f}"


def format_metric_money(value):
    return "-" if not np.isfinite(clean_float(value, np.nan)) else f"{clean_float(value):,.0f}원"


def calc_goal_monthly_return(annual_return_pct):
    annual = clean_float(annual_return_pct, 0.0) / 100
    if annual <= -0.999:
        annual = -0.999
    return float((1 + annual) ** (1 / 12) - 1)


def build_long_term_goal_path(start_amount, monthly_add, annual_return_pct, years):
    months = int(max(clean_float(years, 0), 0) * 12)
    monthly_return = calc_goal_monthly_return(annual_return_pct)
    value = clean_float(start_amount, 0.0)
    monthly_add = clean_float(monthly_add, 0.0)

    rows = [{
        "개월": 0,
        "연차": 0.0,
        "평가자산": value,
        "누적투입": value,
        "누적손익": 0.0,
    }]

    for month in range(1, months + 1):
        value = value * (1 + monthly_return) + monthly_add
        contributed = clean_float(start_amount, 0.0) + monthly_add * month
        rows.append({
            "개월": month,
            "연차": month / 12,
            "평가자산": value,
            "누적투입": contributed,
            "누적손익": value - contributed,
        })

    return pd.DataFrame(rows)


def calc_required_monthly_contribution(start_amount, target_amount, years, annual_return_pct):
    start_amount = clean_float(start_amount, 0.0)
    target_amount = clean_float(target_amount, 0.0)
    months = int(max(clean_float(years, 0), 0) * 12)
    if months <= 0:
        return np.nan

    monthly_return = calc_goal_monthly_return(annual_return_pct)
    growth_factor = (1 + monthly_return) ** months
    start_future = start_amount * growth_factor
    if start_future >= target_amount:
        return 0.0

    if abs(monthly_return) < 1e-12:
        annuity_factor = months
    else:
        annuity_factor = (growth_factor - 1) / monthly_return
    if annuity_factor <= 0:
        return np.nan

    return max((target_amount - start_future) / annuity_factor, 0.0)


def calc_required_annual_return(start_amount, monthly_add, target_amount, years):
    start_amount = clean_float(start_amount, 0.0)
    monthly_add = clean_float(monthly_add, 0.0)
    target_amount = clean_float(target_amount, 0.0)
    years = clean_float(years, 0.0)
    if years <= 0:
        return np.nan
    if start_amount >= target_amount:
        return 0.0

    def final_value(rate_pct):
        path = build_long_term_goal_path(start_amount, monthly_add, rate_pct, years)
        if path.empty:
            return start_amount
        return clean_float(path.iloc[-1].get("평가자산"), start_amount)

    low, high = -30.0, 60.0
    if final_value(high) < target_amount:
        return np.nan
    for _ in range(60):
        mid = (low + high) / 2
        if final_value(mid) >= target_amount:
            high = mid
        else:
            low = mid
    return high


def classify_goal_feasibility(required_return, required_monthly, monthly_add):
    if not np.isfinite(clean_float(required_return, np.nan)):
        return "공격적", "#ef4444", "현재 조건으로는 목표 수익률이 매우 높게 필요합니다."
    required_return = clean_float(required_return, 0.0)
    required_monthly = clean_float(required_monthly, 0.0)
    monthly_add = clean_float(monthly_add, 0.0)

    if required_return <= 7 and required_monthly <= monthly_add * 1.2 + 1:
        return "현실권", "#22c55e", "현재 가정이 유지되면 목표권에 가깝습니다."
    if required_return <= 10 or required_monthly <= monthly_add * 1.8 + 1:
        return "도전권", "#f59e0b", "월 추가투자나 목표수익률을 조금 더 챙겨야 합니다."
    return "공격적", "#ef4444", "목표가 크므로 기간, 월투자금, 기대수익률을 보수적으로 다시 점검하세요."


def render_long_term_goal_simulator(metrics):
    current_asset = clean_float(metrics.get("total_asset"), 0.0)
    if current_asset <= 0:
        return

    annual_default = clean_float(metrics.get("portfolio_annual_return"), np.nan)
    if not np.isfinite(annual_default) or annual_default < -10 or annual_default > 20:
        annual_default = 7.0
    annual_default = float(min(max(round(annual_default * 2) / 2, -10.0), 20.0))

    vol_default = clean_float(metrics.get("portfolio_vol"), np.nan)
    spread_default = 4.0 if not np.isfinite(vol_default) else float(min(max(round((vol_default / 4) * 2) / 2, 2.0), 8.0))
    target_default = int(max(current_asset * 2, current_asset + 100_000_000, 100_000_000))

    st.markdown("#### 10년 목표 시뮬레이션")
    st.caption("현재 총자산, 월 추가투자, 목표기간, 기대수익률을 넣어 장기 목표를 점검합니다. 배당 재투자까지 포함한 단순 복리 모델입니다.")

    i1, i2, i3, i4 = st.columns(4)
    with i1:
        years = st.slider("목표 기간(년)", min_value=3, max_value=30, value=10, step=1, key="long_goal_years")
    with i2:
        monthly_add = st.number_input("월 추가투자금", min_value=0, value=0, step=100000, key="long_goal_monthly_add")
    with i3:
        target_asset = st.number_input("목표 자산", min_value=0, value=target_default, step=10000000, key="long_goal_target_asset")
    with i4:
        base_return = st.slider("기준 연수익률(%)", min_value=-10.0, max_value=20.0, value=annual_default, step=0.5, key="long_goal_base_return")

    spread = st.slider("보수/낙관 시나리오 폭(%p)", min_value=1.0, max_value=12.0, value=spread_default, step=0.5, key="long_goal_spread")
    scenario_defs = [
        ("보수", base_return - spread, "#f97316"),
        ("기준", base_return, "#38bdf8"),
        ("낙관", base_return + spread, "#22c55e"),
    ]

    summary_rows = []
    fig = go.Figure()
    base_final = 0.0
    for label, rate, color in scenario_defs:
        path_df = build_long_term_goal_path(current_asset, monthly_add, rate, years)
        if path_df.empty:
            continue
        final_row = path_df.iloc[-1]
        final_asset = clean_float(final_row.get("평가자산"), 0.0)
        if label == "기준":
            base_final = final_asset
        summary_rows.append({
            "시나리오": label,
            "연수익률": rate,
            "최종자산": final_asset,
            "누적투입": clean_float(final_row.get("누적투입"), 0.0),
            "누적손익": clean_float(final_row.get("누적손익"), 0.0),
            "목표달성률": final_asset / target_asset * 100 if target_asset > 0 else np.nan,
        })
        fig.add_trace(go.Scatter(
            x=path_df["연차"],
            y=path_df["평가자산"],
            mode="lines",
            name=f"{label} {rate:.1f}%",
            line=dict(color=color, width=2),
            hovertemplate="%{x:.1f}년<br>예상자산: ₩%{y:,.0f}<extra></extra>",
        ))

    if target_asset > 0:
        fig.add_hline(y=target_asset, line_dash="dash", line_color="#eab308", annotation_text="목표 자산")

    req_monthly = calc_required_monthly_contribution(current_asset, target_asset, years, base_return)
    req_return = calc_required_annual_return(current_asset, monthly_add, target_asset, years)
    goal_ratio = base_final / target_asset * 100 if target_asset > 0 else np.nan
    feasibility, color, message = classify_goal_feasibility(req_return, req_monthly, monthly_add)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("현재 총자산", format_metric_money(current_asset))
    c2.metric("기준 최종자산", format_metric_money(base_final))
    c3.metric("목표달성률", format_metric_pct(goal_ratio))
    c4.markdown(
        f"<div class='info-panel' style='border-left:5px solid {color};'><b>목표 난이도</b><br>"
        f"<span class='highlight'>{escape_html_value(feasibility)}</span><br>{escape_html_value(message)}</div>",
        unsafe_allow_html=True,
    )

    need_cols = st.columns(2)
    need_cols[0].metric("필요 월투자금", format_metric_money(req_monthly))
    need_cols[1].metric("필요 연수익률", format_metric_pct(req_return))

    show_summary = pd.DataFrame(summary_rows)
    if not show_summary.empty:
        display_summary = show_summary.copy()
        display_summary["연수익률"] = display_summary["연수익률"].apply(format_metric_pct)
        for col in ["최종자산", "누적투입", "누적손익"]:
            display_summary[col] = display_summary[col].apply(format_metric_money)
        display_summary["목표달성률"] = display_summary["목표달성률"].apply(format_metric_pct)
        st.dataframe(display_summary, use_container_width=True, hide_index=True)

    fig.update_layout(
        template="plotly_dark",
        height=360,
        xaxis_title="기간(년)",
        yaxis_title="예상자산(원)",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("단순 복리 모델이라 세금, 수수료, 환율, 배당 변동, 실제 매수 타이밍은 반영하지 않습니다. 목표 점검용으로만 보세요.")


def render_portfolio_analysis_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight):
    st.subheader("포트폴리오 분석")
    st.caption("읽기 전용 분석입니다. 가격 기반 변동성, MDD, 집중도, 상관관계, 대기자금 비중을 함께 봅니다.")

    period = st.selectbox(
        "분석 기간",
        ["6mo", "1y", "2y", "5y"],
        index=1,
        key="portfolio_analysis_period",
        help="가격 데이터가 짧은 신규 ETF/종목은 일부 계산에서 제외될 수 있습니다.",
    )
    if not should_run_heavy_analysis(
        "portfolio_analysis_lazy",
        "상관관계와 포트폴리오 누적 흐름은 보유 종목별 가격 데이터를 조회하므로 필요할 때만 계산합니다.",
    ):
        return

    metrics, asset_df, notes_df, corr_df, portfolio_curve, risk_contrib_df = build_portfolio_analysis_report(
        holdings_table,
        krw_cash,
        usd_cash,
        usdkrw,
        reserve_target_weight,
        period=period,
    )

    reserve_summary = metrics["reserve_summary"]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.markdown(
        f"<div class='info-panel' style='border-left:5px solid {metrics['risk_color']};'><b>위험도</b><br>"
        f"<span class='highlight'>{metrics['risk_grade']}</span><br>{metrics['risk_index']:.0f}/100</div>",
        unsafe_allow_html=True,
    )
    m2.metric("연환산 변동성", "-" if not np.isfinite(metrics["portfolio_vol"]) else f"{metrics['portfolio_vol']:.1f}%")
    m3.metric("분석기간 MDD", "-" if not np.isfinite(metrics["portfolio_mdd"]) else f"{metrics['portfolio_mdd']:.1f}%")
    m4.metric("상위 3개 비중", f"{metrics['top3_weight']:.1f}%")
    m5.metric("대기자금", f"{reserve_summary.get('waiting_pct', 0.0):.1f}%")

    st.markdown("#### Risk Metrics")
    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric("연환산 수익률", format_metric_pct(metrics.get("portfolio_annual_return")))
    r2.metric("Sharpe", format_metric_ratio(metrics.get("sharpe_ratio")))
    r3.metric("Sortino", format_metric_ratio(metrics.get("sortino_ratio")))
    r4.metric("Calmar", format_metric_ratio(metrics.get("calmar_ratio")))
    r5.metric("95% VaR(1일)", format_metric_pct(metrics.get("daily_var_95")))

    tail_cols = st.columns(4)
    tail_cols[0].metric("95% CVaR(1일)", format_metric_pct(metrics.get("daily_cvar_95")))
    tail_cols[1].metric("95% VaR(월간 추정)", format_metric_pct(metrics.get("monthly_var_95")))
    tail_cols[2].metric("VaR 손실액", format_metric_money(metrics.get("active_var_95_krw")))
    tail_cols[3].metric("CVaR 손실액", format_metric_money(metrics.get("active_cvar_95_krw")))
    st.caption("Risk Metrics는 가격 데이터가 있는 운용자산 기준입니다. VaR/CVaR는 과거 일간수익률 기반의 참고 손실 추정치이며 미래 손실 한도가 아닙니다.")

    render_long_term_goal_simulator(metrics)

    if notes_df.empty:
        st.success("현재 기준으로 크게 눈에 띄는 포트폴리오 위험 신호는 없습니다.")
    else:
        st.markdown("#### 위험/분산 체크")
        st.dataframe(notes_df, use_container_width=True, hide_index=True)

    if asset_df.empty:
        st.info("분석할 운용대상 보유자산이 없습니다.")
        return

    show_df = asset_df.copy()
    for col in ["전체비중", "운용비중", "기간수익률", "연환산변동성", "MDD"]:
        if col in show_df.columns:
            show_df[col] = show_df[col].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.1f}%")
    if "원화환산" in show_df.columns:
        show_df["원화환산"] = show_df["원화환산"].apply(lambda v: f"{clean_float(v):,.0f}원")

    st.markdown("#### 자산별 위험 지표")
    st.dataframe(show_df, use_container_width=True, hide_index=True)
    st.download_button(
        "자산별 위험 지표 CSV 다운로드",
        data=dataframe_to_csv_bytes(asset_df),
        file_name=f"stock_lab_portfolio_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="download_portfolio_analysis_csv",
    )

    st.markdown("#### 리스크 기여도")
    st.caption("운용비중이 아니라 포트폴리오 전체 변동성에 실제로 얼마나 영향을 주는지 보는 표입니다.")
    if risk_contrib_df is not None and not risk_contrib_df.empty:
        contrib_show = risk_contrib_df.copy()
        for col in ["운용비중", "연환산변동성", "리스크기여도"]:
            contrib_show[col] = contrib_show[col].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.1f}%")
        contrib_show["비중대비리스크"] = contrib_show["비중대비리스크"].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.2f}x")
        st.dataframe(contrib_show, use_container_width=True, hide_index=True)

        top_contrib = risk_contrib_df.head(12).copy()
        fig_contrib = go.Figure()
        fig_contrib.add_trace(go.Bar(
            x=top_contrib["리스크기여도"],
            y=top_contrib["자산명"].where(top_contrib["자산명"].astype(str).str.strip().ne(""), top_contrib["티커"]),
            orientation="h",
            name="리스크기여도",
            marker_color="#f97316",
        ))
        fig_contrib.add_trace(go.Bar(
            x=top_contrib["운용비중"],
            y=top_contrib["자산명"].where(top_contrib["자산명"].astype(str).str.strip().ne(""), top_contrib["티커"]),
            orientation="h",
            name="운용비중",
            marker_color="#38bdf8",
        ))
        fig_contrib.update_layout(
            template="plotly_dark",
            height=max(360, min(620, 120 + len(top_contrib) * 34)),
            barmode="group",
            xaxis_title="비중/기여도(%)",
            yaxis=dict(autorange="reversed"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig_contrib, use_container_width=True)
    else:
        st.info("리스크 기여도는 가격 데이터가 있는 운용자산이 2개 이상일 때 표시됩니다.")

    chart_l, chart_r = st.columns([1.2, 1])
    with chart_l:
        st.markdown("#### 포트폴리오 누적 흐름")
        if portfolio_curve is not None and not portfolio_curve.empty:
            fig_curve = go.Figure()
            fig_curve.add_trace(go.Scatter(
                x=portfolio_curve.index,
                y=(portfolio_curve - 1) * 100,
                mode="lines",
                name="포트폴리오",
                line=dict(color="#38bdf8", width=2),
            ))
            fig_curve.update_layout(
                template="plotly_dark",
                height=360,
                yaxis_title="누적수익률(%)",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_curve, use_container_width=True)
        else:
            st.info("누적 흐름을 계산할 가격 데이터가 부족합니다.")

    with chart_r:
        st.markdown("#### 현재 비중")
        fig_weight = go.Figure(go.Bar(
            x=asset_df["전체비중"],
            y=asset_df["자산명"].where(asset_df["자산명"].astype(str).str.strip().ne(""), asset_df["티커"]),
            orientation="h",
            marker_color="#22c55e",
        ))
        fig_weight.update_layout(
            template="plotly_dark",
            height=360,
            xaxis_title="전체비중(%)",
            yaxis=dict(autorange="reversed"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_weight, use_container_width=True)

    st.markdown("#### 상관관계")
    if corr_df is not None and not corr_df.empty and len(corr_df.columns) >= 2:
        fig_corr = go.Figure(data=go.Heatmap(
            z=corr_df.values,
            x=corr_df.columns,
            y=corr_df.index,
            zmin=-1,
            zmax=1,
            zmid=0,
            colorscale=[
                [0.0, "#2563eb"],
                [0.35, "#93c5fd"],
                [0.5, "#f8fafc"],
                [0.65, "#fecaca"],
                [1.0, "#dc2626"],
            ],
            xgap=1,
            ygap=1,
            hovertemplate="%{y} vs %{x}<br>상관계수: %{z:.2f}<extra></extra>",
            colorbar=dict(
                title="상관",
                tickmode="array",
                tickvals=[-1, -0.3, 0, 0.3, 1],
                ticktext=["반대", "-0.3", "약함", "+0.3", "같이"],
            ),
        ))
        fig_corr.update_layout(
            template="plotly_dark",
            height=max(360, min(720, 80 + len(corr_df.columns) * 38)),
            xaxis=dict(
                title="빨강=같이 움직임 / 흰색=관계 약함 / 파랑=반대 움직임",
                tickangle=-35,
                automargin=True,
            ),
            yaxis=dict(autorange="reversed", automargin=True),
            margin=dict(l=120, r=40, t=30, b=110),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_corr, use_container_width=True)
        render_correlation_interpretation(corr_df, metrics.get("avg_corr", np.nan))
    else:
        st.info("상관관계는 가격 데이터가 있는 운용자산이 2개 이상일 때 표시됩니다.")


def format_scenario_money(value):
    return f"{clean_float(value):,.0f}원"


def format_scenario_pct(value):
    return f"{clean_float(value):.1f}%"


def infer_scenario_shock_multiplier(row):
    ticker = str(row.get("티커", row.get("ticker", ""))).strip().upper()
    name = str(row.get("자산명", row.get("name", ""))).strip().upper()
    asset_class = str(row.get("asset_class", "")).strip().upper()
    text = f"{ticker} {name} {asset_class}"

    inverse = any(keyword in text for keyword in [
        "INVERSE", "인버스", "곱버스", "BEAR", "SHORT", "SQQQ", "SOXS", "SPXU", "SDS", "PSQ", "SH",
    ])

    multiplier = 1.0
    if any(keyword in text for keyword in ["3X", "3배", "TQQQ", "SOXL", "SQQQ", "SOXS", "SPXL", "SPXU", "UPRO", "TECL", "FNGU", "BULZ"]):
        multiplier = 3.0
    elif any(keyword in text for keyword in ["2X", "2배", "QLD", "SSO", "ROM", "USD", "UWM", "SDS", "QID"]):
        multiplier = 2.0
    elif any(keyword in text for keyword in ["레버리지", "LEVERAGE", "LEVERAGED"]):
        multiplier = 2.0

    return -multiplier if inverse else multiplier


def build_scenario_context(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight):
    total_asset = (
        float(holdings_table["원화환산"].sum()) if holdings_table is not None and not holdings_table.empty and "원화환산" in holdings_table.columns else 0.0
    ) + clean_float(krw_cash) + clean_float(usd_cash) * clean_float(usdkrw, 1400.0)
    full_df = append_cash_rows(
        holdings_table.copy() if holdings_table is not None else pd.DataFrame(),
        krw_cash,
        usd_cash,
        usdkrw,
        total_asset,
    )
    active_df = get_active_portfolio_rows(full_df)
    reserve_summary = calc_reserve_summary(full_df, reserve_target_weight)
    label_map = build_asset_label_map(active_df)

    return {
        "total_asset": total_asset,
        "full_df": full_df,
        "active_df": active_df,
        "reserve_summary": reserve_summary,
        "label_map": label_map,
    }


def calc_asset_shock_table(active_df, total_asset, shock_pct, use_multiplier=True):
    if active_df is None or active_df.empty:
        return pd.DataFrame(columns=["자산", "티커", "현재금액", "현재비중", "적용충격", "예상손익", "충격후금액", "충격배수"])

    label_map = build_asset_label_map(active_df)
    rows = []
    for _, row in active_df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        value = clean_float(row.get("원화환산"), 0.0)
        multiplier = infer_scenario_shock_multiplier(row) if use_multiplier else 1.0
        applied_shock = clean_float(shock_pct, 0.0) * multiplier
        pnl = value * applied_shock / 100
        rows.append({
            "자산": label_map.get(ticker, str(row.get("자산명", "")).strip() or ticker),
            "티커": ticker,
            "현재금액": value,
            "현재비중": value / total_asset * 100 if total_asset > 0 else 0.0,
            "적용충격": applied_shock,
            "예상손익": pnl,
            "충격후금액": max(value + pnl, 0.0),
            "충격배수": multiplier,
        })

    return pd.DataFrame(rows).sort_values("예상손익").reset_index(drop=True)


def build_market_scenario_summary(active_df, total_asset, shock_values, use_multiplier=True):
    rows = []
    for shock_pct in shock_values:
        detail_df = calc_asset_shock_table(active_df, total_asset, shock_pct, use_multiplier)
        total_pnl = float(detail_df["예상손익"].sum()) if not detail_df.empty else 0.0
        after_asset = total_asset + total_pnl
        rows.append({
            "시나리오": f"운용자산 {shock_pct:+.0f}%",
            "기본충격": shock_pct,
            "예상손익": total_pnl,
            "충격후자산": after_asset,
            "총자산변화율": total_pnl / total_asset * 100 if total_asset > 0 else 0.0,
        })

    return pd.DataFrame(rows)


def build_cash_buffer_scenario(active_df, total_asset, reserve_summary, target_waiting_pct, shock_pct, use_multiplier=True):
    active_value = float(active_df["원화환산"].sum()) if active_df is not None and not active_df.empty else 0.0
    current_waiting_pct = clean_float(reserve_summary.get("waiting_pct"), 0.0)
    target_waiting_pct = clean_float(target_waiting_pct, current_waiting_pct)
    additional_waiting = max(total_asset * (target_waiting_pct - current_waiting_pct) / 100, 0.0)

    current_detail = calc_asset_shock_table(active_df, total_asset, shock_pct, use_multiplier)
    current_loss = float(current_detail["예상손익"].sum()) if not current_detail.empty else 0.0

    if active_value <= 0:
        rebalanced_loss = current_loss
    else:
        exposure_ratio = max((active_value - additional_waiting) / active_value, 0.0)
        rebalanced_loss = current_loss * exposure_ratio

    return {
        "current_waiting_pct": current_waiting_pct,
        "target_waiting_pct": target_waiting_pct,
        "additional_waiting": additional_waiting,
        "current_loss": current_loss,
        "rebalanced_loss": rebalanced_loss,
        "loss_reduction": rebalanced_loss - current_loss,
        "current_after_asset": total_asset + current_loss,
        "rebalanced_after_asset": total_asset + rebalanced_loss,
    }


def render_scenario_check_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight):
    st.subheader("시나리오 점검")
    st.caption("미래 예측이 아니라 현재 보유자산에 가상의 충격률을 넣어보는 읽기 전용 점검입니다.")

    if not should_run_heavy_analysis(
        "scenario_check_lazy",
        "하락 시나리오는 가볍지만 첫 화면에서는 생략하고, 필요할 때 계산합니다.",
    ):
        return

    context = build_scenario_context(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight)
    total_asset = context["total_asset"]
    active_df = context["active_df"]
    reserve_summary = context["reserve_summary"]

    if active_df.empty:
        st.info("시나리오를 계산할 운용대상 보유자산이 없습니다.")
        return

    use_multiplier = st.checkbox(
        "레버리지/인버스 배수 추정 반영",
        value=True,
        key="scenario_use_leverage_multiplier",
        help="TQQQ, QLD, 레버리지, 인버스 같은 단서를 보고 충격률을 2배/3배 또는 반대로 추정합니다.",
    )

    scenario_shocks = [-5, -10, -20, -30]
    summary_df = build_market_scenario_summary(active_df, total_asset, scenario_shocks, use_multiplier)
    selected_shock = st.select_slider(
        "상세 분석 충격률",
        options=[-5, -10, -15, -20, -25, -30, -40, -50],
        value=-20,
        key="scenario_selected_shock",
    )
    detail_df = calc_asset_shock_table(active_df, total_asset, selected_shock, use_multiplier)
    selected_pnl = float(detail_df["예상손익"].sum()) if not detail_df.empty else 0.0
    selected_after = total_asset + selected_pnl

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("현재 총자산", format_scenario_money(total_asset))
    s2.metric(f"{selected_shock}% 충격 손익", format_scenario_money(selected_pnl))
    s3.metric("충격 후 총자산", format_scenario_money(selected_after))
    s4.metric("총자산 변화율", format_scenario_pct(selected_pnl / total_asset * 100 if total_asset > 0 else 0.0))

    st.markdown("#### 전체 하락 시나리오")
    show_summary = summary_df.copy()
    for col in ["예상손익", "충격후자산"]:
        show_summary[col] = show_summary[col].apply(format_scenario_money)
    show_summary["총자산변화율"] = show_summary["총자산변화율"].apply(format_scenario_pct)
    st.dataframe(show_summary, use_container_width=True, hide_index=True)

    fig_summary = go.Figure(go.Bar(
        x=summary_df["시나리오"],
        y=summary_df["예상손익"],
        marker_color=["#ef4444" if v < 0 else "#22c55e" for v in summary_df["예상손익"]],
        hovertemplate="%{x}<br>예상손익: ₩%{y:,.0f}<extra></extra>",
    ))
    fig_summary.update_layout(
        template="plotly_dark",
        height=320,
        yaxis_title="예상손익(원)",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_summary, use_container_width=True)

    st.markdown("#### 손실 기여 상위")
    top_loss_df = detail_df.sort_values("예상손익").head(10).copy()
    show_loss_df = top_loss_df.copy()
    for col in ["현재금액", "예상손익", "충격후금액"]:
        show_loss_df[col] = show_loss_df[col].apply(format_scenario_money)
    for col in ["현재비중", "적용충격"]:
        show_loss_df[col] = show_loss_df[col].apply(format_scenario_pct)
    show_loss_df["충격배수"] = show_loss_df["충격배수"].apply(lambda v: f"{clean_float(v):.1f}x")
    st.dataframe(show_loss_df, use_container_width=True, hide_index=True)

    asset_options = list(detail_df["자산"]) if not detail_df.empty else []
    if asset_options:
        st.markdown("#### 개별 자산 충격")
        a1, a2 = st.columns([2, 1])
        with a1:
            selected_asset = st.selectbox("자산 선택", asset_options, key="single_asset_scenario_target")
        with a2:
            asset_shock = st.slider("자산 충격률", min_value=-80, max_value=50, value=-20, step=5, key="single_asset_scenario_shock")

        selected_row = detail_df[detail_df["자산"] == selected_asset].iloc[0]
        asset_value = clean_float(selected_row["현재금액"], 0.0)
        single_pnl = asset_value * clean_float(asset_shock) / 100
        single_after_total = total_asset + single_pnl
        c1, c2, c3 = st.columns(3)
        c1.metric("해당 자산 현재금액", format_scenario_money(asset_value))
        c2.metric("개별 충격 손익", format_scenario_money(single_pnl))
        c3.metric("충격 후 총자산", format_scenario_money(single_after_total))

    st.markdown("#### 대기자금 방어 시뮬레이션")
    target_waiting_default = int(round(max(reserve_summary.get("waiting_pct", 0.0), reserve_target_weight)))
    target_waiting_default = min(max(target_waiting_default, 0), 80)
    b1, b2 = st.columns([1, 1])
    with b1:
        target_waiting_pct = st.slider(
            "목표 대기자금 비중",
            min_value=0,
            max_value=80,
            value=target_waiting_default,
            step=5,
            key="scenario_target_waiting_pct",
        )
    with b2:
        buffer_shock = st.select_slider(
            "방어 효과 계산 충격률",
            options=[-5, -10, -15, -20, -25, -30, -40, -50],
            value=selected_shock,
            key="scenario_buffer_shock",
        )

    buffer = build_cash_buffer_scenario(active_df, total_asset, reserve_summary, target_waiting_pct, buffer_shock, use_multiplier)
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("현재 대기자금", format_scenario_pct(buffer["current_waiting_pct"]))
    d2.metric("추가 확보 필요", format_scenario_money(buffer["additional_waiting"]))
    d3.metric("현재 구조 손익", format_scenario_money(buffer["current_loss"]))
    d4.metric("목표 구조 손익", format_scenario_money(buffer["rebalanced_loss"]))

    if buffer["additional_waiting"] > 0 and buffer["loss_reduction"] > 0:
        st.success(f"목표 대기자금까지 올리면 {buffer_shock}% 충격에서 손실을 약 {format_scenario_money(buffer['loss_reduction'])} 줄이는 계산입니다.")
    elif buffer["additional_waiting"] <= 0:
        st.info("현재 대기자금 비중이 목표 이상입니다.")
    else:
        st.info("대기자금 조정 효과가 작거나 계산할 운용자산이 부족합니다.")

    st.warning("이 탭은 가정 계산입니다. 실제 시장에서는 종목별 하락률, 환율, 괴리율, 레버리지 일일복리 효과가 다르게 나타날 수 있습니다.")


def get_short_trend_label(score):
    if score >= 5:
        return "상승우위", "#22c55e"
    if score >= 2:
        return "상승시도", "#84cc16"
    if score <= -5:
        return "하락우위", "#ef4444"
    if score <= -2:
        return "하락주의", "#f97316"
    return "중립", "#94a3b8"


def calc_pct_change_from_series(series, lookback):
    series = pd.Series(series).dropna()
    if len(series) <= lookback:
        return np.nan
    base = clean_float(series.iloc[-lookback - 1], 0.0)
    last = clean_float(series.iloc[-1], 0.0)
    if base <= 0:
        return np.nan
    return (last / base - 1) * 100


def build_short_trend_universe(holdings_table, watchlist_items):
    rows = []
    seen = set()

    if holdings_table is not None and not holdings_table.empty:
        for _, row in holdings_table.iterrows():
            ticker = str(row.get("티커", "")).strip()
            if not ticker or ticker.upper() in ["KRW_CASH", "USD_CASH"]:
                continue
            key = normalize_ticker(ticker)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({
                "name": str(row.get("자산명", "")).strip() or ticker,
                "ticker": ticker,
                "asset_class": str(row.get("asset_class", "")).strip(),
                "is_etf": clean_bool(row.get("is_etf", False)),
                "source": "보유",
                "weight": clean_float(row.get("현재비중"), 0.0),
            })

    for item in watchlist_items or []:
        ticker = str(item.get("ticker", "")).strip()
        if not ticker:
            continue
        key = normalize_ticker(ticker)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append({
            "name": str(item.get("name", "")).strip() or ticker,
            "ticker": ticker,
            "asset_class": str(item.get("asset_class", "")).strip(),
            "is_etf": clean_bool(item.get("is_etf", False)),
            "source": "관심",
            "weight": 0.0,
        })

    return pd.DataFrame(rows, columns=["name", "ticker", "asset_class", "is_etf", "source", "weight"])


def analyze_short_trend_item(item, period="6mo"):
    name = str(item.get("name", "")).strip()
    ticker = str(item.get("ticker", "")).strip()
    asset_class = str(item.get("asset_class", "")).strip()
    is_etf = is_fin_score_exempt_asset(ticker, item.get("is_etf", False), asset_class, name)

    base_row = {
        "자산명": name or ticker,
        "티커": ticker,
        "구분": str(item.get("source", "")).strip(),
        "현재비중": clean_float(item.get("weight"), 0.0),
        "단기전망": "데이터부족",
        "점수": 0,
        "현재가": np.nan,
        "5일": np.nan,
        "20일": np.nan,
        "60일": np.nan,
        "RSI": np.nan,
        "MACD": "-",
        "MA상태": "-",
        "예상범위": "-",
        "핵심근거": "가격 데이터가 부족합니다.",
    }

    try:
        price_df = load_price_df(ticker, period)
    except Exception as exc:
        base_row["핵심근거"] = f"가격 데이터 조회 실패: {exc}"
        return base_row, pd.DataFrame()

    if price_df is None or price_df.empty or len(price_df) < 35:
        return base_row, price_df if price_df is not None else pd.DataFrame()

    try:
        df = build_indicators(price_df)
    except Exception as exc:
        base_row["핵심근거"] = f"지표 계산 실패: {exc}"
        return base_row, price_df

    df = df.dropna(subset=["Close"]).copy()
    if len(df) < 35:
        return base_row, df

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = pd.Series(df["Close"]).dropna()
    cur = clean_float(close.iloc[-1], np.nan)
    ret5 = calc_pct_change_from_series(close, 5)
    ret20 = calc_pct_change_from_series(close, 20)
    ret60 = calc_pct_change_from_series(close, 60)
    ma5 = clean_float(last.get("MA5"), np.nan)
    ma20 = clean_float(last.get("MA20"), np.nan)
    ma20_prev5 = clean_float(df["MA20"].iloc[-6], np.nan) if len(df) >= 26 else np.nan
    ma20_slope = (ma20 / ma20_prev5 - 1) * 100 if np.isfinite(ma20) and np.isfinite(ma20_prev5) and ma20_prev5 > 0 else np.nan
    rsi = clean_float(last.get("RSI"), np.nan)
    macd = clean_float(last.get("MACD"), np.nan)
    macd_sig = clean_float(last.get("MACD_Sig"), np.nan)
    prev_macd = clean_float(prev.get("MACD"), np.nan)
    pct_b = clean_float(last.get("%B"), np.nan)
    volume = clean_float(last.get("Volume"), 0.0)
    volume_ma20 = clean_float(df["Volume"].rolling(20).mean().iloc[-1], 0.0) if "Volume" in df.columns else 0.0
    volume_ratio = volume / volume_ma20 if volume_ma20 > 0 else np.nan
    daily_vol = close.pct_change().dropna().tail(20).std()
    expected_range = float(daily_vol * np.sqrt(20) * 100) if np.isfinite(daily_vol) else np.nan

    score = 0
    reasons = []

    if np.isfinite(ma5) and np.isfinite(ma20):
        if ma5 > ma20 and np.isfinite(ma20_slope) and ma20_slope > 0:
            score += 2
            reasons.append("MA5>MA20, MA20 상승")
            ma_state = "상승"
        elif ma5 < ma20 and np.isfinite(ma20_slope) and ma20_slope < 0:
            score -= 2
            reasons.append("MA5<MA20, MA20 하락")
            ma_state = "하락"
        else:
            ma_state = "혼조"
    else:
        ma_state = "부족"

    if np.isfinite(ret20):
        if ret20 > 3:
            score += 1
            reasons.append("20일 수익률 양호")
        elif ret20 < -3:
            score -= 1
            reasons.append("20일 수익률 부진")

    if np.isfinite(ret5):
        if ret5 > 1:
            score += 1
            reasons.append("5일 단기 반등")
        elif ret5 < -1:
            score -= 1
            reasons.append("5일 단기 약세")

    if np.isfinite(cur) and np.isfinite(ma20):
        if cur > ma20:
            score += 1
            reasons.append("현재가 MA20 위")
        else:
            score -= 1
            reasons.append("현재가 MA20 아래")

    if np.isfinite(macd) and np.isfinite(macd_sig):
        macd_rising = np.isfinite(prev_macd) and macd > prev_macd
        if macd > macd_sig and macd_rising:
            score += 2
            macd_state = "상승가속"
            reasons.append("MACD 상승")
        elif macd > macd_sig:
            score += 1
            macd_state = "상승유지"
            reasons.append("MACD 양호")
        elif macd < macd_sig and not macd_rising:
            score -= 2
            macd_state = "하락가속"
            reasons.append("MACD 하락")
        else:
            score -= 1
            macd_state = "약세둔화"
    else:
        macd_state = "-"

    if np.isfinite(rsi):
        if 45 <= rsi <= 65:
            score += 1
            reasons.append("RSI 정상 상승권")
        elif rsi < 38:
            score -= 1
            reasons.append("RSI 약세권")
        elif rsi >= 75:
            score -= 1
            reasons.append("RSI 과열권")

    if np.isfinite(volume_ratio) and volume_ratio >= 1.2 and np.isfinite(ret5):
        if ret5 > 0:
            score += 1
            reasons.append("거래량 동반 상승")
        elif ret5 < 0:
            score -= 1
            reasons.append("거래량 동반 하락")

    if np.isfinite(pct_b) and pct_b > 1.05:
        score -= 1
        reasons.append("볼린저 상단 과열")

    if is_etf and score <= -1 and np.isfinite(ret20) and ret20 > 0:
        reasons.append("ETF는 추세/비중 중심 확인")

    label, _ = get_short_trend_label(score)
    base_row.update({
        "단기전망": label,
        "점수": int(score),
        "현재가": cur,
        "5일": ret5,
        "20일": ret20,
        "60일": ret60,
        "RSI": rsi,
        "MACD": macd_state,
        "MA상태": ma_state,
        "예상범위": "-" if not np.isfinite(expected_range) else f"±{expected_range:.1f}%",
        "핵심근거": " / ".join(reasons[:4]) if reasons else "뚜렷한 단기 우위 신호 없음",
    })
    return base_row, df


def build_short_trend_report(holdings_table, watchlist_items, period="6mo"):
    universe_df = build_short_trend_universe(holdings_table, watchlist_items)
    rows = []
    charts = {}
    if universe_df.empty:
        return pd.DataFrame(), charts

    for _, item in universe_df.iterrows():
        row, df = analyze_short_trend_item(item, period)
        rows.append(row)
        if df is not None and not df.empty:
            charts[str(row["티커"])] = df

    result_df = pd.DataFrame(rows)
    if not result_df.empty:
        order_map = {"상승우위": 0, "상승시도": 1, "중립": 2, "하락주의": 3, "하락우위": 4, "데이터부족": 5}
        result_df["_order"] = result_df["단기전망"].map(order_map).fillna(9)
        result_df = result_df.sort_values(["_order", "점수", "현재비중"], ascending=[True, False, False]).drop(columns="_order").reset_index(drop=True)
    return result_df, charts


def render_short_trend_tab(holdings_table, watchlist_items):
    st.subheader("단기 흐름 점검")
    st.caption("2~4주 단기 흐름을 현재 지표로 점검합니다. 미래를 맞히는 예측이 아니라 추세/모멘텀 기반 전망입니다.")

    period = st.selectbox(
        "분석 데이터 기간",
        ["3mo", "6mo", "1y"],
        index=1,
        key="short_trend_period",
        help="3개월은 민감하고, 1년은 더 안정적입니다.",
    )
    if not should_run_heavy_analysis(
        "short_trend_lazy",
        "단기 흐름 점검은 보유/관심 종목 가격을 종목별로 조회하므로 필요할 때만 계산합니다.",
    ):
        return
    trend_df, chart_map = build_short_trend_report(holdings_table, watchlist_items, period)

    if trend_df.empty:
        st.info("분석할 보유자산 또는 관심종목이 없습니다.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("상승우위", int((trend_df["단기전망"] == "상승우위").sum()))
    c2.metric("상승시도", int((trend_df["단기전망"] == "상승시도").sum()))
    c3.metric("하락주의", int((trend_df["단기전망"] == "하락주의").sum()))
    c4.metric("하락우위", int((trend_df["단기전망"] == "하락우위").sum()))

    selected_labels = st.multiselect(
        "전망 필터",
        ["상승우위", "상승시도", "중립", "하락주의", "하락우위", "데이터부족"],
        default=["상승우위", "상승시도", "중립", "하락주의", "하락우위"],
        key="short_trend_filter",
    )
    filtered_df = trend_df[trend_df["단기전망"].isin(selected_labels)] if selected_labels else trend_df.iloc[0:0]

    show_df = filtered_df.copy()
    for col in ["현재비중", "5일", "20일", "60일"]:
        if col in show_df.columns:
            show_df[col] = show_df[col].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.1f}%")
    if "RSI" in show_df.columns:
        show_df["RSI"] = show_df["RSI"].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.1f}")
    if "현재가" in show_df.columns:
        show_df["현재가"] = show_df["현재가"].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):,.2f}")

    st.markdown("#### 단기 전망표")
    st.dataframe(show_df, use_container_width=True, hide_index=True)
    st.download_button(
        "단기 흐름 CSV 다운로드",
        data=dataframe_to_csv_bytes(trend_df),
        file_name=f"stock_lab_short_trend_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="download_short_trend_csv",
    )

    chart_options = [f"{row['자산명']}|{row['티커']}" for _, row in trend_df.iterrows() if str(row.get("티커", "")) in chart_map]
    if chart_options:
        st.markdown("#### 선택 종목 흐름")
        selected = st.selectbox("차트 종목", chart_options, key="short_trend_chart_target")
        selected_name, selected_ticker = selected.rsplit("|", 1)
        chart_df = chart_map.get(selected_ticker)
        selected_row = trend_df[trend_df["티커"] == selected_ticker].iloc[0]

        if chart_df is not None and not chart_df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["Close"], mode="lines", name="Close", line=dict(color="#e5e7eb", width=2)))
            if "MA5" in chart_df.columns:
                fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MA5"], mode="lines", name="MA5", line=dict(color="#38bdf8", width=1.5)))
            if "MA20" in chart_df.columns:
                fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MA20"], mode="lines", name="MA20", line=dict(color="#fbbf24", width=1.5)))

            current_price = clean_float(selected_row.get("현재가"), np.nan)
            range_text = str(selected_row.get("예상범위", ""))
            range_pct = clean_float(range_text.replace("±", "").replace("%", ""), np.nan)
            if np.isfinite(current_price) and np.isfinite(range_pct):
                fig.add_hline(y=current_price * (1 + range_pct / 100), line_dash="dot", line_color="#22c55e", annotation_text="예상상단")
                fig.add_hline(y=current_price * (1 - range_pct / 100), line_dash="dot", line_color="#ef4444", annotation_text="예상하단")

            fig.update_layout(
                template="plotly_dark",
                height=460,
                title=f"{selected_name} 단기 흐름",
                xaxis_rangeslider_visible=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            )
            st.plotly_chart(fig, use_container_width=True)

            label, color = get_short_trend_label(clean_int(selected_row.get("점수"), 0))
            st.markdown(
                f"<div class='info-panel' style='border-left:5px solid {color};'><b>{selected_name}</b><br>"
                f"전망: <span class='highlight'>{label}</span> | 점수: {int(selected_row.get('점수', 0))}<br>"
                f"근거: {escape_html_value(selected_row.get('핵심근거', ''))}</div>",
                unsafe_allow_html=True,
            )

    with st.expander("점수 해석"):
        st.markdown("""
- **상승우위**: MA, MACD, 단기 수익률이 같이 우호적인 상태입니다.
- **상승시도**: 상승 단서가 있지만 아직 확정적이지 않은 상태입니다.
- **중립**: 방향성이 애매하거나 신호가 서로 엇갈립니다.
- **하락주의**: MA/MACD/단기 수익률 중 약세 신호가 우세합니다.
- **하락우위**: 여러 약세 신호가 겹친 상태입니다.
- **예상범위**: 최근 20거래일 변동성으로 계산한 2~4주 참고 범위입니다. 실제 목표가가 아닙니다.
        """)


def calc_forward_return(close_series, idx, horizon):
    if idx + horizon >= len(close_series):
        return np.nan
    entry = clean_float(close_series.iloc[idx], np.nan)
    future = clean_float(close_series.iloc[idx + horizon], np.nan)
    if not finite_num(entry) or not finite_num(future) or entry <= 0:
        return np.nan
    return (future / entry - 1) * 100


def calc_forward_drawdown(close_series, idx, horizon):
    if idx + 1 >= len(close_series):
        return np.nan
    end_idx = min(idx + horizon, len(close_series) - 1)
    entry = clean_float(close_series.iloc[idx], np.nan)
    window = pd.Series(close_series.iloc[idx + 1:end_idx + 1]).dropna()
    if not finite_num(entry) or entry <= 0 or window.empty:
        return np.nan
    return (clean_float(window.min(), np.nan) / entry - 1) * 100


def build_signal_backtest_universe(holdings_table, watchlist_items):
    universe_df = build_short_trend_universe(holdings_table, watchlist_items)
    if universe_df.empty:
        return pd.DataFrame(columns=["label", "name", "ticker", "asset_class", "is_etf"])

    rows = []
    for _, row in universe_df.iterrows():
        ticker = sanitize_ticker_value(row.get("ticker", ""))
        name = sanitize_asset_name(row.get("name", ""), ticker)
        if not ticker:
            continue
        rows.append({
            "label": f"{name} | {ticker}",
            "name": name,
            "ticker": ticker,
            "asset_class": str(row.get("asset_class", "") or "").strip(),
            "is_etf": clean_bool(row.get("is_etf", False)),
        })
    return pd.DataFrame(rows)


def build_signal_backtest(ticker, name, asset_class, signal_type, period="2y", min_gap=10):
    price_df = load_price_df(ticker, period)
    if price_df is None or price_df.empty or len(price_df) < 140:
        return pd.DataFrame(), pd.DataFrame(), f"{ticker} 가격 데이터가 부족합니다."

    df = build_indicators(price_df).copy()
    df = df.dropna(subset=["Close"]).copy()
    if len(df) < 140:
        return pd.DataFrame(), df, f"{ticker} 지표 계산 데이터가 부족합니다."

    close = pd.Series(df["Close"]).astype(float)
    df["RET20"] = close.pct_change(20) * 100
    df["DAY_RET"] = close.pct_change() * 100
    df["VOL_RATIO"] = df["Volume"] / df["Volume"].rolling(20).mean()
    df["ROLL_HIGH"] = df["High"].rolling(252, min_periods=60).max()
    df["MDD_52W"] = df["Close"] / df["ROLL_HIGH"] - 1
    df["MACD_RISING"] = df["MACD"] > df["MACD"].shift(1)

    bench = get_rs_benchmark(ticker, asset_class)
    if bench and normalize_ticker(bench) != normalize_ticker(ticker):
        try:
            bench_df = load_price_df(bench, period)
            if bench_df is not None and not bench_df.empty:
                if isinstance(bench_df.columns, pd.MultiIndex):
                    bench_df.columns = bench_df.columns.get_level_values(0)
                bench_close = bench_df["Close"].reindex(df.index).ffill()
                df["BENCH_RET20"] = bench_close.pct_change(20) * 100
                df["RS_EDGE20"] = df["RET20"] - df["BENCH_RET20"]
            else:
                df["RS_EDGE20"] = df["RET20"]
        except Exception:
            df["RS_EDGE20"] = df["RET20"]
    else:
        df["RS_EDGE20"] = df["RET20"]

    trend_up = (df["MA20"] > df["MA50"]) & (df["MA50"] > df["MA120"])
    rs_strong = df["RS_EDGE20"] > 3
    macd_ok = (df["MACD"] > df["MACD_Sig"]) & df["MACD_RISING"]
    not_hot = (df["MFI"] < 85) & (df["RSI"] < 70) & (df["%B"] < 1.05)
    structure_ok = (df["MDD_52W"] > -0.15) & (df["DAY_RET"] > -4) & (df["Close"] >= df["MA20"] * 0.98)
    structure_damage = (
        (df["MDD_52W"] <= -0.15) |
        (df["Close"] < df["MA50"]) |
        ((df["DAY_RET"] <= -6) & (df["VOL_RATIO"] >= 1.2)) |
        (df["Close"] < df["MA20"] * 0.98)
    )

    if signal_type == "신규대장 후보":
        signal_mask = trend_up & rs_strong & macd_ok & not_hot & structure_ok
    elif signal_type == "S급 눌림목":
        signal_mask = trend_up & rs_strong & df["RSI"].between(45, 58, inclusive="both") & df["%B"].between(0.45, 0.8, inclusive="both")
    elif signal_type == "구조훼손 경고":
        signal_mask = structure_damage
    else:
        signal_mask = trend_up & rs_strong & macd_ok

    events = []
    last_event_idx = -9999
    max_horizon = 60
    for idx, is_signal in enumerate(signal_mask.fillna(False).to_numpy()):
        if not is_signal:
            continue
        if idx < 125 or idx + 5 >= len(df):
            continue
        if idx - last_event_idx < int(min_gap):
            continue
        last_event_idx = idx
        row = df.iloc[idx]
        events.append({
            "날짜": df.index[idx].strftime("%Y-%m-%d") if hasattr(df.index[idx], "strftime") else str(df.index[idx]),
            "종목명": name,
            "티커": ticker,
            "신호": signal_type,
            "신호가": clean_float(row.get("Close"), np.nan),
            "5일후": calc_forward_return(close, idx, 5),
            "20일후": calc_forward_return(close, idx, 20),
            "60일후": calc_forward_return(close, idx, max_horizon),
            "20일최대낙폭": calc_forward_drawdown(close, idx, 20),
            "60일최대낙폭": calc_forward_drawdown(close, idx, max_horizon),
            "RSI": clean_float(row.get("RSI"), np.nan),
            "MFI": clean_float(row.get("MFI"), np.nan),
            "RS우위20일": clean_float(row.get("RS_EDGE20"), np.nan),
            "MDD": clean_float(row.get("MDD_52W"), np.nan) * 100,
        })

    return pd.DataFrame(events), df, ""


def summarize_signal_backtest(events_df):
    rows = []
    for horizon in ["5일후", "20일후", "60일후"]:
        series = pd.to_numeric(events_df.get(horizon, pd.Series(dtype=float)), errors="coerce").dropna()
        if series.empty:
            rows.append({"기간": horizon, "표본": 0, "승률": np.nan, "평균": np.nan, "중앙값": np.nan, "최악": np.nan, "최고": np.nan})
            continue
        rows.append({
            "기간": horizon,
            "표본": int(len(series)),
            "승률": float((series > 0).mean() * 100),
            "평균": float(series.mean()),
            "중앙값": float(series.median()),
            "최악": float(series.min()),
            "최고": float(series.max()),
        })
    return pd.DataFrame(rows)


def format_backtest_percent(value):
    number = clean_float(value, np.nan)
    if not finite_num(number):
        return ""
    return f"{number:.1f}%"


def render_signal_backtest_tab(holdings_table, watchlist_items):
    st.subheader("신호 검증")
    st.caption("전광판 신호가 과거에 나온 뒤 5/20/60거래일 성과를 확인합니다. 수수료, 세금, 체결가, 매크로 패널티는 반영하지 않은 참고용 검증입니다.")

    universe_df = build_signal_backtest_universe(holdings_table, watchlist_items)
    if universe_df.empty:
        st.info("검증할 보유/관심 종목이 없습니다.")
        return

    c1, c2, c3 = st.columns([2.2, 1.2, 1])
    with c1:
        selected_label = st.selectbox("검증 종목", universe_df["label"].tolist(), key="signal_backtest_ticker")
    selected_row = universe_df[universe_df["label"] == selected_label].iloc[0]
    with c2:
        signal_type = st.selectbox("검증 신호", ["신규대장 후보", "S급 눌림목", "구조훼손 경고"], key="signal_backtest_type")
    with c3:
        period = st.selectbox("기간", ["1y", "2y", "5y"], index=1, key="signal_backtest_period")

    min_gap = st.slider("중복 신호 간격(거래일)", min_value=1, max_value=30, value=10, step=1, key="signal_backtest_gap")

    if not should_run_heavy_analysis(
        "signal_backtest_lazy",
        "백테스트는 선택 종목의 과거 가격과 지표를 다시 계산하므로 필요할 때만 실행합니다.",
        run_label="신호 검증 실행/새로고침",
    ):
        return

    events_df, chart_df, message = build_signal_backtest(
        ticker=selected_row["ticker"],
        name=selected_row["name"],
        asset_class=selected_row["asset_class"],
        signal_type=signal_type,
        period=period,
        min_gap=min_gap,
    )

    if message:
        st.warning(message)
        return
    if events_df.empty:
        st.info("선택한 조건에 해당하는 과거 신호가 없습니다. 기간을 늘리거나 중복 간격을 줄여보세요.")
        return

    summary_df = summarize_signal_backtest(events_df)
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("신호 발생", f"{len(events_df)}회")
    ret20 = pd.to_numeric(events_df["20일후"], errors="coerce").dropna()
    ret60 = pd.to_numeric(events_df["60일후"], errors="coerce").dropna()
    dd20 = pd.to_numeric(events_df["20일최대낙폭"], errors="coerce").dropna()
    s2.metric("20일 승률", "-" if ret20.empty else f"{(ret20 > 0).mean() * 100:.1f}%")
    s3.metric("20일 평균", "-" if ret20.empty else f"{ret20.mean():.1f}%")
    s4.metric("20일 평균낙폭", "-" if dd20.empty else f"{dd20.mean():.1f}%")

    st.markdown("#### 기간별 성과")
    show_summary = summary_df.copy()
    for col in ["승률", "평균", "중앙값", "최악", "최고"]:
        show_summary[col] = show_summary[col].apply(format_backtest_percent)
    st.dataframe(show_summary, use_container_width=True, hide_index=True)

    st.markdown("#### 신호 발생 내역")
    show_events = events_df.copy()
    show_events["신호가"] = show_events["신호가"].apply(lambda v: "" if not finite_num(v) else f"{v:,.2f}")
    for col in ["5일후", "20일후", "60일후", "20일최대낙폭", "60일최대낙폭", "RSI", "MFI", "RS우위20일", "MDD"]:
        if col in show_events.columns:
            suffix = "%" if col not in ["RSI", "MFI"] else ""
            show_events[col] = show_events[col].apply(lambda v: "" if not finite_num(v) else f"{clean_float(v):.1f}{suffix}")
    st.dataframe(show_events, use_container_width=True, hide_index=True)
    st.download_button(
        "신호 검증 CSV 다운로드",
        data=dataframe_to_csv_bytes(events_df),
        file_name=f"stock_lab_signal_backtest_{selected_row['ticker']}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="download_signal_backtest_csv",
    )

    if chart_df is not None and not chart_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["Close"], mode="lines", name="Close", line=dict(color="#e5e7eb", width=1.8)))
        if "MA20" in chart_df.columns:
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MA20"], mode="lines", name="MA20", line=dict(color="#fbbf24", width=1.2)))
        if "MA50" in chart_df.columns:
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MA50"], mode="lines", name="MA50", line=dict(color="#60a5fa", width=1.2)))
        event_dates = pd.to_datetime(events_df["날짜"], errors="coerce")
        event_prices = pd.to_numeric(events_df["신호가"], errors="coerce")
        fig.add_trace(go.Scatter(
            x=event_dates,
            y=event_prices,
            mode="markers",
            name="신호",
            marker=dict(size=9, color="#22c55e" if signal_type != "구조훼손 경고" else "#ef4444", symbol="diamond"),
            hovertemplate="신호일 %{x|%Y-%m-%d}<br>가격 %{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(
            template="plotly_dark",
            height=460,
            title=f"{selected_row['name']} {signal_type} 검증",
            xaxis_rangeslider_visible=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("신호 정의"):
        st.markdown("""
- **신규대장 후보**: 정배열, 벤치마크 대비 20일 상대강도 우위, MACD 양호, 과열/구조훼손 제외 조건을 모두 만족한 날입니다.
- **S급 눌림목**: 정배열과 상대강도 우위가 살아있고 RSI 45~58, 볼린저 %B 0.45~0.8인 날입니다.
- **구조훼손 경고**: 고점대비 -15% 이하, MA50 이탈, 급락+거래량, MA20 하단 이탈 중 하나가 발생한 날입니다.
- 앱의 실시간 판정 로직과 100% 동일한 백테스트는 아닙니다. 매크로, 재무점수, 목표비중, 뉴스는 제외한 가격/기술 신호 검증용입니다.
        """)


SIGNAL_BACKTEST_TYPES = ["신규대장 후보", "S급 눌림목", "구조훼손 경고"]
SIGNAL_BACKTEST_RETURN_COLS = ["5일후", "20일후", "60일후"]
SIGNAL_BACKTEST_DD_COLS = ["20일최대낙폭", "60일최대낙폭"]
SIGNAL_BACKTEST_NUMERIC_COLS = SIGNAL_BACKTEST_RETURN_COLS + SIGNAL_BACKTEST_DD_COLS + ["RSI", "MFI", "RS우위20일", "MDD"]


def build_signal_backtest_universe_v2(holdings_table, watchlist_items):
    universe_df = build_short_trend_universe(holdings_table, watchlist_items)
    if universe_df.empty:
        return pd.DataFrame(columns=["label", "name", "ticker", "asset_class", "is_etf"])

    rows = []
    seen = set()
    for _, row in universe_df.iterrows():
        ticker = sanitize_ticker_value(row.get("ticker", ""))
        key = normalize_ticker(ticker)
        if not ticker or key in seen:
            continue
        seen.add(key)
        name = sanitize_asset_name(row.get("name", ""), ticker)
        rows.append({
            "label": f"{name} | {ticker}",
            "name": name,
            "ticker": ticker,
            "asset_class": str(row.get("asset_class", "") or "").strip(),
            "is_etf": clean_bool(row.get("is_etf", False)),
        })
    return pd.DataFrame(rows)


def build_signal_backtest_batch(universe_df, signal_type, period="2y", min_gap=10, max_tickers=12):
    frames = []
    messages = []
    selected_df = universe_df.head(int(max_tickers)).copy()

    for _, row in selected_df.iterrows():
        events_df, _, message = build_signal_backtest(
            ticker=row["ticker"],
            name=row["name"],
            asset_class=row.get("asset_class", ""),
            signal_type=signal_type,
            period=period,
            min_gap=min_gap,
        )
        if message:
            messages.append(message)
        if events_df is not None and not events_df.empty:
            frames.append(events_df)

    if not frames:
        return pd.DataFrame(), messages

    combined = pd.concat(frames, ignore_index=True)
    combined["_날짜정렬"] = pd.to_datetime(combined["날짜"], errors="coerce")
    combined = combined.sort_values(["_날짜정렬", "티커"], ascending=[False, True]).drop(columns=["_날짜정렬"])
    return combined, messages


def summarize_signal_backtest_by_ticker(events_df):
    rows = []
    for (ticker, name), group in events_df.groupby(["티커", "종목명"], dropna=False):
        ret20 = pd.to_numeric(group.get("20일후"), errors="coerce").dropna()
        ret60 = pd.to_numeric(group.get("60일후"), errors="coerce").dropna()
        dd20 = pd.to_numeric(group.get("20일최대낙폭"), errors="coerce").dropna()
        rows.append({
            "종목명": name,
            "티커": ticker,
            "신호수": int(len(group)),
            "20일승률": np.nan if ret20.empty else float((ret20 > 0).mean() * 100),
            "20일평균": np.nan if ret20.empty else float(ret20.mean()),
            "60일평균": np.nan if ret60.empty else float(ret60.mean()),
            "20일평균낙폭": np.nan if dd20.empty else float(dd20.mean()),
            "최근신호": str(group["날짜"].max()) if "날짜" in group.columns else "",
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["20일평균", "신호수"], ascending=[False, False])


def render_signal_summary_metrics(events_df):
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("신호 발생", f"{len(events_df)}건")
    ret20 = pd.to_numeric(events_df["20일후"], errors="coerce").dropna()
    dd20 = pd.to_numeric(events_df["20일최대낙폭"], errors="coerce").dropna()
    s2.metric("20일 승률", "-" if ret20.empty else f"{(ret20 > 0).mean() * 100:.1f}%")
    s3.metric("20일 평균", "-" if ret20.empty else f"{ret20.mean():.1f}%")
    s4.metric("20일 평균낙폭", "-" if dd20.empty else f"{dd20.mean():.1f}%")


def render_signal_summary_table_v2(summary_df):
    st.markdown("#### 기간별 성과")
    show_summary = summary_df.copy()
    for col in ["승률", "평균", "중앙값", "최악", "최고"]:
        if col in show_summary.columns:
            show_summary[col] = show_summary[col].apply(format_backtest_percent)
    st.dataframe(show_summary, use_container_width=True, hide_index=True)


def interpret_signal_backtest_result(signal_count, win20, avg20, avg60, avg_dd20):
    signal_count = int(clean_float(signal_count, 0))
    win20 = clean_float(win20, np.nan)
    avg20 = clean_float(avg20, np.nan)
    avg60 = clean_float(avg60, np.nan)
    avg_dd20 = clean_float(avg_dd20, np.nan)

    if signal_count <= 0 or not finite_num(win20) or not finite_num(avg20):
        return "해석 불가: 검증 표본이 부족합니다."

    if signal_count < 3:
        base = "표본 부족: 참고만"
    elif signal_count < 5:
        base = "참고 가능: 표본 작음"
    elif win20 >= 75 and avg20 > 5 and (not finite_num(avg60) or avg60 > 0):
        base = "검증 우수: 신호 신뢰 높음"
    elif win20 >= 60 and avg20 > 0 and (not finite_num(avg60) or avg60 >= 0):
        base = "검증 양호: 장기 후보 점검 가능"
    elif win20 >= 50 and avg20 > 0:
        base = "혼조 우위: 분할 접근"
    elif avg20 <= 0 or win20 < 45:
        base = "검증 부진: 신호 단독 사용 금지"
    else:
        base = "혼조: 보조지표 확인 필요"

    risk_notes = []
    if signal_count < 10:
        risk_notes.append("표본 작아 과신 금지")
    if finite_num(avg_dd20):
        if avg_dd20 <= -10:
            risk_notes.append("변동성 큼")
        elif avg_dd20 <= -7:
            risk_notes.append("중간 흔들림 감수")
        elif avg_dd20 >= -3:
            risk_notes.append("낙폭 안정적")

    return base if not risk_notes else f"{base} / {', '.join(risk_notes)}"


def render_signal_auto_interpretation(events_df, signal_type):
    ret20 = pd.to_numeric(events_df.get("20일후"), errors="coerce").dropna()
    ret60 = pd.to_numeric(events_df.get("60일후"), errors="coerce").dropna()
    dd20 = pd.to_numeric(events_df.get("20일최대낙폭"), errors="coerce").dropna()

    if ret20.empty:
        return

    win20 = float((ret20 > 0).mean() * 100)
    avg20 = float(ret20.mean())
    avg60 = np.nan if ret60.empty else float(ret60.mean())
    avg_dd20 = np.nan if dd20.empty else float(dd20.mean())
    interpretation = interpret_signal_backtest_result(len(ret20), win20, avg20, avg60, avg_dd20)

    if signal_type == "구조훼손 경고":
        if avg20 < 0:
            headline = "구조훼손 경고가 과거에도 대체로 유효했습니다."
        else:
            headline = "구조훼손 경고 후 반등도 있었으니 손절/관망 기준을 함께 보세요."
    else:
        headline = "이 신호는 과거 성과 기준으로 다음처럼 해석할 수 있습니다."

    st.markdown(
        f"<div class='info-panel' style='border-left: 5px solid #22c55e;'>"
        f"<b>자동해석</b><br>{headline}<br>"
        f"<span class='highlight' style='font-size:1.05em;'>{escape_html_value(interpretation)}</span><br>"
        f"<span style='color:#cbd5e1;'>표본 {len(ret20)}건 | 20일 승률 {win20:.1f}% | "
        f"20일 평균 {avg20:.1f}% | 60일 평균 {format_backtest_percent(avg60) or '-'} | "
        f"20일 평균낙폭 {format_backtest_percent(avg_dd20) or '-'}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def format_signal_events_for_display(events_df):
    show_events = events_df.copy()
    if "신호가" in show_events.columns:
        show_events["신호가"] = show_events["신호가"].apply(lambda v: "" if not finite_num(v) else f"{v:,.2f}")
    for col in SIGNAL_BACKTEST_NUMERIC_COLS:
        if col in show_events.columns:
            suffix = "%" if col not in ["RSI", "MFI"] else ""
            show_events[col] = show_events[col].apply(lambda v: "" if not finite_num(v) else f"{clean_float(v):.1f}{suffix}")
    return show_events


def render_signal_ticker_summary(events_df):
    ticker_summary = summarize_signal_backtest_by_ticker(events_df)
    if ticker_summary.empty:
        return
    st.markdown("#### 종목별 요약")
    show_ticker_summary = ticker_summary.copy()
    show_ticker_summary["자동해석"] = show_ticker_summary.apply(
        lambda r: interpret_signal_backtest_result(
            r.get("신호수", 0),
            r.get("20일승률", np.nan),
            r.get("20일평균", np.nan),
            r.get("60일평균", np.nan),
            r.get("20일평균낙폭", np.nan),
        ),
        axis=1,
    )
    for col in ["20일승률", "20일평균", "60일평균", "20일평균낙폭"]:
        show_ticker_summary[col] = show_ticker_summary[col].apply(format_backtest_percent)
    st.dataframe(show_ticker_summary, use_container_width=True, hide_index=True)


def render_signal_backtest_chart_v2(chart_df, events_df, selected_name, signal_type):
    if chart_df is None or chart_df.empty:
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["Close"], mode="lines", name="Close", line=dict(color="#e5e7eb", width=1.8)))
    if "MA20" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MA20"], mode="lines", name="MA20", line=dict(color="#fbbf24", width=1.2)))
    if "MA50" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MA50"], mode="lines", name="MA50", line=dict(color="#60a5fa", width=1.2)))
    if "MA120" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MA120"], mode="lines", name="MA120", line=dict(color="#a78bfa", width=1, dash="dot")))

    event_dates = pd.to_datetime(events_df["날짜"], errors="coerce")
    event_prices = pd.to_numeric(events_df["신호가"], errors="coerce")
    fig.add_trace(go.Scatter(
        x=event_dates,
        y=event_prices,
        mode="markers",
        name="신호",
        marker=dict(size=9, color="#22c55e" if signal_type != "구조훼손 경고" else "#ef4444", symbol="diamond"),
        hovertemplate="신호일: %{x|%Y-%m-%d}<br>가격: %{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_dark",
        height=460,
        title=f"{selected_name} {signal_type} 검증",
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_signal_backtest_tab(holdings_table, watchlist_items):
    st.subheader("신호 검증")
    st.caption("현재의 신호가 과거에 나온 뒤 5/20/60거래일 성과를 확인합니다. 수수료, 세금, 체결가, 매크로 패널티는 반영하지 않은 참고용 검증입니다.")

    universe_df = build_signal_backtest_universe_v2(holdings_table, watchlist_items)
    if universe_df.empty:
        st.info("검증할 보유/관심 종목이 없습니다.")
        return

    mode = st.radio(
        "검증 방식",
        ["선택 종목", "전광판/보유종목 묶음"],
        horizontal=True,
        key="signal_backtest_mode",
    )

    c1, c2, c3 = st.columns([2.2, 1.2, 1])
    selected_row = None
    selected_subset = universe_df.copy()

    with c1:
        if mode == "선택 종목":
            selected_label = st.selectbox("검증 종목", universe_df["label"].tolist(), key="signal_backtest_ticker")
            selected_row = universe_df[universe_df["label"] == selected_label].iloc[0]
        else:
            labels = universe_df["label"].tolist()
            default_labels = labels[:min(10, len(labels))]
            selected_labels = st.multiselect(
                "묶음 검증 종목",
                labels,
                default=default_labels,
                key="signal_backtest_batch_labels",
            )
            selected_subset = universe_df[universe_df["label"].isin(selected_labels)].copy()
    with c2:
        signal_type = st.selectbox("검증 신호", SIGNAL_BACKTEST_TYPES, key="signal_backtest_type")
    with c3:
        period = st.selectbox("기간", ["1y", "2y", "5y"], index=1, key="signal_backtest_period")

    g1, g2 = st.columns([1.2, 1.2])
    with g1:
        min_gap = st.slider("중복 신호 간격(거래일)", min_value=1, max_value=30, value=10, step=1, key="signal_backtest_gap")
    with g2:
        max_tickers = st.slider("묶음 최대 종목 수", min_value=3, max_value=25, value=min(12, max(3, len(universe_df))), step=1, key="signal_backtest_max_tickers")

    if mode == "전광판/보유종목 묶음":
        if selected_subset.empty:
            st.info("묶음 검증할 종목을 1개 이상 선택해 주세요.")
            return
        st.caption(f"현재 선택된 {len(selected_subset)}개 중 최대 {max_tickers}개까지 순서대로 검증합니다. 너무 많이 고르면 yfinance 호출 때문에 느려질 수 있습니다.")

    if not should_run_heavy_analysis(
        "signal_backtest_lazy",
        "백테스트는 과거 가격과 지표를 다시 계산하므로 필요할 때만 실행합니다.",
        run_label="신호 검증 실행/새로고침",
    ):
        return

    chart_df = pd.DataFrame()
    messages = []
    if mode == "선택 종목":
        events_df, chart_df, message = build_signal_backtest(
            ticker=selected_row["ticker"],
            name=selected_row["name"],
            asset_class=selected_row["asset_class"],
            signal_type=signal_type,
            period=period,
            min_gap=min_gap,
        )
        if message:
            messages.append(message)
    else:
        events_df, messages = build_signal_backtest_batch(
            selected_subset,
            signal_type=signal_type,
            period=period,
            min_gap=min_gap,
            max_tickers=max_tickers,
        )

    if messages:
        with st.expander("검증 제외/주의 메시지"):
            for msg in messages[:30]:
                st.write("-", msg)

    if events_df.empty:
        st.info("선택한 조건에 해당하는 과거 신호가 없습니다. 기간을 늘리거나 중복 간격을 줄여보세요.")
        return

    summary_df = summarize_signal_backtest(events_df)
    render_signal_summary_metrics(events_df)
    render_signal_auto_interpretation(events_df, signal_type)
    render_signal_summary_table_v2(summary_df)

    if mode == "전광판/보유종목 묶음":
        render_signal_ticker_summary(events_df)

    st.markdown("#### 신호 발생 내역")
    st.dataframe(format_signal_events_for_display(events_df), use_container_width=True, hide_index=True)

    file_scope = selected_row["ticker"] if mode == "선택 종목" else "batch"
    st.download_button(
        "신호 검증 CSV 다운로드",
        data=dataframe_to_csv_bytes(events_df),
        file_name=f"stock_lab_signal_backtest_{file_scope}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="download_signal_backtest_csv",
    )

    if mode == "선택 종목":
        render_signal_backtest_chart_v2(chart_df, events_df, selected_row["name"], signal_type)

    with st.expander("신호 정의"):
        st.markdown("""
- **신규대장 후보**: 정배열, 벤치마크 대비 20일 상대강도 우위, MACD 양호, 과열/구조훼손 제외 조건을 모두 만족한 신호입니다.
- **S급 눌림목**: 정배열과 상대강도 우위가 살아있고 RSI 45~58, 볼린저 %B 0.45~0.8인 신호입니다.
- **구조훼손 경고**: 고점대비 -15% 이하, MA50 이탈, 급락+거래량, MA20 하단 이탈 중 하나가 발생한 신호입니다.
- 앱의 실시간 판정 로직과 100% 동일한 백테스트는 아닙니다. 매크로, 재무점수, 목표비중, 뉴스는 제외한 가격/기술 신호 검증용입니다.
        """)


def should_run_heavy_analysis(key, description, run_label="분석 실행/새로고침"):
    ready_key = f"{key}_ready"
    last_key = f"{key}_last_run"
    if ready_key not in st.session_state:
        st.session_state[ready_key] = False

    c1, c2, c3 = st.columns([1.4, 1.0, 3.6])
    if c1.button(run_label, key=f"{key}_run", use_container_width=True):
        st.session_state[ready_key] = True
        st.session_state[last_key] = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")

    if st.session_state.get(ready_key, False):
        if c2.button("계산 접기", key=f"{key}_hide", use_container_width=True):
            st.session_state[ready_key] = False
    else:
        c2.caption("대기 중")

    if not st.session_state.get(ready_key, False):
        st.info(f"첫 로딩 속도를 위해 아직 계산하지 않았습니다. {description}")
        return False

    last_run = st.session_state.get(last_key)
    if last_run:
        c3.caption(f"마지막 실행: {last_run}")
    return True


def get_heavy_analysis_ready(key):
    ready_key = f"{key}_ready"
    if ready_key not in st.session_state:
        st.session_state[ready_key] = False
    return bool(st.session_state.get(ready_key, False))


def render_heavy_analysis_button(key, run_label="분석 실행/새로고침"):
    ready_key = f"{key}_ready"
    last_key = f"{key}_last_run"
    if ready_key not in st.session_state:
        st.session_state[ready_key] = False

    if st.button(run_label, key=f"{key}_run_inline", use_container_width=True):
        st.session_state[ready_key] = True
        st.session_state[last_key] = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
        st.rerun()

    if st.session_state.get(ready_key, False):
        if st.button("계산 접기", key=f"{key}_hide_inline", use_container_width=True):
            st.session_state[ready_key] = False
            st.rerun()
        last_run = st.session_state.get(last_key)
        if last_run:
            st.caption(f"마지막 실행: {last_run}")
    else:
        st.caption("기술적 타점 요약 대기 중")


@st.cache_data(ttl=3600, show_spinner=False)
def load_cached_kr_etf_lab_data():
    return load_kr_etf_lab_dataframe()


def kr_etf_format_numeric(value, digits=2):
    number = clean_float(value, np.nan)
    if not finite_num(number):
        return ""
    return f"{float(number):.{digits}f}"


def kr_etf_format_krw(value):
    number = clean_float(value, np.nan)
    if not finite_num(number):
        return ""
    return f"{float(number):.0f}"


def get_distribution_refresh_targets(df, scope, max_items):
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    if scope == "월배당/분배금 후보":
        out = out[(out["monthly_dividend"] == "Y") | (out["source_distribution"] == "Y")]

    out = out[out["ticker"].astype(str).str.strip().ne("")]
    out = out.drop_duplicates("ticker", keep="first")

    max_items = max(1, int(max_items))
    return out.head(max_items)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_yfinance_distribution_snapshot(ticker):
    ticker = sanitize_ticker_value(ticker)
    if not ticker:
        return {"ok": False, "ticker": ticker, "reason": "티커 없음"}

    try:
        divs = yf.Ticker(ticker).dividends
    except Exception as exc:
        return {"ok": False, "ticker": ticker, "reason": str(exc)}

    if divs is None or divs.empty:
        return {"ok": False, "ticker": ticker, "reason": "분배금 이력 없음"}

    divs = pd.to_numeric(divs, errors="coerce").dropna()
    if divs.empty:
        return {"ok": False, "ticker": ticker, "reason": "분배금 숫자 변환 실패"}

    divs.index = pd.to_datetime(divs.index, errors="coerce")
    divs = divs[~pd.isna(divs.index)]
    if divs.empty:
        return {"ok": False, "ticker": ticker, "reason": "분배금 날짜 변환 실패"}

    divs = divs.sort_index()
    cutoff = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=370) if getattr(divs.index, "tz", None) else pd.Timestamp.now() - pd.Timedelta(days=370)
    recent = divs[divs.index >= cutoff]
    if recent.empty:
        recent = divs.tail(12)

    latest_date = divs.index[-1]
    latest_amount = float(divs.iloc[-1])
    annual_total = float(recent.sum())
    annual_count = int(len(recent))
    price = clean_float(load_latest_price(ticker), 0.0)
    if price <= 0:
        try:
            hist = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=False)
            if hist is not None and not hist.empty:
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.get_level_values(0)
                close = pd.to_numeric(hist.get("Close", pd.Series(dtype=float)), errors="coerce").dropna()
                if not close.empty:
                    price = float(close.iloc[-1])
        except Exception:
            price = 0.0

    latest_rate = (latest_amount / price * 100) if price > 0 else np.nan
    annual_rate = (annual_total / price * 100) if price > 0 else np.nan

    return {
        "ok": True,
        "ticker": ticker,
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "latest_amount": latest_amount,
        "annual_total": annual_total,
        "annual_count": annual_count,
        "latest_rate": latest_rate,
        "annual_rate": annual_rate,
        "price": price,
        "source": "Yahoo Finance dividend history",
    }


def build_kr_etf_distribution_refresh_preview(current_df, scope="월배당/분배금 후보", max_items=120):
    if current_df is None or current_df.empty:
        raise ValueError("기존 ETF 데이터가 없습니다.")

    preview_df = current_df.copy()
    targets = get_distribution_refresh_targets(preview_df, scope, max_items)
    if targets.empty:
        raise ValueError("조회할 ETF가 없습니다.")

    changed_rows = []
    failed_rows = []
    generated_at = format_kst_now()

    for _, target in targets.iterrows():
        ticker = sanitize_ticker_value(target.get("ticker", ""))
        code = clean_symbol(ticker)
        snapshot = fetch_yfinance_distribution_snapshot(ticker)
        if not snapshot.get("ok"):
            failed_rows.append({
                "ticker": ticker,
                "name": target.get("name", ""),
                "reason": snapshot.get("reason", "조회 실패"),
            })
            continue

        row_mask = preview_df["ticker"].astype(str).str.upper() == ticker.upper()
        if not row_mask.any():
            row_mask = preview_df["code"].astype(str).str.zfill(6) == code

        if not row_mask.any():
            failed_rows.append({"ticker": ticker, "name": target.get("name", ""), "reason": "기존 행 매칭 실패"})
            continue

        idx = preview_df[row_mask].index[0]
        old_annual_rate = preview_df.at[idx, "annual_distribution_rate_pct"]
        old_latest_amount = preview_df.at[idx, "distribution_per_share_krw"]

        preview_df.at[idx, "source_distribution"] = "Y"
        preview_df.at[idx, "distribution_type"] = "자동조회"
        preview_df.at[idx, "latest_distribution_rate_pct"] = kr_etf_format_numeric(snapshot.get("latest_rate"), 2)
        preview_df.at[idx, "distribution_ex_date"] = snapshot.get("latest_date", "")
        preview_df.at[idx, "distribution_base_date"] = snapshot.get("latest_date", "")
        preview_df.at[idx, "distribution_per_share_krw"] = kr_etf_format_krw(snapshot.get("latest_amount"))
        preview_df.at[idx, "annual_distribution_rate_pct"] = kr_etf_format_numeric(snapshot.get("annual_rate"), 2)
        preview_df.at[idx, "annual_distribution_total_krw"] = kr_etf_format_krw(snapshot.get("annual_total"))
        preview_df.at[idx, "annual_distribution_count"] = str(snapshot.get("annual_count", ""))
        preview_df.at[idx, "raw_monthly_dividend_flag"] = "YF"
        preview_df.at[idx, "current_price_krw"] = kr_etf_format_krw(snapshot.get("price"))
        preview_df.at[idx, "data_generated_at"] = generated_at
        source_files = str(preview_df.at[idx, "source_files"] or "")
        refresh_source = f"Yahoo Finance 분배금 자동조회 {generated_at}"
        preview_df.at[idx, "source_files"] = refresh_source if not source_files else f"{source_files} / {refresh_source}"

        annual_count = clean_int(snapshot.get("annual_count"), 0) or 0
        if annual_count >= 8:
            preview_df.at[idx, "monthly_dividend"] = "Y"
        preview_df.at[idx, "tags"] = derive_kr_etf_tags(
            preview_df.at[idx, "name"],
            preview_df.at[idx, "etf_big_type"],
            preview_df.at[idx, "etf_small_type"],
            preview_df.at[idx, "representative_big_type"],
            preview_df.at[idx, "representative_small_type"],
            str(preview_df.at[idx, "monthly_dividend"]) == "Y",
        )

        changed_rows.append({
            "ticker": ticker,
            "name": preview_df.at[idx, "name"],
            "최근분배일": snapshot.get("latest_date", ""),
            "최근분배금": preview_df.at[idx, "distribution_per_share_krw"],
            "연분배율(기존)": old_annual_rate,
            "연분배율(갱신)": preview_df.at[idx, "annual_distribution_rate_pct"],
            "분배금(기존)": old_latest_amount,
            "지급횟수": preview_df.at[idx, "annual_distribution_count"],
        })

    if changed_rows:
        preview_df["data_generated_at"] = generated_at

    changed_df = pd.DataFrame(changed_rows)
    failed_df = pd.DataFrame(failed_rows)
    messages = [
        f"온라인 분배금 조회: 대상 {len(targets):,}개",
        f"갱신 성공 {len(changed_df):,}개",
        f"조회 실패/이력 없음 {len(failed_df):,}개",
        "출처: Yahoo Finance 분배금 이력, 누락 종목은 기존값 유지",
    ]
    return preview_df, changed_df, failed_df, messages


def kr_etf_numeric_series(df, col):
    if df is None or df.empty or col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors="coerce")


def kr_etf_unique_options(df, col):
    if df is None or df.empty or col not in df.columns:
        return []
    values = df[col].fillna("").astype(str).str.strip()
    return sorted([x for x in values.unique().tolist() if x])


def kr_etf_tag_options(df):
    tags = set()
    if df is None or df.empty or "tags" not in df.columns:
        return []
    for value in df["tags"].fillna("").astype(str):
        for item in value.split(","):
            item = item.strip()
            if item:
                tags.add(item)
    return sorted(tags)


def render_kr_etf_update_panel(current_df):
    with st.expander("ETF 데이터 갱신/업로드"):
        st.caption("평소에는 앱 내부 CSV를 사용합니다. 새 자료가 생기면 온라인 조회나 엑셀 업로드로 검토한 뒤 저장하세요.")

        st.markdown("#### 온라인 분배금 반자동 갱신")
        online_cols = st.columns([1.2, 1.0, 1.4])
        refresh_scope = online_cols[0].selectbox(
            "조회 범위",
            ["월배당/분배금 후보", "전체 ETF"],
            key="kr_etf_distribution_refresh_scope",
            help="전체 ETF는 오래 걸릴 수 있어 처음에는 월배당/분배금 후보만 권장합니다.",
        )
        refresh_limit = online_cols[1].number_input(
            "최대 조회 수",
            min_value=10,
            max_value=1000,
            value=80,
            step=10,
            key="kr_etf_distribution_refresh_limit",
        )
        online_cols[2].caption("Yahoo Finance 분배금 이력으로 최근분배금/연분배율을 재계산합니다. 조회 실패 종목은 기존값을 유지합니다.")

        if st.button("온라인 분배금 조회", key="kr_etf_distribution_refresh_btn", disabled=current_df is None or current_df.empty):
            try:
                with st.spinner("분배금 이력을 조회하는 중입니다. 대상 수가 많으면 시간이 걸릴 수 있습니다."):
                    preview_df, changed_df, failed_df, messages = build_kr_etf_distribution_refresh_preview(
                        current_df,
                        scope=refresh_scope,
                        max_items=refresh_limit,
                    )
                st.session_state["kr_etf_lab_preview_df"] = preview_df
                st.session_state["kr_etf_lab_preview_messages"] = messages
                st.session_state["kr_etf_lab_preview_changed_df"] = changed_df
                st.session_state["kr_etf_lab_preview_failed_df"] = failed_df
            except Exception as exc:
                st.error(f"온라인 분배금 조회 실패: {exc}")

        st.divider()
        st.markdown("#### 엑셀 업로드 갱신")
        uploads = st.file_uploader(
            "국내 ETF 전체 목록 / 월배당 총정리 / 분배금 지급현황 엑셀",
            type=["xlsx"],
            accept_multiple_files=True,
            key="kr_etf_lab_uploads",
        )

        if st.button("업로드 파일 검토", key="kr_etf_lab_preview_btn", disabled=not uploads):
            try:
                preview_df, messages = build_kr_etf_lab_from_excel_files(uploads, base_df=current_df)
                st.session_state["kr_etf_lab_preview_df"] = preview_df
                st.session_state["kr_etf_lab_preview_messages"] = messages
                st.session_state.pop("kr_etf_lab_preview_changed_df", None)
                st.session_state.pop("kr_etf_lab_preview_failed_df", None)
            except Exception as exc:
                st.error(f"업로드 자료를 읽지 못했습니다: {exc}")

        preview_df = st.session_state.get("kr_etf_lab_preview_df")
        if isinstance(preview_df, pd.DataFrame) and not preview_df.empty:
            messages = st.session_state.get("kr_etf_lab_preview_messages", [])
            if messages:
                st.write(" / ".join(messages))
            p1, p2, p3 = st.columns(3)
            p1.metric("검토 ETF", f"{len(preview_df):,}개")
            p2.metric("월배당", f"{int((preview_df['monthly_dividend'] == 'Y').sum()):,}개")
            p3.metric("분배금 데이터", f"{int((preview_df['source_distribution'] == 'Y').sum()):,}개")

            changed_df = st.session_state.get("kr_etf_lab_preview_changed_df")
            failed_df = st.session_state.get("kr_etf_lab_preview_failed_df")
            if isinstance(changed_df, pd.DataFrame) and not changed_df.empty:
                st.markdown("##### 온라인 갱신 변경 미리보기")
                st.dataframe(changed_df.head(80), use_container_width=True, hide_index=True)
            if isinstance(failed_df, pd.DataFrame) and not failed_df.empty:
                with st.expander(f"조회 실패/분배금 이력 없음 {len(failed_df):,}개"):
                    st.dataframe(failed_df.head(200), use_container_width=True, hide_index=True)

            st.dataframe(
                preview_df[["ticker", "name", "tags", "annual_distribution_rate_pct", "distribution_per_share_krw", "real_fee_pct"]].head(30),
                use_container_width=True,
                hide_index=True,
            )
            save_col, clear_col = st.columns([1, 1])
            if save_col.button("검토 데이터 저장", key="kr_etf_lab_save_preview", use_container_width=True):
                try:
                    save_kr_etf_lab_dataframe(preview_df)
                    cache_clear(load_cached_kr_etf_lab_data)
                    st.session_state.pop("kr_etf_lab_preview_df", None)
                    st.session_state.pop("kr_etf_lab_preview_messages", None)
                    st.session_state.pop("kr_etf_lab_preview_changed_df", None)
                    st.session_state.pop("kr_etf_lab_preview_failed_df", None)
                    st.success("국내 ETF 데이터 저장 완료")
                    st.rerun()
                except Exception as exc:
                    st.error(f"저장하지 못했습니다: {exc}")
            if clear_col.button("검토 취소", key="kr_etf_lab_clear_preview", use_container_width=True):
                st.session_state.pop("kr_etf_lab_preview_df", None)
                st.session_state.pop("kr_etf_lab_preview_messages", None)
                st.session_state.pop("kr_etf_lab_preview_changed_df", None)
                st.session_state.pop("kr_etf_lab_preview_failed_df", None)
                st.rerun()


def render_kr_etf_lab_tab():
    st.subheader("월배당 ETF 탐색")
    st.caption("국내 ETF 전체 목록과 월배당/분배금 자료를 합쳐 장기 월현금흐름 후보를 비교합니다.")

    kr_etf_df = load_cached_kr_etf_lab_data()
    render_kr_etf_update_panel(kr_etf_df)

    if kr_etf_df.empty:
        st.warning("국내 ETF 데이터가 없습니다. ETF 데이터 갱신/업로드에서 전체 ETF 목록 엑셀을 먼저 올려주세요.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("전체 ETF", f"{len(kr_etf_df):,}개")
    m2.metric("월배당 후보", f"{int((kr_etf_df['monthly_dividend'] == 'Y').sum()):,}개")
    m3.metric("분배금 확인", f"{int((kr_etf_df['source_distribution'] == 'Y').sum()):,}개")
    generated_at = str(kr_etf_df["data_generated_at"].dropna().iloc[0]) if "data_generated_at" in kr_etf_df.columns and not kr_etf_df["data_generated_at"].dropna().empty else "-"
    m4.metric("데이터 갱신", generated_at[-8:] if generated_at and generated_at != "-" else "-")

    filter_cols = st.columns([1.6, 1.2, 1.2, 1.2])
    search_text = filter_cols[0].text_input("검색", placeholder="ETF명, 코드, 기초지수", key="kr_etf_search")
    big_type = filter_cols[1].selectbox("대유형", ["전체"] + kr_etf_unique_options(kr_etf_df, "etf_big_type"), key="kr_etf_big_type")
    tag = filter_cols[2].selectbox("분류", ["전체"] + kr_etf_tag_options(kr_etf_df), key="kr_etf_tag")
    sort_mode = filter_cols[3].selectbox(
        "정렬",
        ["연분배율 높은 순", "최근월분배율 높은 순", "운용규모 큰 순", "1년수익률 높은 순", "실부담비율 낮은 순", "이름순"],
        key="kr_etf_sort_mode",
    )

    option_cols = st.columns(5)
    monthly_only = option_cols[0].checkbox("월배당만", value=True, key="kr_etf_monthly_only")
    distribution_only = option_cols[1].checkbox("분배금 확인분만", value=False, key="kr_etf_distribution_only")
    pension_only = option_cols[2].checkbox("연금 가능만", value=False, key="kr_etf_pension_only")
    exclude_leverage = option_cols[3].checkbox("레버리지/인버스 제외", value=True, key="kr_etf_exclude_leverage")
    covered_call_only = option_cols[4].checkbox("커버드콜만", value=False, key="kr_etf_covered_call_only")

    threshold_cols = st.columns(3)
    min_annual_rate = threshold_cols[0].slider("최소 연분배율(%)", 0.0, 30.0, 0.0, 0.5, key="kr_etf_min_annual_rate")
    min_aum = threshold_cols[1].number_input("최소 운용규모(억원)", min_value=0.0, value=0.0, step=100.0, key="kr_etf_min_aum")
    max_real_fee = threshold_cols[2].number_input("최대 실부담비율(%)", min_value=0.0, value=10.0, step=0.1, key="kr_etf_max_real_fee")

    view_df = kr_etf_df.copy()
    if monthly_only:
        view_df = view_df[view_df["monthly_dividend"] == "Y"]
    if distribution_only:
        view_df = view_df[view_df["source_distribution"] == "Y"]
    if pension_only:
        view_df = view_df[(view_df["personal_pension"] == "Y") | (view_df["retirement_pension"] == "Y")]
    if exclude_leverage:
        view_df = view_df[~view_df["tags"].astype(str).str.contains("레버리지|인버스", na=False)]
    if covered_call_only:
        view_df = view_df[view_df["tags"].astype(str).str.contains("커버드콜", na=False)]
    if big_type != "전체":
        view_df = view_df[view_df["etf_big_type"] == big_type]
    if tag != "전체":
        view_df = view_df[view_df["tags"].astype(str).str.contains(tag, regex=False, na=False)]
    if search_text:
        search = search_text.strip().lower()
        target = (
            view_df["name"].astype(str) + " " +
            view_df["ticker"].astype(str) + " " +
            view_df["code"].astype(str) + " " +
            view_df["underlying_index"].astype(str) + " " +
            view_df["tags"].astype(str)
        ).str.lower()
        view_df = view_df[target.str.contains(search, na=False)]

    annual_rate = kr_etf_numeric_series(view_df, "annual_distribution_rate_pct")
    latest_rate = kr_etf_numeric_series(view_df, "latest_distribution_rate_pct")
    aum = kr_etf_numeric_series(view_df, "aum_krw_100m")
    real_fee = kr_etf_numeric_series(view_df, "real_fee_pct")
    if min_annual_rate > 0:
        view_df = view_df[annual_rate >= min_annual_rate]
    if min_aum > 0:
        view_df = view_df[aum >= min_aum]
    if max_real_fee < 10.0:
        view_df = view_df[real_fee <= max_real_fee]

    sort_col_map = {
        "연분배율 높은 순": ("annual_distribution_rate_pct", False),
        "최근월분배율 높은 순": ("latest_distribution_rate_pct", False),
        "운용규모 큰 순": ("aum_krw_100m", False),
        "1년수익률 높은 순": ("return_1y_pct", False),
        "실부담비율 낮은 순": ("real_fee_pct", True),
        "이름순": ("name", True),
    }
    sort_col, ascending = sort_col_map.get(sort_mode, ("annual_distribution_rate_pct", False))
    if sort_col != "name":
        view_df = view_df.assign(_sort=kr_etf_numeric_series(view_df, sort_col)).sort_values("_sort", ascending=ascending, na_position="last").drop(columns="_sort")
    else:
        view_df = view_df.sort_values("name", ascending=True)

    st.markdown("#### ETF 후보 목록")
    st.caption(f"조건에 맞는 ETF {len(view_df):,}개")

    display_cols = {
        "ticker": "티커",
        "name": "ETF명",
        "tags": "분류",
        "etf_big_type": "대유형",
        "etf_small_type": "소유형",
        "annual_distribution_rate_pct": "연분배율(%)",
        "latest_distribution_rate_pct": "최근월분배율(%)",
        "distribution_per_share_krw": "최근 분배금",
        "annual_distribution_count": "지급횟수",
        "real_fee_pct": "실부담(%)",
        "aum_krw_100m": "운용규모(억)",
        "return_1m_pct": "1개월(%)",
        "return_1y_pct": "1년(%)",
        "personal_pension": "개인연금",
        "retirement_pension": "퇴직연금",
        "risk_grade": "위험등급",
    }
    show_cols = [col for col in display_cols if col in view_df.columns]
    show_df = view_df[show_cols].rename(columns=display_cols)
    st.dataframe(show_df.head(300), use_container_width=True, hide_index=True)

    if view_df.empty:
        st.info("조건에 맞는 ETF가 없습니다.")
        return

    st.download_button(
        "필터 결과 CSV 다운로드",
        data=dataframe_to_csv_bytes(view_df),
        file_name=f"stock_lab_kr_monthly_etf_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="download_kr_etf_lab_csv",
    )

    st.markdown("#### 선택 ETF")
    option_map = {
        f"{row['name']} | {row['ticker']}": row
        for _, row in view_df.head(300).iterrows()
    }
    selected_label = st.selectbox("관심종목으로 보낼 ETF", ["선택"] + list(option_map.keys()), key="kr_etf_selected_for_watchlist")
    if selected_label != "선택":
        row = option_map[selected_label]
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("연분배율", f"{clean_float(row.get('annual_distribution_rate_pct'), 0.0):.2f}%")
        s2.metric("최근 분배금", f"{clean_float(row.get('distribution_per_share_krw'), 0.0):,.0f}원")
        s3.metric("실부담비율", f"{clean_float(row.get('real_fee_pct'), 0.0):.3f}%")
        s4.metric("운용규모", f"{clean_float(row.get('aum_krw_100m'), 0.0):,.0f}억")

        add_cols = st.columns([1, 2])
        if add_cols[0].button("전광판 관심종목 추가", key="add_kr_etf_watchlist", use_container_width=True):
            ticker = sanitize_ticker_value(row.get("ticker", ""))
            if is_in_watchlist(ticker):
                st.info("이미 전광판에 등록된 ETF입니다.")
            else:
                st.session_state.watchlist.append({
                    "name": sanitize_asset_name(row.get("name", ""), ticker),
                    "ticker": ticker,
                    "is_etf": True,
                    "asset_class": "kr_etf",
                    "fin_score": 0,
                })
                persist_watchlist()
                st.success("전광판 관심종목에 추가했습니다.")
                st.rerun()

        input_row = pd.DataFrame([{
            "name": row.get("name", ""),
            "ticker": row.get("ticker", ""),
            "qty": 0,
            "avg_price": 0,
            "target_weight": 0,
            "asset_class": "kr_etf",
            "is_etf": True,
            "bucket": "core",
        }])
        add_cols[1].dataframe(input_row, use_container_width=True, hide_index=True)

        with st.expander("선택 ETF 상세"):
            detail_cols = [
                "underlying_index", "manager", "listing_date", "tax_type", "replication",
                "top_1", "top_1_weight_pct", "top_2", "top_2_weight_pct", "top_3", "top_3_weight_pct",
            ]
            detail = pd.DataFrame([{col: row.get(col, "") for col in detail_cols}])
            st.dataframe(detail, use_container_width=True, hide_index=True)


def add_quality_issue(issues, severity, area, ticker, problem, suggestion):
    issues.append({
        "등급": severity,
        "영역": area,
        "티커": str(ticker or "").strip(),
        "문제": problem,
        "확인/조치": suggestion,
    })


def load_fin_scores_for_quality_check():
    try:
        res = supabase.table("fin_scores").select(",".join(FIN_SCORE_COLUMNS)).eq("owner_email", CURRENT_USER_EMAIL).execute()
        return dataframe_from_rows(res.data, FIN_SCORE_COLUMNS), None
    except Exception as exc:
        return pd.DataFrame(columns=FIN_SCORE_COLUMNS), str(exc)


def build_data_quality_report(settings, holdings_df, holdings_table, dividends_df, monthly_logs_df, watchlist_items):
    issues = []
    settings = settings or {}
    holdings_df = holdings_df if holdings_df is not None else pd.DataFrame(columns=HOLDINGS_COLUMNS)
    holdings_table = holdings_table if holdings_table is not None else pd.DataFrame()
    dividends_df = dividends_df if dividends_df is not None else pd.DataFrame(columns=DIVIDENDS_COLUMNS)
    monthly_logs_df = monthly_logs_df if monthly_logs_df is not None else pd.DataFrame(columns=MONTHLY_LOG_COLUMNS)
    watchlist_items = watchlist_items or []

    usdkrw = clean_float(settings.get("usdkrw"), 0.0)
    seed_money = clean_float(settings.get("seed_money"), 0.0)
    if usdkrw <= 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "환율이 0 이하입니다.", "자산 관리에서 USD/KRW 환율을 확인하세요.")
    if seed_money < 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "투입 원금이 음수입니다.", "자산 관리에서 투입 원금을 0 이상으로 수정하세요.")

    asset_lookup = {}
    if holdings_df.empty:
        add_quality_issue(issues, "참고", "보유자산", "", "등록된 보유자산이 없습니다.", "처음 사용하는 상태라면 정상입니다.")
    else:
        missing_cols = [col for col in HOLDINGS_COLUMNS if col not in holdings_df.columns]
        if missing_cols:
            add_quality_issue(issues, "위험", "보유자산", "", f"필수 컬럼이 없습니다: {', '.join(missing_cols)}", "백업/복구 파일 또는 DB 컬럼을 확인하세요.")

        ticker_keys = []
        for idx, row in holdings_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            name = str(row.get("name", "")).strip()
            key = normalize_ticker(ticker)
            if ticker:
                ticker_keys.append(key)
                asset_lookup[key] = {
                    "ticker": ticker,
                    "name": name,
                    "is_etf": row.get("is_etf", False),
                    "asset_class": str(row.get("asset_class", "")).strip(),
                    "source": "보유자산",
                }

            if not ticker:
                add_quality_issue(issues, "위험", "보유자산", f"row {idx + 1}", "티커가 비어 있습니다.", "티커를 입력하거나 해당 행을 삭제하세요.")
            if ticker and not name:
                add_quality_issue(issues, "주의", "보유자산", ticker, "자산명이 비어 있습니다.", "전광판에서 보기 쉽게 자산명을 입력하세요.")

            qty = clean_float(row.get("qty"), 0.0)
            avg_price = clean_float(row.get("avg_price"), 0.0)
            target_weight = clean_float(row.get("target_weight"), 0.0)
            if qty < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "보유량이 음수입니다.", "수량 입력값을 확인하세요.")
            if avg_price < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "매입가가 음수입니다.", "평균 매입가를 0 이상으로 수정하세요.")
            if target_weight < 0 or target_weight > 100:
                add_quality_issue(issues, "주의", "보유자산", ticker, "목표비중이 0~100 범위를 벗어났습니다.", "리밸런싱 기준 비중을 확인하세요.")

            asset_class = str(row.get("asset_class", "")).strip()
            saved_is_etf = clean_bool(row.get("is_etf", False))
            fin_exempt = is_fin_score_exempt_asset(ticker, saved_is_etf, asset_class, name)
            if fin_exempt and not saved_is_etf:
                add_quality_issue(issues, "주의", "ETF/재무점수", ticker, "ETF/ETN/레버리지로 보이지만 ETF 체크가 꺼져 있습니다.", "자산 관리에서 ETF/ETN/레버리지를 체크하세요.")
            if saved_is_etf and not asset_class_marks_fin_score_exempt(asset_class) and not is_known_etf_ticker(ticker):
                add_quality_issue(issues, "참고", "ETF/재무점수", ticker, "ETF 체크는 켜져 있지만 asset_class가 일반 주식 계열입니다.", "asset_class를 ETF/ETN 계열로 맞추면 분류가 더 안정적입니다.")

        duplicated = pd.Series([key for key in ticker_keys if key]).value_counts()
        for key, count in duplicated[duplicated > 1].items():
            add_quality_issue(issues, "위험", "보유자산", key, f"같은 티커가 {int(count)}번 등록되어 있습니다.", "한 행으로 합치거나 중복 행을 정리하세요.")

    if not holdings_table.empty and "운용대상" in holdings_table.columns and "리밸런싱목표비중" in holdings_table.columns:
        active_rows = holdings_table[holdings_table["운용대상"].apply(clean_bool)]
        target_sum = active_rows["리밸런싱목표비중"].apply(clean_float).sum() if not active_rows.empty else 0.0
        if target_sum > 100.5:
            add_quality_issue(issues, "위험", "목표비중", "", f"운용대상 목표비중 합계가 {target_sum:.1f}%입니다.", "현금/예비자산 제외 후 목표비중 합계를 100% 이하로 맞추세요.")
        elif len(active_rows) > 0 and target_sum < 50:
            add_quality_issue(issues, "참고", "목표비중", "", f"운용대상 목표비중 합계가 {target_sum:.1f}%로 낮습니다.", "의도한 현금 비중이 큰 상태인지 확인하세요.")

    watch_keys = []
    for idx, item in enumerate(watchlist_items):
        ticker = str(item.get("ticker", "")).strip()
        name = str(item.get("name", "")).strip()
        key = normalize_ticker(ticker)
        if not ticker:
            add_quality_issue(issues, "주의", "관심목록", f"row {idx + 1}", "티커가 비어 있는 관심종목이 있습니다.", "관심목록에서 빈 행을 제거하세요.")
            continue

        watch_keys.append(key)
        asset_lookup.setdefault(key, {
            "ticker": ticker,
            "name": name,
            "is_etf": item.get("is_etf", False),
            "asset_class": str(item.get("asset_class", "")).strip(),
            "source": "관심목록",
        })

        asset_class = str(item.get("asset_class", "")).strip()
        saved_is_etf = clean_bool(item.get("is_etf", False))
        fin_exempt = is_fin_score_exempt_asset(ticker, saved_is_etf, asset_class, name)
        if fin_exempt and not saved_is_etf:
            add_quality_issue(issues, "주의", "관심목록", ticker, "ETF/ETN/레버리지로 보이지만 ETF 체크가 꺼져 있습니다.", "관심목록 저장 시 ETF/ETN/레버리지로 분류하세요.")
        if fin_exempt and clean_int(item.get("fin_score"), 0) not in (0, None):
            add_quality_issue(issues, "주의", "관심목록", ticker, "재무점수 해당없음 대상인데 관심목록 재무점수가 남아 있습니다.", "관심목록을 다시 저장해 0/해당없음 상태로 맞추세요.")

    duplicated_watch = pd.Series([key for key in watch_keys if key]).value_counts()
    for key, count in duplicated_watch[duplicated_watch > 1].items():
        add_quality_issue(issues, "주의", "관심목록", key, f"같은 티커가 {int(count)}번 등록되어 있습니다.", "중복 관심종목을 정리하세요.")

    fin_scores_df, fin_scores_error = load_fin_scores_for_quality_check()
    if fin_scores_error:
        add_quality_issue(issues, "참고", "재무점수", "", f"재무점수 테이블을 점검하지 못했습니다: {fin_scores_error}", "네트워크 또는 Supabase 연결을 확인하세요.")

    if not fin_scores_df.empty:
        for _, row in fin_scores_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            key = normalize_ticker(ticker)
            if not ticker:
                add_quality_issue(issues, "주의", "재무점수", "", "티커가 비어 있는 재무점수 행이 있습니다.", "fin_scores 데이터를 확인하세요.")
                continue

            manual_score = clean_int(row.get("manual_score"))
            source = str(row.get("source", "")).strip()
            meta = asset_lookup.get(key)
            if meta and is_fin_score_exempt_asset(meta["ticker"], meta["is_etf"], meta["asset_class"], meta["name"]):
                if manual_score is not None or source != "not_applicable":
                    add_quality_issue(issues, "주의", "재무점수", ticker, "ETF/ETN/레버리지인데 수동 재무점수 또는 일반 점수 출처가 남아 있습니다.", "정밀 관측소에서 해당없음 체크 상태를 확인한 뒤 저장하세요.")
            elif key not in asset_lookup and manual_score is not None:
                add_quality_issue(issues, "참고", "재무점수", ticker, "보유/관심목록에 없는 티커의 수동 재무점수가 남아 있습니다.", "더 이상 쓰지 않는 종목이면 정리 후보로 봐도 됩니다.")

    if not dividends_df.empty:
        missing_cols = [col for col in DIVIDENDS_COLUMNS if col not in dividends_df.columns]
        if missing_cols:
            add_quality_issue(issues, "주의", "배당", "", f"배당 필수 컬럼이 없습니다: {', '.join(missing_cols)}", "배당 복구 파일 또는 DB 컬럼을 확인하세요.")
        for idx, row in dividends_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            date_text = str(row.get("date", "")).strip()
            amount = clean_float(row.get("amount"), 0.0)
            if not ticker:
                add_quality_issue(issues, "주의", "배당", f"row {idx + 1}", "배당 티커가 비어 있습니다.", "배당을 받은 종목 티커를 입력하세요.")
            if amount < 0:
                add_quality_issue(issues, "주의", "배당", ticker, "배당금이 음수입니다.", "환입/정정 목적이 아니라면 금액을 확인하세요.")
            if date_text and pd.isna(pd.to_datetime(date_text, errors="coerce")):
                add_quality_issue(issues, "주의", "배당", ticker, "배당일 형식을 날짜로 읽지 못했습니다.", "YYYY-MM-DD 형식으로 입력하세요.")

    if not monthly_logs_df.empty:
        missing_cols = [col for col in MONTHLY_LOG_COLUMNS if col not in monthly_logs_df.columns]
        if missing_cols:
            add_quality_issue(issues, "주의", "월별 로그", "", f"월별 로그 필수 컬럼이 없습니다: {', '.join(missing_cols)}", "월별 로그 복구 파일 또는 DB 컬럼을 확인하세요.")

        month_values = monthly_logs_df.get("month", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        duplicated_months = month_values[month_values.ne("")].value_counts()
        for month, count in duplicated_months[duplicated_months > 1].items():
            add_quality_issue(issues, "주의", "월별 로그", month, f"같은 월이 {int(count)}번 기록되어 있습니다.", "월별 로그는 월당 한 행으로 정리하세요.")

        for idx, row in monthly_logs_df.fillna("").iterrows():
            month = str(row.get("month", "")).strip()
            if not month:
                add_quality_issue(issues, "주의", "월별 로그", f"row {idx + 1}", "월 값이 비어 있습니다.", "YYYY-MM 형식으로 입력하세요.")
            elif pd.isna(pd.to_datetime(month, errors="coerce")):
                add_quality_issue(issues, "주의", "월별 로그", month, "월 형식을 날짜로 읽지 못했습니다.", "YYYY-MM 형식으로 입력하세요.")

            for col in ["total_invested", "evaluated_value", "dividend"]:
                if col in monthly_logs_df.columns and clean_float(row.get(col), 0.0) < 0:
                    add_quality_issue(issues, "주의", "월별 로그", month, f"{col} 값이 음수입니다.", "정정 목적이 아니라면 입력값을 확인하세요.")

    report_df = pd.DataFrame(issues, columns=["등급", "영역", "티커", "문제", "확인/조치"])
    if report_df.empty:
        return report_df

    severity_order = {"위험": 0, "주의": 1, "참고": 2}
    report_df["_order"] = report_df["등급"].map(severity_order).fillna(9)
    return report_df.sort_values(["_order", "영역", "티커"]).drop(columns="_order").reset_index(drop=True)


def render_data_quality_tab(settings, holdings_df, holdings_table, dividends_df, monthly_logs_df, watchlist_items):
    st.subheader("데이터 점검")
    st.caption("읽기 전용 점검판입니다. 여기서는 데이터를 자동 수정하지 않고, 확인이 필요한 후보만 보여줍니다.")

    report_df = build_data_quality_report(
        settings,
        holdings_df,
        holdings_table,
        dividends_df,
        monthly_logs_df,
        watchlist_items,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체", len(report_df))
    c2.metric("위험", int((report_df["등급"] == "위험").sum()) if not report_df.empty else 0)
    c3.metric("주의", int((report_df["등급"] == "주의").sum()) if not report_df.empty else 0)
    c4.metric("참고", int((report_df["등급"] == "참고").sum()) if not report_df.empty else 0)

    if report_df.empty:
        st.success("현재 점검 항목에서 큰 이상 후보가 보이지 않습니다.")
    else:
        selected_levels = st.multiselect("등급 필터", ["위험", "주의", "참고"], default=["위험", "주의", "참고"])
        filtered_df = report_df[report_df["등급"].isin(selected_levels)] if selected_levels else report_df.iloc[0:0]
        st.dataframe(filtered_df, use_container_width=True, hide_index=True)
        st.download_button(
            "점검 결과 CSV 다운로드",
            data=dataframe_to_csv_bytes(filtered_df),
            file_name=f"stock_lab_data_quality_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

        if (report_df["등급"] == "위험").any():
            st.error("위험 항목은 계산 결과를 크게 흔들 수 있습니다. 먼저 확인하는 편이 좋습니다.")
        elif (report_df["등급"] == "주의").any():
            st.warning("주의 항목은 앱 사용은 가능하지만 표시나 판단 보조 점수에 영향을 줄 수 있습니다.")

    with st.expander("점검 항목 보기"):
        st.markdown("""
- 기본 설정: 환율, 투입 원금
- 보유자산: 필수 컬럼, 빈 티커, 중복 티커, 음수 수량/매입가, 목표비중 범위
- ETF/ETN/레버리지: 재무점수 해당없음 분류와 수동 재무점수 잔존 여부
- 관심목록: 빈 티커, 중복 티커, ETF 분류 불일치
- 배당/월별 로그: 날짜 형식, 음수 금액, 중복 월
        """)


def build_asset_quick_quality_report(settings, holdings_df, dividends_df, monthly_logs_df):
    issues = []
    settings = settings or {}
    holdings_df = holdings_df if holdings_df is not None else pd.DataFrame(columns=HOLDINGS_COLUMNS)
    dividends_df = dividends_df if dividends_df is not None else pd.DataFrame(columns=DIVIDENDS_COLUMNS)
    monthly_logs_df = monthly_logs_df if monthly_logs_df is not None else pd.DataFrame(columns=MONTHLY_LOG_COLUMNS)

    if clean_float(settings.get("usdkrw"), 0.0) <= 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "환율이 0 이하입니다.", "입력/수정 영역에서 USD/KRW 환율을 확인하세요.")
    if clean_float(settings.get("seed_money"), 0.0) < 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "시드머니가 음수입니다.", "시드머니를 0 이상으로 수정하세요.")

    if holdings_df.empty:
        add_quality_issue(issues, "참고", "보유자산", "", "등록된 보유자산이 없습니다.", "처음 사용하는 상태라면 정상입니다.")
    else:
        ticker_keys = []
        for idx, row in holdings_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            key = normalize_ticker(ticker)
            if key:
                ticker_keys.append(key)
            else:
                add_quality_issue(issues, "위험", "보유자산", f"row {idx + 1}", "티커가 비어 있습니다.", "티커를 입력하거나 행을 삭제하세요.")

            if clean_float(row.get("qty"), 0.0) < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "보유량이 음수입니다.", "수량 입력값을 확인하세요.")
            if clean_float(row.get("avg_price"), 0.0) < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "매입가가 음수입니다.", "평균 매입가를 0 이상으로 수정하세요.")

            target_weight = clean_float(row.get("target_weight"), 0.0)
            if target_weight < 0 or target_weight > 100:
                add_quality_issue(issues, "주의", "보유자산", ticker, "목표비중이 0~100 범위를 벗어났습니다.", "목표비중을 확인하세요.")

        duplicated = pd.Series([key for key in ticker_keys if key]).value_counts()
        for key, count in duplicated[duplicated > 1].items():
            add_quality_issue(issues, "위험", "보유자산", key, f"같은 티커가 {int(count)}번 등록되어 있습니다.", "중복 행을 정리하세요.")

    if not dividends_df.empty:
        for idx, row in dividends_df.fillna("").iterrows():
            if str(row.get("date", "")).strip() and pd.isna(pd.to_datetime(row.get("date"), errors="coerce")):
                add_quality_issue(issues, "주의", "배당", f"row {idx + 1}", "배당 날짜 형식이 애매합니다.", "YYYY-MM-DD 형식으로 입력하면 가장 안정적입니다.")
            if clean_float(row.get("amount"), 0.0) < 0:
                add_quality_issue(issues, "주의", "배당", str(row.get("ticker", "")), "배당금이 음수입니다.", "정정 입력이 아니라면 금액을 확인하세요.")

    if not monthly_logs_df.empty:
        months = []
        for idx, row in monthly_logs_df.fillna("").iterrows():
            month = str(row.get("month", "")).strip()
            if month:
                months.append(month)
            else:
                add_quality_issue(issues, "주의", "월별 로그", f"row {idx + 1}", "월 정보가 비어 있습니다.", "예: 2026-05 형식으로 입력하세요.")

            for col in ["total_invested", "evaluated_value", "dividend"]:
                if col in monthly_logs_df.columns and clean_float(row.get(col), 0.0) < 0:
                    add_quality_issue(issues, "주의", "월별 로그", month, f"{col} 값이 음수입니다.", "입력값을 확인하세요.")

        duplicated_months = pd.Series([m for m in months if m]).value_counts()
        for month, count in duplicated_months[duplicated_months > 1].items():
            add_quality_issue(issues, "주의", "월별 로그", month, f"같은 월이 {int(count)}번 등록되어 있습니다.", "월별 로그를 한 행으로 정리하세요.")

    report_df = pd.DataFrame(issues, columns=["등급", "영역", "티커", "문제", "확인/조치"])
    if report_df.empty:
        return report_df

    severity_order = {"위험": 0, "주의": 1, "참고": 2}
    report_df["_order"] = report_df["등급"].map(severity_order).fillna(9)
    return report_df.sort_values(["_order", "영역", "티커"]).drop(columns="_order").reset_index(drop=True)


def render_asset_quick_quality_summary(settings, holdings_df, dividends_df, monthly_logs_df):
    quick_df = build_asset_quick_quality_report(settings, holdings_df, dividends_df, monthly_logs_df)
    danger_count = int((quick_df["등급"] == "위험").sum()) if not quick_df.empty else 0
    warning_count = int((quick_df["등급"] == "주의").sum()) if not quick_df.empty else 0
    note_count = int((quick_df["등급"] == "참고").sum()) if not quick_df.empty else 0

    status = "정상"
    if danger_count > 0:
        status = "위험 확인"
    elif warning_count > 0:
        status = "주의 확인"
    elif note_count > 0:
        status = "참고 있음"

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("입력 데이터 상태", status)
    q2.metric("위험", f"{danger_count}건")
    q3.metric("주의", f"{warning_count}건")
    q4.metric("참고", f"{note_count}건")

    if quick_df.empty:
        st.success("빠른 점검 기준으로 큰 입력 이상은 보이지 않습니다.")
        return

    with st.expander("빠른 점검 항목 보기", expanded=danger_count > 0):
        st.dataframe(quick_df, use_container_width=True, hide_index=True)
        st.caption("더 자세한 점검은 데이터 점검 탭에서 확인할 수 있습니다.")


def render_monthly_record_status(monthly_logs_df, portfolio_summary):
    perf_df = prepare_monthly_performance_df(monthly_logs_df)
    current_month = get_kst_now().strftime("%Y-%m")
    previous_month = (pd.Timestamp(get_kst_now().date()).replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m")

    if perf_df is None or perf_df.empty:
        st.markdown("### 월별 기록 상태")
        cols = st.columns(4)
        cols[0].metric("기록 상태", "기록 없음")
        cols[1].metric("최신 기록월", "-")
        cols[2].metric("기록 평가자산", "-")
        cols[3].metric("기록 수익률", "-")
        st.info("월별 로그를 입력하면 자산 변화, 누적손익, 배당금, 벤치마크 비교 차트가 표시됩니다.")
        return

    latest = perf_df.iloc[-1]
    latest_month = pd.Timestamp(latest["month_end"]).strftime("%Y-%m")
    latest_asset = clean_float(latest.get("evaluated_value"), 0.0)
    latest_return = clean_float(latest.get("cum_return_pct"), 0.0)
    current_asset = clean_float(portfolio_summary.get("current_asset"), 0.0)
    asset_gap = current_asset - latest_asset

    if latest_month == current_month:
        status = "이번 달 기록 있음"
    elif latest_month == previous_month:
        status = "최근 월 기록 완료"
    else:
        status = "업데이트 필요"

    st.markdown("### 월별 기록 상태")
    cols = st.columns(4)
    cols[0].metric("기록 상태", status)
    cols[1].metric("최신 기록월", latest_month, f"{len(perf_df)}개월")
    cols[2].metric("기록 평가자산", f"{latest_asset:,.0f}원", f"현재와 {asset_gap:+,.0f}원")
    cols[3].metric("기록 누적수익률", f"{latest_return:.2f}%")

    if status == "업데이트 필요":
        st.warning("월별 로그가 최근 월 기준으로 오래되었습니다. 입력/수정 영역에서 최신 월을 추가하면 차트가 더 정확해집니다.")
    else:
        st.caption("월별 로그가 비교적 최신 상태입니다. 월말 기준으로 기록하면 장기 성과 추적이 안정적입니다.")


def format_status_chip(label, color):
    return (
        f"<span style='display:inline-block; padding:3px 8px; border-radius:999px; "
        f"background:{color}22; border:1px solid {color}; color:{color}; font-size:0.85rem; font-weight:700;'>"
        f"{escape_html_value(label)}</span>"
    )


def classify_kpi_status(level):
    if level == "위험":
        return "#ef4444"
    if level == "주의":
        return "#f59e0b"
    if level == "양호":
        return "#22c55e"
    return "#60a5fa"


def build_asset_overview_kpis(holdings_table, portfolio_summary, reserve_summary):
    df = holdings_table.copy() if holdings_table is not None else pd.DataFrame()
    current_asset = clean_float(portfolio_summary.get("current_asset"), 0.0)
    cum_return = clean_float(portfolio_summary.get("cum_return"), 0.0)
    waiting_pct = clean_float(reserve_summary.get("waiting_pct"), 0.0)
    target_pct = clean_float(reserve_summary.get("target_pct"), 0.0)
    waiting_gap = waiting_pct - target_pct

    active_df = pd.DataFrame()
    if not df.empty and "운용대상" in df.columns:
        active_df = df[df["운용대상"].apply(clean_bool)].copy()
    elif not df.empty:
        active_df = df.copy()

    if not active_df.empty and "티커" in active_df.columns:
        active_df = active_df[~active_df["티커"].astype(str).str.upper().isin(["KRW_CASH", "USD_CASH"])]

    top_name = "-"
    top_weight = 0.0
    target_sum = 0.0
    rebalance_count = 0
    stale_price_count = 0
    etf_weight = 0.0

    if not active_df.empty:
        if "현재비중" in active_df.columns:
            weight_series = active_df["현재비중"].apply(clean_float)
            top_idx = weight_series.idxmax()
            top_weight = float(weight_series.loc[top_idx])
            top_name = str(active_df.loc[top_idx].get("자산명", active_df.loc[top_idx].get("티커", "-")) or "-")
            if "is_etf" in active_df.columns:
                etf_weight = float(active_df.loc[active_df["is_etf"].apply(clean_bool), "현재비중"].apply(clean_float).sum())

        if "리밸런싱목표비중" in active_df.columns:
            target_sum = float(active_df["리밸런싱목표비중"].apply(clean_float).sum())
        elif "목표비중" in active_df.columns:
            target_sum = float(active_df["목표비중"].apply(clean_float).sum())

        if "비중차이" in active_df.columns:
            rebalance_count = int((active_df["비중차이"].apply(clean_float).abs() >= 3.0).sum())

        if "현재가" in active_df.columns:
            stale_price_count = int((active_df["현재가"].apply(clean_float) <= 0).sum())

    if waiting_gap < -5:
        cash_status, cash_level = "부족", "주의"
    elif waiting_gap > 10:
        cash_status, cash_level = "여유", "양호"
    else:
        cash_status, cash_level = "정상", "양호"

    if top_weight >= 50:
        concentration_status, concentration_level = "집중위험", "위험"
    elif top_weight >= 35:
        concentration_status, concentration_level = "집중주의", "주의"
    else:
        concentration_status, concentration_level = "분산양호", "양호"

    if target_sum > 100.5:
        target_status, target_level = "초과", "위험"
    elif target_sum < 50 and len(active_df) > 0:
        target_status, target_level = "낮음", "참고"
    else:
        target_status, target_level = "정상", "양호"

    if stale_price_count > 0:
        data_status, data_level = "확인필요", "주의"
    else:
        data_status, data_level = "정상", "양호"

    if cum_return < -15:
        return_status, return_level = "손실확대", "주의"
    elif cum_return < 0:
        return_status, return_level = "손실권", "참고"
    else:
        return_status, return_level = "수익권", "양호"

    alerts = []
    if cash_level == "주의":
        alerts.append(f"대기자금이 목표보다 {abs(waiting_gap):.1f}%p 낮습니다.")
    elif waiting_gap > 10:
        alerts.append(f"대기자금이 목표보다 {waiting_gap:.1f}%p 높습니다. 투입 대기 자금인지 확인하세요.")
    if concentration_level in ["주의", "위험"]:
        alerts.append(f"최대 비중 자산은 {top_name} {top_weight:.1f}%입니다.")
    if target_level == "위험":
        alerts.append(f"운용대상 목표비중 합계가 {target_sum:.1f}%입니다.")
    if rebalance_count > 0:
        alerts.append(f"목표비중과 3%p 이상 차이나는 자산이 {rebalance_count}개 있습니다.")
    if stale_price_count > 0:
        alerts.append(f"현재가가 0이거나 누락된 운용자산이 {stale_price_count}개 있습니다.")

    kpis = [
        {"title": "운용 상태", "status": "점검" if alerts else "정상", "level": "주의" if alerts else "양호", "value": f"{len(alerts)}건", "detail": "확인 필요" if alerts else "큰 이상 없음"},
        {"title": "대기자금", "status": cash_status, "level": cash_level, "value": f"{waiting_pct:.1f}%", "detail": f"목표 {target_pct:.1f}% / {waiting_gap:+.1f}%p"},
        {"title": "집중도", "status": concentration_status, "level": concentration_level, "value": f"{top_weight:.1f}%", "detail": top_name},
        {"title": "목표비중", "status": target_status, "level": target_level, "value": f"{target_sum:.1f}%", "detail": f"리밸런싱 {rebalance_count}개"},
        {"title": "성과 상태", "status": return_status, "level": return_level, "value": f"{cum_return:.2f}%", "detail": f"총자산 {current_asset:,.0f}원"},
        {"title": "ETF 비중", "status": "참고", "level": "참고", "value": f"{etf_weight:.1f}%", "detail": "운용자산 내 ETF"},
        {"title": "데이터", "status": data_status, "level": data_level, "value": f"{stale_price_count}개", "detail": "현재가 누락"},
    ]

    return kpis, alerts


def render_kpi_summary_panel(kpis, alerts):
    st.markdown("### 운영 KPI")
    kpi_cols = st.columns(4)
    for idx, item in enumerate(kpis[:4]):
        color = classify_kpi_status(item["level"])
        with kpi_cols[idx]:
            st.markdown(
                f"<div class='info-panel' style='border-left:5px solid {color};'>"
                f"<b>{escape_html_value(item['title'])}</b> {format_status_chip(item['status'], color)}<br>"
                f"<span class='highlight'>{escape_html_value(item['value'])}</span><br>"
                f"<span class='score-detail'>{escape_html_value(item['detail'])}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    sub_cols = st.columns(3)
    for idx, item in enumerate(kpis[4:7]):
        color = classify_kpi_status(item["level"])
        with sub_cols[idx]:
            st.metric(item["title"], item["value"], item["detail"])
            st.markdown(format_status_chip(item["status"], color), unsafe_allow_html=True)

    if alerts:
        with st.expander("오늘 확인할 항목", expanded=True):
            for alert in alerts[:6]:
                st.write(f"- {alert}")
    else:
        st.success("오늘 바로 조치가 필요한 KPI 경고는 없습니다.")


def render_asset_overview_dashboard(holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw, reserve_target_weight):
    full_df = append_cash_rows(
        holdings_table.copy(),
        krw_cash,
        usd_cash,
        usdkrw,
        portfolio_summary["current_asset"]
    )
    reserve_summary = calc_reserve_summary(full_df, reserve_target_weight)

    current_asset = clean_float(portfolio_summary.get("current_asset"), 0.0)
    stock_value = clean_float(portfolio_summary.get("stock_value"), 0.0)
    cash_value = clean_float(portfolio_summary.get("cash_value"), 0.0)
    total_dividend = clean_float(portfolio_summary.get("total_dividend"), 0.0)
    cum_profit = clean_float(portfolio_summary.get("cum_profit"), 0.0)
    cum_return = clean_float(portfolio_summary.get("cum_return"), 0.0)
    invest_value = clean_float(reserve_summary.get("invest_value"), 0.0)
    waiting_value = clean_float(reserve_summary.get("waiting_value"), 0.0)
    waiting_pct = clean_float(reserve_summary.get("waiting_pct"), 0.0)
    target_pct = clean_float(reserve_summary.get("target_pct"), 0.0)
    excess_pct = clean_float(reserve_summary.get("excess_pct"), 0.0)

    profit_label = "수익" if cum_profit >= 0 else "손실"
    profit_delta = f"{cum_return:.2f}%"
    waiting_gap = waiting_pct - target_pct
    waiting_delta = f"{waiting_gap:+.2f}%p vs 목표"
    invest_pct = (invest_value / current_asset * 100) if current_asset > 0 else 0.0

    kpis, alerts = build_asset_overview_kpis(holdings_table, portfolio_summary, reserve_summary)
    render_kpi_summary_panel(kpis, alerts)

    st.markdown("### 자산 현황 요약")
    top_cols = st.columns(4)
    top_cols[0].metric("총자산", f"{current_asset:,.0f}원", f"투자자산 {stock_value:,.0f}원")
    top_cols[1].metric(f"누적{profit_label}", f"{cum_profit:,.0f}원", profit_delta)
    top_cols[2].metric("누적수익률", f"{cum_return:.2f}%", f"누적배당 {total_dividend:,.0f}원")
    top_cols[3].metric("대기자금", f"{waiting_value:,.0f}원", waiting_delta)

    detail_cols = st.columns(4)
    detail_cols[0].metric("투자자산", f"{invest_value:,.0f}원", f"{invest_pct:.2f}%")
    detail_cols[1].metric("현금/예수금", f"{cash_value:,.0f}원")
    detail_cols[2].metric("대기자금 목표", f"{target_pct:.2f}%")
    detail_cols[3].metric("초과 대기자금", f"{clean_float(reserve_summary.get('deployable_value'), 0.0):,.0f}원", f"{excess_pct:.2f}%p")

    gauge_cols = st.columns([2, 2, 1.2])
    with gauge_cols[0]:
        st.caption(f"투자자산 비중 {invest_pct:.2f}%")
        st.progress(min(max(invest_pct / 100, 0.0), 1.0))
    with gauge_cols[1]:
        st.caption(f"대기자금 비중 {waiting_pct:.2f}% / 목표 {target_pct:.2f}%")
        st.progress(min(max(waiting_pct / 100, 0.0), 1.0))
    with gauge_cols[2]:
        last_price_refresh_time = st.session_state.get("latest_price_refresh_time", "-")
        st.caption("현재가 갱신")
        st.write(last_price_refresh_time)

    st.caption("평소에는 자산관리 표 옆 현재가 새로고침만 눌러도 충분합니다. 재무/뉴스 새로고침은 필요할 때만 사용하세요.")


def render_speed_check_tab():
    st.subheader("속도 점검")
    st.caption("로딩이 느릴 때 어느 데이터를 다시 불러오는지 구분하기 위한 읽기 전용 점검판입니다.")

    rows = [
        {
            "구분": "현재가",
            "체감속도": "빠름",
            "캐시": "60초",
            "마지막 수동갱신": get_refresh_event_time("latest_price_refresh_time"),
            "사용 위치": "보유자산 평가금액, 정밀관측소 현재가",
            "버튼": "전체 현재가 새로고침",
        },
        {
            "구분": "차트/기술",
            "체감속도": "중간",
            "캐시": "5분",
            "마지막 수동갱신": get_refresh_event_time("chart_price_refresh_time"),
            "사용 위치": "전광판, 정밀관측소 차트/기술점수, 단기 흐름",
            "버튼": "전체 차트/기술 새로고침",
        },
        {
            "구분": "뉴스/리포트",
            "체감속도": "중간",
            "캐시": "뉴스 10분 / 목표가 6시간",
            "마지막 수동갱신": get_refresh_event_time("news_report_refresh_time"),
            "사용 위치": "정밀관측소 뉴스, 증권사/애널리스트 링크",
            "버튼": "전체 뉴스/리포트 새로고침",
        },
        {
            "구분": "재무점수/매크로",
            "체감속도": "무거움",
            "캐시": "재무 6시간 / 매크로 5분",
            "마지막 수동갱신": get_refresh_event_time("fin_macro_refresh_time"),
            "사용 위치": "재무점수, 후보등급, 매크로 패널티",
            "버튼": "전체 재무점수/매크로 새로고침",
        },
    ]

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("보유종목", f"{len(holdings_df)}개")
    m2.metric("전광판", f"{len(st.session_state.get('watchlist', []))}개")
    m3.metric("현금 포함 자산", f"{portfolio_summary['current_asset']:,.0f}원")
    m4.metric("화면 생성", get_kst_now().strftime("%H:%M:%S"))

    st.info("평소에는 현재가만 새로고침하면 충분합니다. 차트/기술, 뉴스/리포트, 재무점수는 필요할 때만 눌러야 덜 버벅입니다.")
    render_data_basis_caption("속도점검", include_news=True, include_fin=True)


# -------------------------------------------------
# 8. 메인 UI 렌더링
# -------------------------------------------------
macro_res, final_macro_risk, macro_penalty, move_val = get_macro_analysis()
st.caption(f"모드: {app_mode} | 매크로 리스크: {final_macro_risk:.1f} | 매크로 패널티: -{macro_penalty}")

if macro_res:
    m_cols = st.columns(len(macro_res))
    for i, (n, info) in enumerate(macro_res.items()):
        s_tag = "<br><span style='color:#ef4444; font-weight:bold;'>🚨폭풍</span>" if info["storm"] and n != "환율" else ""
        m_cols[i].markdown(f"<div class='macro-panel'>🌐 {n}: <b>{info['val']:,.1f}</b> {info['icon']}{s_tag}</div>", unsafe_allow_html=True)
else:
    st.info("매크로 데이터를 불러오지 못했습니다.")

settings = load_settings_db()
holdings_df = load_holdings_db()
dividends_df = load_dividends_db()
monthly_logs_df = load_monthly_logs_db()

seed_money = float(settings.get("seed_money", 0.0))
krw_cash = float(settings.get("krw_cash", 0.0))
usd_cash = float(settings.get("usd_cash", 0.0))
saved_usdkrw = float(settings.get("usdkrw", 1400.0))
auto_usdkrw = load_usdkrw_rate()
usdkrw = float(auto_usdkrw) if auto_usdkrw and auto_usdkrw > 0 else saved_usdkrw
usdkrw_source = "자동 환율" if auto_usdkrw and auto_usdkrw > 0 else "저장 환율"
effective_settings = dict(settings)
effective_settings["usdkrw"] = usdkrw
reserve_target_weight = float(settings.get("reserve_target_weight", 10.0))      

render_refresh_control_panel()

holdings_table = build_holdings_table(holdings_df, krw_cash, usd_cash, usdkrw)
portfolio_summary = calc_portfolio_summary(holdings_table, seed_money, krw_cash, usd_cash, usdkrw, dividends_df)
total_eval = portfolio_summary["current_asset"]

tab_asset, tab_portfolio, tab_dashboard, tab_precision, tab_scenario, tab_short, tab_backtest, tab_money, tab_kr_etf, tab_swing, tab_feedback, tab_data, tab_speed, tab_manual, tab_guide = st.tabs([
    "💼 자산 현황",
    "📊 포트폴리오 분석",
    "📋 전광판",
    "🔍 정밀관측소",
    "📉 시나리오 점검",
    "📈 단기 흐름 점검",
    "🧪 신호 검증",
    "💸 돈흐름 레이더",
    "💰 월배당 ETF",
    "🎯 스윙 레이더",
    "🎤 피드백/Q&A",
    "🧪 데이터 점검",
    "⏱ 속도 점검",
    "📘 판정 매뉴얼",
    "📖 사용 가이드",
])

with tab_dashboard:
    st.subheader("CCTV 통합 통제실")
    render_data_basis_caption("전광판", include_fin=True)
    st.write(
        f"현재자산: {portfolio_summary['current_asset']:,.0f}원 | "
        f"누적손익: {portfolio_summary['cum_profit']:,.0f}원 | "
        f"누적수익률: {portfolio_summary['cum_return']:.2f}% | "
        f"누적배당금: {portfolio_summary['total_dividend']:,.0f}원"
    )
    st.caption("전광판 등록 종목만 표시됩니다.")

    remove_options = ["선택"] + [
        f"{sanitize_asset_name(item.get('name', ''), item.get('ticker', ''))}|{sanitize_ticker_value(item.get('ticker', ''))}"
        for item in st.session_state.watchlist
    ]
    remove_target = st.selectbox("제거할 종목", remove_options, key="remove_watchlist_target")

    if remove_target != "선택" and st.button("전광판에서 제거"):
        _, remove_ticker = remove_target.split("|", 1)
        st.session_state.watchlist = [item for item in st.session_state.watchlist if normalize_ticker(item["ticker"]) != normalize_ticker(remove_ticker)]
        sync_watchlist_to_query()
        st.rerun()

    summary_df = get_all_summary(tuple(sorted(st.session_state.fin_score_map.items())), app_mode, tuple(st.session_state.watchlist))
    if summary_df.empty:
        st.warning("전광판에 표시할 종목이 없습니다.")
    else:
        quick_jump_map = {
            f"{row['종목명']} ({row['티커']})": row["티커"]
            for _, row in summary_df.iterrows()
        }
        quick_jump_cols = st.columns([2.6, 1.0, 2.4])
        with quick_jump_cols[0]:
            quick_jump_label = st.selectbox(
                "정밀관측소로 보낼 종목",
                ["선택"] + list(quick_jump_map.keys()),
                key="dashboard_precision_jump_target",
            )
        with quick_jump_cols[1]:
            st.write("")
            st.write("")
            if st.button("선택값 적용", key="dashboard_precision_jump_apply", use_container_width=True):
                jump_ticker = quick_jump_map.get(quick_jump_label, "")
                if not jump_ticker:
                    st.warning("먼저 종목을 선택하세요.")
                else:
                    precision_options, precision_option_map_for_jump = build_precision_select_options()
                    precision_label = find_precision_select_label_by_ticker(jump_ticker, precision_option_map_for_jump)
                    if precision_label:
                        st.session_state["precision_selected_option"] = precision_label
                        st.success("정밀관측소 선택값을 바꿨습니다. 위의 정밀관측소 탭을 열어 확인하세요.")
                    else:
                        st.warning("정밀관측소 선택값으로 연결할 수 없습니다. 자유 종목 탐색에서 직접 입력해 주세요.")
        with quick_jump_cols[2]:
            st.caption("전광판에서 종목을 고른 뒤 적용하면 정밀관측소의 종목 선택이 그 종목으로 맞춰집니다.")

        st.markdown("#### 전광판 보기")
        group_order = ["전체", "한국 ETF", "한국 개별주", "미국 ETF", "미국 개별주"]
        group_tabs = st.tabs([
            f"{label} ({len(summary_df) if label == '전체' else int((summary_df['전광판그룹'] == label).sum())})"
            for label in group_order
        ])

        for group_tab, group_label in zip(group_tabs, group_order):
            with group_tab:
                render_dashboard_group_summary(summary_df, group_label)

with tab_precision:
    options, precision_option_map = build_precision_select_options()
    if st.session_state.get("precision_selected_option") not in options:
        st.session_state["precision_selected_option"] = options[0]
    sel = st.selectbox("종목 선택", options, key="precision_selected_option")
    selected_option = precision_option_map.get(sel, {"type": "preset"})
    is_free = (selected_option.get("type") == "free")

    if is_free:
        c1, c2 = st.columns([2, 1])
        with c1: user_tkr_raw = sanitize_ticker_value(st.text_input("티커/종목코드 (예: GOOGL, 005930)", "GOOGL"))
        with c2: mkt_opt = st.selectbox("시장 (한국주식 시)", ["KOSPI (.KS)", "KOSDAQ (.KQ)"])

        tkr = f"{user_tkr_raw}{'.KS' if 'KOSPI' in mkt_opt else '.KQ'}" if (user_tkr_raw.isdigit() and len(user_tkr_raw) == 6) else user_tkr_raw
        tkr = sanitize_ticker_value(tkr)

        known_sp500_etfs = {"SPY", "VOO", "IVV", "SPLG", "SPYM", "379800.KS"}
        known_nasdaq_etfs = {"QQQ", "QQQM", "QLD", "TQQQ", "379810.KS"}
        ticker_norm = normalize_ticker(tkr)
        is_etf = is_fin_score_exempt_asset(tkr)
        
        if is_etf:
            a_class = infer_asset_class_for_ticker(tkr)
        else:
            a_class = "kr_stock" if tkr.endswith((".KS", ".KQ")) else "us_stock"

        name = sanitize_asset_name("", tkr)
        my_p, has_p = 0.0, False
    elif selected_option.get("type") == "watchlist":
        watch_item = selected_option.get("item", {})
        tkr = sanitize_ticker_value(watch_item.get("ticker", ""))
        name = sanitize_asset_name(watch_item.get("name", ""), tkr)
        is_etf = is_fin_score_exempt_asset(tkr, watch_item.get("is_etf", False), watch_item.get("asset_class", ""), name)
        a_class = infer_asset_class_for_ticker(tkr, watch_item.get("asset_class", "")) if is_etf else str(watch_item.get("asset_class", "")).strip()
        my_p, has_p = get_my_price(name, tkr), has_position(name, tkr)
    else:
        name = sel
        tkr, is_etf, a_class = TICKER_MAP[sel]
        my_p, has_p = get_my_price(name, tkr), has_position(name, tkr)

    render_data_basis_caption("정밀관측소", tkr, include_news=True, include_fin=True)

    u_asset, u_price, u_curr_w, u_targ_w = 0.0, my_p, 0.0, 0.0
    if app_mode == "범용모드":
        st.markdown("### 🧩 범용 입력값")
        in1, in2 = st.columns(2)
        with in1:
            u_asset = st.number_input("총 자산(원)", min_value=0.0, value=10000000.0, step=100000.0)
            u_price = st.number_input("내 평단가", min_value=0.0, value=0.0, step=1.0)
        with in2:
            u_curr_w = st.number_input("현재비중(%)", min_value=0.0, value=0.0, step=0.1)
            u_targ_w = st.number_input("목표비중(%)", min_value=0.0, value=0.0, step=0.1)

    f_labels = get_fin_label_map()
    fin_key = normalize_ticker(tkr)

    auto_fin_exempt = is_fin_score_exempt_asset(tkr, is_etf, a_class, name)
    fin_exempt_selected = st.checkbox(
        "ETF/ETN/레버리지 상품: 재무점수 해당없음",
        value=auto_fin_exempt,
        disabled=is_known_etf_ticker(tkr),
        key=f"fin_score_exempt_{fin_key}",
        help="체크하면 재무점수 수동 선택을 쓰지 않고 해당 종목의 재무점수를 '해당없음'으로 처리합니다.",
    )
    if is_known_etf_ticker(tkr):
        fin_exempt_selected = True

    if fin_exempt_selected:
        is_etf = True
        a_class = infer_asset_class_for_ticker(tkr, a_class)
        marker_key = f"fin_score_exempt_marked_{fin_key}"
        if not st.session_state.get(marker_key, False):
            mark_fin_score_not_applicable_db(tkr)
            st.session_state[marker_key] = True
    else:
        is_etf = False
        st.session_state[f"fin_score_exempt_marked_{fin_key}"] = False
        if asset_class_marks_fin_score_exempt(a_class):
            a_class = "kr_stock" if is_kr_listed(tkr) else "us_stock"

    fin_score, fin_meta = load_fin_score_meta_fast(tkr, is_etf)
    fin_score = int(fin_score)
    
    if fin_score not in f_labels:
        fin_score = UNCALCULATED_FIN_DEFAULT_SCORE
        
    st.session_state.fin_score_map[fin_key] = fin_score

    st.markdown(f"<div class='info-panel'><b>재무 점수</b><br>{f_labels[fin_score]}</div>", unsafe_allow_html=True)

    with st.expander("재무점수 계산 근거"):
        notes, metrics, weighted = get_fin_meta_parts(fin_meta)

        if not is_etf:
            if st.button("자동 재무점수 돌리기", key=f"run_auto_fin_{fin_key}"):
                with st.spinner("DART/FMP 재무 자동 계산 중..."):
                    clear_financial_api_cache()
                    new_score, _ = get_final_fin_score(tkr, is_etf, a_class)
                    st.session_state.fin_score_map[fin_key] = int(new_score)
                st.success("자동 재무점수 계산 완료")
                st.rerun()

        annual_judgements = notes.get("annual_judgements", {})
        quarter_judgements = notes.get("quarter_judgements", {})

        summary_tab, judgement_tab, raw_tab = st.tabs(["요약", "판정표", "원자료"])

        with summary_tab:
            render_fin_health_summary(fin_score, fin_meta, is_etf=is_etf)

        with judgement_tab:
            meta_rows = [
                {"항목": "source", "값": fin_meta.get("source")},
                {"항목": "mode", "값": fin_meta.get("mode")},
                {"항목": "auto_score", "값": fin_meta.get("auto_score")},
                {"항목": "manual_score", "값": fin_meta.get("manual_score")},
                {"항목": "final_score", "값": fin_meta.get("final_score")},
            ]
            st.dataframe(pd.DataFrame(meta_rows), use_container_width=True, hide_index=True)

            if weighted:
                weighted_rows = [
                    {"항목": "weighted score", "값": weighted.get("weighted_net_score")},
                    {"항목": "S_sum", "값": weighted.get("s_sum")},
                    {"항목": "A_sum", "값": weighted.get("a_sum")},
                    {"항목": "B_sum", "값": weighted.get("b_sum")},
                    {"항목": "danger_count", "값": weighted.get("danger_count")},
                    {"항목": "범용판단", "값": weighted.get("generic_score")},
                    {"항목": "수주판단", "값": weighted.get("order_score")},
                    {"항목": "중간형판단", "값": weighted.get("middle_score")},
                    {"항목": "selected_mode", "값": weighted.get("selected_mode")},
                ]
                st.markdown("#### 가중 판정")
                st.dataframe(pd.DataFrame(weighted_rows), use_container_width=True, hide_index=True)

            st.markdown("#### 연간 판정 문구")
            if annual_judgements:
                st.dataframe(pd.DataFrame([{"key": k, "judgement": v} for k, v in annual_judgements.items()]), use_container_width=True, hide_index=True)
            else:
                st.write("연간 판정 없음")

            st.markdown("#### 분기 판정 문구")
            if quarter_judgements:
                st.dataframe(pd.DataFrame([{"key": k, "judgement": v} for k, v in quarter_judgements.items()]), use_container_width=True, hide_index=True)
            else:
                st.write("분기 판정 없음")

            messages = notes.get("messages", [])
            if messages:
                st.markdown("#### notes")
                for msg in messages: st.write("-", msg)

        with raw_tab:
            annual_records = metrics.get("annual_records", [])
            quarter_records = metrics.get("quarter_records", [])

            if annual_records:
                st.write("annual records")
                st.dataframe(pd.DataFrame(annual_records), use_container_width=True, hide_index=True)
            else:
                st.write("annual records 없음")

            if quarter_records:
                st.write("quarter records")
                st.dataframe(pd.DataFrame(quarter_records), use_container_width=True, hide_index=True)
            else:
                st.write("quarter records 없음")

            derived = metrics.get("derived", {})
            if derived:
                st.write("derived metrics")
                st.json(derived)
            else:
                st.write("derived metrics 없음")

    if is_etf:
        st.info("ETF/ETN/레버리지 상품은 재무점수 해당없음입니다. 수동 재무점수도 적용하지 않습니다.")
    else:
        had_manual = fin_meta.get("manual_score") is not None
        manual_override = st.checkbox("재무점수 수동 수정", value=had_manual, key=f"manual_fin_{fin_key}")

        if had_manual and not manual_override:
            reset_manual_fin_score(tkr)
            st.session_state.fin_score_map.pop(fin_key, None)
            st.rerun()

        if manual_override:
            manual_options = [1, 2, 3, 4]
            current_manual = fin_meta.get("manual_score")
            radio_default_value = int(current_manual) if current_manual in manual_options else int(fin_score)
            if radio_default_value not in manual_options: radio_default_value = 3

            manual_score = st.radio("수동 재무점수", manual_options, index=manual_options.index(radio_default_value), format_func=lambda x: f_labels[x], horizontal=True, key=f"manual_fin_score_{fin_key}")

            if current_manual != int(manual_score):
                set_manual_fin_score(tkr, manual_score)
                st.session_state.fin_score_map[fin_key] = int(manual_score)
                st.rerun()

            fin_score = int(manual_score)

            if st.button("자동 재무점수로 되돌리기", key=f"reset_manual_{fin_key}"):
                reset_manual_fin_score(tkr)
                st.session_state.fin_score_map.pop(fin_key, None)
                st.rerun()

    st.markdown("### ⭐ 관심종목 관리")
    a1, a2 = st.columns(2)

    current_item = {"name": sanitize_asset_name(name, tkr), "ticker": sanitize_ticker_value(tkr), "is_etf": is_etf, "asset_class": a_class, "fin_score": int(fin_score)}

    if is_in_watchlist(tkr):
        for item in st.session_state.watchlist:
            if normalize_ticker(item["ticker"]) == normalize_ticker(tkr):
                item["fin_score"] = int(fin_score)
                break
        sync_watchlist_to_query()

    with a1:
        if is_in_watchlist(tkr): st.success("이미 전광판에 등록된 종목입니다.")
        else:
            if st.button("전광판에 등록"):
                 st.session_state.watchlist.append(current_item)
                 persist_watchlist()
                 st.rerun()
                
    with a2:
        if is_in_watchlist(tkr):
            if st.button("전광판에서 제거", key=f"remove_{normalize_ticker(tkr)}"):
                st.session_state.watchlist = [item for item in st.session_state.watchlist if normalize_ticker(item["ticker"]) != normalize_ticker(tkr)]
                persist_watchlist()
                st.rerun()

    df = load_price_df(tkr, "1y")
    if not df.empty:
        df = build_indicators(df)
        c = calc_scores_and_decision(name, tkr, is_etf, a_class, df, u_price if app_mode=="범용모드" else my_p, 
                                     (u_price > 0 or u_curr_w > 0) if app_mode=="범용모드" else has_p, fin_score, is_free, 
                                     app_mode, u_asset, u_curr_w, u_targ_w)

        L, R = st.columns([1.1, 2.4])
        with L:
            st.markdown(f"<h2>📊 {escape_html_value(name)}</h2>", unsafe_allow_html=True)
            dd_c = "#dc2626" if c['dd'] <= -0.2 else ("#d97706" if c['dd'] <= -0.1 else "#2ecc71")
            ret3_color = "#2ecc71" if c["ret_3m"] > 0 else "#dc2626"
            ret6_color = "#2ecc71" if c["ret_6m"] > 0 else "#dc2626"
            display_cur_p = load_latest_price(tkr)
            if display_cur_p <= 0:
                display_cur_p = c["cur_p"]
            price_refresh_key = f"precision_price_refresh_time_{fin_key}"
            price_refresh_time = st.session_state.get(price_refresh_key)
            price_source = "최신/프리 가능" if abs(float(display_cur_p) - float(c["cur_p"])) > 1e-9 else "일봉 기준"

            price_info_col, price_refresh_col = st.columns([2.2, 1])
            with price_info_col:
                st.markdown(
                    f"<div class='info-panel'>현재가: <span class='highlight'>{format_currency(display_cur_p, tkr)}</span><br>"
                    f"3개월 수익률: <span style='color:{ret3_color}; font-weight:bold;'>{c['ret_3m']*100:.1f}%</span><br>"
                    f"6개월 수익률: <span style='color:{ret6_color}; font-weight:bold;'>{c['ret_6m']*100:.1f}%</span><br>"
                    f"고점대비 MDD: <span style='color:{dd_c}; font-weight:bold;'>{c['dd']*100:.1f}%</span></div>",
                    unsafe_allow_html=True
                )
            with price_refresh_col:
                st.caption("현재가")
                if st.button("새로고침", key=f"refresh_precision_price_{fin_key}", use_container_width=True, help="선택 종목의 현재가 캐시를 비우고 다시 조회합니다. 미국장은 가능하면 프리/애프터 가격을 반영합니다."):
                    clear_selected_price_cache()
                    st.session_state[price_refresh_key] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                    st.toast(f"{tkr} 현재가를 다시 조회합니다.")
                    st.rerun()
                st.caption(price_source)
                if price_refresh_time:
                    st.caption(f"갱신 {price_refresh_time[-8:]}")

            if is_free or app_mode == "범용모드": st.info("💡 직접 입력 기반 분석 모드입니다.")
            else:
                if has_p and my_p > 0: st.markdown(f"<div class='info-panel' style='border-left: 5px solid #27ae60;'><b>내 평단가 (DB 연동)</b><br><span class='highlight' style='color:#2ecc71;'>{format_currency(my_p, tkr)}</span></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-panel'><b>비중</b><br>목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>부족 매수액: {c['buy_amt']:,.0f}원</div>", unsafe_allow_html=True)

            if app_mode == "범용모드": 
                st.markdown(f"<div class='info-panel'><b>입력 기준</b><br>총 자산: {u_asset:,.0f}원<br>평단가: {format_currency(u_price, tkr)}<br>목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br><b>부족 매수액: {c['buy_amt']:,.0f}원</b></div>", unsafe_allow_html=True)

            st.markdown(f'<div class="signal-box" style="background-color: {c["col"]};"><div style="font-size: 1.5em;">{c["dec"]}</div><div class="score-detail">Adj: {c["adj"]:.1f}점</div></div>', unsafe_allow_html=True)

            fin_text = "해당없음" if is_etf else f"{c['fin_score']}/4"
            st.markdown(
                f"<div class='info-panel' style='border-left: 5px solid #8b5cf6;'><b>📌 후보 등급 판정</b><br>"
                f"<span class='highlight' style='font-size:1.1em;'>{c['grade']}</span> (총점: {c['t_score']}점)<br>"
                f"└ 🛠️기술: {c['tech_total']} (RS:{c['rs_s']}, MFI:{c['mfi_s']}, 추세:{c['trend_s']}, MACD:{c['macd_s']}, SQZ:{c['sqz_s']})<br>"
                f"└ 💰재무: {fin_text}</div>", unsafe_allow_html=True
            )

        with R:
            fig = go.Figure(data=[go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Price")])
            fig.add_trace(go.Scatter(x=df.index, y=df["MA5"], line=dict(color="#22c55e", width=1.4), name="MA5"))
            fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], line=dict(color="#fbbf24", width=2), name="MA20"))
            fig.add_trace(go.Scatter(x=df.index, y=df["MA50"], line=dict(color="#60a5fa", width=1.6), name="MA50"))
            fig.add_trace(go.Scatter(x=df.index, y=df["MA120"], line=dict(color="#94a3b8", width=1.5, dash="dot"), name="MA120"))
            p_line = u_price if app_mode == "범용모드" else my_p
            if p_line > 0 and ((app_mode == "범용모드" and c['current_w'] > 0) or (app_mode == "개인모드" and not is_free and has_p)): 
                fig.add_hline(y=p_line, line_dash="dash", line_color="#2ecc71", annotation_text="내 평단가")
            fig.update_layout(template="plotly_dark", height=600, xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        b1, b2 = st.columns(2)
        with b1: 
            f_txt = f"{c['fvg_type']} | {'미충족' if c['fvg_active'] else '터치됨'}" if c['fvg_type'] != "없음" else "없음"
            st.markdown(f"<div class='info-panel' style='border-left: 5px solid #e67e22;'><b>🛡️ SMC 구조 해석</b><br>• 외부구조: <b>{c['ext_structure']}</b><br>• 내부구조: <b>{c['int_structure']}</b><br>• 내부 이벤트: <b>{c['int_event']}</b><br>• 외부 이벤트: <b>{c['ext_event']}</b><br>• 유동성 상태: <b>{c['liq_state']}</b><br>• FVG 상태: <b>{f_txt}</b><br>• P/D Zone: <b>{c['pd_zone']}</b><br>• 실시간 MACD: <b>{c['rt_macd']}</b><br>• SQZ: <b>{c['sqz']}</b><hr style='margin:10px 0; border-color:#334155;'>🎯 <b>실행 해석:</b> {c['smc_action']}</div>", unsafe_allow_html=True)
        with b2: 
            structure_note = "주의" if c.get("structure_risk") else "정상"
            structure_color = "#fbbf24" if c.get("structure_risk") else "#10b981"
            st.markdown(f"<div class='info-panel' style='border-left: 5px solid #10b981;'><b>📐 전술 지표</b><br>• 추세: <b>{c['trend']}</b> | MACD: <b>{c['macd']}</b><br>• RS: <b>{c['rs_label']}</b> | RSI: <b>{c['rsi']:.1f}</b> | MFI: <b>{c['mfi']:.1f}</b><br>• 볼린저 %B: <b>{c['pct_b']:.2f}</b> | SQZ: <b>{c['sqz']}</b><br>• 전일등락: <b>{c['day_ret']*100:.1f}%</b> | 거래량20일비: <b>{c['vol_ratio']:.1f}x</b> | 구조위험: <b style='color:{structure_color};'>{structure_note}</b><hr style='margin:10px 0; border-color:#334155;'><span class='smc-tag'>MA5</span> {format_currency(c['ma5'], tkr)}<br><span class='smc-tag'>MA20</span> {format_currency(c['ma20'], tkr)}<br><span class='smc-tag'>MA50</span> {format_currency(c['ma50'], tkr)}<br><span class='smc-tag'>MA120</span> {format_currency(c['ma120'], tkr)}<hr style='margin:10px 0; border-color:#334155;'>💡 <b>보조 해석:</b> {c['smc_insight']}</div>", unsafe_allow_html=True)

        render_personal_stock_analysis_panel(name, tkr, is_etf, a_class, c, fin_score, fin_meta, has_p, my_p)

        render_research_report_panel(name, tkr, c["cur_p"], is_etf=is_etf)

        st.markdown("### 📰 최신 현장 뉴스")
        news_items, news_logs = get_ticker_news(tkr, name, news_debug)
        if news_items:
            render_news_cards(news_items)

        else:
            st.info("현재 제공되는 최신 뉴스가 없습니다.")

        if news_debug: 
            with st.expander("🛠️ 뉴스 디버그 로그"):
                for log in news_logs: st.write(log)
        
        st.markdown("### 🤖 AI 종합 해석 프롬프트")
        if st.button("AI 분석용 프롬프트 생성", key=f"ai_analysis_{normalize_ticker(tkr)}"):
            prompt = build_ai_analysis_prompt(name, tkr, macro_res, final_macro_risk, c)
            st.info("아래 프롬프트를 복사해서 ChatGPT나 Gemini에 붙여넣으면 됩니다.")
            st.text_area("분석용 프롬프트", value=prompt, height=500, key=f"prompt_box_{normalize_ticker(tkr)}")
    else: st.error("해당 종목의 차트 데이터를 불러올 수 없습니다. 티커를 다시 확인해 주십시오.")

with tab_asset:
    st.subheader("앱 내부 자산 관리")
    render_data_basis_caption("자산관리", include_fin=True)
    render_asset_overview_dashboard(holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw, reserve_target_weight)
    render_asset_quick_quality_summary(effective_settings, holdings_df, dividends_df, monthly_logs_df)
    render_monthly_record_status(monthly_logs_df, portfolio_summary)

    with st.expander("0) 백업 다운로드", expanded=False):
    
        backup_dash_df = append_cash_rows(
            holdings_table.copy(),
            krw_cash,
            usd_cash,
            usdkrw,
            portfolio_summary["current_asset"]
        )
        fin_scores_backup_df = load_fin_scores_db()
    
        bkp1, bkp2, bkp3, bkp4 = st.columns(4)
        bkp1.metric("보유종목 DB", f"{count_valid_rows(holdings_df, ['ticker'])}건")
        bkp2.metric("배당 DB", f"{count_valid_rows(dividends_df, ['date', 'ticker'])}건")
        bkp3.metric("월별 로그", f"{count_valid_rows(monthly_logs_df, ['month'])}건")
        bkp4.metric("관심종목", f"{len(st.session_state.watchlist)}건")
    
        backup_stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M")
        swing_radar_backup_df, _ = load_swing_radar_db_safe()
        backup_zip = build_portfolio_backup_zip(
            settings=settings,
            holdings_df=holdings_df,
            dividends_df=dividends_df,
            monthly_logs_df=monthly_logs_df,
            watchlist_items=st.session_state.watchlist,
            dashboard_df=backup_dash_df,
            fin_scores_df=fin_scores_backup_df,
            swing_radar_df=swing_radar_backup_df,
        )
        st.download_button(
            "현재 Supabase 데이터 ZIP 백업",
            data=backup_zip,
            file_name=f"stock_lab_backup_{backup_stamp}.zip",
            mime="application/zip",
            use_container_width=True,
            key="download_supabase_backup_zip",
        )
    
    with st.expander("CSV 백업 복구", expanded=False):
        st.caption("Supabase/SQLite에서 export한 holdings, dividends, monthly_logs, dashboard CSV를 업로드해 현재 계정으로 복구합니다.")
        recovery_files = st.file_uploader(
            "복구 CSV/ZIP 업로드",
            type=["csv", "zip"],
            accept_multiple_files=True,
            key="recovery_csv_files",
        )

        recovery_fingerprint = tuple(
            (str(getattr(file, "name", "")), int(getattr(file, "size", len(file.getvalue())) or 0))
            for file in (recovery_files or [])
        )
        if st.session_state.get("recovery_file_fingerprint") != recovery_fingerprint:
            st.session_state.recovery_file_fingerprint = recovery_fingerprint
            st.session_state.confirm_restore_from_csvs = False

        recovery_frames, recovery_unknown_files, recovery_read_errors, recovery_parsed_files = collect_recovery_frames(recovery_files)
        recovery_summary_df, recovery_issue_df = build_recovery_preflight_report(
            recovery_frames,
            recovery_unknown_files,
            recovery_read_errors,
        )

        if recovery_files:
            st.markdown("#### 복구 미리보기")

            p1, p2, p3, p4 = st.columns(4)
            p1.metric("인식 데이터", len(recovery_summary_df))
            p2.metric("차단", int((recovery_issue_df["등급"] == "차단").sum()) if not recovery_issue_df.empty else 0)
            p3.metric("주의", int((recovery_issue_df["등급"] == "주의").sum()) if not recovery_issue_df.empty else 0)
            p4.metric("참고", int((recovery_issue_df["등급"] == "참고").sum()) if not recovery_issue_df.empty else 0)

            if not recovery_parsed_files.empty:
                st.dataframe(recovery_parsed_files, use_container_width=True, hide_index=True)

            if not recovery_summary_df.empty:
                st.markdown("##### 반영 예정 데이터")
                st.dataframe(recovery_summary_df, use_container_width=True, hide_index=True)

            if recovery_issue_df.empty:
                st.success("사전 점검에서 차단 항목이 없습니다.")
            else:
                st.markdown("##### 사전 점검 결과")
                st.dataframe(recovery_issue_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "사전 점검 결과 CSV 다운로드",
                    data=dataframe_to_csv_bytes(recovery_issue_df),
                    file_name=f"stock_lab_restore_preflight_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    key="download_restore_preflight_csv",
                )

            if has_recovery_blockers(recovery_issue_df):
                st.error("차단 항목이 있으면 복구를 실행하지 않습니다. 중복 키나 읽기 오류를 먼저 정리하세요.")
            else:
                st.warning("복구 실행 시 보유자산/배당/월별 로그/관심목록/스윙 레이더는 업로드 데이터로 대체될 수 있습니다.")

            st.checkbox(
                "미리보기를 확인했고, 복구 시 현재 계정의 일부 데이터가 대체될 수 있음을 이해했습니다.",
                key="confirm_restore_from_csvs",
            )

        if st.button("업로드 CSV로 복구 실행", key="restore_from_csvs"):
            if not recovery_files:
                st.warning("먼저 복구할 CSV 또는 ZIP 파일을 업로드하세요.")
            elif has_recovery_blockers(recovery_issue_df):
                st.error("복구가 차단되었습니다. 사전 점검의 차단 항목을 먼저 해결하세요.")
            elif not st.session_state.get("confirm_restore_from_csvs", False):
                st.warning("복구 미리보기를 확인했다는 체크가 필요합니다.")
            else:
                restored, unknown_files = restore_from_uploaded_csvs(recovery_files)

                if restored:
                    st.success("복구 완료: " + ", ".join(restored))
                    if unknown_files:
                        st.warning("인식하지 못한 파일: " + ", ".join(unknown_files))
                    st.rerun()
                else:
                    st.warning("복구할 수 있는 CSV를 찾지 못했습니다.")

    with st.expander("입력/수정 영역", expanded=False):
        st.caption("기본 설정, 보유종목, 배당, 월별 로그를 수정할 때만 열어주세요.")
        st.markdown("### 1) 기본 설정")
        st.caption(
            f"현재 계산 환율: {usdkrw:,.2f} ({usdkrw_source}) | "
            f"저장 환율: {saved_usdkrw:,.2f}"
        )
        col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
        with col_s1: new_seed = st.number_input("시드머니", min_value=0.0, value=float(seed_money), step=100000.0)
        with col_s2: new_krw = st.number_input("원화 예수금", min_value=0.0, value=float(krw_cash), step=100000.0)
        with col_s3: new_usd = st.number_input("달러 예수금", min_value=0.0, value=float(usd_cash), step=100.0)
        with col_s4: new_fx = st.number_input("환율(USDKRW)", min_value=0.0, value=float(usdkrw), step=1.0, help="기본값은 자동 조회 환율입니다. 자동 조회 실패 시 저장된 환율을 사용합니다.")
        with col_s5: new_reserve_target = st.number_input("대기자금 목표비중(%)", min_value=0.0, max_value=100.0, value=float(reserve_target_weight), step=0.5)
    
        fx_c1, fx_c2 = st.columns([1, 4])
        with fx_c1:
            if st.button("환율 다시 조회", key="refresh_usdkrw_rate"):
                cache_clear(load_usdkrw_rate)
                st.rerun()
        with fx_c2:
            if auto_usdkrw and auto_usdkrw > 0:
                st.caption("자동 환율을 저장해두고 싶으면 기본 설정 저장을 누르면 됩니다.")
            else:
                st.caption("자동 환율 조회가 실패해 저장 환율로 계산 중입니다. 필요하면 직접 수정 후 저장하세요.")
    
        if st.button("기본 설정 저장"):
            save_settings_db(new_seed, new_krw, new_usd, new_fx, new_reserve_target)
            st.success("기본 설정 저장 완료")
            st.rerun()
    
        st.markdown("### 2) 보유 종목 관리")
        holdings_editor_df = load_holdings_db()
        if holdings_editor_df.empty: holdings_editor_df = pd.DataFrame(columns=["name", "ticker", "qty", "avg_price", "target_weight", "asset_class", "is_etf"])
        if "bucket" not in holdings_editor_df.columns:
            holdings_editor_df["bucket"] = "core"
    
        holdings_editor_df["bucket"] = holdings_editor_df.apply(
            lambda r: infer_bucket(r.get("ticker", ""), r.get("bucket", "core")),
            axis=1
        )
    
        st.caption("bucket: core=장기투자, swing=스윙후보, reserve=비상대기/파킹. 원화/달러 예수금은 자동 cash 처리됩니다.")
            
        edited_holdings = st.data_editor(
            holdings_editor_df,
            num_rows="dynamic",
            use_container_width=True,
            key="holdings_editor",
            column_config={
                "is_etf": st.column_config.CheckboxColumn(
                    "ETF/ETN/레버리지",
                    help="체크하면 재무점수를 해당없음으로 처리하고 기존 수동 재무점수는 적용하지 않습니다."
                ),
                "asset_class": st.column_config.SelectboxColumn(
                    "asset_class",
                    options=["", "kr_stock", "us_stock", "us_stock_tech", "us_stock_growth", "kr_etf", "us_etf_sp", "us_etf_nasdaq", "us_etf_other", "kr_etn", "us_etn", "fund"],
                    help="ETF/ETN/레버리지 상품은 ETF/ETN 계열로 선택"
                ),
                "bucket": st.column_config.SelectboxColumn(
                    "bucket",
                    options=["core", "swing", "reserve"],
                    help="357870.KS, SGOV 같은 파킹자산은 reserve로 설정"
                )
            }
        )
    
        if st.button("보유 종목 저장"):
            if save_holdings_db(edited_holdings.fillna("")):
                st.success("보유 종목 저장 완료")
                st.rerun()
    
        st.markdown("### 3) 배당 내역 관리")
        dividends_editor_df = load_dividends_db()
        if dividends_editor_df.empty: dividends_editor_df = pd.DataFrame(columns=["date", "ticker", "amount", "currency"])
        edited_dividends = st.data_editor(dividends_editor_df, num_rows="dynamic", use_container_width=True, key="dividends_editor")
    
        if st.button("배당 내역 저장"):
            if save_dividends_db(edited_dividends.fillna("")):
                st.success("배당 내역 저장 완료")
                st.rerun()
    
        st.markdown("### 4) 월별 로그 관리")
        monthly_editor_df = load_monthly_logs_db()
        if monthly_editor_df.empty: monthly_editor_df = pd.DataFrame(columns=["month", "total_invested", "evaluated_value", "dividend"])
        edited_monthly = st.data_editor(monthly_editor_df, num_rows="dynamic", use_container_width=True, key="monthly_editor")
    
        if st.button("월별 로그 저장"):
            if save_monthly_logs_db(edited_monthly.fillna("")):
                st.success("월별 로그 저장 완료")
                st.rerun()
    
    st.markdown("### 포트폴리오 상세")
    st.caption("상단 자산 현황 요약의 세부 분포, 비중, 손익, 월별 기록을 확인합니다.")

    dash_df = append_cash_rows(
        holdings_table.copy(),
        krw_cash,
        usd_cash,
        usdkrw,
        portfolio_summary["current_asset"]
    )

    if not dash_df.empty:


        dash_df["평가손익_원화"] = dash_df.apply(
            lambda r: r["평가손익"] if str(r["티커"]).upper().endswith((".KS", ".KQ"))
            else r["평가손익"] * usdkrw,
            axis=1
        )
        dash_df["수익률_pct"] = dash_df["수익률"] * 100
        
        reserve_summary = calc_reserve_summary(dash_df, reserve_target_weight)

        asset_tech_summary_key = "asset_management_tech_summary_lazy"
        run_asset_tech_summary = get_heavy_analysis_ready(asset_tech_summary_key)

        signal_rows = []
        if run_asset_tech_summary:
            for _, r in dash_df.iterrows():
                tkr = r["티커"]
                name = r["자산명"]
                is_etf = bool(r.get("is_etf", False))
                asset_class = r.get("asset_class", "")

                bucket = normalize_bucket(r.get("bucket", "core"))

                if bucket in ["reserve", "cash"]:
                    label = "즉시투입 예수금" if bucket == "cash" else "비상대기/파킹"
                    signal_rows.append({
                        "티커": tkr,
                        "기술적타점": label,
                        "ADJ점수": 0,
                        "후보등급": "대기자금",
                        "추세": "-",
                        "RS": "-",
                        "RSI": np.nan,
                        "MFI": np.nan,
                        "MACD": "-",
                        "SQZ": "-",
                    })
                    continue
                
                try:
                    px = load_price_df(tkr, "1y")
                    if px.empty or len(px) < 2:
                        continue

                    px = build_indicators(px)
                    fin_score, _ = load_fin_score_meta_fast(tkr, is_etf)

                    c = calc_scores_and_decision(
                        name=name,
                        ticker=tkr,
                        is_etf=is_etf,
                        asset_class=asset_class,
                        df=px,
                        my_price=float(r["매입가"] or 0),
                        has_pos=float(r["보유량"] or 0) > 0,
                        fin_score=int(fin_score),
                        is_free=False,
                        app_mode="개인모드"
                    )

                    signal_rows.append({
                        "티커": tkr,
                        "기술적타점": c["dec"],
                        "ADJ점수": round(c["adj"], 1),
                        "후보등급": c["grade"],
                        "추세": c["trend"],
                        "RS": c["rs_label"],
                        "RSI": round(c["rsi"], 1),
                        "MFI": round(c["mfi"], 1),
                        "MACD": c["macd"],
                        "SQZ": c["sqz"],
                    })
                except Exception as e:
                    signal_rows.append({
                        "티커": tkr,
                        "기술적타점": f"계산 실패: {e}",
                        "ADJ점수": np.nan,
                        "후보등급": "-",
                        "추세": "-",
                        "RS": "-",
                        "RSI": np.nan,
                        "MFI": np.nan,
                        "MACD": "-",
                        "SQZ": "-",
                    })

        signal_df = pd.DataFrame(signal_rows)
        if not signal_df.empty:
            dash_df = dash_df.merge(signal_df, on="티커", how="left")

        defaults = {
            "기술적타점": "-",
            "ADJ점수": 0,
            "후보등급": "-",
            "추세": "-",
            "RS": "-",
            "RSI": np.nan,
            "MFI": np.nan,
            "MACD": "-",
            "SQZ": "-",
        }
        for col, default in defaults.items():
            if col not in dash_df.columns:
                dash_df[col] = default

        dash_df["ADJ점수_num"] = pd.to_numeric(dash_df["ADJ점수"], errors="coerce").fillna(0)

        st.markdown("#### 자산 구성/비중 상세")

        c1, c2 = st.columns([1.1, 1])

        tree_values = dash_df["원화환산"].astype(float).clip(lower=0)
        if tree_values.sum() <= 0:
            tree_values = pd.Series([1] * len(dash_df), index=dash_df.index)

        with c1:
            fig_tree = go.Figure(go.Treemap(
                labels=dash_df["자산명"],
                parents=[""] * len(dash_df),
                values=tree_values,
                marker=dict(
                    colors=dash_df["수익률_pct"],
                    colorscale=[[0, "#dc2626"], [0.5, "#64748b"], [1, "#16a34a"]],
                    cmid=0,
                    colorbar=dict(title="수익률%")
                ),
                customdata=dash_df[["매입가", "현재가", "원화환산", "평가손익_원화", "현재비중", "목표비중", "기술적타점", "ADJ점수"]],
                hovertemplate=
                    "<b>%{label}</b><br>" +
                    "매입가: %{customdata[0]:,.2f}<br>" +
                    "현재가: %{customdata[1]:,.2f}<br>" +
                    "원화환산: ₩%{customdata[2]:,.0f}<br>" +
                    "평가손익: ₩%{customdata[3]:,.0f}<br>" +
                    "현재비중: %{customdata[4]:.2f}%<br>" +
                    "목표비중: %{customdata[5]:.2f}%<br>" +
                    "타점: %{customdata[6]}<br>" +
                    "ADJ: %{customdata[7]}<extra></extra>"
            ))
            fig_tree.update_layout(template="plotly_dark", height=430, title="포트폴리오 히트맵")
            st.plotly_chart(fig_tree, use_container_width=True)

        with c2:
            max_eval = max(float(dash_df["원화환산"].max() or 0), 1.0)
            bubble_size = np.clip(np.sqrt(dash_df["원화환산"] / max_eval) * 55, 14, 55)

            fig_bubble = go.Figure(go.Scatter(
                x=dash_df["비중차이"],
                y=dash_df["수익률_pct"],
                mode="markers+text",
                text=dash_df["자산명"],
                textposition="top center",
                marker=dict(
                    size=bubble_size,
                    color=dash_df["ADJ점수_num"],
                    colorscale="Viridis",
                    showscale=True,
                    colorbar=dict(title="ADJ")
                ),
                customdata=dash_df[["기술적타점", "후보등급", "현재비중", "목표비중"]],
                hovertemplate=
                    "<b>%{text}</b><br>" +
                    "비중차이: %{x:.2f}%<br>" +
                    "수익률: %{y:.2f}%<br>" +
                    "타점: %{customdata[0]}<br>" +
                    "등급: %{customdata[1]}<br>" +
                    "현재/목표: %{customdata[2]:.2f}% / %{customdata[3]:.2f}%<extra></extra>"
            ))
            fig_bubble.add_vline(x=0, line_dash="dash", line_color="#94a3b8")
            fig_bubble.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
            fig_bubble.update_layout(template="plotly_dark", height=430, title="타점/비중/수익률 매트릭스")
            st.plotly_chart(fig_bubble, use_container_width=True)

        w1, w2 = st.columns(2)

        with w1:
            fig_weight = go.Figure()
            fig_weight.add_trace(go.Bar(y=dash_df["자산명"], x=dash_df["현재비중"], orientation="h", name="현재비중"))
            fig_weight.add_trace(go.Bar(y=dash_df["자산명"], x=dash_df["리밸런싱목표비중"], orientation="h", name="관리기준비중"))
            fig_weight.update_layout(template="plotly_dark", barmode="group", height=420, title="현재비중 vs 목표비중")
            st.plotly_chart(fig_weight, use_container_width=True)

        with w2:
            pnl_color = np.where(dash_df["평가손익_원화"] >= 0, "#16a34a", "#dc2626")
            fig_pnl = go.Figure(go.Bar(
                y=dash_df["자산명"],
                x=dash_df["평가손익_원화"],
                orientation="h",
                marker_color=pnl_color
            ))
            fig_pnl.add_vline(x=0, line_color="#94a3b8")
            fig_pnl.update_layout(template="plotly_dark", height=420, title="평가손익 랭킹")
            st.plotly_chart(fig_pnl, use_container_width=True)

        monthly_perf_df = prepare_monthly_performance_df(monthly_logs_df)
        if not monthly_perf_df.empty:
            st.markdown("#### 월별 성과 기록")

            latest_month = monthly_perf_df.iloc[-1]
            m_k1, m_k2, m_k3, m_k4 = st.columns(4)
            m_k1.metric("최근 기록월", str(latest_month["month_label"]))
            m_k2.metric("기록 평가자산", f"{latest_month['evaluated_value']:,.0f}원")
            m_k3.metric("기록 누적손익", f"{latest_month['cum_profit']:,.0f}원")
            m_k4.metric("기록 누적수익률", f"{latest_month['cum_return_pct']:.2f}%")

            p1, p2 = st.columns(2)

            with p1:
                fig_monthly_asset = go.Figure()
                fig_monthly_asset.add_trace(go.Scatter(
                    x=monthly_perf_df["month_label"],
                    y=monthly_perf_df["evaluated_value"],
                    mode="lines+markers",
                    name="자산",
                    line=dict(color="#ef4444", width=3),
                    hovertemplate="%{x}<br>자산: ₩%{y:,.0f}<extra></extra>"
                ))
                fig_monthly_asset.add_trace(go.Scatter(
                    x=monthly_perf_df["month_label"],
                    y=monthly_perf_df["total_invested"],
                    mode="lines+markers",
                    name="원금",
                    line=dict(color="#cbd5e1", width=2),
                    hovertemplate="%{x}<br>원금: ₩%{y:,.0f}<extra></extra>"
                ))
                fig_monthly_asset.update_layout(
                    template="plotly_dark",
                    height=360,
                    title="월별 투자 기록",
                    yaxis_title="원",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0)
                )
                st.plotly_chart(fig_monthly_asset, use_container_width=True)

            with p2:
                pnl_colors = np.where(monthly_perf_df["cum_profit"] >= 0, "#22d3ee", "#ef4444")
                fig_cum_pnl = go.Figure(go.Bar(
                    x=monthly_perf_df["month_label"],
                    y=monthly_perf_df["cum_profit"],
                    marker_color=pnl_colors,
                    hovertemplate="%{x}<br>누적손익: ₩%{y:,.0f}<extra></extra>"
                ))
                fig_cum_pnl.add_hline(y=0, line_color="#94a3b8")
                fig_cum_pnl.update_layout(
                    template="plotly_dark",
                    height=360,
                    title="누적 손익",
                    yaxis_title="원"
                )
                st.plotly_chart(fig_cum_pnl, use_container_width=True)

            p3, p4 = st.columns(2)

            with p3:
                fig_cum_return = go.Figure(go.Scatter(
                    x=monthly_perf_df["month_label"],
                    y=monthly_perf_df["cum_return_pct"],
                    mode="lines+markers",
                    name="누적수익률",
                    line=dict(color="#22c55e", width=3),
                    hovertemplate="%{x}<br>누적수익률: %{y:.2f}%<extra></extra>"
                ))
                fig_cum_return.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
                fig_cum_return.update_layout(
                    template="plotly_dark",
                    height=220,
                    title="월별 누적수익률",
                    yaxis_title="수익률 %"
                )
                st.plotly_chart(fig_cum_return, use_container_width=True)

                benchmark_df = build_benchmark_return_df(monthly_perf_df)
                fig_benchmark = go.Figure()
                if not benchmark_df.empty:
                    color_map = {
                        "내 기간수익률": "#00ff38",
                        "S&P500": "#f87171",
                        "나스닥100": "#60a5fa",
                        "코스피": "#a7f3d0",
                    }
                    for label in benchmark_df["구분"].drop_duplicates():
                        part = benchmark_df[benchmark_df["구분"] == label]
                        fig_benchmark.add_trace(go.Scatter(
                            x=part["month_label"],
                            y=part["수익률_pct"],
                            mode="lines+markers",
                            name=label,
                            line=dict(color=color_map.get(label, "#cbd5e1"), width=3 if label == "내 기간수익률" else 2, dash="solid" if label == "내 기간수익률" else "dot"),
                            hovertemplate=f"%{{x}}<br>{label}: %{{y:.2f}}%<extra></extra>"
                        ))
                fig_benchmark.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
                fig_benchmark.update_layout(
                    template="plotly_dark",
                    height=320,
                    title="첫 기록월 대비 수익률 변화 vs 벤치마크",
                    yaxis_title="수익률 %",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0)
                )
                st.plotly_chart(fig_benchmark, use_container_width=True)

            with p4:
                fig_dividend = go.Figure(go.Bar(
                    x=monthly_perf_df["month_label"],
                    y=monthly_perf_df["dividend"],
                    marker_color="#fbbf24",
                    hovertemplate="%{x}<br>월별배당금: ₩%{y:,.0f}<extra></extra>"
                ))
                fig_dividend.update_layout(
                    template="plotly_dark",
                    height=360,
                    title="월별 배당금",
                    yaxis_title="원"
                )
                st.plotly_chart(fig_dividend, use_container_width=True)
        else:
            st.info("월별 로그를 입력하면 월별 투자 기록, 누적손익, 벤치마크 비교, 배당금 차트가 표시됩니다.")

        asset_summary_title_col, asset_summary_tech_col, asset_summary_refresh_col = st.columns([2.4, 1.2, 1])
        with asset_summary_title_col:
            st.markdown("#### 보유자산 + 기술적 타점 요약")
            if not run_asset_tech_summary:
                st.caption("기술적 타점은 버튼을 누를 때만 계산합니다. 기본 자산 차트는 위에 먼저 표시됩니다.")
        with asset_summary_tech_col:
            render_heavy_analysis_button(asset_tech_summary_key, "기술적 타점계산")
        with asset_summary_refresh_col:
            if st.button("현재가 새로고침", key="refresh_asset_table_latest_prices", use_container_width=True, help="보유자산 평가금액에 쓰는 60초 현재가 캐시를 비우고 다시 조회합니다."):
                clear_latest_price_cache()
                st.session_state["latest_price_refresh_time"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                st.toast("보유자산 현재가를 다시 조회합니다.")
                st.rerun()
        last_price_refresh_time = st.session_state.get("latest_price_refresh_time")
        if last_price_refresh_time:
            st.caption(f"현재가 수동 갱신: {last_price_refresh_time}")
        else:
            st.caption("현재가 캐시: 60초")

        show_cols = [
            "자산명", "티커", "보유량", "매입가", "현재가", "평가금액", "평가손익",
            "평가손익_원화", "수익률_pct", "원화환산", "목표비중", "현재비중", "비중차이",
            "기술적타점", "ADJ점수", "후보등급", "추세", "RS", "RSI", "MFI", "MACD", "SQZ" ,"bucket", "운용대상", "리밸런싱목표비중"
        ]
        st.dataframe(dash_df[[c for c in show_cols if c in dash_df.columns]], use_container_width=True, hide_index=True)

    else:
        st.info("등록된 보유 종목이 없습니다.")

with tab_portfolio:
    render_portfolio_analysis_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight)

with tab_scenario:
    render_scenario_check_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight)

with tab_short:
    render_short_trend_tab(holdings_table, st.session_state.watchlist)

with tab_backtest:
    render_signal_backtest_tab(holdings_table, st.session_state.watchlist)

with tab_money:
    render_money_flow_tab()

with tab_kr_etf:
    render_kr_etf_lab_tab()

with tab_swing:
    render_swing_radar_tab()

with tab_feedback:
    render_feedback_tab()

with tab_data:
    render_data_quality_tab(effective_settings, holdings_df, holdings_table, dividends_df, monthly_logs_df, st.session_state.watchlist)

with tab_speed:
    render_speed_check_tab()

with tab_manual:
    render_manual_tab() 

with tab_guide:
    render_user_guide_tab()


