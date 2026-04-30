import io
import zipfile
import requests
import json
import base64
from pathlib import Path
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
import sqlite3

# -------------------------------------------------
# 1. 기본 설정 및 CSS
# -------------------------------------------------
st.set_page_config(page_title="최종 관제실", layout="wide")

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
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("🛠️ 관제탑 세팅")
    app_mode = st.radio("사용 모드", ["개인모드", "범용모드"], index=0, help="개인모드는 앱 내부 자산 연동, 범용모드는 직접 입력 방식입니다.")
    news_debug = st.checkbox("뉴스 디버그 보기", value=False)

st.title(f"🚀 REALTIME DIGITAL DASHBOARD v13.1 ({app_mode})")

# -------------------------------------------------
# 2. 유틸리티 함수
# -------------------------------------------------
def format_currency(val, ticker):
    if pd.isna(val): return "-"
    if str(ticker).endswith(".KS") or str(ticker).endswith(".KQ"): return f"₩{int(val):,}"
    return f"${val:,.2f}"

def normalize_text(x): return str(x).strip().lower()
def normalize_ticker(t): return str(t).strip().lower().replace(".ks", "").replace(".kq", "")
def parse_num(v):
    if pd.isna(v): return 0.0
    s = str(v).replace(",", "").replace("%", "").replace("₩", "").replace("$", "").strip()
    return pd.to_numeric(s, errors="coerce") if s != "" else 0.0

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
        0: "0점 (ETF/해당없음)",
        1: "1점 (🚨F급/처분)",
        2: "2점 (⚠️불안정/주의)",
        3: "3점 (✅회복형/중간형)",
        4: "4점 (💎완성형 우량)"
    }

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
# 2-1. SQLite 저장소
# -------------------------------------------------
DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)
DB_FILE = DB_DIR / "portfolio.db"

def get_conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        seed_money REAL DEFAULT 0,
        krw_cash REAL DEFAULT 0,
        usd_cash REAL DEFAULT 0,
        usdkrw REAL DEFAULT 1400
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS holdings (
        ticker TEXT PRIMARY KEY,
        name TEXT,
        qty REAL DEFAULT 0,
        avg_price REAL DEFAULT 0,
        target_weight REAL DEFAULT 0,
        asset_class TEXT DEFAULT '',
        is_etf INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dividends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        ticker TEXT,
        amount REAL DEFAULT 0,
        currency TEXT DEFAULT 'KRW'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS monthly_logs (
        month TEXT PRIMARY KEY,
        total_invested REAL DEFAULT 0,
        evaluated_value REAL DEFAULT 0,
        dividend REAL DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fin_scores (
        ticker TEXT PRIMARY KEY,
        auto_score INTEGER,
        manual_score INTEGER,
        final_score INTEGER,
        source TEXT,
        notes_json TEXT
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS watchlist (
        ticker TEXT PRIMARY KEY,
        name TEXT,
        is_etf INTEGER DEFAULT 0,
        asset_class TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        fin_score INTEGER
    )
    """)
   
    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO settings (id, seed_money, krw_cash, usd_cash, usdkrw)
            VALUES (1, 0, 0, 0, 1400)
        """)

    conn.commit()
    conn.close()

def load_settings_db():
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM settings WHERE id = 1", conn)
    finally:
        conn.close()
    if df.empty:
        return {"seed_money": 0.0, "krw_cash": 0.0, "usd_cash": 0.0, "usdkrw": 1400.0}
    row = df.iloc[0]
    return {
        "seed_money": float(row["seed_money"]),
        "krw_cash": float(row["krw_cash"]),
        "usd_cash": float(row["usd_cash"]),
        "usdkrw": float(row["usdkrw"])
    }

def save_settings_db(seed_money, krw_cash, usd_cash, usdkrw):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE settings
            SET seed_money = ?, krw_cash = ?, usd_cash = ?, usdkrw = ?
            WHERE id = 1
        """, (float(seed_money), float(krw_cash), float(usd_cash), float(usdkrw)))
        conn.commit()
    finally:
        conn.close()

def load_holdings_db():
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM holdings", conn)
    finally:
        conn.close()
    return df

def save_holdings_db(df):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM holdings")
        for _, row in df.iterrows():
            ticker_value = str(row.get("ticker", "")).strip()
            if not ticker_value:
                continue
            raw_is_etf = row.get("is_etf", False)
            if isinstance(raw_is_etf, str):
                is_etf = 1 if raw_is_etf.strip().lower() in ["true", "1", "yes", "y"] else 0
            else:
                is_etf = 1 if bool(raw_is_etf) else 0

            cur.execute("""
                INSERT OR REPLACE INTO holdings
                (ticker, name, qty, avg_price, target_weight, asset_class, is_etf)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker_value,
                str(row.get("name", "")).strip(),
                float(row.get("qty", 0) or 0),
                float(row.get("avg_price", 0) or 0),
                float(row.get("target_weight", 0) or 0),
                str(row.get("asset_class", "")).strip(),
                is_etf
            ))
        conn.commit()
    finally:
        conn.close()


def load_dividends_db():
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM dividends ORDER BY date DESC, id DESC", conn)
    finally:
        conn.close()
    return df

def save_dividends_db(df):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dividends")
        for _, row in df.iterrows():
            cur.execute("""
                INSERT INTO dividends (date, ticker, amount, currency)
                VALUES (?, ?, ?, ?)
            """, (
                str(row.get("date", "")).strip(),
                str(row.get("ticker", "")).strip(),
                float(row.get("amount", 0) or 0),
                str(row.get("currency", "KRW")).strip().upper()
            ))
        conn.commit()
    finally:
        conn.close()

def load_monthly_logs_db():
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM monthly_logs ORDER BY month", conn)
    finally:
        conn.close()
    return df

def save_monthly_logs_db(df):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM monthly_logs")
        for _, row in df.iterrows():
            cur.execute("""
                INSERT OR REPLACE INTO monthly_logs (month, total_invested, evaluated_value, dividend)
                VALUES (?, ?, ?, ?)
            """, (
                str(row.get("month", "")).strip(),
                float(row.get("total_invested", 0) or 0),
                float(row.get("evaluated_value", 0) or 0),
                float(row.get("dividend", 0) or 0)
            ))
        conn.commit()
    finally:
        conn.close()

def load_fin_scores_db():
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM fin_scores", conn)
    finally:
        conn.close()
    return df

def load_watchlist_db():
    conn = get_conn()
    try:
        df = pd.read_sql_query(
            "SELECT name, ticker, is_etf, asset_class, fin_score FROM watchlist ORDER BY sort_order, name",
            conn
        )
    finally:
        conn.close()

    if df.empty:
        return []

    items = []
    for _, row in df.iterrows():
        items.append({
            "name": str(row.get("name", "")).strip(),
            "ticker": str(row.get("ticker", "")).strip(),
            "is_etf": bool(int(row.get("is_etf", 0) or 0)),
            "asset_class": str(row.get("asset_class", "")).strip(),
            "fin_score": int(row["fin_score"]) if pd.notna(row.get("fin_score")) else None,
        })
    return [x for x in items if x["ticker"]]


def save_watchlist_db(watchlist):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM watchlist")

        for idx, item in enumerate(watchlist):
            ticker = str(item.get("ticker", "")).strip()
            if not ticker:
                continue

            cur.execute("""
                INSERT OR REPLACE INTO watchlist
                (ticker, name, is_etf, asset_class, sort_order, fin_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                str(item.get("name", "")).strip(),
                1 if bool(item.get("is_etf", False)) else 0,
                str(item.get("asset_class", "")).strip(),
                idx,
                int(item["fin_score"]) if item.get("fin_score") is not None else None,
            ))

        conn.commit()
    finally:
        conn.close()


def load_watchlist_persistent():
    db_items = load_watchlist_db()
    if db_items:
        return db_items

    query_items = load_watchlist_from_query()
    save_watchlist_db(query_items)
    return query_items

def persist_watchlist():
    save_watchlist_db(st.session_state.watchlist)
        
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
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO fin_scores
            (ticker, auto_score, manual_score, final_score, source, notes_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            normalize_ticker(ticker),
            int(auto_score) if auto_score is not None else None,
            int(manual_score) if manual_score is not None else None,
            int(final_score) if final_score is not None else None,
            str(source),
            json.dumps(to_jsonable(notes), ensure_ascii=False)
        ))
        conn.commit()
    finally:
        conn.close()

def delete_manual_fin_score_db(ticker):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE fin_scores
            SET manual_score = NULL, final_score = auto_score
            WHERE ticker = ?
        """, (normalize_ticker(ticker),))
        conn.commit()
    finally:
        conn.close()

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
    "ASML", "LRCX", "KLAC", "AMAT", "INTC", "QCOM", "ARM", "SMCI"
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
            "notes": {"mode": "ETF", "messages": ["ETF는 재무점수 0점 고정"], "annual_judgements": {}, "quarter_judgements": {}, "weighted_scores": {}},
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
            "수익률", "원화환산", "현재비중", "목표비중", "비중차이", "is_etf", "asset_class"
        ])

    rows = []
    for _, row in holdings_df.iterrows():
        name = row.get("name", "")
        ticker = row.get("ticker", "")
        qty = float(row.get("qty", 0) or 0)
        avg_price = float(row.get("avg_price", 0) or 0)
        target_weight = float(row.get("target_weight", 0) or 0)
        asset_class = row.get("asset_class", "us_stock")

        raw_is_etf = row.get("is_etf", False)
        if isinstance(raw_is_etf, str): is_etf = raw_is_etf.strip().lower() in ["true", "1", "yes", "y"]
        else: is_etf = bool(raw_is_etf)

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
            "원화환산": krw_eval, "목표비중": target_weight, "is_etf": is_etf, "asset_class": asset_class
        })

    df = pd.DataFrame(rows)
    total_assets = df["원화환산"].sum() + krw_cash + (usd_cash * usdkrw)
    if total_assets > 0: df["현재비중"] = df["원화환산"] / total_assets * 100
    else: df["현재비중"] = 0.0
    df["비중차이"] = df["목표비중"] - df["현재비중"]
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

def get_holding_row_by_ticker(holdings_table, ticker):
    if holdings_table.empty: return None
    t = normalize_ticker(ticker)
    matched = holdings_table[holdings_table["티커"].apply(normalize_ticker) == t]
    if not matched.empty: return matched.iloc[0]
    return None

# -------------------------------------------------
# 3. 뉴스 듀얼 모터
# -------------------------------------------------
@st.cache_data(ttl=600)
def get_ticker_news(ticker, name, debug=False):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    search_query = name.replace("탐색: ", "").replace(".KS", "").replace(".KQ", "").strip()
    encoded = urllib.parse.quote(search_query)
    logs = [f"검색어: {search_query}"]

    try:
        url = f"https://newssearch.naver.com/search.naver?where=rss&query={encoded}"
        if debug: logs.append(f"네이버 URL: {url}")
        req = urllib.request.Request(url, headers=headers)
        root = ET.fromstring(urllib.request.urlopen(req, timeout=4).read())
        items = root.findall("./channel/item")
        if items:
            res = [{"title": i.find("title").text.replace("<b>","").replace("</b>","").replace("&quot;","\"").replace("&amp;","&") if i.find("title") is not None else "제목 없음", 
                    "link": i.find("link").text if i.find("link") is not None else "#", 
                    "publisher": "네이버 뉴스"} for i in items[:3]]
            logs.append(f"네이버 뉴스 성공 ({len(items)}건)")
            return res, logs
    except Exception as e: logs.append(f"네이버 뉴스 실패: {e}")

    try:
        url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        if debug: logs.append(f"구글 URL: {url}")
        req = urllib.request.Request(url, headers=headers)
        root = ET.fromstring(urllib.request.urlopen(req, timeout=4).read())
        items = root.findall("./channel/item")
        if items:
            res = [{"title": i.find("title").text if i.find("title") is not None else "제목 없음", 
                    "link": i.find("link").text if i.find("link") is not None else "#", 
                    "publisher": i.find("source").text if i.find("source") is not None else "구글 뉴스"} for i in items[:3]]
            logs.append(f"구글 뉴스 성공 ({len(items)}건)")
            return res, logs
    except Exception as e: logs.append(f"구글 뉴스 실패: {e}")

    return [], logs

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
    for name, tkr in tickers.items():
        data = yf.download(tkr, period="2mo", interval="1d", progress=False)
        if data.empty: continue
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        cur = float(data["Close"].iloc[-1])
        prev_m = float(data["Close"].iloc[-22]) if len(data) >= 22 else float(data["Close"].iloc[0])
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

def clean_symbol(ticker):
    return str(ticker).strip().upper().replace(".KS", "").replace(".KQ", "")

def is_kr_listed(ticker):
    return str(ticker).strip().upper().endswith((".KS", ".KQ"))

def get_rs_benchmark(ticker, asset_class):
    symbol = clean_symbol(ticker)
    ac = str(asset_class).strip().lower()

    if ac in ["kr_stock", "kr_etf"]: return KR_MARKET_BENCHMARK
    if is_kr_listed(ticker) and ac == "us_etf_nasdaq": return KR_US_NASDAQ_BENCHMARK
    if is_kr_listed(ticker) and ac == "us_etf_sp": return KR_US_SP_BENCHMARK
    if ac == "us_etf_nasdaq": return US_TECH_BENCHMARK
    if ac == "us_etf_sp": return US_BROAD_BENCHMARK
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

    trend_label = "🚀정배열(상승)" if (last["MA20"] > last["MA50"] > last["MA120"]) else ("⏳혼조세" if last["MA20"] > last["MA50"] else "🌊역배열(하락)")
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
        if mfi_now >= 85: dec, col = "🚫극단과열: 추격금지", "#dc2626"
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
    "s&p500": ("379800.KS", True, "us_etf_sp"), "다우존스": ("458730.KS", True, "us_etf_sp"), "kodex 200": ("069500.KS", True, "kr_etf"),
    "MSFT": ("MSFT", False, "us_stock"), "네비우스": ("NBIS", False, "us_stock"), "시에나": ("CIEN", False, "us_stock"), "아리스타 네트웍스": ("ANET", False, "us_stock"),
    "샌디스크": ("SNDK", False, "us_stock"), "TSM": ("TSM", False, "us_stock"), "브로드컴": ("AVGO", False, "us_stock"), "MRVL": ("MRVL", False, "us_stock"),
    "버티브홀딩스": ("VRT", False, "us_stock"), "마이크론": ("MU", False, "us_stock"), "삼성전자": ("005930.KS", False, "kr_stock"),
    "두산에너빌리티": ("034020.KS", False, "kr_stock"), "하이닉스": ("000660.KS", False, "kr_stock"), "한화에어로스페이스": ("012450.KS", False, "kr_stock"),
    "HD현대중공업": ("329180.KS", False, "kr_stock"), "에이피알": ("278470.KS", False, "kr_stock"), "HD현대일렉트릭": ("267260.KS", False, "kr_stock"),
    "에이디테크놀러지": ("200710.KQ", False, "kr_stock"), "SPYM": ("SPYM", True, "us_etf_sp"),
}

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

def get_all_summary(fin_score_map_items, mode, watchlist_items):
    rows = []
    for item in watchlist_items:
        name = item["name"]
        tkr = item["ticker"]
        is_etf = item["is_etf"]
        a_class = item["asset_class"]

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

        rows.append({
            "종목명": name, "티커": tkr, "현재가": format_currency(c["cur_p"], tkr), "MDD": f"{c['dd']*100:.1f}%",
            "재무점수": "ETF 0점" if is_etf else f"{f_score}/4", "📌후보등급": c["grade"], "RS": c["rs_label"],
            "RSI": round(c["rsi"], 1), "MFI": round(c["mfi"], 1), "볼린저 %B": round(c["pct_b"], 2),
            "🔥기술적 타점": c["dec"], "Adj점수": round(c["adj"], 1)
        })

    return pd.DataFrame(rows)

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
    st.caption("현재 코드의 판정 기준을 표로 정리한 탭입니다. 기준을 바꾸고 싶으면 MANUAL_SECTIONS 데이터만 수정하면 됩니다.")

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

    with st.expander("운영 메모"):
        st.markdown("""
- 이 매뉴얼은 `calc_scores_and_decision()`의 판정 로직을 사람이 읽기 쉽게 요약한 것입니다.
- 실제 매수/관망 문구를 바꾸면 `MANUAL_SECTIONS["기술적 타점"]`도 같이 수정하면 됩니다.
- 점수 기준을 바꾸면 `MANUAL_SECTIONS["점수 계산"]`, `MANUAL_SECTIONS["후보 등급"]`을 같이 수정하면 됩니다.
- 앱 화면에서는 이 데이터를 보여주기만 하므로, 나중에 관리가 쉽습니다.
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

holdings_table = build_holdings_table(holdings_df, krw_cash, usd_cash, usdkrw)
portfolio_summary = calc_portfolio_summary(holdings_table, seed_money, krw_cash, usd_cash, usdkrw, dividends_df)
total_eval = portfolio_summary["current_asset"]

tab1, tab2, tab3, tab4 = st.tabs(["📋 전체 요약 전광판", "🔍 종목 정밀 관측소", "⚙️ 자산 관리", "📘 판정 매뉴얼"])

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
    if summary_df.empty: st.warning("전광판에 표시할 종목이 없습니다.")
    else: st.dataframe(summary_df, use_container_width=True, height=720, hide_index=True)

with tab2:
    options = ["🆓 자유 종목 탐색 (티커 입력)"] + list(TICKER_MAP.keys())
    sel = st.selectbox("종목 선택", options)
    is_free = (sel == "🆓 자유 종목 탐색 (티커 입력)")

    if is_free:
        c1, c2 = st.columns([2, 1])
        with c1: user_tkr_raw = st.text_input("티커/종목코드 (예: GOOGL, 005930)", "GOOGL").upper().strip()
        with c2: mkt_opt = st.selectbox("시장 (한국주식 시)", ["KOSPI (.KS)", "KOSDAQ (.KQ)"])

        tkr = f"{user_tkr_raw}{'.KS' if 'KOSPI' in mkt_opt else '.KQ'}" if (user_tkr_raw.isdigit() and len(user_tkr_raw) == 6) else user_tkr_raw

        known_sp500_etfs = {"SPY", "VOO", "IVV", "SPLG", "SPYM", "379800.KS"}
        known_nasdaq_etfs = {"QQQ", "QQQM", "QLD", "TQQQ", "379810.KS"}
        ticker_norm = normalize_ticker(tkr)
        is_etf = (ticker_norm in {normalize_ticker(x) for x in known_sp500_etfs | known_nasdaq_etfs | {"SOXL", "SOXX", "VTI", "DIA", "IWM", "SCHD", "JEPI", "JEPQ", "SMH", "XLE", "XLF", "XLK", "IYW", "458730.KS", "069500.KS"}} or tkr.upper().endswith("ETF"))
        
        if is_etf:
            if tkr.endswith((".KS", ".KQ")): a_class = "kr_etf"
            elif ticker_norm in {normalize_ticker(x) for x in known_sp500_etfs}: a_class = "us_etf_sp"
            else: a_class = "us_etf_nasdaq"
        else:
            a_class = "kr_stock" if tkr.endswith((".KS", ".KQ")) else "us_stock"

        name = f"탐색: {tkr}"
        my_p, has_p = 0.0, False
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
        st.info("ETF는 재무점수 0점 고정입니다. 수동 재무점수도 적용하지 않습니다.")
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
            st.markdown(f"<h2>📊 {name}</h2>", unsafe_allow_html=True)
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

        st.markdown("### 📰 최신 현장 뉴스")
        news_items, news_logs = get_ticker_news(tkr, name, news_debug)
        if news_items:
            for item in news_items:
                safe_title = html.escape(str(item.get("title", "제목 없음")))
                safe_pub = html.escape(str(item.get("publisher", "")))
                safe_link = str(item.get("link", "#")).strip()
                if not safe_link.startswith(("http://", "https://")): safe_link = "#"
                st.markdown(f"<div class='news-box'><a href='{safe_link}' target='_blank'>🔗 {safe_title}</a> <span style='color:#94a3b8; font-size:0.8em;'>출처: {safe_pub}</span></div>", unsafe_allow_html=True)
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

    st.markdown("### 1) 기본 설정")
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1: new_seed = st.number_input("시드머니", min_value=0.0, value=float(seed_money), step=100000.0)
    with col_s2: new_krw = st.number_input("원화 예수금", min_value=0.0, value=float(krw_cash), step=100000.0)
    with col_s3: new_usd = st.number_input("달러 예수금", min_value=0.0, value=float(usd_cash), step=100.0)
    with col_s4: new_fx = st.number_input("환율(USDKRW)", min_value=0.0, value=float(usdkrw), step=1.0)

    if st.button("기본 설정 저장"):
        save_settings_db(new_seed, new_krw, new_usd, new_fx)
        st.success("기본 설정 저장 완료")
        st.rerun()

    st.markdown("### 2) 보유 종목 관리")
    holdings_editor_df = load_holdings_db()
    if holdings_editor_df.empty: holdings_editor_df = pd.DataFrame(columns=["name", "ticker", "qty", "avg_price", "target_weight", "asset_class", "is_etf"])
    edited_holdings = st.data_editor(holdings_editor_df, num_rows="dynamic", use_container_width=True, key="holdings_editor")

    if st.button("보유 종목 저장"):
        save_holdings_db(edited_holdings.fillna(""))
        st.success("보유 종목 저장 완료")
        st.rerun()

    st.markdown("### 3) 배당 내역 관리")
    dividends_editor_df = load_dividends_db()
    if dividends_editor_df.empty: dividends_editor_df = pd.DataFrame(columns=["date", "ticker", "amount", "currency"])
    edited_dividends = st.data_editor(dividends_editor_df, num_rows="dynamic", use_container_width=True, key="dividends_editor")

    if st.button("배당 내역 저장"):
        save_dividends_db(edited_dividends.fillna(""))
        st.success("배당 내역 저장 완료")
        st.rerun()

    st.markdown("### 4) 월별 로그 관리")
    monthly_editor_df = load_monthly_logs_db()
    if monthly_editor_df.empty: monthly_editor_df = pd.DataFrame(columns=["month", "total_invested", "evaluated_value", "dividend"])
    edited_monthly = st.data_editor(monthly_editor_df, num_rows="dynamic", use_container_width=True, key="monthly_editor")

    if st.button("월별 로그 저장"):
        save_monthly_logs_db(edited_monthly.fillna(""))
        st.success("월별 로그 저장 완료")
        st.rerun()

    st.markdown("### 5) 현재 계산 결과")

    if not holdings_table.empty:
        dash_df = holdings_table.copy()

        dash_df["평가손익_원화"] = dash_df.apply(
            lambda r: r["평가손익"] if str(r["티커"]).upper().endswith((".KS", ".KQ"))
            else r["평가손익"] * usdkrw,
            axis=1
        )
        dash_df["수익률_pct"] = dash_df["수익률"] * 100

        signal_rows = []
        for _, r in dash_df.iterrows():
            tkr = r["티커"]
            name = r["자산명"]
            is_etf = bool(r.get("is_etf", False))
            asset_class = r.get("asset_class", "")

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
            fig_weight.add_trace(go.Bar(y=dash_df["자산명"], x=dash_df["목표비중"], orientation="h", name="목표비중"))
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

        st.markdown("#### 보유자산 + 기술적 타점 요약")
        show_cols = [
            "자산명", "티커", "보유량", "매입가", "현재가", "평가금액", "평가손익",
            "평가손익_원화", "수익률_pct", "원화환산", "목표비중", "현재비중", "비중차이",
            "기술적타점", "ADJ점수", "후보등급", "추세", "RS", "RSI", "MFI", "MACD", "SQZ"
        ]
        st.dataframe(dash_df[[c for c in show_cols if c in dash_df.columns]], use_container_width=True, hide_index=True)

with tab4:
    render_manual_tab() 

    else:
        st.info("등록된 보유 종목이 없습니다.")
