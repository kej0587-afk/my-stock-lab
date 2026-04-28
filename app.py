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
import OpenDartReader
import sqlite3

# -------------------------------------------------
# 1. 기본 설정 및 CSS
# -------------------------------------------------
st.set_page_config(page_title="대장님의 최종 관제실 v13.1 (그랜드 오픈 마감판)", layout="wide")

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
• 이 판단을 무효화할 수 있는 변수 3가지 이상 제시
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
    df = pd.read_sql_query("SELECT * FROM settings WHERE id = 1", conn)
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
    cur = conn.cursor()
    cur.execute("""
        UPDATE settings
        SET seed_money = ?, krw_cash = ?, usd_cash = ?, usdkrw = ?
        WHERE id = 1
    """, (float(seed_money), float(krw_cash), float(usd_cash), float(usdkrw)))
    conn.commit()
    conn.close()

def load_holdings_db():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM holdings", conn)
    conn.close()
    return df

def save_holdings_db(df):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM holdings")
    for _, row in df.iterrows():
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
            str(row.get("ticker", "")).strip(),
            str(row.get("name", "")).strip(),
            float(row.get("qty", 0) or 0),
            float(row.get("avg_price", 0) or 0),
            float(row.get("target_weight", 0) or 0),
            str(row.get("asset_class", "")).strip(),
            is_etf
        ))
    conn.commit()
    conn.close()

def load_dividends_db():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM dividends ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

def save_dividends_db(df):
    conn = get_conn()
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
    conn.close()

def load_monthly_logs_db():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM monthly_logs ORDER BY month", conn)
    conn.close()
    return df

def save_monthly_logs_db(df):
    conn = get_conn()
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
    conn.close()

def load_fin_scores_db():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM fin_scores", conn)
    conn.close()
    return df

def upsert_fin_score_db(ticker, auto_score, manual_score, final_score, source, notes):
    conn = get_conn()
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
        json.dumps(notes, ensure_ascii=False)
    ))
    conn.commit()
    conn.close()

def delete_manual_fin_score_db(ticker):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE fin_scores
        SET manual_score = NULL, final_score = auto_score
        WHERE ticker = ?
    """, (normalize_ticker(ticker),))
    conn.commit()
    conn.close()

init_db()

# -------------------------------------------------
# 2-2. 자동 재무제표 로드 + 점수화
# -------------------------------------------------
@st.cache_resource
def get_dart_client():
    api_key = st.secrets.get("dart_api_key", "")
    if not api_key:
        return None
    return OpenDartReader(api_key)

def safe_float(x, default=np.nan):
    try:
        if pd.isna(x):
            return default
        s = str(x).replace(",", "").replace("%", "").replace("₩", "").replace("$", "").strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default

def normalize_stock_code(ticker: str) -> str:
    t = str(ticker).strip().upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return t.split(".")[0]
    return t

def pick_account_amount(df, keywords):
    if df is None or df.empty:
        return np.nan

    for col in ["account_nm", "accountNm", "sj_nm", "sjNm"]:
        if col in df.columns:
            names = df[col].astype(str)
            mask = pd.Series(False, index=df.index)
            for kw in keywords:
                mask = mask | names.str.contains(kw, case=False, na=False)
            matched = df[mask]
            if not matched.empty:
                for amount_col in ["thstrm_amount", "thstrmAmount", "frmtrm_amount", "frmtrmAmount"]:
                    if amount_col in matched.columns:
                        vals = matched[amount_col].apply(safe_float).dropna()
                        if not vals.empty:
                            return float(vals.iloc[0])
    return np.nan

@st.cache_data(ttl=3600)
def fetch_kr_financials_auto(ticker: str):
    dart = get_dart_client()
    if dart is None:
        return {"ok": False, "reason": "DART API 키 없음"}

    stock_code = normalize_stock_code(ticker)

    try:
        fs = dart.finstate_all(stock_code, bsns_year='2025', reprt_code='11011')
        if fs is None or len(fs) == 0:
            fs = dart.finstate_all(stock_code, bsns_year='2024', reprt_code='11011')

        if fs is None or len(fs) == 0:
            return {"ok": False, "reason": "DART 재무제표 없음"}

        revenue = pick_account_amount(fs, ["매출액", "수익(매출액)", "영업수익"])
        op_income = pick_account_amount(fs, ["영업이익"])
        net_income = pick_account_amount(fs, ["당기순이익", "연결당기순이익", "당기순이익(손실)"])
        equity = pick_account_amount(fs, ["자본총계"])
        liabilities = pick_account_amount(fs, ["부채총계"])
        assets = pick_account_amount(fs, ["자산총계"])
        ocf = pick_account_amount(fs, ["영업활동현금흐름"])

        roe = np.nan
        debt_ratio = np.nan
        op_margin = np.nan
        net_margin = np.nan

        if not np.isnan(net_income) and not np.isnan(equity) and equity != 0:
            roe = net_income / equity * 100
        if not np.isnan(liabilities) and not np.isnan(equity) and equity != 0:
            debt_ratio = liabilities / equity * 100
        if not np.isnan(op_income) and not np.isnan(revenue) and revenue != 0:
            op_margin = op_income / revenue * 100
        if not np.isnan(net_income) and not np.isnan(revenue) and revenue != 0:
            net_margin = net_income / revenue * 100

        return {
            "ok": True,
            "source": "dart",
            "revenue": revenue,
            "op_income": op_income,
            "net_income": net_income,
            "equity": equity,
            "liabilities": liabilities,
            "assets": assets,
            "ocf": ocf,
            "roe": roe,
            "debt_ratio": debt_ratio,
            "op_margin": op_margin,
            "net_margin": net_margin,
        }
    except Exception as e:
        return {"ok": False, "reason": f"DART 오류: {e}"}

@st.cache_data(ttl=3600)
def fetch_us_financials_auto(ticker: str):
    try:
        tk = yf.Ticker(ticker)

        info = getattr(tk, "info", {}) or {}
        income_stmt = getattr(tk, "income_stmt", pd.DataFrame())
        balance_sheet = getattr(tk, "balance_sheet", pd.DataFrame())
        cashflow = getattr(tk, "cashflow", pd.DataFrame())

        if (income_stmt is None or income_stmt.empty) and not info:
            return {"ok": False, "reason": "Yahoo 재무제표 없음"}

        def get_row(df, row_names):
            if df is None or df.empty:
                return np.nan
            for rn in row_names:
                if rn in df.index:
                    vals = pd.to_numeric(df.loc[rn], errors="coerce").dropna()
                    if not vals.empty:
                        return float(vals.iloc[0])
            return np.nan

        revenue = get_row(income_stmt, ["Total Revenue", "Operating Revenue"])
        op_income = get_row(income_stmt, ["Operating Income"])
        net_income = get_row(income_stmt, ["Net Income"])
        equity = get_row(balance_sheet, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"])
        liabilities = get_row(balance_sheet, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
        assets = get_row(balance_sheet, ["Total Assets"])
        ocf = get_row(cashflow, ["Operating Cash Flow"])

        roe = safe_float(info.get("returnOnEquity"), np.nan)
        if not np.isnan(roe):
            roe = roe * 100
        elif not np.isnan(net_income) and not np.isnan(equity) and equity != 0:
            roe = net_income / equity * 100

        debt_ratio = np.nan
        if not np.isnan(liabilities) and not np.isnan(equity) and equity != 0:
            debt_ratio = liabilities / equity * 100

        op_margin = safe_float(info.get("operatingMargins"), np.nan)
        if not np.isnan(op_margin):
            op_margin = op_margin * 100
        elif not np.isnan(op_income) and not np.isnan(revenue) and revenue != 0:
            op_margin = op_income / revenue * 100

        net_margin = safe_float(info.get("profitMargins"), np.nan)
        if not np.isnan(net_margin):
            net_margin = net_margin * 100
        elif not np.isnan(net_income) and not np.isnan(revenue) and revenue != 0:
            net_margin = net_income / revenue * 100

        if np.isnan(revenue) and np.isnan(op_income) and np.isnan(net_income) and np.isnan(roe):
            return {"ok": False, "reason": "Yahoo 재무 핵심값 없음"}

        return {
            "ok": True,
            "source": "yfinance",
            "revenue": revenue,
            "op_income": op_income,
            "net_income": net_income,
            "equity": equity,
            "liabilities": liabilities,
            "assets": assets,
            "ocf": ocf,
            "roe": roe,
            "debt_ratio": debt_ratio,
            "op_margin": op_margin,
            "net_margin": net_margin,
        }
    except Exception as e:
        return {"ok": False, "reason": f"Yahoo 오류: {e}"}

def score_auto_financials(fin):
    if not fin.get("ok", False):
        reason = fin.get("reason", "원인 미상")
        return 3, [
            "자동 재무 조회 실패 → 기본 3점",
            f"사유: {reason}"
        ]

    roe = fin.get("roe", np.nan)
    debt_ratio = fin.get("debt_ratio", np.nan)
    op_margin = fin.get("op_margin", np.nan)
    net_margin = fin.get("net_margin", np.nan)
    ocf = fin.get("ocf", np.nan)
    revenue = fin.get("revenue", np.nan)
    net_income = fin.get("net_income", np.nan)

    notes = []
    score = 0
    danger = 0

    if not np.isnan(roe) and roe < 0:
        danger += 1
        notes.append("🚨 ROE 음수")
    if not np.isnan(net_income) and net_income < 0:
        danger += 1
        notes.append("🚨 순이익 음수")
    if not np.isnan(ocf) and ocf < 0:
        danger += 1
        notes.append("🚨 영업현금흐름 음수")

    if not np.isnan(roe) and roe >= 12:
        score += 3
        notes.append("💎 ROE 우수")
    elif not np.isnan(roe) and roe >= 6:
        score += 1
        notes.append("✅ ROE 양호")
    elif not np.isnan(roe) and roe < 3:
        score -= 2
        notes.append("❌ ROE 낮음")

    if not np.isnan(op_margin) and op_margin >= 10:
        score += 3
        notes.append("💎 영업이익률 우수")
    elif not np.isnan(op_margin) and op_margin >= 5:
        score += 1
        notes.append("✅ 영업이익률 양호")
    elif not np.isnan(op_margin) and op_margin < 3:
        score -= 2
        notes.append("❌ 영업이익률 낮음")

    if not np.isnan(net_margin) and net_margin >= 8:
        score += 2
        notes.append("✅ 순이익률 양호")
    elif not np.isnan(net_margin) and net_margin < 2:
        score -= 1
        notes.append("❌ 순이익률 낮음")

    if not np.isnan(debt_ratio) and debt_ratio <= 100:
        score += 2
        notes.append("✅ 부채비율 안정")
    elif not np.isnan(debt_ratio) and debt_ratio <= 180:
        score += 1
        notes.append("➖ 부채비율 보통")
    elif not np.isnan(debt_ratio) and debt_ratio > 250:
        score -= 2
        notes.append("❌ 부채비율 높음")

    if not np.isnan(ocf) and ocf > 0:
        score += 2
        notes.append("✅ 영업현금흐름 양수")

    if not np.isnan(revenue) and revenue > 0:
        score += 1
        notes.append("✅ 매출 존재")

    if danger >= 2:
        return 1, notes

    if score >= 8:
        return 4, notes
    elif score >= 4:
        return 3, notes
    elif score >= 1:
        return 2, notes
    else:
        return 1, notes
        
ORDER_BASED_TICKERS = {
    "012450",      # 한화에어로스페이스
    "012450.ks",
    "329180",      # HD현대중공업
    "329180.ks"
}

def score_order_based_financials(fin):
    if not fin.get("ok", False):
        reason = fin.get("reason", "원인 미상")
        return 3, [f"자동 재무 조회 실패 → 기본 3점", f"사유: {reason}"]

    roe = fin.get("roe", np.nan)
    debt_ratio = fin.get("debt_ratio", np.nan)
    op_margin = fin.get("op_margin", np.nan)
    net_margin = fin.get("net_margin", np.nan)
    ocf = fin.get("ocf", np.nan)
    revenue = fin.get("revenue", np.nan)
    net_income = fin.get("net_income", np.nan)

    notes = []
    score = 0
    danger = 0

    if not np.isnan(net_income) and net_income < 0:
        danger += 1
        notes.append("🚨 순이익 음수")
    if not np.isnan(ocf) and ocf < 0:
        notes.append("⚠️ 영업현금흐름 음수(수주형 특성 반영)")

    if not np.isnan(roe) and roe >= 8:
        score += 2
        notes.append("✅ ROE 양호")
    elif not np.isnan(roe) and roe >= 3:
        score += 1
        notes.append("➖ ROE 보통")
    elif not np.isnan(roe) and roe < 1:
        score -= 1
        notes.append("❌ ROE 낮음")

    if not np.isnan(op_margin) and op_margin >= 8:
        score += 2
        notes.append("✅ 영업이익률 양호")
    elif not np.isnan(op_margin) and op_margin >= 3:
        score += 1
        notes.append("➖ 영업이익률 보통")
    elif not np.isnan(op_margin) and op_margin < 1:
        score -= 1
        notes.append("❌ 영업이익률 낮음")

    if not np.isnan(net_margin) and net_margin >= 3:
        score += 1
        notes.append("✅ 순이익률 양호")
    elif not np.isnan(net_margin) and net_margin < 0:
        score -= 1
        notes.append("❌ 순이익률 음수")

    if not np.isnan(debt_ratio) and debt_ratio <= 200:
        score += 2
        notes.append("✅ 부채비율 허용")
    elif not np.isnan(debt_ratio) and debt_ratio <= 300:
        score += 1
        notes.append("➖ 부채비율 보통")
    elif not np.isnan(debt_ratio) and debt_ratio > 400:
        score -= 2
        notes.append("❌ 부채비율 높음")

    if not np.isnan(revenue) and revenue > 0:
        score += 1
        notes.append("✅ 매출 존재")

    if danger >= 2:
        return 1, notes

    if score >= 6:
        return 4, notes
    elif score >= 3:
        return 3, notes
    elif score >= 0:
        return 2, notes
    else:
        return 1, notes

def get_auto_fin_score_for_ticker(ticker: str, is_etf: bool):
    if is_etf:
        return 0, {"ok": True, "source": "etf"}, ["ETF는 재무점수 미합산"]

    is_kr = str(ticker).endswith(".KS") or str(ticker).endswith(".KQ")
    fin = fetch_kr_financials_auto(ticker) if is_kr else fetch_us_financials_auto(ticker)

    t_norm = normalize_ticker(ticker)
    if t_norm in ORDER_BASED_TICKERS:
        score, notes = score_order_based_financials(fin)
    else:
        score, notes = score_auto_financials(fin)

    return score, fin, notes

def get_final_fin_score(ticker, is_etf, asset_class):
    fin_scores_df = load_fin_scores_db()
    key = normalize_ticker(ticker)

    if is_etf:
        upsert_fin_score_db(
            ticker=key,
            auto_score=0,
            manual_score=None,
            final_score=0,
            source="etf",
            notes=["ETF는 재무점수 미합산"]
        )
        return 0, {
            "auto_score": 0,
            "manual_score": None,
            "final_score": 0,
            "source": "etf",
            "notes": ["ETF는 재무점수 미합산"],
            "metrics": {}
        }

    matched = fin_scores_df[fin_scores_df["ticker"] == key]
    manual_score = None
    if not matched.empty:
        row = matched.iloc[0]
        if pd.notna(row["manual_score"]):
            manual_score = int(row["manual_score"])

    # 항상 최신 자동 재무 재계산
    auto_score, fin_auto, fin_notes = get_auto_fin_score_for_ticker(ticker, is_etf)

    final_score = manual_score if manual_score is not None else int(auto_score)

    upsert_fin_score_db(
        ticker=key,
        auto_score=int(auto_score),
        manual_score=manual_score,
        final_score=int(final_score),
        source=fin_auto.get("source", "unknown"),
        notes=fin_notes
    )

    return int(final_score), {
        "auto_score": int(auto_score),
        "manual_score": manual_score,
        "final_score": int(final_score),
        "source": fin_auto.get("source", "unknown"),
        "notes": fin_notes,
        "metrics": {
            "roe": fin_auto.get("roe"),
            "op_margin": fin_auto.get("op_margin"),
            "net_margin": fin_auto.get("net_margin"),
            "debt_ratio": fin_auto.get("debt_ratio"),
            "ocf": fin_auto.get("ocf"),
            "revenue": fin_auto.get("revenue"),
            "net_income": fin_auto.get("net_income"),
        }
    }
    
if st.button("재무점수 강제 재계산", key=f"refresh_fin_{fin_key}"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM fin_scores WHERE ticker = ?", (normalize_ticker(tkr),))
    conn.commit()
    conn.close()

    if fin_key in st.session_state.fin_score_map:
        del st.session_state.fin_score_map[fin_key]

    st.rerun()

def set_manual_fin_score(ticker, score):
    key = normalize_ticker(ticker)
    fin_scores_df = load_fin_scores_db()
    matched = fin_scores_df[fin_scores_df["ticker"] == key]

    if matched.empty:
        upsert_fin_score_db(
            ticker=key,
            auto_score=int(score),
            manual_score=int(score),
            final_score=int(score),
            source="manual",
            notes=[]
        )
    else:
        row = matched.iloc[0]
        notes = []
        try:
            notes = json.loads(row["notes_json"]) if pd.notna(row["notes_json"]) else []
        except Exception:
            notes = []

        upsert_fin_score_db(
            ticker=key,
            auto_score=int(row["auto_score"]) if pd.notna(row["auto_score"]) else int(score),
            manual_score=int(score),
            final_score=int(score),
            source=row["source"] if pd.notna(row["source"]) else "manual",
            notes=notes
        )

def reset_manual_fin_score(ticker):
    delete_manual_fin_score_db(ticker)

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
        if isinstance(raw_is_etf, str):
            is_etf = raw_is_etf.strip().lower() in ["true", "1", "yes", "y"]
        else:
            is_etf = bool(raw_is_etf)

        px_df = load_price_df(ticker, "1mo")
        cur_price = float(px_df["Close"].iloc[-1]) if not px_df.empty else 0.0

        eval_amt = qty * cur_price
        pnl = qty * (cur_price - avg_price)
        ret = ((cur_price / avg_price) - 1) if avg_price > 0 else 0.0

        is_kr = str(ticker).endswith(".KS") or str(ticker).endswith(".KQ")
        krw_eval = eval_amt if is_kr else eval_amt * usdkrw

        rows.append({
            "자산명": name,
            "티커": ticker,
            "보유량": qty,
            "매입가": avg_price,
            "현재가": cur_price,
            "평가금액": eval_amt,
            "평가손익": pnl,
            "수익률": ret,
            "원화환산": krw_eval,
            "목표비중": target_weight,
            "is_etf": is_etf,
            "asset_class": asset_class
        })

    df = pd.DataFrame(rows)
    total_assets = df["원화환산"].sum() + krw_cash + (usd_cash * usdkrw)

    if total_assets > 0:
        df["현재비중"] = df["원화환산"] / total_assets * 100
    else:
        df["현재비중"] = 0.0

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
        "current_asset": current_asset,
        "stock_value": stock_value,
        "cash_value": cash_value,
        "total_dividend": total_dividend,
        "cum_profit": cum_profit,
        "cum_return": cum_return
    }

def get_holding_row_by_ticker(holdings_table, ticker):
    if holdings_table.empty:
        return None
    t = normalize_ticker(ticker)
    matched = holdings_table[holdings_table["티커"].apply(normalize_ticker) == t]
    if not matched.empty:
        return matched.iloc[0]
    return None

# -------------------------------------------------
# 3. 뉴스 듀얼 모터
# -------------------------------------------------
@st.cache_data(ttl=600)
def get_ticker_news(ticker, name, debug=False):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
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
        df.ffill(inplace=True); df.dropna(inplace=True)
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

# --- 세션 초기화 (유일한 곳) ---
if "fin_score_map" not in st.session_state:
    st.session_state.fin_score_map = {}

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist_from_query()

sync_watchlist_to_query()

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

def get_rs_score(ticker, asset_class):
    bench = "069500.KS" if asset_class in ["kr_stock", "kr_etf"] else ("QQQM" if asset_class == "us_stock" else "379810.KS")
    if normalize_ticker(ticker) == normalize_ticker(bench): return 1, "➖보통"
    s_df, b_df = load_price_df(ticker, "3mo"), load_price_df(bench, "3mo")
    if len(s_df) < 15 or len(b_df) < 15: return 1, "➖보통"
    s_now, s_10d = float(s_df["Close"].iloc[-1]), float(s_df["Close"].iloc[-11])
    b_now, b_10d = float(b_df["Close"].iloc[-1]), float(b_df["Close"].iloc[-11])
    rs_now, rs_10d = s_now / b_now, s_10d / b_10d
    if rs_now > rs_10d * 1.03: return 2, "🚀강함"
    elif rs_now < rs_10d * 0.97: return 0, "🐢약함"
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
    if row is None:
        return 0.0
    return float(row.get("현재비중", 0.0) or 0.0)

def get_target_weight_from_sheet(name, ticker):
    row = get_holding_row_by_ticker(holdings_table, ticker)
    if row is None:
        return 0.0
    return float(row.get("목표비중", 0.0) or 0.0)

def get_my_price(name, ticker):
    row = get_holding_row_by_ticker(holdings_table, ticker)
    if row is None:
        return 0.0
    return float(row.get("매입가", 0.0) or 0.0)

def has_position(name, ticker):
    row = get_holding_row_by_ticker(holdings_table, ticker)
    if row is None:
        return False
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

    is_early_entry = (trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and last["MACD"] > prev["MACD"] and 
                      macd_state in ["📉하락주의(데드크로스)", "⏳추세관망"] and mfi_now < 80 and pct_b_now < 0.85 and 50 <= rsi_now <= 65 and adj_tech_score >= 4.0)
    is_breakout_extreme = (not is_etf) and fin_score == 4 and adj_tech_score >= 4.0 and pct_b_now > 1.02 and rs_label == "🚀강함"
    is_breakout_normal = (not is_etf) and fin_score == 4 and adj_tech_score >= 4.0 and 0.95 <= pct_b_now <= 1.02 and rs_label == "🚀강함"
    
    # -------------------------------
    # 예외 승인 프로세스 (정찰대 진입)
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

    is_ma5_pullback = (
        ma5_now > 0 and (
            abs(cur_p - ma5_now) / ma5_now <= 0.015 or
            low_now <= ma5_now * 1.01
        )
    )

    is_bullish_fvg_pullback = (
        fvg_info["type"] == "Bullish FVG" and
        fvg_info["bottom"] is not None and
        fvg_info["top"] is not None and
        float(fvg_info["bottom"]) * 0.995 <= cur_p <= float(fvg_info["top"]) * 1.01
    )

    is_exception_entry = (
        is_leader_base and
        (is_ma5_pullback or is_bullish_fvg_pullback) and
        mfi_now < 90 and
        pct_b_now < 1.08
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
        if not is_etf and fin_score == 1: dec, col = "🚨하드차단: 재무F급(처분)", "#dc2626"
        elif curr_w > targ_w and targ_w > 0: dec, col = "🛑하드차단: 비중 초과", "#dc2626"
        elif curr_w >= targ_w and targ_w > 0: dec, col = "⏸️하드차단: 비중 충족(관망)", "#d97706"
        elif current_dd <= -0.5: dec, col = "💣패닉(-50%↓): 최종투입", "#7f1d1d"
        elif current_dd <= -0.4: dec, col = "💣패닉(-40%↓): 현금 투입", "#991b1b"
        elif current_dd <= -0.3: dec, col = "🚨위기(-30%↓): 코어 집중", "#b91c1c"
        elif current_dd <= -0.2: dec, col = "🚨위기(-20%↓): 현금 확보", "#dc2626"
        elif final_macro_risk >= 4.5: dec, col = "🛑하드차단: 퍼펙트스톰(대피)", "#dc2626"
        elif is_exception_entry and has_pos:
            dec, col = "🟣예외승인: 정찰대 추매(MA5/FVG)", "#7c3aed"
        elif is_exception_entry and (not has_pos):
            dec, col = "🟣예외승인: 정찰대 진입(MA5/FVG)", "#7c3aed"     
        elif mfi_now >= 85: dec, col = "🚫하드차단: MFI 극단 과열", "#dc2626"
        elif is_breakout_extreme: dec, col = "⚠️과열확장: 추격금지, MA5 대기", "#d97706"
        elif is_breakout_normal: dec, col = "🔥불뿜는 대장주: MA5 눌림 진입", "#ec4899"
        elif pct_b_now >= 0.95: dec, col = "🚫하드차단: 볼린상단 이탈", "#dc2626"
        elif has_pos:
            if trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 추매", "#8b5cf6"
            elif mfi_now >= 80: dec, col = "⚠️단기과열: 추매 보류", "#d97706"
            elif rsi_now <= 30: dec, col = "🔥낙폭과대: 줍줍 찬스", "#16a34a"
            elif rs_label == "🚀강함" and mfi_now < 35: dec, col = "💎S급: 과매도(풀매수)", "#16a34a"
            elif adj_tech_score >= 4 and cur_p <= my_price: dec, col = "🎯A급: 기술적 반등", "#16a34a"
            elif trend_label == "🚀정배열(상승)" and pct_b_now < 0.8 and rsi_now < 60 and cur_p <= my_price: dec, col = "📈정배열: 눌림목 매수", "#16a34a"
            elif cur_p > my_price: dec, col = "⏳평단이상: 하락대기(보유)", "#d97706"
            elif cur_p <= my_price: dec, col = "✅평단이하: 분할매수", "#16a34a"
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
    "에이디테크놀러지": ("200710.KQ", False, "kr_stock"),
}

@st.cache_data(ttl=300)
def get_all_summary(fin_score_map_items, mode, watchlist_items):
    rows = []
    fin_map = dict(fin_score_map_items)

    for item in watchlist_items:
        name = item["name"]
        tkr = item["ticker"]
        is_etf = item["is_etf"]
        a_class = item["asset_class"]

        df = load_price_df(tkr, "1y")
        if df.empty:
            continue

        df = build_indicators(df)

        auto_fin_score, _ = get_final_fin_score(tkr, is_etf, a_class)
        fin_key = normalize_ticker(tkr)
        f_score = int(fin_map.get(fin_key, auto_fin_score))

        c = calc_scores_and_decision(
            name, tkr, is_etf, a_class, df,
            0, False, f_score, app_mode=mode
        )

        rows.append({
            "종목명": name,
            "티커": tkr,
            "현재가": format_currency(c["cur_p"], tkr),
            "MDD": f"{c['dd']*100:.1f}%",
            "📌후보등급": c["grade"],
            "RS": c["rs_label"],
            "RSI": round(c["rsi"], 1),
            "MFI": round(c["mfi"], 1),
            "볼린저 %B": round(c["pct_b"], 2),
            "🔥기술적 타점": c["dec"],
            "Adj점수": round(c["adj"], 1)
        })

    return pd.DataFrame(rows)

# -------------------------------------------------
# 8. 메인 UI 렌더링
# -------------------------------------------------
macro_res, final_macro_risk, macro_penalty, move_val = get_macro_analysis()

st.caption(f"모드: {app_mode} | 매크로 리스크: {final_macro_risk:.1f} | 매크로 패널티: -{macro_penalty}")

if macro_res:
    m_cols = st.columns(len(macro_res))
    for i, (n, info) in enumerate(macro_res.items()):
        s_tag = "<br><span style='color:#ef4444; font-weight:bold;'>🚨폭풍</span>" if info["storm"] else ""
        m_cols[i].markdown(
            f"<div class='macro-panel'>🌐 {n}: <b>{info['val']:,.1f}</b> {info['icon']}{s_tag}</div>",
            unsafe_allow_html=True
        )
else:
    st.info("매크로 데이터를 불러오지 못했습니다.")

# --- 데이터 로드 블록 (SQLite DB 연동) ---
settings = load_settings_db()
holdings_df = load_holdings_db()
dividends_df = load_dividends_db()
monthly_logs_df = load_monthly_logs_db()

seed_money = float(settings.get("seed_money", 0.0))
krw_cash = float(settings.get("krw_cash", 0.0))
usd_cash = float(settings.get("usd_cash", 0.0))
usdkrw = float(settings.get("usdkrw", 1400.0))

holdings_table = build_holdings_table(holdings_df, krw_cash, usd_cash, usdkrw)
portfolio_summary = calc_portfolio_summary(
    holdings_table, seed_money, krw_cash, usd_cash, usdkrw, dividends_df
)
total_eval = portfolio_summary["current_asset"]
# --------------------------------------------

tab1, tab2, tab3 = st.tabs(["📋 전체 요약 전광판", "🔍 종목 정밀 관측소", "⚙️ 자산 관리"])

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
        st.session_state.watchlist = [
            item for item in st.session_state.watchlist
            if normalize_ticker(item["ticker"]) != normalize_ticker(remove_ticker)
        ]
        sync_watchlist_to_query()
        st.rerun()

    summary_df = get_all_summary(
        tuple(sorted(st.session_state.fin_score_map.items())),
        app_mode,
        tuple(st.session_state.watchlist)
    )

    if summary_df.empty:
        st.warning("전광판에 표시할 종목이 없습니다.")
    else:
        st.dataframe(summary_df, use_container_width=True, height=720, hide_index=True)
        
with tab2:
    options = ["🆓 자유 종목 탐색 (티커 입력)"] + list(TICKER_MAP.keys())
    sel = st.selectbox("종목 선택", options)
    is_free = (sel == "🆓 자유 종목 탐색 (티커 입력)")

    if is_free:
        c1, c2 = st.columns([2, 1])
        with c1:
            user_tkr_raw = st.text_input("티커/종목코드 (예: GOOGL, 005930)", "GOOGL").upper().strip()
        with c2:
            mkt_opt = st.selectbox("시장 (한국주식 시)", ["KOSPI (.KS)", "KOSDAQ (.KQ)"])

        if user_tkr_raw.isdigit() and len(user_tkr_raw) == 6:
            tkr = f"{user_tkr_raw}{'.KS' if 'KOSPI' in mkt_opt else '.KQ'}"
        else:
            tkr = user_tkr_raw

        known_etf_tickers = {
            "QQQ", "QQQM", "QLD", "TQQQ", "SOXL", "SOXX", "SPY", "VOO", "IVV",
            "VTI", "DIA", "IWM", "SCHD", "JEPI", "JEPQ", "SMH", "XLE", "XLF",
            "379810.KS", "379800.KS", "458730.KS", "069500.KS"
        }

        ticker_norm = normalize_ticker(tkr)
        is_etf = (
            ticker_norm in {normalize_ticker(x) for x in known_etf_tickers}
            or tkr.upper().endswith("ETF")
        )

        a_class = "kr_etf" if (is_etf and tkr.endswith((".KS", ".KQ"))) else (
            "us_etf_nasdaq" if is_etf else ("kr_stock" if tkr.endswith((".KS", ".KQ")) else "us_stock")
        )

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
    auto_fin_score, fin_meta = get_final_fin_score(tkr, is_etf, a_class)

    if fin_key not in st.session_state.fin_score_map:
        st.session_state.fin_score_map[fin_key] = auto_fin_score

    fin_score = int(st.session_state.fin_score_map[fin_key])

    st.markdown(
        f"<div class='info-panel'><b>재무 점수</b><br>{f_labels[fin_score]}</div>",
        unsafe_allow_html=True
    )

    with st.expander("재무점수 계산 근거"):
        st.write("source:", fin_meta.get("source"))
        st.write("auto_score:", fin_meta.get("auto_score"))
        st.write("manual_score:", fin_meta.get("manual_score"))
        st.write("final_score:", fin_meta.get("final_score"))

        metrics = fin_meta.get("metrics", {})
        if metrics:
            st.write("roe:", metrics.get("roe"))
            st.write("op_margin:", metrics.get("op_margin"))
            st.write("net_margin:", metrics.get("net_margin"))
            st.write("debt_ratio:", metrics.get("debt_ratio"))
            st.write("ocf:", metrics.get("ocf"))
            st.write("revenue:", metrics.get("revenue"))
            st.write("net_income:", metrics.get("net_income"))

        for n in fin_meta.get("notes", []):
            st.write("-", n)

    manual_override = st.checkbox("재무점수 수동 수정", key=f"manual_fin_{fin_key}")
    if manual_override:
        manual_score = st.radio(
            "수동 재무점수",
            [0, 1, 2, 3, 4],
            index=int(fin_score),
            format_func=lambda x: f_labels[x],
            horizontal=True,
            key=f"manual_fin_score_{fin_key}"
        )
        set_manual_fin_score(tkr, manual_score)
        st.session_state.fin_score_map[fin_key] = int(manual_score)
        fin_score = int(manual_score)

        if st.button("자동 재무점수로 되돌리기", key=f"reset_manual_{fin_key}"):
            reset_manual_fin_score(tkr)
            st.session_state.fin_score_map[fin_key] = get_final_fin_score(tkr, is_etf, a_class)[0]
            st.rerun()

    st.markdown("### ⭐ 관심종목 관리")
    a1, a2 = st.columns(2)

    current_item = {
        "name": name,
        "ticker": tkr,
        "is_etf": is_etf,
        "asset_class": a_class,
        "fin_score": int(fin_score)
    }

    if is_in_watchlist(tkr):
        for item in st.session_state.watchlist:
            if normalize_ticker(item["ticker"]) == normalize_ticker(tkr):
                item["fin_score"] = int(fin_score)
                break
        sync_watchlist_to_query()
        
    with a1:
        if is_in_watchlist(tkr):
            st.success("이미 전광판에 등록된 종목입니다.")
        else:
            if st.button("전광판에 등록"):
                st.session_state.watchlist.append(current_item)
                sync_watchlist_to_query()
                st.rerun()

    with a2:
        if is_in_watchlist(tkr):
            if st.button("전광판에서 제거", key=f"remove_{normalize_ticker(tkr)}"):
                st.session_state.watchlist = [
                    item for item in st.session_state.watchlist
                    if normalize_ticker(item["ticker"]) != normalize_ticker(tkr)
                ]
                sync_watchlist_to_query()
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
                f"<div class='info-panel'>"
                f"현재가: <span class='highlight'>{format_currency(c['cur_p'], tkr)}</span><br>"
                f"3개월 수익률: <span style='color:{ret3_color}; font-weight:bold;'>{c['ret_3m']*100:.1f}%</span><br>"
                f"6개월 수익률: <span style='color:{ret6_color}; font-weight:bold;'>{c['ret_6m']*100:.1f}%</span><br>"
                f"고점대비 MDD: <span style='color:{dd_c}; font-weight:bold;'>{c['dd']*100:.1f}%</span>"
                f"</div>",
                unsafe_allow_html=True
            )
            
            if is_free or app_mode == "범용모드": 
                st.info("💡 직접 입력 기반 분석 모드입니다.")
            else:
                if has_p and my_p > 0: st.markdown(f"<div class='info-panel' style='border-left: 5px solid #27ae60;'><b>내 평단가 (DB 연동)</b><br><span class='highlight' style='color:#2ecc71;'>{format_currency(my_p, tkr)}</span></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-panel'><b>비중</b><br>목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>부족 매수액: {c['buy_amt']:,.0f}원</div>", unsafe_allow_html=True)
            
            if app_mode == "범용모드": 
                st.markdown(
                    f"<div class='info-panel'><b>입력 기준</b><br>"
                    f"총 자산: {u_asset:,.0f}원<br>"
                    f"평단가: {format_currency(u_price, tkr)}<br>"
                    f"목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>"
                    f"<b>부족 매수액: {c['buy_amt']:,.0f}원</b></div>",
                    unsafe_allow_html=True
                )
            
            st.markdown(f'<div class="signal-box" style="background-color: {c["col"]};"><div style="font-size: 1.5em;">{c["dec"]}</div><div class="score-detail">Adj: {c["adj"]:.1f}점</div></div>', unsafe_allow_html=True)
            
            fin_text = "해당없음" if is_etf else f"{c['fin_score']}/4"
            st.markdown(
                f"<div class='info-panel' style='border-left: 5px solid #8b5cf6;'>"
                f"<b>📌 후보 등급 판정</b><br>"
                f"<span class='highlight' style='font-size:1.1em;'>{c['grade']}</span> (총점: {c['t_score']}점)<br>"
                f"└ 🛠️기술: {c['tech_total']} (RS:{c['rs_s']}, MFI:{c['mfi_s']}, 추세:{c['trend_s']}, MACD:{c['macd_s']}, SQZ:{c['sqz_s']})<br>"
                f"└ 💰재무: {fin_text}</div>",
                unsafe_allow_html=True
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
            for item in news_items: st.markdown(f"<div class='news-box'><a href='{item['link']}' target='_blank'>🔗 {item['title']}</a> <span style='color:#94a3b8; font-size:0.8em;'>출처: {item['publisher']}</span></div>", unsafe_allow_html=True)
        else: st.info("현재 제공되는 최신 뉴스가 없습니다.")
        
        if news_debug: 
            with st.expander("🛠️ 뉴스 디버그 로그"):
                for log in news_logs: st.write(log)
        st.markdown("### 🤖 AI 종합 해석 프롬프트")

        if st.button("AI 분석용 프롬프트 생성", key=f"ai_analysis_{normalize_ticker(tkr)}"):
            prompt = build_ai_analysis_prompt(name, tkr, macro_res, final_macro_risk, c)

            st.info("아래 프롬프트를 복사해서 ChatGPT나 Gemini에 붙여넣으면 됩니다.")

            st.text_area(
                "분석용 프롬프트",
                value=prompt,
                height=500,
                key=f"prompt_box_{normalize_ticker(tkr)}"
            )
    else: st.error("해당 종목의 차트 데이터를 불러올 수 없습니다. 티커를 다시 확인해 주십시오.")

with tab3:
    st.subheader("앱 내부 자산 관리")

    st.markdown("### 1) 기본 설정")
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        new_seed = st.number_input("시드머니", min_value=0.0, value=float(seed_money), step=100000.0)
    with col_s2:
        new_krw = st.number_input("원화 예수금", min_value=0.0, value=float(krw_cash), step=100000.0)
    with col_s3:
        new_usd = st.number_input("달러 예수금", min_value=0.0, value=float(usd_cash), step=100.0)
    with col_s4:
        new_fx = st.number_input("환율(USDKRW)", min_value=0.0, value=float(usdkrw), step=1.0)

    if st.button("기본 설정 저장"):
        save_settings_db(new_seed, new_krw, new_usd, new_fx)
        st.success("기본 설정 저장 완료")
        st.rerun()

    st.markdown("### 2) 보유 종목 관리")
    holdings_editor_df = load_holdings_db()
    if holdings_editor_df.empty:
        holdings_editor_df = pd.DataFrame(columns=["name", "ticker", "qty", "avg_price", "target_weight", "asset_class", "is_etf"])

    edited_holdings = st.data_editor(
        holdings_editor_df,
        num_rows="dynamic",
        use_container_width=True,
        key="holdings_editor"
    )

    if st.button("보유 종목 저장"):
        save_holdings_db(edited_holdings.fillna(""))
        st.success("보유 종목 저장 완료")
        st.rerun()

    st.markdown("### 3) 배당 내역 관리")
    dividends_editor_df = load_dividends_db()
    if dividends_editor_df.empty:
        dividends_editor_df = pd.DataFrame(columns=["date", "ticker", "amount", "currency"])

    edited_dividends = st.data_editor(
        dividends_editor_df,
        num_rows="dynamic",
        use_container_width=True,
        key="dividends_editor"
    )

    if st.button("배당 내역 저장"):
        save_dividends_db(edited_dividends.fillna(""))
        st.success("배당 내역 저장 완료")
        st.rerun()

    st.markdown("### 4) 월별 로그 관리")
    monthly_editor_df = load_monthly_logs_db()
    if monthly_editor_df.empty:
        monthly_editor_df = pd.DataFrame(columns=["month", "total_invested", "evaluated_value", "dividend"])

    edited_monthly = st.data_editor(
        monthly_editor_df,
        num_rows="dynamic",
        use_container_width=True,
        key="monthly_editor"
    )

    if st.button("월별 로그 저장"):
        save_monthly_logs_db(edited_monthly.fillna(""))
        st.success("월별 로그 저장 완료")
        st.rerun()

    st.markdown("### 5) 현재 계산 결과")
    st.write(
        f"주식 평가금: {portfolio_summary['stock_value']:,.0f}원 | "
        f"현금 포함 자산: {portfolio_summary['current_asset']:,.0f}원 | "
        f"누적손익: {portfolio_summary['cum_profit']:,.0f}원 | "
        f"누적수익률: {portfolio_summary['cum_return']:.2f}%"
    )

    if not holdings_table.empty:
        show_df = holdings_table.copy()
        show_df["수익률"] = show_df["수익률"].apply(lambda x: f"{x*100:.2f}%")
        st.dataframe(show_df, use_container_width=True, hide_index=True)
    else:
        st.info("등록된 보유 종목이 없습니다.")
