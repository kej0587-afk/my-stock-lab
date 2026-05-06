from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
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
from supabase import create_client

# -------------------------------------------------
# 1. 기본 설정 및 CSS
# -------------------------------------------------
st.set_page_config(page_title="최종 관제실", layout="wide")

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
    mode = str(st.secrets.get("AUTH_MODE", "")).strip().lower()

    if mode in ["password", "pass", "local"]:
        return "password"
    if mode in ["google", "oauth"]:
        return "google"

    # Emergency-safe default: if APP_PASSWORD is set, avoid Google OAuth.
    if get_secret_value("APP_PASSWORD"):
        return "password"

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

# -------------------------------------------------
# 2. 유틸리티 함수
# -------------------------------------------------
def format_currency(val, ticker):
    if pd.isna(val): return "-"
    if str(ticker).endswith(".KS") or str(ticker).endswith(".KQ"): return f"₩{int(val):,}"
    return f"${val:,.2f}"

def escape_html_value(value):
    return html.escape(str(value or ""))

def normalize_text(x): return str(x).strip().lower()
def normalize_ticker(t): return str(t).strip().lower().replace(".ks", "").replace(".kq", "")
def parse_num(v):
    if pd.isna(v): return 0.0
    s = str(v).replace(",", "").replace("%", "").replace("₩", "").replace("$", "").strip()
    return pd.to_numeric(s, errors="coerce") if s != "" else 0.0

RESERVE_TICKERS = {"357870", "sgov"}
RESERVE_BUCKETS = {"reserve", "cash"}

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

def clean_symbol(ticker):
    return str(ticker).strip().upper().replace(".KS", "").replace(".KQ", "")

def is_kr_listed(ticker):
    return str(ticker).strip().upper().endswith((".KS", ".KQ"))

def is_known_etf_ticker(ticker):
    raw = str(ticker).strip().upper()
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

DEFAULT_WATCHLIST = [
    {"name": "MSFT", "ticker": "MSFT", "is_etf": False, "asset_class": "us_stock"},
    {"name": "QQQM", "ticker": "QQQM", "is_etf": True, "asset_class": "us_etf_nasdaq"},
    {"name": "TQQQ", "ticker": "TQQQ", "is_etf": True, "asset_class": "us_etf_nasdaq"},
    {"name": "하이닉스", "ticker": "000660.KS", "is_etf": False, "asset_class": "kr_stock"},
    {"name": "두산에너빌리티", "ticker": "034020.KS", "is_etf": False, "asset_class": "kr_stock"},
]

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
        return [dict(x) for x in DEFAULT_WATCHLIST]
    loaded = decode_watchlist(raw)
    return loaded if loaded else [dict(x) for x in DEFAULT_WATCHLIST]

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
SETTINGS_COLUMNS = ["seed_money", "krw_cash", "usd_cash", "usdkrw", "reserve_target_weight"]
HOLDINGS_COLUMNS = ["ticker", "name", "qty", "avg_price", "target_weight", "asset_class", "is_etf", "bucket"]
DIVIDENDS_COLUMNS = ["id", "date", "ticker", "amount", "currency"]
MONTHLY_LOG_COLUMNS = ["month", "total_invested", "evaluated_value", "dividend"]
FIN_SCORE_COLUMNS = ["ticker", "auto_score", "manual_score", "final_score", "source", "notes_json"]
WATCHLIST_COLUMNS = ["name", "ticker", "is_etf", "asset_class", "fin_score"]
SWING_RADAR_COLUMNS = [
    "ticker", "name", "asset_class", "idea",
    "check_1", "check_2", "check_3",
    "risk_1", "risk_2", "risk_3",
    "entry_rule", "exit_rule", "next_event",
    "status", "decision", "importance",
    "reference_link", "last_checked", "memo",
]

SWING_EDITOR_COLUMNS = [
    "status", "decision", "importance",
    "name", "ticker", "asset_class",
    "idea", "check_1", "check_2", "check_3",
    "risk_1", "risk_2", "risk_3",
    "entry_rule", "exit_rule", "next_event",
    "last_checked", "reference_link", "memo",
]

SWING_TEMPLATE_TEXT_FIELDS = [
    "idea", "check_1", "check_2", "check_3",
    "risk_1", "risk_2", "risk_3",
    "entry_rule", "exit_rule", "next_event",
]


def clean_float(value, default=0.0):
    try:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return float(default)
        return float(str(value).replace(",", ""))
    except Exception:
        return float(default)


def clean_int(value, default=None):
    try:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return default
        return int(float(value))
    except Exception:
        return default


def clean_bool(value):
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, str):
        return value.strip().lower() in ["true", "1", "yes", "y", "t"]
    return bool(value)


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


def run_supabase(query, action="Supabase operation"):
    try:
        return query.execute()
    except Exception as e:
        st.error(f"{action} failed: {e}")
        st.info("Check that Supabase tables were created and Streamlit Secrets are correct.")
        st.stop()


def dataframe_from_rows(rows, columns):
    if isinstance(rows, pd.DataFrame):
        df = rows.copy()
    else:
        df = pd.DataFrame(rows or [])
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


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
    return dataframe_from_rows(res.data, HOLDINGS_COLUMNS)


def save_holdings_db(df):
    rows = []
    for _, row in df.iterrows():
        ticker_value = str(row.get("ticker", "")).strip()
        if not ticker_value:
            continue

        name_value = str(row.get("name", "")).strip()
        asset_class = str(row.get("asset_class", "")).strip()
        is_fin_exempt = is_fin_score_exempt_asset(
            ticker_value,
            row.get("is_etf", False),
            asset_class,
            name_value,
        )
        if is_fin_exempt:
            asset_class = infer_asset_class_for_ticker(ticker_value, asset_class)
            mark_fin_score_not_applicable_db(ticker_value)

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
            "ticker": str(row.get("ticker", "")).strip(),
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
        name = str(row.get("name", "")).strip()
        ticker = str(row.get("ticker", "")).strip()
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
        ticker = str(item.get("ticker", "")).strip()
        if not ticker:
            continue

        name = str(item.get("name", "")).strip()
        asset_class = str(item.get("asset_class", "")).strip()
        is_fin_exempt = is_fin_score_exempt_asset(ticker, item.get("is_etf", False), asset_class, name)
        if is_fin_exempt:
            asset_class = infer_asset_class_for_ticker(ticker, asset_class)
            mark_fin_score_not_applicable_db(ticker)

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


def count_valid_rows(df, key_columns):
    if df is None or df.empty:
        return 0

    count = 0
    for _, row in df.iterrows():
        if any(str(row.get(col, "")).strip() for col in key_columns):
            count += 1
    return count


def dataframe_to_csv_bytes(df):
    if df is None:
        df = pd.DataFrame()
    return df.to_csv(index=False).encode("utf-8-sig")


def build_portfolio_backup_zip(settings, holdings_df, dividends_df, monthly_logs_df, watchlist_items, dashboard_df, fin_scores_df, swing_radar_df=None):
    settings_df = pd.DataFrame([settings or {}])
    watchlist_df = pd.DataFrame(watchlist_items or [])

    files = {
        "settings.csv": settings_df,
        "holdings.csv": holdings_df,
        "dividends.csv": dividends_df,
        "monthly_logs.csv": monthly_logs_df,
        "watchlist.csv": watchlist_df,
        "fin_scores.csv": fin_scores_df,
        "swing_radar.csv": swing_radar_df if swing_radar_df is not None else pd.DataFrame(columns=SWING_RADAR_COLUMNS),
        "dashboard.csv": dashboard_df,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, df in files.items():
            zf.writestr(filename, dataframe_to_csv_bytes(df))

    buffer.seek(0)
    return buffer.getvalue()


def classify_recovery_csv(df):
    cols = set(df.columns)

    if {"seed_money", "krw_cash", "usd_cash", "usdkrw", "reserve_target_weight"}.issubset(cols):
        return "settings"
    if {"ticker", "name", "qty", "avg_price", "target_weight", "asset_class", "is_etf", "bucket"}.issubset(cols):
        return "holdings"
    if {"date", "ticker", "amount", "currency"}.issubset(cols):
        return "dividends"
    if {"month", "total_invested", "evaluated_value", "dividend"}.issubset(cols):
        return "monthly_logs"
    if {"name", "ticker", "is_etf", "asset_class"}.issubset(cols):
        return "watchlist"
    if {"ticker", "auto_score", "manual_score", "final_score", "source", "notes_json"}.issubset(cols):
        return "fin_scores"
    if set(SWING_RADAR_COLUMNS).issubset(cols):
        return "swing_radar"
    if {"자산명", "티커", "보유량", "매입가", "원화환산", "bucket"}.issubset(cols):
        return "dashboard"

    return "unknown"


RECOVERY_KIND_INFO = {
    "settings": {
        "label": "기본 설정",
        "required": SETTINGS_COLUMNS,
        "key_columns": ["seed_money", "krw_cash", "usd_cash", "usdkrw"],
        "restore_mode": "마지막 행 기준으로 설정 저장",
    },
    "holdings": {
        "label": "보유자산",
        "required": HOLDINGS_COLUMNS,
        "key_columns": ["ticker"],
        "unique_column": "ticker",
        "restore_mode": "기존 보유자산을 대체",
    },
    "dividends": {
        "label": "배당 내역",
        "required": DIVIDENDS_COLUMNS,
        "key_columns": ["date", "ticker"],
        "restore_mode": "기존 배당 내역을 대체",
    },
    "monthly_logs": {
        "label": "월별 로그",
        "required": MONTHLY_LOG_COLUMNS,
        "key_columns": ["month"],
        "unique_column": "month",
        "restore_mode": "기존 월별 로그를 대체",
    },
    "watchlist": {
        "label": "관심목록",
        "required": WATCHLIST_COLUMNS,
        "key_columns": ["ticker"],
        "unique_column": "ticker",
        "restore_mode": "기존 관심목록을 대체",
    },
    "fin_scores": {
        "label": "재무점수",
        "required": FIN_SCORE_COLUMNS,
        "key_columns": ["ticker"],
        "restore_mode": "티커별 업서트",
    },
    "swing_radar": {
        "label": "스윙 레이더",
        "required": SWING_RADAR_COLUMNS,
        "key_columns": ["ticker"],
        "unique_column": "ticker",
        "restore_mode": "기존 스윙 레이더를 대체",
    },
    "dashboard": {
        "label": "계산 결과/현금 추출",
        "required": ["자산명", "티커", "보유량", "매입가", "원화환산", "bucket"],
        "key_columns": ["티커"],
        "restore_mode": "현금/환율 보조 추출",
    },
}


def add_recovery_issue(issues, severity, dataset, target, problem, suggestion):
    issues.append({
        "등급": severity,
        "데이터": dataset,
        "대상": str(target or "").strip(),
        "문제": problem,
        "확인/조치": suggestion,
    })


def normalize_recovery_key(value, column):
    text = str(value or "").strip()
    if column in ["ticker", "티커"]:
        return normalize_ticker(text)
    return text


def get_duplicate_recovery_values(df, column):
    if df is None or df.empty or column not in df.columns:
        return []

    values = df[column].fillna("").apply(lambda v: normalize_recovery_key(v, column))
    values = values[values.astype(str).str.strip().ne("")]
    counts = values.value_counts()
    return [(value, int(count)) for value, count in counts[counts > 1].items()]


def collect_recovery_frames(uploaded_files):
    frames = {}
    unknown_files = []
    read_errors = []
    parsed_files = []

    for uploaded_file in uploaded_files or []:
        filename = str(getattr(uploaded_file, "name", "uploaded_file"))
        raw = uploaded_file.getvalue()

        if not raw:
            read_errors.append(f"{filename}: 빈 파일입니다.")
            continue

        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for zip_name in zf.namelist():
                        if zip_name.endswith("/") or not zip_name.lower().endswith(".csv"):
                            continue

                        file_label = f"{filename}:{zip_name}"
                        try:
                            df = read_recovery_csv_bytes(zf.read(zip_name))
                        except Exception as exc:
                            read_errors.append(f"{file_label}: CSV 읽기 실패 ({exc})")
                            continue

                        kind = classify_recovery_csv(df)
                        if kind == "unknown":
                            unknown_files.append(file_label)
                            continue

                        add_recovery_frame(frames, kind, df)
                        parsed_files.append({
                            "파일": file_label,
                            "데이터": RECOVERY_KIND_INFO.get(kind, {}).get("label", kind),
                            "행수": len(df),
                        })
            except zipfile.BadZipFile:
                read_errors.append(f"{filename}: ZIP 파일로 읽을 수 없습니다.")
            continue

        try:
            df = read_recovery_csv_bytes(raw)
        except Exception as exc:
            read_errors.append(f"{filename}: CSV 읽기 실패 ({exc})")
            continue

        kind = classify_recovery_csv(df)
        if kind == "unknown":
            unknown_files.append(filename)
            continue

        add_recovery_frame(frames, kind, df)
        parsed_files.append({
            "파일": filename,
            "데이터": RECOVERY_KIND_INFO.get(kind, {}).get("label", kind),
            "행수": len(df),
        })

    return frames, unknown_files, read_errors, pd.DataFrame(parsed_files, columns=["파일", "데이터", "행수"])


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


def read_recovery_csv_bytes(raw_bytes):
    for encoding in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), encoding=encoding)
            df.columns = [str(col).strip().lstrip("\ufeff") for col in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(io.BytesIO(raw_bytes))
    df.columns = [str(col).strip().lstrip("\ufeff") for col in df.columns]
    return df


def read_recovery_csv(uploaded_file):
    uploaded_file.seek(0)
    return read_recovery_csv_bytes(uploaded_file.read())


def add_recovery_frame(frames, kind, df):
    if kind in frames:
        frames[kind] = pd.concat([frames[kind], df], ignore_index=True)
    else:
        frames[kind] = df


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


def upsert_fin_score_db(ticker, auto_score, manual_score, final_score, source, notes):
    run_supabase(
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
    )


def mark_fin_score_not_applicable_db(ticker, reason="ETF/ETN/레버리지 상품"):
    upsert_fin_score_db(
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

        px_df = load_price_df(ticker, "1mo")
        cur_price = float(px_df["Close"].iloc[-1]) if not px_df.empty else 0.0

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

    df = pd.DataFrame(rows)
    total_assets = df["원화환산"].sum() + krw_cash + (usd_cash * usdkrw)
    if total_assets > 0: df["현재비중"] = df["원화환산"] / total_assets * 100
    else: df["현재비중"] = 0.0
    df["운용대상"] = ~df["bucket"].apply(is_reserve_or_cash_bucket)
    df["비중차이"] = df.apply(
        lambda r: 0.0 if is_reserve_or_cash_bucket(r.get("bucket")) else float(r["목표비중"]) - float(r["현재비중"]),
        axis=1
    )
    df["리밸런싱목표비중"] = df.apply(
        lambda r: float(r["현재비중"]) if is_reserve_or_cash_bucket(r.get("bucket")) else float(r["목표비중"]),
        axis=1
    )

    return df

def calc_portfolio_summary(holdings_table, seed_money, krw_cash, usd_cash, usdkrw, dividends_df):
    stock_value = holdings_table["원화환산"].sum() if not holdings_table.empty else 0.0
    cash_value = krw_cash + (usd_cash * usdkrw)
    current_asset = stock_value + cash_value

    total_dividend = 0.0
    if dividends_df is not None and not dividends_df.empty:
        for _, r in dividends_df.iterrows():
            amt = float(r.get("amount", 0) or 0)
            ccy = str(r.get("currency", "KRW")).upper()
            total_dividend += amt if ccy == "KRW" else amt * usdkrw

    cum_profit = current_asset + total_dividend - seed_money
    cum_return = (cum_profit / seed_money * 100) if seed_money > 0 else 0.0

    return {
        "current_asset": current_asset, "stock_value": stock_value, "cash_value": cash_value,
        "total_dividend": total_dividend, "cum_profit": cum_profit, "cum_return": cum_return
    }
def make_cash_rows(krw_cash, usd_cash, usdkrw, total_asset):
    rows = []
    total_asset = float(total_asset or 0)

    if krw_cash > 0:
        cur_w = krw_cash / total_asset * 100 if total_asset > 0 else 0.0
        rows.append({
            "자산명": "원화예수금", "티커": "KRW_CASH", "보유량": krw_cash,
            "매입가": 1.0, "현재가": 1.0, "평가금액": krw_cash, "평가손익": 0.0,
            "수익률": 0.0, "원화환산": krw_cash, "현재비중": cur_w,
            "목표비중": 0.0, "비중차이": 0.0, "is_etf": True,
            "asset_class": "cash", "bucket": "cash", "운용대상": False,
            "리밸런싱목표비중": cur_w
        })

    if usd_cash > 0:
        usd_cash_krw = usd_cash * usdkrw
        cur_w = usd_cash_krw / total_asset * 100 if total_asset > 0 else 0.0
        rows.append({
            "자산명": "달러예수금", "티커": "USD_CASH", "보유량": usd_cash,
            "매입가": usdkrw, "현재가": usdkrw, "평가금액": usd_cash, "평가손익": 0.0,
            "수익률": 0.0, "원화환산": usd_cash_krw, "현재비중": cur_w,
            "목표비중": 0.0, "비중차이": 0.0, "is_etf": True,
            "asset_class": "cash", "bucket": "cash", "운용대상": False,
            "리밸런싱목표비중": cur_w
        })

    return rows

def append_cash_rows(df, krw_cash, usd_cash, usdkrw, total_asset):
    cash_rows = make_cash_rows(krw_cash, usd_cash, usdkrw, total_asset)
    if cash_rows:
        return pd.concat([df, pd.DataFrame(cash_rows)], ignore_index=True)
    return df

def calc_reserve_summary(df, reserve_target_weight):
    total = float(df["원화환산"].sum()) if not df.empty else 0.0
    bucket = df["bucket"].apply(normalize_bucket) if not df.empty else pd.Series(dtype=str)

    waiting_value = float(df.loc[bucket.isin(["reserve", "cash"]), "원화환산"].sum()) if total > 0 else 0.0
    reserve_value = float(df.loc[bucket == "reserve", "원화환산"].sum()) if total > 0 else 0.0
    cash_value = float(df.loc[bucket == "cash", "원화환산"].sum()) if total > 0 else 0.0
    invest_value = total - waiting_value

    waiting_pct = waiting_value / total * 100 if total > 0 else 0.0
    excess_pct = max(waiting_pct - float(reserve_target_weight), 0.0)

    return {
        "total": total,
        "invest_value": invest_value,
        "waiting_value": waiting_value,
        "reserve_value": reserve_value,
        "cash_value": cash_value,
        "waiting_pct": waiting_pct,
        "target_pct": float(reserve_target_weight),
        "excess_pct": excess_pct,
        "deployable_value": total * excess_pct / 100 if total > 0 else 0.0,
    }

def get_holding_row_by_ticker(holdings_table, ticker):
    if holdings_table.empty: return None
    t = normalize_ticker(ticker)
    matched = holdings_table[holdings_table["티커"].apply(normalize_ticker) == t]
    if not matched.empty: return matched.iloc[0]
    return None

def parse_month_end_date(value):
    raw = str(value or "").strip()
    if not raw:
        return pd.NaT

    if len(raw) == 7 and raw[4] == "-":
        dt = pd.to_datetime(f"{raw}-01", errors="coerce")
    else:
        dt = pd.to_datetime(raw, errors="coerce")

    if pd.isna(dt):
        return pd.NaT

    return dt + pd.offsets.MonthEnd(0)

def prepare_monthly_performance_df(monthly_df):
    required = ["month", "total_invested", "evaluated_value", "dividend"]
    if monthly_df is None or monthly_df.empty:
        return pd.DataFrame(columns=required)

    df = monthly_df.copy()
    for col in required:
        if col not in df.columns:
            df[col] = 0 if col != "month" else ""

    df["month_end"] = df["month"].apply(parse_month_end_date)
    df = df.dropna(subset=["month_end"]).sort_values("month_end")

    if df.empty:
        return df

    df["month_label"] = df["month_end"].dt.strftime("%y-%m")
    for col in ["total_invested", "evaluated_value", "dividend"]:
        df[col] = df[col].apply(clean_float)

    df["cum_dividend"] = df["dividend"].cumsum()
    df["cum_profit"] = df["evaluated_value"] + df["cum_dividend"] - df["total_invested"]
    df["cum_return_pct"] = np.where(
        df["total_invested"] > 0,
        df["cum_profit"] / df["total_invested"] * 100,
        0.0
    )

    first_return = float(df["cum_return_pct"].iloc[0]) if not df.empty else 0.0
    df["relative_return_pct"] = df["cum_return_pct"] - first_return
    return df

def build_benchmark_return_df(perf_df):
    if perf_df is None or perf_df.empty or "month_end" not in perf_df.columns:
        return pd.DataFrame(columns=["month_label", "구분", "수익률_pct"])

    rows = []
    for _, row in perf_df.iterrows():
        rows.append({
            "month_label": row["month_label"],
            "구분": "내 기간수익률",
            "수익률_pct": float(row.get("relative_return_pct", 0.0)),
        })

    benchmarks = {
        "S&P500": "379800.KS",
        "나스닥100": "379810.KS",
        "코스피": "069500.KS",
    }

    for label, ticker in benchmarks.items():
        try:
            px = load_price_df(ticker, "5y")
            if px.empty:
                continue

            close = px["Close"].copy()
            close.index = pd.to_datetime(close.index).tz_localize(None)

            prices = []
            for month_end in perf_df["month_end"]:
                target_dt = pd.Timestamp(month_end).tz_localize(None)
                eligible = close[close.index <= target_dt]
                prices.append(float(eligible.iloc[-1]) if not eligible.empty else np.nan)

            valid_prices = [p for p in prices if finite_num(p) and p > 0]
            if not valid_prices:
                continue

            base = valid_prices[0]
            for month_label, price in zip(perf_df["month_label"], prices):
                if finite_num(price) and price > 0:
                    ret = (float(price) / base - 1) * 100
                    rows.append({"month_label": month_label, "구분": label, "수익률_pct": ret})
        except Exception:
            continue

    return pd.DataFrame(rows)

MONEY_FLOW_UNIVERSE = [
    {"구분": "미국 섹터", "섹터": "나스닥", "ticker": "QQQ", "name": "Invesco QQQ Trust"},
    {"구분": "미국 섹터", "섹터": "S&P500", "ticker": "VOO", "name": "Vanguard S&P 500 ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 VanEck", "ticker": "SMH", "name": "VanEck Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 iShares", "ticker": "SOXX", "name": "iShares Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "기술", "ticker": "XLK", "name": "Technology Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "커뮤니케이션", "ticker": "XLC", "name": "Communication Services SPDR"},
    {"구분": "미국 섹터", "섹터": "금융", "ticker": "XLF", "name": "Financial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "헬스케어", "ticker": "XLV", "name": "Health Care Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "에너지", "ticker": "XLE", "name": "Energy Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "산업재", "ticker": "XLI", "name": "Industrial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "소재", "ticker": "XLB", "name": "Materials Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "경기소비재", "ticker": "XLY", "name": "Consumer Discretionary SPDR"},
    {"구분": "미국 섹터", "섹터": "필수소비재", "ticker": "XLP", "name": "Consumer Staples SPDR"},
    {"구분": "미국 섹터", "섹터": "유틸리티", "ticker": "XLU", "name": "Utilities Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "부동산", "ticker": "VNQ", "name": "Vanguard Real Estate ETF"},
    {"구분": "미국 섹터", "섹터": "바이오", "ticker": "IBB", "name": "iShares Biotechnology ETF"},
    {"구분": "미국 섹터", "섹터": "신재생", "ticker": "ICLN", "name": "iShares Global Clean Energy ETF"},
    {"구분": "미국 섹터", "섹터": "인프라", "ticker": "PAVE", "name": "Global X U.S. Infrastructure Development ETF"},
    {"구분": "미국 섹터", "섹터": "방산", "ticker": "SHLD", "name": "Global X Defense Tech ETF"},
    {"구분": "미국 섹터", "섹터": "항공방산", "ticker": "ITA", "name": "iShares U.S. Aerospace & Defense ETF"},
    {"구분": "미국 섹터", "섹터": "소프트웨어", "ticker": "IGV", "name": "iShares Expanded Tech-Software Sector ETF"},

    {"구분": "한국 섹터", "섹터": "코스피", "ticker": "069500.KS", "name": "KODEX 200"},
    {"구분": "한국 섹터", "섹터": "코스닥", "ticker": "229200.KS", "name": "KODEX 코스닥150"},
    {"구분": "한국 섹터", "섹터": "반도체", "ticker": "396500.KS", "name": "TIGER 반도체TOP10"},
    {"구분": "한국 섹터", "섹터": "IT/기술", "ticker": "139260.KS", "name": "TIGER 200 IT"},
    {"구분": "한국 섹터", "섹터": "2차전지", "ticker": "305540.KS", "name": "TIGER 2차전지테마"},
    {"구분": "한국 섹터", "섹터": "전력인프라", "ticker": "487240.KS", "name": "KODEX AI전력핵심설비"},
    {"구분": "한국 섹터", "섹터": "전력기기", "ticker": "0117V0.KS", "name": "TIGER 코리아AI전력기기TOP3플러스"},
    {"구분": "한국 섹터", "섹터": "원자력", "ticker": "434730.KS", "name": "HANARO 원자력iSelect"},
    {"구분": "한국 섹터", "섹터": "원자력TOP10", "ticker": "433500.KS", "name": "ACE 원자력TOP10"},
    {"구분": "한국 섹터", "섹터": "조선", "ticker": "494670.KS", "name": "TIGER 조선TOP10"},
    {"구분": "한국 섹터", "섹터": "방산", "ticker": "449450.KS", "name": "PLUS K방산"},
    {"구분": "한국 섹터", "섹터": "K-뷰티", "ticker": "479850.KS", "name": "HANARO K-뷰티"},
    {"구분": "한국 섹터", "섹터": "에너지", "ticker": "139250.KS", "name": "TIGER 200 에너지화학"},
    {"구분": "한국 섹터", "섹터": "금융", "ticker": "139270.KS", "name": "TIGER 200 금융"},
    {"구분": "한국 섹터", "섹터": "바이오", "ticker": "244580.KS", "name": "KODEX 바이오"},
    {"구분": "한국 섹터", "섹터": "부동산", "ticker": "329200.KS", "name": "TIGER 리츠부동산인프라"},
    {"구분": "한국 섹터", "섹터": "건설/유틸", "ticker": "139220.KS", "name": "TIGER 200 건설"},

    {"구분": "글로벌", "섹터": "미국 나스닥", "ticker": "QQQ", "name": "Invesco QQQ Trust"},
    {"구분": "글로벌", "섹터": "미국 S&P500", "ticker": "VOO", "name": "Vanguard S&P 500 ETF"},
    {"구분": "글로벌", "섹터": "일본", "ticker": "EWJ", "name": "iShares MSCI Japan ETF"},
    {"구분": "글로벌", "섹터": "캐나다", "ticker": "EWC", "name": "iShares MSCI Canada ETF"},
    {"구분": "글로벌", "섹터": "한국", "ticker": "EWY", "name": "iShares MSCI South Korea ETF"},
    {"구분": "글로벌", "섹터": "대만", "ticker": "EWT", "name": "iShares MSCI Taiwan ETF"},
    {"구분": "글로벌", "섹터": "홍콩", "ticker": "EWH", "name": "iShares MSCI Hong Kong ETF"},
    {"구분": "글로벌", "섹터": "중국", "ticker": "MCHI", "name": "iShares MSCI China ETF"},
    {"구분": "글로벌", "섹터": "인도", "ticker": "FLIN", "name": "Franklin FTSE India ETF"},
    {"구분": "글로벌", "섹터": "글로벌AI전력인프라", "ticker": "491010.KS", "name": "TIGER 글로벌AI전력인프라액티브"},
    {"구분": "글로벌", "섹터": "미국AI전력인프라", "ticker": "487230.KS", "name": "KODEX 미국AI전력핵심인프라"},
    {"구분": "글로벌", "섹터": "우라늄/원전", "ticker": "URA", "name": "Global X Uranium ETF"},
    {"구분": "글로벌", "섹터": "브라질", "ticker": "EWZ", "name": "iShares MSCI Brazil ETF"},
    {"구분": "글로벌", "섹터": "멕시코", "ticker": "EWW", "name": "iShares MSCI Mexico ETF"},
    {"구분": "글로벌", "섹터": "사우디", "ticker": "KSA", "name": "iShares MSCI Saudi Arabia ETF"},
    {"구분": "글로벌", "섹터": "베트남", "ticker": "VNM", "name": "VanEck Vietnam ETF"},

    {"구분": "매크로", "섹터": "금", "ticker": "IAU", "name": "iShares Gold Trust"},
    {"구분": "매크로", "섹터": "미국 장기채", "ticker": "TLT", "name": "iShares 20+ Year Treasury Bond ETF"},
]

def normalize_money_flow_ticker(ticker):
    t = str(ticker).strip().upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        code, suffix = t.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    return t

@st.cache_data(ttl=900, show_spinner=False)
def download_money_flow_prices(tickers):
    tickers = sorted({normalize_money_flow_ticker(t) for t in tickers if str(t).strip()})
    if not tickers:
        return pd.DataFrame()
    data = yf.download(
        tickers,
        period="1y",
        interval="1d",
        progress=False,
        group_by="ticker",
        threads=True,
        auto_adjust=False,
    )
    return data

def get_money_flow_ohlc(data, ticker):
    ticker = normalize_money_flow_ticker(ticker)
    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        level0 = list(data.columns.get_level_values(0))
        level1 = list(data.columns.get_level_values(1))

        if ticker in level0:
            out = data[ticker].copy()
        elif ticker in level1:
            out = data.xs(ticker, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        out = data.copy()

    needed = [c for c in ["Close", "High", "Low"] if c in out.columns]
    if len(needed) < 3:
        return pd.DataFrame()

    out = out[["Close", "High", "Low"]].ffill().dropna()
    return out

def get_return_by_days(close, days):
    if close is None or len(close) < 2:
        return np.nan
    idx = -days if len(close) > days else 0
    old = float(close.iloc[idx])
    new = float(close.iloc[-1])
    if old <= 0:
        return np.nan
    return (new / old) - 1

def classify_money_flow_state(ret_3m, ret_6m, accel):
    if finite_num(ret_3m) and finite_num(accel) and ret_3m >= 0.05 and accel >= 0.03:
        return "신규 유입"
    if finite_num(ret_3m) and finite_num(ret_6m) and ret_3m >= 0.05 and ret_6m >= 0.05 and (not finite_num(accel) or accel >= -0.03):
        return "주도 유지"
    if finite_num(ret_6m) and finite_num(accel) and ret_6m >= 0.05 and accel <= -0.05:
        return "둔화 경고"
    if finite_num(ret_3m) and finite_num(ret_6m) and ret_3m < 0 and ret_6m < 0:
        return "소외 지속"
    return "관찰"

def calculate_money_flow_df():
    universe = [dict(item, ticker=normalize_money_flow_ticker(item["ticker"])) for item in MONEY_FLOW_UNIVERSE]
    tickers = [item["ticker"] for item in universe]
    data = download_money_flow_prices(tickers)

    rows = []
    for item in universe:
        px = get_money_flow_ohlc(data, item["ticker"])
        if px.empty or len(px) < 20:
            continue

        close = px["Close"]
        cur = float(close.iloc[-1])
        high_52w = float(px["High"].max())
        low_52w = float(px["Low"].min())
        period_ret = get_return_by_days(close, len(close) - 1)
        ret_1m = get_return_by_days(close, 21)
        ret_3m = get_return_by_days(close, 63)
        ret_6m = get_return_by_days(close, 126)
        accel = ret_3m - ret_6m if finite_num(ret_3m) and finite_num(ret_6m) else np.nan
        price_level = (cur - low_52w) / (high_52w - low_52w) if high_52w > low_52w else np.nan
        flow_score = (
            (ret_3m if finite_num(ret_3m) else 0) * 45 +
            (ret_6m if finite_num(ret_6m) else 0) * 35 +
            (accel if finite_num(accel) else 0) * 20
        )

        rows.append({
            "구분": item["구분"],
            "섹터": item["섹터"],
            "Ticker": item["ticker"],
            "ETF 이름": item["name"],
            "현재가": cur,
            "가격수준": price_level,
            "기간수익률": period_ret,
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "6개월수익률": ret_6m,
            "가속도": accel,
            "돈흐름점수": flow_score,
            "상태": classify_money_flow_state(ret_3m, ret_6m, accel),
            "52주 최고가": high_52w,
            "52주 최저가": low_52w,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return df.sort_values("돈흐름점수", ascending=False)

def fmt_flow_pct(v):
    if not finite_num(v):
        return "-"
    return f"{float(v) * 100:.1f}%"

def render_money_flow_tab():
    st.subheader("돈흐름 레이더")
    st.caption("미국 섹터, 한국 섹터, 글로벌 국가 ETF의 3개월/6개월 흐름과 가속도를 비교해 돈이 어디로 향하는지 봅니다.")

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
    top_accel = flow_df.sort_values("가속도", ascending=False).head(1)

    s1, s2, s3, s4 = st.columns(4)
    if not top_us.empty:
        r = top_us.iloc[0]
        s1.metric("미국 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    if not top_kr.empty:
        r = top_kr.iloc[0]
        s2.metric("한국 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    if not top_global.empty:
        r = top_global.iloc[0]
        s3.metric("글로벌 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    if not top_accel.empty:
        r = top_accel.iloc[0]
        s4.metric("가속도 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["가속도"]))

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
            customdata=tree_df[["3개월수익률", "6개월수익률", "가속도", "상태"]],
            hovertemplate=
                "<b>%{label}</b><br>" +
                "3개월: %{customdata[0]:.1%}<br>" +
                "6개월: %{customdata[1]:.1%}<br>" +
                "가속도: %{customdata[2]:.1%}<br>" +
                "상태: %{customdata[3]}<extra></extra>"
        ))
        fig_tree.update_layout(template="plotly_dark", height=470, title="돈흐름 히트맵", margin=dict(t=45, l=4, r=4, b=4))
        st.plotly_chart(fig_tree, use_container_width=True)
        st.caption("블록이 클수록 최근 3개월 움직임이 크고, 초록색일수록 3개월/6개월 흐름과 가속도가 좋다는 뜻입니다.")

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


# -------------------------------------------------
# 4. 데이터 로드 (외부 의존성 제거)
# -------------------------------------------------
@st.cache_data(ttl=300)
def load_price_df(ticker, period="1y"):
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.ffill().dropna()
    return df

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
    "396500.KS": "한국 반도체",
    "487240.KS": "전력인프라",
    "494670.KS": "조선",
    "449450.KS": "방산",
    "305540.KS": "2차전지",
    "434730.KS": "HANARO 원자력iSelect",
    "479850.KS": "HANARO K-뷰티",
}

SECTOR_BENCHMARK_MAP = {
    "005930": ("396500.KS", "반도체"),
    "000660": ("396500.KS", "반도체"),
    "200710": ("396500.KS", "반도체"),
    "267260": ("487240.KS", "전력인프라"),
    "278470": ("479850.KS", "K-뷰티"),
    "034020": ("434730.KS", "원자력"),
    "329180": ("494670.KS", "조선"),
    "012450": ("449450.KS", "방산"),
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


def get_sector_benchmark_info(ticker, asset_class):
    key = normalize_ticker(ticker)
    if key in SECTOR_BENCHMARK_MAP:
        return SECTOR_BENCHMARK_MAP[key]
    symbol = clean_symbol(ticker)
    if symbol in SECTOR_BENCHMARK_MAP:
        return SECTOR_BENCHMARK_MAP[symbol]
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
        elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
        elif rsi_now <= 30: dec, col = "🔥낙폭과대: 신규 진입", "#16a34a"
        elif is_early_entry: dec, col = "🟢선진입 가능 구간", "#16a34a"
        elif adj_tech_score >= 4.5 and rs_label == "🚀강함": dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
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
        elif current_dd <= -0.2: dec, col = "🚨위기(-20%↓): 현금 확보", "#dc2626"
        
        elif final_macro_risk >= 4.5:
            dec, col = "🛑하드차단: 퍼펙트스톰(대피)", "#dc2626"
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
            elif adj_tech_score >= 4.5 and rs_label == "🚀강함": dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
            elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5: dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
            elif ret_3m < 0 and trend_label in ["🌊역배열(하락)", "⏳혼조세"]: dec, col = "⚠️하락추세: 진입보류", "#dc2626"
            elif trend_label == "🌊역배열(하락)": dec, col = "🚫진입보류: 역배열 대기", "#dc2626"
            else: dec, col = "🔍대기: 신규 타점 탐색", "#64748b"

    return {
        "cur_p": cur_p, "rsi": rsi_now, "mfi": mfi_now, "pct_b": pct_b_now, "rs_label": rs_label, "adj": adj_tech_score, "dec": dec, "col": col,
        "grade": grade, "t_score": tech_total + (0 if is_etf else fin_score), "tech_total": tech_total, "fin_score": fin_score,
        "dd": current_dd, "ret_3m": ret_3m, "ret_6m": ret_6m, "target_w": targ_w, "current_w": curr_w, "buy_amt": buy_amount,
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
    "에이디테크놀러지": ("200710.KQ", False, "kr_stock"), "SPYM": ("SPYM", True, "us_etf_sp"),
}

FREE_SEARCH_OPTION = "🆓 자유 종목 탐색 (티커 입력)"


def build_precision_select_options():
    options = [FREE_SEARCH_OPTION]
    option_map = {FREE_SEARCH_OPTION: {"type": "free"}}
    seen_labels = set(options)

    for item in st.session_state.get("watchlist", []):
        ticker = str(item.get("ticker", "")).strip()
        if not ticker:
            continue

        name = str(item.get("name", ticker)).strip() or ticker
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


def get_all_summary(fin_score_map_items, mode, watchlist_items):
    swing_status_map, swing_decision_map = get_dashboard_swing_status_maps()
    rows = []
    for item in watchlist_items:
        name = item["name"]
        tkr = item["ticker"]
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
        sector_bench, _ = get_sector_benchmark_info(tkr, a_class)
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
        {"항목": "MDD", "정의": "52주 고점 대비 낙폭", "코드 기준": "-20%, -30%, -40%, -50% 단계별 위기/패닉", "해석": "낙폭이 깊을수록 리스크 원인 점검 필요"},
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
        {"타점": "신규진입: 대장주 포착", "조건": "ADJ 4.5 이상 + RS 강함", "의미": "신규 후보"},
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

2. **자산 관리 입력**
   `⚙️ 자산 관리` 탭에서 시드머니, 원화/달러 예수금, 환율, 보유 종목을 입력합니다.

3. **보유 종목 저장**
   보유 종목 표에는 `ticker`, `name`, `qty`, `avg_price`, `target_weight`, `asset_class`, `is_etf`, `bucket`을 입력합니다.

4. **전광판 확인**
   `📋 전체 요약 전광판`에서 한국 ETF, 한국 개별주, 미국 ETF, 미국 개별주를 나눠 봅니다.

5. **정밀 관측소에서 한 종목 확인**
   관심 종목을 하나 골라 현재가, 추세, RS, RSI, MFI, MACD, 볼린저 위치, 최종 판정을 확인합니다.
        """)

        st.info("처음에는 전광판을 먼저 보고, 매수/추매 고민이 생긴 종목만 정밀 관측소에서 확인하는 흐름이 가장 편합니다.")

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

**📋 전체 요약 전광판**  
등록된 종목을 한 번에 보는 첫 화면입니다. 한국/미국, ETF/개별주를 나눠서 보고 `기술적 타점`, `ADJ점수`, `RS`, `시장벤치`, `섹터RS`를 확인합니다.

**🔍 종목 정밀 관측소**  
한 종목을 깊게 보는 곳입니다. 차트, 추세, MACD, SQZ, SMC 구조, 뉴스, AI 분석용 프롬프트를 확인합니다.

**⚙️ 자산 관리**  
시드머니, 예수금, 보유 종목, 배당, 월별 로그를 관리합니다. 입력값이 틀리면 비중/추매금액 판정도 틀어집니다.

**💸 돈흐름 레이더**  
섹터와 ETF 흐름을 보는 곳입니다. 돈흐름 1위는 “이 섹터에서 후보를 먼저 찾아보라”는 뜻이지 즉시 매수 신호가 아닙니다.

**🎯 스윙 레이더**  
스윙 후보의 투자 아이디어, 체크포인트, 리스크, 진입/청산 기준을 메모하는 곳입니다.

**📘 판정 매뉴얼**  
하드차단, S급 눌림목, ETF 적립 가능 같은 문구가 왜 나오는지 확인하는 곳입니다.
        """)

        with st.expander("추천 사용 순서", expanded=True):
            st.markdown("""
1. 돈흐름 레이더에서 강한 섹터 확인
2. 전광판에서 해당 섹터 관련 종목 확인
3. 정밀 관측소에서 타점 확인
4. 스윙 레이더에서 체크리스트 확인
5. 목표비중과 현재비중을 보고 최종 판단
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


# -------------------------------------------------
# 8. 메인 UI 렌더링
# -------------------------------------------------
macro_res, final_macro_risk, macro_penalty, move_val = get_macro_analysis()
st.caption(f"모드: {app_mode} | 매크로 리스크: {final_macro_risk:.1f} | 매크로 패널티: -{macro_penalty}")

if macro_res:
    m_cols = st.columns(len(macro_res))
    for i, (n, info) in enumerate(macro_res.items()):
        s_tag = "<br><span style='color:#ef4444; font-weight:bold;'>🚨폭풍</span>" if info["storm"] else ""
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
usdkrw = float(settings.get("usdkrw", 1400.0))
reserve_target_weight = float(settings.get("reserve_target_weight", 10.0))      

holdings_table = build_holdings_table(holdings_df, krw_cash, usd_cash, usdkrw)
portfolio_summary = calc_portfolio_summary(holdings_table, seed_money, krw_cash, usd_cash, usdkrw, dividends_df)
total_eval = portfolio_summary["current_asset"]

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📋 전체 요약 전광판",
    "🔍 종목 정밀 관측소",
    "⚙️ 자산 관리",
    "💸 돈흐름 레이더",
    "🎯 스윙 레이더",
    "🧪 데이터 점검",
    "📘 판정 매뉴얼",
    "📖 사용 가이드",
])

with tab1:
    st.subheader("CCTV 통합 통제실")
    st.write(
        f"현재자산: {portfolio_summary['current_asset']:,.0f}원 | "
        f"누적손익: {portfolio_summary['cum_profit']:,.0f}원 | "
        f"누적수익률: {portfolio_summary['cum_return']:.2f}% | "
        f"누적배당금: {portfolio_summary['total_dividend']:,.0f}원"
    )
    st.caption("전광판 등록 종목만 표시됩니다.")

    remove_options = ["선택"] + [f"{item['name']}|{item['ticker']}" for item in st.session_state.watchlist]
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
        st.markdown("#### 전광판 보기")
        group_order = ["전체", "한국 ETF", "한국 개별주", "미국 ETF", "미국 개별주"]
        group_tabs = st.tabs([
            f"{label} ({len(summary_df) if label == '전체' else int((summary_df['전광판그룹'] == label).sum())})"
            for label in group_order
        ])

        for group_tab, group_label in zip(group_tabs, group_order):
            with group_tab:
                render_dashboard_group_summary(summary_df, group_label)

with tab2:
    options, precision_option_map = build_precision_select_options()
    sel = st.selectbox("종목 선택", options)
    selected_option = precision_option_map.get(sel, {"type": "preset"})
    is_free = (selected_option.get("type") == "free")

    if is_free:
        c1, c2 = st.columns([2, 1])
        with c1: user_tkr_raw = st.text_input("티커/종목코드 (예: GOOGL, 005930)", "GOOGL").upper().strip()
        with c2: mkt_opt = st.selectbox("시장 (한국주식 시)", ["KOSPI (.KS)", "KOSDAQ (.KQ)"])

        tkr = f"{user_tkr_raw}{'.KS' if 'KOSPI' in mkt_opt else '.KQ'}" if (user_tkr_raw.isdigit() and len(user_tkr_raw) == 6) else user_tkr_raw

        known_sp500_etfs = {"SPY", "VOO", "IVV", "SPLG", "SPYM", "379800.KS"}
        known_nasdaq_etfs = {"QQQ", "QQQM", "QLD", "TQQQ", "379810.KS"}
        ticker_norm = normalize_ticker(tkr)
        is_etf = is_fin_score_exempt_asset(tkr)
        
        if is_etf:
            a_class = infer_asset_class_for_ticker(tkr)
        else:
            a_class = "kr_stock" if tkr.endswith((".KS", ".KQ")) else "us_stock"

        name = f"탐색: {tkr}"
        my_p, has_p = 0.0, False
    elif selected_option.get("type") == "watchlist":
        watch_item = selected_option.get("item", {})
        name = str(watch_item.get("name", "")).strip() or str(watch_item.get("ticker", "")).strip()
        tkr = str(watch_item.get("ticker", "")).strip()
        is_etf = is_fin_score_exempt_asset(tkr, watch_item.get("is_etf", False), watch_item.get("asset_class", ""), name)
        a_class = infer_asset_class_for_ticker(tkr, watch_item.get("asset_class", "")) if is_etf else str(watch_item.get("asset_class", "")).strip()
        my_p, has_p = get_my_price(name, tkr), has_position(name, tkr)
    else:
        name = sel
        tkr, is_etf, a_class = TICKER_MAP[sel]
        my_p, has_p = get_my_price(name, tkr), has_position(name, tkr)

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
        notes = fin_meta.get("notes", {})
        metrics = fin_meta.get("metrics", {})
        weighted = notes.get("weighted_scores", {}) or metrics.get("weighted_scores", {}) if isinstance(notes, dict) else {}
        if not isinstance(notes, dict): notes = {"messages": notes if isinstance(notes, list) else [str(notes)]}

        st.write("source:", fin_meta.get("source"))
        st.write("mode:", fin_meta.get("mode"))
        st.write("auto_score:", fin_meta.get("auto_score"))
        st.write("manual_score:", fin_meta.get("manual_score"))
        st.write("final_score:", fin_meta.get("final_score"))

        if not is_etf:
            if st.button("자동 재무점수 돌리기", key=f"run_auto_fin_{fin_key}"):
                with st.spinner("DART/FMP 재무 자동 계산 중..."):
                    clear_financial_api_cache()
                    new_score, _ = get_final_fin_score(tkr, is_etf, a_class)
                    st.session_state.fin_score_map[fin_key] = int(new_score)
                st.success("자동 재무점수 계산 완료")
                st.rerun()

        if weighted:
            st.write("weighted score:", weighted.get("weighted_net_score"))
            st.write("S_sum:", weighted.get("s_sum"))
            st.write("A_sum:", weighted.get("a_sum"))
            st.write("B_sum:", weighted.get("b_sum"))
            st.write("danger_count:", weighted.get("danger_count"))
            st.write("범용판단:", weighted.get("generic_score"))
            st.write("수주판단:", weighted.get("order_score"))
            st.write("중간형판단:", weighted.get("middle_score"))
            st.write("selected_mode:", weighted.get("selected_mode"))

        annual_judgements = notes.get("annual_judgements", {})
        quarter_judgements = notes.get("quarter_judgements", {})

        st.markdown("#### annual 판정 문구")
        if annual_judgements: st.dataframe(pd.DataFrame([{"key": k, "judgement": v} for k, v in annual_judgements.items()]), use_container_width=True, hide_index=True)
        else: st.write("annual 판정 없음")

        st.markdown("#### quarter 판정 문구")
        if quarter_judgements: st.dataframe(pd.DataFrame([{"key": k, "judgement": v} for k, v in quarter_judgements.items()]), use_container_width=True, hide_index=True)
        else: st.write("quarter 판정 없음")

        st.markdown("#### 핵심 metrics")
        annual_records = metrics.get("annual_records", [])
        quarter_records = metrics.get("quarter_records", [])

        if annual_records:
            st.write("annual records")
            st.dataframe(pd.DataFrame(annual_records), use_container_width=True, hide_index=True)

        if quarter_records:
            st.write("quarter records")
            st.dataframe(pd.DataFrame(quarter_records), use_container_width=True, hide_index=True)

        derived = metrics.get("derived", {})
        if derived:
            st.write("derived metrics")
            st.json(derived)

        messages = notes.get("messages", [])
        if messages:
            st.markdown("#### notes")
            for msg in messages: st.write("-", msg)

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

    current_item = {"name": name, "ticker": tkr, "is_etf": is_etf, "asset_class": a_class, "fin_score": int(fin_score)}

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

            st.markdown(
                f"<div class='info-panel'>현재가: <span class='highlight'>{format_currency(c['cur_p'], tkr)}</span><br>"
                f"3개월 수익률: <span style='color:{ret3_color}; font-weight:bold;'>{c['ret_3m']*100:.1f}%</span><br>"
                f"6개월 수익률: <span style='color:{ret6_color}; font-weight:bold;'>{c['ret_6m']*100:.1f}%</span><br>"
                f"고점대비 MDD: <span style='color:{dd_c}; font-weight:bold;'>{c['dd']*100:.1f}%</span></div>",
                unsafe_allow_html=True
            )

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
            fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], line=dict(color="#fbbf24", width=2), name="MA20"))
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
            st.markdown(f"<div class='info-panel' style='border-left: 5px solid #10b981;'><b>📐 전술 지표</b><br>• 추세: <b>{c['trend']}</b> | MACD: <b>{c['macd']}</b><br>• RS: <b>{c['rs_label']}</b> | RSI: <b>{c['rsi']:.1f}</b> | MFI: <b>{c['mfi']:.1f}</b><br>• 볼린저 %B: <b>{c['pct_b']:.2f}</b> | SQZ: <b>{c['sqz']}</b><hr style='margin:10px 0; border-color:#334155;'><span class='smc-tag'>MA5</span> {format_currency(c['ma5'], tkr)}<br><span class='smc-tag'>MA20</span> {format_currency(c['ma20'], tkr)}<br><span class='smc-tag'>MA50</span> {format_currency(c['ma50'], tkr)}<br><span class='smc-tag'>MA120</span> {format_currency(c['ma120'], tkr)}<hr style='margin:10px 0; border-color:#334155;'>💡 <b>보조 해석:</b> {c['smc_insight']}</div>", unsafe_allow_html=True)

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

with tab3:
    st.subheader("앱 내부 자산 관리")

    st.markdown("### 0) 백업/복구 안전장치")

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

    st.markdown("### 1) 기본 설정")
    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
    with col_s1: new_seed = st.number_input("시드머니", min_value=0.0, value=float(seed_money), step=100000.0)
    with col_s2: new_krw = st.number_input("원화 예수금", min_value=0.0, value=float(krw_cash), step=100000.0)
    with col_s3: new_usd = st.number_input("달러 예수금", min_value=0.0, value=float(usd_cash), step=100.0)
    with col_s4: new_fx = st.number_input("환율(USDKRW)", min_value=0.0, value=float(usdkrw), step=1.0)
    with col_s5: new_reserve_target = st.number_input("대기자금 목표비중(%)", min_value=0.0, max_value=100.0, value=float(reserve_target_weight), step=0.5)


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

    st.markdown("### 5) 현재 계산 결과")

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

        signal_rows = []
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

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("주식 평가금", f"{portfolio_summary['stock_value']:,.0f}원")
        k2.metric("현금 포함 자산", f"{portfolio_summary['current_asset']:,.0f}원")
        k3.metric("누적손익", f"{portfolio_summary['cum_profit']:,.0f}원")
        k4.metric("누적수익률", f"{portfolio_summary['cum_return']:.2f}%")

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("투자자산", f"{reserve_summary['invest_value']:,.0f}원")
        r2.metric("대기자금", f"{reserve_summary['waiting_value']:,.0f}원", f"{reserve_summary['waiting_pct']:.2f}%")
        r3.metric("대기자금 목표", f"{reserve_summary['target_pct']:.2f}%")
        r4.metric("초과 대기자금", f"{reserve_summary['deployable_value']:,.0f}원", f"{reserve_summary['excess_pct']:.2f}%p")
        
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

        st.markdown("#### 보유자산 + 기술적 타점 요약")
        show_cols = [
            "자산명", "티커", "보유량", "매입가", "현재가", "평가금액", "평가손익",
            "평가손익_원화", "수익률_pct", "원화환산", "목표비중", "현재비중", "비중차이",
            "기술적타점", "ADJ점수", "후보등급", "추세", "RS", "RSI", "MFI", "MACD", "SQZ" ,"bucket", "운용대상", "리밸런싱목표비중"
        ]
        st.dataframe(dash_df[[c for c in show_cols if c in dash_df.columns]], use_container_width=True, hide_index=True)

    else:
        st.info("등록된 보유 종목이 없습니다.")

with tab4:
    render_money_flow_tab()

with tab5:
    render_swing_radar_tab()

with tab6:
    render_data_quality_tab(settings, holdings_df, holdings_table, dividends_df, monthly_logs_df, st.session_state.watchlist)

with tab7:
    render_manual_tab() 

with tab8:
    render_user_guide_tab()
