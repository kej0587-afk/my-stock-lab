from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import hmac
import io
import math
import zipfile
import requests
import json
import base64
import os
import numpy as np
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
from stock_lab_core.financial_score import (
    estimate_kr_fin_score_from_naver_snapshot,
    resolve_fin_score_source,
)
from stock_lab_core.decision_engine import (
    build_core_dca_outcome,
    build_decision_outcome,
    build_limited_history_etf_outcome,
    build_position_sizing_hint,
    build_core_dca_context_values,
    classify_candidate_grade,
    classify_decision_signal,
    classify_core_etf_dca_rate as classify_core_etf_dca_rate_rule,
    ensure_min_price_rows_for_decision,
    is_new_entry_decision_code,
    score_main_entry,
    score_technical_components,
)
from stock_lab_core.news import (
    get_analyst_snapshot,
    get_ticker_news,
    render_news_cards,
    render_research_report_panel,
    fetch_naver_kr_snapshot,
    fetch_investor_trend,
    render_investor_trend_panel,
    render_investor_top10_panel,
)
from stock_lab_core.money_flow import (
    calculate_money_flow_df,
    calculate_rotation_df,
    calculate_sector_rotation_df,
    classify_money_flow_state,
    download_money_flow_prices,
)
try:
    from stock_lab_core.money_flow import (
        calculate_image_theme_flow_df,
        calculate_image_theme_group_df,
        calculate_image_theme_rotation_df,
        get_image_theme_names,
        IMAGE_THEME_META,
    )
    IMAGE_THEME_FLOW_AVAILABLE = True
except ImportError:
    IMAGE_THEME_FLOW_AVAILABLE = False
    IMAGE_THEME_META = {}

try:
    from streamlit_lightweight_charts import renderLightweightCharts
    _LWC_AVAILABLE = True
except ImportError:
    _LWC_AVAILABLE = False

    def get_image_theme_names():
        return []

    def calculate_image_theme_flow_df(theme):
        return pd.DataFrame()

    def calculate_image_theme_group_df(theme_flow_df):
        return pd.DataFrame()

    def calculate_image_theme_rotation_df(theme_flow_df):
        return pd.DataFrame()
try:
    from stock_lab_core.money_flow import get_sector_flow_state
except ImportError:
    def get_sector_flow_state(ticker): return "-"
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
# ==========================================
# [신규 추가] 유틸리티 및 안전 장치
# ==========================================
from dataclasses import dataclass
from typing import Optional
# numpy는 파일 상단에서 이미 import됨 (중복 제거)

# 1. Supabase 안전 조회 래퍼
@dataclass
class DbResult:
    data: list
    error: Optional[str] = None
    
    @property
    def ok(self) -> bool:
        return self.error is None

def safe_supabase_query(query, action: str = "") -> DbResult:
    """Supabase 쿼리를 실행하고 결과를 안전하게 반환합니다."""
    try:
        res = query.execute()
        return DbResult(data=res.data or [])
    except Exception as e:
        return DbResult(data=[], error=f"{action}: {e}")

# 2. 보유종목 행 파싱 헬퍼 (타입 에러 방지)
def parse_holding_row(row: dict) -> dict:
    """보유종목 행에서 타입 안전한 값을 추출합니다."""
    return {
        "ticker": sanitize_ticker_value(row.get("ticker", "")),
        "name": str(row.get("name", "")).strip(),
        "qty": clean_float(row.get("qty"), 0.0),
        "avg_price": clean_float(row.get("avg_price"), 0.0),
        "target_weight": clean_float(row.get("target_weight"), 0.0),
        "asset_class": str(row.get("asset_class", "")).strip(),
        "is_etf": clean_bool(row.get("is_etf", False)),
        "bucket": infer_bucket(row.get("ticker", ""), row.get("bucket", "core")),
    }

# 3. 매크로 리스크 등급 (상수화)
class MacroRiskLevel:
    PERFECT_STORM = 4.5
    HIGH = 2.5
    MODERATE = 1.5
    LOW = 0.0

# ==========================================
# [신규 추가] 독립 분석 모듈 (신고가, 실적, 사이징)
# ==========================================

def detect_52w_breakout(df: pd.DataFrame) -> dict:
    """52주 신고가 돌파 여부와 강도를 분석합니다."""
    if len(df) < 20:
        return {"breakout": False, "label": "데이터부족"}
    
    # 252거래일(약 1년) 최고가 계산
    high_52w = df["High"].rolling(252, min_periods=60).max().iloc[-1]
    cur = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2])
    
    # 거래량 분석
    vol_mean_20 = df["Volume"].rolling(20).mean().iloc[-1]
    vol_ratio = float(df["Volume"].iloc[-1]) / float(vol_mean_20) if (not pd.isna(vol_mean_20) and vol_mean_20 > 0) else 1.0
    
    is_breakout = (prev < high_52w) and (cur >= high_52w) and (vol_ratio >= 1.3)
    near_high = (cur >= high_52w * 0.97) and not is_breakout
    
    if is_breakout:
        label = f"🚀 52주 신고가 돌파 (거래량 {vol_ratio:.1f}x)"
    elif near_high:
        label = f"⚡ 52주 신고가 근접 ({(cur/high_52w - 1)*100:.1f}%)"
    else:
        label = f"고점대비 {(cur/high_52w - 1)*100:.1f}%"
    
    return {"breakout": is_breakout, "near_high": near_high, "label": label}

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_earnings_date(ticker: str) -> dict:
    """다음 실적 발표일과 이벤트 리스크를 반환합니다."""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None or (isinstance(cal, pd.DataFrame) and cal.empty):
            return {"ok": False, "label": "실적발표일 미확인"}
        
        earnings_date = None
        # yfinance 버전에 따라 calendar 형태가 다를 수 있음
        if isinstance(cal, dict) and "Earnings Date" in cal:
            earnings_date = cal["Earnings Date"][0]
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            earnings_date = cal.loc["Earnings Date"].iloc[0]
            
        if not earnings_date or pd.isna(earnings_date):
            return {"ok": False, "label": "실적발표일 미확인"}
        
        # 날짜 비교 (timezone 제거 후 계산)
        target_dt = pd.to_datetime(earnings_date).tz_localize(None)
        now_dt = pd.Timestamp.now().tz_localize(None)
        days_until = (target_dt - now_dt).days
        
        if days_until < 0:
            risk_label = "실적 발표 완료"
        elif days_until <= 7:
            risk_label = f"⚠️ 실적 {days_until}일 후 (주의)"
        else:
            risk_label = f"📅 실적 {days_until}일 후"
            
        return {"ok": True, "label": risk_label, "high_risk": 0 <= days_until <= 7}
    except Exception:
        return {"ok": False, "label": "조회 불가"}

def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range 계산 (변동성 지표)"""
    if len(df) < period + 1: return 0.0
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def calc_position_size(total_asset: float, target_weight_pct: float, current_weight_pct: float, current_price: float, atr: float) -> dict:
    """비중 및 ATR 기반 매수/손절 가이드 계산"""
    weight_gap = max(target_weight_pct - current_weight_pct, 0.0)
    budget = total_asset * (weight_gap / 100)
    
    # 2 ATR 손절선 적용
    stop_distance = atr * 2.0
    stop_price = current_price - stop_distance if stop_distance > 0 else 0
    final_qty = budget / current_price if current_price > 0 else 0
    
    return {
        "budget_amount": budget,
        "final_qty": final_qty,
        "stop_price": stop_price,
        "atr": atr
    }

# ==========================================
# [신규 추가] 고급 차트 분석 (SMC, FVG, 지지/저항)
# ==========================================
def detect_smc_features(df: pd.DataFrame) -> dict:
    """최근 캔들 데이터를 분석하여 FVG(Fair Value Gap) 및 단기 강한 지지선을 찾습니다."""
    if len(df) < 5:
        return {"fvg_label": "데이터 부족", "ob_label": "데이터 부족"}

    # 최근 20거래일 데이터로 단기 수급 분석
    recent_df = df.tail(20).copy()
    bullish_fvgs = []
    bearish_fvgs = []

    # 1. FVG(불균형 갭) 탐지: 3개의 캔들 사이의 빈 공간
    for i in range(2, len(recent_df)):
        c1_high = float(recent_df['High'].iloc[i-2])
        c1_low = float(recent_df['Low'].iloc[i-2])
        c3_high = float(recent_df['High'].iloc[i])
        c3_low = float(recent_df['Low'].iloc[i])

        # 상승 FVG: 1번 캔들 고가보다 3번 캔들 저가가 높을 때 (매수세가 너무 강해 생긴 빈 공간)
        if c1_high < c3_low:
            bullish_fvgs.append((c1_high, c3_low))
        # 하락 FVG: 1번 캔들 저가보다 3번 캔들 고가가 낮을 때 (매도세가 너무 강해 생긴 빈 공간)
        if c1_low > c3_high:
            bearish_fvgs.append((c3_high, c1_low))

    fvg_label = "FVG 갭 없음 (균형 상태)"
    if bullish_fvgs:
        latest_bull = bullish_fvgs[-1]
        fvg_label = f"🔼 지지 갭(FVG): {latest_bull[0]:.2f} ~ {latest_bull[1]:.2f}"
    elif bearish_fvgs:
        latest_bear = bearish_fvgs[-1]
        fvg_label = f"🔽 저항 갭(FVG): {latest_bear[0]:.2f} ~ {latest_bear[1]:.2f}"

    # 2. 단기 강한 지지선 (최근 20일 내 최저점을 만든 캔들의 영역)
    min_idx = recent_df['Low'].idxmin()
    ob_low = float(recent_df.loc[min_idx, 'Low'])
    ob_high = float(recent_df.loc[min_idx, 'High'])
    ob_label = f"🛡️ 단기 지지선: {ob_low:.2f} ~ {ob_high:.2f}"

    return {
        "fvg_label": fvg_label,
        "ob_label": ob_label
    }

# ================================================
# [신규 추가] 손절 vs 장기보유 종합 판단 엔진
# ================================================
from enum import Enum
from dataclasses import dataclass, field

class HoldDecision(Enum):
    STRONG_HOLD = "💎 강력 장기보유"
    CONDITIONAL_HOLD = "✅ 조건부 장기보유"
    WATCH = "⚠️ 모니터링 강화"
    REDUCE = "📉 비중 축소 검토"
    STOP_LOSS = "🚨 손절 검토"
    EMERGENCY_EXIT = "❌ 긴급 매도"

@dataclass
class HoldJudgement:
    decision: HoldDecision
    score: int
    fundamental_score: int = 0
    technical_score: int = 0
    thesis_score: int = 0
    risk_score: int = 0
    reasons_hold: list = field(default_factory=list)
    reasons_caution: list = field(default_factory=list)
    reasons_exit: list = field(default_factory=list)
    action_plan: str = ""

def build_hold_decision(ticker, name, is_etf, fin_score, c, my_price, has_pos) -> HoldJudgement:
    score = 0
    r_hold, r_caution, r_exit = [], [], []

    cur_p = clean_float(c.get("cur_p"), 0.0)
    dd = clean_float(c.get("dd"), 0.0)
    trend = str(c.get("trend", ""))
    rs_label = str(c.get("rs_label", ""))
    structure_risk = bool(c.get("structure_risk"))
    price_vs_avg = (cur_p / my_price - 1) if has_pos and my_price > 0 else np.nan

    # 1. 재무 점수
    fund_score = 0
    if is_etf:
        fund_score = 2
        r_hold.append("ETF: 개별기업 부도 리스크 없음")
    else:
        if fin_score >= 4: fund_score = 4; r_hold.append("재무 4점: 펀더멘털 우수")
        elif fin_score == 3: fund_score = 1; r_hold.append("재무 3점: 펀더멘털 양호")
        elif fin_score == 2: fund_score = -2; r_caution.append("재무 2점: 재무 훼손 주의")
        else: fund_score = -4; r_exit.append("재무 1점: 펀더멘털 위험 수준 (처분 검토)")
    score += fund_score

    # 2. 기술적 점수
    tech_score = 0
    if "정배열" in trend: tech_score += 2; r_hold.append("이동평균선 정배열 유지")
    elif "역배열" in trend: tech_score -= 2; r_caution.append("이동평균선 역배열 (추세 꺾임)")
    
    rs_slope_label = str(c.get("rs_slope_label", ""))
    if "🚀" in rs_label:
        if "📉" in rs_slope_label:
            tech_score += 1; r_caution.append("RS 강함이나 기울기 하락 중 — 상대강도 약화 진행")
        else:
            tech_score += 2; r_hold.append("시장/섹터 대비 강한 상대강도")
    elif "🐢" in rs_label:
        if "📈" in rs_slope_label:
            tech_score -= 1; r_caution.append("RS 약하나 기울기 개선 중 — 반전 여부 관찰")
        else:
            tech_score -= 2; r_caution.append("시장/섹터 대비 약한 상대강도")
        
    if dd <= -0.30: tech_score -= 3; r_exit.append(f"고점대비 {dd*100:.1f}% 하락 (구조적 손상)")
    elif dd <= -0.20: tech_score -= 1; r_caution.append(f"고점대비 {dd*100:.1f}% 하락")
        
    if structure_risk: tech_score -= 2; r_caution.append("구조 훼손 신호 포착")
    score += tech_score

    # 3. 리스크/포지션 점수
    risk_score = 0
    if has_pos and finite_num(price_vs_avg):
        if price_vs_avg <= -0.15: risk_score -= 3; r_exit.append(f"내 평단 대비 {price_vs_avg*100:.1f}% 손실")
        elif price_vs_avg > 0.20: risk_score += 2; r_hold.append("충분한 안전마진 확보")
    score += risk_score

    # 4. 투자 논리 점수
    # 수동 스윙 레이더는 현재 운용 흐름에서 제외하므로 장기보유 판정에 반영하지 않습니다.
    thesis_score = 0
    score += thesis_score

    # 5. 최종 판정
    hard_exit = (not is_etf and fin_score <= 1) or (has_pos and finite_num(price_vs_avg) and price_vs_avg <= -0.25 and dd <= -0.25)
    
    if hard_exit: decision = HoldDecision.EMERGENCY_EXIT
    elif score >= 6: decision = HoldDecision.STRONG_HOLD
    elif score >= 3: decision = HoldDecision.CONDITIONAL_HOLD
    elif score >= 0: decision = HoldDecision.WATCH
    elif score >= -3: decision = HoldDecision.REDUCE
    else: decision = HoldDecision.STOP_LOSS

    action_plan = "즉시 비중 대폭 축소 또는 매도 검토" if decision in [HoldDecision.EMERGENCY_EXIT, HoldDecision.STOP_LOSS] else ("비중 축소 검토" if decision == HoldDecision.REDUCE else "현재 포지션 유지 가능")
    if decision == HoldDecision.STRONG_HOLD: action_plan = "장기 보유 유효 (목표 비중까지 분할 매수 가능)"

    return HoldJudgement(decision, score, fund_score, tech_score, thesis_score, risk_score, r_hold, r_caution, r_exit, action_plan)

def render_hold_decision_panel(name, ticker, is_etf, c, fin_score, has_pos, my_price):
    st.markdown("### 🏛️ 장기보유 종합 판정 (독립 모듈)")
    
    if not has_pos:
        st.info("보유 포지션이 없습니다. 매수 후 이 패널을 활용해 손절/장기보유를 점검하세요.")
        return
        
    judgement = build_hold_decision(ticker, name, is_etf, fin_score, c, my_price, has_pos)
    
    color_map = {
        HoldDecision.STRONG_HOLD: "#16a34a", HoldDecision.CONDITIONAL_HOLD: "#22c55e",
        HoldDecision.WATCH: "#d97706", HoldDecision.REDUCE: "#f97316",
        HoldDecision.STOP_LOSS: "#dc2626", HoldDecision.EMERGENCY_EXIT: "#7f1d1d",
    }
    color = color_map.get(judgement.decision, "#64748b")
    
    st.markdown(
        f"<div class='info-panel' style='border-left: 6px solid {color};'>"
        f"<b>{escape_html_value(name)} 보유 판단</b><br>"
        f"<span class='highlight' style='font-size:1.3em; color:{color};'>"
        f"{escape_html_value(judgement.decision.value)}</span> (총 {judgement.score}점)<br><br>"
        f"<b>행동 제안:</b> {escape_html_value(judgement.action_plan)}"
        f"</div>",
        unsafe_allow_html=True,
    )
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### ✅ 긍정/유지 요인")
        for r in judgement.reasons_hold: st.caption(f"- {r}")
    with col2:
        st.markdown("#### ⚠️ 주의 요인")
        for r in judgement.reasons_caution: st.caption(f"- {r}")
    with col3:
        st.markdown("#### 🚨 위험/매도 요인")
        for r in judgement.reasons_exit: st.caption(f"- {r}")

st.markdown("""
    <style>
    /* 🖨️ 스트림릿 인쇄 고질병(1장만 인쇄됨) 완벽 치료 CSS */
    @media print {
        /* 1. 스트림릿의 겹겹이 쌓인 스크롤 컨테이너 봉인 해제 (가장 중요) */
        html, body, .stApp, 
        [data-testid="stAppViewContainer"], 
        [data-testid="stMain"], 
        [data-testid="stAppViewBlockContainer"],
        [data-testid="stMainBlockContainer"] {
            display: block !important;
            height: auto !important;
            width: 100% !important;
            max-height: none !important;
            max-width: 100% !important;
            overflow: visible !important;
            position: static !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        
        /* 2. 불필요한 UI 완벽 숨김 */
        [data-testid="stSidebar"], 
        [data-testid="stHeader"], 
        [data-testid="stToolbar"],
        .stButton, .stDownloadButton,
        div[data-baseweb="select"], 
        div[data-baseweb="radio"],
        div[data-testid="stCheckbox"] {
            display: none !important;
        }

        /* 3. 표와 컬럼 가로 잘림 방지 */
        [data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-wrap: wrap !important;
            overflow: visible !important;
            width: 100% !important;
        }
        [data-testid="column"] {
            flex: 1 1 auto !important;
            min-width: 0 !important;
            overflow: visible !important;
        }

        /* 4. 페이지 넘김 (Page Break) 강제 실행 */
        .print-page-break {
            display: block !important;
            page-break-before: always !important;
            break-before: page !important;
            height: 1px !important;
            margin: 0 !important;
            padding: 0 !important;
            visibility: hidden !important;
        }

        /* 5. 차트/표가 페이지 중간에서 찢어지는 것 방지 */
        table, .stDataFrame, div[data-testid="stDataFrame"] > div, .stPlotlyChart {
            page-break-inside: avoid !important;
            break-inside: avoid !important;
            overflow: visible !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# -------------------------------------------------
# 1. 기본 설정 및 CSS
# -------------------------------------------------
st.set_page_config(page_title="최종 관제실", layout="wide")
KST = timezone(timedelta(hours=9))

def safe_secret_get(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def get_secret_value(name, fallback_name=None):
    value = safe_secret_get(name, "")
    if not value:
        value = os.environ.get(name, "")
    if (not value) and fallback_name:
        value = safe_secret_get(fallback_name, "")
    if (not value) and fallback_name:
        value = os.environ.get(fallback_name, "")
    return str(value).strip()


def get_secret_emails(name):
    value = safe_secret_get(name, [])
    if isinstance(value, str):
        value = [x.strip() for x in value.split(",")]
    return {str(x).strip().lower() for x in value if str(x).strip()}


def get_auth_mode():
    forced_mode = os.environ.get("STOCK_LAB_FORCE_AUTH_MODE", "").strip().lower()
    if forced_mode in ["public_demo", "public-demo", "demo", "public", "체험모드"]:
        return "public_demo"

    mode = get_secret_value("AUTH_MODE", "auth_mode").strip().lower()

    if mode in ["password", "pass", "local"]:
        return "password"
    if mode in ["google", "oauth"]:
        return "google"
    if mode in ["public_demo", "public-demo", "demo", "public", "체험모드"]:
        return "public_demo"

    # Keep Google as the default. Password login is emergency-only and must be explicit.
    return "google"

st.markdown("""
    <style>
    /* 인쇄할 때만 적용되는 마법의 CSS */
    @media print {
        /* 1. 사이드바, 상단 헤더, 버튼 등 불필요한 UI는 인쇄 안 함 */
        [data-testid="stSidebar"], 
        header[data-testid="stHeader"], 
        .stButton, 
        .stDownloadButton {
            display: none !important;
        }
        
        /* 2. 화면 전체를 종이 끝까지 넓게 쓰기 */
        .main .block-container {
            max-width: 100% !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            padding-left: 1cm !important;
            padding-right: 1cm !important;
        }

        /* 3. ★ 핵심: 챕터별 강제 페이지 넘김 ★ */
        .page-break {
            page-break-before: always;
            padding-top: 2cm;
        }

        /* 4. 표나 차트가 종이 중간에 반으로 잘리지 않게 방지 */
        table, .stDataFrame, .stPlotlyChart {
            page-break-inside: avoid !important;
        }
    }
    </style>
""", unsafe_allow_html=True)


AUTH_MODE = get_auth_mode()


def is_public_demo_mode():
    return AUTH_MODE == "public_demo"


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
            if hmac.compare_digest(str(password), str(app_password)):
                st.session_state.password_ok = True
                st.rerun()
            else:
                st.error("Wrong password.")

        st.stop()

    return get_owner_email_for_password_login()


def logout_current_user():
    if is_public_demo_mode():
        st.rerun()
    elif AUTH_MODE == "password":
        st.session_state.password_ok = False
        st.rerun()
    else:
        st.logout()


def require_login():
    if is_public_demo_mode():
        return "public_demo@stocklab.local"

    if AUTH_MODE == "password":
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
IS_PUBLIC_DEMO = is_public_demo_mode()


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
    APP_MODE_LABELS = {
        "개인모드": "내 자산 연동",
        "범용모드": "직접 입력 분석",
    }
    if IS_PUBLIC_DEMO:
        app_mode = "범용모드"
        app_mode_label = "체험모드"
        st.info("체험모드입니다. 로그인 없이 볼 수 있고, 저장/복구/수정 내용은 서버에 반영되지 않습니다.")
        st.caption("정밀관측소의 직접 입력값과 샘플 포트폴리오로 기능을 체험합니다.")
    else:
        app_mode = st.radio(
            "분석 기준",
            ["개인모드", "범용모드"],
            index=0,
            format_func=lambda mode: APP_MODE_LABELS.get(mode, mode),
            help="내 자산 연동은 저장된 보유자산/평단/목표비중을 사용합니다. 직접 입력 분석은 정밀관측소에서 임의 값을 넣어 한 종목을 가정 분석합니다.",
        )
        app_mode_label = APP_MODE_LABELS.get(app_mode, app_mode)
        if app_mode == "개인모드":
            st.caption("저장된 내 보유자산, 평단가, 현재비중, 목표비중을 기준으로 판정합니다.")
        else:
            st.caption("공개 접속 모드가 아닙니다. 로그인한 상태에서 총자산, 평단가, 현재/목표비중을 직접 넣어 가정 분석합니다.")
    news_debug = st.checkbox("뉴스 디버그 보기", value=False)
    if IS_PUBLIC_DEMO:
        st.caption("Signed in: public demo (저장 안 됨)")
    else:
        st.caption(f"Signed in: {CURRENT_USER_EMAIL}")
        st.button("Log out", on_click=logout_current_user, key="logout_sidebar")

with st.sidebar:
        st.subheader("📂 계좌 필터링")
        
        # 1. DB에서 계좌 목록 불러오기
        base_accounts = ["일반", "ISA", "연금저축", "IRP"]
        try:
            tmp_df = load_holdings_db()
            if not tmp_df.empty and "account_type" in tmp_df.columns:
                db_accounts = tmp_df["account_type"].dropna().unique().tolist()
                base_accounts = list(dict.fromkeys(base_accounts + db_accounts))
        except:
            pass

        # 2. 스트림릿 고질적 버그(StreamlitAPIException) 완벽 우회
        # key를 직접 multiselect에 주지 않고 변수로 받아서 세션에 수동 저장합니다.
        prev_selected = st.session_state.get("my_safe_acc_filter", base_accounts)
        valid_selected = [x for x in prev_selected if x in base_accounts]
        if not valid_selected: valid_selected = base_accounts

        chosen_accounts = st.multiselect(
            "조회할 계좌 선택",
            options=base_accounts,
            default=valid_selected
        )
        
        # 수동으로 세션에 값 주입 (시스템 전체가 이 값을 바라보게 됨)
        st.session_state["my_safe_acc_filter"] = chosen_accounts
        st.session_state["acc_filter"] = chosen_accounts
    
st.title(f"🚀 REALTIME DIGITAL DASHBOARD v13.1 ({app_mode_label})")

def normalize_bucket(value):
    raw = str(value or "").strip().lower()
    if raw in ["core", "swing", "reserve", "cash", "leverage"]:
        return raw
    return "core"

def infer_bucket(ticker, value=""):
    key = normalize_ticker(ticker)
    raw = str(value or "").strip().lower()

    if key in RESERVE_TICKERS and raw in ["", "core", "nan", "none"]:
        return "reserve"
    if raw in ["core", "swing", "reserve", "cash", "leverage"]:
        return raw
    return "core"

def is_reserve_or_cash_bucket(bucket):
    return normalize_bucket(bucket) in RESERVE_BUCKETS

from stock_lab_core.ta_engine import (
    get_sqz_status, get_macd_state,
    build_indicators, get_trend,
    get_pivot_highs_lows, get_recent_levels,
    detect_structure_event, detect_liquidity_grab,
    detect_recent_fvg, get_pd_zone, summarize_smc_action,
)

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
    "HACK", "CIBR", "BUG",  # 사이버보안 ETF
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
    "012330": "현대모비스",
    "307950": "현대오토에버",
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
    # 영숫자 혼합 6자리 KR ETF 코드 (isdigit() 검사 우회)
    "0117V0": "TIGER 코리아AI전력기기TOP3플러스",
    "0022T0": "SOL 국제금커버드콜액티브",
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
        # 네이버 금융이 UTF-8로 전환됐으므로 UTF-8 우선 시도, 실패 시 EUC-KR 폴백
        try:
            page = raw.decode("utf-8")
        except UnicodeDecodeError:
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
    """yfinance 정보를 가져오고 한글 깨짐을 즉시 복구"""
    ticker = sanitize_ticker_value(ticker)
    if not ticker: return {}

    try:
        info = yf.Ticker(ticker).info
        if not info or not isinstance(info, dict): return {}
    except:
        return {}

    keys = ["shortName", "longName", "displayName", "quoteType", "sector", "industry", "category"]
    result = {}
    for key in keys:
        val = info.get(key, "")
        if isinstance(val, str) and val:
            try:
                # yfinance latin-1 버그 복구
                val = val.encode('latin-1').decode('utf-8')
            except:
                pass
        result[key] = val
    return result

def lookup_yfinance_display_name(ticker):
    info = lookup_yfinance_info(ticker)
    if not info:
        return ""
    
    def fix_latin(text):
        if not text or not isinstance(text, str): return text
        try:
            # latin-1으로 잘못 읽힌 것을 utf-8으로 재해석
            return text.encode('latin-1').decode('utf-8')
        except:
            return text

    for field in ["shortName", "longName", "displayName"]:
        raw_name = info.get(field, "")
        if raw_name:
            # 여기서 복구 로직 실행
            fixed_name = fix_latin(raw_name)
            name = clean_resolved_display_name(fixed_name, ticker)
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

    # [핵심] 한국 주식이면 네이버/KRX 이름만 쓰고 야후 파이낸스는 절대 조회하지 않음!
    # 0117V0, 0022T0 같이 영숫자 혼합 6자리 코드도 KR로 인식
    is_kr = (
        ticker_clean.endswith((".KS", ".KQ"))
        or (symbol.isdigit() and len(symbol) == 6)
        or (len(symbol) == 6 and symbol[0].isdigit() and symbol.isalnum())
    )
    if is_kr:
        for resolver in [lookup_kr_etf_display_name, lookup_naver_stock_name]:
            name = resolver(symbol)
            if name:
                return name
        return strip_search_prefix(fallback).strip() or ticker_clean

    # 미국 주식 등 해외 주식만 야후 파이낸스 이름 조회
    name = lookup_yfinance_display_name(ticker_clean)
    if name:
        return name

    fallback_name = strip_search_prefix(fallback).strip()
    if fallback_name and not (is_ticker_like_text(fallback_name) and clean_symbol(fallback_name) == symbol):
        return fallback_name

    return ticker_clean


def _is_garbled_kr_name(name: str, ticker: str) -> bool:
    """
    한국 종목(KS/KQ)에서 인코딩 오류로 깨진 이름 감지.
    원리: 네이버 금융이 UTF-8인데 EUC-KR로 잘못 읽으면
          UTF-8 3바이트 한글 시퀀스 일부가 CJK 통합 한자(U+4E00~U+9FFF)나
          호환 한자(U+F900~U+FAFF)로 잘못 디코딩됨.
          → 한국 회사명에 정상적으로 나오면 안 되는 한자가 섞이는 패턴.
    """
    if not name:
        return False
    if not str(ticker).upper().endswith((".KS", ".KQ")):
        return False
    # CJK 통합 한자 영역에 속하는 문자가 포함되면 깨진 이름으로 판단
    return any('一' <= ch <= '鿿' or '豈' <= ch <= '﫿' for ch in name)


def sanitize_asset_name(name, ticker=""):
    ticker_clean = sanitize_ticker_value(ticker)
    symbol = clean_symbol(ticker_clean)
    raw_name = str(name or "").strip()
    cleaned_name = strip_search_prefix(raw_name).strip()
    known_name = KNOWN_TICKER_DISPLAY_NAMES.get(symbol, "")

    # KNOWN_TICKER_DISPLAY_NAMES에 등록된 종목은 DB 저장값과 무관하게 항상 우선 적용
    if known_name:
        return known_name

    if not cleaned_name or cleaned_name.startswith((":","：")):
        return resolve_display_name_for_ticker(ticker_clean, ticker_clean)

    if is_ticker_like_text(cleaned_name) and clean_symbol(cleaned_name) == symbol:
        return resolve_display_name_for_ticker(ticker_clean, ticker_clean)

    # 과거 EUC-KR 오디코딩으로 Supabase에 저장된 깨진 이름 자동 재복구
    # (예: "쇱깆湲" → CJK 한자 포함 패턴 감지 → Naver 재조회)
    if _is_garbled_kr_name(cleaned_name, ticker_clean):
        return resolve_display_name_for_ticker(ticker_clean, ticker_clean)

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
RS 기울기: {c['rs_slope_label']} ({c['rs_slope_val']:+.1f}%, Adj보정:{c['rs_slope_s']:+d})
익절 시그널: {'⚠️발동(MFI≥80+%B>0.9+수익20%↑)' if c.get('profit_take_signal') else '없음'}
52주 신고가 돌파: {'🚀발동' if c.get('is_52w_breakout') else '없음'}
R/R 비율: {f"{c['rr_ratio']:.2f} (목표:{c['rr_target']:.0f} / 손절:{c['rr_stop']:.0f})" if c.get('rr_ratio') else '산출불가'}
섹터 머니플로우: {c.get('sector_flow_state', '-')}
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


PUBLIC_DEMO_EMAIL = "public_demo@stocklab.local"


def public_demo_write_blocked(action="저장"):
    st.info(f"체험모드에서는 {action}이 서버에 저장되지 않습니다. 실제 사용은 Google 로그인 버전에서 가능합니다.")
    return False


def get_public_demo_settings():
    return {
        "seed_money": 30_000_000.0,
        "krw_cash": 2_000_000.0,
        "usd_cash": 1_000.0,
        "usdkrw": 1400.0,
        "reserve_target_weight": 12.0,
    }


def get_public_demo_holdings_df():
    rows = [
        {"ticker": "QQQM", "name": "QQQM", "qty": 12, "avg_price": 185, "target_weight": 22, "asset_class": "us_etf_nasdaq", "is_etf": True, "bucket": "core"},
        {"ticker": "SCHD", "name": "SCHD", "qty": 25, "avg_price": 78, "target_weight": 18, "asset_class": "us_etf_other", "is_etf": True, "bucket": "core"},
        {"ticker": "MSFT", "name": "MSFT", "qty": 5, "avg_price": 390, "target_weight": 14, "asset_class": "us_stock", "is_etf": False, "bucket": "core"},
        {"ticker": "000660.KS", "name": "SK하이닉스", "qty": 8, "avg_price": 175000, "target_weight": 14, "asset_class": "kr_stock", "is_etf": False, "bucket": "core"},
        {"ticker": "379810.KS", "name": "TIGER 미국나스닥100", "qty": 35, "avg_price": 23500, "target_weight": 12, "asset_class": "us_etf_nasdaq", "is_etf": True, "bucket": "core"},
        {"ticker": "357870.KS", "name": "TIGER CD금리투자KIS", "qty": 20, "avg_price": 55000, "target_weight": 12, "asset_class": "kr_etf", "is_etf": True, "bucket": "reserve"},
    ]
    return dataframe_from_rows(rows, HOLDINGS_COLUMNS)


def get_public_demo_dividends_df():
    rows = [
        {"id": 1, "date": "2026-01-15", "ticker": "SCHD", "amount": 42000, "currency": "KRW"},
        {"id": 2, "date": "2026-02-15", "ticker": "QQQM", "amount": 18000, "currency": "KRW"},
        {"id": 3, "date": "2026-03-15", "ticker": "SCHD", "amount": 45000, "currency": "KRW"},
        {"id": 4, "date": "2026-04-15", "ticker": "379810.KS", "amount": 22000, "currency": "KRW"},
    ]
    return dataframe_from_rows(rows, DIVIDENDS_COLUMNS)


def get_public_demo_monthly_logs_df():
    rows = [
        {"month": "2025-11", "total_invested": 25_000_000, "evaluated_value": 25_800_000, "dividend": 25000},
        {"month": "2025-12", "total_invested": 26_000_000, "evaluated_value": 27_100_000, "dividend": 33000},
        {"month": "2026-01", "total_invested": 27_000_000, "evaluated_value": 28_000_000, "dividend": 42000},
        {"month": "2026-02", "total_invested": 28_000_000, "evaluated_value": 29_300_000, "dividend": 18000},
        {"month": "2026-03", "total_invested": 29_000_000, "evaluated_value": 30_400_000, "dividend": 45000},
        {"month": "2026-04", "total_invested": 30_000_000, "evaluated_value": 31_200_000, "dividend": 22000},
    ]
    return dataframe_from_rows(rows, MONTHLY_LOG_COLUMNS)


def get_public_demo_watchlist():
    holdings = get_public_demo_holdings_df()
    rows = []
    for _, row in holdings.iterrows():
        rows.append({
            "name": row.get("name", ""),
            "ticker": row.get("ticker", ""),
            "is_etf": clean_bool(row.get("is_etf", False)),
            "asset_class": row.get("asset_class", ""),
            "fin_score": 0 if clean_bool(row.get("is_etf", False)) else UNCALCULATED_FIN_DEFAULT_SCORE,
        })
    return [sanitize_watchlist_item(row) for row in rows]


PUBLIC_DEMO_PRICE_MAP = {
    "QQQM": 229.0,
    "SCHD": 79.5,
    "MSFT": 462.0,
    "000660.KS": 226000.0,
    "379810.KS": 28350.0,
    "357870.KS": 55650.0,
}


def get_public_demo_latest_price_map(tickers):
    result = {}
    for ticker in tickers:
        key = normalize_price_lookup_key(ticker)
        result[key] = clean_float(PUBLIC_DEMO_PRICE_MAP.get(key), 0.0)
    return result


def get_public_demo_macro_analysis():
    results = {
        "10Y 금리": {"val": 4.3, "icon": "➡️", "storm": False},
        "유가": {"val": 78.0, "icon": "➡️", "storm": False},
        "환율": {"val": 1400.0, "icon": "➡️", "storm": False},
        "MOVE": {"val": 102.0, "icon": "➡️", "storm": False},
        "VIX": {"val": 17.5, "icon": "➡️", "storm": False},
    }
    return results, 0.5, 0.0, results["MOVE"]["val"]

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


supabase = None if IS_PUBLIC_DEMO else get_supabase()


def get_supabase_for_feedback():
    if supabase is not None:
        return supabase, None
    try:
        return get_supabase_client(), None
    except Exception as e:
        return None, str(e)


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
    if IS_PUBLIC_DEMO:
        return

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


@st.cache_data(ttl=30, show_spinner=False)
def load_settings_db_for_user(owner_email):
    if IS_PUBLIC_DEMO:
        return get_public_demo_settings()

    res = run_supabase(
        supabase.table("settings").select("*").eq("owner_email", owner_email),
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


def load_settings_db():
    return load_settings_db_for_user(PUBLIC_DEMO_EMAIL if IS_PUBLIC_DEMO else CURRENT_USER_EMAIL)


def save_settings_db(seed_money, krw_cash, usd_cash, usdkrw, reserve_target_weight=10.0):
    if IS_PUBLIC_DEMO:
        return public_demo_write_blocked("기본 설정 저장")

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
    load_settings_db_for_user.clear()
    return True

@st.cache_data(ttl=30, show_spinner=False)
def load_holdings_db_for_user(owner_email):
    if IS_PUBLIC_DEMO:
        return get_public_demo_holdings_df()
        
    try:
        supabase = get_supabase_client()
        if not supabase: return pd.DataFrame(columns=HOLDINGS_COLUMNS + ["account_type"])
            
        # 939행 근처의 중간 return을 삭제하고 본인 데이터만 가져오도록 통합
        res = supabase.table("holdings").select("*").eq("owner_email", owner_email).execute()
        
        if not res or not res.data:
            return pd.DataFrame(columns=HOLDINGS_COLUMNS + ["account_type"])
            
        df = pd.DataFrame(res.data)
        if "account_type" not in df.columns: df["account_type"] = "일반"
            
        if not df.empty:
            df["ticker"] = df["ticker"].apply(sanitize_ticker_value)
            df["name"] = df.apply(lambda row: sanitize_asset_name(row.get("name", ""), row.get("ticker", "")), axis=1)
        return df
    except Exception as e:
        st.error(f"DB 로드 중 오류: {e}")
        return pd.DataFrame(columns=HOLDINGS_COLUMNS + ["account_type"])

def load_holdings_db():
    return load_holdings_db_for_user(PUBLIC_DEMO_EMAIL if IS_PUBLIC_DEMO else CURRENT_USER_EMAIL)

def _normalize_kr_ticker_suffix(ticker: str) -> str:
    """6자리 영숫자 KR 코드에 .KS 접미사가 없으면 자동으로 추가.
    예: 0117V0 → 0117V0.KS, 069500 → 069500.KS
    """
    t = str(ticker or "").strip().upper()
    if not t or t.endswith((".KS", ".KQ")):
        return t
    if len(t) == 6 and t[0].isdigit() and t.isalnum():
        return t + ".KS"
    return t


def save_holdings_db(df):
    if IS_PUBLIC_DEMO:
        return public_demo_write_blocked("보유 종목 저장")

    rows = []
    row_keys = []
    for _, row in df.iterrows():
        ticker_value = sanitize_ticker_value(row.get("ticker", ""))
        ticker_value = _normalize_kr_ticker_suffix(ticker_value)
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
            "account_type": str(row.get("account_type", "일반")).strip() or "일반",
        })
        row_keys.append(f"{normalize_ticker(ticker_value)}|{normalize_text(rows[-1].get('account_type', '일반'))}")

    if not rows:
        st.warning("No holdings rows to save. Existing holdings were kept unchanged.")
        return False

    duplicate_keys = sorted({key for key in row_keys if row_keys.count(key) > 1})
    if duplicate_keys:
        duplicate_labels = [key.replace("|", " / ") for key in duplicate_keys]
        st.error(
            "같은 계좌 안에 같은 티커가 여러 줄 있습니다. 기존 데이터 보호를 위해 저장하지 않았습니다. "
            f"티커와 계좌 조합을 한 줄만 남겨 주세요: {', '.join(duplicate_labels)}"
        )
        return False

    existing_res = run_supabase(
        supabase.table("holdings").select("ticker,account_type").eq("owner_email", CURRENT_USER_EMAIL),
        "load existing holdings before save",
    )
    existing_holdings = [
        (
            sanitize_ticker_value(row.get("ticker", "")),
            str(row.get("account_type", "일반")).strip() or "일반",
        )
        for row in (existing_res.data or [])
        if sanitize_ticker_value(row.get("ticker", ""))
    ]

    run_supabase(
        supabase.table("holdings").upsert(rows, on_conflict="owner_email,ticker,account_type"),
        "upsert holdings",
    )

    new_keys = {
        f"{normalize_ticker(row['ticker'])}|{normalize_text(row.get('account_type', '일반'))}"
        for row in rows
    }
    removed_holdings = [
        (ticker, account_type)
        for ticker, account_type in existing_holdings
        if f"{normalize_ticker(ticker)}|{normalize_text(account_type)}" not in new_keys
    ]
    failed_deletes = []
    for ticker, account_type in removed_holdings:
        res = run_supabase(
            supabase.table("holdings").delete().eq("owner_email", CURRENT_USER_EMAIL).eq("ticker", ticker).eq("account_type", account_type),
            f"delete removed holding {ticker}/{account_type}",
            stop_on_error=False,
        )
        if res is None:
            failed_deletes.append(f"{ticker}({account_type})")

    if failed_deletes:
        st.warning(
            "일부 삭제된 보유자산 행을 지우지 못했습니다. 표를 확인한 뒤 다시 저장해 주세요: "
            f"{', '.join(failed_deletes)}"
        )

    load_holdings_db_for_user.clear()
    return True


@st.cache_data(ttl=30, show_spinner=False)
def load_dividends_db_for_user(owner_email):
    if IS_PUBLIC_DEMO:
        return get_public_demo_dividends_df()

    res = run_supabase(
        supabase.table("dividends").select(",".join(DIVIDENDS_COLUMNS)).eq("owner_email", owner_email),
        "load dividends",
    )
    rows = sorted(res.data or [], key=lambda r: (str(r.get("date") or ""), int(r.get("id") or 0)), reverse=True)
    return dataframe_from_rows(rows, DIVIDENDS_COLUMNS)


def load_dividends_db():
    return load_dividends_db_for_user(PUBLIC_DEMO_EMAIL if IS_PUBLIC_DEMO else CURRENT_USER_EMAIL)


def save_dividends_db(df):
    if IS_PUBLIC_DEMO:
        return public_demo_write_blocked("배당 내역 저장")

    existing_res = run_supabase(
        supabase.table("dividends").select("id").eq("owner_email", CURRENT_USER_EMAIL),
        "load existing dividends before save",
    )
    existing_ids = {
        clean_int(row.get("id"))
        for row in (existing_res.data or [])
        if clean_int(row.get("id")) is not None
    }

    rows_to_upsert = []
    rows_to_insert = []
    kept_existing_ids = []
    for _, row in df.iterrows():
        if not str(row.get("date", "")).strip() and not str(row.get("ticker", "")).strip():
            continue

        item = {
            "owner_email": CURRENT_USER_EMAIL,
            "date": str(row.get("date", "")).strip(),
            "ticker": sanitize_ticker_value(row.get("ticker", "")),
            "amount": clean_float(row.get("amount")),
            "currency": str(row.get("currency", "KRW")).strip().upper() or "KRW",
        }

        row_id = clean_int(row.get("id"))
        if row_id in existing_ids:
            item["id"] = row_id
            rows_to_upsert.append(item)
            kept_existing_ids.append(row_id)
        else:
            rows_to_insert.append(item)

    if not rows_to_upsert and not rows_to_insert:
        st.warning("No dividend rows to save. Existing dividends were kept unchanged.")
        return False

    duplicate_ids = sorted({row_id for row_id in kept_existing_ids if kept_existing_ids.count(row_id) > 1})
    if duplicate_ids:
        st.error(
            "배당 내역에 같은 id가 여러 줄 있습니다. 기존 데이터 보호를 위해 저장하지 않았습니다. "
            f"id를 확인해 주세요: {', '.join(str(x) for x in duplicate_ids)}"
        )
        return False

    if rows_to_upsert:
        run_supabase(
            supabase.table("dividends").upsert(rows_to_upsert, on_conflict="id"),
            "upsert dividends",
        )

    if rows_to_insert:
        run_supabase(supabase.table("dividends").insert(rows_to_insert), "insert new dividends")

    failed_deletes = []
    kept_ids = set(kept_existing_ids)
    for row_id in existing_ids:
        if row_id in kept_ids:
            continue
        res = run_supabase(
            supabase.table("dividends").delete().eq("owner_email", CURRENT_USER_EMAIL).eq("id", row_id),
            f"delete removed dividend {row_id}",
            stop_on_error=False,
        )
        if res is None:
            failed_deletes.append(row_id)

    if failed_deletes:
        st.warning(
            "일부 삭제된 배당 내역을 지우지 못했습니다. 목록을 확인한 뒤 다시 저장해 주세요. "
            f"{', '.join(str(x) for x in failed_deletes)}"
        )

    load_dividends_db_for_user.clear()
    return True


@st.cache_data(ttl=30, show_spinner=False)
def load_monthly_logs_db_for_user(owner_email):
    if IS_PUBLIC_DEMO:
        return get_public_demo_monthly_logs_df()

    res = run_supabase(
        supabase.table("monthly_logs").select(",".join(MONTHLY_LOG_COLUMNS)).eq("owner_email", owner_email),
        "load monthly logs",
    )
    rows = sorted(res.data or [], key=lambda r: str(r.get("month") or ""))
    return dataframe_from_rows(rows, MONTHLY_LOG_COLUMNS)


def load_monthly_logs_db():
    return load_monthly_logs_db_for_user(PUBLIC_DEMO_EMAIL if IS_PUBLIC_DEMO else CURRENT_USER_EMAIL)


def save_monthly_logs_db(df):
    if IS_PUBLIC_DEMO:
        return public_demo_write_blocked("월별 로그 저장")

    rows = []
    row_keys = []
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
        row_keys.append(month)

    if not rows:
        st.warning("No monthly log rows to save. Existing monthly logs were kept unchanged.")
        return False

    duplicate_months = sorted({key for key in row_keys if row_keys.count(key) > 1})
    if duplicate_months:
        st.error(
            "월별 로그에 같은 월이 여러 줄 있습니다. 기존 데이터 보호를 위해 저장하지 않았습니다. "
            f"월별로 한 줄만 남겨 주세요: {', '.join(duplicate_months)}"
        )
        return False

    existing_res = run_supabase(
        supabase.table("monthly_logs").select("month").eq("owner_email", CURRENT_USER_EMAIL),
        "load existing monthly logs before save",
    )
    existing_months = [
        str(row.get("month", "")).strip()
        for row in (existing_res.data or [])
        if str(row.get("month", "")).strip()
    ]

    run_supabase(
        supabase.table("monthly_logs").upsert(rows, on_conflict="owner_email,month"),
        "upsert monthly logs",
    )

    new_months = {row["month"] for row in rows}
    failed_deletes = []
    for month in existing_months:
        if month in new_months:
            continue
        res = run_supabase(
            supabase.table("monthly_logs").delete().eq("owner_email", CURRENT_USER_EMAIL).eq("month", month),
            f"delete removed monthly log {month}",
            stop_on_error=False,
        )
        if res is None:
            failed_deletes.append(month)

    if failed_deletes:
        st.warning(
            "일부 삭제된 월별 로그를 지우지 못했습니다. 목록을 확인한 뒤 다시 저장해 주세요. "
            f"{', '.join(failed_deletes)}"
        )

    load_monthly_logs_db_for_user.clear()
    return True


@st.cache_data(ttl=30, show_spinner=False)
def load_fin_scores_db_for_user(owner_email):
    if IS_PUBLIC_DEMO:
        return pd.DataFrame(columns=FIN_SCORE_COLUMNS)

    res = run_supabase(
        supabase.table("fin_scores").select(",".join(FIN_SCORE_COLUMNS)).eq("owner_email", owner_email),
        "load financial scores",
    )
    return dataframe_from_rows(res.data, FIN_SCORE_COLUMNS)


def load_fin_scores_db():
    return load_fin_scores_db_for_user(PUBLIC_DEMO_EMAIL if IS_PUBLIC_DEMO else CURRENT_USER_EMAIL)


@st.cache_data(ttl=30, show_spinner=False)
def load_watchlist_db_for_user(owner_email):
    if IS_PUBLIC_DEMO:
        return []

    res = run_supabase(
        supabase.table("watchlist").select("name,ticker,is_etf,asset_class,sort_order,fin_score").eq("owner_email", owner_email),
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


def load_watchlist_db():
    return load_watchlist_db_for_user(PUBLIC_DEMO_EMAIL if IS_PUBLIC_DEMO else CURRENT_USER_EMAIL)


def save_watchlist_db(watchlist):
    if IS_PUBLIC_DEMO:
        return False

    rows = []
    row_keys = []
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
        row_keys.append(normalize_ticker(ticker))

    if not rows:
        st.warning("No watchlist rows to save. Existing watchlist was kept unchanged.")
        return False

    duplicate_keys = sorted({key for key in row_keys if row_keys.count(key) > 1})
    if duplicate_keys:
        st.error(
            "관심목록에 같은 티커가 여러 번 들어 있습니다. 기존 데이터 보호를 위해 저장하지 않았습니다. "
            f"티커당 한 줄만 남겨 주세요: {', '.join(duplicate_keys)}"
        )
        return False

    existing_res = run_supabase(
        supabase.table("watchlist").select("ticker").eq("owner_email", CURRENT_USER_EMAIL),
        "load existing watchlist before save",
    )
    existing_tickers = [
        sanitize_ticker_value(row.get("ticker", ""))
        for row in (existing_res.data or [])
        if sanitize_ticker_value(row.get("ticker", ""))
    ]

    run_supabase(
        supabase.table("watchlist").upsert(rows, on_conflict="owner_email,ticker"),
        "upsert watchlist",
    )

    new_keys = {normalize_ticker(row["ticker"]) for row in rows}
    failed_deletes = []
    for ticker in existing_tickers:
        if normalize_ticker(ticker) in new_keys:
            continue
        res = run_supabase(
            supabase.table("watchlist").delete().eq("owner_email", CURRENT_USER_EMAIL).eq("ticker", ticker),
            f"delete removed watchlist item {ticker}",
            stop_on_error=False,
        )
        if res is None:
            failed_deletes.append(ticker)

    if failed_deletes:
        st.warning(
            "일부 제거된 관심종목을 지우지 못했습니다. 목록을 확인한 뒤 다시 저장해 주세요: "
            f"{', '.join(failed_deletes)}"
        )

    load_watchlist_db_for_user.clear()
    return True


def load_watchlist_persistent():
    if IS_PUBLIC_DEMO:
        return get_public_demo_watchlist()

    db_items = load_watchlist_db()
    if db_items:
        return db_items

    query_items = load_watchlist_from_query()
    save_watchlist_db(query_items)
    return query_items


def persist_watchlist():
    if IS_PUBLIC_DEMO:
        return False

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

alter table swing_radar enable row level security;

drop policy if exists swing_radar_owner_select on swing_radar;
drop policy if exists swing_radar_owner_insert on swing_radar;
drop policy if exists swing_radar_owner_update on swing_radar;
drop policy if exists swing_radar_owner_delete on swing_radar;

create policy swing_radar_owner_select
on swing_radar for select
using (owner_email = coalesce(auth.jwt() ->> 'email', ''));

create policy swing_radar_owner_insert
on swing_radar for insert
with check (owner_email = coalesce(auth.jwt() ->> 'email', ''));

create policy swing_radar_owner_update
on swing_radar for update
using (owner_email = coalesce(auth.jwt() ->> 'email', ''))
with check (owner_email = coalesce(auth.jwt() ->> 'email', ''));

create policy swing_radar_owner_delete
on swing_radar for delete
using (owner_email = coalesce(auth.jwt() ->> 'email', ''));
""".strip()


def load_swing_radar_db_safe():
    if IS_PUBLIC_DEMO:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS), None

    try:
        res = supabase.table("swing_radar").select(",".join(SWING_RADAR_COLUMNS)).eq("owner_email", CURRENT_USER_EMAIL).execute()
        return dataframe_from_rows(res.data, SWING_RADAR_COLUMNS), None
    except Exception as e:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS), str(e)


def save_swing_radar_db_safe(df):
    if IS_PUBLIC_DEMO:
        return False, "체험모드에서는 스윙 레이더를 저장하지 않습니다."

    try:
        rows = []
        row_keys = []
        for _, row in df.iterrows():
            ticker = sanitize_ticker_value(row.get("ticker", ""))
            if not ticker:
                continue

            item = {"owner_email": CURRENT_USER_EMAIL, "ticker": ticker}
            for col in SWING_RADAR_COLUMNS:
                if col == "ticker":
                    continue
                value = row.get(col, "")
                item[col] = "" if value is None or pd.isna(value) else str(value).strip()
            rows.append(item)
            row_keys.append(normalize_ticker(ticker))

        if not rows:
            return False, "저장할 스윙 레이더 행이 없습니다."

        duplicate_keys = sorted({key for key in row_keys if row_keys.count(key) > 1})
        if duplicate_keys:
            return False, f"스윙 레이더에 같은 티커가 여러 줄 있습니다: {', '.join(duplicate_keys)}"

        existing_res = (
            supabase.table("swing_radar")
            .select("ticker")
            .eq("owner_email", CURRENT_USER_EMAIL)
            .execute()
        )
        existing_tickers = [
            sanitize_ticker_value(row.get("ticker", ""))
            for row in (existing_res.data or [])
            if sanitize_ticker_value(row.get("ticker", ""))
        ]

        supabase.table("swing_radar").upsert(rows, on_conflict="owner_email,ticker").execute()

        new_keys = {normalize_ticker(row["ticker"]) for row in rows}
        failed_deletes = []
        for ticker in existing_tickers:
            if normalize_ticker(ticker) in new_keys:
                continue
            try:
                (
                    supabase.table("swing_radar")
                    .delete()
                    .eq("owner_email", CURRENT_USER_EMAIL)
                    .eq("ticker", ticker)
                    .execute()
                )
            except Exception:
                failed_deletes.append(ticker)

        if failed_deletes:
            st.warning(
                "일부 삭제된 스윙 후보를 지우지 못했습니다. 다시 저장해 주세요. "
                f"{', '.join(failed_deletes)}"
            )
            return True, f"일부 삭제된 스윙 후보를 지우지 못했습니다. 다시 저장해 주세요: {', '.join(failed_deletes)}"

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

alter table feedback enable row level security;

drop policy if exists feedback_owner_select on feedback;
drop policy if exists feedback_owner_insert on feedback;
drop policy if exists feedback_owner_update on feedback;
drop policy if exists feedback_owner_delete on feedback;

create policy feedback_owner_select
on feedback for select
using (owner_email = coalesce(auth.jwt() ->> 'email', ''));

create policy feedback_owner_insert
on feedback for insert
with check (owner_email = coalesce(auth.jwt() ->> 'email', ''));

create policy feedback_owner_update
on feedback for update
using (owner_email = coalesce(auth.jwt() ->> 'email', ''))
with check (owner_email = coalesce(auth.jwt() ->> 'email', ''));

create policy feedback_owner_delete
on feedback for delete
using (owner_email = coalesce(auth.jwt() ->> 'email', ''));
""".strip()


def is_admin_user():
    if IS_PUBLIC_DEMO:
        return False
    return normalize_text(CURRENT_USER_EMAIL) in get_secret_emails("ADMIN_EMAILS")


def load_feedback_db_safe(limit=200):
    if IS_PUBLIC_DEMO:
        return dataframe_from_rows([], FEEDBACK_COLUMNS), None

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
        client = supabase
        if IS_PUBLIC_DEMO:
            client, config_error = get_supabase_for_feedback()
            if client is None:
                return False, f"체험모드 피드백 저장용 Supabase Secrets가 필요합니다: {config_error}"

        payload = {
            "owner_email": PUBLIC_DEMO_EMAIL if IS_PUBLIC_DEMO else CURRENT_USER_EMAIL,
            "category": str(category or "개선 제안").strip(),
            "title": str(title or "").strip(),
            "body": str(body or "").strip(),
            "priority": str(priority or "보통").strip(),
            "status": "접수",
        }
        client.table("feedback").insert(payload).execute()
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

        if kind == "holdings":
            unique_column = ["ticker", "account_type"]

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
    if IS_PUBLIC_DEMO:
        return [], ["체험모드에서는 CSV 복구를 실행하지 않습니다."]

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
    if IS_PUBLIC_DEMO:
        return False

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
    if res is not None:
        load_fin_scores_db_for_user.clear()
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
    if IS_PUBLIC_DEMO:
        return False

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
    load_fin_scores_db_for_user.clear()


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
    "LITE", "PANW", "HACK", "NFLX", "UBER", "ABNB",
}

def get_dart_api_key():
    return get_secret_value("dart_api_key")

def get_krx_api_key():
    return get_secret_value("krx_api_key")

def get_sec_user_agent():
    return get_secret_value("sec_user_agent")

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_dart_corp_code_map():
    api_key = get_dart_api_key()
    if not api_key:
        return {}

    url = "https://opendart.fss.or.kr/api/corpCode.xml"

    try:
        res = requests.get(url, params={"crtfc_key": api_key}, timeout=8)
        res.raise_for_status()

        zf = zipfile.ZipFile(io.BytesIO(res.content))
        xml_name = zf.namelist()[0]
        root = ET.fromstring(zf.read(xml_name))
    except Exception:
        return {}

    code_map = {}
    for item in root.findall("list"):
        corp_code = (item.findtext("corp_code") or "").strip()
        stock_code = (item.findtext("stock_code") or "").strip()

        if corp_code and stock_code:
            code_map[stock_code] = corp_code

    return code_map

def get_dart_corp_code(stock_code):
    stock_code = normalize_stock_code(stock_code)
    try:
        code_map = fetch_dart_corp_code_map()
    except Exception:
        return None
    return code_map.get(stock_code)

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_dart_disclosures(corp_code: str, days: int = 30) -> list:
    """최근 N일 내 DART 공시 목록 (최대 15건)."""
    import requests as _req
    from datetime import date as _date, timedelta as _td
    api_key = get_dart_api_key()
    if not api_key or not corp_code:
        return []
    bgn_de = (_date.today() - _td(days=days)).strftime("%Y%m%d")
    try:
        r = _req.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "page_count": 15,
                "sort": "date",
                "sort_mth": "desc",
            },
            timeout=8,
        )
        data = r.json()
        return data.get("list", [])[:15] if data.get("status") == "000" else []
    except Exception:
        return []


def _rebcalc_signal_multiplier(tap: str, bucket: str, dip_level: int = 0) -> float:
    """기술적타점 문자열 → 배분 배율
    버킷별 로직:
      core    : 신호없음=1.0(DCA), 매수=1.0, 과열=0.25, 차단=0.0
      leverage: 구조훼손=0.0, 과열=0.0, 신호없음=0.5(DCA유지),
                매수=1.5, 매수+약하락(dip1)=1.5, 매수+중하락(dip2)=1.75, 매수+강하락(dip3)=2.0
                대기/신호없음+약하락=0.75, +중하락=1.0, +강하락=1.25
      swing   : 명시적 매수 신호 없으면 0.0
    dip_level: 0=정상, 1=-5%~-10%(약하락), 2=-10%~-15%(중하락), 3=-15%↓(강하락)
    """
    tap = str(tap).strip()
    bucket = str(bucket).strip().lower()
    is_empty = tap in ("-", "", "nan", "none", "None")
    is_buy   = any(k in tap for k in ["매수", "분할", "추매", "🟢", "✅", "🟣"]) or ("진입" in tap and "보류" not in tap)
    is_hot   = any(k in tap for k in ["과열", "주의", "⚠"])
    is_hard  = any(k in tap for k in ["하드", "차단", "구조", "🔴", "⛔"])
    is_wait  = any(k in tap for k in ["평단", "하락", "대기", "⏸"])

    # ── 레버리지 버킷 (QLD, TQQQ 등) ────────────────────────────────────────
    if bucket == "leverage":
        if is_hard: return 0.0   # 구조 훼손 → 완전 중단
        if is_hot:  return 0.0   # 과열 → 진입 금물
        if is_buy:
            # 매수 신호: 하락 깊이에 따라 배율 상향
            if dip_level >= 3: return 2.0    # 매수 + 강하락(-15%↓) → 2배 집중
            if dip_level == 2: return 1.75   # 매수 + 중하락(-10%~-15%) → 1.75배
            return 1.5                       # 매수 + 약하락 or 정상 → 1.5배
        if is_wait or is_empty:
            # 신호없음/대기: 하락 깊이에 따라 DCA 강도 조절
            if dip_level >= 3: return 1.25   # 강하락 → 1.25배 DCA
            if dip_level == 2: return 1.0    # 중하락 → 1배 DCA
            if dip_level == 1: return 0.75   # 약하락 → 0.75배 DCA
        return 0.5                           # 그외 (정상 구간) → 0.5배 DCA

    # ── 코어 버킷 ────────────────────────────────────────────────────────────
    if tap in ("-", "", "nan", "none", "None"):
        return 1.0 if bucket == "core" else 0.0
    if is_buy:  return 1.0
    if is_hot:  return 0.25
    if is_hard: return 0.0
    if is_wait: return 0.0

    # 스윙은 명시적 매수 신호 없으면 0%
    if bucket == "swing":
        return 0.0

    # 코어: 보유/중립 → 50%
    return 0.5


def render_monthly_rebalancing_calculator(holdings_table, usdkrw, portfolio_summary, monthly_logs_df=None):
    """월 적립 리밸런싱 계산기 (자산 현황 탭 내 expander)"""
    import datetime as _dt

    # ── 이번 달 기준 키 (월이 바뀌면 자동으로 새 상태 사용) ──────────────────
    _this_month = _dt.date.today().strftime("%Y-%m")
    _done_key   = f"rebcalc_done_{_this_month}"   # 월별 완료 체크

    # ── session_state 초기화 ──────────────────────────────────────────────────
    if "rebcalc_monthly" not in st.session_state:
        st.session_state["rebcalc_monthly"] = 750000
    if "rebcalc_carryover" not in st.session_state:
        st.session_state["rebcalc_carryover"] = 0
    if "rebcalc_redistribute" not in st.session_state:
        st.session_state["rebcalc_redistribute"] = True
    if _done_key not in st.session_state:
        st.session_state[_done_key] = {}
    # 종목별 적립 누적금 (1주 미달 시 매달 쌓아두는 금액, 월 스코프 없이 영구 보관)
    if "rebcalc_accum" not in st.session_state:
        st.session_state["rebcalc_accum"] = {}   # {ticker: accumulated_krw}
    # 항상 투자 종목 (신호 무관 · 과열/차단 무시하고 배율 1.0 고정)
    if "rebcalc_always_invest" not in st.session_state:
        st.session_state["rebcalc_always_invest"] = []

    # 대시보드 "분석 실행" 버튼을 눌렀을 때 캐시된 신호 맵 읽기
    _signal_cache = st.session_state.get("_ticker_signal_cache", {})
    _has_signals  = bool(_signal_cache)

    with st.expander("💰 월 적립 리밸런싱 계산기", expanded=False):

        # 신호 캐시 상태 안내
        if not _has_signals:
            st.info(
                "⚠️ 기술적 타점 신호가 아직 로드되지 않았습니다. "
                "아래 포트폴리오 섹션의 **'분석 실행/새로고침'** 버튼을 눌러주세요. "
                "그 다음부터는 대시보드와 동일한 신호가 표시됩니다."
            )
        else:
            st.caption(
                f"**{_this_month}** 기준 · 신호는 대시보드 분석 기준과 동일 · "
                "🟢 투자=신호OK · ⚠️ 25%=과열주의 · ⛔ 차단 / ⏸ 대기·스윙 = 이번달 제외"
            )

        # ── 입력 영역 ──────────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        monthly = c1.number_input(
            "이번 달 적립금 (원)", min_value=0, step=50000,
            value=st.session_state["rebcalc_monthly"], key="rebcalc_monthly_inp",
        )
        carryover = c2.number_input(
            "이월 누적금 (원)", min_value=0, step=10000,
            value=st.session_state["rebcalc_carryover"], key="rebcalc_carryover_inp",
        )
        st.session_state["rebcalc_monthly"] = monthly
        st.session_state["rebcalc_carryover"] = carryover
        total_invest = monthly + carryover
        c3.metric("총 투자 가능금", f"{total_invest:,.0f}원")
        redistribute_mode = c4.checkbox(
            "미투자금 자동 재분배", value=st.session_state["rebcalc_redistribute"],
            key="rebcalc_redist_chk",
            help="차단·대기 종목에 배분됐을 금액을 투자 가능 종목에 비중대로 추가 배분합니다.",
        )
        st.session_state["rebcalc_redistribute"] = redistribute_mode

        if holdings_table is None or holdings_table.empty or total_invest <= 0:
            st.info("적립금을 입력하면 계산이 시작됩니다.")
            return

        # ── 투자 대상 필터링 ───────────────────────────────────────────────────
        df = holdings_table.copy()
        excl_buckets = {"reserve", "cash"}
        eligible = df[~df["bucket"].apply(lambda b: normalize_bucket(str(b)) in excl_buckets)].copy()
        eligible = eligible[eligible["목표비중"].apply(lambda v: clean_float(v, 0.0)) > 0]
        if "운용대상" in eligible.columns:
            eligible = eligible[eligible["운용대상"].apply(clean_bool)]

        if eligible.empty:
            st.info("리밸런싱 대상 종목이 없습니다. (목표비중 > 0, reserve/cash 제외)")
            return

        target_w_sum = float(eligible["목표비중"].apply(lambda v: clean_float(v, 0.0)).sum())
        if target_w_sum <= 0:
            st.warning("목표비중 합계가 0입니다.")
            return

        # ── 항상 투자 종목 선택 (신호 무관 · 배율 1.0 고정) ──────────────────
        _eligible_ticker_map = {
            str(row.get("티커", "")): str(row.get("자산명", row.get("티커", "")))
            for _, row in eligible.iterrows()
            if str(row.get("티커", ""))
        }
        _prev_always = [t for t in st.session_state["rebcalc_always_invest"] if t in _eligible_ticker_map]
        always_invest_list = st.multiselect(
            "📌 항상 투자 종목 — 신호 무관하게 매달 100% 배분 (나스닥·S&P500 등 지수 ETF 권장)",
            options=list(_eligible_ticker_map.keys()),
            default=_prev_always,
            format_func=lambda t: f"{_eligible_ticker_map.get(t, t)} ({t})",
            key="rebcalc_always_invest_sel",
        )
        st.session_state["rebcalc_always_invest"] = always_invest_list
        always_invest_set = set(always_invest_list)

        # ── 1차 계산: 기본 배분 + 타점 배율 ──────────────────────────────────
        calc_rows = []
        for _, row in eligible.iterrows():
            ticker   = str(row.get("티커", ""))
            name     = str(row.get("자산명", ""))
            target_w = clean_float(row.get("목표비중"), 0.0)
            bucket   = normalize_bucket(str(row.get("bucket", "core")))
            cur_p    = clean_float(row.get("현재가"), 0.0)
            avg_p    = clean_float(row.get("매입가"), 0.0)
            qty      = clean_float(row.get("보유량"), 0.0)
            is_usd   = not ticker.upper().endswith((".KS", ".KQ")) and ticker not in ("KRW_CASH", "USD_CASH")
            asset_is_etf = (
                clean_bool(row.get("is_etf", False))
                or is_known_etf_ticker(ticker)
            )

            # 신호: 캐시에서 먼저 조회 (= 대시보드 분석과 동일 값), 없으면 holdings_table 값
            tap_raw = str(_signal_cache.get(ticker, row.get("기술적타점", "-"))).strip()

            # 표시용 레이블: 빈 신호일 때 ETF/레버리지/일반 구분
            if tap_raw in ("-", "", "nan", "None", "none"):
                if bucket == "leverage":
                    tap_disp = "레버리지 (신호없음)"
                elif asset_is_etf:
                    tap_disp = "ETF (신호없음)"
                else:
                    tap_disp = "신호없음"
            else:
                tap_disp = tap_raw

            # 레버리지 하락 감지: 평단 대비 하락 깊이를 3단계로 분류
            # 일상 변동(-2%~-5%)은 노이즈 → -5% 이상부터 의미있는 하락으로 처리
            if bucket == "leverage" and avg_p > 0:
                pct_drop = (cur_p - avg_p) / avg_p   # 음수 = 하락
                if pct_drop <= -0.15:
                    dip_level = 3   # 강하락 -15%↓
                elif pct_drop <= -0.10:
                    dip_level = 2   # 중하락 -10%~-15%
                elif pct_drop <= -0.05:
                    dip_level = 1   # 약하락 -5%~-10%
                else:
                    dip_level = 0   # 정상 (평단 -5% 이내)
            else:
                dip_level = 0
            is_dip = dip_level > 0   # 표시용 플래그 유지

            base_alloc = total_invest * (target_w / target_w_sum)
            multiplier = _rebcalc_signal_multiplier(tap_raw, bucket, dip_level=dip_level)
            if ticker in always_invest_set:
                multiplier = 1.0
                tap_disp = f"📌 항상투자" if tap_disp in ("-", "신호없음", "ETF (신호없음)") else f"{tap_disp} → 📌무시"
            eff_alloc  = base_alloc * multiplier

            calc_rows.append({
                "ticker": ticker, "name": name, "bucket": bucket,
                "target_w": target_w, "tap_raw": tap_raw, "tap_disp": tap_disp,
                "is_etf": asset_is_etf, "is_dip": is_dip, "dip_level": dip_level,
                "avg_p": avg_p,
                "base_alloc": base_alloc, "multiplier": multiplier,
                "eff_alloc": eff_alloc,
                "cur_p": cur_p, "is_usd": is_usd, "qty": qty,
            })

        # ── 2차: 재분배 모드 처리 ─────────────────────────────────────────────
        blocked_total = sum(r["base_alloc"] for r in calc_rows if r["multiplier"] == 0)
        investable    = [r for r in calc_rows if r["multiplier"] > 0]
        inv_w_sum     = sum(r["target_w"] for r in investable) or 1

        for r in calc_rows:
            if r["multiplier"] == 0:
                r["final_alloc"] = 0.0
            elif redistribute_mode:
                bonus = blocked_total * (r["target_w"] / inv_w_sum)
                r["final_alloc"] = r["eff_alloc"] + bonus
            else:
                r["final_alloc"] = r["eff_alloc"]

        # 레버리지 1.5x/2.0x 등으로 합계가 total_invest 초과 시 비례 정규화
        total_final = sum(r["final_alloc"] for r in calc_rows)
        if total_final > total_invest * 1.005:   # 0.5% 허용 오차
            _scale = total_invest / total_final
            for r in calc_rows:
                r["final_alloc"] *= _scale

        # ── 3차: 권장 주수 계산 + 1주 미달 감지 ─────────────────────────────
        _accum = dict(st.session_state["rebcalc_accum"])   # 종목별 누적금 읽기
        for r in calc_rows:
            alloc  = r["final_alloc"]
            cur_p  = r["cur_p"]
            is_usd = r["is_usd"]
            ticker = r["ticker"]

            # 기존 적립 누적금 포함한 실질 배분 가능금
            accumulated_krw = _accum.get(ticker, 0.0)
            effective_alloc = alloc + accumulated_krw   # 누적금 포함

            if is_usd:
                alloc_usd       = alloc / usdkrw if usdkrw > 0 else 0
                eff_alloc_usd   = effective_alloc / usdkrw if usdkrw > 0 else 0
                rec_shares      = int(eff_alloc_usd / cur_p) if cur_p > 0 else 0
                rec_krw         = rec_shares * cur_p * usdkrw
                unit_price_krw  = cur_p * usdkrw           # 1주 원화 환산가
                r["alloc_disp"] = f"${alloc_usd:,.2f}" + (f" (+누적${accumulated_krw/usdkrw:,.2f})" if accumulated_krw > 0 else "")
            else:
                rec_shares      = int(effective_alloc / cur_p) if cur_p > 0 else 0
                rec_krw         = rec_shares * cur_p
                unit_price_krw  = cur_p
                r["alloc_disp"] = f"{alloc:,.0f}원" + (f" (+누적{accumulated_krw:,.0f}원)" if accumulated_krw > 0 else "")
            r["rec_shares"]        = rec_shares
            r["rec_krw"]           = rec_krw
            r["accumulated_krw"]   = accumulated_krw
            r["effective_alloc"]   = effective_alloc
            r["unit_price_krw"]    = unit_price_krw

            # 1주 미달 판정: 투자 신호가 있는데 누적 포함해도 1주를 못 살 때
            r["is_underalloc"] = (r["multiplier"] > 0 and cur_p > 0 and rec_shares == 0)

            # 상태 레이블
            tap   = r["tap_raw"]
            mult  = r["multiplier"]
            bkt   = r["bucket"]

            if mult == 0:
                if any(k in tap for k in ["하드", "차단", "구조", "🔴", "⛔"]):
                    r["status"] = "⛔ 구조훼손" if bkt == "leverage" else "⛔ 차단"
                elif bkt == "leverage" and any(k in tap for k in ["과열", "주의", "⚠"]):
                    r["status"] = "🌡️ 과열패스"   # 레버리지 과열은 완전 중단
                elif any(k in tap for k in ["평단", "하락", "대기", "⏸"]):
                    r["status"] = "⏸ 대기"
                elif bkt == "swing":
                    r["status"] = "⏸ 스윙대기"
                else:
                    r["status"] = "⏸ 제외"
            elif r["is_underalloc"]:
                alloc_for_months = r["final_alloc"]
                months_at_eff = (
                    math.ceil((unit_price_krw - accumulated_krw) / alloc_for_months)
                    if alloc_for_months > 0 else 99
                )
                r["months_to_buy"] = months_at_eff
                r["status"] = f"🟡 적립중 (~{months_at_eff}달 후)"
            elif bkt == "leverage":
                if mult >= 2.0:
                    r["status"] = "📉📉📉🚀 강하락+집중매수"
                elif mult >= 1.75:
                    r["status"] = "📉📉🚀 중하락+집중매수"
                elif mult >= 1.5:
                    r["status"] = "🚀 레버리지 진입"
                elif mult >= 1.25:
                    r["status"] = "📉📉 강하락 DCA"
                elif mult >= 1.0:
                    r["status"] = "📉 중하락 DCA"
                elif mult >= 0.75:
                    r["status"] = "〰️ 약하락 DCA"
                else:
                    r["status"] = "〰️ 레버리지 DCA"
            elif mult < 1.0:
                r["status"] = f"⚠️ {int(mult*100)}%"
            else:
                r["status"] = "🟢 투자"

        # 구매 가능해진 종목의 누적금을 구매 후 잔여분으로 자동 정리
        # (accumulated_krw가 쌓여서 rec_shares > 0이 된 경우, 소진 후 남은 금액만 유지)
        _accum_refresh = dict(st.session_state["rebcalc_accum"])
        _accum_refresh_changed = False
        for r in calc_rows:
            if r.get("accumulated_krw", 0) > 0 and r.get("rec_shares", 0) > 0:
                leftover = max(0.0, r["effective_alloc"] - r["rec_krw"])
                _accum_refresh[r["ticker"]] = leftover
                _accum_refresh_changed = True
        if _accum_refresh_changed:
            st.session_state["rebcalc_accum"] = _accum_refresh

        active_rows      = [r for r in calc_rows if r["multiplier"] > 0]
        blocked_rows     = [r for r in calc_rows if r["multiplier"] == 0]
        swing_rows       = [r for r in blocked_rows if r["bucket"] == "swing"]
        leverage_rows    = [r for r in calc_rows if r["bucket"] == "leverage"]
        lev_active       = [r for r in leverage_rows if r["multiplier"] > 0]
        lev_blocked      = [r for r in leverage_rows if r["multiplier"] == 0]
        underalloc_rows  = [r for r in active_rows if r["is_underalloc"]]
        buyable_rows     = [r for r in active_rows if not r["is_underalloc"]]

        # ── 📋 이번달 배분 계획 ───────────────────────────────────────────────
        st.markdown("#### 📋 이번달 배분 계획")
        table_rows = []
        for r in calc_rows:
            shares_disp = (
                str(r["rec_shares"]) if r["multiplier"] > 0 and r["rec_shares"] > 0
                else ("-" if r["multiplier"] == 0 else "0주")
            )
            # 레버리지 배율 표시 추가
            if r["bucket"] == "leverage" and r["multiplier"] > 0:
                mult_badge = f" ×{r['multiplier']:.1f}"
            else:
                mult_badge = ""
            # 하락 감지 표시
            dip_badge = " 📉" if r.get("is_dip") else ""
            table_rows.append({
                "자산명":     r["name"] + dip_badge,
                "버킷":       r["bucket"],
                "목표비중":   f"{r['target_w']:.1f}%",
                "기술적타점": r["tap_disp"],
                "배분금액":   (r["alloc_disp"] + mult_badge) if r["multiplier"] > 0 else "-",
                "권장주수":   shares_disp,
                "상태":       r["status"],
            })
        # 정렬: 레버리지 투자 → 일반 투자 → 레버리지 패스 → 일반 차단
        def _sort_key(pair):
            _, r = pair
            if r["bucket"] == "leverage" and r["multiplier"] > 0: return 0
            if r["multiplier"] > 0:                                return 1
            if r["bucket"] == "leverage":                          return 2
            return 3
        sorted_pairs = sorted(zip(table_rows, calc_rows), key=_sort_key)
        st.dataframe(pd.DataFrame([t for t, _ in sorted_pairs]), use_container_width=True, hide_index=True)

        total_rec_krw     = sum(r["rec_krw"] for r in active_rows)
        total_blocked     = sum(r["base_alloc"] for r in blocked_rows)
        remainder_krw     = total_invest - total_rec_krw

        # 원화 vs 달러 환전 분리
        rec_krw_only  = sum(r["rec_krw"] for r in active_rows if not r["is_usd"])   # 원화 직접 투자
        rec_usd_krw   = sum(r["rec_krw"] for r in active_rows if r["is_usd"])        # 달러 환전 필요분(원화 기준)
        rec_usd_amt   = rec_usd_krw / usdkrw if usdkrw > 0 else 0                   # 달러 금액

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("총 투자 가능", f"{total_invest:,.0f}원")
        s2.metric("이번달 권장 투자금", f"{total_rec_krw:,.0f}원")
        s3.metric("잔여(이월 후보)", f"{remainder_krw:,.0f}원",
                  help="반올림 차이 + 차단·대기로 미투자된 금액. '잔여금 이월' 버튼으로 다음달 적립금에 합산하세요.")
        if not redistribute_mode:
            s4.metric("차단·대기 금액", f"{total_blocked:,.0f}원",
                      help="재분배 체크 시 투자 가능 종목에 비중대로 추가 배분됩니다.")
        else:
            s4.metric("재분배", "✅ 적용됨")

        # 환전 필요금액 안내
        if rec_usd_krw > 0 or rec_krw_only > 0:
            fx1, fx2, fx3 = st.columns(3)
            fx1.metric("🇰🇷 원화 직접 투자", f"{rec_krw_only:,.0f}원",
                       help="국내 종목(KS/KQ) 매수에 필요한 원화")
            fx2.metric("🇺🇸 달러 환전 필요", f"${rec_usd_amt:,.2f}",
                       help=f"해외 종목 매수용 · 원화 기준 {rec_usd_krw:,.0f}원 (환율 {usdkrw:,.0f}원/달러 적용)")
            fx3.metric("원화+환전 합계", f"{(rec_krw_only + rec_usd_krw):,.0f}원",
                       help="이번달 실제 필요 원화 총액 (환전분 포함)")

        # ── 🟡 1주 미달 종목: 적립 누적 관리 ────────────────────────────────
        if underalloc_rows:
            st.markdown("#### 🟡 1주 미달 종목 — 적립 누적 관리")
            st.caption(
                "투자 신호는 있지만 배분금액이 **1주 가격 미만**인 종목입니다. "
                "매달 이 금액을 누적하거나, 재분배 모드를 켜서 다른 종목에 배분할 수 있습니다."
            )
            ua_table = []
            for r in underalloc_rows:
                accum = r["accumulated_krw"]
                needed = max(0, r["unit_price_krw"] - accum)
                ua_table.append({
                    "자산명":       r["name"],
                    "1주 가격":     f"{r['unit_price_krw']:,.0f}원",
                    "이번달 배분":  r["alloc_disp"],
                    "현재 누적금":  f"{accum:,.0f}원",
                    "추가 필요":    f"{needed:,.0f}원",
                    "예상 구매":    f"~{r.get('months_to_buy', '?')}달 후",
                    "상태":         r["status"],
                })
            st.dataframe(pd.DataFrame(ua_table), use_container_width=True, hide_index=True)

            ua_c1, ua_c2 = st.columns(2)
            with ua_c1:
                if st.button("💰 이번달 미달 배분금 누적에 추가", key="rebcalc_accum_add"):
                    _accum_new = dict(st.session_state["rebcalc_accum"])
                    added_total = 0
                    for r in underalloc_rows:
                        prev = _accum_new.get(r["ticker"], 0.0)
                        _accum_new[r["ticker"]] = prev + r["final_alloc"]
                        added_total += r["final_alloc"]
                    st.session_state["rebcalc_accum"] = _accum_new
                    st.success(f"✅ {len(underalloc_rows)}개 종목 · 총 {added_total:,.0f}원 누적에 추가됐습니다.")
                    st.rerun()
            with ua_c2:
                if st.button("🗑️ 누적금 전체 초기화", key="rebcalc_accum_reset"):
                    st.session_state["rebcalc_accum"] = {}
                    st.success("누적금이 초기화됐습니다.")
                    st.rerun()

            st.info(
                "💡 **설계 가이드** — 1주 미달 상황 대처법:\n\n"
                "• **🟡 적립 이월 (권장·코어ETF)**: '이번달 배분금 누적에 추가' 클릭 → 다음달 자동 합산 → 1주 가격 모이면 구매\n"
                "• **⚠️ 재분배**: 상단 '미투자금 자동 재분배' 체크 → 미달 배분금이 다른 종목에 추가됨 (비중 왜곡 있음)\n"
                "• **⏸ 신호 해소 대기**: 과열 신호 → 차단·대기 종목으로 설정 → 신호가 🟢로 바뀔 때 100% 비중으로 구매\n"
                "• **📅 타이밍 결론**: 코어 ETF는 '적립 이월'이 가장 안전. "
                "과열 해소되면 배분금이 커지고 주수도 늘어납니다."
            )

        # ── ⚡ 레버리지 버킷 전략 현황 ────────────────────────────────────────
        if leverage_rows:
            st.markdown("#### ⚡ 레버리지 전략 현황")
            st.caption(
                "**레버리지 배율 기준** — "
                "🚀 진입 ×1.5 · 📉 약하락 DCA ×0.75 · 📉📉 중하락 DCA ×1.0 · 📉📉 강하락 ×1.25 · "
                "📉📉🚀 매수+중하락 ×1.75 · 📉📉📉🚀 매수+강하락 ×2.0 · "
                "🌡️ 과열패스 ×0 · ⛔ 구조훼손 ×0\n\n"
                "평단 대비 **-5% 이상** 하락 시 단계별 배율 상향 — "
                "약(-5%~-10%) → 중(-10%~-15%) → 강(-15%↓)"
            )
            _dip_labels = {0: "📈 정상", 1: "📉 약(-5~-10%)", 2: "📉📉 중(-10~-15%)", 3: "📉📉📉 강(-15%↓)"}
            lev_table = []
            for r in leverage_rows:
                pct_vs_avg = ((r["cur_p"] / r["avg_p"]) - 1) * 100 if r["avg_p"] > 0 else 0
                pct_disp   = f"{pct_vs_avg:+.1f}%" if r["avg_p"] > 0 else "-"
                lev_table.append({
                    "자산명":     r["name"],
                    "기술적타점": r["tap_disp"],
                    "평단대비":   pct_disp,
                    "하락단계":   _dip_labels.get(r.get("dip_level", 0), "📈 정상"),
                    "배율":       f"×{r['multiplier']:.2f}",
                    "배분금액":   r["alloc_disp"] if r["multiplier"] > 0 else "-",
                    "권장주수":   str(r["rec_shares"]) if r["rec_shares"] > 0 else "-",
                    "상태":       r["status"],
                })
            st.dataframe(pd.DataFrame(lev_table), use_container_width=True, hide_index=True)

            # 레버리지 전략 요약
            if lev_active:
                lev_alloc_total = sum(r["final_alloc"] for r in lev_active)
                lev_krw_total   = sum(r["rec_krw"] for r in lev_active)
                dip_cnt         = sum(1 for r in lev_active if r["is_dip"])
                la1, la2, la3 = st.columns(3)
                la1.metric("레버리지 배분 합계", f"{lev_alloc_total:,.0f}원")
                la2.metric("레버리지 권장 투자금", f"{lev_krw_total:,.0f}원")
                la3.metric("하락 감지 종목", f"{dip_cnt}개", help="평단 -5% 이상 하락 종목 수")

            if lev_blocked:
                blocked_names = ", ".join(r["name"] for r in lev_blocked)
                st.caption(f"⚠️ 이번달 패스 레버리지: {blocked_names}")

        # ── 📊 총 필요 주수 (목표 비중 대비 전체 포트폴리오 기준) ────────────
        st.markdown("#### 📊 총 필요 주수 (목표비중 대비)")
        portfolio_total = clean_float(
            portfolio_summary.get("current_asset") if portfolio_summary else None, 0.0
        )
        st.caption(
            f"현재 포트폴리오 총평가액 **{portfolio_total:,.0f}원** 기준 · "
            "목표비중을 달성하려면 각 종목을 몇 주 보유해야 하는지 표시합니다. "
            "매달 적립매수로 자연스럽게 수렴하는 목표치로 활용하세요."
        )
        need_rows = []
        for r in calc_rows:
            cur_p  = r["cur_p"]
            is_usd = r["is_usd"]
            target_w_pct = r["target_w"]
            qty_now = r["qty"]

            if cur_p <= 0 or portfolio_total <= 0:
                target_shares = 0.0
            else:
                target_krw = portfolio_total * (target_w_pct / 100.0)
                if is_usd:
                    target_shares = target_krw / (cur_p * usdkrw) if usdkrw > 0 else 0.0
                else:
                    target_shares = target_krw / cur_p

            diff = target_shares - qty_now
            diff_disp = f"+{diff:.2f}" if diff >= 0 else f"{diff:.2f}"
            need_rows.append({
                "자산명":   r["name"],
                "목표비중": f"{target_w_pct:.1f}%",
                "목표주수": f"{target_shares:.2f}",
                "현재보유": f"{qty_now:.4f}",
                "추가필요": diff_disp,
                "버킷":     r["bucket"],
                "상태":     ("✅ 완료" if abs(diff) < 0.5
                              else ("📈 매수필요" if diff > 0 else "📉 비중초과")),
            })
        st.dataframe(pd.DataFrame(need_rows), use_container_width=True, hide_index=True)

        # ── 스윙 종목 별도 체크 ───────────────────────────────────────────────
        if swing_rows:
            st.markdown("#### ⚡ 스윙 종목 (이번달 매수 여부)")
            st.caption(
                "스윙 종목은 자동 배분에서 제외되지만, 기회매수를 했다면 아래에서 체크하세요."
            )
            sw_cols = st.columns(min(len(swing_rows), 4))
            swing_done_map = dict(st.session_state[_done_key])
            for i, r in enumerate(swing_rows):
                with sw_cols[i % 4]:
                    checked = st.checkbox(
                        f"⚡ {r['name']}",
                        value=swing_done_map.get(r["ticker"], False),
                        key=f"rebcalc_swing_{r['ticker']}_{_this_month}",
                    )
                    swing_done_map[r["ticker"]] = checked
            st.session_state[_done_key] = swing_done_map

        # ── ✅ 투자 완료 체크 (실제 매수 가능 종목만) ───────────────────────
        st.markdown("#### ✅ 이번달 투자 완료 체크")
        done_map = dict(st.session_state[_done_key])
        if buyable_rows:
            chk_cols = st.columns(min(len(buyable_rows), 4))
            for i, r in enumerate(buyable_rows):
                with chk_cols[i % 4]:
                    checked = st.checkbox(
                        r["name"],
                        value=done_map.get(r["ticker"], False),
                        key=f"rebcalc_chk_{r['ticker']}_{_this_month}",
                    )
                    done_map[r["ticker"]] = checked
            st.session_state[_done_key] = done_map

            all_done = all(done_map.get(r["ticker"], False) for r in buyable_rows)
            if all_done and buyable_rows:
                st.success("🎉 이번 달 매수 가능 종목을 모두 완료했습니다!")
        elif active_rows and not buyable_rows:
            st.caption("이번 달 1주 이상 매수 가능한 종목이 없습니다. 위 적립 누적 섹션을 이용하세요.")
        else:
            st.caption("이번 달 투자 가능한 종목이 없습니다.")

        # ── 📅 월별 로그 연동 ─────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 📅 월별 로그 연동")

        prev_total_invested = 0.0
        prev_month_str = ""
        if monthly_logs_df is not None and not monthly_logs_df.empty:
            _logs = monthly_logs_df[monthly_logs_df["month"].astype(str) < _this_month].copy()
            if not _logs.empty:
                _latest = _logs.sort_values("month").iloc[-1]
                prev_total_invested = clean_float(_latest.get("total_invested"), 0.0)
                prev_month_str = str(_latest.get("month", ""))

        # 누적 투자금 = 이전달 누적 + 이번달 적립금
        # (이월 누적금은 "아직 투자 안 한 현금"이므로 누적 투자금에는 포함하지 않음)
        new_total_invested = prev_total_invested + monthly

        with st.container():
            if prev_month_str:
                st.info(
                    f"직전 월 로그: **{prev_month_str}** · 누적 투자금 {prev_total_invested:,.0f}원  \n"
                    f"→ 이번 달 적립금 **{monthly:,.0f}원** 합산 → 누적 **{new_total_invested:,.0f}원**"
                )
            else:
                st.info(f"월별 로그 없음 · 첫 달로 기록됩니다 (적립금: {monthly:,.0f}원)")

            # 이월금 개념 설명
            if carryover > 0:
                st.caption(
                    f"💡 **이월 누적금 {carryover:,.0f}원** 안내 — "
                    "이월금은 지난달 미투자 잔여금으로, 현재 **원화 예수금에 포함**되어 있습니다. "
                    "월별 누적 투자금에는 실제로 '입금한 적립금'만 더하고, "
                    "이월금은 이번달 배분 가능 총액(=적립금+이월금)에만 반영합니다. "
                    f"이번달 총 투자 가능금: **{total_invest:,.0f}원** (적립금 {monthly:,.0f} + 이월금 {carryover:,.0f})"
                )

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("📝 이번달 로그 기록 (Supabase)", key="rebcalc_save_log"):
                if monthly_logs_df is None:
                    st.error("monthly_logs_df가 전달되지 않았습니다.")
                elif IS_PUBLIC_DEMO:
                    st.warning("데모 모드에서는 저장할 수 없습니다.")
                else:
                    logs_copy = monthly_logs_df.copy()
                    existing_mask = logs_copy["month"].astype(str) == _this_month
                    _cur_asset = clean_float(
                        portfolio_summary.get("current_asset") if portfolio_summary else None, 0.0
                    )
                    if existing_mask.any():
                        logs_copy.loc[existing_mask, "total_invested"] = new_total_invested
                        logs_copy.loc[existing_mask, "evaluated_value"] = _cur_asset
                    else:
                        new_row = pd.DataFrame([{
                            "month": _this_month,
                            "total_invested": new_total_invested,
                            "evaluated_value": _cur_asset,
                            "dividend": 0.0,
                        }])
                        logs_copy = pd.concat([logs_copy, new_row], ignore_index=True)
                    if save_monthly_logs_db(logs_copy.fillna("")):
                        st.success(
                            f"✅ {_this_month} 로그 저장 완료 — "
                            f"누적 투자금 {new_total_invested:,.0f}원 / 평가금액 {_cur_asset:,.0f}원"
                        )
                        st.rerun()
        with b2:
            if st.button("➡️ 잔여금 다음달 이월", key="rebcalc_do_carryover"):
                _new_carry = int(st.session_state.get("rebcalc_carryover", 0) + remainder_krw)
                st.session_state["rebcalc_carryover"] = _new_carry
                st.success(
                    f"잔여금 {remainder_krw:,.0f}원 이월 추가. "
                    f"다음달 이월금: {_new_carry:,.0f}원 "
                    f"(원화 예수금에 보관 중인 미투자 현금)"
                )
                st.rerun()
        with b3:
            if st.button("🔄 이번달 초기화", key="rebcalc_reset"):
                st.session_state[_done_key] = {}
                st.rerun()


def render_dart_disclosure_panel(holdings_table):
    """보유 KR 종목의 최근 공시를 expander로 표시합니다."""
    if holdings_table is None or holdings_table.empty:
        return

    kr_tickers = [
        str(r.get("티커", ""))
        for _, r in holdings_table.iterrows()
        if str(r.get("티커", "")).upper().endswith((".KS", ".KQ"))
    ]
    if not kr_tickers:
        return

    all_items = []
    for tkr in kr_tickers[:12]:
        code = str(tkr).upper().replace(".KS", "").replace(".KQ", "").strip()
        try:
            corp_code = get_dart_corp_code(code)
        except Exception:
            corp_code = None
        if not corp_code:
            continue
        for item in fetch_dart_disclosures(corp_code, days=30)[:3]:
            all_items.append({
                "종목": sanitize_asset_name("", tkr),
                "날짜": item.get("rcept_dt", "")[:8],
                "제목": item.get("report_nm", ""),
                "rcept_no": item.get("rcept_no", ""),
            })

    all_items = sorted(all_items, key=lambda x: x["날짜"], reverse=True)[:20]
    label = f"📢 최근 DART 공시 ({len(all_items)}건, 30일)" if all_items else "📢 최근 DART 공시 (30일)"

    with st.expander(label, expanded=False):
        if not all_items:
            st.caption("최근 30일 내 공시가 없거나 DART API 키가 설정되지 않았습니다.")
        else:
            for d in all_items:
                ds = d["날짜"]
                date_fmt = f"{ds[:4]}.{ds[4:6]}.{ds[6:]}" if len(ds) >= 8 else ds
                link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d['rcept_no']}"
                st.markdown(
                    f"<small style='color:#94a3b8'>{date_fmt}</small>&nbsp;&nbsp;"
                    f"<b>{d['종목']}</b> — "
                    f"<a href='{link}' target='_blank' style='color:#60a5fa'>{d['제목']}</a>",
                    unsafe_allow_html=True,
                )


def _render_dart_disclosure_single(ticker: str, name: str):
    """개별 종목 분석 패널용 DART 공시 expander."""
    code = str(ticker).upper().replace(".KS", "").replace(".KQ", "").strip()
    try:
        corp_code = get_dart_corp_code(code)
    except Exception:
        corp_code = None

    items = fetch_dart_disclosures(corp_code, days=60) if corp_code else []
    label = f"📢 DART 공시 ({len(items)}건, 60일)" if items else "📢 DART 공시 (60일)"

    with st.expander(label, expanded=False):
        if not items:
            if not corp_code:
                st.caption("DART 기업코드를 찾을 수 없습니다.")
            else:
                st.caption("최근 60일 내 공시가 없거나 DART API 키가 설정되지 않았습니다.")
        else:
            for item in items[:15]:
                ds = item.get("rcept_dt", "")[:8]
                date_fmt = f"{ds[:4]}.{ds[4:6]}.{ds[6:]}" if len(ds) >= 8 else ds
                rcept_no = item.get("rcept_no", "")
                link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                st.markdown(
                    f"<small style='color:#94a3b8'>{date_fmt}</small>&nbsp;&nbsp;"
                    f"<a href='{link}' target='_blank' style='color:#60a5fa'>{item.get('report_nm', '')}</a>",
                    unsafe_allow_html=True,
                )


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

        if len(annual_records) < 1:
            return attach_krx_context_to_kr_failure(ticker, "dart", "DART annual financials: 0 years found")

        if len(quarter_records) < 1:
            return attach_krx_context_to_kr_failure(ticker, "dart", "DART single-quarter financials missing")

        return {
            "ok": True,
            "source": "dart",
            "ticker": ticker,
            "annual": annual_records[-3:],
            "quarter": quarter_records[-4:],
        }

    except Exception as e:
        return attach_krx_context_to_kr_failure(ticker, "dart", f"DART error: {e}")


def render_financial_trend_chart(ticker: str, name: str):
    """DART 연간 재무 트렌드 차트 (매출/영업이익/순이익 + YoY 성장률)."""
    if not str(ticker).upper().endswith((".KS", ".KQ")):
        st.caption("재무 트렌드는 한국 DART 데이터 기반입니다.")
        return

    with st.spinner("재무 데이터 로딩 중…"):
        fin = fetch_kr_financials_auto(ticker)

    if not fin.get("ok") or not fin.get("annual"):
        st.caption("DART 재무 데이터를 불러오지 못했습니다.")
        return

    annual = fin["annual"]
    if len(annual) < 2:
        st.caption("연간 재무 데이터가 2년 미만입니다.")
        return

    _b = 1e8  # 억 단위 변환
    years      = [str(r.get("fiscal_year", "")) for r in annual]
    revenues   = [clean_float(r.get("revenue"),   0) / _b for r in annual]
    op_incomes = [clean_float(r.get("op_income"), 0) / _b for r in annual]
    net_incomes= [clean_float(r.get("net_income"),0) / _b for r in annual]

    def _yoy(vals):
        result = [None]
        for i in range(1, len(vals)):
            prev = vals[i - 1]
            result.append(((vals[i] / prev) - 1) * 100 if prev and prev != 0 else None)
        return result

    rev_yoy = _yoy(revenues)
    op_yoy  = _yoy(op_incomes)
    net_yoy = _yoy(net_incomes)

    def _bar_colors(vals):
        return ["#22c55e" if v >= 0 else "#ef4444" for v in vals]

    def _txt(vals, yoys):
        lines = []
        for v, g in zip(vals, yoys):
            t = f"{v:,.0f}억"
            if g is not None:
                arrow = "▲" if g > 0 else "▼"
                t += f"<br>{arrow}{abs(g):.1f}%"
            lines.append(t)
        return lines

    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=("매출액", "영업이익", "순이익"),
        horizontal_spacing=0.08,
    )
    fig.add_trace(go.Bar(
        x=years, y=revenues, marker_color="#3b82f6",
        text=_txt(revenues, rev_yoy), textposition="inside",
        textfont=dict(size=11), name="매출",
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=years, y=op_incomes, marker_color=_bar_colors(op_incomes),
        text=_txt(op_incomes, op_yoy), textposition="inside",
        textfont=dict(size=11), name="영업이익",
    ), row=1, col=2)
    fig.add_trace(go.Bar(
        x=years, y=net_incomes, marker_color=_bar_colors(net_incomes),
        text=_txt(net_incomes, net_yoy), textposition="inside",
        textfont=dict(size=11), name="순이익",
    ), row=1, col=3)

    fig.update_layout(
        template="plotly_dark",
        height=280,
        showlegend=False,
        margin=dict(t=45, b=15, l=10, r=10),
        font=dict(size=12),
    )
    fig.update_yaxes(ticksuffix="억")
    st.plotly_chart(fig, use_container_width=True)

    last_ry  = rev_yoy[-1]
    last_oy  = op_yoy[-1]
    last_ny  = net_yoy[-1]
    parts = []
    if last_ry  is not None: parts.append(f"매출 <b style='color:{'#22c55e' if last_ry>=0 else '#ef4444'}'>{last_ry:+.1f}%</b>")
    if last_oy  is not None: parts.append(f"영업이익 <b style='color:{'#22c55e' if last_oy>=0 else '#ef4444'}'>{last_oy:+.1f}%</b>")
    if last_ny  is not None: parts.append(f"순이익 <b style='color:{'#22c55e' if last_ny>=0 else '#ef4444'}'>{last_ny:+.1f}%</b>")
    if parts:
        st.markdown(
            f"<small>최근 연간 YoY: {' &nbsp;|&nbsp; '.join(parts)}</small>",
            unsafe_allow_html=True,
        )


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

KRX_STOCK_API_ENDPOINTS = [
    ("KOSPI", "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"),
    ("KOSDAQ", "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd"),
]

def get_krx_stock_api_endpoints_for_ticker(ticker):
    text = str(ticker or "").strip().upper()
    if text.endswith(".KS"):
        return [KRX_STOCK_API_ENDPOINTS[0]]
    if text.endswith(".KQ"):
        return [KRX_STOCK_API_ENDPOINTS[1]]
    return KRX_STOCK_API_ENDPOINTS

SEC_US_GAAP_TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "liabilities": ["Liabilities"],
    "assets": ["Assets"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
}

SEC_FLOW_FIELDS = {"revenue", "op_income", "net_income", "ocf"}

def krx_recent_business_dates(days=5):
    today = datetime.now(KST).date()
    dates = []
    cur = today
    while len(dates) < days:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y%m%d"))
        cur = cur - timedelta(days=1)
    return dates

def get_krx_rows_from_payload(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ["OutBlock_1", "output", "data", "rows", "list"]:
        rows = payload.get(key)
        if isinstance(rows, list):
            return rows
    return []

def get_krx_row_value(row, keys, default=""):
    if not isinstance(row, dict):
        return default
    for key in keys:
        value = row.get(key)
        if value not in [None, ""]:
            return value
    return default

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_krx_stock_snapshot(ticker: str):
    """pykrx 기반 KRX 종목 기본 정보 조회 (API 키 불필요)."""
    stock_code = normalize_stock_code(ticker)
    if not stock_code or not stock_code.isdigit():
        return {"ok": False, "source": "krx", "reason": f"KRX stock code invalid: {ticker}"}
    try:
        from pykrx import stock as _pykrx
        from datetime import date as _d, timedelta as _td
        # 최근 거래일 찾기 (최대 5일 소급)
        for offset in range(5):
            bas_dd = (_d.today() - _td(days=offset)).strftime("%Y%m%d")
            try:
                if hasattr(_pykrx, "get_market_cap_by_ticker"):
                    df = _pykrx.get_market_cap_by_ticker(bas_dd, market="ALL")
                else:
                    df = _pykrx.get_market_cap(bas_dd)
                if df is None or df.empty:
                    continue
                if stock_code not in df.index:
                    continue
                row = df.loc[stock_code]
                mktcap = int(row.get("시가총액", 0) or 0)
                listed_shares = int(row.get("상장주식수", 0) or 0)
                # 종목명 조회
                try:
                    name = _pykrx.get_market_ticker_name(stock_code) or ""
                except Exception:
                    name = ""
                market_label = "KOSPI" if ticker.upper().endswith(".KS") else "KOSDAQ"
                return {
                    "ok": True,
                    "source": "pykrx",
                    "basDd": bas_dd,
                    "market": market_label,
                    "name": name,
                    "ticker": ticker,
                    "stock_code": stock_code,
                    "mktcap": mktcap,
                    "listed_shares": listed_shares,
                }
            except Exception:
                continue
        return {"ok": False, "source": "pykrx", "reason": "pykrx 데이터 없음 (신규 상장 또는 거래정지)"}
    except ImportError:
        return {"ok": False, "source": "krx", "reason": "pykrx 미설치"}

def attach_krx_context_to_kr_failure(ticker, source, reason):
    snapshot = fetch_krx_stock_snapshot(ticker)
    if snapshot.get("ok"):
        extra = (
            f"KRX listed: {snapshot.get('market', '-')}, "
            f"{snapshot.get('name', '-')}, {snapshot.get('basDd', '-')}"
        )
    else:
        extra = f"KRX check failed: {snapshot.get('reason', 'unknown')}"
    return {
        "ok": False,
        "source": f"{source}/krx",
        "reason": f"{reason} / {extra}",
        "krx_snapshot": snapshot,
    }

def sec_request_json(url):
    user_agent = get_sec_user_agent()
    if not user_agent:
        raise RuntimeError("SEC User-Agent missing")
    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }
    res = requests.get(url, headers=headers, timeout=20)
    if res.status_code == 429:
        raise RuntimeError("SEC rate limit")
    if res.status_code in [403, 404]:
        raise RuntimeError(f"SEC HTTP {res.status_code}: {res.text[:160]}")
    res.raise_for_status()
    return res.json()

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_sec_company_tickers():
    data = sec_request_json("https://www.sec.gov/files/company_tickers.json")
    if isinstance(data, dict):
        return list(data.values())
    return data if isinstance(data, list) else []

def get_sec_cik_for_ticker(ticker: str):
    symbol = str(ticker or "").strip().upper()
    aliases = {symbol, symbol.replace(".", "-"), symbol.replace("-", ".")}
    for item in fetch_sec_company_tickers():
        sec_ticker = str(item.get("ticker", "")).strip().upper()
        if sec_ticker in aliases:
            return str(int(item.get("cik_str"))).zfill(10), item
    return "", {}

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_sec_company_facts(cik: str):
    cik = str(cik or "").strip().zfill(10)
    return sec_request_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")

def sec_fact_rows(company_facts, tags, units=("USD", "shares")):
    facts = company_facts.get("facts", {}) if isinstance(company_facts, dict) else {}
    us_gaap = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
    rows = []
    for tag in tags:
        tag_data = us_gaap.get(tag, {})
        unit_data = tag_data.get("units", {}) if isinstance(tag_data, dict) else {}
        for unit in units:
            for row in unit_data.get(unit, []) or []:
                if isinstance(row, dict) and row.get("val") not in [None, ""]:
                    item = dict(row)
                    item["tag"] = tag
                    item["unit"] = unit
                    rows.append(item)
    return rows

def sec_duration_days(row):
    try:
        start = row.get("start")
        end = row.get("end")
        if not start or not end:
            return None
        return (pd.Timestamp(end) - pd.Timestamp(start)).days
    except Exception:
        return None

def sec_pick_value(company_facts, field, fy, forms, fps=None, annual_flow=False, quarterly_flow=False):
    candidates = []
    for row in sec_fact_rows(company_facts, SEC_US_GAAP_TAGS.get(field, [])):
        try:
            row_fy = int(row.get("fy"))
        except Exception:
            continue
        if row_fy != int(fy):
            continue
        form = str(row.get("form", "")).upper()
        fp = str(row.get("fp", "")).upper()
        if form not in forms:
            continue
        if fps is not None and fp not in fps:
            continue
        duration = sec_duration_days(row)
        if field in SEC_FLOW_FIELDS and annual_flow and duration is not None and duration < 250:
            continue
        if field in SEC_FLOW_FIELDS and quarterly_flow and duration is not None and duration > 140:
            continue
        candidates.append(row)

    if not candidates:
        return np.nan

    candidates = sorted(
        candidates,
        key=lambda r: (str(r.get("filed", "")), str(r.get("end", "")), str(r.get("tag", ""))),
    )
    return safe_float(candidates[-1].get("val"))

def build_sec_annual_records(company_facts):
    revenue_rows = sec_fact_rows(company_facts, SEC_US_GAAP_TAGS["revenue"])
    years = sorted({
        int(row.get("fy"))
        for row in revenue_rows
        if str(row.get("form", "")).upper() in {"10-K", "10-K/A"}
        and str(row.get("fp", "")).upper() == "FY"
        and str(row.get("fy", "")).isdigit()
    })

    records = []
    for fy in years[-5:]:
        record = {
            "period": "annual",
            "fiscal_year": str(fy),
            "fiscal_quarter": 4,
            "report_code": "10-K",
            "report_label": "10-K",
            "date": str(fy),
        }
        for field in SEC_US_GAAP_TAGS:
            record[field] = sec_pick_value(
                company_facts,
                field,
                fy,
                forms={"10-K", "10-K/A"},
                fps={"FY"},
                annual_flow=True,
            )
        record = enrich_fin_record(record)
        if has_dart_core_values(record):
            records.append(record)
    return records[-3:]

def build_sec_quarter_records(company_facts):
    revenue_rows = sec_fact_rows(company_facts, SEC_US_GAAP_TAGS["revenue"])
    keys = sorted({
        (int(row.get("fy")), str(row.get("fp", "")).upper())
        for row in revenue_rows
        if str(row.get("form", "")).upper() in {"10-Q", "10-Q/A"}
        and str(row.get("fp", "")).upper() in {"Q1", "Q2", "Q3"}
        and str(row.get("fy", "")).isdigit()
    })

    records = []
    for fy, fp in keys[-8:]:
        try:
            q_no = int(fp.replace("Q", ""))
        except Exception:
            q_no = None
        record = {
            "period": "quarter",
            "fiscal_year": str(fy),
            "fiscal_quarter": q_no,
            "report_code": fp,
            "report_label": fp,
            "date": f"{fy}-{fp}",
        }
        for field in SEC_US_GAAP_TAGS:
            record[field] = sec_pick_value(
                company_facts,
                field,
                fy,
                forms={"10-Q", "10-Q/A"},
                fps={fp},
                quarterly_flow=True,
            )
        record = enrich_fin_record(record)
        if has_dart_core_values(record):
            records.append(record)
    return records[-4:]

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_us_financials_sec(ticker: str):
    symbol = str(ticker).strip().upper()
    try:
        cik, ticker_meta = get_sec_cik_for_ticker(symbol)
        if not cik:
            return {"ok": False, "source": "sec_edgar", "reason": f"SEC CIK lookup failed: {symbol}"}

        facts = fetch_sec_company_facts(cik)
        annual_records = build_sec_annual_records(facts)
        quarter_records = build_sec_quarter_records(facts)

        if len(annual_records) < 2:
            return {
                "ok": False,
                "source": "sec_edgar",
                "reason": "SEC annual financials under 2 years",
                "sec_meta": {"cik": cik, "ticker_meta": ticker_meta},
            }

        return {
            "ok": True,
            "source": "sec_edgar",
            "ticker": ticker,
            "annual": annual_records[-3:],
            "quarter": quarter_records[-4:],
            "sec_meta": {"cik": cik, "ticker_meta": ticker_meta},
        }
    except Exception as exc:
        return {"ok": False, "source": "sec_edgar", "reason": f"SEC error: {exc}"}

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_us_financials_fmp(ticker: str):
    api_key = get_secret_value("fmp_api_key")
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

@st.cache_data(ttl=FIN_DATA_TTL_SECONDS, show_spinner=False)
def fetch_us_financials_auto(ticker: str):
    fmp_result = fetch_us_financials_fmp(ticker)
    if fmp_result.get("ok", False):
        return fmp_result

    sec_result = fetch_us_financials_sec(ticker)
    if sec_result.get("ok", False):
        sec_result = dict(sec_result)
        sec_result["fallback_from"] = {
            "source": fmp_result.get("source", "fmp"),
            "reason": fmp_result.get("reason", "unknown"),
        }
        return sec_result

    return {
        "ok": False,
        "source": "fmp/sec_edgar",
        "reason": (
            f"FMP: {fmp_result.get('reason', 'unknown')} / "
            f"SEC: {sec_result.get('reason', 'unknown')}"
        ),
        "fmp_error": fmp_result,
        "sec_error": sec_result,
    }

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

def _estimate_kr_fin_score_from_naver(ticker: str) -> tuple:
    """
    DART 완전 실패 시 Naver/pykrx 지표로 간이 재무점수를 추정합니다.
    최대 3점 (데이터 부족으로 4점 확정 불가).
    반환: (score, reason_str)
    """
    try:
        naver = fetch_naver_kr_snapshot(ticker)
        return estimate_kr_fin_score_from_naver_snapshot(
            naver,
            default_score=AUTO_FIN_FAIL_SCORE,
        )
    except Exception as e:
        return AUTO_FIN_FAIL_SCORE, f"Naver간이추정 실패: {e}"


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
        metrics = {
            key: fin.get(key)
            for key in ["krx_snapshot", "sec_meta", "fmp_error", "sec_error"]
            if fin.get(key) is not None
        }
        dart_reason = fin.get("reason", "원인 미상")
        # KR 종목이면 Naver 간이 추정으로 flat-3 보다 정밀한 폴백 시도
        if is_kr:
            naver_score, naver_reason = _estimate_kr_fin_score_from_naver(ticker)
            notes = {
                "ok": False, "source": "naver_fallback", "mode": "Naver간이추정",
                "reason": dart_reason, "annual_judgements": {}, "quarter_judgements": {},
                "weighted_scores": {}, "messages": [
                    f"자동 재무 조회 실패 → Naver 간이추정 {naver_score}점 (최대 3점)",
                    f"DART 사유: {dart_reason}",
                    f"추정 근거: {naver_reason}",
                ],
            }
            return naver_score, fin, notes, metrics
        else:
            notes = {
                "ok": False, "source": fin.get("source", "unknown"), "mode": "fallback",
                "reason": dart_reason, "annual_judgements": {}, "quarter_judgements": {},
                "weighted_scores": {}, "messages": [f"자동 재무 조회 실패 → 보수 임시 {AUTO_FIN_FAIL_SCORE}점", f"사유: {dart_reason}"],
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
    if fin.get("sec_meta") is not None:
        metrics["sec_meta"] = fin.get("sec_meta")
    if fin.get("fallback_from") is not None:
        metrics["fallback_from"] = fin.get("fallback_from")
    if fin.get("krx_snapshot") is not None:
        metrics["krx_snapshot"] = fin.get("krx_snapshot")

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
    score_source = resolve_fin_score_source(fin_auto, stored_notes)

    upsert_fin_score_db(
        ticker=key, auto_score=int(auto_score), manual_score=manual_score,
        final_score=int(final_score), source=score_source, notes=stored_notes
    )

    return int(final_score), {
        "auto_score": int(auto_score), "manual_score": manual_score, "final_score": int(final_score),
        "source": score_source, "mode": stored_notes.get("mode", "unknown"),
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
            "해석": "버튼을 누르면 DART/FMP/SEC 재무 데이터를 불러와 자동으로 판정합니다.",
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
        ("데이터", str(source), "DART/FMP/SEC 기준" if not is_etf else "ETF 기준"),
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
    for fn_name in [
        "fetch_us_financials_auto",
        "fetch_us_financials_fmp",
        "fetch_us_financials_sec",
        "fetch_sec_company_tickers",
        "fetch_sec_company_facts",
        "fetch_kr_financials_auto",
        "fetch_dart_finstate_all_raw",
        "fetch_krx_stock_snapshot",
    ]:
        fn = globals().get(fn_name)
        if fn is not None and hasattr(fn, "clear"):
            fn.clear()
    # imported 함수는 globals()로 못 찾으므로 직접 지움
    cache_clear(fetch_naver_kr_snapshot)


# -------------------------------------------------
# 2-3. 보유자산 계산
# -------------------------------------------------
def build_holdings_table(holdings_df, krw_cash, usd_cash, usdkrw):
    def get_empty_holdings():
        empty_df = pd.DataFrame(columns=[
            "자산명", "티커", "보유량", "매입가", "현재가", "평가금액", "평가손익",
            "수익률", "원화환산", "현재비중", "목표비중", "비중차이", "is_etf", "asset_class", "bucket", "운용대상", "리밸런싱목표비중"
        ])
        return apply_holdings_weight_columns(empty_df, krw_cash, usd_cash, usdkrw)

    if holdings_df.empty:
        return get_empty_holdings()

    if "account_type" not in holdings_df.columns:
        holdings_df["account_type"] = "일반"
    holdings_df["account_type"] = holdings_df["account_type"].fillna("일반")

    # --- 사이드바 필터링 적용 ---
    if "acc_filter" in st.session_state:
        if len(st.session_state.acc_filter) == 0:
            return get_empty_holdings()
            
        holdings_df = holdings_df[holdings_df["account_type"].isin(st.session_state.acc_filter)]
        if holdings_df.empty:
            return get_empty_holdings()

    # ==========================================
    # [신규 추가] 동일한 종목(티커) 하나로 합치기
    # ==========================================
    # 수량과 매입가를 숫자로 변환
    holdings_df["qty"] = pd.to_numeric(holdings_df["qty"], errors="coerce").fillna(0.0)
    holdings_df["avg_price"] = pd.to_numeric(holdings_df["avg_price"], errors="coerce").fillna(0.0)
    holdings_df["target_weight"] = pd.to_numeric(holdings_df["target_weight"], errors="coerce").fillna(0.0)
    
    # 총 매입금액 계산 (가중평균을 위해)
    holdings_df["invested"] = holdings_df["qty"] * holdings_df["avg_price"]
    
    # 티커 기준으로 병합 (수량 합산, 목표비중 합산)
    grouped = holdings_df.groupby("ticker", as_index=False).agg({
        "name": "first",
        "qty": "sum",
        "invested": "sum",
        "target_weight": "sum",
        "asset_class": "first",
        "is_etf": "first",
        "bucket": "first"
    })
    
    # 가중 평균 매입가 재계산
    grouped["avg_price"] = np.where(grouped["qty"] > 0, grouped["invested"] / grouped["qty"], 0.0)
    holdings_df = grouped
    # ==========================================

    # --- 가격 가져오기 ---
    price_tickers = tuple(
        str(ticker).strip()
        for ticker in holdings_df.get("ticker", pd.Series(dtype=str)).tolist()
        if str(ticker).strip()
    )
    latest_price_map = get_public_demo_latest_price_map(price_tickers) if IS_PUBLIC_DEMO else load_latest_prices_batch(price_tickers)

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
        if cur_price <= 0 and not IS_PUBLIC_DEMO:
            cur_price = load_latest_price(ticker)
        elif cur_price <= 0:
            cur_price = avg_price

        eval_amt = qty * cur_price
        pnl = qty * (cur_price - avg_price)
        ret = ((cur_price / avg_price) - 1) if avg_price > 0 else 0.0

        is_kr = str(ticker).upper().endswith(".KS") or str(ticker).upper().endswith(".KQ")
        krw_eval = eval_amt if is_kr else eval_amt * usdkrw

        # ── 손익분기점: 매입가 × (1 + 수수료율) ─────────────────────────────
        _fee_rate = 0.0015 if is_kr else 0.001   # KRX 0.15%, 해외 0.1%
        breakeven = round(avg_price * (1 + _fee_rate), 4) if avg_price > 0 else 0.0
        to_breakeven_pct = round((cur_price / breakeven - 1) * 100, 2) if cur_price > 0 and breakeven > 0 else np.nan

        rows.append({
            "자산명": name, "티커": ticker, "보유량": qty, "매입가": avg_price,
            "현재가": cur_price, "평가금액": eval_amt, "평가손익": pnl, "수익률": ret,
            "원화환산": krw_eval, "목표비중": target_weight, "is_etf": is_etf, "asset_class": asset_class,
            "bucket": bucket,
            "손익분기점": breakeven,
            "본전까지%": to_breakeven_pct,
        })

    return apply_holdings_weight_columns(pd.DataFrame(rows), krw_cash, usd_cash, usdkrw)

# 돈흐름 데이터 로직은 stock_lab_core.money_flow 모듈로 분리

def fmt_flow_pct(v):
    if not finite_num(v):
        return "-"
    return f"{float(v) * 100:.1f}%"


def fmt_flow_score(v):
    if not finite_num(v):
        return "-"
    return f"{float(v):.1f}"


def build_today_flow_rank_table(df, group_name, score_col="돈흐름점수", top_n=5):
    if df is None or df.empty or score_col not in df.columns:
        return pd.DataFrame()
    if "구분" not in df.columns:
        return pd.DataFrame()
    view = df[df["구분"].astype(str).eq(group_name)].dropna(subset=[score_col]).copy()
    if view.empty:
        return pd.DataFrame()
    # 스윙 점수 기준 필터 (하락·둔화·고점 추격 제외)
    if score_col == "스윙점수":
        if "2주수익률" in view.columns:
            # 2주 +1% 미만 제외 — 진짜 단기 모멘텀 없으면 스윙 자리 아님
            view = view[view["2주수익률"].apply(lambda v: finite_num(v) and float(v) >= 0.01)]
        if "단기가속도" in view.columns:
            # 단기가속도 음수 제외 — 둔화·역전 중인 섹터 차단
            view = view[view["단기가속도"].apply(lambda v: finite_num(v) and float(v) >= 0.0)]
        if "상태" in view.columns:
            # 과열경보 제외 — 고점 추격 방지
            view = view[view["상태"].astype(str) != "과열경보"]
    if view.empty:
        return pd.DataFrame()
    return view.sort_values(score_col, ascending=False).head(top_n)


def format_today_flow_rank_table(df, score_col="돈흐름점수"):
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy()
    for col in ["1개월수익률", "2주수익률", "3개월수익률", "상대3개월수익률", "6개월수익률", "가속도", "단기가속도", "거래량증가", "상승종목비율"]:
        if col in view.columns:
            view[col] = view[col].apply(fmt_flow_pct)
    for sc in [score_col, "스윙점수"]:
        if sc in view.columns:
            view[sc] = view[sc].apply(fmt_flow_score)
    cols = list(dict.fromkeys([  # 중복 제거 (score_col == "스윙점수" 일 때)
        "섹터", "Ticker", "ETF 이름", score_col, "스윙점수", "상태", "추격위험",
        "2주수익률", "1개월수익률", "3개월수익률", "단기가속도", "거래량증가",
    ]))
    return view[[c for c in cols if c in view.columns]]


def format_today_theme_rank_table(df, score_col="테마돈흐름점수"):
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy()
    for col in ["1개월수익률", "3개월수익률", "상대3개월수익률", "6개월수익률", "가속도", "거래량증가", "상승종목비율"]:
        if col in view.columns:
            view[col] = view[col].apply(fmt_flow_pct)
    if score_col in view.columns:
        view[score_col] = view[score_col].apply(fmt_flow_score)
    cols = [
        "테마", "하위테마", "대표주", score_col, "상태", "추격위험",
        "3개월수익률", "상승종목비율", "가속도", "거래량증가", "구성종목",
    ]
    return view[[c for c in cols if c in view.columns]]


def build_today_theme_flow_tables(theme_flow_df, rotation_df, group_df):
    if rotation_df is None or rotation_df.empty or "테마돈흐름점수" not in rotation_df.columns:
        return pd.DataFrame(), pd.DataFrame()

    theme_rank = rotation_df.dropna(subset=["테마돈흐름점수"]).copy()
    if theme_rank.empty:
        return pd.DataFrame(), pd.DataFrame()

    theme_rank = theme_rank.sort_values("테마돈흐름점수", ascending=False)
    top_theme = str(theme_rank.iloc[0].get("테마", "") or "")

    subtheme_rank = pd.DataFrame()
    if group_df is not None and not group_df.empty and top_theme:
        score_col = "돈흐름점수" if "돈흐름점수" in group_df.columns else "테마돈흐름점수"
        if score_col in group_df.columns:
            subtheme_rank = (
                group_df[group_df["테마"].astype(str).eq(top_theme)]
                .dropna(subset=[score_col])
                .sort_values(score_col, ascending=False)
                .head(3)
                .copy()
            )

    return theme_rank.head(5), subtheme_rank


@st.cache_data(ttl=900, show_spinner=False)
def get_today_market_flow_snapshot():
    flow_df = calculate_money_flow_df()
    us_top5 = build_today_flow_rank_table(flow_df, "미국 섹터", top_n=5)
    kr_top5 = build_today_flow_rank_table(flow_df, "한국 섹터", top_n=5)
    global_top = build_today_flow_rank_table(flow_df, "글로벌", top_n=1)
    local_top = build_today_flow_rank_table(flow_df, "국내상장 대표 ETF", top_n=1)
    # 스윙 점수 기준 TOP (스윙 트레이딩용 — 단기 방향 전환 민감)
    us_swing_top3  = build_today_flow_rank_table(flow_df, "미국 섹터",  score_col="스윙점수", top_n=3)
    kr_swing_top3  = build_today_flow_rank_table(flow_df, "한국 섹터",  score_col="스윙점수", top_n=3)
    global_swing_top = build_today_flow_rank_table(flow_df, "글로벌",   score_col="스윙점수", top_n=1)
    sector_rotation_df = calculate_sector_rotation_df(flow_df)

    theme_flow_df = pd.DataFrame()
    theme_rotation_df = pd.DataFrame()
    subtheme_group_df = pd.DataFrame()
    theme_top5 = pd.DataFrame()
    subtheme_top = pd.DataFrame()
    if IMAGE_THEME_FLOW_AVAILABLE:
        theme_flow_df = calculate_image_theme_flow_df("")
        theme_rotation_df = calculate_image_theme_rotation_df(theme_flow_df)
        subtheme_group_df = calculate_image_theme_group_df(theme_flow_df)
        theme_top5, subtheme_top = build_today_theme_flow_tables(
            theme_flow_df,
            theme_rotation_df,
            subtheme_group_df,
        )

    return {
        "flow_df": flow_df,
        "us_top5": us_top5,
        "kr_top5": kr_top5,
        "global_top": global_top,
        "local_top": local_top,
        "us_swing_top3": us_swing_top3,
        "kr_swing_top3": kr_swing_top3,
        "global_swing_top": global_swing_top,
        "sector_rotation_df": sector_rotation_df,
        "theme_flow_df": theme_flow_df,
        "theme_rotation_df": theme_rotation_df,
        "theme_top5": theme_top5,
        "subtheme_top": subtheme_top,
    }


def add_money_flow_row_to_watchlist(row, is_stock: bool = False):
    """ETF/섹터 행 또는 테마 종목 행을 전광판에 추가.

    is_stock=True 이면 개별종목으로 취급(kr_stock / us_stock).
    """
    ticker = sanitize_ticker_value(row.get("Ticker", ""))
    if not ticker:
        return False, "티커가 없어 전광판에 보낼 수 없습니다."
    if is_in_watchlist(ticker):
        return False, f"{ticker}는 이미 전광판에 등록되어 있습니다."

    # ETF 이름 > 종목명 > 섹터 순으로 이름 결정
    name = sanitize_asset_name(
        row.get("ETF 이름", "") or row.get("종목명", "") or row.get("섹터", ""),
        ticker,
    )
    if is_stock:
        default_asset_class = "kr_stock" if is_kr_listed(ticker) else "us_stock"
        is_etf_flag = False
    else:
        default_asset_class = "kr_etf" if is_kr_listed(ticker) else "us_etf_other"
        is_etf_flag = True
    asset_class = infer_asset_class_for_ticker(ticker, default_asset_class)
    st.session_state.watchlist.append(sanitize_watchlist_item({
        "name": name,
        "ticker": ticker,
        "is_etf": is_etf_flag,
        "asset_class": asset_class,
        "fin_score": 0,
    }))
    persist_watchlist()
    return True, f"{name} ({ticker})를 전광판에 추가했습니다."


_LWC_CHART_OPTIONS = {
    "layout": {
        "background": {"type": "solid", "color": "transparent"},
        "textColor": "#94a3b8",
    },
    "grid": {
        "vertLines": {"color": "#1e293b"},
        "horzLines": {"color": "#1e293b"},
    },
    "crosshair": {"mode": 1},
    "rightPriceScale": {"borderColor": "#334155"},
    "timeScale": {"borderColor": "#334155", "timeVisible": False},
}


def render_lwc_candlestick(df: pd.DataFrame, avg_price: float = 0.0, key: str = "lwc_candle") -> bool:
    """TradingView Lightweight Charts 캔들스틱 + MA 라인 렌더링.

    df 컬럼: Open, High, Low, Close, MA5, MA20, MA50, MA120
    Returns True if rendered, False if fallback needed.
    """
    if not _LWC_AVAILABLE or df is None or df.empty:
        return False

    def _to_lwc_time(idx):
        try:
            return idx.strftime("%Y-%m-%d")
        except Exception:
            return str(idx)[:10]

    candle_data = [
        {"time": _to_lwc_time(t), "open": float(o), "high": float(h),
         "low": float(l), "close": float(c)}
        for t, o, h, l, c in zip(
            df.index, df["Open"], df["High"], df["Low"], df["Close"]
        )
        if all(pd.notna(v) for v in [o, h, l, c])
    ]
    if not candle_data:
        return False

    def _ma_series(col_name, color, width=1, dash=False):
        if col_name not in df.columns:
            return None
        data = [
            {"time": _to_lwc_time(t), "value": float(v)}
            for t, v in zip(df.index, df[col_name])
            if pd.notna(v)
        ]
        opts = {"color": color, "lineWidth": width, "title": col_name}
        if dash:
            opts["lineStyle"] = 2   # dashed
        return {"type": "Line", "data": data, "options": opts}

    series = [
        {
            "type": "Candlestick",
            "data": candle_data,
            "options": {
                "upColor": "#22c55e", "downColor": "#ef4444",
                "borderUpColor": "#22c55e", "borderDownColor": "#ef4444",
                "wickUpColor": "#22c55e", "wickDownColor": "#ef4444",
            },
        },
    ]
    for ma in [
        _ma_series("MA5",   "#22c55e", 1),
        _ma_series("MA20",  "#fbbf24", 2),
        _ma_series("MA50",  "#60a5fa", 2),
        _ma_series("MA120", "#94a3b8", 1, dash=True),
    ]:
        if ma:
            series.append(ma)

    # 평단가 기준선
    if avg_price and avg_price > 0:
        series.append({
            "type": "Line",
            "data": [
                {"time": candle_data[0]["time"],  "value": avg_price},
                {"time": candle_data[-1]["time"], "value": avg_price},
            ],
            "options": {"color": "#2ecc71", "lineWidth": 1,
                        "lineStyle": 2, "title": "평단가"},
        })

    chart_opts = {**_LWC_CHART_OPTIONS, "height": 600}
    renderLightweightCharts([{"chart": chart_opts, "series": series}], key=key)
    return True


@st.cache_data(ttl=900, show_spinner=False)
def _load_benchmark_returns(bench_ticker: str) -> pd.Series:
    """벤치마크 6개월 일별 수익률(%) 시리즈를 반환 (캐시)."""
    try:
        df = load_price_df(bench_ticker, "6mo")
        if df is None or df.empty or "Close" not in df.columns:
            return pd.Series(dtype=float)
        base = float(df["Close"].iloc[0])
        if base <= 0:
            return pd.Series(dtype=float)
        ret = ((df["Close"] / base) - 1) * 100
        ret.index = pd.to_datetime(ret.index).normalize()
        return ret
    except Exception:
        return pd.Series(dtype=float)


# ── 섹터/구분별 벤치마크 매핑 ────────────────────────────────────────
# (bench_ticker, bench_label) | None → 비교 불가(절대수익 표시)
_SECTOR_BENCH_MAP: dict[str, tuple[str, str] | None] = {
    # ── 금/실물 ──────────────────────────────────────────────────────
    "금":           ("GLD",       "금(GLD)"),
    "한국 금현물":  ("GLD",       "금(GLD)"),
    "금 커버드콜":  ("GLD",       "금(GLD)"),
    "국제금커버드콜액티브": ("GLD", "금(GLD)"),
    # ── 채권 ─────────────────────────────────────────────────────────
    "미국 장기채":      ("TLT", "미국장기채(TLT)"),
    "장기채 커버드콜":  ("TLT", "미국장기채(TLT)"),
    "미국 단기채":      ("SHV", "미국단기채(SHV)"),
    "하이일드채권":     ("HYG", "하이일드(HYG)"),
    "종합채권":         ("AGG", "채권(AGG)"),
    "국내 단기채":      ("AGG", "채권(AGG)"),
    "금리형":           ("AGG", "채권(AGG)"),
    # ── 비교 불가 매크로 ─────────────────────────────────────────────
    "공포지수(VIX)":  None,
    "비트코인":       None,
    "미국 달러":      None,
    "머니마켓":       None,
    # ── 글로벌 지역 ──────────────────────────────────────────────────
    "한국":     ("069500.KS", "KODEX200"),
    "일본":     ("EWJ",       "일본주식(EWJ)"),
    "중국":     ("MCHI",      "중국주식(MCHI)"),
    "대만":     ("EWT",       "대만주식(EWT)"),
    "홍콩":     ("EWH",       "홍콩주식(EWH)"),
    "인도":     ("EEM",       "신흥국(EEM)"),
    "베트남":   ("EEM",       "신흥국(EEM)"),
    "브라질":   ("EEM",       "신흥국(EEM)"),
    "멕시코":   ("EEM",       "신흥국(EEM)"),
    "사우디":   ("EEM",       "신흥국(EEM)"),
    "캐나다":   ("SPY",       "S&P500(SPY)"),
    # ── 미국 섹터 ────────────────────────────────────────────────────
    "반도체 iShares": ("SPY", "S&P500(SPY)"),
    "반도체 VanEck":  ("SPY", "S&P500(SPY)"),
    "기술":           ("QQQ", "나스닥100(QQQ)"),
    "소프트웨어":     ("QQQ", "나스닥100(QQQ)"),
    "사이버보안":     ("QQQ", "나스닥100(QQQ)"),
    "로봇/AI":        ("QQQ", "나스닥100(QQQ)"),
    "핀테크":         ("QQQ", "나스닥100(QQQ)"),
    "경기소비재":     ("SPY", "S&P500(SPY)"),
    "필수소비재":     ("SPY", "S&P500(SPY)"),
    "헬스케어":       ("XLV", "헬스케어(XLV)"),
    "바이오":         ("XLV", "헬스케어(XLV)"),
    "금융":           ("XLF", "금융(XLF)"),
    "에너지":         ("XLE", "에너지(XLE)"),
    "유틸리티":       ("XLU", "유틸리티(XLU)"),
    "부동산":         ("VNQ", "리츠(VNQ)"),
    "산업재":         ("XLI", "산업재(XLI)"),
    "소재":           ("XLB", "소재(XLB)"),
    "커뮤니케이션":   ("SPY", "S&P500(SPY)"),
    "항공방산":       ("SPY", "S&P500(SPY)"),
    "방산":           ("SPY", "S&P500(SPY)"),
    "주택건설":       ("SPY", "S&P500(SPY)"),
    "인프라":         ("SPY", "S&P500(SPY)"),
    "신재생":         ("SPY", "S&P500(SPY)"),
    "원자재(구리)":   ("SPY", "S&P500(SPY)"),
    "리튬/EV밸류체인":("SPY", "S&P500(SPY)"),
    "우라늄/원전":    ("SPY", "S&P500(SPY)"),
    # ── 글로벌 AI/인프라 ─────────────────────────────────────────────
    "글로벌AI전력인프라": ("QQQ", "나스닥100(QQQ)"),
    "미국AI전력인프라":   ("QQQ", "나스닥100(QQQ)"),
    "글로벌 AI":          ("QQQ", "나스닥100(QQQ)"),
    "미국 나스닥":        ("QQQ", "나스닥100(QQQ)"),
    "미국 나스닥100":     ("QQQ", "나스닥100(QQQ)"),
    "미국 반도체":        ("SOXX","반도체(SOXX)"),
    "미국 S&P500":        ("SPY", "S&P500(SPY)"),
    # ── 월배당 커버드콜 ──────────────────────────────────────────────
    "나스닥100 커버드콜": ("QQQ", "나스닥100(QQQ)"),
    "S&P500 커버드콜":    ("SPY", "S&P500(SPY)"),
    "미국 테크 커버드콜": ("QQQ", "나스닥100(QQQ)"),
    "미국 배당":          ("SPY", "S&P500(SPY)"),
    "미국 배당 커버드콜": ("SPY", "S&P500(SPY)"),
    "KOSPI200 커버드콜":  ("069500.KS", "KODEX200"),
    "국내 고배당":        ("069500.KS", "KODEX200"),
    "은행 고배당":        ("139270.KS", "TIGER금융"),
    # ── 국내 섹터 ────────────────────────────────────────────────────
    "코스피":       ("069500.KS", "KODEX200"),
    "코스닥":       ("229200.KS", "KODEX코스닥150"),
    "반도체":       ("069500.KS", "KODEX200"),
    "전력인프라":   ("069500.KS", "KODEX200"),
    "전력기기":     ("069500.KS", "KODEX200"),
    "2차전지":      ("069500.KS", "KODEX200"),
    "바이오":       ("069500.KS", "KODEX200"),
    "건설/유틸":    ("069500.KS", "KODEX200"),
    "조선":         ("069500.KS", "KODEX200"),
    "방산":         ("069500.KS", "KODEX200"),
    "화장품":       ("069500.KS", "KODEX200"),
    "K-뷰티":       ("069500.KS", "KODEX200"),
    "웹툰&게임":    ("229200.KS", "KODEX코스닥150"),
    "IT/기술":      ("069500.KS", "KODEX200"),
    "에너지":       ("069500.KS", "KODEX200"),
    "원자력TOP10":  ("069500.KS", "KODEX200"),
    "원자력":       ("069500.KS", "KODEX200"),
    "부동산":       ("069500.KS", "KODEX200"),
    "KOSPI200 대형":("069500.KS", "KODEX200"),
    "헬스케어":     ("069500.KS", "KODEX200"),
    "인도 Nifty50": ("EEM",       "신흥국(EEM)"),
    "일본 Nikkei225":("EWJ",      "일본주식(EWJ)"),
    "중국 CSI300":  ("MCHI",      "중국주식(MCHI)"),
    "중국 전기차":  ("MCHI",      "중국주식(MCHI)"),
}


def _resolve_benchmark(ticker: str, sector: str = "", group: str = "") -> tuple[str | None, str]:
    """섹터/구분/티커 suffix 기반으로 (bench_ticker, bench_label) 결정."""
    # 1) 섹터명 직접 매칭
    for key in [sector, group]:
        if key and key in _SECTOR_BENCH_MAP:
            result = _SECTOR_BENCH_MAP[key]
            if result is None:
                return None, ""          # 비교 불가
            return result

    # 2) suffix 기반 기본값
    _upper = ticker.upper()
    if _upper.endswith(".KS") or _upper.endswith(".KQ"):
        return "069500.KS", "KODEX200"
    return "SPY", "S&P500(SPY)"


def render_lwc_baseline(
    ticker: str,
    label: str = "",
    key: str = "lwc_baseline",
    sector: str = "",
    group: str = "",
) -> bool:
    """선택 ETF/종목의 벤치마크 대비 초과수익률을 Baseline 차트로 렌더링.

    기준선(0%) = 벤치마크와 동일한 수익률.
    초록(위) = 벤치마크보다 강함, 빨강(아래) = 벤치마크보다 약함.

    sector: 돈흐름 '섹터' 컬럼값 (우선 사용)
    group:  돈흐름 '구분' 컬럼값 (sector 미매칭 시 fallback)
    """
    if not _LWC_AVAILABLE or not ticker:
        return False

    bench_ticker, bench_label = _resolve_benchmark(ticker, sector, group)

    # 비교 불가 자산 → 절대수익률(자기 자신 기준)로 표시
    if bench_ticker is None:
        bench_ticker = ticker
        bench_label  = "자기자신(절대수익)"

    try:
        df = load_price_df(ticker, "6mo")
    except Exception:
        return False
    if df is None or df.empty or "Close" not in df.columns:
        return False

    base = float(df["Close"].iloc[0])
    if base <= 0:
        return False

    bench_ret = _load_benchmark_returns(bench_ticker)

    def _to_lwc_time(idx):
        try:
            return idx.strftime("%Y-%m-%d")
        except Exception:
            return str(idx)[:10]

    data = []
    for t, c in zip(df.index, df["Close"]):
        if not pd.notna(c):
            continue
        etf_ret = (float(c) / base - 1) * 100
        t_norm  = pd.Timestamp(t).normalize()
        b_ret   = float(bench_ret.get(t_norm, 0.0)) if not bench_ret.empty else 0.0
        excess  = round(etf_ret - b_ret, 3)
        data.append({"time": _to_lwc_time(t), "value": excess})

    if not data:
        return False

    # 벤치마크 자신 비교(절대수익)이면 타이틀 다르게
    is_absolute = (bench_ticker == ticker)
    chart_title = (
        f"{label or ticker} (절대수익률, 6M)"
        if is_absolute
        else f"{label or ticker} vs {bench_label}"
    )
    caption_txt = (
        f"⚠️ 비교 기준이 없는 자산 — 6개월 절대수익률로 표시"
        if is_absolute
        else (
            f"🟢 초록 = {bench_label}보다 강함 &nbsp;|&nbsp; "
            f"🔴 빨강 = {bench_label}보다 약함 &nbsp;|&nbsp; 단위: %p (6개월)"
        )
    )

    series = [{
        "type": "Baseline",
        "data": data,
        "options": {
            "baseValue":      {"type": "price", "price": 0},
            "topLineColor":    "#22c55e",
            "topFillColor1":   "rgba(34,197,94,0.28)",
            "topFillColor2":   "rgba(34,197,94,0.02)",
            "bottomLineColor": "#ef4444",
            "bottomFillColor1":"rgba(239,68,68,0.02)",
            "bottomFillColor2":"rgba(239,68,68,0.28)",
            "lineWidth": 2,
            "title": chart_title,
        },
    }]

    chart_opts = {
        **_LWC_CHART_OPTIONS,
        "height": 260,
        "rightPriceScale": {
            **_LWC_CHART_OPTIONS.get("rightPriceScale", {}),
            "scaleMargins": {"top": 0.1, "bottom": 0.1},
        },
    }
    renderLightweightCharts([{"chart": chart_opts, "series": series}], key=key)
    st.caption(caption_txt, unsafe_allow_html=True)
    return True


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
    # 섹터·구분 정보 추출 (벤치마크 정확도 향상)
    _flow_sector = ""
    _flow_group  = ""
    if not selected_flow.empty and "섹터" in view_df.columns:
        _row_full = view_df[view_df["Ticker"] == ticker]
        if not _row_full.empty:
            _flow_sector = str(_row_full.iloc[0].get("섹터", ""))
            _flow_group  = str(_row_full.iloc[0].get("구분", ""))
    comp_df, etf_row = get_kr_etf_composition(ticker)

    # ── 6개월 초과수익률 Baseline 차트 ───────────────────────────────
    _bl_rendered = render_lwc_baseline(
        ticker,
        label=flow_name,
        key=f"lwc_baseline_{ticker}",
        sector=_flow_sector,
        group=_flow_group,
    )
    if not _bl_rendered and _LWC_AVAILABLE:
        st.caption(f"📈 {ticker} 가격 데이터를 불러오지 못했습니다.")

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

    # ── 전광판 추가 버튼 ──────────────────────────────────────────────
    selected_flow_row = view_df[view_df["Ticker"].astype(str).str.strip() == ticker.strip()]
    row_dict = selected_flow_row.iloc[0].to_dict() if not selected_flow_row.empty else {}
    if row_dict:
        already = is_in_watchlist(ticker)
        if already:
            st.success(f"✅ {flow_name} ({ticker})는 이미 전광판에 등록되어 있습니다.")
        else:
            if st.button(
                f"📌 전광판에 추가 — {flow_name} ({ticker})",
                key="mf_comp_add_watchlist",
                use_container_width=False,
            ):
                ok, msg = add_money_flow_row_to_watchlist(row_dict)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)


def render_rotation_panel(flow_df: pd.DataFrame):
    """섹터 로테이션 4분면 차트 + 테이블."""
    st.markdown("#### 🔄 섹터 로테이션 맵")
    st.caption(
        "벤치마크(KOSPI200·S&P500) 대비 **상대강도(RS_3m)**와 **RS모멘텀**으로 자금 이동 방향 감지  \n"
        "**주도** → 약화 → 소외 → 개선 → **주도** 순으로 순환"
    )

    rot_df = calculate_rotation_df(flow_df)
    if rot_df is None or rot_df.empty:
        st.info("로테이션 데이터를 계산할 수 없습니다.")
        return

    QUAD_COLOR = {"주도": "#16a34a", "약화": "#ea580c", "개선": "#2563eb", "소외": "#dc2626", "-": "#94a3b8"}
    QUAD_EMOJI = {"주도": "🟢 주도", "약화": "🟠 약화", "개선": "🔵 개선", "소외": "🔴 소외", "-": "⬜ -"}

    group_options = [g for g in ["한국 섹터", "미국 섹터", "글로벌"] if g in rot_df["구분"].values]
    if not group_options:
        st.info("데이터 없음")
        return

    tabs = st.tabs(group_options)
    for tab, group in zip(tabs, group_options):
        with tab:
            gdf = rot_df[rot_df["구분"] == group].dropna(subset=["RS_3m", "RS모멘텀"]).copy()
            if gdf.empty:
                st.info("해당 그룹 데이터 없음")
                continue

            # ── 4분면 scatter ──────────────────────────────────────────────
            fig = go.Figure()

            # 사분면 배경
            x_max = max(abs(gdf["RS_3m"].max()), abs(gdf["RS_3m"].min()), 0.05) * 1.4
            y_max = max(abs(gdf["RS모멘텀"].max()), abs(gdf["RS모멘텀"].min()), 0.03) * 1.4
            quad_bg = [
                (0, x_max,  0, y_max,  "rgba(22,163,74,0.07)"),   # 주도 (우상)
                (0, x_max,  -y_max, 0, "rgba(234,88,12,0.07)"),    # 약화 (우하)
                (-x_max, 0, 0, y_max,  "rgba(37,99,235,0.07)"),    # 개선 (좌상)
                (-x_max, 0, -y_max, 0, "rgba(220,38,38,0.07)"),    # 소외 (좌하)
            ]
            for x0, x1, y0, y1, color in quad_bg:
                fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
                              fillcolor=color, line_width=0, layer="below")

            # 기준선
            fig.add_hline(y=0, line_dash="dash", line_color="#94a3b8", line_width=1)
            fig.add_vline(x=0, line_dash="dash", line_color="#94a3b8", line_width=1)

            # 사분면 라벨
            for label, x, y, color in [
                ("🟢 주도", x_max * 0.85,  y_max * 0.85,  "#16a34a"),
                ("🟠 약화", x_max * 0.85, -y_max * 0.85,  "#ea580c"),
                ("🔵 개선", -x_max * 0.85, y_max * 0.85,  "#2563eb"),
                ("🔴 소외", -x_max * 0.85, -y_max * 0.85, "#dc2626"),
            ]:
                fig.add_annotation(x=x, y=y, text=f"<b>{label}</b>",
                                   showarrow=False, font=dict(color=color, size=12))

            # 섹터 점
            fig.add_trace(go.Scatter(
                x=gdf["RS_3m"] * 100,
                y=gdf["RS모멘텀"] * 100,
                mode="markers+text",
                text=gdf["섹터"],
                textposition="top center",
                textfont=dict(size=10),
                marker=dict(
                    size=14,
                    color=[QUAD_COLOR.get(q, "#94a3b8") for q in gdf["로테이션"]],
                    line=dict(width=1, color="#fff"),
                ),
                customdata=gdf[["3개월수익률", "1개월수익률", "거래량증가", "상태"]].values,
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "RS_3m: %{x:.1f}%<br>"
                    "RS모멘텀: %{y:.1f}%<br>"
                    "3개월: %{customdata[0]:.1%}<br>"
                    "1개월: %{customdata[1]:.1%}<br>"
                    "거래량↑: %{customdata[2]:.1%}<br>"
                    "상태: %{customdata[3]}<extra></extra>"
                ),
                showlegend=False,
            ))

            fig.update_layout(
                height=420,
                xaxis=dict(title="RS_3m (벤치마크 대비 3개월 초과수익, %)",
                           range=[-x_max * 100, x_max * 100], zeroline=False),
                yaxis=dict(title="RS모멘텀 (가속도 차이, %)",
                           range=[-y_max * 100, y_max * 100], zeroline=False),
                margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor="#0f172a",
                paper_bgcolor="#0f172a",
                font=dict(color="#e2e8f0"),
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── 요약 테이블 ────────────────────────────────────────────────
            tbl = gdf[["섹터", "로테이션", "RS_3m", "RS모멘텀", "3개월수익률", "1개월수익률", "2주수익률", "상태"]].copy()
            tbl["로테이션"] = tbl["로테이션"].map(QUAD_EMOJI)
            for col in ["RS_3m", "RS모멘텀", "3개월수익률", "1개월수익률", "2주수익률"]:
                tbl[col] = tbl[col].apply(lambda v: f"{v*100:+.1f}%" if finite_num(v) else "-")
            tbl = tbl.sort_values("로테이션")
            st.dataframe(tbl, use_container_width=True, hide_index=True,
                         column_config={
                             "RS_3m":     st.column_config.TextColumn("RS(3m)", help="벤치마크 대비 3개월 초과수익"),
                             "RS모멘텀":  st.column_config.TextColumn("RS모멘텀", help="벤치마크 대비 가속도 차이. 양수=빨라짐"),
                             "3개월수익률": st.column_config.TextColumn("3M"),
                             "1개월수익률": st.column_config.TextColumn("1M"),
                             "2주수익률":   st.column_config.TextColumn("2W"),
                         })


# ---------------------------------------------------------------------------
# 돈흐름 레이더 해석 헬퍼
# ---------------------------------------------------------------------------

def _flow_get_val(flow_df, ticker: str, col: str):
    """flow_df에서 특정 티커 단일 수치 추출. 없으면 np.nan."""
    r = flow_df[flow_df["Ticker"].astype(str) == ticker]
    if r.empty:
        return np.nan
    v = r.iloc[0].get(col, np.nan)
    return float(v) if finite_num(v) else np.nan


def _build_global_flow_reading(flow_df, rankable_df, leader, accel_leader, weak) -> str:
    """ETF 돈흐름 레이더 해석 HTML 생성.

    분석 축:
        1. 리더 vs 가속도 1위 괴리 → 리더 교체 신호 여부
        2. 시장 폭(Market Breadth) → 광범위 상승/선별/방어/약세
        3. 매크로 리스크온·오프 → VIX/HYG/TLT/IBIT/UUP 방향성
        4. 상태 분포 요약 → 우호/경계/부진 개수 + 과열·급락 알림
    """
    parts = []

    # ── 1. 리더 vs 가속도 ──────────────────────────────────────────────
    l_name = f"{leader['섹터']} ({leader['Ticker']})"
    a_name = f"{accel_leader['섹터']} ({accel_leader['Ticker']})"
    w_name = f"{weak['섹터']} ({weak['Ticker']})"
    l_3m   = leader.get("3개월수익률", np.nan)
    a_acc  = accel_leader.get("가속도", np.nan)

    if leader["Ticker"] == accel_leader["Ticker"]:
        parts.append(
            f"돈흐름 1위 <b>{l_name}</b>이 가속도도 1위를 겸하고 있어 "
            f"추세가 한 방향으로 강화 중입니다."
            + (f" (3M {l_3m*100:+.1f}%)" if finite_num(l_3m) else "")
        )
    else:
        parts.append(
            f"기존 강세 1위는 <b>{l_name}</b>"
            + (f" (3M {l_3m*100:+.1f}%)" if finite_num(l_3m) else "")
            + f"이지만, 가속도 1위는 <b>{a_name}</b>"
            + (f" (가속 {a_acc*100:+.1f}%p)" if finite_num(a_acc) else "")
            + "입니다. 리더 교체 초기일 수 있으므로 두 섹터를 함께 주목합니다."
        )
    parts.append(f"현재 가장 약한 구간은 <b>{w_name}</b>입니다.")

    # ── 2. 시장 폭 ────────────────────────────────────────────────────
    total  = max(len(rankable_df), 1)
    pos_3m  = int((rankable_df["3개월수익률"].fillna(0) > 0).sum())
    pos_6m  = int((rankable_df["6개월수익률"].fillna(0) > 0).sum())
    pos_acc = int((rankable_df["가속도"].fillna(0) > 0).sum())
    b3 = pos_3m / total
    ba = pos_acc / total

    if b3 >= 0.70:
        bw_label, bw_hint = "광범위 상승 국면", "시장 전반에 자금이 유입되는 환경입니다."
    elif b3 >= 0.50:
        bw_label, bw_hint = "선별적 상승", "강한 섹터에 집중하고 약한 섹터는 피합니다."
    elif b3 >= 0.35:
        bw_label, bw_hint = "방어 국면", "상승 섹터가 소수에 한정. 비중 관리를 우선합니다."
    else:
        bw_label, bw_hint = "광범위 하락", "대부분 ETF가 하락 중. 안전자산 또는 현금 비중 확대를 검토합니다."

    bw_line = (
        f"시장 폭: 3M 상승 ETF <b>{pos_3m}/{total}개 ({b3*100:.0f}%)</b> → <b>{bw_label}</b>. {bw_hint}"
    )
    if ba >= 0.60:
        bw_line += f" 가속 ETF도 {pos_acc}개({ba*100:.0f}%)로 상승 동력이 확산 중입니다."
    elif ba < 0.40:
        bw_line += f" 단, 가속 ETF는 {pos_acc}개({ba*100:.0f}%)에 그쳐 상승 동력이 약해지고 있습니다."
    parts.append(bw_line)

    # ── 3. 매크로 리스크온/오프 ────────────────────────────────────────
    vix_3m  = _flow_get_val(flow_df, "^VIX",  "3개월수익률")
    hyg_3m  = _flow_get_val(flow_df, "HYG",   "3개월수익률")
    tlt_3m  = _flow_get_val(flow_df, "TLT",   "3개월수익률")
    ibit_3m = _flow_get_val(flow_df, "IBIT",  "3개월수익률")
    uup_3m  = _flow_get_val(flow_df, "UUP",   "3개월수익률")
    slv_3m  = _flow_get_val(flow_df, "SLV",   "3개월수익률")

    ron, rof = 0, 0
    items = []

    if finite_num(vix_3m):
        if vix_3m > 0.10:
            rof += 1; items.append(f"VIX <span style='color:#f87171'>+{vix_3m*100:.0f}%</span> 공포 확대")
        elif vix_3m < -0.05:
            ron += 1; items.append(f"VIX <span style='color:#4ade80'>{vix_3m*100:.0f}%</span> 공포 완화")

    if finite_num(hyg_3m):
        if hyg_3m > 0.01:
            ron += 1; items.append(f"HYG <span style='color:#4ade80'>+{hyg_3m*100:.1f}%</span> 신용 수요↑")
        elif hyg_3m < -0.03:
            rof += 1; items.append(f"HYG <span style='color:#f87171'>{hyg_3m*100:.1f}%</span> 신용 수요↓")

    if finite_num(ibit_3m):
        if ibit_3m > 0.10:
            ron += 1; items.append(f"BTC <span style='color:#4ade80'>+{ibit_3m*100:.0f}%</span> 위험선호")
        elif ibit_3m < -0.15:
            rof += 1; items.append(f"BTC <span style='color:#f87171'>{ibit_3m*100:.0f}%</span> 위험회피")

    if finite_num(tlt_3m):
        if tlt_3m > 0.05:
            rof += 1; items.append(f"TLT <span style='color:#fbbf24'>+{tlt_3m*100:.1f}%</span> 안전자산 피신↑")
        elif tlt_3m < -0.05:
            ron += 1; items.append(f"TLT <span style='color:#94a3b8'>{tlt_3m*100:.1f}%</span> 채권 이탈·주식 선호")

    if finite_num(uup_3m):
        if uup_3m > 0.03:
            rof += 1; items.append(f"달러 <span style='color:#fbbf24'>+{uup_3m*100:.1f}%</span> 강달러(신흥국 부담)")
        elif uup_3m < -0.02:
            ron += 1; items.append(f"달러 <span style='color:#4ade80'>{uup_3m*100:.1f}%</span> 약달러(위험자산 우호)")

    if finite_num(slv_3m):
        if slv_3m > 0.08:
            items.append(f"은 <span style='color:#94a3b8'>+{slv_3m*100:.0f}%</span> (실물 수요·인플레 기대)")

    if items:
        if ron > rof + 1:
            sig = "🟢 리스크온"
        elif rof > ron + 1:
            sig = "🔴 리스크오프"
        elif rof >= 2:
            sig = "🟠 리스크오프 기울기"
        else:
            sig = "🟡 혼조세"
        parts.append(
            f"<b>매크로 {sig}</b> — {' &nbsp;·&nbsp; '.join(items)}"
        )

    # ── 4. 상태 분포 ────────────────────────────────────────────────────
    if "상태" in rankable_df.columns:
        sc = rankable_df["상태"].value_counts()
        n_pos   = sum(sc.get(s, 0) for s in ["강세 가속", "신규 유입", "주도 유지", "급반등"])
        n_warn  = sum(sc.get(s, 0) for s in ["과열경보", "둔화 경고"])
        n_neg   = sum(sc.get(s, 0) for s in ["소외 지속", "급락 경보", "고변동"])
        n_hot   = sc.get("과열경보", 0)
        n_crash = sc.get("급락 경보", 0)

        dist = (
            f"상태 분포: <span style='color:#4ade80'>우호 {n_pos}개</span>"
            f" · <span style='color:#fbbf24'>경계 {n_warn}개</span>"
            f" · <span style='color:#f87171'>부진 {n_neg}개</span>"
        )
        if n_hot >= 3:
            dist += f" — ⚠️ 과열경보 {n_hot}개: 고점권 추격 매수 주의"
        if n_crash >= 2:
            dist += f" — 💥 급락 경보 {n_crash}개: 시장 구조 점검 필요"
        parts.append(dist)

    return "<br>".join(parts)


def _build_rotation_reading(rotation_df) -> str:
    """전체 테마 로테이션 해석 HTML 생성.

    분석 축:
        1. 점수·확산·거래량 1위 일치 여부 → 진짜 주도 테마 vs 쏠림
        2. 테마 폭(양수 점수 비율) → 전반 상승/선별/부진
        3. 가장 약한 테마 명시
    """
    parts = []
    total = len(rotation_df)
    if total == 0:
        return ""

    leader        = rotation_df.iloc[0]
    breadth_leader = rotation_df.sort_values("상승종목비율", ascending=False).iloc[0]
    volume_leader  = rotation_df.sort_values("거래량증가", ascending=False, na_position="last").iloc[0]
    accel_leader   = rotation_df.sort_values("가속도", ascending=False, na_position="last").iloc[0]
    weak           = rotation_df.sort_values("테마돈흐름점수", ascending=True).iloc[0]

    l_name  = str(leader["테마"])
    bl_name = str(breadth_leader["테마"])
    vl_name = str(volume_leader["테마"])
    al_name = str(accel_leader["테마"])
    l_score = leader.get("테마돈흐름점수", np.nan)

    pos_themes   = int((rotation_df["테마돈흐름점수"].fillna(-999) > 0).sum())
    accel_themes = int((rotation_df["가속도"].fillna(0) > 0).sum())
    b_ratio = pos_themes / max(total, 1)

    # ── 1. 리더 일치성 ─────────────────────────────────────────────────
    matches = sum([l_name == bl_name, l_name == vl_name, l_name == al_name])
    if matches == 3:
        parts.append(
            f"<b>{l_name}</b>이 점수·상승 확산·가속도·거래량 모두 1위입니다. "
            f"3가지 축이 일치하는 강한 주도 테마 신호입니다."
            + (f" (스코어 {l_score:.1f})" if finite_num(l_score) else "")
        )
    elif matches == 2:
        diff = [n for n in [bl_name, vl_name, al_name] if n != l_name]
        parts.append(
            f"점수 1위 <b>{l_name}</b>이 주요 지표 2개 이상에서 1위를 겸합니다. "
            + (f"단, {diff[0]}이 일부 지표에서 앞서고 있어 병행 모니터링을 권장합니다." if diff else "")
        )
    else:
        parts.append(
            f"점수 1위 <b>{l_name}</b>, 확산 1위 <b>{bl_name}</b>, "
            f"가속 1위 <b>{al_name}</b>, 거래량 1위 <b>{vl_name}</b>가 서로 다릅니다. "
            f"테마 간 순환이 빠르게 전개 중이므로 각 테마의 지속성을 개별 확인합니다."
        )

    # ── 2. 테마 폭 ─────────────────────────────────────────────────────
    if b_ratio >= 0.65:
        parts.append(
            f"테마 {pos_themes}/{total}개 양수 ({b_ratio*100:.0f}%) → <b>테마 전반 상승</b>. "
            f"가속 테마도 {accel_themes}개로 동력이 넓게 분포합니다."
        )
    elif b_ratio >= 0.45:
        parts.append(
            f"테마 {pos_themes}/{total}개 양수 ({b_ratio*100:.0f}%) → <b>선별적 상승</b>. "
            f"상위 테마와 하위 테마 간 격차가 벌어지는 구간입니다."
        )
    else:
        parts.append(
            f"테마 {pos_themes}/{total}개만 양수 ({b_ratio*100:.0f}%) → <b>테마 전반 부진</b>. "
            f"방어적 접근 또는 매크로 이벤트 확인이 먼저입니다."
        )

    # ── 3. 약세 테마 ───────────────────────────────────────────────────
    w_score = weak.get("테마돈흐름점수", np.nan)
    w_state = str(weak.get("상태", ""))
    parts.append(
        f"현재 가장 약한 테마는 <b>{weak['테마']}</b>"
        + (
            f" (스코어 {w_score:.1f}"
            + (f" · {w_state}" if w_state not in ("", "nan") else "")
            + ")"
            if finite_num(w_score) else ""
        )
        + "입니다."
    )

    return "<br>".join(parts)


def _build_theme_detail_reading(group_df, leader, accel_leader, weak) -> str:
    """테마 하위테마별 상세 해석 HTML 생성.

    분석 축:
        1. 점수 1위 vs 가속도 1위 괴리 여부
        2. 하위테마 폭(양수 점수 비율)
        3. 1위 하위테마 3M vs 6M 지속성
        4. 상위종목 쏠림 경고
        5. 약한 하위테마 명시
    """
    parts = []
    total_sub = len(group_df)
    pos_sub   = int((group_df["돈흐름점수"].fillna(-999) > 0).sum())
    b_ratio   = pos_sub / max(total_sub, 1)

    l_name = str(leader["하위테마"])
    a_name = str(accel_leader["하위테마"])
    w_name = str(weak["하위테마"])
    l_r3   = leader.get("3개월수익률", np.nan)
    l_r6   = leader.get("6개월수익률", np.nan)
    a_acc  = accel_leader.get("가속도", np.nan)

    # ── 1. 리더 vs 가속 ────────────────────────────────────────────────
    if leader["하위테마"] == accel_leader["하위테마"]:
        parts.append(
            f"<b>{l_name}</b>이 점수와 가속도 모두 1위입니다."
            + (f" (3M {l_r3*100:+.1f}%)" if finite_num(l_r3) else "")
            + " 추세가 더 강화되는 중입니다."
        )
    else:
        parts.append(
            f"점수 1위 <b>{l_name}</b>"
            + (f" (3M {l_r3*100:+.1f}%)" if finite_num(l_r3) else "")
            + f", 가속도 1위 <b>{a_name}</b>"
            + (f" (가속 {a_acc*100:+.1f}%p)" if finite_num(a_acc) else "")
            + f". {a_name}의 최근 탄력이 더 강해지고 있으므로 두 하위테마를 함께 주목합니다."
        )

    # ── 2. 하위테마 폭 ─────────────────────────────────────────────────
    if b_ratio >= 0.70:
        parts.append(
            f"하위테마 <b>{pos_sub}/{total_sub}개</b> 양수 → 테마 내 흐름이 전반적으로 상승 중입니다."
        )
    elif b_ratio >= 0.50:
        parts.append(
            f"하위테마 <b>{pos_sub}/{total_sub}개</b> 양수 → 일부 하위테마 중심 구간. 점수 높은 하위테마 집중 접근을 권장합니다."
        )
    else:
        parts.append(
            f"하위테마 <b>{pos_sub}/{total_sub}개</b>만 양수 → 테마 내 흐름 분산. 상위 하위테마로 압축이 필요합니다."
        )

    # ── 3. 1위 지속성 (3M vs 6M) ───────────────────────────────────────
    if finite_num(l_r3) and finite_num(l_r6):
        r3v, r6v = float(l_r3), float(l_r6)
        if r3v > 0 and r6v > 0:
            if r3v > r6v * 1.2:
                parts.append(
                    f"1위 <b>{l_name}</b>의 3M({r3v*100:+.1f}%)이 6M({r6v*100:+.1f}%)보다 강해 <b>최근 상승이 가속</b>되고 있습니다."
                )
            else:
                parts.append(
                    f"1위 <b>{l_name}</b>이 3M({r3v*100:+.1f}%)·6M({r6v*100:+.1f}%) 모두 양호해 <b>추세가 지속</b> 중입니다."
                )
        elif r3v > 0 >= r6v:
            parts.append(
                f"1위 <b>{l_name}</b>의 3M({r3v*100:+.1f}%)은 양수이나 6M({r6v*100:+.1f}%)은 부진합니다. "
                f"<b>단기 반등</b>인지 추세 전환인지 추가 확인이 필요합니다."
            )

    # ── 4. 쏠림 경고 ───────────────────────────────────────────────────
    conc = leader.get("상위종목쏠림", np.nan)
    if finite_num(conc) and float(conc) > 0.60:
        parts.append(
            f"⚠️ <b>{l_name}</b> 내 상위종목 쏠림 {float(conc):.2f} — "
            f"소수 종목에 점수가 집중되어 있어 리더 종목 훼손 시 하위테마 점수 급락 가능성이 있습니다."
        )

    # ── 5. 약세 하위테마 ───────────────────────────────────────────────
    w_r3 = weak.get("3개월수익률", np.nan)
    parts.append(
        f"현재 가장 약한 하위테마는 <b>{w_name}</b>"
        + (f" (3M {float(w_r3)*100:+.1f}%)" if finite_num(w_r3) else "")
        + "입니다."
    )

    return "<br>".join(parts)


def render_money_flow_etf_section():
    st.subheader("🌊 글로벌 자금 흐름 레이더")
    st.caption("미국/한국 섹터, 국내상장 대표 ETF, 월배당 ETF 대표군의 가격 모멘텀과 거래량 증가를 함께 비교합니다.")

    if not should_run_heavy_analysis(
        "money_flow_lazy",
        "돈흐름 레이더는 여러 ETF 가격을 한 번에 조회하므로 필요할 때만 실행합니다.",
    ):
        return

    # 1. 가장 먼저 데이터를 불러옵니다.
    with st.spinner("ETF 돈흐름 계산 중..."):
        flow_df = calculate_money_flow_df()

    if flow_df.empty:
        st.warning("돈흐름 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    if "거래량증가" not in flow_df.columns:
        flow_df["거래량증가"] = np.nan
    for col in ["이전3개월수익률", "상대3개월수익률"]:
        if col not in flow_df.columns:
            flow_df[col] = np.nan
    if "추격위험" not in flow_df.columns:
        flow_df["추격위험"] = "-"

    # 2. 보기 범위(필터링) 라디오 버튼 구성
    groups = ["전체"] + list(flow_df["구분"].drop_duplicates())
    selected_group = st.radio("보기 범위", groups, horizontal=True, key="money_flow_group")
    
    # 선택된 그룹에 따라 보여줄 데이터셋(view_df) 결정
    view_df = flow_df if selected_group == "전체" else flow_df[flow_df["구분"] == selected_group]
    if selected_group == "전체":
        sort_cols = ["돈흐름점수"]
        ascending = [False]
        if "유니버스순번" in view_df.columns:
            sort_cols.append("유니버스순번")
            ascending.append(True)
        view_df = (
            view_df.sort_values(sort_cols, ascending=ascending, na_position="last")
            .drop_duplicates(subset=["Ticker"], keep="first")
        )

    if view_df.empty:
        st.info("선택한 범위에 표시할 데이터가 없습니다.")
        return

    rankable_df = view_df.dropna(subset=["돈흐름점수"]).copy()

    # 3. 상단 메트릭 카드 (필터링된 view_df 기준 TOP 3 + 거래량)
    top_cols = st.columns(4)
    top_3 = rankable_df.nlargest(3, "돈흐름점수") if not rankable_df.empty else pd.DataFrame()

    for i, (idx, row) in enumerate(top_3.iterrows()):
        with top_cols[i]:
            st.metric(
                label=f"TOP {i+1}: {row['섹터']}",
                value=f"{row['돈흐름점수']:.1f} pts",
                delta=f"{row['1개월수익률']*100:.1f}% (1M)"
            )
    vol_rank = view_df.dropna(subset=["거래량증가"]).sort_values("거래량증가", ascending=False).head(1)
    with top_cols[3]:
        if not vol_rank.empty:
            r = vol_rank.iloc[0]
            st.metric("거래량 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["거래량증가"]))
        else:
            st.metric("거래량 1위", "-", "-")
            
    st.divider() # 시각적 구분을 위한 선

    # 5. 상세 데이터 테이블
    st.markdown("#### 📊 섹터별 상세 지표")

    # 상태 이모지 배지 추가
    _state_badge = {
        # ── 고변동 계열 ──────────────────────────────
        "과열경보": "🔥 과열경보",   # 52주 고점 85% 초과, 추격 위험
        "강세 가속": "🚀 강세 가속", # 상승 + 가속 (좋음)
        "급락 경보": "💥 급락 경보", # 하락 + 가속 (나쁨)
        "급반등":   "⚡ 급반등",     # 저점 40% 미만 + 반등 시도
        "고변동":   "〰️ 고변동",     # 방향 혼재, 관망 필요
        # ── 일반 계열 ────────────────────────────────
        "신규 유입": "🟢 신규 유입",
        "주도 유지": "💚 주도 유지",
        "둔화 경고": "🟡 둔화 경고",
        "소외 지속": "🔴 소외 지속",
        "상대 약세": "🟠 상대 약세",
        "관찰":     "⚪ 관찰",
        "가격부족": "⬛ 가격부족",
    }
    table_df = view_df.copy()
    if "상태" in table_df.columns:
        table_df["상태"] = table_df["상태"].map(lambda s: _state_badge.get(str(s), str(s)))

    # 현재가 포맷 결정
    first_ticker = str(view_df['Ticker'].iloc[0])
    # ── CSV 내보내기까지 올바르게 나오도록 모든 숫자를 문자열로 포맷 ──
    table_df["현재가"] = table_df.apply(lambda r: format_currency(r["현재가"], r["Ticker"]), axis=1)
    table_df["가격수준"] = table_df["가격수준"].apply(
        lambda v: f"{v*100:.1f}%" if finite_num(v) else "-"
    )
    for _score_col in ["돈흐름점수", "스윙점수"]:
        if _score_col in table_df.columns:
            table_df[_score_col] = table_df[_score_col].apply(
                lambda v: f"{v:.1f}" if finite_num(v) else "-"
            )
    for _col in ["2주수익률", "1개월수익률", "3개월수익률", "6개월수익률"]:
        if _col in table_df.columns:
            table_df[_col] = table_df[_col].apply(fmt_flow_pct)
    for _col in ["가속도", "단기가속도", "거래량증가"]:
        if _col in table_df.columns:
            table_df[_col] = table_df[_col].apply(
                lambda v: f"{v:.2f}" if finite_num(v) else "-"
            )
    # 데이터 없는 컬럼 제거 (이전3개월수익률·상대3개월수익률·추격위험 등)
    _drop_if_empty = ["이전3개월수익률", "상대3개월수익률", "추격위험"]
    for _col in _drop_if_empty:
        if _col in table_df.columns:
            _vals = table_df[_col].replace("-", pd.NA).dropna()
            if _vals.empty or (_vals.astype(str).str.strip() == "").all():
                table_df.drop(columns=[_col], inplace=True)

    # 표시할 컬럼 순서 지정 (내부 컬럼 제외)
    _show_cols = [c for c in [
        "구분", "섹터", "Ticker", "ETF 이름", "현재가",
        "상태", "가격수준", "돈흐름점수", "스윙점수",
        "2주수익률", "1개월수익률", "3개월수익률", "6개월수익률",
        "단기가속도", "가속도", "거래량증가",
    ] if c in table_df.columns]

    st.dataframe(
        table_df[_show_cols],
        column_config={
            "가격수준":    st.column_config.TextColumn("52주위치",  help="52주 최저~최고 범위 내 현재 위치"),
            "돈흐름점수":  st.column_config.TextColumn("스코어",    help="1M 12% + 3M 33% + 6M 25% + 중기가속도 15% + 거래량 15% — 장기 모멘텀"),
            "스윙점수":    st.column_config.TextColumn("스윙",      help="2W 25% + 1M 35% + 단기가속도 25% + 거래량 15% — 최근 방향 전환에 민감"),
            "2주수익률":   st.column_config.TextColumn("2W"),
            "1개월수익률": st.column_config.TextColumn("1M"),
            "3개월수익률": st.column_config.TextColumn("3M"),
            "6개월수익률": st.column_config.TextColumn("6M"),
            "단기가속도":  st.column_config.TextColumn("단기가속",  help="최근 1M - 이전 1M. 양수=단기 가속 중"),
            "가속도":      st.column_config.TextColumn("중기가속",  help="최근 3M - 이전 3M 수익률. 양수=중기 가속"),
            "거래량증가":  st.column_config.TextColumn("거래량↑",   help="최근 20일 평균 거래량 / 직전 60일 평균 - 1"),
        },
        hide_index=True,
        use_container_width=True,
    )

    missing_view_df = view_df[view_df["상태"].astype(str).eq("가격부족")].copy() if "상태" in view_df.columns else pd.DataFrame()
    if not missing_view_df.empty:
        st.warning("일부 ETF는 이번 조회에서 가격 데이터가 부족해 점수 계산에서 제외했습니다.")
        st.dataframe(
            missing_view_df[["구분", "섹터", "Ticker", "ETF 이름", "상태"]],
            use_container_width=True,
            hide_index=True,
        )

    if rankable_df.empty:
        st.info("선택한 범위에 계산 가능한 ETF가 없습니다.")
        return

    top_us = flow_df[flow_df["구분"] == "미국 섹터"].head(1)
    top_kr = flow_df[flow_df["구분"] == "한국 섹터"].head(1)
    top_global = flow_df[flow_df["구분"] == "글로벌"].head(1)
    top_income = flow_df[flow_df["구분"] == "월배당 ETF"].head(1)
    # 가속도 1위: 매크로(VIX 등 역방향 지표) 제외 — 상승 VIX가 최상위에 오는 혼선 방지
    top_accel = flow_df[flow_df["구분"] != "매크로"].sort_values("가속도", ascending=False).head(1)
    top_volume = flow_df.dropna(subset=["거래량증가"]).sort_values("거래량증가", ascending=False).head(1)

    s1, s2, s3, s4, s5, s6 = st.columns(6)
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
    if not top_volume.empty:
        r = top_volume.iloc[0]
        s6.metric("거래량 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["거래량증가"]))

    # 해석용 리더 계산 시 매크로(VIX 등 역방향 지표) 제외 — 공포 급등이 리더로 오는 혼선 방지
    _rank_for_interp = (
        rankable_df[rankable_df["구분"] != "매크로"].copy()
        if "구분" in rankable_df.columns and not rankable_df[rankable_df["구분"] != "매크로"].empty
        else rankable_df
    )
    leader = _rank_for_interp.iloc[0]
    accel_leader = _rank_for_interp.sort_values("가속도", ascending=False).iloc[0]
    weak = _rank_for_interp.sort_values("돈흐름점수", ascending=True).iloc[0]

    _reading = _build_global_flow_reading(flow_df, rankable_df, leader, accel_leader, weak)
    st.markdown(
        f"""
<div class='info-panel'>
<b>📊 돈흐름 해석</b><br>
{_reading}
<br><span style='color:#94a3b8;font-size:0.85em;'>가속도 = 최근 3M - 이전 3M 수익률. 시장 폭은 현재 선택 범위 기준. 매크로 신호는 flow_df 전체에서 해당 티커를 직접 조회합니다.</span>
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
            customdata=tree_df[["Ticker", "ETF 이름", "3개월수익률", "6개월수익률", "가속도", "거래량증가", "상태"]],
            hovertemplate=
                "<b>%{label}</b><br>" +
                "%{customdata[1]}<br>" +
                "3개월: %{customdata[2]:.1%}<br>" +
                "6개월: %{customdata[3]:.1%}<br>" +
                "가속도: %{customdata[4]:.1%}<br>" +
                "거래량증가: %{customdata[5]:.1%}<br>" +
                "상태: %{customdata[6]}<extra></extra>"
        ))
        fig_tree.update_layout(template="plotly_dark", height=470, title="돈흐름 히트맵", margin=dict(t=45, l=4, r=4, b=4))
        tree_event = st.plotly_chart(
            fig_tree,
            use_container_width=True,
            key="money_flow_heatmap_select",
            on_select="rerun",
            selection_mode="points",
        )
        st.caption("블록이 클수록 최근 3개월 움직임이 크고, 초록색일수록 가격 흐름과 거래량 확인값이 좋다는 뜻입니다. 블록을 클릭하면 아래에서 구성종목을 확인합니다.")

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
            customdata=view_df[["Ticker", "상태", "돈흐름점수", "거래량증가"]],
            hovertemplate=
                "<b>%{text}</b> (%{customdata[0]})<br>" +
                "6개월: %{x:.1f}%<br>" +
                "3개월: %{y:.1f}%<br>" +
                "상태: %{customdata[1]}<br>" +
                "돈흐름점수: %{customdata[2]:.1f}<br>" +
                "거래량증가: %{customdata[3]:.1%}<extra></extra>"
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

    b1, b2, b3 = st.columns(3)
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

    with b3:
        top_volume_df = view_df.dropna(subset=["거래량증가"]).sort_values("거래량증가", ascending=False).head(12)
        if top_volume_df.empty:
            st.info("거래량 랭킹을 계산할 데이터가 부족합니다.")
        else:
            volume_colors = np.where(top_volume_df["거래량증가"] >= 0, "#22c55e", "#ef4444")
            fig_volume = go.Figure(go.Bar(
                y=top_volume_df["섹터"] + " (" + top_volume_df["Ticker"] + ")",
                x=top_volume_df["거래량증가"] * 100,
                orientation="h",
                marker_color=volume_colors,
                hovertemplate="%{y}<br>거래량증가: %{x:.1f}%<extra></extra>"
            ))
            fig_volume.add_vline(x=0, line_color="#94a3b8")
            fig_volume.update_layout(template="plotly_dark", height=430, title="거래량 증가 랭킹", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_volume, use_container_width=True)

    # ── 섹터 로테이션 맵 ──────────────────────────────────────────────
    render_rotation_panel(flow_df)

    # ── 시장 폭(Market Breadth) + 상태 분포 ─────────────────────────
    st.markdown("#### 📡 시장 폭 & 상태 분포")
    _calc_df = view_df.dropna(subset=["돈흐름점수"])
    _total = max(len(_calc_df), 1)
    _pos_3m  = int((_calc_df["3개월수익률"].fillna(0) > 0).sum())
    _pos_6m  = int((_calc_df["6개월수익률"].fillna(0) > 0).sum())
    _pos_acc = int((_calc_df["가속도"].fillna(0) > 0).sum())
    _avg_pl  = _calc_df["가격수준"].dropna().mean()

    bw1, bw2, bw3, bw4 = st.columns(4)
    bw1.metric(
        "3M 상승 ETF",
        f"{_pos_3m}/{_total}",
        f"{_pos_3m/_total*100:.0f}%",
        help="3개월 수익률이 양수인 ETF 비율. 50% 초과 = 위험자산 선호",
    )
    bw2.metric(
        "6M 상승 ETF",
        f"{_pos_6m}/{_total}",
        f"{_pos_6m/_total*100:.0f}%",
        help="6개월 수익률이 양수인 ETF 비율. 중기 추세 건강도",
    )
    bw3.metric(
        "가속 ETF",
        f"{_pos_acc}/{_total}",
        f"{_pos_acc/_total*100:.0f}%",
        help="가속도가 양수인 ETF 비율. 상승 동력이 붙고 있는 비율",
    )
    bw4.metric(
        "평균 52주 위치",
        f"{_avg_pl:.2f}" if np.isfinite(_avg_pl) else "-",
        help="0=52주 최저, 1=52주 최고. 0.7 이상이면 전반적 고점권",
    )

    # 상태 분포 바 차트
    _state_order = ["과열경보", "강세 가속", "급반등", "고변동", "신규 유입", "주도 유지", "둔화 경고", "관찰", "소외 지속", "급락 경보", "가격부족"]
    _state_colors = {
        "과열경보":  "#f97316",
        "강세 가속": "#22c55e",
        "급반등":    "#a3e635",
        "고변동":    "#94a3b8",
        "신규 유입": "#4ade80",
        "주도 유지": "#16a34a",
        "둔화 경고": "#facc15",
        "관찰":      "#64748b",
        "소외 지속": "#ef4444",
        "급락 경보": "#dc2626",
        "가격부족":  "#374151",
    }
    if "상태" in view_df.columns:
        _state_counts = view_df["상태"].value_counts().reindex(_state_order, fill_value=0)
        _state_counts = _state_counts[_state_counts > 0]
        if not _state_counts.empty:
            fig_state = go.Figure(go.Bar(
                x=_state_counts.index.tolist(),
                y=_state_counts.values.tolist(),
                marker_color=[_state_colors.get(s, "#64748b") for s in _state_counts.index],
                text=_state_counts.values.tolist(),
                textposition="outside",
                hovertemplate="%{x}: %{y}개<extra></extra>",
            ))
            fig_state.update_layout(
                template="plotly_dark",
                height=220,
                title="상태별 ETF 분포",
                margin=dict(t=40, l=10, r=10, b=30),
                yaxis=dict(showticklabels=False),
                showlegend=False,
            )
            st.plotly_chart(fig_state, use_container_width=True)

    show_df = view_df.copy()
    for col in ["가격수준", "기간수익률", "1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률", "6개월수익률", "가속도", "거래량증가"]:
        if col in show_df.columns:
            show_df[col] = show_df[col].apply(fmt_flow_pct)
    show_df["현재가"] = show_df.apply(lambda r: format_currency(r["현재가"], r["Ticker"]), axis=1)
    show_df["돈흐름점수"] = show_df["돈흐름점수"].apply(lambda x: "-" if not finite_num(x) else f"{x:.1f}")
    # 데이터 없는 컬럼 제거
    for _col in ["이전3개월수익률", "상대3개월수익률", "추격위험"]:
        if _col in show_df.columns:
            _vals = show_df[_col].replace("-", pd.NA).dropna()
            if _vals.empty or (_vals.astype(str).str.strip() == "").all():
                show_df.drop(columns=[_col], inplace=True)
    _detail_cols = [c for c in [
        "구분", "섹터", "Ticker", "ETF 이름", "현재가",
        "가격수준", "기간수익률",
        "1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률", "6개월수익률",
        "가속도", "거래량증가", "돈흐름점수", "상태",
    ] if c in show_df.columns]
    st.markdown("#### 돈흐름 상세 테이블")
    st.dataframe(
        show_df[_detail_cols],
        use_container_width=True,
        hide_index=True,
        height=520,
    )


def render_image_theme_rotation_overview(rotation_df, market_label):
    if rotation_df is None or rotation_df.empty:
        st.info("선택한 시장 범위에서 비교할 테마 데이터가 부족합니다.")
        return

    leader = rotation_df.iloc[0]
    breadth_leader = rotation_df.sort_values("상승종목비율", ascending=False).iloc[0]
    volume_leader = rotation_df.sort_values("거래량증가", ascending=False, na_position="last").iloc[0]
    weak = rotation_df.sort_values("테마돈흐름점수", ascending=True).iloc[0]

    st.markdown("#### 전체 테마 로테이션")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("돈흐름 1위", str(leader["테마"]), f"{leader['테마돈흐름점수']:.1f} pts")
    c2.metric("확산 1위", str(breadth_leader["테마"]), fmt_flow_pct(breadth_leader["상승종목비율"]))
    c3.metric("거래량 1위", str(volume_leader["테마"]), fmt_flow_pct(volume_leader["거래량증가"]))
    c4.metric("약한 테마", str(weak["테마"]), f"{weak['테마돈흐름점수']:.1f} pts")

    _rot_reading = _build_rotation_reading(rotation_df)
    st.markdown(
        f"""
<div class='info-panel'>
<b>📊 {market_label} 테마 로테이션 해석</b><br>
{_rot_reading}
<br><span style='color:#94a3b8;font-size:0.85em;'>테마돈흐름점수 = 1M×18 + 3M×36 + 6M×22 + 가속도×18 + 상승비율 보정 + 거래량 보정 - 쏠림 패널티 - 과열 패널티</span>
</div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.05, 1])
    with left:
        chart_df = rotation_df.sort_values("테마돈흐름점수", ascending=True)
        colors = np.where(chart_df["테마돈흐름점수"] >= 0, "#22c55e", "#ef4444")
        fig_score = go.Figure(go.Bar(
            x=chart_df["테마돈흐름점수"],
            y=chart_df["테마"],
            orientation="h",
            marker_color=colors,
            customdata=chart_df[["대표주", "3개월수익률", "가속도", "상승종목비율", "거래량증가", "상위종목쏠림"]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "대표주: %{customdata[0]}<br>"
                "3개월 평균: %{customdata[1]:.1%}<br>"
                "가속도: %{customdata[2]:.1%}<br>"
                "상승종목비율: %{customdata[3]:.1%}<br>"
                "거래량증가: %{customdata[4]:.1%}<br>"
                "상위쏠림: %{customdata[5]:.1%}<extra></extra>"
            ),
        ))
        fig_score.add_vline(x=0, line_color="#94a3b8")
        fig_score.update_layout(
            template="plotly_dark",
            height=max(420, min(640, 150 + len(chart_df) * 40)),
            title="테마돈흐름점수",
            xaxis_title="점수",
            yaxis=dict(autorange="reversed"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_score, use_container_width=True)

    with right:
        fig_quad = go.Figure(go.Scatter(
            x=rotation_df["6개월수익률"] * 100,
            y=rotation_df["3개월수익률"] * 100,
            mode="markers+text",
            text=rotation_df["테마"],
            textposition="top center",
            marker=dict(
                size=np.clip(rotation_df["상승종목비율"].fillna(0.5) * 38, 14, 40),
                color=rotation_df["가속도"] * 100,
                colorscale="RdYlGn",
                cmid=0,
                showscale=True,
                colorbar=dict(title="가속도"),
            ),
            customdata=rotation_df[["대표주", "테마돈흐름점수", "거래량증가", "상위종목쏠림"]],
            hovertemplate=(
                "<b>%{text}</b><br>"
                "대표주: %{customdata[0]}<br>"
                "6개월 평균: %{x:.1f}%<br>"
                "3개월 평균: %{y:.1f}%<br>"
                "점수: %{customdata[1]:.1f}<br>"
                "거래량증가: %{customdata[2]:.1%}<br>"
                "상위쏠림: %{customdata[3]:.1%}<extra></extra>"
            ),
        ))
        fig_quad.add_vline(x=0, line_dash="dash", line_color="#94a3b8")
        fig_quad.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
        fig_quad.update_layout(
            template="plotly_dark",
            height=470,
            title="전체 테마 로테이션",
            xaxis_title="6개월 평균 수익률 %",
            yaxis_title="3개월 평균 수익률 %",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_quad, use_container_width=True)

    show_rotation = rotation_df.copy()
    for col in ["1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률", "6개월수익률", "가속도", "상승종목비율", "거래량증가", "상위종목쏠림", "가격수준"]:
        if col not in show_rotation.columns:
            show_rotation[col] = np.nan
        show_rotation[col] = show_rotation[col].apply(fmt_flow_pct)
    show_rotation["테마돈흐름점수"] = show_rotation["테마돈흐름점수"].apply(lambda x: "-" if not finite_num(x) else f"{x:.1f}")
    # 데이터 없는 컬럼 제거
    for _col in ["이전3개월수익률", "상대3개월수익률", "추격위험"]:
        if _col in show_rotation.columns:
            _vals = show_rotation[_col].replace("-", pd.NA).dropna()
            if _vals.empty or (_vals.astype(str).str.strip() == "").all():
                show_rotation.drop(columns=[_col], inplace=True)
    _rot_cols = [c for c in [
        "테마", "계산종목수", "종목수", "대표주",
        "1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률", "6개월수익률",
        "가속도", "상승종목비율", "거래량증가", "상위종목쏠림",
        "테마돈흐름점수", "상태",
    ] if c in show_rotation.columns]
    st.dataframe(
        show_rotation[_rot_cols],
        use_container_width=True,
        hide_index=True,
        height=360,
    )


def render_power_grid_match_panel(rotation_df):
    if rotation_df is None or rotation_df.empty:
        return

    matched_themes = rotation_df[rotation_df["테마"].isin(["전력·에너지 인프라", "글로벌 원전·SMR"])].copy()
    if matched_themes.empty:
        return

    try:
        etf_df = calculate_money_flow_df()
    except Exception:
        etf_df = pd.DataFrame()

    rows = []
    if etf_df is not None and not etf_df.empty:
        if "거래량증가" not in etf_df.columns:
            etf_df["거래량증가"] = np.nan
        for sector in ["전력기기", "전력인프라", "글로벌AI전력인프라", "미국AI전력인프라", "원자력", "원자력TOP10", "우라늄/원전"]:
            match = etf_df[etf_df["섹터"] == sector].head(1)
            if match.empty:
                continue
            r = match.iloc[0]
            rows.append({
                "구분": "ETF/섹터",
                "축": sector,
                "대표": f"{r['Ticker']} · {r['ETF 이름']}",
                "3개월수익률": r["3개월수익률"],
                "가속도": r["가속도"],
                "거래량증가": r["거래량증가"],
                "점수": r["돈흐름점수"],
                "해석": "대표 ETF 가격/거래량 흐름",
            })

    for _, r in matched_themes.iterrows():
        rows.append({
            "구분": "이미지 테마",
            "축": r["테마"],
            "대표": r["대표주"],
            "3개월수익률": r["3개월수익률"],
            "가속도": r["가속도"],
            "거래량증가": r["거래량증가"],
            "점수": r["테마돈흐름점수"],
            "해석": "구성종목 확산/쏠림 반영",
        })

    if not rows:
        return

    st.markdown("#### 전력 ETF ↔ 테마 종목 매칭")
    st.markdown(
        """
<div class='info-panel'>
<b>전력 신호를 읽는 순서</b><br>
ETF의 <b>전력기기/전력인프라</b>와 직접 비교할 대상은 이미지 테마의 <b>전력·에너지 인프라</b>입니다.
<b>글로벌 원전·SMR</b>은 원전 운영, SMR, 우라늄/연료 축이라 국내 전력기기 ETF와 별도로 해석합니다.
</div>
        """,
        unsafe_allow_html=True,
    )

    show = pd.DataFrame(rows)
    for col in ["3개월수익률", "가속도", "거래량증가"]:
        show[col] = show[col].apply(fmt_flow_pct)
    show["점수"] = show["점수"].apply(lambda x: "-" if not finite_num(x) else f"{x:.1f}")
    st.dataframe(
        show[["구분", "축", "대표", "3개월수익률", "가속도", "거래량증가", "점수", "해석"]],
        use_container_width=True,
        hide_index=True,
        height=300,
    )


def render_image_theme_flow_section():
    st.subheader("🧭 테마 종목 흐름")
    st.caption(
        "테마/하위테마 묶음을 가격 기반 모멘텀으로 비교합니다. "
        "실제 자금 유입액이 아니라 1개월/3개월/6개월 수익률, 최근 3개월-이전 3개월 가속도, 거래량 증가를 합친 참고 지표입니다."
    )

    themes = get_image_theme_names()
    if not themes:
        if not IMAGE_THEME_FLOW_AVAILABLE:
            st.error(
                "테마 종목 데이터 모듈이 아직 배포본에 반영되지 않았습니다. "
                "`stock_lab_core/money_flow.py`까지 함께 배포되어야 국내/해외 테마 종목이 표시됩니다."
            )
        else:
            st.info("등록된 테마 종목 universe가 없습니다.")
        return

    # ── 테마 선택 UI ──────────────────────────────────────────────────
    def _theme_label(t: str) -> str:
        meta = IMAGE_THEME_META.get(t, {})
        tag  = meta.get("tag", "")
        return f"{t}  [{tag}]" if tag else t

    c1, c2 = st.columns([1.3, 0.7])
    with c1:
        selected_theme = st.selectbox(
            "테마 선택",
            themes,
            format_func=_theme_label,
            key="image_theme_flow_theme",
        )
    with c2:
        selected_market = st.radio(
            "시장 범위",
            ["전체", "국내", "해외"],
            horizontal=True,
            key="image_theme_flow_market",
        )

    # ── 선택 테마 설명 칩 ─────────────────────────────────────────────
    _meta = IMAGE_THEME_META.get(selected_theme, {})
    if _meta:
        _etf_hint = f" &nbsp;|&nbsp; 벤치 ETF: <code>{_meta.get('etf','')}</code>" if _meta.get("etf") else ""
        st.markdown(
            f"<span style='background:#1e293b;padding:4px 10px;border-radius:6px;font-size:0.88em;'>"
            f"{_meta.get('tag','')} &nbsp; {_meta.get('desc','')}{_etf_hint}</span>",
            unsafe_allow_html=True,
        )
        st.write("")  # 여백

    if not should_run_heavy_analysis(
        "image_theme_flow_lazy",
        "선택한 테마의 구성종목 가격을 한 번에 조회하므로 필요할 때만 실행합니다.",
    ):
        return

    with st.spinner("전체 테마 종목 흐름 계산 중..."):
        all_theme_df = calculate_image_theme_flow_df("")

    if all_theme_df.empty:
        st.warning("테마 종목 데이터를 불러오지 못했습니다.")
        return

    all_market_suffix = all_theme_df["Ticker"].astype(str).str.upper().str.endswith((".KS", ".KQ"))
    if selected_market == "국내":
        rotation_source_df = all_theme_df[all_market_suffix].copy()
    elif selected_market == "해외":
        rotation_source_df = all_theme_df[~all_market_suffix].copy()
    else:
        rotation_source_df = all_theme_df.copy()

    rotation_df = calculate_image_theme_rotation_df(rotation_source_df)
    render_image_theme_rotation_overview(rotation_df, selected_market)
    st.divider()

    theme_df_all = all_theme_df[all_theme_df["테마"] == selected_theme].copy()
    market_suffix = theme_df_all["Ticker"].astype(str).str.upper().str.endswith((".KS", ".KQ"))
    domestic_count = int(market_suffix.sum())
    foreign_count = int((~market_suffix).sum())

    if selected_market == "국내":
        theme_df = theme_df_all[market_suffix].copy()
    elif selected_market == "해외":
        theme_df = theme_df_all[~market_suffix].copy()
    else:
        theme_df = theme_df_all.copy()

    if theme_df.empty:
        st.warning(f"{selected_theme}에는 선택한 시장 범위({selected_market})에 해당하는 종목이 없습니다.")
        return

    group_df = calculate_image_theme_group_df(theme_df)

    available_count = int(theme_df["돈흐름점수"].notna().sum())
    total_count = int(len(theme_df))
    missing_df = theme_df[theme_df["상태"] == "가격부족"].copy()

    if group_df.empty:
        st.warning("계산 가능한 가격 데이터가 부족합니다. 티커 또는 야후파이낸스 조회 상태를 확인해 주세요.")
        if not missing_df.empty:
            st.dataframe(missing_df[["하위테마", "종목명", "Ticker", "상태"]], use_container_width=True, hide_index=True)
        return

    leader = group_df.iloc[0]
    accel_leader = group_df.sort_values("가속도", ascending=False).iloc[0]
    weak = group_df.sort_values("돈흐름점수", ascending=True).iloc[0]

    st.markdown(f"#### {selected_theme} 드릴다운")

    # ── 테마 수치 요약 카드 ──────────────────────────────────────────
    _th_avg_3m   = theme_df["3개월수익률"].dropna().mean()
    _th_avg_acc  = theme_df["가속도"].dropna().mean()
    _th_pos_ratio = float((theme_df["3개월수익률"].fillna(0) > 0).mean())
    _th_n_sub    = int(group_df["하위테마"].nunique()) if not group_df.empty else 0
    _th_state    = classify_money_flow_state(
        _th_avg_3m if finite_num(_th_avg_3m) else None,
        theme_df["6개월수익률"].dropna().mean() if not theme_df.empty else None,
        _th_avg_acc if finite_num(_th_avg_acc) else None,
        theme_df["가격수준"].dropna().mean() if not theme_df.empty else None,
    ) if IMAGE_THEME_FLOW_AVAILABLE else "-"
    _state_badge_map = {
        "과열경보": "🔥", "강세 가속": "🚀", "급락 경보": "💥", "급반등": "⚡",
        "고변동": "〰️", "신규 유입": "🟢", "주도 유지": "💚",
        "둔화 경고": "🟡", "소외 지속": "🔴", "관찰": "⚪",
    }
    _state_icon = _state_badge_map.get(_th_state, "")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("계산 종목", f"{available_count}/{total_count}", f"국내 {domestic_count} · 해외 {foreign_count}")
    m2.metric("하위테마 수", f"{_th_n_sub}개")
    m3.metric("테마 평균 3M", fmt_flow_pct(_th_avg_3m) if finite_num(_th_avg_3m) else "-")
    m4.metric("상승 종목 비율", f"{_th_pos_ratio*100:.0f}%")
    m5.metric("테마 상태", f"{_state_icon} {_th_state}")

    _detail_reading = _build_theme_detail_reading(group_df, leader, accel_leader, weak)
    st.markdown(
        f"""
<div class='info-panel'>
<b>📊 {selected_theme} 해석</b><br>
{_detail_reading}
<br><span style='color:#94a3b8;font-size:0.85em;'>대표주: {leader.get('대표주', '-')} &nbsp;|&nbsp; 스코어: {leader.get('돈흐름점수', float('nan')):.1f}pts (1M×12 + 3M×33 + 6M×25 + 가속도×15 + 거래량×15)</span>
</div>
        """,
        unsafe_allow_html=True,
    )

    # ── 상태 이모지 배지 (탭 공통) ────────────────────────────────────
    _it_state_badge = {
        "과열경보": "🔥 과열경보",
        "강세 가속": "🚀 강세 가속",
        "급락 경보": "💥 급락 경보",
        "급반등":   "⚡ 급반등",
        "고변동":   "〰️ 고변동",
        "신규 유입": "🟢 신규 유입",
        "주도 유지": "💚 주도 유지",
        "둔화 경고": "🟡 둔화 경고",
        "소외 지속": "🔴 소외 지속",
        "상대 약세": "🟠 상대 약세",
        "관찰":     "⚪ 관찰",
        "가격부족": "⬛ 가격부족",
    }

    # 가격부족 경고
    if not missing_df.empty:
        _missing_cnt = len(missing_df)
        _missing_names = ", ".join(missing_df["종목명"].head(5).astype(str).tolist())
        st.warning(
            f"⬛ 가격 데이터 부족 {_missing_cnt}개 종목이 점수 계산에서 제외됐습니다: {_missing_names}"
            + (" 외" if _missing_cnt > 5 else "")
            + " (야후파이낸스 조회 실패 또는 상장 1년 미만)"
        )

    summary_tab, stocks_tab, raw_tab = st.tabs(["하위테마 요약", "종목별 흐름", "원자료"])

    with summary_tab:
        left, right = st.columns([1.05, 1])
        with left:
            chart_df = group_df.sort_values("돈흐름점수", ascending=True).tail(15)
            colors = np.where(chart_df["돈흐름점수"] >= 0, "#22c55e", "#ef4444")
            fig_score = go.Figure(go.Bar(
                x=chart_df["돈흐름점수"],
                y=chart_df["하위테마"],
                orientation="h",
                marker_color=colors,
                customdata=chart_df[["대표주", "3개월수익률", "6개월수익률", "가속도", "상태"]],
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "대표주: %{customdata[0]}<br>"
                    "3개월: %{customdata[1]:.1%}<br>"
                    "6개월: %{customdata[2]:.1%}<br>"
                    "가속도: %{customdata[3]:.1%}<br>"
                    "상태: %{customdata[4]}<extra></extra>"
                ),
            ))
            fig_score.add_vline(x=0, line_color="#94a3b8")
            fig_score.update_layout(
                template="plotly_dark",
                height=max(420, min(650, 120 + len(chart_df) * 34)),
                title="하위테마 돈흐름점수",
                xaxis_title="점수",
                yaxis=dict(autorange="reversed"),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_score, use_container_width=True)

        with right:
            fig_quad = go.Figure(go.Scatter(
                x=group_df["6개월수익률"] * 100,
                y=group_df["3개월수익률"] * 100,
                mode="markers+text",
                text=group_df["하위테마"],
                textposition="top center",
                marker=dict(
                    size=np.clip(group_df["가격수준"].fillna(0.5) * 28, 12, 34),
                    color=group_df["가속도"] * 100,
                    colorscale="RdYlGn",
                    cmid=0,
                    showscale=True,
                    colorbar=dict(title="가속도"),
                ),
                customdata=group_df[["대표주", "돈흐름점수", "상태"]],
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "대표주: %{customdata[0]}<br>"
                    "6개월: %{x:.1f}%<br>"
                    "3개월: %{y:.1f}%<br>"
                    "점수: %{customdata[1]:.1f}<br>"
                    "상태: %{customdata[2]}<extra></extra>"
                ),
            ))
            fig_quad.add_vline(x=0, line_dash="dash", line_color="#94a3b8")
            fig_quad.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
            fig_quad.update_layout(
                template="plotly_dark",
                height=470,
                title="하위테마 로테이션",
                xaxis_title="6개월 수익률 %",
                yaxis_title="3개월 수익률 %",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_quad, use_container_width=True)

        show_group = group_df.copy()
        if "상태" in show_group.columns:
            show_group["상태"] = show_group["상태"].map(lambda s: _it_state_badge.get(str(s), str(s)))
        # ── CSV 내보내기까지 올바르게 나오도록 모든 숫자를 문자열로 포맷 ──
        for _col in ["1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률",
                     "6개월수익률", "상승종목비율"]:
            if _col in show_group.columns:
                show_group[_col] = show_group[_col].apply(fmt_flow_pct)
        for _col in ["가속도", "거래량증가", "상위종목쏠림"]:
            if _col in show_group.columns:
                show_group[_col] = show_group[_col].apply(
                    lambda v: f"{v:.2f}" if finite_num(v) else "-"
                )
        if "가격수준" in show_group.columns:
            show_group["가격수준"] = show_group["가격수준"].apply(
                lambda v: f"{v*100:.1f}%" if finite_num(v) else "-"
            )
        if "돈흐름점수" in show_group.columns:
            show_group["돈흐름점수"] = show_group["돈흐름점수"].apply(
                lambda v: f"{v:.1f}" if finite_num(v) else "-"
            )
        # 데이터 없는 컬럼 제거
        for _col in ["이전3개월수익률", "상대3개월수익률", "추격위험"]:
            if _col in show_group.columns:
                _vals = show_group[_col].replace("-", pd.NA).dropna()
                if _vals.empty or (_vals.astype(str).str.strip() == "").all():
                    show_group.drop(columns=[_col], inplace=True)
        _sg_show_cols = [c for c in [
            "하위테마", "종목수", "대표주",
            "1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률", "6개월수익률",
            "가속도", "상승종목비율", "거래량증가", "상위종목쏠림",
            "가격수준", "돈흐름점수", "상태", "구성종목",
        ] if c in show_group.columns]
        st.dataframe(
            show_group[_sg_show_cols],
            column_config={
                "가격수준":    st.column_config.TextColumn("52주위치",  help="52주 최저~최고 범위 내 현재 위치(평균)"),
                "돈흐름점수":  st.column_config.TextColumn("스코어",    help="1M 12% + 3M 33% + 6M 25% + 가속도 15% + 거래량 15%"),
                "1개월수익률":  st.column_config.TextColumn("1M"),
                "3개월수익률":  st.column_config.TextColumn("3M"),
                "6개월수익률":  st.column_config.TextColumn("6M"),
                "가속도":       st.column_config.TextColumn("가속도",   help="최근 3M - 이전 3M. 양수=가속"),
                "상승종목비율": st.column_config.TextColumn("상승비율"),
                "거래량증가":   st.column_config.TextColumn("거래량↑"),
                "상위종목쏠림": st.column_config.TextColumn("쏠림"),
            },
            use_container_width=True,
            hide_index=True,
            height=430,
        )

    with stocks_tab:
        subthemes = ["전체"] + list(theme_df["하위테마"].drop_duplicates())
        selected_subtheme = st.selectbox("하위테마 필터", subthemes, key="image_theme_flow_subtheme")
        stock_view = theme_df if selected_subtheme == "전체" else theme_df[theme_df["하위테마"] == selected_subtheme]
        stock_view = stock_view.sort_values("돈흐름점수", ascending=False, na_position="last")

        chart_stock_df = stock_view.dropna(subset=["돈흐름점수"]).head(20).sort_values("돈흐름점수", ascending=True)
        if not chart_stock_df.empty:
            stock_colors = np.where(chart_stock_df["돈흐름점수"] >= 0, "#38bdf8", "#f97316")
            fig_stock = go.Figure(go.Bar(
                x=chart_stock_df["돈흐름점수"],
                y=chart_stock_df["종목명"] + " (" + chart_stock_df["Ticker"] + ")",
                orientation="h",
                marker_color=stock_colors,
                customdata=chart_stock_df[["하위테마", "3개월수익률", "6개월수익률", "가속도", "상태"]],
                hovertemplate=(
                    "%{y}<br>"
                    "하위테마: %{customdata[0]}<br>"
                    "3개월: %{customdata[1]:.1%}<br>"
                    "6개월: %{customdata[2]:.1%}<br>"
                    "가속도: %{customdata[3]:.1%}<br>"
                    "상태: %{customdata[4]}<extra></extra>"
                ),
            ))
            fig_stock.add_vline(x=0, line_color="#94a3b8")
            fig_stock.update_layout(
                template="plotly_dark",
                height=max(430, min(720, 130 + len(chart_stock_df) * 30)),
                title="종목별 돈흐름점수 TOP",
                xaxis_title="점수",
                yaxis=dict(autorange="reversed"),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_stock, use_container_width=True)

        show_stock = stock_view.copy()
        if "상태" in show_stock.columns:
            show_stock["상태"] = show_stock["상태"].map(lambda s: _it_state_badge.get(str(s), str(s)))
        # 현재가 포맷 (국내: 정수, 해외: 소수 2자리)
        show_stock["현재가"] = show_stock.apply(
            lambda r: format_currency(r["현재가"], r["Ticker"]) if finite_num(r["현재가"]) else "-",
            axis=1,
        )
        # ── CSV 내보내기까지 올바르게 나오도록 모든 숫자를 문자열로 포맷 ──
        for _col in ["1개월수익률", "3개월수익률", "상대3개월수익률", "6개월수익률"]:
            if _col in show_stock.columns:
                show_stock[_col] = show_stock[_col].apply(fmt_flow_pct)
        for _col in ["가속도", "거래량증가"]:
            if _col in show_stock.columns:
                show_stock[_col] = show_stock[_col].apply(
                    lambda v: f"{v:.2f}" if finite_num(v) else "-"
                )
        if "가격수준" in show_stock.columns:
            show_stock["가격수준"] = show_stock["가격수준"].apply(
                lambda v: f"{v*100:.1f}%" if finite_num(v) else "-"
            )
        if "돈흐름점수" in show_stock.columns:
            show_stock["돈흐름점수"] = show_stock["돈흐름점수"].apply(
                lambda v: f"{v:.1f}" if finite_num(v) else "-"
            )
        # 데이터 없는 컬럼 제거
        for _col in ["상대3개월수익률", "추격위험"]:
            if _col in show_stock.columns:
                _vals = show_stock[_col].replace("-", pd.NA).dropna()
                if _vals.empty or (_vals.astype(str).str.strip() == "").all():
                    show_stock.drop(columns=[_col], inplace=True)
        _it_show_cols = [c for c in [
            "하위테마", "종목명", "Ticker", "현재가", "상태",
            "가격수준", "돈흐름점수",
            "1개월수익률", "3개월수익률", "상대3개월수익률", "6개월수익률",
            "가속도", "거래량증가",
        ] if c in show_stock.columns]
        st.dataframe(
            show_stock[_it_show_cols],
            column_config={
                "가격수준":    st.column_config.TextColumn("52주위치",  help="52주 최저~최고 범위 내 현재 위치"),
                "돈흐름점수":  st.column_config.TextColumn("스코어",    help="1M 12% + 3M 33% + 6M 25% + 가속도 15% + 거래량 15%"),
                "1개월수익률": st.column_config.TextColumn("1M"),
                "3개월수익률": st.column_config.TextColumn("3M"),
                "6개월수익률": st.column_config.TextColumn("6M"),
                "가속도":      st.column_config.TextColumn("가속도",    help="최근 3M - 이전 3M. 양수=가속"),
                "거래량증가":  st.column_config.TextColumn("거래량↑",   help="최근 20일 평균 거래량 / 직전 60일 평균 - 1"),
            },
            use_container_width=True,
            hide_index=True,
            height=560,
        )

        # ── 전광판 추가 ──────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 📌 전광판에 종목 추가")
        _sendable = stock_view.dropna(subset=["Ticker"]).copy()
        if not _sendable.empty:
            _send_options = [
                f"{r['종목명']} ({r['Ticker']}) — {r.get('하위테마', '')}"
                for _, r in _sendable.iterrows()
            ]
            _send_ticker_map = {
                f"{r['종목명']} ({r['Ticker']}) — {r.get('하위테마', '')}": r.to_dict()
                for _, r in _sendable.iterrows()
            }
            sc1, sc2 = st.columns([3, 1])
            with sc1:
                _selected_send = st.selectbox(
                    "추가할 종목 선택",
                    _send_options,
                    key="theme_stock_send_select",
                )
            with sc2:
                _send_row = _send_ticker_map.get(_selected_send, {})
                _send_ticker = sanitize_ticker_value(_send_row.get("Ticker", ""))
                _already = is_in_watchlist(_send_ticker) if _send_ticker else False
                st.write("")  # 버튼 수직 정렬용
                if _already:
                    st.caption("✅ 이미 등록됨")
                elif st.button("전광판 추가", key="theme_stock_send_btn", use_container_width=True):
                    ok, msg = add_money_flow_row_to_watchlist(_send_row, is_stock=True)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.warning(msg)

            # ── 선택 종목 Baseline 차트 (벤치마크 대비 초과수익) ────────
            if _send_ticker:
                _stock_name    = _send_row.get("종목명", _send_ticker)
                _stock_subtheme = str(_send_row.get("하위테마", ""))
                render_lwc_baseline(
                    _send_ticker,
                    label=_stock_name,
                    key=f"lwc_baseline_theme_{_send_ticker}",
                    sector=_stock_subtheme,
                )

    with raw_tab:
        st.dataframe(theme_df, use_container_width=True, hide_index=True, height=520)
        if not missing_df.empty:
            st.warning("아래 종목은 이번 조회에서 가격 데이터가 부족했습니다. 티커 오류, 거래소 suffix, 야후파이낸스 지연을 확인하세요.")
            st.dataframe(missing_df[["하위테마", "종목명", "Ticker", "상태"]], use_container_width=True, hide_index=True)


def render_money_flow_tab():
    etf_tab, image_theme_tab = st.tabs(["ETF/섹터 돈흐름", "테마 종목 흐름"])
    with etf_tab:
        render_money_flow_etf_section()
    with image_theme_tab:
        render_image_theme_flow_section()

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
            # 자산관리 탭의 기술적 타점도 다음 렌더에서 재계산되도록 플래그 설정
            st.session_state["asset_management_tech_summary_lazy_ready"] = True
            st.session_state["_ticker_signal_cache"] = {}   # 이전 캐시 초기화
            st.toast("차트/기술 캐시를 비웠습니다. 기술적 타점이 재계산됩니다.")
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

# -------------------------------------------------
# 5. SMC 헬퍼 및 엔진 로직
# -------------------------------------------------
# get_pivot_highs_lows, get_recent_levels, detect_structure_event,
# detect_liquidity_grab, detect_recent_fvg, get_pd_zone, summarize_smc_action
# → stock_lab_core/ta_engine.py 로 이동됨 (상단 import 블록 참조)

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
        "HACK": US_TECH_BENCHMARK,   # 사이버보안 ETF → QQQM 대비 RS
        "URA": US_BROAD_BENCHMARK,   # 우라늄 테마 → SPY 대비 RS
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
    # asset_class 미설정 한국 종목 폴백: .KS/.KQ 접미사로 판별
    if is_kr_listed(ticker): return KR_MARKET_BENCHMARK

    # ── 글로벌 거래소 suffix 기반 폴백 ─────────────────────────────
    _upper = str(ticker).upper()
    if _upper.endswith(".T"):   return "EWJ"      # 일본 → iShares MSCI Japan
    if _upper.endswith(".HK"):  return "EWH"      # 홍콩 → iShares MSCI Hong Kong
    if _upper.endswith(".TW"):  return "EWT"      # 대만 → iShares MSCI Taiwan
    if _upper.endswith(".L"):   return "EWU"      # 런던 → iShares MSCI UK
    if _upper.endswith(".AX"):  return "EWA"      # 호주 → iShares MSCI Australia
    if _upper.endswith(".TO"):  return "EWC"      # 캐나다 → iShares MSCI Canada
    if _upper.endswith(".PA") or _upper.endswith(".DE") or _upper.endswith(".MI"):
        return "EZU"                              # 유로존 → iShares MSCI EMU

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


def get_rs_slope(ticker: str, asset_class: str) -> tuple:
    """RS(상대강도) 기울기를 측정합니다.

    get_rs_score()가 현재 RS 수준을 판단한다면,
    이 함수는 그 RS가 개선 중인지 악화 중인지를 8주 변화율로 측정합니다.
    4주·8주 두 구간이 같은 방향일 때만 신호로 인정하여 노이즈를 줄입니다.

    Returns:
        slope_pct (float) : 8주간 RS 변화율 (%)
        label     (str)   : 📈RS상승중 / ➡️RS횡보 / 📉RS하락중 / ⏳RS기울기부족
        score     (int)   : +1 / 0 / -1
    """
    bench = get_rs_benchmark(ticker, asset_class)
    if normalize_ticker(ticker) == normalize_ticker(bench):
        return 0.0, "➡️RS횡보", 0

    s_df = load_price_df(ticker, "3mo")
    b_df = load_price_df(bench,  "3mo")

    # 8주(≈40 거래일) + 현재 1일 = 최소 42행 필요
    if len(s_df) < 42 or len(b_df) < 42:
        return 0.0, "⏳RS기울기부족", 0

    def _price(df, idx):
        v = float(df["Close"].iloc[idx])
        return v if v > 0 else None

    s_now = _price(s_df, -1);  b_now = _price(b_df, -1)
    s_4w  = _price(s_df, -21); b_4w  = _price(b_df, -21)
    s_8w  = _price(s_df, -41); b_8w  = _price(b_df, -41)

    if any(v is None for v in [s_now, b_now, s_4w, b_4w, s_8w, b_8w]):
        return 0.0, "⏳RS기울기부족", 0

    rs_now = s_now / b_now
    rs_4w  = s_4w  / b_4w
    rs_8w  = s_8w  / b_8w

    if rs_8w <= 0 or rs_4w <= 0:
        return 0.0, "⏳RS기울기부족", 0

    slope_pct  = (rs_now - rs_8w) / rs_8w * 100   # 8주 RS 변화율
    recent_pct = (rs_now - rs_4w) / rs_4w * 100   # 최근 4주 RS 변화율

    # 두 기간이 같은 방향일 때만 신호 인정 (일관성 필터)
    consistent = (slope_pct > 0 and recent_pct > 0) or (slope_pct < 0 and recent_pct < 0)

    if slope_pct > 3 and consistent:
        return round(slope_pct, 1), "📈RS상승중", 1
    elif slope_pct < -3 and consistent:
        return round(slope_pct, 1), "📉RS하락중", -1
    else:
        return round(slope_pct, 1), "➡️RS횡보", 0


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
    "AAPL": ("XLK", "미국 기술"),
    "ADBE": ("XLK", "미국 기술"),
    "CRM": ("XLK", "미국 기술"),
    "ORCL": ("XLK", "미국 기술"),
    "NOW": ("XLK", "미국 기술"),
    "SNOW": ("XLK", "미국 기술"),
    "PANW": ("XLK", "미국 기술"),          # Palo Alto → 사이버보안/기술
    "HACK": ("XLK", "미국 기술"),           # Cybersecurity ETF → XLK 기준
    "NBIS": ("XLK", "미국 기술/AI"),        # QQQM → XLK (시장벤치와 섹터벤치 분리)
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
    "DRAM": ("SMH", "미국 반도체"),         # Roundhill Memory ETF → SMH (키워드 오매핑 방지)
    "AMZN": ("XLY", "미국 경기소비재"),     # yfinance 의존 제거 → 명시 매핑
    "TSLA": ("XLY", "미국 경기소비재"),
    "GOOGL": ("XLC", "미국 커뮤니케이션"),
    "GOOG": ("XLC", "미국 커뮤니케이션"),
    "META": ("XLC", "미국 커뮤니케이션"),
    "NFLX": ("XLC", "미국 커뮤니케이션"),
    "PLTR": ("XLK", "미국 기술"),
    "SMCI": ("SMH", "미국 반도체"),
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

# yfinance ETF의 category 필드 → 섹터벤치 자동 매핑
# ETF는 sector 대신 category를 반환함
ETF_CATEGORY_SECTOR_MAP = {
    # 기술/성장
    "Technology": ("XLK", "미국 기술"),
    "Equity Technology": ("XLK", "미국 기술"),
    "Technology Growth": ("XLK", "미국 기술"),
    "Communications": ("XLC", "미국 커뮤니케이션"),
    "Communication Services": ("XLC", "미국 커뮤니케이션"),
    # 반도체
    "Semiconductor": ("SMH", "미국 반도체"),
    "Semiconductors": ("SMH", "미국 반도체"),
    # 산업재/인프라
    "Industrials": ("XLI", "미국 산업재"),
    "Infrastructure": ("XLI", "미국 산업재"),
    # 헬스케어
    "Health": ("XLV", "미국 헬스케어"),
    "Health Care": ("XLV", "미국 헬스케어"),
    "Healthcare": ("XLV", "미국 헬스케어"),
    "Biotechnology": ("XLV", "미국 헬스케어"),
    # 금융
    "Financial": ("XLF", "미국 금융"),
    "Financial Services": ("XLF", "미국 금융"),
    # 에너지
    "Energy": ("XLE", "미국 에너지"),
    "Equity Energy": ("XLE", "미국 에너지"),
    "Natural Resources": ("XLE", "미국 에너지"),
    "Equity Precious Metals": ("XLE", "미국 에너지/소재"),
    # 소비재
    "Consumer Cyclical": ("XLY", "미국 경기소비재"),
    "Consumer Defensive": ("XLP", "미국 필수소비재"),
    # 유틸리티/부동산
    "Utilities": ("XLU", "미국 유틸리티"),
    "Real Estate": ("VNQ", "미국 리츠/부동산"),
}


def infer_us_sector_benchmark(ticker, asset_class):
    """
    US 종목/ETF의 섹터벤치를 자동 추론.
    - 주식: yfinance sector/industry → SPDR 섹터 ETF
    - ETF: yfinance category → 섹터 ETF (SECTOR_BENCHMARK_MAP 미등록 ETF 처리)
    """
    if is_kr_listed(ticker):
        return None

    info = lookup_yfinance_info(ticker)
    quote_type = str(info.get("quoteType", "") or "").upper()
    ac = str(asset_class or "").strip().lower()

    # ── ETF 처리 ──────────────────────────────────────
    if quote_type == "ETF" or ("etf" in ac):
        category = str(info.get("category", "") or "").strip()
        # 정확 매칭
        if category in ETF_CATEGORY_SECTOR_MAP:
            return ETF_CATEGORY_SECTOR_MAP[category]
        # 부분 매칭 (예: "Equity Technology" → "Technology" 키로 폴백)
        cat_lower = category.lower()
        for key, val in ETF_CATEGORY_SECTOR_MAP.items():
            if key.lower() in cat_lower or cat_lower in key.lower():
                return val
        # category 없으면 ETF 섹터벤치 없음
        return None

    # ── 주식 처리 ──────────────────────────────────────
    if ac and "stock" not in ac and ac != "us":
        return None

    sector = str(info.get("sector", "") or "").strip()
    if sector in US_YFINANCE_SECTOR_BENCHMARKS:
        return US_YFINANCE_SECTOR_BENCHMARKS[sector]

    industry = str(info.get("industry", "") or "").lower()
    if any(w in industry for w in ["semiconductor", "chip", "electronic"]):
        return ("SMH", "미국 반도체")
    if any(w in industry for w in ["software", "information technology", "computer hardware", "cybersecurity", "internet"]):
        return ("XLK", "미국 기술")
    if any(w in industry for w in ["aerospace", "defense"]):
        return ("XLI", "미국 산업재")
    if any(w in industry for w in ["biotechnology", "pharmaceutical", "drug"]):
        return ("XLV", "미국 헬스케어")
    if any(w in industry for w in ["bank", "insurance", "asset management", "capital markets"]):
        return ("XLF", "미국 금융")
    if any(w in industry for w in ["retail", "e-commerce", "auto", "restaurant"]):
        return ("XLY", "미국 경기소비재")
    if any(w in industry for w in ["oil", "gas", "energy"]):
        return ("XLE", "미국 에너지")
    if any(w in industry for w in ["entertainment", "media", "streaming", "social", "telecom"]):
        return ("XLC", "미국 커뮤니케이션")

    return None


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
        for idx in range(1, 11):  # top 5 → top 10으로 확장: 주요 구성 종목 커버리지 향상
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
    "102110": ("069500.KS", "KOSPI200"),   # TIGER 200
    "229200": ("069500.KS", "KOSPI200"),   # KODEX 코스닥150
    # ── 테마/섹터 ETF: 추적지수가 없으므로 기초자산 표시 없음 ──
    "URA": ("", "-"),       # 우라늄 테마 → 비교 지수 없음
    "139260": ("", "-"),    # TIGER 200 IT → 섹터ETF, KOSPI200이 기초가 아님
    "487240": ("", "-"),    # KODEX AI전력핵심설비 → 테마ETF
    "433500": ("", "-"),    # ACE 원자력테마딥서치 → 테마ETF
    "396500": ("", "-"),    # KODEX 한국반도체 → 섹터ETF
    "449450": ("", "-"),    # KODEX K-방산 → 섹터ETF
    "494670": ("", "-"),    # KODEX 조선 → 섹터ETF
    "305540": ("", "-"),    # KODEX 2차전지 → 섹터ETF
    "479850": ("", "-"),    # HANARO K-뷰티 → 테마ETF
    "434730": ("", "-"),    # HANARO 원자력iSelect → 테마ETF
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
    # kr_etf 폴백: UNDERLYING_BENCHMARK_MAP에 없는 한국 ETF는
    # 테마/섹터 ETF일 가능성이 높으므로 기초자산 표시 안 함.
    # 광범위 시장추적 ETF(069500 등)는 위 맵에 명시적으로 등록.
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

    # ── 글로벌 거래소 suffix 기반 폴백 ─────────────────────────────
    # 섹터를 특정할 수 없을 때 해당 국가 지수 ETF로라도 비교
    _upper = str(ticker).upper()
    if _upper.endswith(".T"):   return ("EWJ", "일본주식")
    if _upper.endswith(".HK"):  return ("EWH", "홍콩주식")
    if _upper.endswith(".TW"):  return ("EWT", "대만주식")
    if _upper.endswith(".L"):   return ("EWU", "영국주식")
    if _upper.endswith(".AX"):  return ("EWA", "호주주식")
    if _upper.endswith(".TO"):  return ("EWC", "캐나다주식")
    if _upper.endswith(".PA") or _upper.endswith(".DE") or _upper.endswith(".MI"):
        return ("EZU", "유로존주식")

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

@st.cache_data(ttl=3600, show_spinner=False)
def get_auto_benchmark_info(ticker: str, name: str, asset_class: str, is_etf: bool) -> dict:
    """
    벤치마크 정보 단일 진입점 — 시장/섹터/기초자산 벤치를 한 번에 반환합니다.

    기존에 렌더링 루프 안에서 get_rs_benchmark / get_sector_benchmark_info /
    get_underlying_benchmark_info / get_rs_score_against_benchmark 를 따로 호출하던
    패턴을 이 함수 하나로 대체합니다.  결과는 1시간 TTL로 캐싱됩니다.

    Returns dict keys:
        market_bench      : str  (예: "QQQM", "069500.KS")
        sector_bench      : str  (예: "XLK", "396500.KS", "")
        sector_label      : str  (예: "미국 기술", "반도체", "-")
        underlying_bench  : str  (예: "QQQM", "")
        underlying_asset  : str  (예: "나스닥100", "-")
        sector_rs_label   : str  (예: "🚀강함", "➖보통", "🐢약함", "-")
    """
    market_bench = get_rs_benchmark(ticker, asset_class)

    sector_result = get_sector_benchmark_info(ticker, asset_class, name)
    if isinstance(sector_result, tuple) and len(sector_result) == 2:
        sector_bench, sector_label = sector_result
    else:
        sector_bench, sector_label = "", "-"

    if is_etf:
        underlying_result = get_underlying_benchmark_info(ticker, asset_class)
        if isinstance(underlying_result, tuple) and len(underlying_result) == 2:
            underlying_bench, underlying_asset = underlying_result
        else:
            underlying_bench, underlying_asset = "", "-"
    else:
        underlying_bench, underlying_asset = "", "-"

    _, sector_rs_label = get_rs_score_against_benchmark(ticker, sector_bench)

    return {
        "market_bench":     market_bench,
        "sector_bench":     sector_bench,
        "sector_label":     sector_label,
        "underlying_bench": underlying_bench,
        "underlying_asset": underlying_asset,
        "sector_rs_label":  sector_rs_label,
    }


def prefetch_benchmark_info_parallel(watchlist_items: list, max_workers: int = 6):
    """
    워치리스트 전체의 벤치마크 정보를 병렬로 선제 캐싱합니다.
    이후 get_auto_benchmark_info 호출은 캐시 히트로 즉시 반환됩니다.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch(item):
        tkr  = sanitize_ticker_value(item.get("ticker", ""))
        name = sanitize_asset_name(item.get("name", ""), tkr)
        if not tkr:
            return
        is_etf = is_fin_score_exempt_asset(tkr, item.get("is_etf", False), item.get("asset_class", ""), name)
        ac = infer_asset_class_for_ticker(tkr, item.get("asset_class", "")) if is_etf else item.get("asset_class", "")
        try:
            get_auto_benchmark_info(tkr, name, ac, is_etf)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch, item) for item in watchlist_items]
        for f in as_completed(futures):
            f.result()


# build_indicators, get_trend → stock_lab_core/ta_engine.py 로 이동됨 (상단 import 블록 참조)

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

def get_effective_bucket(mode, name, ticker):
    if mode == "개인모드":
        row = get_holding_row_by_ticker(holdings_table, ticker)
        if row is not None:
            return infer_bucket(ticker, row.get("bucket", "core"))
    return infer_bucket(ticker, "")

def get_cash_available_for_dca(mode):
    if mode != "개인모드":
        return 0.0
    # globals() 대신 session_state 사용 (안전한 참조)
    return clean_float(st.session_state.get("_app_krw_cash"), 0.0) + (
        clean_float(st.session_state.get("_app_usd_cash"), 0.0) * clean_float(st.session_state.get("_app_usdkrw", 1400.0), 1400.0)
    )

def get_reserve_available_for_crash_buy(mode):
    if mode != "개인모드":
        return 0.0
    table = st.session_state.get("_app_holdings_table")
    if table is None or table.empty or "bucket" not in table.columns or "원화환산" not in table.columns:
        return 0.0
    reserve_rows = table[table["bucket"].apply(lambda v: normalize_bucket(v) == "reserve")]
    return float(reserve_rows["원화환산"].apply(clean_float).sum()) if not reserve_rows.empty else 0.0

def is_leveraged_or_inverse_product(name, ticker, asset_class=""):
    text = f"{name} {ticker} {asset_class}".upper()
    keywords = [
        "LEVER", "LEVERAGE", "LEVERAGED", "INVERSE", "인버스", "레버리지", "곱버스",
        "2X", "3X", "TQQQ", "SQQQ", "QLD", "SOXL", "SOXS", "SPXL", "SPXS", "UPRO", "SPXU",
    ]
    return any(keyword in text for keyword in keywords)

def classify_core_etf_dca_rate(is_core_etf, name, ticker, asset_class, weight_gap, current_dd, rsi_now, mfi_now, pct_b_now, trend):
    return classify_core_etf_dca_rate_rule(
        is_core_etf=is_core_etf,
        weight_gap=weight_gap,
        current_dd=current_dd,
        rsi_now=rsi_now,
        mfi_now=mfi_now,
        pct_b_now=pct_b_now,
        trend=trend,
        is_leveraged_or_inverse=is_leveraged_or_inverse_product(name, ticker, asset_class),
        final_macro_risk=final_macro_risk,
    )


def build_core_dca_context(
    mode, is_core_etf, name, ticker, asset_class, weight_gap, buy_amount,
    current_dd, rsi_now, mfi_now, pct_b_now, trend,
    cash_available_snapshot=None, reserve_available_snapshot=None,
):
    rate, label = classify_core_etf_dca_rate(
        is_core_etf, name, ticker, asset_class, weight_gap, current_dd, rsi_now, mfi_now, pct_b_now, trend
    )
    cash_available = (
        get_cash_available_for_dca(mode)
        if cash_available_snapshot is None
        else clean_float(cash_available_snapshot, 0.0)
    )
    reserve_available = (
        get_reserve_available_for_crash_buy(mode)
        if reserve_available_snapshot is None
        else clean_float(reserve_available_snapshot, 0.0)
    )


    return build_core_dca_context_values(
        mode=mode,
        rate=rate,
        label=label,
        buy_amount=buy_amount,
        current_dd=current_dd,
        cash_available=cash_available,
        reserve_available=reserve_available,
    )

# -------------------------------------------------
# 7. 기술적 분석 메인 엔진
# -------------------------------------------------
def calc_scores_and_decision(name, ticker, is_etf, asset_class, df, my_price, has_pos, fin_score,
                             is_free=False, app_mode="개인모드", user_total_asset=0.0, user_curr_w=0.0, user_targ_w=0.0,
                             _macro_penalty=None, _final_macro_risk=None, _total_eval=None,
                             _cash_available=None, _reserve_available=None):
    # 글로벌 매크로 값을 명시적 파라미터로 주입 가능 (미전달 시 모듈 전역 변수 사용)
    _mp  = macro_penalty      if _macro_penalty      is None else _macro_penalty
    _fmr = final_macro_risk   if _final_macro_risk   is None else _final_macro_risk
    _te  = total_eval         if _total_eval         is None else _total_eval

    df = ensure_min_price_rows_for_decision(df)

    last, prev, cur_p = df.iloc[-1], df.iloc[-2], float(df.iloc[-1]["Close"])
    p3m = df["Close"].iloc[-61] if len(df) >= 61 else df["Close"].iloc[0]
    p6m = df["Close"].iloc[-121] if len(df) >= 121 else df["Close"].iloc[0]
    ret_3m, ret_6m = (cur_p / p3m) - 1, (cur_p / p6m) - 1
    prev_close = float(prev["Close"]) if finite_num(prev["Close"]) else 0.0
    day_ret = (cur_p / prev_close) - 1 if prev_close > 0 else 0.0
    high_52w = df["High"].rolling(252).max().iloc[-1] if len(df) >= 252 else df["High"].max()
    current_dd = (cur_p / high_52w) - 1 if high_52w > 0 else 0.0

    short_history = len(df) < 60 or not finite_num(last["MA50"]) or not finite_num(last["MA120"])
    trend = get_trend(last)
    macd_state = get_macd_state(last["MACD"], last["MACD_Sig"], prev["MACD"], prev["MACD_Sig"])
    rt_macd_label = "📈상승추세" if last["MACD"] > prev["MACD"] else ("📉하락추세" if last["MACD"] < prev["MACD"] else "⏳관망")
    rsi_now, mfi_now, pct_b_now = float(last["RSI"]), float(last["MFI"]), float(last["%B"])
    _, rs_label = get_rs_score(ticker, asset_class)
    rs_slope_val, rs_slope_label, rs_slope_s = get_rs_slope(ticker, asset_class)
    sqz_status = get_sqz_status(bool(last["SQZ_ON"]), bool(prev["SQZ_ON"]))

    tech_scores = score_technical_components(rs_label, mfi_now, trend, macd_state, sqz_status)
    rs_s = tech_scores["rs_s"]
    mfi_s = tech_scores["mfi_s"]
    trend_s = tech_scores["trend_s"]
    macd_s = tech_scores["macd_s"]
    sqz_s = tech_scores["sqz_s"]
    tech_total = tech_scores["tech_total"]
    vol_ma20 = float(df["Volume"].rolling(20).mean().iloc[-1]) if pd.notna(df["Volume"].rolling(20).mean().iloc[-1]) else 1
    vol_ratio = float(last["Volume"]) / vol_ma20 if vol_ma20 > 0 else 0
    ma20_now = float(last["MA20"]) if finite_num(last["MA20"]) else 0.0
    ma50_now = float(last["MA50"]) if finite_num(last["MA50"]) else 0.0
    below_ma20 = ma20_now > 0 and cur_p < ma20_now * 0.98
    below_ma50 = ma50_now > 0 and cur_p < ma50_now
    is_single_day_breakdown = (not is_etf) and day_ret <= -0.06 and vol_ratio >= 1.2

    main_score = score_main_entry(trend, macd_state, rsi_now, day_ret, vol_ratio)
    # rs_slope_s(±1)는 adj_tech_score에만 반영 — grade 임계값 안정성 유지
    adj_tech_score = (main_score + rs_s + mfi_s + rs_slope_s) - _mp

    candidate_grade = classify_candidate_grade(is_etf, tech_total, fin_score)
    t_score = candidate_grade.t_score
    grade = candidate_grade.grade

    levels = get_recent_levels(df)

    # Feature ②: R/R 비율 — 추가 인사이트와 동일한 2ATR 손절 기준 사용
    _atr = calc_atr(df)  # 추가 인사이트(독립 모듈) 손절 계산과 동일한 함수
    rr_stop_atr  = round(cur_p - _atr * 2.0, 4) if _atr > 0 else None   # 2ATR 손절
    rr_risk_atr  = cur_p - rr_stop_atr if rr_stop_atr else 0

    # 목표가: 구조적 저항이 현재가 위에 있으면 그것을 사용, 없으면 4ATR 돌파 목표 (2:1 R/R 투영)
    if levels["int_high"] > cur_p:
        rr_target_price = levels["int_high"]
    elif levels["ext_high"] > cur_p:
        rr_target_price = levels["ext_high"]
    else:
        rr_target_price = round(cur_p + _atr * 4.0, 4) if _atr > 0 else None  # 신고가 돌파: 4ATR 목표 투영

    rr_reward = (rr_target_price - cur_p) if rr_target_price else 0
    rr_ratio  = round(rr_reward / rr_risk_atr, 2) if (rr_risk_atr > 0 and rr_reward > 0) else None

    # Feature ④: 52주 신고가 돌파 감지 — near_high 제외, 실제 돌파만 인정
    _bk_info = detect_52w_breakout(df)
    is_52w_breakout = (
        _bk_info["breakout"] and
        rs_label == "🚀강함" and
        day_ret > 0
    )

    # Feature ③: 섹터 머니플로우 상태
    _bench_info = get_auto_benchmark_info(ticker, name, asset_class, is_etf)
    sector_flow_state = get_sector_flow_state(_bench_info.get("sector_bench", ""))

    ext_structure = "Bullish" if trend == "🚀정배열(상승)" else ("Bearish" if trend == "🌊역배열(하락)" else "Neutral")

    int_structure = (
        "Bullish" if rs_label == "🚀강함" and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]
        else ("Bearish" if trend == "🌊역배열(하락)" or rs_label == "🐢약함" else "Mixed")
    )

    int_event, ext_event = detect_structure_event(df, levels)
    liq_state = detect_liquidity_grab(df, levels)
    fvg_info = detect_recent_fvg(df)
    pd_zone = get_pd_zone(df)
    smc_action = summarize_smc_action(ext_structure, int_structure, int_event, ext_event, liq_state, fvg_info, pd_zone)

    if rsi_now <= 30: smc_insight = "과매도 극단. 유동성 청산 후 구조적 반등(CHoCH) 여부 관찰."
    elif mfi_now >= 80: smc_insight = "스마트머니 익절 가능성이 높은 단기 과열 구간."
    elif trend == "🆕신규상장/자료부족": smc_insight = "상장 초기라 MA50/MA120 기반 추세 판정은 보류. 단기 흐름과 거래량만 참고."
    elif 0.45 < pct_b_now < 0.8 and sqz_status == "🚀해제직후": smc_insight = "응축 후 발산 초기. 모멘텀 실리는 타점 구간."
    elif trend == "🚀정배열(상승)" and rs_label == "🚀강함":
        if rs_slope_label == "📉RS하락중":
            smc_insight = "구조적 상승(BoS) 유지 중이나 RS 기울기 하락 — 상대강도 약화 초기 신호, 추격 자제."
        elif rs_slope_label == "📈RS상승중":
            smc_insight = "RS 모멘텀 가속 중 (상승+강함+기울기 상승). 구조적 추세 확장 구간."
        else:
            smc_insight = "구조적 상승(BoS) 진행 중. MA20 눌림 여부 확인 필요."
    elif rs_label == "🐢약함" and rs_slope_label == "📈RS상승중":
        smc_insight = "RS 반전 초입 — 상대강도 회복 중. 추세 전환 확인 후 접근."
    elif trend == "🌊역배열(하락)": smc_insight = "하락 구조 우세. 추세 전환 전까지 보수적 접근 권장."
    else: smc_insight = "주요 매물대(FVG/Order Block) 소화 중. 방향성 확정 대기."

    eff_total = get_effective_total_asset(app_mode, user_total_asset, _te)
    curr_w, targ_w = get_effective_weights(app_mode, name, ticker, user_curr_w, user_targ_w)
    buy_amount = get_effective_buy_amount(app_mode, name, ticker, eff_total, user_curr_w, user_targ_w)
                                 
    price_vs_avg = ((cur_p / my_price) - 1) if my_price > 0 else 0.0
    weight_gap = targ_w - curr_w
    effective_bucket = get_effective_bucket(app_mode, name, ticker)
    is_core_etf = is_etf and effective_bucket == "core"
    core_dca_context = build_core_dca_context(
        app_mode, is_core_etf, name, ticker, asset_class, weight_gap, buy_amount,
        current_dd, rsi_now, mfi_now, pct_b_now, trend,
        cash_available_snapshot=_cash_available,
        reserve_available_snapshot=_reserve_available,
    )
    core_dca_rate = clean_float(core_dca_context.get("core_dca_rate"), 0.0)
    is_core_dca_allowed = core_dca_rate > 0 and targ_w > 0 and weight_gap > 0


    is_stock_add_on_strength = (
        (not is_etf) and
        has_pos and
        my_price > 0 and
        targ_w > 0 and
        weight_gap >= 2 and
        0.00 < price_vs_avg <= 0.05 and
        trend in ["🚀정배열(상승)", "⏳혼조세"] and
        rs_label in ["🚀강함"] and
        last["MACD"] > prev["MACD"] and
        mfi_now < 80 and
        rsi_now < 70 and
        pct_b_now < 1.00 and
        vol_ratio < 2.5 and
        _fmr < 4.5
    )

    is_early_entry = (trend == "🚀정배열(상승)" and rs_label == "🚀강함" and last["MACD"] > prev["MACD"] and 
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
        trend == "🚀정배열(상승)" and
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
        rs_slope_label != "📉RS하락중" and
        (is_ma5_pullback or is_bullish_fvg_pullback) and
        is_exception_not_chasing
    )

    # RS가 강하고 대장주 조건(fin4 + 정배열)이면 MA50 눌림은 구조훼손이 아닌 매수 기회
    _rs_strong = rs_label == "🚀강함"
    _is_leader_grade = (not is_etf) and fin_score == 4 and trend == "🚀정배열(상승)"
    # 재무 3점이라도 RS 강함 + 정배열 + MA20 위 5% 이상이면 모멘텀 대장주로 인정
    # → 고모멘텀 주식의 -15~20% 조정은 정상 눌림 (CANSLIM 기준 허용범위)
    _is_momentum_leader = (
        (not is_etf) and
        fin_score >= 3 and
        trend == "🚀정배열(상승)" and
        _rs_strong and
        ma20_now > 0 and cur_p > ma20_now * 1.05
    )
    _ma50_damage = below_ma50 and not (_rs_strong and (_is_leader_grade or _is_momentum_leader))
    # 재무4 대장주 또는 모멘텀 대장주(재무3+RS강함+MA20위) → -20%까지 허용
    _dd_threshold = -0.20 if (_is_leader_grade or _is_momentum_leader) and _rs_strong else -0.15
    is_structure_damage_entry_risk = (
        (not is_etf) and
        (not short_history) and
        (
            current_dd <= _dd_threshold or
            _ma50_damage or
            (below_ma20 and not _rs_strong) or
            is_single_day_breakdown
        )
    )

    is_clean_leader_entry = (
        (not is_etf) and
        adj_tech_score >= 4.5 and
        rs_label == "🚀강함" and
        trend == "🚀정배열(상승)" and
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
        (trend != "🌊역배열(하락)" or weight_gap >= 10) and
        mfi_now < 85 and
        rsi_now < 75 and
        pct_b_now < 1.03 and
        _fmr < 4.5
    )
    decision_outcome = None

    # Precompute structure-damage reason strings so each call site stays lean
    _sd_reasons: list[str] = []
    if is_structure_damage_entry_risk:
        if current_dd <= _dd_threshold:
            _sd_reasons.append(f"고점대비 {current_dd*100:.1f}% 하락 (임계치 {_dd_threshold*100:.0f}%)")
        if _ma50_damage:
            _sd_reasons.append("MA50 하회 (대장주 요건 미충족)")
        if below_ma20 and not _rs_strong:
            _sd_reasons.append(f"MA20 하회 + RS {rs_label}")
        if is_single_day_breakdown:
            _sd_reasons.append("단일 봉 급락 감지")
    _sd_reasons_t = tuple(_sd_reasons)

    def _set_decision(label, color, code=None, reasons=()):
        outcome = build_decision_outcome(label, color, code, reasons=reasons)
        return outcome.label, outcome.color, outcome

    if is_free:
        if is_core_dca_allowed:
            dca_label = core_dca_context["core_dca_label"]
            prefix = "🧱신규 코어 ETF" if short_history else "🧱코어 ETF"
            decision_outcome = build_core_dca_outcome(prefix, core_dca_rate, dca_label)
            dec, col = decision_outcome.label, decision_outcome.color
        elif is_etf and short_history:
            decision_outcome = build_limited_history_etf_outcome(
                len(df), has_pos, my_price, cur_p, targ_w, curr_w, weight_gap,
                rsi_now, mfi_now, pct_b_now, price_vs_avg
            )
            dec, col = decision_outcome.label, decision_outcome.color
        elif mfi_now >= 85:
            dec, col, decision_outcome = _set_decision(
                "🚫극단과열: 추격금지", "#dc2626", "EXTREME_OVERHEAT_NO_CHASE",
                reasons=(
                    f"MFI {mfi_now:.0f} (기준: 85 초과) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                    "극단 과열 — 추격 매수 금지, 눌림 후 재접근",
                ),
            )
        elif is_breakout_extreme:
            dec, col, decision_outcome = _set_decision(
                "⚠️과열확장: 추격금지, MA5 대기", "#d97706", "OVERHEAT_EXTENSION_WAIT_MA5",
                reasons=(
                    f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                    "과열 확장 구간 — MA5 눌림 확인 후 진입",
                ),
            )
        elif is_breakout_normal:
            dec, col, decision_outcome = _set_decision(
                "🔥불뿜는 대장주: 초단기 눌림(MA5) 진입", "#ec4899", "LEADER_MA5_FAST_PULLBACK_ENTRY",
                reasons=(
                    f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                    "불뿜는 대장주 포착 — MA5 눌림 초단기 진입 기회",
                ),
            )
        elif pct_b_now >= 0.95:
            dec, col, decision_outcome = _set_decision(
                "⚠️밴드상단: 눌림 대기", "#d97706", "BAND_UPPER_WAIT",
                reasons=(
                    f"%B {pct_b_now:.2f} (기준: 0.95 이상) / RSI {rsi_now:.0f}",
                    "볼린저 밴드 상단 근접 — 눌림 대기 후 진입",
                ),
            )
        elif current_dd <= -0.2:
            dec, col, decision_outcome = _set_decision(
                "🚨위기/패닉: 투매 포착", "#dc2626", "CRISIS_PANIC_SELL_OFF",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 하락",
                    "급락/투매 포착 (미보유) — 극단 분할매수 검토",
                ),
            )
        elif is_structure_damage_entry_risk:
            dec, col, decision_outcome = _set_decision(
                "⚠️구조훼손: 신규진입 보류", "#d97706", "STRUCTURE_DAMAGE_NO_ENTRY",
                reasons=_sd_reasons_t,
            )
        elif is_52w_breakout and mfi_now < 80 and pct_b_now < 0.95:
            dec, col, decision_outcome = _set_decision(
                "🚀52주 신고가 돌파: 모멘텀 진입 검토", "#7c3aed", "BREAKOUT_52W_ENTRY",
                reasons=(
                    f"52주 신고가 돌파 / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                    "모멘텀 돌파 신호 — 소액 정찰 진입 검토",
                ),
            )
        elif trend == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
            dec, col, decision_outcome = _set_decision(
                "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
                reasons=(
                    f"정배열 + RS강함 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                    "S급 눌림목 최적 구간 — 탑승 찬스",
                ),
            )
        elif rsi_now <= 30:
            dec, col, decision_outcome = _set_decision(
                "🔥낙폭과대: 신규 진입", "#16a34a", "OVERSOLD_NEW_ENTRY",
                reasons=(
                    f"RSI {rsi_now:.0f} (기준: 30 이하) / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                    f"고점대비 {current_dd*100:.1f}% / 재무점수 {fin_score}점 / 추세 {trend}",
                    "과매도 구간 신규 진입 — 소액 분할 매수",
                ),
            )
        elif is_early_entry:
            dec, col, decision_outcome = _set_decision(
                "🟢선진입 가능 구간", "#16a34a", "EARLY_ENTRY",
                reasons=(
                    f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                    "선진입 조건 충족 — 반전 초입 소액 진입 가능",
                ),
            )
        elif is_clean_leader_entry:
            dec, col, decision_outcome = _set_decision(
                "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
                reasons=(
                    f"기술점수 {adj_tech_score:.1f} / 추세 {trend} / RS {rs_label}",
                    f"고점대비 {current_dd*100:.1f}% (구조훼손 없음) / 재무점수 {fin_score}점",
                    "대장주 조건 충족 — 1차 정찰 진입 가능",
                ),
            )
        elif trend == "🌊역배열(하락)" and adj_tech_score >= 5:
            dec, col, decision_outcome = _set_decision(
                "🎯낙폭과대: 분할매수", "#8b5cf6", "OVERSOLD_DCA",
                reasons=(
                    f"역배열 + 기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                    "역배열 낙폭과대 — 소량 분할매수 검토",
                ),
            )
        elif ret_3m < 0 and trend in ["🌊역배열(하락)", "⏳혼조세"]:
            dec, col, decision_outcome = _set_decision(
                "⚠️하락추세: 진입보류", "#dc2626", "DOWNTREND_NO_ENTRY",
                reasons=(
                    f"추세 {trend} / 3개월 수익률 {ret_3m*100:.1f}%",
                    "하락추세 + 마이너스 수익 — 진입 보류",
                ),
            )
        elif trend == "🌊역배열(하락)":
            dec, col, decision_outcome = _set_decision(
                "🚫역배열: 진입 보류", "#dc2626", "REVERSE_TREND_NO_ENTRY",
                reasons=(
                    f"추세 {trend} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                    "역배열 상태 — 추세 전환 확인 후 진입",
                ),
            )
        else:
            dec, col, decision_outcome = _set_decision(
                "🔍관망: 타점 대기", "#64748b", "WATCH_WAIT_ENTRY",
                reasons=(
                    f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                    "특별 진입 신호 없음 — 타점 대기",
                ),
            )
    else:
        if not is_etf and fin_score <= 1:
            dec, col, decision_outcome = _set_decision(
                "🚨하드차단: 재무F급(처분)", "#dc2626", "HARD_BLOCK_FINANCIAL_F",
                reasons=(f"재무점수 {fin_score}점 (기준: 2점 이상 필요)", "재무 F급 종목 — 보유 지속 시 손실 위험 높음"),
            )
        elif curr_w > targ_w and targ_w > 0:
            dec, col, decision_outcome = _set_decision(
                "🛑하드차단: 비중 초과", "#dc2626", "HARD_BLOCK_OVERWEIGHT",
                reasons=(
                    f"현재비중 {curr_w:.1f}% > 목표비중 {targ_w:.1f}% (+{curr_w-targ_w:.1f}%p 초과)",
                    "비중 초과 상태 — 신규 매수 불가, 리밸런싱 또는 익절 검토",
                ),
            )
        elif curr_w >= targ_w and targ_w > 0:
            dec, col, decision_outcome = _set_decision(
                "⏸️하드차단: 비중 충족(관망)", "#d97706", "HARD_BLOCK_TARGET_FILLED",
                reasons=(
                    f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}%",
                    "비중 충족 - 추가 매수 불필요, 눌림 시 재검토",
                ),
            )
        elif _fmr >= 4.5:
            dec, col, decision_outcome = _set_decision(
                "🛑하드차단: 퍼펙트스톰(대피)", "#dc2626", "HARD_BLOCK_MACRO_STORM",
                reasons=(
                    f"퍼펙트스톰 지수 {_fmr:.1f} (기준: 4.5 이상)",
                    "매크로 위험 최고조 — 신규 매수 전면 중단, 현금 확보 우선",
                ),
            )
        elif is_core_dca_allowed and current_dd <= -0.3:
            prefix = "🧱신규 코어 ETF" if short_history else "🧱코어"
            dec, col, decision_outcome = _set_decision(
                f"{prefix} 폭락: {core_dca_context['core_dca_label']}", "#b91c1c", "CORE_CRASH_DCA",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 폭락 (코어 DCA 구간)",
                    f"코어 ETF 폭락 매수 타이밍 — {core_dca_context['core_dca_label']} 적립",
                ),
            )
        elif current_dd <= -0.5:
            dec, col, decision_outcome = _set_decision(
                "💣패닉(-50%↓): 최종투입", "#7f1d1d", "PANIC_FINAL_DEPLOY",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 하락 (패닉 최심 구간)",
                    "예비 현금 최종 투입 — 분할 매수 완료 단계",
                ),
            )
        elif current_dd <= -0.4:
            dec, col, decision_outcome = _set_decision(
                "💣패닉(-40%↓): 현금 투입", "#991b1b", "PANIC_CASH_DEPLOY",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 하락 (패닉 구간)",
                    "현금 비중 투입 타이밍 — 분할 매수 2~3회차",
                ),
            )
        elif current_dd <= -0.3:
            dec, col, decision_outcome = _set_decision(
                "🚨위기(-30%↓): 코어 집중", "#b91c1c", "CRISIS_CORE_FOCUS",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 하락 (위기 구간)",
                    "코어 ETF 중심 분할 매수 집중 — 스윙 신규 진입 보류",
                ),
            )
        elif is_core_dca_allowed and current_dd <= -0.2:
            prefix = "🧱신규 코어 ETF" if short_history else "🧱코어"
            dec, col, decision_outcome = _set_decision(
                f"{prefix} 하락: {core_dca_context['core_dca_label']}", "#16a34a", "CORE_DRAWDOWN_DCA",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 하락 (코어 DCA 구간)",
                    f"코어 하락 매수 타이밍 — {core_dca_context['core_dca_label']} 적립",
                ),
            )
        elif is_structure_damage_entry_risk and not has_pos:
            dec, col, decision_outcome = _set_decision(
                "⚠️구조훼손: 신규진입 보류", "#d97706", "STRUCTURE_DAMAGE_NO_ENTRY",
                reasons=_sd_reasons_t,
            )
        elif current_dd <= -0.2 and has_pos and is_structure_damage_entry_risk:
            dec, col, decision_outcome = _set_decision(
                "⚠️고점대비 -20%: 추매금지/손절기준 점검", "#d97706", "DRAWDOWN_20_HOLDING_STOP_CHECK",
                reasons=(f"고점대비 {current_dd*100:.1f}% 하락",) + _sd_reasons_t,
            )
        elif current_dd <= -0.2 and has_pos:
            dec, col, decision_outcome = _set_decision(
                "⚠️고점대비 -20%: 추매금지/원인점검", "#d97706", "DRAWDOWN_20_HOLDING_CAUSE_CHECK",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 하락 (기준: -20%)",
                    "구조훼손 신호 없음 — 하락 원인(매크로/실적) 점검 후 판단",
                ),
            )
        elif current_dd <= -0.2:
            dec, col, decision_outcome = _set_decision(
                "⚠️고점대비 -20%: 신규진입 보류", "#d97706", "DRAWDOWN_20_NO_ENTRY",
                reasons=(
                    f"고점대비 {current_dd*100:.1f}% 하락 (기준: -20%)",
                    "미보유 종목 — 하락 안정 확인 후 재검토",
                ),
            )
        
        
        elif is_structure_damage_entry_risk and has_pos:
            dec, col, decision_outcome = _set_decision(
                "⚠️구조훼손: 추매금지/손절기준 점검", "#d97706", "STRUCTURE_DAMAGE_HOLDING_CHECK",
                reasons=_sd_reasons_t,
            )
        elif is_structure_damage_entry_risk:
            dec, col, decision_outcome = _set_decision(
                "⚠️구조훼손: 신규진입 보류", "#d97706", "STRUCTURE_DAMAGE_NO_ENTRY",
                reasons=_sd_reasons_t,
            )
        elif (
            is_exception_entry and
            has_pos and
            my_price > 0 and
            cur_p <= my_price * 1.02 and
            targ_w > 0 and
            curr_w < targ_w
        ):
            dec, col, decision_outcome = _set_decision(
                "🟣예외승인: 정찰대 추매(MA5/FVG)", "#7c3aed", "EXCEPTION_ADD_ON",
                reasons=(
                    f"MA5 눌림 또는 FVG 구간 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                    f"예외 승인 — 정찰대 추매 조건 충족 (평단 {my_price:,.0f}원 근처)",
                ),
            )
        elif is_exception_entry and (not has_pos):
            dec, col, decision_outcome = _set_decision(
                "🟣예외승인: 정찰대 진입(MA5/FVG)", "#7c3aed", "EXCEPTION_ENTRY",
                reasons=(
                    f"MA5 눌림 또는 FVG 구간 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                    "예외 승인 — 정찰대 신규 진입 조건 충족",
                ),
            )

        elif is_core_dca_allowed:
            dca_label = core_dca_context["core_dca_label"]
            prefix = "🧱신규 코어 ETF" if short_history else "🧱코어"
            decision_outcome = build_core_dca_outcome(prefix, core_dca_rate, dca_label)
            dec, col = decision_outcome.label, decision_outcome.color
        elif is_etf and short_history:
            decision_outcome = build_limited_history_etf_outcome(
                len(df), has_pos, my_price, cur_p, targ_w, curr_w, weight_gap,
                rsi_now, mfi_now, pct_b_now, price_vs_avg
            )
            dec, col = decision_outcome.label, decision_outcome.color
        elif mfi_now >= 85:
            dec, col, decision_outcome = _set_decision(
                "🚫하드차단: MFI 극단 과열", "#dc2626", "HARD_BLOCK_MFI_OVERHEAT",
                reasons=(
                    f"MFI {mfi_now:.0f} (기준: 85 초과) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                    "자금흐름 극단 과열 — 추격 매수 위험, 눌림 후 재진입",
                ),
            )
        elif is_breakout_extreme:
            dec, col, decision_outcome = _set_decision(
                "⚠️과열확장: 추격금지, MA5 대기", "#d97706", "OVERHEAT_EXTENSION_WAIT_MA5",
                reasons=(
                    f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                    "과열 확장 구간 — MA5 눌림 확인 후 추가",
                ),
            )
        elif is_breakout_normal:
            dec, col, decision_outcome = _set_decision(
                "🔥불뿜는 대장주: MA5 눌림 진입", "#ec4899", "LEADER_MA5_PULLBACK_ENTRY",
                reasons=(
                    f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                    "불뿜는 대장주 — MA5 눌림 진입 기회",
                ),
            )
        elif (not is_etf) and pct_b_now >= 0.95:
            dec, col, decision_outcome = _set_decision(
                "🚫하드차단: 볼린상단 이탈", "#dc2626", "HARD_BLOCK_BOLLINGER_UPPER",
                reasons=(
                    f"%B {pct_b_now:.2f} (기준: 0.95 초과) / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                    "볼린저 밴드 상단 이탈 — 과매수 구간, 눌림 대기",
                ),
            )
        elif is_etf_accumulation_ok and weight_gap >= 10:
            dec, col, decision_outcome = _set_decision(
                "✅ETF 비중부족 큼: 소액 적립 허용", "#16a34a", "ETF_LARGE_GAP_DCA_OK",
                reasons=(
                    f"목표비중 {targ_w:.1f}% 대비 {weight_gap:.1f}%p 부족 (큰 미달)",
                    f"ETF 적립 허용 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / 추세 {trend}",
                ),
            )
        elif is_etf_accumulation_ok:
            dec, col, decision_outcome = _set_decision(
                "✅ETF 목표비중 미달: 적립식 매수 가능", "#16a34a", "ETF_DCA_OK",
                reasons=(
                    f"목표비중 {targ_w:.1f}% 대비 {weight_gap:.1f}%p 부족",
                    f"ETF 적립 가능 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / 추세 {trend}",
                ),
            )
        elif is_stock_add_on_strength:
            dec, col, decision_outcome = _set_decision(
                "✅상승확인: 2차 정찰 추매 가능", "#16a34a", "STRENGTH_ADD_ON_OK",
                reasons=(
                    f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                    "상승 확인 후 2차 정찰 추매 — 조건 충족",
                ),
            )
        elif has_pos and my_price > 0 and cur_p > my_price * 1.02:
            # 최종승인자가 막는 이유를 구체적으로 표시
            
            # 케이스 1: 비중이 꽉 참
            if targ_w > 0 and curr_w >= targ_w * 0.97:
                if grade.startswith("💎") or grade.startswith("✅"):
                    dec, col, decision_outcome = _set_decision(
                        "⏸️S급이나 비중 충족: 눌림 오면 재진입", "#8b5cf6", "TARGET_FILLED_S_GRADE_WAIT",
                        reasons=(
                            f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}% ({grade[:3]})",
                            "비중 충족 + S급 - 눌림 오면 재진입",
                        ),
                    )
                else:
                    dec, col, decision_outcome = _set_decision(
                        "⏸️비중 충족: 보유 유지", "#64748b", "TARGET_FILLED_HOLD",
                        reasons=(
                            f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}%",
                            "비중 충족 - 보유 유지",
                        ),
                    )
            
            # 케이스 2: 비중 여유 있는데 과열
            elif weight_gap >= 3 and (mfi_now >= 80 or rsi_now >= 72 or pct_b_now >= 0.90):
                if grade.startswith("💎") or grade.startswith("✅"):
                    dec, col, decision_outcome = _set_decision(
                        "⏳S급 과열 구간: 식힌 뒤 추가", "#d97706", "S_GRADE_OVERHEAT_WAIT",
                        reasons=(
                            f"MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f} ({grade[:3]} 과열)",
                            "S급이나 과열 — 식힌 뒤 추가",
                        ),
                    )
                else:
                    dec, col, decision_outcome = _set_decision(
                        "⏳과열: 눌림 대기", "#d97706", "OVERHEAT_WAIT",
                        reasons=(
                            f"MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                            "과열 구간 — 눌림 대기 후 추가",
                        ),
                    )
            
            # 케이스 3: 비중 여유 있고 과열 아님 → 추가 허용 조건
            elif weight_gap >= 3 and mfi_now < 75 and rsi_now < 68 and pct_b_now < 0.88:
                if (grade.startswith("💎") and
                    rs_label == "🚀강함" and
                    trend == "🚀정배열(상승)" and
                    fin_score >= 4 and
                    (_fmr < 4.0 if rs_slope_label == "📈RS상승중" else _fmr < 3.5)):
                    dec, col, decision_outcome = _set_decision(
                        "✅S급 비중여유: 분할 추가 가능", "#16a34a", "S_GRADE_ADD_ON_OK",
                        reasons=(
                            f"S급 / 비중여유 {weight_gap:.1f}%p / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                            "S급 비중여유 분할 추가 조건 충족",
                        ),
                    )
                elif grade.startswith("✅") and trend == "🚀정배열(상승)":
                    dec, col, decision_outcome = _set_decision(
                        "📈A급 비중여유: 소액 추가 검토", "#22c55e", "A_GRADE_ADD_ON_REVIEW",
                        reasons=(
                            f"A급 정배열 / 비중여유 {weight_gap:.1f}%p / MFI {mfi_now:.0f}",
                            "A급 정배열 + 비중여유 — 소액 추가 검토",
                        ),
                    )
                else:
                    dec, col, decision_outcome = _set_decision(
                        "⏳평단이상: 추가 하락 대기", "#64748b", "ABOVE_COST_WAIT_PULLBACK",
                        reasons=(
                            f"비중여유 {weight_gap:.1f}%p / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                            "추가 조건 미달 — 추가 하락 대기",
                        ),
                    )
            
            # 케이스 4: 그 외 모든 상황 (비중 여유 없거나 조건 미달 등)
            else:
                dec, col, decision_outcome = _set_decision(
                    "⏳평단이상: 보유 유지", "#64748b", "ABOVE_COST_HOLD",
                    reasons=(
                        f"평단 이상 / 비중여유 {weight_gap:.1f}%p",
                        "추가 조건 미달 — 보유 유지",
                    ),
                )
        elif has_pos:
            if (not is_core_etf) and mfi_now >= 80 and pct_b_now > 0.9 and price_vs_avg > 0.20:
                dec, col, decision_outcome = _set_decision(
                    "🔔익절 타이밍: 고평가+과열+수익20%↑ (분할 매도 검토)", "#dc2626", "PROFIT_TAKE_REVIEW",
                    reasons=(
                        f"MFI {mfi_now:.0f} / %B {pct_b_now:.2f} / 수익률 {price_vs_avg*100:.1f}%",
                        "고평가+과열+수익 20%↑ — 분할 매도 검토",
                    ),
                )
            elif trend == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
                dec, col, decision_outcome = _set_decision(
                    "🎯S급 눌림목: 추매", "#8b5cf6", "S_PULLBACK_ADD_ON",
                    reasons=(
                        f"정배열 + RS강함 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "S급 눌림목 — 추매 타이밍",
                    ),
                )
            elif mfi_now >= 80:
                dec, col, decision_outcome = _set_decision(
                    "⚠️단기과열: 추매 보류", "#d97706", "SHORT_OVERHEAT_NO_ADD",
                    reasons=(
                        f"MFI {mfi_now:.0f} (기준: 80 이상) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "단기 과열 — 추매 보류, 눌림 대기",
                    ),
                )
            elif rsi_now <= 30:
                dec, col, decision_outcome = _set_decision(
                    "🔥낙폭과대: 줍줍 찬스", "#16a34a", "OVERSOLD_ADD_ON",
                    reasons=(
                        f"RSI {rsi_now:.0f} (기준: 30 이하) / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                        f"고점대비 {current_dd*100:.1f}% / 재무점수 {fin_score}점",
                        "과매도 구간 — 분할 추가 매수 기회",
                    ),
                )
            elif rs_label == "🚀강함" and mfi_now < 35:
                dec, col, decision_outcome = _set_decision(
                    "💎S급: 과매도(풀매수)", "#16a34a", "S_GRADE_OVERSOLD_BUY",
                    reasons=(
                        f"RS강함 / MFI {mfi_now:.0f} (기준: 35 이하) / RSI {rsi_now:.0f}",
                        "S급 과매도 — 풀매수 타이밍",
                    ),
                )
            elif adj_tech_score >= 4 and cur_p <= my_price:
                dec, col, decision_outcome = _set_decision(
                    "🎯A급: 기술적 반등", "#16a34a", "A_GRADE_TECH_REBOUND",
                    reasons=(
                        f"기술점수 {adj_tech_score:.1f} / 추세 {trend} / 평단이하",
                        "A급 기술적 반등 신호 — 분할매수",
                    ),
                )
            elif (trend == "🚀정배열(상승)" and pct_b_now < 0.8 and rsi_now < 60 and price_vs_avg <= -0.03 and price_vs_avg > -0.15 and curr_w < targ_w):
                dec, col, decision_outcome = _set_decision(
                    "📈정배열: -3% 이상 눌림 분할매수", "#16a34a", "UPTREND_PULLBACK_DCA",
                    reasons=(
                        f"정배열 / %B {pct_b_now:.2f} / 평단대비 {price_vs_avg*100:.1f}%",
                        "정배열 눌림 분할매수 조건 충족",
                    ),
                )
            elif cur_p > my_price:
                dec, col, decision_outcome = _set_decision(
                    "⏳평단이상: 하락대기(보유)", "#d97706", "ABOVE_COST_WAIT",
                    reasons=(
                        f"평단대비 +{price_vs_avg*100:.1f}% / MFI {mfi_now:.0f}",
                        "평단 이상 — 추가 하락 대기 후 매수",
                    ),
                )
            elif cur_p <= my_price:
                if curr_w >= targ_w and targ_w > 0:
                    dec, col, decision_outcome = _set_decision(
                        "⏸️평단이하: 비중 충족(추매 보류)", "#d97706", "BELOW_COST_TARGET_FILLED",
                        reasons=(
                            f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}%",
                            "평단이하지만 비중 충족 - 추매 보류",
                        ),
                    )
                elif price_vs_avg > -0.03:
                    dec, col, decision_outcome = _set_decision(
                        "⏳평단근처: 추가 하락 대기", "#64748b", "NEAR_COST_WAIT",
                        reasons=(
                            f"평단대비 {price_vs_avg*100:.1f}% (기준: -3% 미만)",
                            "평단 근처 — 추가 하락 대기",
                        ),
                    )
                elif price_vs_avg >= -0.07 and trend != "🌊역배열(하락)" and mfi_now < 80:
                    dec, col, decision_outcome = _set_decision(
                        "✅평단 -3~-7%: 소액 분할매수", "#16a34a", "COST_MINUS_3_7_DCA",
                        reasons=(
                            f"평단대비 {price_vs_avg*100:.1f}% / 추세 {trend} / MFI {mfi_now:.0f}",
                            "평단 -3~7% 구간 소액 분할매수 조건 충족",
                        ),
                    )
                elif price_vs_avg >= -0.15 and fin_score >= 3 and _fmr < 4.5:
                    dec, col, decision_outcome = _set_decision(
                        "🎯평단 -7~-15%: 조건부 분할매수", "#8b5cf6", "COST_MINUS_7_15_CONDITIONAL_DCA",
                        reasons=(
                            f"평단대비 {price_vs_avg*100:.1f}% / 재무점수 {fin_score}점 / FMR {_fmr:.1f}",
                            "평단 -7~15% 조건부 분할매수 조건 충족",
                        ),
                    )
                else:
                    dec, col, decision_outcome = _set_decision(
                        "🚫평단 -15%↓/추세위험: 원인 점검", "#dc2626", "COST_MINUS_15_TREND_RISK",
                        reasons=(
                            f"평단대비 {price_vs_avg*100:.1f}% / 추세 {trend} / 재무점수 {fin_score}점",
                            "평단 -15% 이하 또는 추세 위험 — 원인 점검 필요",
                        ),
                    )
            else:
                dec, col, decision_outcome = _set_decision(
                    "⏳보유중(신호대기)", "#64748b", "HOLD_WAIT_SIGNAL",
                    reasons=(
                        f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                        "보유 중 — 매수 신호 대기",
                    ),
                )
        else:
            if 0.85 <= pct_b_now < 0.95:
                dec, col, decision_outcome = _set_decision(
                    "⚠️상단부근: 눌림 대기", "#d97706", "NEAR_UPPER_WAIT",
                    reasons=(
                        f"%B {pct_b_now:.2f} (기준: 0.85~0.95) / RSI {rsi_now:.0f}",
                        "밴드 상단 근처 — 눌림 대기 후 진입",
                    ),
                )
            elif is_52w_breakout and mfi_now < 80 and pct_b_now < 0.95:
                dec, col, decision_outcome = _set_decision(
                    "🚀52주 신고가 돌파: 모멘텀 진입 검토", "#7c3aed", "BREAKOUT_52W_ENTRY",
                    reasons=(
                        f"52주 신고가 돌파 / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                        "모멘텀 돌파 신호 — 소액 정찰 진입 검토",
                    ),
                )
            elif trend == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
                dec, col, decision_outcome = _set_decision(
                    "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
                    reasons=(
                        f"정배열 + RS강함 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "S급 눌림목 최적 구간 — 탑승 찬스",
                    ),
                )
            elif mfi_now >= 80:
                dec, col, decision_outcome = _set_decision(
                    "⚠️단기과열: 진입 보류", "#d97706", "SHORT_OVERHEAT_NO_ENTRY",
                    reasons=(
                        f"MFI {mfi_now:.0f} (기준: 80 이상) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "단기 과열 — 신규 진입 보류, 눌림 대기",
                    ),
                )
            elif rsi_now <= 30:
                dec, col, decision_outcome = _set_decision(
                    "🔥낙폭과대: 신규 진입", "#16a34a", "OVERSOLD_NEW_ENTRY",
                    reasons=(
                        f"RSI {rsi_now:.0f} (기준: 30 이하) / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                        f"고점대비 {current_dd*100:.1f}% / 재무점수 {fin_score}점 / 추세 {trend}",
                        "과매도 구간 신규 진입 — 소액 분할매수",
                    ),
                )
            elif is_early_entry:
                dec, col, decision_outcome = _set_decision(
                    "🟢선진입 가능: 반전 초입", "#16a34a", "EARLY_REVERSAL_ENTRY",
                    reasons=(
                        f"RSI {rsi_now:.0f} / 추세 {trend}",
                        "반전 초입 신호 — 소액 선진입 가능",
                    ),
                )
            elif is_clean_leader_entry:
                dec, col, decision_outcome = _set_decision(
                    "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
                    reasons=(
                        f"기술점수 {adj_tech_score:.1f} / 추세 {trend} / RS {rs_label}",
                        f"고점대비 {current_dd*100:.1f}% (구조훼손 없음) / 재무점수 {fin_score}점",
                        "대장주 조건 충족 — 1차 정찰 진입 가능",
                    ),
                )
            elif trend == "🌊역배열(하락)" and adj_tech_score >= 5:
                dec, col, decision_outcome = _set_decision(
                    "🎯낙폭과대: 분할매수", "#8b5cf6", "OVERSOLD_DCA",
                    reasons=(
                        f"역배열 + 기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "역배열 낙폭과대 — 소량 분할매수 검토",
                    ),
                )
            elif ret_3m < 0 and trend in ["🌊역배열(하락)", "⏳혼조세"]:
                dec, col, decision_outcome = _set_decision(
                    "⚠️하락추세: 진입보류", "#dc2626", "DOWNTREND_NO_ENTRY",
                    reasons=(
                        f"추세 {trend} / 3개월 수익률 {ret_3m*100:.1f}%",
                        "하락추세 + 마이너스 수익 — 진입 보류",
                    ),
                )
            elif trend == "🌊역배열(하락)":
                dec, col, decision_outcome = _set_decision(
                    "🚫진입보류: 역배열 대기", "#dc2626", "REVERSE_TREND_NO_ENTRY",
                    reasons=(
                        f"추세 {trend} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "역배열 상태 — 추세 전환 확인 후 진입",
                    ),
                )
            else:
                # 상승 추세에서 중립 구간 진입 신호
                if (
                    trend == "🚀정배열(상승)" and
                    rs_label == "🚀강함" and
                    45 <= rsi_now <= 65 and
                    0.35 <= pct_b_now <= 0.75 and
                    mfi_now < 75 and
                    _fmr < 3.5
                ):
                    if fin_score >= 4:
                        dec, col, decision_outcome = _set_decision(
                            "🎯우량주 눌림 구간: 정찰 진입 적합", "#8b5cf6", "QUALITY_PULLBACK_ENTRY",
                            reasons=(
                                f"재무점수 {fin_score}점 / 기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f}",
                                f"정배열 + RS강함 + %B {pct_b_now:.2f} — 우량주 눌림 정찰 진입 적합",
                            ),
                        )
                    else:
                        dec, col, decision_outcome = _set_decision(
                            "📈추세 눌림 구간: 소액 탐색 가능", "#3b82f6", "TREND_PULLBACK_EXPLORE",
                            reasons=(
                                f"기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                                f"정배열 + RS강함 — 추세 눌림 소액 탐색 (재무점수 {fin_score}점)",
                            ),
                        )
    
                elif (
                    trend == "🚀정배열(상승)" and
                    rs_label == "➖보통" and
                    rsi_now < 55 and pct_b_now < 0.65
                ):
                    dec, col, decision_outcome = _set_decision(
                        "🔍정배열 눌림: 신호 확인 후 접근", "#64748b", "UPTREND_PULLBACK_CONFIRM",
                        reasons=(
                            f"정배열 + RS보통 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                            "정배열 눌림이나 RS 보통 — 추가 신호 확인 후 접근",
                        ),
                    )
    
                else:
                    if grade.startswith("💎") and trend == "🚀정배열(상승)":
                        dec, col, decision_outcome = _set_decision(
                            "🔍S급 정배열: 눌림 구간 진입 대기", "#8b5cf6", "S_UPTREND_WAIT_PULLBACK",
                            reasons=(
                                f"S급 정배열 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                                "S급 정배열 확인 — 눌림 구간 진입 대기",
                            ),
                        )
                    elif grade.startswith("✅") and trend == "🚀정배열(상승)":
                        dec, col, decision_outcome = _set_decision(
                            "🔍A급 정배열: 타점 탐색 중", "#3b82f6", "A_UPTREND_SEARCH_ENTRY",
                            reasons=(
                                f"A급 정배열 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                                "A급 정배열 — 타점 탐색 중",
                            ),
                        )
                    else:
                        dec, col, decision_outcome = _set_decision(
                            "🔍대기: 신규 타점 탐색", "#64748b", "SEARCH_NEW_ENTRY",
                            reasons=(
                                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                                "진입 조건 미충족 — 타점 탐색",
                            ),
                        )

    # ── 포지션 사이징 힌트 ────────────────────────────────────────────────────
    if decision_outcome is None:
        decision_outcome = build_decision_outcome(dec, col)
    _is_new_entry_signal = (not has_pos) and is_new_entry_decision_code(decision_outcome.code)
    sizing_hint = build_position_sizing_hint(_is_new_entry_signal, targ_w, eff_total, cur_p, is_etf)

    return {
        "cur_p": cur_p, "rsi": rsi_now, "mfi": mfi_now, "pct_b": pct_b_now, "rs_label": rs_label, "adj": adj_tech_score,
        "dec": decision_outcome.label, "col": decision_outcome.color,
        "decision_code": decision_outcome.code, "decision_group": decision_outcome.group,
        "decision_reasons": decision_outcome.reasons,
        "grade": grade, "t_score": t_score, "tech_total": tech_total, "fin_score": fin_score,
        "dd": current_dd, "ret_3m": ret_3m, "ret_6m": ret_6m, "target_w": targ_w, "current_w": curr_w, "buy_amt": buy_amount,
        "bucket": effective_bucket, "short_history": short_history, "history_days": len(df), **core_dca_context,
        "day_ret": day_ret, "vol_ratio": vol_ratio, "structure_risk": is_structure_damage_entry_risk,
        "sizing_hint": sizing_hint,
        "ext_structure": ext_structure, "int_structure": int_structure, "pd_zone": pd_zone, "smc_action": smc_action,
        "ma5": last["MA5"], "ma20": last["MA20"], "ma50": last["MA50"], "ma120": last["MA120"], "sqz": sqz_status, "macd": macd_state, "rt_macd": rt_macd_label,
        "trend": trend, "fvg_type": fvg_info["type"], "fvg_active": fvg_info["active"], "fvg_top": fvg_info["top"], "fvg_bottom": fvg_info["bottom"],
        "liq_state": liq_state, "int_event": int_event, "ext_event": ext_event, 
        "main_s": main_score, "rs_s": rs_s, "mfi_s": mfi_s,
        "trend_s": trend_s, "macd_s": macd_s, "sqz_s": sqz_s,
        "rs_slope_s": rs_slope_s, "rs_slope_label": rs_slope_label, "rs_slope_val": rs_slope_val,
        "profit_take_signal": (has_pos and (not is_core_etf) and mfi_now >= 80 and pct_b_now > 0.9 and price_vs_avg > 0.20),
        "rr_ratio": rr_ratio, "rr_target": rr_target_price, "rr_stop": rr_stop_atr,
        "is_52w_breakout": is_52w_breakout,
        "sector_flow_state": sector_flow_state,
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
    if "판정분류" in view_df.columns:
        signal_group = view_df["판정분류"].astype(str)
    else:
        signal_group = view_df["🔥기술적 타점"].astype(str).map(classify_decision_signal)
    buyish_count = int((signal_group == "buyish").sum())
    caution_count = int((signal_group == "caution").sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("표시 종목", f"{len(view_df)}개")
    m2.metric("평균 ADJ", "-" if adj.dropna().empty else f"{adj.mean():.1f}")
    m3.metric("매수/관심 신호", f"{buyish_count}개")
    m4.metric("차단/주의 신호", f"{caution_count}개")

    if "ETF" in group_label:
        show_cols = [
            "시장", "유형", "종목명", "티커", "현재가", "MDD",
            "📌후보등급", "RS", "시장벤치", "기초자산", "기초벤치", "RSI", "MFI", "볼린저 %B",
            "🔥기술적 타점", "핵심근거", "Adj점수"
        ]
    elif "개별주" in group_label:
        show_cols = [
            "시장", "유형", "종목명", "티커", "현재가", "MDD", "재무점수",
            "📌후보등급", "RS", "시장벤치", "섹터RS", "섹터벤치",
            "🔥기술적 타점", "핵심근거", "Adj점수"
        ]
    else:
        show_cols = [
            "시장", "유형", "종목명", "티커", "현재가", "MDD", "재무점수",
            "📌후보등급", "RS", "시장벤치", "기초자산", "기초벤치", "섹터RS", "섹터벤치",
            "🔥기술적 타점", "핵심근거", "Adj점수"
        ]
    st.dataframe(view_df[[c for c in show_cols if c in view_df.columns]], use_container_width=True, height=640, hide_index=True)


def build_precision_narrative(name, tkr, c, fin_score, has_p, my_p):
    """
    정밀관측소 차트 아래 표시할 종합 서술형 해설.
    외부 API 없이 이미 계산된 c 딕셔너리와 fin_score만 사용합니다.
    """
    dec         = c.get("dec", "")
    grade       = c.get("grade", "")
    t_score     = c.get("t_score", 0)
    tech_total  = c.get("tech_total", 0)
    trend       = c.get("trend", "")
    rs_label    = c.get("rs_label", "")
    rs_slope    = c.get("rs_slope_label", "")
    rsi         = c.get("rsi", 0.0)
    mfi         = c.get("mfi", 0.0)
    pct_b       = c.get("pct_b", 0.0)
    macd        = c.get("macd", "")
    sqz         = c.get("sqz", "")
    ext_struct  = c.get("ext_structure", "")
    int_struct  = c.get("int_structure", "")
    int_event   = c.get("int_event", "None")
    ext_event   = c.get("ext_event", "None")
    fvg_type    = c.get("fvg_type", "없음")
    fvg_active  = c.get("fvg_active", False)
    fvg_top     = c.get("fvg_top", 0)
    fvg_bottom  = c.get("fvg_bottom", 0)
    pd_zone     = c.get("pd_zone", "")
    smc_action  = c.get("smc_action", "")
    smc_insight = c.get("smc_insight", "")
    sector_flow = c.get("sector_flow_state", "-")
    is_52w      = c.get("is_52w_breakout", False)
    rr_ratio    = c.get("rr_ratio")
    rr_target   = c.get("rr_target", 0)
    rr_stop     = c.get("rr_stop", 0)
    cur_p       = c.get("cur_p", 0)
    day_ret     = c.get("day_ret", 0.0)
    vol_ratio   = c.get("vol_ratio", 0.0)
    ma5         = c.get("ma5", 0)
    ma20        = c.get("ma20", 0)
    decision_code = c.get("decision_code", "")

    lines = []

    # ── 1. 현재 판정 한 줄 ──────────────────────────────────
    fin_labels = {4: "💎완성형 우량(4/4)", 3: "✅양호(3/4)", 2: "🔶보통(2/4)", 1: "⚠️주의(1/4)", 0: "🚨위험(0/4)"}
    fin_desc = fin_labels.get(fin_score, f"{fin_score}점")
    lines.append(
        f"<b>📋 현재 판정</b>: <b>{dec}</b> &nbsp;|&nbsp; "
        f"후보등급 {grade} &nbsp;|&nbsp; 종합점수 {t_score}점 "
        f"(기술 {tech_total}점 / 재무 {fin_desc})"
    )

    # ── 2. 기술 구조 ─────────────────────────────────────────
    # 추세
    trend_interp = {
        "🚀정배열(상승)": "장기 정배열 상승 구조",
        "🌊역배열(하락)": "역배열 하락 구조",
        "➡️횡보/혼조": "횡보·혼조 구간",
        "🆕신규상장/자료부족": "상장 초기(MA 미형성)",
    }.get(trend, trend)

    # RSI
    if rsi >= 70:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 단기 과열 구간, 조정·횡보 가능성 있음"
    elif rsi >= 60:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 강세 유지 중"
    elif rsi >= 45:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 눌림 구간, 진입 적합 범위"
    elif rsi >= 30:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 약세·바닥 탐색 중"
    else:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 극단적 과매도"

    # %B
    if pct_b > 0.82:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 상단 초과, 단기 과열"
    elif pct_b >= 0.75:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 상단 근접"
    elif pct_b >= 0.35:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 중립 구간"
    else:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 하단 근접, 과매도 구간"

    # MFI
    if mfi >= 80:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 유입 과열(익절 주의)"
    elif mfi >= 55:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 유입 우세"
    elif mfi >= 40:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 중립"
    else:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 유출 우세"

    # RS slope
    slope_desc = ""
    if rs_slope == "📈RS상승중":
        slope_desc = ", 상대강도 가속 중"
    elif rs_slope == "📉RS하락중":
        slope_desc = ", 상대강도 약화 중(추격 주의)"

    lines.append(
        f"🔧 <b>기술 구조</b>: {trend_interp}, RS {rs_label}{slope_desc}. "
        f"{rsi_interp}. {pb_interp}. {mfi_interp}. "
        f"MACD: <b>{macd}</b> / SQZ: <b>{sqz}</b>."
    )

    # ── 3. SMC 구조 ──────────────────────────────────────────
    smc_parts = [f"외부구조 <b>{ext_struct}</b> / 내부구조 <b>{int_struct}</b>"]
    if int_event and int_event not in ("None", "없음", ""):
        smc_parts.append(f"내부 이벤트: <b>{int_event}</b>")
    if ext_event and ext_event not in ("None", "없음", ""):
        smc_parts.append(f"외부 이벤트: <b>{ext_event}</b>")
    if fvg_type != "없음" and fvg_type:
        fvg_status = "미충족(지지대 유효)" if fvg_active else "이미 터치됨"
        fvg_range = ""
        if fvg_bottom and fvg_top and fvg_bottom > 0:
            fvg_range = f" ({format_currency(fvg_bottom, tkr)}~{format_currency(fvg_top, tkr)})"
        smc_parts.append(f"FVG: <b>{fvg_type}</b> {fvg_status}{fvg_range}")
    smc_parts.append(f"현재 가격대: <b>{pd_zone}</b>")
    if is_52w:
        smc_parts.append("🚀 <b>52주 신고가 돌파</b>")
    lines.append("🛡️ <b>SMC 구조</b>: " + " | ".join(smc_parts))
    if smc_insight:
        lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;→ {smc_insight}")
    if smc_action:
        lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;🎯 실행 해석: <b>{smc_action}</b>")

    # ── 4. 수급·가격 흐름 ────────────────────────────────────
    flow_parts = [f"섹터 머니플로우: <b>{sector_flow}</b>"]
    if day_ret != 0:
        dr_emoji = "🔺" if day_ret > 0 else "🔻"
        flow_parts.append(f"전일 등락: {dr_emoji} <b>{day_ret*100:.1f}%</b>")
    if vol_ratio > 0:
        vol_desc = "거래량 급증" if vol_ratio >= 2 else ("보통" if vol_ratio >= 0.7 else "거래량 감소")
        flow_parts.append(f"거래량 20일비: <b>{vol_ratio:.1f}x</b> ({vol_desc})")
    if ma5 > 0 and ma20 > 0 and cur_p > 0:
        pos_vs_ma5 = (cur_p / ma5 - 1) * 100
        pos_vs_ma20 = (cur_p / ma20 - 1) * 100
        flow_parts.append(f"MA5 대비 {pos_vs_ma5:+.1f}% / MA20 대비 {pos_vs_ma20:+.1f}%")
    lines.append("💸 <b>수급·가격 흐름</b>: " + " | ".join(flow_parts))

    # ── 5. 진입 조건 (핵심: 뭐가 부족한지) ──────────────────
    entry_hint = ""
    if decision_code == "S_UPTREND_WAIT_PULLBACK":
        missing = []
        if rsi > 65:
            missing.append(f"RSI {rsi:.0f} → <b>65 이하</b>")
        if pct_b > 0.75:
            missing.append(f"%B {pct_b:.2f} → <b>0.75 이하</b>")
        if mfi >= 75:
            missing.append(f"MFI {mfi:.0f} → <b>75 미만</b>")
        if missing:
            entry_hint = (
                f"⏳ <b>진입 전환 조건</b>: {', '.join(missing)} 충족 시 "
                f"<b>'우량주 눌림 구간: 정찰 진입 적합'</b>으로 신호 전환됩니다. "
                f"급락 없이도 며칠 <b>횡보·숨 고르기</b>만으로 충족될 수 있습니다."
            )
    elif decision_code == "A_UPTREND_WAIT_PULLBACK":
        missing = []
        if rsi > 65: missing.append(f"RSI {rsi:.0f} → <b>65 이하</b>")
        if pct_b > 0.75: missing.append(f"%B {pct_b:.2f} → <b>0.75 이하</b>")
        if missing:
            entry_hint = f"⏳ <b>진입 전환 조건 (A급)</b>: {', '.join(missing)} 충족 필요."
    elif decision_code in ("QUALITY_PULLBACK_ENTRY", "TREND_PULLBACK_EXPLORE"):
        entry_hint = "✅ <b>현재 진입 구간</b>: 눌림 매수 적합 시점입니다."
    elif decision_code == "CORE_ETF_DCA_BUY":
        entry_hint = "✅ <b>코어 ETF 분할매수</b> 적합 구간입니다."
    elif decision_code in ("REVERSE_TREND_NO_ENTRY", "STRONG_REVERSE_NO_ENTRY"):
        entry_hint = "🚫 <b>진입 보류</b>: 역배열·하락 구조. 추세 전환 확인 전까지 신규 진입은 위험합니다."
    elif decision_code == "PROFIT_TAKE_SIGNAL":
        entry_hint = "💰 <b>익절 신호</b>: MFI·%B 과열 + 평단 대비 수익 20% 이상. 일부 익절 고려."
    elif decision_code == "HOLD_QUALITY_UPTREND":
        entry_hint = "🏆 <b>홀드 구간</b>: 정배열 유지 중이나 추매보다 홀드가 우선인 타이밍."

    if entry_hint:
        lines.append(entry_hint)

    # ── 6. R/R ───────────────────────────────────────────────
    if rr_ratio and rr_ratio > 0 and rr_target and rr_stop:
        lines.append(
            f"📐 <b>R/R 비율</b>: <b>{rr_ratio:.2f}</b> — "
            f"목표가 {format_currency(rr_target, tkr)} / 손절 {format_currency(rr_stop, tkr)}"
        )

    # ── 7. 내 포지션 손익 ─────────────────────────────────────
    if has_p and my_p > 0 and cur_p > 0:
        pnl_pct = (cur_p / my_p - 1) * 100
        pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
        lines.append(
            f"{pnl_emoji} <b>내 손익</b>: 평단 {format_currency(my_p, tkr)} 대비 현재가 {pnl_pct:+.1f}%"
        )

    border_color = "#10b981" if "진입" in dec or "매수" in dec or "홀드" in dec else (
        "#ef4444" if "보류" in dec or "역배열" in dec else "#6366f1"
    )
    html = (
        f"<div class='info-panel' style='border-left:5px solid {border_color}; line-height:2.0;'>"
        f"<b>📖 종합 해설</b><br><br>"
        + "<br>".join(f"• {line}" for line in lines)
        + "</div>"
    )
    return html


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

    # ==========================================
    # [신규 추가] UI 렌더링: 신규 분석 기능 표출
    # ==========================================
    st.markdown("### 🔍 추가 인사이트 (독립 모듈)")
    
    # 1. 안전하게 주가 데이터 로드 (캐시되어 있어 매우 빠름)
    local_df = load_price_df(ticker, "1y")

    # 2. 3단 컬럼으로 정보 표시
    col_ins1, col_ins2, col_ins3, col_ins4 = st.columns(4)
    
    with col_ins1:
        if not local_df.empty:
            breakout_data = detect_52w_breakout(local_df)
            st.info(f"**수급/추세:**\n{breakout_data['label']}")
        else:
            st.info("**수급/추세:**\n데이터 없음")

    with col_ins2:
        earnings_data = fetch_earnings_date(ticker)
        if earnings_data.get("high_risk"):
            st.warning(f"**이벤트 리스크:**\n{earnings_data['label']}")
        else:
            st.success(f"**이벤트 리스크:**\n{earnings_data['label']}")

    with col_ins3:
        if not local_df.empty:
            current_price = float(local_df['Close'].iloc[-1])
            atr_val = calc_atr(local_df)
            # 기존 c 딕셔너리에서 값 안전하게 빼오기
            target_w = clean_float(c.get("target_w"), 0.0)
            curr_w = clean_float(c.get("current_w"), 0.0)
            
            # 총자산은 임시로 1억 세팅 (이후 필요시 portfolio_summary와 연동)
            size_data = calc_position_size(100000000, target_w, curr_w, current_price, atr_val)
            st.info(f"**손절 가이드 (2 ATR):**\n권장 손절가: {size_data['stop_price']:,.0f}")
        else:
            st.info("**진입/손절 가이드:**\n데이터 없음")  

    with col_ins4:
        if not local_df.empty:
            smc_data = detect_smc_features(local_df)
            st.info(f"**스마트머니(SMC):**\n{smc_data['fvg_label']}\n{smc_data['ob_label']}")
        else:
            st.info("**스마트머니(SMC):**\n데이터 없음")

    # ── 한국 종목 전용: 외국인/기관 수급 + 재무 트렌드 + 공시 ────────────────────
    if str(ticker).upper().endswith((".KS", ".KQ")):
        with st.expander("📊 투자자별 수급 현황 (최근 20거래일)", expanded=False):
            render_investor_trend_panel(ticker, name)
        if not is_etf:
            with st.expander("📈 재무 트렌드 (연간 DART)", expanded=False):
                render_financial_trend_chart(ticker, name)
        _render_dart_disclosure_single(ticker, name)

    render_hold_decision_panel(name, ticker, is_etf, c, fin_score, has_pos, my_price)

VALUATION_INFO_KEYS = [
    "currentPrice",
    "regularMarketPrice",
    "targetMeanPrice",
    "targetMedianPrice",
    "numberOfAnalystOpinions",
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "priceToSalesTrailing12Months",
    "enterpriseToRevenue",
    "enterpriseToEbitda",
    "pegRatio",
    "revenueGrowth",
    "earningsGrowth",
    "profitMargins",
    "operatingMargins",
    "grossMargins",
    "returnOnEquity",
    "debtToEquity",
    "recommendationKey",
    "recommendationMean",
    "trailingEps",
    "bookValue",
]


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_valuation_snapshot(ticker):
    ticker = sanitize_ticker_value(ticker)
    if not ticker:
        return {"ok": False, "reason": "티커 없음", "data": {}}
    try:
        info = yf.Ticker(ticker).get_info()
    except Exception:
        info = {}
    if not isinstance(info, dict):
        info = {}

    data = {key: info.get(key) for key in VALUATION_INFO_KEYS}
    has_any = any(data.get(k) not in [None, ""] for k in VALUATION_INFO_KEYS)

    # ── 한국 종목: yfinance에 데이터가 없으면 네이버 증권으로 보완 ──────────────
    if str(ticker).upper().endswith((".KS", ".KQ")):
        naver = fetch_naver_kr_snapshot(ticker)
        if naver.get("ok"):
            nd = naver.get("data", {})
            for key in VALUATION_INFO_KEYS:
                if data.get(key) in [None, ""] and nd.get(key) not in [None, ""]:
                    data[key] = nd[key]
            has_any = any(data.get(k) not in [None, ""] for k in VALUATION_INFO_KEYS)

    if not has_any:
        reason = "yfinance/네이버 밸류 데이터 없음" if str(ticker).upper().endswith((".KS", ".KQ")) else "yfinance 밸류 데이터 없음"
        return {"ok": False, "reason": reason, "data": data}
    return {"ok": True, "reason": "", "data": data}


def fmt_multiple(value, digits=1):
    number = clean_float(value, np.nan)
    if not finite_num(number) or number <= 0:
        return "-"
    return f"{number:.{digits}f}x"


def fmt_growth_pct(value):
    number = clean_float(value, np.nan)
    if not finite_num(number):
        return "-"
    if abs(number) <= 3:
        number = number * 100
    return f"{number:.1f}%"


def valuation_factor_label(kind, value):
    number = clean_float(value, np.nan)
    if not finite_num(number):
        return "데이터 없음", 0

    if kind == "target_upside":
        if number >= 20:
            return "매력", 2
        if number >= 8:
            return "양호", 1
        if number >= -5:
            return "중립", 0
        return "부담", -1

    if kind == "pe":
        if number <= 20:
            return "낮음", 2
        if number <= 35:
            return "적정", 1
        if number <= 55:
            return "성장프리미엄", 0
        return "높음", -1

    if kind == "pbr":
        if number <= 1.0:
            return "자산가치 이하", 2
        if number <= 2.0:
            return "적정", 1
        if number <= 4.0:
            return "프리미엄", 0
        return "고평가", -1

    if kind == "ps":
        if number <= 3:
            return "낮음", 2
        if number <= 8:
            return "적정", 1
        if number <= 15:
            return "높음", 0
        return "매우 높음", -1

    if kind == "peg":
        if number <= 0:
            return "해석주의", 0
        if number <= 1.2:
            return "매력", 2
        if number <= 2.0:
            return "양호", 1
        if number <= 3.0:
            return "중립", 0
        return "부담", -1

    if kind == "growth":
        if abs(number) <= 3:
            number = number * 100
        if number >= 25:
            return "고성장", 2
        if number >= 10:
            return "성장", 1
        if number >= 0:
            return "둔화", 0
        return "역성장", -1

    if kind == "margin":
        if abs(number) <= 3:
            number = number * 100
        if number >= 25:
            return "우수", 2
        if number >= 10:
            return "양호", 1
        if number >= 0:
            return "낮음", 0
        return "적자", -1

    return "중립", 0


def build_valuation_interpretation(data, current_price, ticker):
    cur = clean_float(current_price, np.nan)
    target_mean = clean_float(data.get("targetMeanPrice"), np.nan)
    target_upside = np.nan
    if finite_num(target_mean) and finite_num(cur) and cur > 0:
        target_upside = (target_mean / cur - 1) * 100

    forward_pe = clean_float(data.get("forwardPE"), np.nan)
    trailing_pe = clean_float(data.get("trailingPE"), np.nan)
    pe_for_score = forward_pe if finite_num(forward_pe) else trailing_pe
    pbr = clean_float(data.get("priceToBook"), np.nan)
    ps = clean_float(data.get("priceToSalesTrailing12Months"), np.nan)
    peg = clean_float(data.get("pegRatio"), np.nan)
    revenue_growth = clean_float(data.get("revenueGrowth"), np.nan)
    earnings_growth = clean_float(data.get("earningsGrowth"), np.nan)
    profit_margin = clean_float(data.get("profitMargins"), np.nan)
    operating_margin = clean_float(data.get("operatingMargins"), np.nan)

    factors = [
        ("목표가 업사이드", "target_upside", target_upside, format_backtest_percent(target_upside)),
        ("PER", "pe", pe_for_score, fmt_multiple(pe_for_score)),
        ("PBR", "pbr", pbr, fmt_multiple(pbr)),
        ("PSR", "ps", ps, fmt_multiple(ps)),
        ("PEG", "peg", peg, fmt_multiple(peg)),
        ("매출 성장", "growth", revenue_growth, fmt_growth_pct(revenue_growth)),
        ("이익 성장", "growth", earnings_growth, fmt_growth_pct(earnings_growth)),
        ("순이익률", "margin", profit_margin, fmt_growth_pct(profit_margin)),
        ("영업이익률", "margin", operating_margin, fmt_growth_pct(operating_margin)),
    ]

    rows = []
    valuation_score = 0
    quality_score = 0
    data_count = 0
    for title, kind, value, display_value in factors:
        label, score = valuation_factor_label(kind, value)
        if finite_num(value):
            data_count += 1
            if kind in ["target_upside", "pe", "pbr", "ps", "peg"]:
                valuation_score += score
            else:
                quality_score += score
        rows.append({"항목": title, "값": display_value or "-", "판정": label})

    if data_count == 0:
        headline = "밸류 데이터 부족"
        color = "#64748b"
        is_kr = str(ticker).upper().endswith((".KS", ".KQ"))
        note = (
            "yfinance 및 네이버 증권에서 현재 종목의 밸류/성장 지표를 가져오지 못했습니다. "
            "네이버 증권 앱에서 직접 확인하세요."
            if is_kr else
            "yfinance에서 현재 종목의 밸류/성장 지표를 충분히 제공하지 않았습니다."
        )
    elif valuation_score >= 4 and quality_score >= 3:
        headline = "가격매력 우수"
        color = "#16a34a"
        note = "목표가/멀티플 부담 대비 성장성과 마진이 같이 뒷받침되는 구간입니다."
    elif valuation_score >= 2 and quality_score >= 2:
        headline = "조건부 적정"
        color = "#22c55e"
        note = "기업 체력은 양호하나 신호, 실적 발표, 목표비중 안에서 분할 접근이 적합합니다."
    elif valuation_score <= 0 and quality_score >= 3:
        headline = "성장 프리미엄"
        color = "#d97706"
        note = "좋은 회사일 수 있지만 가격에는 기대가 많이 반영된 구간입니다."
    elif valuation_score <= 0:
        headline = "밸류 부담"
        color = "#dc2626"
        note = "재무점수가 좋아도 현재 가격 매력은 약할 수 있어 추격매수는 보수적으로 봅니다."
    else:
        headline = "중립"
        color = "#64748b"
        note = "밸류만으로 강한 결론을 내리기 어려워 기술 신호와 실적 뉴스를 함께 봅니다."

    return {
        "headline": headline,
        "color": color,
        "note": note,
        "rows": rows,
        "target_upside": target_upside,
        "target_mean": target_mean,
        "forward_pe": forward_pe,
        "trailing_pe": trailing_pe,
        "ps": ps,
        "peg": peg,
        "revenue_growth": revenue_growth,
        "profit_margin": profit_margin,
    }


def render_valuation_price_panel(name, ticker, is_etf, c, fin_score):
    st.markdown("### 💎 밸류 / 가격매력 점검")

    if is_etf:
        st.info("ETF는 개별 기업 PER/목표가보다 기초지수 흐름, 돈흐름 레이더, 운용보수, 괴리율을 보는 편이 더 적합합니다.")
        return

    snapshot = fetch_valuation_snapshot(ticker)
    data = snapshot.get("data", {}) if snapshot.get("ok") else {}
    analyst_snapshot = get_analyst_snapshot(ticker)
    analyst_data = analyst_snapshot.get("data", {}) if analyst_snapshot.get("ok") else {}
    for key in ["targetMeanPrice", "targetMedianPrice", "numberOfAnalystOpinions", "recommendationKey", "currentPrice", "regularMarketPrice"]:
        if data.get(key) in [None, ""] and analyst_data.get(key) not in [None, ""]:
            data[key] = analyst_data.get(key)

    cur_p = clean_float(c.get("cur_p"), np.nan)
    valuation = build_valuation_interpretation(data, cur_p, ticker)

    v1, v2, v3, v4 = st.columns(4)
    v1.metric("밸류 판정", valuation["headline"])
    v2.metric("목표가 업사이드", format_backtest_percent(valuation["target_upside"]) or "-")
    pe_display = fmt_multiple(valuation["forward_pe"]) if finite_num(valuation["forward_pe"]) else fmt_multiple(valuation["trailing_pe"])
    v3.metric("PER", pe_display)
    v4.metric("PSR", fmt_multiple(valuation["ps"]))

    st.markdown(
        f"<div class='info-panel' style='border-left: 5px solid {valuation['color']};'>"
        f"<b>{escape_html_value(name)} 가격매력 해석</b><br>"
        f"<span class='highlight' style='font-size:1.05em;'>{valuation['headline']}</span><br>"
        f"{escape_html_value(valuation['note'])}<br>"
        f"<span style='color:#cbd5e1;'>재무점수 {fin_score}/4 종목이라도, 밸류 부담이 높으면 분할/대기가 더 유리할 수 있습니다.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    show_rows = valuation["rows"]
    if show_rows:
        with st.expander("밸류 세부 지표", expanded=False):
            st.dataframe(pd.DataFrame(show_rows), use_container_width=True, hide_index=True)
    if not snapshot.get("ok"):
        st.caption(f"밸류 데이터 참고: {snapshot.get('reason', '제공 데이터 없음')}")


def get_valuation_headline_for_final_check(ticker, is_etf, current_price):
    if is_etf:
        return "ETF 별도판단", "ETF는 밸류보다 추세/돈흐름/괴리율 중심으로 봅니다.", np.nan

    snapshot = fetch_valuation_snapshot(ticker)
    data = snapshot.get("data", {}) if snapshot.get("ok") else {}
    analyst_snapshot = get_analyst_snapshot(ticker)
    analyst_data = analyst_snapshot.get("data", {}) if analyst_snapshot.get("ok") else {}
    for key in ["targetMeanPrice", "targetMedianPrice", "numberOfAnalystOpinions", "recommendationKey", "currentPrice", "regularMarketPrice"]:
        if data.get(key) in [None, ""] and analyst_data.get(key) not in [None, ""]:
            data[key] = analyst_data.get(key)

    valuation = build_valuation_interpretation(data, current_price, ticker)
    return valuation["headline"], valuation["note"], valuation["target_upside"]


def final_check_status_style(status):
    if status == "통과":
        return "#16a34a"
    if status == "주의":
        return "#d97706"
    if status == "차단":
        return "#dc2626"
    return "#64748b"


def build_pre_buy_final_checks(name, ticker, is_etf, c, fin_score, has_pos, my_price):
    rows = []

    def add_check(category, status, detail):
        rows.append({"점검항목": category, "상태": status, "해석": detail})

    dec = str(c.get("dec", ""))
    trend = str(c.get("trend", ""))
    rs_label = str(c.get("rs_label", ""))
    structure_risk = bool(c.get("structure_risk"))
    mfi = clean_float(c.get("mfi"), np.nan)
    rsi = clean_float(c.get("rsi"), np.nan)
    pct_b = clean_float(c.get("pct_b"), np.nan)
    dd = clean_float(c.get("dd"), 0.0)
    curr_w = clean_float(c.get("current_w"), 0.0)
    target_w = clean_float(c.get("target_w"), 0.0)
    weight_gap = target_w - curr_w
    core_dca_rate = clean_float(c.get("core_dca_rate"), 0.0)
    is_core_dca = core_dca_rate > 0 and str(c.get("bucket", "")) == "core"
    macro_risk = clean_float(st.session_state.get("_app_final_macro_risk", np.nan), np.nan)
    price_vs_avg = np.nan
    if has_pos and clean_float(my_price, 0.0) > 0 and clean_float(c.get("cur_p"), 0.0) > 0:
        price_vs_avg = clean_float(c.get("cur_p"), 0.0) / clean_float(my_price, 0.0) - 1

    hard_words = ["하드차단", "진입보류", "추격금지", "구조훼손", "추매금지", "현금 확보", "원인 점검"]
    positive_words = ["매수", "진입", "S급", "적립", "승인", "탑승", "반등"]
    if any(word in dec for word in hard_words):
        add_check("시스템 타점", "차단", f"현재 판정이 '{dec}'입니다. 신호가 풀릴 때까지 신규/추매는 보수적으로 봅니다.")
    elif any(word in dec for word in positive_words):
        add_check("시스템 타점", "통과", f"현재 판정이 '{dec}'입니다. 다만 비중과 과열 여부를 함께 봅니다.")
    else:
        add_check("시스템 타점", "주의", f"현재 판정이 '{dec}'입니다. 강한 매수 신호라기보다 확인 구간입니다.")

    if is_etf:
        add_check("재무/상품", "통과", "ETF/ETN류는 개별기업 재무점수 대신 기초자산, 돈흐름, 추세를 봅니다.")
    elif int(fin_score) >= 4:
        add_check("재무/상품", "통과", "재무 4점입니다. 장기 후보로 볼 수 있는 기본 체력은 양호합니다.")
    elif int(fin_score) >= 3:
        add_check("재무/상품", "주의", "재무 3점입니다. 장기보유보다는 실적 개선 지속 여부 확인이 필요합니다.")
    else:
        add_check("재무/상품", "차단", "재무점수가 낮습니다. 기술 신호가 좋아도 장기보유 후보로 보기 어렵습니다.")

    if is_etf and bool(c.get("short_history")):
        add_check("데이터", "주의", f"가격 데이터가 {int(clean_float(c.get('history_days'), 0))}거래일 수준입니다. MA50/MA120 같은 장기 추세보다 RSI/MFI/볼린저/평단 기준 단기 관측을 우선합니다.")

    valuation_headline, valuation_note, target_upside = get_valuation_headline_for_final_check(ticker, is_etf, c.get("cur_p"))
    if valuation_headline in ["가격매력 우수", "조건부 적정", "ETF 별도판단"]:
        val_status = "통과"
    elif valuation_headline in ["성장 프리미엄", "중립", "밸류 데이터 부족"]:
        val_status = "주의"
    else:
        val_status = "차단"
    upside_text = "" if not finite_num(target_upside) else f" 목표가 업사이드 {target_upside:.1f}%."
    add_check("밸류/가격", val_status, f"{valuation_headline}. {valuation_note}{upside_text}")

    if is_core_dca and dd <= -0.2:
        add_check("구조/추세", "주의", f"고점대비 MDD {dd * 100:.1f}%. 코어 ETF 급락 구간은 원인 확인 후 파킹자산 일부 투입 후보로 봅니다.")
    elif structure_risk or dd <= -0.2:
        add_check("구조/추세", "차단", f"고점대비 MDD {dd * 100:.1f}% 또는 구조위험이 있습니다. 원인 확인 전 추매는 금지에 가깝게 봅니다.")
    elif "역배열" in trend or "약함" in rs_label:
        add_check("구조/추세", "주의", f"{trend} / {rs_label}. 추세 회복을 확인하고 접근하는 쪽이 낫습니다.")
    else:
        add_check("구조/추세", "통과", f"{trend} / {rs_label}. 즉시 구조 경고는 크지 않습니다.")

    if is_core_dca and ((finite_num(mfi) and mfi >= 85) or (finite_num(rsi) and rsi >= 75) or (finite_num(pct_b) and pct_b >= 1.02)):
        add_check("과열", "주의", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 코어 ETF라 추격매수 대신 {c.get('core_dca_label', '속도 조절 적립')}으로 제한합니다.")
    elif (finite_num(mfi) and mfi >= 85) or (finite_num(rsi) and rsi >= 75) or (finite_num(pct_b) and pct_b >= 1.02):
        add_check("과열", "차단", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 추격매수 부담이 큽니다.")
    elif (finite_num(mfi) and mfi >= 80) or (finite_num(rsi) and rsi >= 70) or (finite_num(pct_b) and pct_b >= 0.95):
        add_check("과열", "주의", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 눌림 대기가 더 유리할 수 있습니다.")
    else:
        add_check("과열", "통과", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 극단 과열은 아닙니다.")

    if target_w > 0 and curr_w >= target_w:
        add_check("비중", "차단", f"현재 {curr_w:.2f}% / 목표 {target_w:.2f}%. 목표비중을 이미 채웠습니다.")
    elif target_w > 0 and weight_gap > 0:
        add_check("비중", "통과", f"현재 {curr_w:.2f}% / 목표 {target_w:.2f}%. 남은 여유비중 {weight_gap:.2f}%p입니다.")
    else:
        add_check("비중", "주의", "목표비중이 없거나 부족 매수액 계산이 약합니다. 먼저 목표비중을 정하는 편이 좋습니다.")

    if finite_num(macro_risk) and macro_risk >= 4.5:
        add_check("매크로", "차단", f"매크로 리스크 {macro_risk:.1f}. 시장 환경상 대피/관망 우선입니다.")
    elif finite_num(macro_risk) and macro_risk >= 2.5:
        add_check("매크로", "주의", f"매크로 리스크 {macro_risk:.1f}. 분할 접근이 적합합니다.")
    else:
        add_check("매크로", "통과", "-" if not finite_num(macro_risk) else f"매크로 리스크 {macro_risk:.1f}. 큰 차단 신호는 아닙니다.")

    if not has_pos:
        if trend == "🚀정배열(상승)" and rs_label == "🚀강함":
            add_check("보유상태", "통과", "신규 진입. 추세/RS가 양호해 정찰 비중으로 시작 가능합니다.")
        else:
            add_check("보유상태", "주의", "신규 진입. 첫 진입은 정찰 비중으로 시작하는 편이 안전합니다.")
    elif finite_num(price_vs_avg) and price_vs_avg < -0.07:
        add_check("보유상태", "주의", f"평단 대비 {price_vs_avg * 100:.1f}%. 추가매수보다 손상 원인 확인이 먼저입니다.")
    elif finite_num(price_vs_avg):
        add_check("보유상태", "통과", f"평단 대비 {price_vs_avg * 100:.1f}%. 보유 관리 범위 안에서 판단 가능합니다.")
    else:
        add_check("보유상태", "통과", "보유 정보 기준의 특이 위험은 크지 않습니다.")

    status_counts = pd.Series([row["상태"] for row in rows]).value_counts().to_dict()
    block_count = int(status_counts.get("차단", 0))
    caution_count = int(status_counts.get("주의", 0))
    pass_count = int(status_counts.get("통과", 0))

    if block_count >= 2:
        final_label, final_color, action = "매수 금지", "#dc2626", "차단 항목이 2개 이상입니다. 신규/추매보다 원인 점검과 비중 관리가 우선입니다."
    elif block_count == 1:
        final_label, final_color, action = "대기", "#d97706", "차단 항목이 남아 있습니다. 해당 항목이 해소될 때까지 정찰 이상은 보류합니다."
    elif caution_count >= 3:
        final_label, final_color, action = "소액 분할", "#d97706", "주의 항목이 많습니다. 매수한다면 소액 정찰 또는 분할 접근이 적합합니다."
    elif pass_count >= 6 and caution_count <= 2:
        final_label, final_color, action = "분할 가능", "#16a34a", "대부분의 점검을 통과했습니다. 목표비중 안에서 분할 접근을 검토할 수 있습니다."
    else:
        final_label, final_color, action = "조건부 관망", "#64748b", "강한 결론은 아닙니다. 신호, 실적 뉴스, 밸류 중 하나가 더 확인되면 좋습니다."

    return rows, {
        "final_label": final_label,
        "final_color": final_color,
        "action": action,
        "pass_count": pass_count,
        "caution_count": caution_count,
        "block_count": block_count,
    }


def render_pre_buy_final_check_panel(name, ticker, is_etf, c, fin_score, has_pos, my_price):
    st.markdown("### ✅ 매수 전 최종 체크")
    rows, summary = build_pre_buy_final_checks(name, ticker, is_etf, c, fin_score, has_pos, my_price)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("최종 판정", summary["final_label"])
    k2.metric("통과", f"{summary['pass_count']}개")
    k3.metric("주의", f"{summary['caution_count']}개")
    k4.metric("차단", f"{summary['block_count']}개")

    st.markdown(
        f"<div class='info-panel' style='border-left: 5px solid {summary['final_color']};'>"
        f"<b>{escape_html_value(name)} 최종 액션</b><br>"
        f"<span class='highlight' style='font-size:1.08em;'>{summary['final_label']}</span><br>"
        f"{escape_html_value(summary['action'])}<br>"
        f"<span style='color:#cbd5e1;'>투자 권유가 아니라, 현재 앱 지표를 한 번에 묶은 의사결정 보조 체크입니다.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    show_df = pd.DataFrame(rows)
    if not show_df.empty:
        show_df["상태"] = show_df["상태"].apply(lambda x: f"{x}")
    st.dataframe(show_df, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────
# [삽입 위치] render_pre_buy_final_check_panel 함수
# 정의 바로 아래 (~5825라인 이후)에 이 함수를 추가
# ─────────────────────────────────────────────────

def detect_fin_trend_direction(fin_meta: dict) -> dict:
    """재무가 좋아지고 있는지 나빠지고 있는지 방향성을 감지합니다."""
    notes, metrics, _ = get_fin_meta_parts(fin_meta)
    derived = metrics.get("derived", {}) if isinstance(metrics, dict) else {}

    rev_growth = clean_float(derived.get("rev_growth"), np.nan)
    prev_rev_growth = clean_float(derived.get("prev_rev_growth"), np.nan)
    q_rev_growth = clean_float(derived.get("q_rev_growth"), np.nan)
    q_op_growth = clean_float(derived.get("q_op_growth"), np.nan)
    net_growth = clean_float(derived.get("net_growth"), np.nan)
    ocf_growth = clean_float(derived.get("ocf_growth"), np.nan)

    score = 0
    signals = []

    # 연간 성장 가속/둔화
    if finite_num(rev_growth) and finite_num(prev_rev_growth):
        delta = rev_growth - prev_rev_growth
        if delta >= 5:
            signals.append(f"✅ 매출 성장 가속 ({prev_rev_growth:.1f}%→{rev_growth:.1f}%)")
            score += 2
        elif delta <= -15 and rev_growth < 5:
            signals.append(f"🚨 매출 성장 급둔화 ({prev_rev_growth:.1f}%→{rev_growth:.1f}%)")
            score -= 3
        elif delta <= -8:
            signals.append(f"⚠️ 매출 성장 둔화 ({prev_rev_growth:.1f}%→{rev_growth:.1f}%)")
            score -= 1

    # 분기 최신 모멘텀 (가장 최신 신호)
    if finite_num(q_rev_growth):
        if q_rev_growth >= 10:
            signals.append(f"✅ 최근 분기 매출 강세 (+{q_rev_growth:.1f}%)")
            score += 2
        elif q_rev_growth <= -15:
            signals.append(f"🚨 최근 분기 매출 급감 ({q_rev_growth:.1f}%)")
            score -= 3
        elif q_rev_growth <= -5:
            signals.append(f"⚠️ 최근 분기 매출 위축 ({q_rev_growth:.1f}%)")
            score -= 1

    if finite_num(q_op_growth):
        if q_op_growth >= 15:
            signals.append(f"✅ 최근 분기 영업이익 강세 (+{q_op_growth:.1f}%)")
            score += 1
        elif q_op_growth <= -20:
            signals.append(f"🚨 최근 분기 영업이익 급감 ({q_op_growth:.1f}%)")
            score -= 2

    # 이익의 질 (순이익 + OCF 동반 방향)
    if finite_num(net_growth) and finite_num(ocf_growth):
        if net_growth < 0 and ocf_growth < 0:
            signals.append("🚨 순이익·OCF 동반 악화: 펀더멘털 훼손")
            score -= 3
        elif net_growth > 10 and ocf_growth > 0:
            signals.append("✅ 순이익·OCF 동반 성장: 이익의 질 양호")
            score += 2

    # 방향성 레이블 결정
    if score >= 4:
        label, color = "📈 강한 개선", "#16a34a"
    elif score >= 2:
        label, color = "↗️ 개선 중", "#22c55e"
    elif score >= 0:
        label, color = "➡️ 유지", "#64748b"
    elif score >= -2:
        label, color = "↘️ 둔화", "#d97706"
    else:
        label, color = "📉 훼손 진행", "#dc2626"

    return {
        "score": score,
        "label": label,
        "color": color,
        "signals": signals,
        "is_improving": score >= 2,
        "is_deteriorating": score <= -2,
        "has_data": len(signals) > 0,
    }


def render_hold_or_cut_panel(name, ticker, is_etf, fin_score, fin_meta,
                              c, my_price, has_pos):
    """
    보유 지속 vs 손절 종합 판단 패널.
    보유 중일 때만 표시. 재무 방향성 + 기술 + 손익 종합.
    """
    if not has_pos:
        return

    cur_p = clean_float(c.get("cur_p"), 0.0)
    dd = clean_float(c.get("dd"), 0.0)
    trend = str(c.get("trend", ""))
    rs_label = str(c.get("rs_label", ""))
    price_vs_avg = (cur_p / my_price - 1) if my_price > 0 and cur_p > 0 else 0.0

    st.markdown("### 🏛️ 보유 지속 vs 손절 종합 판단")
    st.caption("재무 방향성(좋아지고 있나 나빠지고 있나) + 기술 구조 + 내 손익을 종합합니다.")

    # ── 점수 계산 ──────────────────────────────
    total_score = 0
    hold_reasons = []
    cut_reasons = []
    fin_trend = {}

    # 재무 방향성 (개별주만)
    if not is_etf:
        fin_trend = detect_fin_trend_direction(fin_meta)
        total_score += fin_trend["score"]
        for sig in fin_trend.get("signals", []):
            if "✅" in sig:
                hold_reasons.append(sig)
            else:
                cut_reasons.append(sig)

        # 재무점수 스냅샷
        if fin_score >= 4:
            total_score += 2
            hold_reasons.append("재무점수 4점: 완성형 우량주")
        elif fin_score <= 1:
            total_score -= 4
            cut_reasons.append("재무점수 1점: 구조적 문제")
        elif fin_score == 2:
            total_score -= 1
            cut_reasons.append("재무점수 2점: 불안정")
    else:
        total_score += 1
        hold_reasons.append("ETF: 개별기업 부도 리스크 없음")

    # 기술 구조
    if "정배열" in trend:
        total_score += 2
        hold_reasons.append("MA 정배열: 중기 추세 유효")
    elif "역배열" in trend:
        total_score -= 2
        cut_reasons.append("MA 역배열: 추세 훼손 상태")

    if rs_label == "🚀강함":
        total_score += 2
        hold_reasons.append("RS 강함: 시장/섹터 대비 자금 유입 중")
    elif rs_label == "🐢약함":
        total_score -= 2
        cut_reasons.append("RS 약함: 돈이 다른 종목/섹터로 이동 중")

    # MDD
    if dd <= -0.30:
        total_score -= 3
        cut_reasons.append(f"고점대비 {dd*100:.1f}%: 구조적 손상 수준")
    elif dd <= -0.20:
        total_score -= 1
        cut_reasons.append(f"고점대비 {dd*100:.1f}%: 추세 훼손 주의")
    elif dd > -0.10:
        total_score += 1
        hold_reasons.append("고점 근처 유지: 추세 건전")

    # 내 손익
    if price_vs_avg <= -0.20:
        total_score -= 2
        cut_reasons.append(f"평단 대비 {price_vs_avg*100:.1f}%: 손실 규모 점검")
    elif price_vs_avg <= -0.10:
        total_score -= 1
        cut_reasons.append(f"평단 대비 {price_vs_avg*100:.1f}%: 원인 확인 필요")
    elif price_vs_avg > 0.20:
        total_score += 1
        hold_reasons.append(f"평단 대비 +{price_vs_avg*100:.1f}%: 안전마진 확보")

    # 매크로
    macro_risk = clean_float(st.session_state.get("_app_final_macro_risk", 0), 0.0)
    if macro_risk >= 4.5:
        total_score -= 2
        cut_reasons.append("퍼펙트스톰: 전체 리스크 상승")
    elif macro_risk >= 2.5:
        total_score -= 1
        cut_reasons.append(f"매크로 리스크 {macro_risk:.1f}: 보수적 접근")

    # ── 하드 손절 조건 ──────────────────────────
    hard_cut = (
        (not is_etf and fin_score <= 1) or
        (price_vs_avg <= -0.25 and dd <= -0.25 and "역배열" in trend)
    )

    # ── 최종 판정 ──────────────────────────────
    if hard_cut:
        decision, color = "❌ 손절 강력 검토", "#7f1d1d"
        action = "재무 훼손 + 기술 손상 동시 발생. 손실이 더 커지기 전에 포지션 정리를 검토하세요."
    elif total_score >= 6:
        decision, color = "💎 장기보유 적합", "#16a34a"
        action = "재무 방향성·추세·RS 모두 살아있습니다. 목표비중까지 보유 유지, 추가 확대도 검토 가능."
    elif total_score >= 3:
        decision, color = "✅ 조건부 보유", "#22c55e"
        action = "대부분 건전합니다. 다음 실적 발표에서 방향성 재확인 후 추매 여부 결정."
    elif total_score >= 0:
        decision, color = "⚠️ 모니터링 강화", "#d97706"
        action = "긍·부정 혼재. 추매 보류, 다음 트리거(실적/추세 회복)까지 대기."
    elif total_score >= -3:
        decision, color = "📉 비중 축소 검토", "#f97316"
        action = "부정 신호 우세. 일부 익절 또는 비중을 줄이고 현금화 고려."
    else:
        decision, color = "🚨 손절 검토", "#dc2626"
        action = "여러 훼손 신호 동시 발생. 손절선을 명확히 설정하고 지키세요."

    # ── UI 렌더링 ───────────────────────────────
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("종합 판정", decision.split(" ", 1)[-1])
    h2.metric("종합 점수", f"{total_score:+d}점")
    h3.metric("평단 대비", f"{price_vs_avg*100:.1f}%" if finite_num(price_vs_avg) else "-")
    fin_dir_label = fin_trend.get("label", "ETF") if not is_etf else "ETF"
    h4.metric("재무 방향", fin_dir_label)

    st.markdown(
        f"<div class='info-panel' style='border-left:6px solid {color};'>"
        f"<b>{escape_html_value(name)} 보유 판단</b><br>"
        f"<span class='highlight' style='color:{color};font-size:1.15em;'>"
        f"{escape_html_value(decision)}</span><br><br>"
        f"{escape_html_value(action)}"
        f"</div>",
        unsafe_allow_html=True,
    )

    rc1, rc2 = st.columns(2)
    with rc1:
        st.markdown("**✅ 보유 근거**")
        if hold_reasons:
            for r in hold_reasons:
                st.markdown(f"- {r}")
        else:
            st.caption("보유 근거 부족")
    with rc2:
        st.markdown("**🚨 우려 근거**")
        if cut_reasons:
            for r in cut_reasons:
                st.markdown(f"- {r}")
        else:
            st.caption("주요 우려 없음")

    # 재무 방향성 상세 (개별주만)
    if not is_etf and fin_trend.get("has_data"):
        with st.expander("재무 방향성 상세"):
            st.markdown(
                f"**방향**: {fin_trend['label']} (방향점수 {fin_trend['score']:+d})<br>"
                f"분기가 가장 최신 신호입니다. 연간은 추세, 분기는 현재 모멘텀으로 봅니다.",
                unsafe_allow_html=True,
            )
            for sig in fin_trend["signals"]:
                st.markdown(f"- {sig}")
            st.caption("재무 방향성은 DART/FMP 자동 계산 데이터 기반입니다. 재무점수를 먼저 돌린 뒤 봐야 정확합니다.")


def prefetch_price_data_parallel(tickers: list, period: str = "1y", max_workers: int = 8):
    """
    [속도 개선] 여러 티커의 가격 데이터를 ThreadPoolExecutor로 병렬 선제 로딩합니다.
    load_price_df가 @st.cache_data를 사용하므로 병렬 호출 후 캐시에 저장됩니다.
    이후 순차 호출 시 캐시 히트로 즉시 반환됩니다.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not tickers:
        return
    def _fetch(tkr):
        try:
            return load_price_df(tkr, period)
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, tkr): tkr for tkr in tickers}
        for future in as_completed(futures):
            future.result()  # 예외가 있으면 무시하고 계속


def _compute_summary_item(item, mode, snap_macro_penalty, snap_final_macro_risk, snap_total_eval,
                          snap_cash_available, snap_reserve_available):
    """워커 함수: CPU 계산만 담당. session_state 쓰기 없음 (스레드 안전).
    매크로 전역값은 호출 시점에 스냅샷으로 전달받아 스레드 안전성을 보장합니다."""
    tkr = sanitize_ticker_value(item.get("ticker", ""))
    name = sanitize_asset_name(item.get("name", ""), tkr)
    if not tkr:
        return None
    is_etf = is_fin_score_exempt_asset(tkr, item.get("is_etf", False), item.get("asset_class", ""), name)
    a_class = infer_asset_class_for_ticker(tkr, item.get("asset_class", "")) if is_etf else item.get("asset_class", "")

    df = load_price_df(tkr, "1y")
    if df.empty:
        return None
    # tail(300)으로 슬라이싱해 TA 계산량 제한 (1y ≈ 250행이라 실질적 안전망)
    df = build_indicators(df.tail(300))

    final_fin_score, _ = load_fin_score_meta_fast(tkr, is_etf)
    f_score = int(final_fin_score)

    my_p = get_my_price(name, tkr)
    has_p = has_position(name, tkr)

    c = calc_scores_and_decision(
        name=name, ticker=tkr, is_etf=is_etf, asset_class=a_class, df=df,
        my_price=my_p, has_pos=has_p, fin_score=f_score, is_free=False, app_mode=mode,
        _macro_penalty=snap_macro_penalty,
        _final_macro_risk=snap_final_macro_risk,
        _total_eval=snap_total_eval,
        _cash_available=snap_cash_available,
        _reserve_available=snap_reserve_available,
    )

    # 벤치마크 단일 진입점 — prefetch_benchmark_info_parallel 이 선제 캐싱함
    bm = get_auto_benchmark_info(tkr, name, a_class, is_etf)

    row = {
        "시장": get_dashboard_market_label(tkr), "유형": get_dashboard_type_label(is_etf),
        "전광판그룹": get_dashboard_group_label(tkr, is_etf),
        "종목명": name, "티커": tkr, "현재가": format_currency(c["cur_p"], tkr), "MDD": f"{c['dd']*100:.1f}%",
        "재무점수": "해당없음" if is_etf else f"{f_score}/4", "📌후보등급": c["grade"], "RS": c["rs_label"],
        "시장벤치": get_benchmark_display_name(bm["market_bench"]),
        "기초자산": bm["underlying_asset"] if bm["underlying_bench"] else "-",
        "기초벤치": get_benchmark_display_name(bm["underlying_bench"]) if bm["underlying_bench"] else "-",
        "섹터벤치": get_benchmark_display_name(bm["sector_bench"]) if bm["sector_bench"] else "-",
        "섹터RS": bm["sector_rs_label"] if bm["sector_bench"] else "-",
        "RSI": round(c["rsi"], 1), "MFI": round(c["mfi"], 1), "볼린저 %B": round(c["pct_b"], 2),
        "🔥기술적 타점": c["dec"],
        "핵심근거": c.get("decision_reasons", ("",))[0] if c.get("decision_reasons") else "",
        "판정코드": c.get("decision_code", ""),
        "판정분류": c.get("decision_group") or classify_decision_signal(c["dec"]),
        "Adj점수": round(c["adj"], 1)
    }
    return {"tkr": tkr, "f_score": f_score, "row": row}


def get_all_summary(fin_score_map_items, mode, watchlist_items):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # [속도 개선] 전광판 종목 전체를 병렬로 선제 로딩 (이후 load_price_df는 캐시 히트)
    all_tickers = [
        sanitize_ticker_value(item.get("ticker", ""))
        for item in watchlist_items
        if sanitize_ticker_value(item.get("ticker", ""))
    ]
    prefetch_price_data_parallel(all_tickers, "1y")
    # [속도 개선] 벤치마크 정보 병렬 선제 캐싱 (이후 get_auto_benchmark_info 는 캐시 히트)
    prefetch_benchmark_info_parallel(watchlist_items)

    # 매크로 전역값을 워커 진입 전에 스냅샷 — 스레드 간 일관성 보장
    snap_mp  = macro_penalty
    snap_fmr = final_macro_risk
    snap_te  = total_eval
    snap_cash_available = get_cash_available_for_dca(mode)
    snap_reserve_available = get_reserve_available_for_crash_buy(mode)

    # 원래 순서를 보존하기 위해 인덱스를 키로 사용
    results_map: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(
                _compute_summary_item,
                item, mode, snap_mp, snap_fmr, snap_te,
                snap_cash_available, snap_reserve_available,
            ): i
            for i, item in enumerate(watchlist_items)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                result = future.result()
            except Exception:
                result = None
            if result is not None:
                results_map[idx] = result

    # 메인 스레드에서 session_state 쓰기 + 원래 순서대로 rows 구성
    rows = []
    for i in range(len(watchlist_items)):
        r = results_map.get(i)
        if r is None:
            continue
        st.session_state.fin_score_map[normalize_ticker(r["tkr"])] = r["f_score"]
        rows.append(r["row"])

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
        {"항목": "RS 기울기", "정의": "RS의 방향성 (4주·8주 일관성)", "코드 기준": "4주·8주 RS 변화가 같은 방향이고 ±3% 초과 시 상승/하락 판정, ADJ 점수 ±1 반영", "해석": "RS가 강해지는 중인지 약해지는 중인지 추세를 본다"},
        {"항목": "RSI", "정의": "가격 모멘텀 과열/침체", "코드 기준": "30 이하 과매도, 70 이상 과열권", "해석": "낮으면 반등 후보, 높으면 추격주의"},
        {"항목": "MFI", "정의": "거래량 포함 자금흐름", "코드 기준": "30 미만 +2점, 80 초과 -1점, 85 이상 하드차단", "해석": "자금 유입/과열 판단"},
        {"항목": "볼린저 %B", "정의": "볼린저밴드 내 현재 위치", "코드 기준": "0.95 이상 상단권, 1.02 초과 과열확장", "해석": "상단권은 눌림 대기 우선"},
        {"항목": "MACD", "정의": "추세 전환/유지", "코드 기준": "골든크로스 +2, 상승유지 +1, 데드크로스 -2", "해석": "매수 타점의 핵심 모멘텀"},
        {"항목": "SQZ", "정의": "변동성 압축/해제", "코드 기준": "해제직후 + MACD 양호 시 +1", "해석": "압축 후 방향성 분출 체크"},
        {"항목": "MDD", "정의": "52주 고점 대비 낙폭", "코드 기준": "-20%는 추매금지/원인점검, -30% 이하는 위기 단계", "해석": "내 손익률이 아니라 최근 고점 대비 구조 훼손 정도를 보는 보조 지표"},
        {"항목": "ADJ점수", "정의": "매크로 패널티 반영 기술점수", "코드 기준": "메인점수 + RS점수 + MFI점수 + RS기울기점수 - 매크로패널티", "해석": "높을수록 현재 타점 우호"},
        {"항목": "R/R 비율", "정의": "2ATR 손절 기준 리스크/리워드", "코드 기준": "손절 = 현재가 - 2ATR (추가 인사이트와 동일). 목표 = 내부 피벗 고점 → 외부 피벗 고점 → 4ATR 투영 순서로 사용. R/R = (목표-현재가)/(현재가-손절)", "해석": "1.5 이상이면 타점 우호. 신고가 돌파 구간은 4ATR 목표로 투영됨"},
        {"항목": "섹터 머니플로우", "정의": "해당 종목의 섹터 ETF 자금흐름 상태", "코드 기준": "3개월·6개월 수익률 + 가속도로 신규유입/주도유지/둔화경고/소외지속/관찰 판정", "해석": "섹터 자체에 돈이 들어오고 있는지 확인"},
    ],
    "점수 계산": [
        {"항목": "RS 점수", "계산": "강함 +2, 보통 +1, 약함 0", "용도": "기술점수/ADJ점수"},
        {"항목": "MFI 점수", "계산": "30 미만 +2, 80 초과 -1, 그 외 0", "용도": "자금흐름 반영"},
        {"항목": "추세 점수", "계산": "MA20 > MA50 > MA120 정배열이면 +2", "용도": "중기 추세 반영"},
        {"항목": "MACD 점수", "계산": "골든크로스 +2, 상승유지 +1, 데드크로스 -2", "용도": "모멘텀 반영"},
        {"항목": "SQZ 점수", "계산": "SQZ 해제직후 + MACD 양호하면 +1", "용도": "변동성 발산 초입 반영"},
        {"항목": "거래량 방향 점수", "계산": "양봉 + 거래량 1.2배↑ → +1 / 음봉(-2%↓) + 거래량 1.5배↑ → -1", "용도": "main_score 반영"},
        {"항목": "기술점수", "계산": "RS + MFI + 추세 + MACD + SQZ", "용도": "후보등급 계산 (거래량 방향은 main_score 경유)"},
        {"항목": "ADJ점수", "계산": "main_score + RS점수 + MFI점수 + RS기울기점수(±1) - 매크로패널티", "용도": "타점 판정 기준 점수"},
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
        {"타점": "코어 ETF 적립속도", "조건": "bucket core ETF + 목표비중 부족", "의미": "과열 25%, 중립 50%, 눌림 100%, 급락 150~200%로 투입 속도 조절"},
        {"타점": "신규ETF 단기관측", "조건": "ETF 가격 데이터 60거래일 미만", "의미": "장기추세는 보류하되 RSI/MFI/볼린저/평단/비중으로 과열·눌림·소액추매 판단"},
        {"타점": "상승확인: 2차 정찰 추매", "조건": "평단 대비 0~5% 상승 + 비중부족 + 추세 양호", "의미": "상승 확인 후 제한적 추매"},
        {"타점": "S급 눌림목", "조건": "정배열 + RS 강함 + RSI 45~58 + %B 0.45~0.8", "의미": "가장 선호하는 눌림 매수 구간"},
        {"타점": "낙폭과대", "조건": "RSI 30 이하 또는 하락추세 속 ADJ 높음", "의미": "반등 가능성은 있으나 분할 접근"},
        {"타점": "평단 -3~-7%", "조건": "평단 이하, 추세 훼손 크지 않음, MFI 80 미만", "의미": "소액 분할매수 후보"},
        {"타점": "평단 -7~-15%", "조건": "손실 확대 + 재무 3점 이상 + 매크로 위험 낮음", "의미": "조건부 분할매수"},
        {"타점": "평단 -15%↓", "조건": "평단 대비 큰 손실 또는 추세위험", "의미": "원인 점검 우선"},
        {"타점": "고점대비 -20%", "조건": "52주 고점 대비 -20% 이하", "의미": "보유 중이면 추매 금지와 원인 점검, 미보유면 신규진입 보류"},
        {"타점": "구조훼손: 신규진입 보류", "조건": "개별주 MDD -15% 이하, MA50 이탈, 급락+거래량, MA20 하단 이탈 중 하나", "의미": "점수가 좋아도 차트 구조 확인 전 신규매수 보류"},
        {"타점": "신규진입: 대장주 포착", "조건": "ADJ 4.5 이상 + RS 강함 + 정배열 + MA20 근처 이상 + MDD -15% 이내 + 급락 아님", "의미": "구조가 살아있는 신규 후보"},
        {"타점": "52주 신고가 돌파", "조건": "전일 52주 고점 이하 → 당일 돌파 + 거래량 1.3배↑ + RS 강함 + 양봉", "의미": "모멘텀 진입 검토 (MFI<80, %B<0.95 조건 추가)"},
        {"타점": "예외승인 차단 (RS하락중)", "조건": "예외승인 MA5/FVG 조건 충족이어도 RS 기울기가 하락 중이면 예외 불허", "의미": "RS 모멘텀이 꺾이는 구간의 추격 진입 방지"},
        {"타점": "익절 타이밍", "조건": "보유 중 + 코어ETF 아님 + MFI≥80 + %B>0.9 + 수익률 20%↑", "의미": "분할 매도 검토 신호 (판단은 투자자 몫)"},
        {"타점": "케이스3 추가 완화", "조건": "S급+RS강함+정배열+비중여유 조건에서 RS 기울기 상승 중이면 매크로 임계값 3.5→4.0으로 완화", "의미": "상승 모멘텀이 살아있는 구간에서 약간 더 관대하게 허용"},
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

다만 `bucket=core`인 장기 ETF는 목표비중이 부족하면 MFI/RSI 과열 구간에서도 완전 대기가 아니라 적립 속도를 줄여 표시합니다. 평상시 재원은 예수금이고, -20% 이상 급락 구간부터는 reserve/CD 같은 파킹자산도 별도 투입 후보로 봅니다.
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

아닙니다. DART/FMP/SEC 데이터 기반 자동 계산이므로 누락이나 업종 특성이 있을 수 있습니다. 필요하면 수동 점수로 보정할 수 있습니다.

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


GUIDE_IMAGE_FILES = [
    ("오늘 점검", "docs/tab_guides/00_today_queue.svg", "매수 후보, 주의/차단, 확인 필요 종목을 먼저 정리합니다."),
    ("자산 현황", "docs/tab_guides/01_asset_overview.svg", "보유종목, 예수금, 목표비중을 입력하고 전체 자산을 확인합니다."),
    ("포트폴리오 분석", "docs/tab_guides/02_portfolio_analysis.svg", "집중도, 변동성, MDD, 상관관계로 내 포트폴리오 위험을 봅니다."),
    ("전광판", "docs/tab_guides/03_dashboard.svg", "관심종목을 한국/미국, ETF/개별주로 나눠 한 번에 확인합니다."),
    ("정밀관측소", "docs/tab_guides/04_precision_lab.svg", "한 종목을 깊게 열어 신호, 차트, 밸류, 최종 체크를 확인합니다."),
    ("시나리오 평가", "docs/tab_guides/05_scenario_check.svg", "시장 하락, 환율, 레버리지 충격을 가정해 손실 규모를 미리 봅니다."),
    ("단기 흐름 점검", "docs/tab_guides/06_short_trend.svg", "보유/관심종목의 2~4주 흐름을 빠르게 스캔합니다."),
    ("신호 검증", "docs/tab_guides/07_signal_backtest.svg", "과거 신호의 5/20/60일 성과와 승률을 확인합니다."),
    ("돈흐름 레이더", "docs/tab_guides/08_money_flow.svg", "ETF 가격 모멘텀으로 강한 섹터와 새로 힘붙는 테마를 찾습니다."),
    ("배당 ETF", "docs/tab_guides/09_kr_etf_lab.svg", "국내 ETF의 분배, 비용, 구성, 테마를 비교합니다."),
    ("피드백/Q&A", "docs/tab_guides/11_feedback.svg", "사용 중 헷갈리는 점과 개선 요청을 앱 안에서 남깁니다."),
    ("데이터 점검", "docs/tab_guides/12_data_quality.svg", "ETF 분류, 목표비중, 저장 데이터 오류를 점검합니다."),
    ("속도 점검", "docs/tab_guides/13_speed_check.svg", "무거운 계산과 새로고침 기준을 확인합니다."),
    ("판정 매뉴얼", "docs/tab_guides/14_manual.svg", "하드차단, S급 눌림목, ETF 적립 등 판정 기준을 찾아봅니다."),
    ("사용 가이드", "docs/tab_guides/15_user_guide.svg", "처음 쓰는 사람에게 앱 사용 순서와 주의사항을 안내합니다."),
]


def render_guide_image_gallery():
    st.markdown("### 탭별 이미지 빠른 가이드")
    st.caption("지인에게 설명할 때 이 이미지만 공유해도 기본 사용법을 이해할 수 있게 만든 요약 카드입니다.")

    for idx, (title, image_path, desc) in enumerate(GUIDE_IMAGE_FILES):
        with st.expander(f"{idx + 1}. {title}", expanded=(idx == 0)):
            st.caption(desc)
            if os.path.exists(image_path):
                st.image(image_path, use_container_width=True)
                with open(image_path, "rb") as image_file:
                    st.download_button(
                        "이미지 다운로드",
                        data=image_file.read(),
                        file_name=os.path.basename(image_path),
                        mime="image/svg+xml",
                        key=f"download_guide_image_{idx}",
                        use_container_width=True,
                    )
            else:
                st.warning(f"가이드 이미지 파일을 찾지 못했습니다: {image_path}")


def render_user_guide_tab():
    st.subheader("사용 가이드")
    st.caption("처음 쓰는 사용자를 위한 안내입니다. 앱은 투자 권유가 아니라 포트폴리오 점검과 의사결정 보조 도구입니다.")

    start_tab, flow_tab, signal_tab, image_tab, faq_tab = st.tabs(["처음 시작", "화면 사용법", "문구 해석", "이미지 가이드", "공유/주의"])

    with start_tab:
        st.markdown("""
### 처음 5분 세팅

1. **로그인**
   허용된 계정으로 로그인합니다. 계정별로 자산, 관심종목, 피드백이 분리 저장됩니다.

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
### 각 화면은 이렇게 씁니다

**✅ 오늘 점검**
관심/보유 종목을 자동으로 훑어서 매수 후보, 주의/차단, 확인 필요 종목을 먼저 보여주는 시작 화면입니다.

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

**📘 판정 매뉴얼**
하드차단, S급 눌림목, ETF 적립 가능 같은 문구가 왜 나오는지 확인하는 곳입니다.
        """)

        with st.expander("추천 사용 순서", expanded=True):
            st.markdown("""
1. 자산 현황에서 총자산, 손익, 대기자금, 보유자산 표를 확인
2. 필요할 때만 입력/수정 영역을 열어 보유종목, 예수금, 배당, 월별 로그 수정
3. 포트폴리오 분석에서 집중도, 변동성, 대기자금 비중 확인
4. 오늘 점검에서 매수 후보와 주의/차단 종목을 먼저 확인
5. 정밀관측소에서 매수/추매 고민이 있는 종목만 깊게 확인
6. 전광판에서 관심종목을 한국/미국, ETF/개별주로 나눠 확인
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

    with image_tab:
        render_guide_image_gallery()

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

> 사용 전 왼쪽 사이드바의 `📖 사용 가이드` 화면을 먼저 읽어주세요.
> 오늘 점검은 우선순위 확인, 전광판은 전체 후보 확인, 정밀 관측소는 한 종목 상세 확인용입니다.
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


def calc_portfolio_leverage_summary(asset_df):
    columns = ["자산명", "티커", "전체비중", "운용비중", "충격배수", "레버리지환산노출", "추가노출"]
    summary = {
        "leveraged_principal_pct": 0.0,
        "effective_exposure_pct": 0.0,
        "extra_exposure_pct": 0.0,
        "active_effective_exposure_pct": 0.0,
        "max_multiplier": 1.0,
    }

    if asset_df is None or asset_df.empty:
        return summary, pd.DataFrame(columns=columns)

    rows = []
    for _, row in asset_df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        name = str(row.get("자산명", "")).strip()
        multiplier = abs(clean_float(infer_scenario_shock_multiplier({
            "티커": ticker,
            "자산명": name,
        }), 1.0))

        if multiplier <= 1.05:
            continue

        total_weight = clean_float(row.get("전체비중"), 0.0)
        active_weight = clean_float(row.get("운용비중"), 0.0)
        effective_exposure = total_weight * multiplier
        active_effective_exposure = active_weight * multiplier
        extra_exposure = max(effective_exposure - total_weight, 0.0)

        rows.append({
            "자산명": name if name else ticker,
            "티커": ticker,
            "전체비중": total_weight,
            "운용비중": active_weight,
            "충격배수": multiplier,
            "레버리지환산노출": effective_exposure,
            "추가노출": extra_exposure,
            "_active_effective_exposure": active_effective_exposure,
        })

    if not rows:
        return summary, pd.DataFrame(columns=columns)

    leverage_df = pd.DataFrame(rows)
    summary["leveraged_principal_pct"] = float(leverage_df["전체비중"].sum())
    summary["effective_exposure_pct"] = float(leverage_df["레버리지환산노출"].sum())
    summary["extra_exposure_pct"] = float(leverage_df["추가노출"].sum())
    summary["active_effective_exposure_pct"] = float(leverage_df["_active_effective_exposure"].sum())
    summary["max_multiplier"] = float(leverage_df["충격배수"].max())

    return summary, leverage_df.drop(columns=["_active_effective_exposure"], errors="ignore")[columns]


def build_correlation_pair_summary(corr_df):
    if corr_df is None or corr_df.empty or len(corr_df.columns) < 2:
        return pd.DataFrame(columns=["자산 A", "자산 B", "상관계수", "구분", "해석"])

    rows = []
    cols = list(corr_df.columns)
    for i, left in enumerate(cols):
        for j in range(i + 1, len(cols)):
            right = cols[j]
            if str(left).strip() == str(right).strip():
                continue
            value = clean_float(corr_df.iloc[i, j], np.nan)
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


def normalize_datetime_index_no_tz(index):
    idx = pd.to_datetime(index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)
    return idx


def get_portfolio_analysis_start_date(monthly_logs_df):
    perf_df = prepare_monthly_performance_df(monthly_logs_df)
    if perf_df is None or perf_df.empty or "month_end" not in perf_df.columns:
        return None

    month_end = pd.to_datetime(perf_df["month_end"], errors="coerce").dropna()
    if month_end.empty:
        return None

    first_month = pd.Timestamp(month_end.min())
    if getattr(first_month, "tzinfo", None) is not None:
        first_month = first_month.tz_convert(None)
    return first_month.replace(day=1).normalize()


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


def build_portfolio_analysis_report(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight, period="1y", analysis_start_date=None):
    if analysis_start_date is not None:
        analysis_start_date = pd.Timestamp(analysis_start_date).normalize()

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

        target_weight = clean_float(row.get("목표비중"), 0.0)
        row_info = {
            "자산명": name,
            "티커": ticker,
            "원화환산": value_krw,
            "전체비중": weight_total,
            "목표비중": target_weight,
            "비중차이": target_weight - weight_total,
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
            close.index = normalize_datetime_index_no_tz(close.index)
            if analysis_start_date is not None:
                close = close[close.index >= analysis_start_date]
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
        "자산명", "티커", "원화환산", "전체비중", "목표비중", "비중차이", "운용비중", "기간수익률", "연환산변동성", "MDD", "데이터"
    ])

    if not asset_df.empty:
        asset_df = asset_df.sort_values("전체비중", ascending=False).reset_index(drop=True)
    asset_label_map = build_asset_label_map(asset_df)
    leverage_summary, leverage_df = calc_portfolio_leverage_summary(asset_df)

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
    portfolio_observation_count = 0

    if price_series:
        prices = pd.concat(price_series.values(), axis=1).sort_index().ffill(limit=3)
        returns_df = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="all").fillna(0.0)

        usable_cols = [col for col in returns_df.columns if col in set(asset_df["티커"])]
        if usable_cols:
            # 전체비중(현금 포함 총자산 기준) 사용 — 운용비중으로 재정규화하면 현금의 리스크 완충 효과가 사라짐
            weight_map = {
                str(row["티커"]): clean_float(row["전체비중"], 0.0) / 100
                for _, row in asset_df.iterrows()
                if str(row["티커"]) in usable_cols
            }
            weight_sum = sum(weight_map.values())
            if weight_sum > 0:
                weights = pd.Series({ticker: weight for ticker, weight in weight_map.items()})
                aligned_returns = returns_df[weights.index].copy()
                portfolio_returns = aligned_returns.mul(weights, axis=1).sum(axis=1)
                if not portfolio_returns.empty:
                    portfolio_observation_count = int(len(portfolio_returns))
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
                    _rf_rate = 0.035  # 무위험이율 3.5% (한국 기준금리 근방)
                    sharpe_ratio = ratio_or_nan(annual_return_decimal - _rf_rate, portfolio_vol_decimal)
                    sortino_ratio = ratio_or_nan(annual_return_decimal - _rf_rate, downside_vol_decimal)
                    calmar_ratio = ratio_or_nan(annual_return_decimal, abs(portfolio_mdd_decimal))
                    daily_var_95, daily_cvar_95 = calc_var_cvar(portfolio_returns, 0.95)
                    monthly_var_95 = daily_var_95 * np.sqrt(21) if np.isfinite(daily_var_95) else np.nan
                    # 전체자산 기준으로 VaR/CVaR 원화 손실액 산출 (현금 비중이 이미 수익률에 반영됨)
                    active_var_95_krw = total_asset * abs(daily_var_95) / 100 if np.isfinite(daily_var_95) else np.nan
                    active_cvar_95_krw = total_asset * abs(daily_cvar_95) / 100 if np.isfinite(daily_cvar_95) else np.nan
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
    leverage_component = min(max(float(leverage_summary.get("extra_exposure_pct", 0.0)), 0.0) * 0.9, 20)
    reserve_gap = max(float(reserve_target_weight) - float(reserve_summary.get("waiting_pct", 0.0)), 0.0)
    reserve_component = min(reserve_gap * 1.5, 15)
    risk_index = min(vol_component + mdd_component + concentration_component + corr_component + leverage_component + reserve_component, 100)
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
    if leverage_summary.get("leveraged_principal_pct", 0.0) > 0:
        leverage_level = "주의" if leverage_summary.get("extra_exposure_pct", 0.0) >= 8 or leverage_summary.get("effective_exposure_pct", 0.0) >= 15 else "참고"
        add_portfolio_risk_note(
            notes,
            leverage_level,
            "레버리지",
            (
                f"레버리지 ETF 원금비중은 {leverage_summary.get('leveraged_principal_pct', 0.0):.1f}%이고 "
                f"2배/3배 환산 노출은 {leverage_summary.get('effective_exposure_pct', 0.0):.1f}%입니다."
            ),
            "전체 위험도가 균형이어도 레버리지 환산 노출과 손실 속도는 별도로 확인하세요.",
        )
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
        "leverage_summary": leverage_summary,
        "leverage_df": leverage_df,
        "leverage_component": leverage_component,
        "usable_asset_count": len(price_series),
        "portfolio_observation_count": portfolio_observation_count,
        "analysis_start_date": analysis_start_date,
    }

    return metrics, asset_df, notes_df, corr_df, portfolio_curve, risk_contrib_df


def format_metric_pct(value, digits=1):
    return "-" if not np.isfinite(clean_float(value, np.nan)) else f"{clean_float(value):.{digits}f}%"


def format_metric_ratio(value, digits=2):
    return "-" if not np.isfinite(clean_float(value, np.nan)) else f"{clean_float(value):.{digits}f}"


def format_metric_money(value):
    return "-" if not np.isfinite(clean_float(value, np.nan)) else f"{clean_float(value):,.0f}원"


def render_portfolio_sample_warning(metrics):
    observation_count = int(clean_float(metrics.get("portfolio_observation_count", 0), 0))
    if observation_count <= 0:
        return

    if observation_count < 63:
        st.warning(
            f"가격 표본이 {observation_count}거래일뿐이라 연환산 수익률, Sharpe, Sortino가 크게 왜곡될 수 있습니다. "
            "최근 흐름 참고용으로만 보세요."
        )
    elif observation_count < 126:
        st.info(
            f"가격 표본이 {observation_count}거래일입니다. 연환산 지표는 아직 짧은 기간을 1년으로 늘린 값이라 "
            "실제 장기 성과처럼 해석하면 안 됩니다."
        )


def render_leverage_exposure_panel(metrics):
    summary = metrics.get("leverage_summary", {}) or {}
    leverage_df = metrics.get("leverage_df", pd.DataFrame())
    principal = clean_float(summary.get("leveraged_principal_pct"), 0.0)

    if principal <= 0 or leverage_df is None or leverage_df.empty:
        return

    effective = clean_float(summary.get("effective_exposure_pct"), 0.0)
    extra = clean_float(summary.get("extra_exposure_pct"), 0.0)
    active_effective = clean_float(summary.get("active_effective_exposure_pct"), 0.0)
    reserve_summary = metrics.get("reserve_summary", {}) or {}
    waiting_pct = clean_float(reserve_summary.get("waiting_pct"), 0.0)

    st.markdown("#### 레버리지 환산 노출")
    l1, l2, l3, l4 = st.columns(4)
    l1.metric("레버리지 원금비중", f"{principal:.1f}%")
    l2.metric("2배/3배 환산노출", f"{effective:.1f}%")
    l3.metric("추가 위험노출", f"+{extra:.1f}%p")
    l4.metric("운용자산 환산노출", f"{active_effective:.1f}%")

    if extra >= 8 or effective >= 15:
        st.warning(
            "전체 위험도가 `균형`으로 보여도 레버리지 ETF는 하락장에서 손실 속도가 더 빠릅니다. "
            f"대기자금 {waiting_pct:.1f}%가 전체 위험도를 낮춰 보이게 할 수 있으니, 위 환산노출을 별도로 기준 삼으세요."
        )
    else:
        st.info(
            "레버리지 ETF가 포함되어 있습니다. 현재 환산노출은 과도한 편은 아니지만, "
            "매수 판단은 전체 위험도보다 레버리지 환산노출과 손실 허용폭을 같이 봐야 합니다."
        )

    show_df = leverage_df.copy()
    for col in ["전체비중", "운용비중", "레버리지환산노출", "추가노출"]:
        if col in show_df.columns:
            show_df[col] = show_df[col].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.1f}%")
    if "충격배수" in show_df.columns:
        show_df["충격배수"] = show_df["충격배수"].apply(lambda v: f"{clean_float(v):.1f}x")
    st.dataframe(show_df, use_container_width=True, hide_index=True)


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


def render_portfolio_analysis_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight, monthly_logs_df=None):
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

    analysis_start_date = get_portfolio_analysis_start_date(monthly_logs_df)
    if analysis_start_date is not None:
        st.caption(f"월별 로그 시작월({analysis_start_date.strftime('%Y-%m')}) 이후 가격 흐름만 분석합니다.")

    metrics, asset_df, notes_df, corr_df, portfolio_curve, risk_contrib_df = build_portfolio_analysis_report(
        holdings_table,
        krw_cash,
        usd_cash,
        usdkrw,
        reserve_target_weight,
        period=period,
        analysis_start_date=analysis_start_date,
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

    render_leverage_exposure_panel(metrics)

    st.markdown("#### Risk Metrics")
    st.caption(
        "**연환산 수익률**: 분석 기간 포트폴리오 가격 흐름을 연 단위로 환산한 참고값.  "
        "**Sharpe**: (연환산수익률 − 무위험이율 3.5%) ÷ 연환산변동성. 1 이상이면 변동성 대비 수익이 양호한 편.  "
        "**Sortino**: 하락 변동성만 분모로 사용. Sharpe보다 하락 리스크에 예민.  "
        "**Calmar**: 연환산수익률 ÷ |MDD|. 낙폭 대비 수익 효율.  "
        "**VaR/CVaR**: 과거 일간 수익률 기반 참고 손실 추정치입니다."
    )
    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric("연환산 수익률", format_metric_pct(metrics.get("portfolio_annual_return")))
    r2.metric("Sharpe", format_metric_ratio(metrics.get("sharpe_ratio")))
    r3.metric("Sortino", format_metric_ratio(metrics.get("sortino_ratio")))
    r4.metric("Calmar", format_metric_ratio(metrics.get("calmar_ratio")))
    r5.metric("95% VaR(1일)", format_metric_pct(metrics.get("daily_var_95")))
    _sharpe_v = clean_float(metrics.get("sharpe_ratio"), np.nan)
    _sortino_v = clean_float(metrics.get("sortino_ratio"), np.nan)
    _obs = metrics.get("portfolio_observation_count", 0)
    if (np.isfinite(_sharpe_v) and abs(_sharpe_v) > 4) or (np.isfinite(_sortino_v) and abs(_sortino_v) > 6) or _obs < 60:
        st.warning(
            f"⚠️ Sharpe/Sortino가 평소보다 높습니다 "
            f"(Sharpe {format_metric_ratio(_sharpe_v)}, Sortino {format_metric_ratio(_sortino_v)}, 관측일 {_obs}일). "
            "단기 상승장 구간이거나 관측 기간이 짧으면 연환산 수익률이 과장되어 비율이 크게 나올 수 있습니다. "
            "참고값으로만 사용하세요."
        )

    tail_cols = st.columns(4)
    tail_cols[0].metric("95% CVaR(1일)", format_metric_pct(metrics.get("daily_cvar_95")))
    tail_cols[1].metric("95% VaR(월간 추정)", format_metric_pct(metrics.get("monthly_var_95")))
    tail_cols[2].metric("VaR 손실액", format_metric_money(metrics.get("active_var_95_krw")))
    tail_cols[3].metric("CVaR 손실액", format_metric_money(metrics.get("active_cvar_95_krw")))
    st.caption("Risk Metrics는 총자산(현금 포함) 기준의 가중 포트폴리오 수익률을 사용합니다. VaR/CVaR 손실액도 총자산 기준이며, 현금 비중이 높을수록 손실 추정액이 낮아집니다. 미래 손실 한도가 아닌 참고값입니다.")
    render_portfolio_sample_warning(metrics)

    render_long_term_goal_simulator(metrics)

    if notes_df.empty:
        st.success("현재 기준으로 크게 눈에 띄는 포트폴리오 위험 신호는 없습니다.")
    else:
        st.markdown("#### 위험/분산 체크")
        st.dataframe(notes_df, use_container_width=True, hide_index=True)

    if asset_df.empty:
        st.info("분석할 운용대상 보유자산이 없습니다.")
        return

    # ── 목표비중 vs 현재비중 비교 ──────────────────────────────────────────
    if "목표비중" in asset_df.columns and asset_df["목표비중"].apply(lambda v: clean_float(v, 0.0)).sum() > 0:
        st.markdown("#### 목표비중 vs 현재비중")
        st.caption(
            "**현재비중**: 총자산(현금 포함) 대비 해당 자산의 비중. "
            "**목표비중**: 보유종목관리에서 설정한 목표 배분. "
            "**비중차이**: 목표 − 현재(양수=미달, 음수=초과)."
        )
        wt_df = asset_df[["자산명", "티커", "전체비중", "목표비중", "비중차이"]].copy()
        wt_df = wt_df[wt_df["목표비중"].apply(lambda v: clean_float(v, 0.0)) > 0].copy()
        if not wt_df.empty:
            wt_df = wt_df.sort_values("비중차이", ascending=False).reset_index(drop=True)
            wt_show = wt_df.copy()
            for col in ["전체비중", "목표비중", "비중차이"]:
                wt_show[col] = wt_show[col].apply(
                    lambda v: f"{clean_float(v):+.1f}%" if col == "비중차이" else f"{clean_float(v):.1f}%"
                )
            wt_show = wt_show.rename(columns={"전체비중": "현재비중"})
            st.dataframe(wt_show, use_container_width=True, hide_index=True)

            # 비중 불일치 경고
            big_under = wt_df[wt_df["비중차이"].apply(lambda v: clean_float(v, 0.0)) >= 5]
            big_over  = wt_df[wt_df["비중차이"].apply(lambda v: clean_float(v, 0.0)) <= -5]
            if not big_under.empty:
                names = ", ".join(big_under["자산명"].fillna(big_under["티커"]).tolist())
                st.warning(f"목표보다 5%p 이상 미달인 자산: {names} — 매수 또는 현금 투입을 검토하세요.")
            if not big_over.empty:
                names = ", ".join(big_over["자산명"].fillna(big_over["티커"]).tolist())
                st.info(f"목표보다 5%p 이상 초과인 자산: {names} — 비중 조정 또는 트리밍을 고려하세요.")

            # 현금 비중 현황
            total_asset_val = metrics.get("total_asset", 0.0)
            active_val = metrics.get("active_value", 0.0)
            cash_pct = (total_asset_val - active_val) / total_asset_val * 100 if total_asset_val > 0 else 0.0
            target_stock_pct = wt_df["목표비중"].apply(lambda v: clean_float(v, 0.0)).sum()
            implied_cash_target = max(100.0 - target_stock_pct, 0.0)
            c1, c2, c3 = st.columns(3)
            c1.metric("현재 현금비중", f"{cash_pct:.1f}%")
            c2.metric("목표 주식비중 합계", f"{target_stock_pct:.1f}%")
            c3.metric("암묵적 현금 목표", f"{implied_cash_target:.1f}%")

    # ── 자산별 위험 지표 ───────────────────────────────────────────────────
    show_df = asset_df.copy()
    # "기간수익률"은 자산 가격의 분석기간 등락률(내 매입가 기준 수익률 아님)임을 명확히 하기 위해 컬럼명 변경
    if "기간수익률" in show_df.columns:
        show_df = show_df.rename(columns={"기간수익률": "자산가격등락률"})
    for col in ["전체비중", "목표비중", "비중차이", "운용비중", "자산가격등락률", "연환산변동성", "MDD"]:
        if col in show_df.columns:
            if col == "비중차이":
                show_df[col] = show_df[col].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):+.1f}%")
            else:
                show_df[col] = show_df[col].apply(lambda v: "" if not np.isfinite(clean_float(v, np.nan)) else f"{clean_float(v):.1f}%")
    if "원화환산" in show_df.columns:
        show_df["원화환산"] = show_df["원화환산"].apply(lambda v: f"{clean_float(v):,.0f}원")

    st.markdown("#### 자산별 위험 지표")
    st.caption(
        "**자산가격등락률**: 분석 기간 시작~종료 사이 해당 자산의 가격 변동률입니다. "
        "내가 매입한 가격 기준 수익률과 다를 수 있습니다(매입 시점 차이). "
        "**연환산변동성**: 일간 수익률의 표준편차를 연 단위로 환산. **MDD**: 분석 기간 내 최고점 대비 최대 낙폭."
    )
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
        st.markdown("#### 누적 흐름")
        actual_perf_df = prepare_monthly_performance_df(monthly_logs_df)
        has_actual_curve = actual_perf_df is not None and not actual_perf_df.empty and "month_end" in actual_perf_df.columns
        has_price_curve = portfolio_curve is not None and not portfolio_curve.empty
        if has_actual_curve or has_price_curve:
            fig_curve = go.Figure()

            if has_actual_curve:
                actual_curve_df = actual_perf_df.copy()
                actual_curve_df["month_end"] = pd.to_datetime(actual_curve_df["month_end"], errors="coerce")
                actual_curve_df = actual_curve_df.dropna(subset=["month_end"])
                fig_curve.add_trace(go.Scatter(
                    x=actual_curve_df["month_end"],
                    y=actual_curve_df["cum_return_pct"],
                    mode="lines+markers",
                    name="실제 누적수익률",
                    line=dict(color="#22c55e", width=3),
                    marker=dict(size=7),
                    hovertemplate="%{x|%Y-%m}<br>실제 누적수익률: %{y:.2f}%<extra></extra>",
                ))

            if has_price_curve:
                fig_curve.add_trace(go.Scatter(
                    x=portfolio_curve.index,
                    y=(portfolio_curve - 1) * 100,
                    mode="lines",
                    name="가격기반 보유자산 흐름",
                    line=dict(color="#38bdf8", width=2, dash="dot"),
                    opacity=0.8,
                    hovertemplate="%{x|%Y-%m-%d}<br>가격기반 흐름: %{y:.2f}%<extra></extra>",
                ))

            fig_curve.update_layout(
                template="plotly_dark",
                height=360,
                yaxis_title="누적수익률(%)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_curve, use_container_width=True)
            st.caption("초록선은 월별 로그/총자산 기준 실제 누적수익률입니다. 파란 점선은 현재 보유 운용자산을 현재 비중으로 보유했다고 가정한 가격 기반 참고선이라 실제 수익률과 다를 수 있습니다.")
        else:
            st.info("누적 흐름을 계산할 월별 기록 또는 가격 데이터가 부족합니다.")

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
    st.caption(
        "자산 간 일간 수익률이 얼마나 같이 움직이는지를 나타냅니다. "
        "빨강(+1)에 가까울수록 함께 오르고 내리며, 파랑(−1)에 가까울수록 반대로 움직입니다. "
        "분산 효과는 상관계수가 낮을수록 더 큽니다."
    )
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

    # ── 종합 평가 ──────────────────────────────────────────────────────────
    st.markdown("#### 📋 종합 포트폴리오 평가")
    _eval_lines: list[str] = []
    _rg = metrics.get("risk_grade", "-")
    _ri = metrics.get("risk_index", 0.0)
    _pvol = metrics.get("portfolio_vol", np.nan)
    _pmdd = metrics.get("portfolio_mdd", np.nan)
    _pann = metrics.get("portfolio_annual_return", np.nan)
    _sharpe = metrics.get("sharpe_ratio", np.nan)
    _sortino = metrics.get("sortino_ratio", np.nan)
    _calmar = metrics.get("calmar_ratio", np.nan)
    _top1 = metrics.get("top1_weight", 0.0)
    _top3 = metrics.get("top3_weight", 0.0)
    _avg_corr = metrics.get("avg_corr", np.nan)
    _reserve_pct = metrics.get("reserve_summary", {}).get("waiting_pct", 0.0)
    _reserve_target = float(reserve_target_weight)

    # 위험도 평가
    _eval_lines.append(f"**위험도 {_rg}** ({_ri:.0f}/100): " + (
        "전반적으로 안정적인 구성입니다." if _ri < 35
        else "일부 위험 요인이 있으며 점검이 필요합니다." if _ri < 60
        else "위험 노출이 높습니다. 포지션 점검을 권장합니다."
    ))

    # 변동성/MDD
    if np.isfinite(_pvol):
        _vol_comment = "낮음(보수적)" if _pvol < 12 else "보통" if _pvol < 22 else "높음(공격적)"
        _eval_lines.append(f"**변동성**: 연환산 {_pvol:.1f}% — {_vol_comment}.")
    if np.isfinite(_pmdd):
        _mdd_comment = "양호" if _pmdd > -15 else "주의 필요" if _pmdd > -30 else "큰 하락 경험 구간"
        _eval_lines.append(f"**최대낙폭(MDD)**: {_pmdd:.1f}% — {_mdd_comment}.")

    # 수익성
    if np.isfinite(_pann):
        _ret_comment = "부진" if _pann < 5 else "양호" if _pann < 20 else "우수 (단기 과장 가능)"
        _eval_lines.append(f"**연환산 수익률**: {_pann:.1f}% — {_ret_comment}.")
    if np.isfinite(_sharpe):
        _sharpe_comment = "낮음" if _sharpe < 0.5 else "보통" if _sharpe < 1.5 else "우수 (단기 상승 과장 가능 확인 권장)"
        _eval_lines.append(f"**Sharpe**: {_sharpe:.2f} — {_sharpe_comment}.")

    # 집중도
    if _top1 >= 30:
        _eval_lines.append(f"**집중도 주의**: 1위 자산 비중이 {_top1:.1f}%입니다. 단일 종목 의존도가 높습니다.")
    elif _top3 >= 60:
        _eval_lines.append(f"**집중도 보통**: 상위 3개 비중이 {_top3:.1f}%입니다.")
    else:
        _eval_lines.append(f"**집중도 양호**: 상위 3개 비중이 {_top3:.1f}%로 적절히 분산돼 있습니다.")

    # 상관관계
    if np.isfinite(_avg_corr):
        _corr_comment = "분산 효과 높음" if _avg_corr < 0.4 else "분산 효과 보통" if _avg_corr < 0.7 else "높은 동조화 — 분산 효과 제한"
        _eval_lines.append(f"**자산간 상관**: 평균 {_avg_corr:.2f} — {_corr_comment}.")

    # 대기자금
    _reserve_gap = _reserve_target - _reserve_pct
    if _reserve_gap > 3:
        _eval_lines.append(f"**대기자금 부족**: 현재 {_reserve_pct:.1f}% / 목표 {_reserve_target:.1f}%. 하락 시 투입 여력이 부족합니다.")
    else:
        _eval_lines.append(f"**대기자금 충분**: 현재 {_reserve_pct:.1f}% / 목표 {_reserve_target:.1f}%.")

    _eval_html = "<br>".join(f"• {line}" for line in _eval_lines)
    st.markdown(
        f"<div class='info-panel'>{_eval_html}</div>",
        unsafe_allow_html=True,
    )
    st.caption("종합 평가는 분석 기간 내 가격 데이터 기반 자동 생성 참고 의견입니다. 매입 시점·미실현 수익률과 다를 수 있습니다.")


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


def get_short_trend(score):
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

    label, _ = get_short_trend(score)
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

    # [속도 개선] 분석 전 전체 티커 병렬 선제 로딩
    all_tickers = [str(r["ticker"]) for _, r in universe_df.iterrows() if r.get("ticker")]
    prefetch_price_data_parallel(all_tickers, period)

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

            label, color = get_short_trend(clean_int(selected_row.get("점수"), 0))
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
                if IS_PUBLIC_DEMO:
                    st.info("체험모드에서는 ETF 데이터 파일을 저장하지 않습니다.")
                else:
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
    if IS_PUBLIC_DEMO:
        return pd.DataFrame(columns=FIN_SCORE_COLUMNS), None

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
            account_type = str(row.get("account_type", "일반")).strip()
            unique_key = f"{key} ({account_type})" if key else ""
            
            if ticker:
                ticker_keys.append(unique_key)
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
            account_type = str(row.get("account_type", "일반")).strip()

            unique_key = f"{key} ({account_type})" if key else ""

            if key:
                ticker_keys.append(unique_key)
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


def render_today_market_flow_panel():
    st.markdown("#### 시장 돈흐름 요약")
    st.caption("글로벌 자금 흐름 레이더와 테마 종목의 상위 흐름만 오늘 점검용으로 짧게 보여줍니다.")

    if not should_run_heavy_analysis(
        "today_market_flow_lazy",
        "ETF/섹터와 테마 종목 가격을 여러 개 조회하므로 필요할 때만 계산합니다.",
        run_label="돈흐름 요약 계산/새로고침",
    ):
        return

    try:
        with st.spinner("ETF/테마 돈흐름 요약 계산 중..."):
            snapshot = get_today_market_flow_snapshot()
    except Exception as exc:
        st.warning(f"돈흐름 요약을 계산하지 못했습니다: {exc}")
        return

    flow_df = snapshot.get("flow_df", pd.DataFrame())
    if flow_df is None or flow_df.empty:
        st.info("ETF/섹터 돈흐름 데이터가 아직 없습니다.")
        return

    us_top5 = snapshot.get("us_top5", pd.DataFrame())
    kr_top5 = snapshot.get("kr_top5", pd.DataFrame())
    global_top = snapshot.get("global_top", pd.DataFrame())
    local_top = snapshot.get("local_top", pd.DataFrame())
    us_swing_top3 = snapshot.get("us_swing_top3", pd.DataFrame())
    kr_swing_top3 = snapshot.get("kr_swing_top3", pd.DataFrame())
    global_swing_top = snapshot.get("global_swing_top", pd.DataFrame())
    sector_rotation_df = snapshot.get("sector_rotation_df", pd.DataFrame())
    theme_top5 = snapshot.get("theme_top5", pd.DataFrame())
    subtheme_top = snapshot.get("subtheme_top", pd.DataFrame())
    theme_flow_df = snapshot.get("theme_flow_df", pd.DataFrame())
    theme_rotation_df = snapshot.get("theme_rotation_df", pd.DataFrame())

    metric_cols = st.columns(4)
    if not kr_top5.empty:
        r = kr_top5.iloc[0]
        metric_cols[0].metric("한국 섹터 1위", f"{r['섹터']} ({r['Ticker']})", f"{fmt_flow_score(r['돈흐름점수'])} pts")
    else:
        metric_cols[0].metric("한국 섹터 1위", "-", "-")

    if not us_top5.empty:
        r = us_top5.iloc[0]
        metric_cols[1].metric("미국 섹터 1위", f"{r['섹터']} ({r['Ticker']})", f"{fmt_flow_score(r['돈흐름점수'])} pts")
    else:
        metric_cols[1].metric("미국 섹터 1위", "-", "-")

    if not global_top.empty:
        r = global_top.iloc[0]
        metric_cols[2].metric("글로벌 ETF 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    elif not local_top.empty:
        r = local_top.iloc[0]
        metric_cols[2].metric("대표 ETF 1위", f"{r['섹터']} ({r['Ticker']})", fmt_flow_pct(r["3개월수익률"]))
    else:
        metric_cols[2].metric("글로벌/대표 ETF 1위", "-", "-")

    if not theme_top5.empty:
        r = theme_top5.iloc[0]
        metric_cols[3].metric("테마 종목 1위", str(r["테마"]), f"{fmt_flow_score(r['테마돈흐름점수'])} pts")
    else:
        metric_cols[3].metric("테마 종목 1위", "-", "-")

    st.caption("돈흐름점수(1위)는 3~6개월 누적 모멘텀 기준 — 최근 조정은 반영이 느립니다. 진입 시점은 아래 **로테이션 맵 → ✅ 진입검토** 를 함께 확인하세요.")

    with st.expander("전광판으로 보내기", expanded=False):
        send_groups = ["한국 섹터", "미국 섹터", "글로벌", "국내상장 대표 ETF", "월배당 ETF"]
        available_groups = [g for g in send_groups if g in set(flow_df["구분"].astype(str))]
        if not available_groups:
            st.info("전광판으로 보낼 ETF 후보가 없습니다.")
        else:
            group_col, select_col, action_col = st.columns([1.15, 2.4, 1.0])
            with group_col:
                send_group = st.selectbox("그룹", available_groups, key="today_flow_send_group")
            send_df = (
                flow_df[flow_df["구분"].astype(str).eq(send_group)]
                .dropna(subset=["돈흐름점수"])
                .sort_values("돈흐름점수", ascending=False)
                .copy()
            )
            if send_df.empty:
                st.info("선택한 그룹에 계산 가능한 ETF가 없습니다.")
            else:
                option_rows = send_df.reset_index(drop=True)
                option_labels = [
                    f"{idx + 1}. {row['섹터']} | {row['Ticker']} | {fmt_flow_score(row['돈흐름점수'])} pts"
                    for idx, row in option_rows.iterrows()
                ]
                with select_col:
                    selected_label = st.selectbox("보낼 섹터/ETF", option_labels, key="today_flow_send_target")
                selected_idx = option_labels.index(selected_label)
                selected_row = option_rows.iloc[selected_idx]
                already_added = is_in_watchlist(selected_row["Ticker"])
                with action_col:
                    st.write("")
                    st.write("")
                    if already_added:
                        st.caption("이미 등록됨")
                    elif st.button("전광판 추가", key="today_flow_send_add", use_container_width=True):
                        ok, message = add_money_flow_row_to_watchlist(selected_row)
                        if ok:
                            st.success(message)
                            st.rerun()
                        else:
                            st.info(message)
                st.caption("추가하면 관심목록에 저장되어 전광판에서 가격/판정 신호를 볼 수 있습니다.")

    # ── 공통: 로테이션 차트 그리기 ───────────────────────────────────
    def _render_rotation_chart_and_table(grp_df: pd.DataFrame, label_col: str, ret_col_1m: str = "1개월수익률"):
        """RS(3M)/RS모멘텀 기준 사분면 차트 + 진입검토 후보 테이블 렌더링."""
        _QUAD_COLOR  = {"주도": "#22c55e", "약화": "#f59e0b", "개선": "#60a5fa", "소외": "#ef4444"}
        _QUAD_SYMBOL = {"주도": "circle", "약화": "diamond", "개선": "square", "소외": "x"}

        fig = go.Figure()
        for quad, qdf in grp_df.groupby("사분면"):
            color  = _QUAD_COLOR.get(quad, "#94a3b8")
            symbol = _QUAD_SYMBOL.get(quad, "circle")
            entry_mask = qdf["진입검토"] == "✅ 진입검토"
            for is_entry, subdf in [(True, qdf[entry_mask]), (False, qdf[~entry_mask])]:
                if subdf.empty:
                    continue
                hover_r1m = subdf[ret_col_1m] if ret_col_1m in subdf.columns else pd.Series([np.nan] * len(subdf))
                fig.add_trace(go.Scatter(
                    x=subdf["RS(3M)"] * 100,
                    y=subdf["RS모멘텀"] * 100,
                    mode="markers+text",
                    name=f"{quad}{'★' if is_entry else ''}",
                    text=subdf[label_col],
                    textposition="top center",
                    textfont=dict(size=10, color=color),
                    marker=dict(
                        size=14 if is_entry else 9,
                        color=color,
                        symbol=symbol,
                        line=dict(width=2.5 if is_entry else 0.5,
                                  color="#ffffff" if is_entry else color),
                        opacity=0.95 if is_entry else 0.65,
                    ),
                    customdata=np.column_stack([
                        subdf.get("Ticker", pd.Series([""] * len(subdf))).values,
                        subdf["RS(3M)"].values,
                        hover_r1m.values if hasattr(hover_r1m, "values") else [np.nan] * len(subdf),
                        subdf["상태"].values,
                        subdf["진입검토"].values,
                    ]),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        "RS(3M): %{x:.1f}%p  RS모멘텀: %{y:.2f}%p<br>"
                        "1M수익률: %{customdata[2]:.1%}  상태: %{customdata[3]}<br>"
                        "<b>%{customdata[4]}</b><extra></extra>"
                    ),
                    showlegend=True,
                ))

        x_max = max(grp_df["RS(3M)"].abs().max() * 115, 5)
        y_max = max(grp_df["RS모멘텀"].abs().max() * 115, 5)
        for qname, (x0, x1, y0, y1) in [
            ("주도", (0, x_max,  0, y_max)),
            ("약화", (0, x_max, -y_max, 0)),
            ("개선", (-x_max, 0, 0, y_max)),
            ("소외", (-x_max, 0, -y_max, 0)),
        ]:
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
                          fillcolor=_QUAD_COLOR[qname], opacity=0.06, line_width=0, layer="below")
            fig.add_annotation(x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                               text=f"<b>{qname}</b>", showarrow=False,
                               font=dict(size=13, color=_QUAD_COLOR[qname]), opacity=0.35)

        fig.add_hline(y=0, line_dash="dot", line_color="#475569", line_width=1)
        fig.add_vline(x=0, line_dash="dot", line_color="#475569", line_width=1)
        fig.update_layout(
            height=430,
            margin=dict(l=10, r=10, t=20, b=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.6)",
            xaxis=dict(title="RS(3M) %p", gridcolor="#1e293b", zerolinecolor="#475569"),
            yaxis=dict(title="RS모멘텀 %p", gridcolor="#1e293b", zerolinecolor="#475569"),
            legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
            font=dict(color="#94a3b8"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # 진입검토 후보 테이블
        entry_df = grp_df[grp_df["진입검토"] == "✅ 진입검토"].copy()
        if entry_df.empty:
            st.info("현재 진입검토 조건(개선/주도 + 단기 상승 확인 + 비과열)을 모두 충족한 항목이 없습니다.")
        else:
            st.markdown("**✅ 진입검토 후보**")
            show_cols = [c for c in ["섹터", "테마", "Ticker", "사분면", "RS(3M)", "RS모멘텀",
                                      "3M수익률", "1개월수익률", "상태"] if c in entry_df.columns]
            entry_show = entry_df[show_cols].copy()
            for col in ["RS(3M)", "RS모멘텀", "3M수익률", "1개월수익률"]:
                if col in entry_show.columns:
                    entry_show[col] = entry_show[col].apply(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "-")
            st.dataframe(entry_show, use_container_width=True, hide_index=True)

        with st.expander("전체 상세 보기", expanded=False):
            all_cols = [c for c in ["섹터", "테마", "Ticker", "사분면", "진입검토",
                                     "RS(3M)", "RS모멘텀", "3M수익률", "1개월수익률", "상태"] if c in grp_df.columns]
            all_show = grp_df[all_cols].copy()
            for col in ["RS(3M)", "RS모멘텀", "3M수익률", "1개월수익률"]:
                if col in all_show.columns:
                    all_show[col] = all_show[col].apply(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "-")
            st.dataframe(all_show.sort_values(["사분면", "RS(3M)"], ascending=[True, False]),
                         use_container_width=True, hide_index=True)

    # ── 테마 rotation df에 RS vs KOSPI200 + 사분면 + 진입검토 추가 ─
    _bench_kr = flow_df[flow_df["Ticker"].astype(str) == "069500.KS"] if not flow_df.empty else pd.DataFrame()
    _b_3m_kr    = float(_bench_kr.iloc[0]["3개월수익률"]) if not _bench_kr.empty and finite_num(_bench_kr.iloc[0].get("3개월수익률")) else 0.0
    _b_accel_kr = float(_bench_kr.iloc[0]["가속도"])      if not _bench_kr.empty and finite_num(_bench_kr.iloc[0].get("가속도"))      else 0.0

    theme_rot_map_df = pd.DataFrame()
    if not theme_rotation_df.empty:
        _td = theme_rotation_df.copy()
        _td["RS(3M)"]   = _td["3개월수익률"].apply(lambda v: float(v) - _b_3m_kr    if finite_num(v) else np.nan)
        _td["RS모멘텀"] = _td["가속도"].apply(      lambda v: float(v) - _b_accel_kr if finite_num(v) else np.nan)
        _td = _td.dropna(subset=["RS(3M)", "RS모멘텀"])

        def _quad(r):
            rs, mom = r["RS(3M)"], r["RS모멘텀"]
            if rs >= 0 and mom >= 0: return "주도"
            if rs >= 0 and mom <  0: return "약화"
            if rs <  0 and mom >= 0: return "개선"
            return "소외"

        def _entry(r):
            quad  = r.get("사분면", "")
            r1m   = r.get("1개월수익률", np.nan)
            accel = r.get("가속도", np.nan)
            state = str(r.get("상태", ""))
            ok = (
                quad in {"개선", "주도"}
                and finite_num(r1m) and float(r1m) >= 0.01
                and finite_num(accel) and float(accel) >= 0.0
                and state != "과열경보"
            )
            return "✅ 진입검토" if ok else "🔸 관망"

        _td["사분면"]  = _td.apply(_quad, axis=1)
        _td["진입검토"] = _td.apply(_entry, axis=1)
        theme_rot_map_df = _td

    # ── 통합 로테이션 맵 (한국섹터 / 미국섹터 / 테마종목) ──────────────
    st.markdown("#### 🔄 로테이션 맵 — 섹터 · 테마 진입검토")
    st.caption(
        "**X축 RS(3M)**: 벤치마크 대비 초과 수익률 &nbsp;|&nbsp; "
        "**Y축 RS모멘텀**: 가속도 초과분 &nbsp;|&nbsp; "
        "✅ 진입검토 = 개선/주도 + 단기 상승 확인(1M≥+1%) + 가속도≥0 + 비과열 &nbsp;|&nbsp; "
        "ETF 벤치마크: KODEX200 / VOO &nbsp;|&nbsp; 테마 벤치마크: KODEX200"
    )

    _rot_tab_labels = ["한국섹터", "미국섹터", "테마종목"]
    _rot_tabs = st.tabs(_rot_tab_labels)

    with _rot_tabs[0]:
        _kr_rot = sector_rotation_df[sector_rotation_df["구분"] == "한국 섹터"].copy() if not sector_rotation_df.empty else pd.DataFrame()
        if _kr_rot.empty:
            st.info("한국 섹터 데이터가 부족합니다.")
        else:
            _render_rotation_chart_and_table(_kr_rot, label_col="섹터", ret_col_1m="3M수익률")

    with _rot_tabs[1]:
        _us_rot = sector_rotation_df[sector_rotation_df["구분"] == "미국 섹터"].copy() if not sector_rotation_df.empty else pd.DataFrame()
        if _us_rot.empty:
            st.info("미국 섹터 데이터가 부족합니다.")
        else:
            _render_rotation_chart_and_table(_us_rot, label_col="섹터", ret_col_1m="3M수익률")

    with _rot_tabs[2]:
        if theme_rot_map_df.empty:
            st.info("테마 데이터가 부족합니다 (IMAGE_THEME_FLOW 비활성).")
        else:
            _render_rotation_chart_and_table(theme_rot_map_df, label_col="테마", ret_col_1m="1개월수익률")

    # ── 투자자별 순매수 TOP 10 은 render_investor_top10_section() 에서 별도 렌더링 ──


def render_investor_top10_section():
    """
    투자자별 순매수 TOP 10 섹션 (전광판 추가 UI 포함).
    render_today_market_flow_panel 과 독립적으로 호출한다.

    ※ should_run_heavy_analysis 를 사용하지 않는다.
      그 함수는 ready=True 가 세션 내내 유지돼 탭 재방문 시 자동 계산되는 문제가 있기 때문.
      여기서는 버튼 클릭 시점에만 계산하고 결과를 session_state 에 보관한다.
      새 세션(앱 재시작) 또는 날짜가 바뀌면 자동 초기화된다.
    """
    st.divider()
    st.markdown("#### 📊 오늘 투자자별 순매수 TOP 10")

    # ── 날짜 기반 캐시 키 (날짜 바뀌면 자동 초기화) ──────────────────────────
    _today_key = get_kst_now().strftime("%Y%m%d")
    _SS_DATA   = "investor_top10_data"
    _SS_DATE   = "investor_top10_date"
    _SS_TIME   = "investor_top10_calc_time"

    if st.session_state.get(_SS_DATE) != _today_key:
        # 날짜 바뀌면 이전 결과 삭제
        st.session_state.pop(_SS_DATA, None)
        st.session_state[_SS_DATE] = _today_key

    # ── 버튼 UI ───────────────────────────────────────────────────────────────
    _has_data = _SS_DATA in st.session_state
    _b1, _b2, _b3 = st.columns([1.4, 1.0, 3.6])
    _do_calc = _b1.button(
        "수급 TOP 10 계산/새로고침",
        key="investor_top10_calc_btn",
        use_container_width=True,
    )
    if _has_data:
        if _b2.button("결과 지우기", key="investor_top10_clear_btn", use_container_width=True):
            st.session_state.pop(_SS_DATA, None)
            st.session_state.pop(_SS_TIME, None)
            st.rerun()
        _last = st.session_state.get(_SS_TIME, "")
        if _last:
            _b3.caption(f"마지막 조회: {_last}")
    else:
        _b2.caption("대기 중")
        _b3.caption("버튼을 눌러 KRX/네이버 수급 데이터를 조회합니다.")

    # ── 계산 트리거 ───────────────────────────────────────────────────────────
    if not _do_calc and not _has_data:
        return   # 버튼 안 눌렀고 저장 데이터도 없으면 종료

    if _do_calc:
        st.session_state.pop(_SS_DATA, None)   # 재계산 강제

    if _SS_DATA not in st.session_state:
        # ── 추적 KR 종목 수집 ────────────────────────────────────────────────
        _tracked_kr: list[str] = []
        for _item in st.session_state.get("watchlist", []):
            _t = sanitize_ticker_value(_item.get("ticker", ""))
            if _t.upper().endswith((".KS", ".KQ")):
                _tracked_kr.append(_t)
        try:
            _snap = get_today_market_flow_snapshot()
            for _key in ("theme_flow_df", "flow_df"):
                _df = _snap.get(_key, pd.DataFrame())
                if not _df.empty and "Ticker" in _df.columns:
                    _tracked_kr += [
                        _t for _t in _df["Ticker"].dropna().unique()
                        if str(_t).upper().endswith((".KS", ".KQ"))
                    ]
        except Exception:
            pass
        _tracked_kr = list(dict.fromkeys(_tracked_kr))

        # ── 패널 렌더링 & 결과 저장 ──────────────────────────────────────────
        _fetched = render_investor_top10_panel(_tracked_kr)
        st.session_state[_SS_DATA] = _fetched or {}
        st.session_state[_SS_TIME] = get_kst_now().strftime("%Y-%m-%d %H:%M")

    top10_data = st.session_state.get(_SS_DATA, {})

    # ── 전광판 추가 UI ────────────────────────────────────────────────────────
    if not top10_data:
        return

    # 전 투자자 데이터에서 (종목명, Ticker) 고유 목록 수집
    _cand_map: dict[str, str] = {}   # ticker → name (순서 유지)
    for _df_inv in top10_data.values():
        if _df_inv is None or _df_inv.empty:
            continue
        if "Ticker" not in _df_inv.columns or "종목명" not in _df_inv.columns:
            continue
        for _, _row in _df_inv.iterrows():
            _tk = sanitize_ticker_value(str(_row.get("Ticker", "")))
            _nm = str(_row.get("종목명", _tk))
            if _tk and _tk not in _cand_map:
                _cand_map[_tk] = _nm

    if not _cand_map:
        return

    with st.expander("📌 TOP 10 종목 → 전광판 추가", expanded=False):
        _option_labels = [
            f"{_nm}  ({_tk})"
            for _tk, _nm in _cand_map.items()
            if not is_in_watchlist(_tk)
        ]
        _already_labels = [
            f"✅ {_nm}  ({_tk})"
            for _tk, _nm in _cand_map.items()
            if is_in_watchlist(_tk)
        ]

        if _already_labels:
            st.caption("이미 등록된 종목: " + "  ·  ".join(_already_labels))

        if not _option_labels:
            st.success("TOP 10에 표시된 종목이 전부 전광판에 등록되어 있습니다.")
            return

        _selected = st.multiselect(
            "전광판에 추가할 종목 선택 (복수 선택 가능)",
            options=_option_labels,
            key="investor_top10_wl_multiselect",
            placeholder="종목을 선택하세요...",
        )
        if _selected:
            if st.button(
                f"✚ 선택 {len(_selected)}개 전광판 추가",
                key="investor_top10_wl_add_btn",
                use_container_width=True,
            ):
                _added, _skipped = [], []
                for _lbl in _selected:
                    # 레이블에서 ticker 추출: "이름  (TICKER)"
                    _m = re.search(r"\(([^)]+)\)\s*$", _lbl)
                    if not _m:
                        continue
                    _tk = _m.group(1).strip()
                    _nm = _cand_map.get(_tk, _tk)
                    if is_in_watchlist(_tk):
                        _skipped.append(_nm)
                        continue
                    st.session_state.watchlist.append(sanitize_watchlist_item({
                        "ticker": _tk,
                        "name": _nm,
                        "is_etf": False,
                        "asset_class": "kr_stock",
                        "target_weight": 0,
                        "fin_score": 0,
                    }))
                    _added.append(_nm)
                if _added:
                    persist_watchlist()
                    st.success(f"추가 완료 ({len(_added)}개): {', '.join(_added)}")
                    st.rerun()
                if _skipped:
                    st.info(f"이미 등록됨: {', '.join(_skipped)}")


def render_today_queue_tab(mode):
    st.subheader("오늘 점검")
    render_data_basis_caption("오늘점검", include_fin=True)
    st.caption("스윙 일지 대신 관심/보유 종목을 자동으로 훑어서 매수 후보, 차단/주의, 확인 필요 종목만 모아봅니다.")

    watch_items = tuple(st.session_state.get("watchlist", []))
    if not watch_items:
        st.info("관심종목이 비어 있습니다. 정밀관측소에서 종목을 추가하면 오늘 점검에 자동으로 올라옵니다.")
        st.divider()
        render_today_market_flow_panel()
        render_investor_top10_section()
        return

    st.metric("관심/보유 점검 대상", f"{len(watch_items)}개")
    if not should_run_heavy_analysis(
        "today_queue_lazy",
        "오늘 점검은 관심/보유 종목의 가격과 벤치마크를 여러 개 조회하므로 필요할 때만 실행합니다.",
        run_label="오늘 종목 점검 계산/새로고침",
    ):
        st.divider()
        render_today_market_flow_panel()
        render_investor_top10_section()
        return

    with st.spinner("관심/보유 종목 신호를 정리하는 중입니다..."):
        summary_df = get_all_summary(tuple(sorted(st.session_state.fin_score_map.items())), mode, watch_items)

    if summary_df.empty:
        st.warning("오늘 점검에 표시할 종목이 없습니다. 가격 데이터를 불러오지 못했거나 관심종목이 비어 있을 수 있습니다.")
        st.divider()
        render_today_market_flow_panel()
        render_investor_top10_section()
        return

    if "판정분류" in summary_df.columns:
        signal_group = summary_df["판정분류"].astype(str)
    else:
        signal_group = summary_df["🔥기술적 타점"].astype(str).map(classify_decision_signal)

    code_series = summary_df.get("판정코드", pd.Series("", index=summary_df.index)).astype(str)
    label_series = summary_df.get("🔥기술적 타점", pd.Series("", index=summary_df.index)).astype(str)
    hard_block_mask = code_series.str.contains("HARD_BLOCK", na=False) | label_series.str.contains("하드차단", na=False)
    buyish_mask = signal_group.eq("buyish") & ~hard_block_mask
    caution_mask = signal_group.eq("caution") | hard_block_mask

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("점검 종목", f"{len(summary_df)}개")
    m2.metric("매수/관심 후보", f"{int(buyish_mask.sum())}개")
    m3.metric("주의/차단", f"{int(caution_mask.sum())}개")
    m4.metric("하드차단", f"{int(hard_block_mask.sum())}개")

    cash_available = clean_float(get_cash_available_for_dca(mode), 0.0)
    reserve_available = clean_float(get_reserve_available_for_crash_buy(mode), 0.0)
    if final_macro_risk >= 4.5:
        st.error("매크로 리스크가 높은 구간입니다. 신규 매수보다 현금/방어자산 유지와 비중 초과 종목 점검을 우선합니다.")
    elif hard_block_mask.any():
        st.warning("하드차단 종목이 있습니다. 비중 초과, 과열, 매크로, 재무 위험 같은 차단 사유를 먼저 확인하세요.")
    elif buyish_mask.any() and cash_available > 0:
        st.success("매수/관심 후보가 있습니다. 현금 범위 안에서 정찰 또는 분할 접근 후보로만 검토하세요.")
    elif buyish_mask.any():
        st.info("매수/관심 후보는 있지만 적립용 현금이 부족합니다. 신규 매수보다 현금 계획을 먼저 확인하세요.")
    else:
        st.info("강한 매수 후보가 많지 않습니다. 오늘은 보유 유지, 비중 점검, 관심종목 정리 쪽이 더 적합합니다.")

    cash_cols = st.columns(2)
    cash_cols[0].metric("적립용 현금", f"{cash_available:,.0f}원")
    cash_cols[1].metric("폭락장 예비자금", f"{reserve_available:,.0f}원")

    st.divider()
    render_today_market_flow_panel()
    render_investor_top10_section()
    st.divider()

    show_cols = [
        "종목명", "티커", "유형", "현재가", "📌후보등급", "🔥기술적 타점",
        "핵심근거", "Adj점수", "RS", "섹터RS", "RSI", "MFI", "볼린저 %B", "MDD",
    ]
    show_cols = [col for col in show_cols if col in summary_df.columns]

    view_mode = st.radio(
        "보기",
        ["매수/관심 후보", "주의/차단", "전체"],
        horizontal=True,
        key="today_queue_view_mode",
    )
    if view_mode == "매수/관심 후보":
        view_df = summary_df.loc[buyish_mask].copy()
        sort_ascending = False
    elif view_mode == "주의/차단":
        view_df = summary_df.loc[caution_mask].copy()
        view_df["_hard_block"] = hard_block_mask.loc[view_df.index].astype(int)
        sort_ascending = True
    else:
        view_df = summary_df.copy()
        sort_ascending = False

    if view_df.empty:
        st.info(f"{view_mode}에 해당하는 종목이 없습니다.")
        return

    if view_mode == "주의/차단" and "_hard_block" in view_df.columns:
        sort_cols = ["_hard_block"]
        ascending = [False]
        if "Adj점수" in view_df.columns:
            sort_cols.append("Adj점수")
            ascending.append(True)
        view_df = view_df.sort_values(sort_cols, ascending=ascending)
    elif "Adj점수" in view_df.columns:
        view_df = view_df.sort_values("Adj점수", ascending=sort_ascending)

    st.dataframe(view_df[show_cols], use_container_width=True, hide_index=True)

    st.caption("매수 후보는 바로 매수하라는 뜻이 아니라, 정밀관측소에서 비중·과열·현금 조건을 한 번 더 확인할 우선순위입니다.")


def render_public_demo_fast_shell(settings, holdings_df, holdings_table, dividends_df, monthly_logs_df, portfolio_summary, krw_cash, usd_cash, usdkrw, reserve_target_weight):
    st.caption("데모는 첫 화면 속도를 위해 선택한 화면만 계산합니다. 무거운 분석은 버튼을 누를 때만 실행됩니다.")
    demo_page = st.radio(
        "체험 화면",
        ["자산 현황", "오늘 점검", "전광판", "정밀관측소", "시나리오", "단기 흐름", "신호 검증", "돈흐름", "월배당 ETF", "피드백", "가이드"],
        horizontal=True,
        key="public_demo_fast_page",
    )

    if demo_page == "자산 현황":
        st.subheader("앱 내부 자산 관리")
        render_data_basis_caption("자산관리", include_fin=True)
        render_asset_overview_dashboard(holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw, reserve_target_weight)
        render_asset_quick_quality_summary(settings, holdings_df, dividends_df, monthly_logs_df)
        render_monthly_record_status(monthly_logs_df, portfolio_summary)
        return

    if demo_page == "오늘 점검":
        st.caption("데모에서는 버튼을 눌러야 오늘 점검 계산을 시작합니다.")
        if st.button("오늘 점검 계산 시작", key="public_demo_today_queue_run", use_container_width=True):
            st.session_state["public_demo_today_queue_ready"] = True
        if not st.session_state.get("public_demo_today_queue_ready", False):
            st.info("첫 접속 속도를 위해 오늘 점검 계산을 멈춰뒀습니다. 누르면 샘플 종목의 우선순위를 계산합니다.")
            return
        render_today_queue_tab("개인모드")
        return

    if demo_page == "전광판":
        st.subheader("CCTV 통합 통제실")
        st.caption("데모에서는 버튼을 눌러야 전광판 기술 계산을 시작합니다.")
        if st.button("전광판 계산 시작", key="public_demo_dashboard_run", use_container_width=True):
            st.session_state["public_demo_dashboard_ready"] = True
        if not st.session_state.get("public_demo_dashboard_ready", False):
            st.info("첫 접속 속도를 위해 전광판 계산을 멈춰뒀습니다. 누르면 샘플 종목의 기술 신호를 계산합니다.")
            return
        summary_df = get_all_summary(tuple(sorted(st.session_state.fin_score_map.items())), "개인모드", tuple(st.session_state.watchlist))
        if summary_df.empty:
            st.warning("전광판에 표시할 종목이 없습니다.")
        else:
            render_dashboard_group_summary(summary_df, "전체")
        return

    if demo_page == "정밀관측소":
        st.subheader("정밀관측소")
        st.caption("샘플 종목 하나만 골라 가볍게 판정을 확인합니다.")
        sample_items = [sanitize_watchlist_item(item) for item in st.session_state.get("watchlist", [])]
        labels = [f"{item['name']} ({item['ticker']})" for item in sample_items]
        selected_label = st.selectbox("샘플 종목", labels, key="public_demo_precision_sample")
        item = sample_items[labels.index(selected_label)] if labels else {}
        if not item:
            st.info("샘플 종목이 없습니다.")
            return
        if st.button("정밀 분석 실행", key="public_demo_precision_run", use_container_width=True):
            st.session_state["public_demo_precision_ready"] = selected_label
        if st.session_state.get("public_demo_precision_ready") != selected_label:
            st.info("첫 화면 속도를 위해 차트 데이터 조회를 멈춰뒀습니다. 버튼을 누르면 이 종목만 분석합니다.")
            return

        tkr = sanitize_ticker_value(item.get("ticker", ""))
        name = sanitize_asset_name(item.get("name", ""), tkr)
        is_etf = is_fin_score_exempt_asset(tkr, item.get("is_etf", False), item.get("asset_class", ""), name)
        asset_class = infer_asset_class_for_ticker(tkr, item.get("asset_class", "")) if is_etf else item.get("asset_class", "")
        df = load_price_df(tkr, "1y")
        if df.empty:
            st.error("샘플 종목 차트 데이터를 불러오지 못했습니다.")
            return
        df = build_indicators(df)
        fin_score, fin_meta = load_fin_score_meta_fast(tkr, is_etf)
        my_price = get_my_price(name, tkr)
        has_pos_value = has_position(name, tkr)
        c = calc_scores_and_decision(name, tkr, is_etf, asset_class, df, my_price, has_pos_value, int(fin_score), False, "개인모드")
        st.markdown(f'<div class="signal-box" style="background-color: {c["col"]};"><div style="font-size: 1.4em;">{c["dec"]}</div><div class="score-detail">Adj: {c["adj"]:.1f}점</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([
            {"항목": "현재가", "값": format_currency(c["cur_p"], tkr)},
            {"항목": "목표/현재 비중", "값": f"{c['target_w']:.2f}% / {c['current_w']:.2f}%"},
            {"항목": "RSI/MFI/%B", "값": f"{c['rsi']:.1f} / {c['mfi']:.1f} / {c['pct_b']:.2f}"},
            {"항목": "후보등급", "값": c["grade"]},
        ]), use_container_width=True, hide_index=True)
        render_pre_buy_final_check_panel(name, tkr, is_etf, c, int(fin_score), has_pos_value, my_price)
        return

    if demo_page == "시나리오":
        st.subheader("시나리오 점검")
        if st.button("시나리오 계산 시작", key="public_demo_scenario_run", use_container_width=True):
            st.session_state["public_demo_scenario_ready"] = True
        if st.session_state.get("public_demo_scenario_ready", False):
            render_scenario_check_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight)
        else:
            st.info("시나리오는 보유자산별 충격률을 계산해서 버튼을 누를 때만 실행합니다.")
        return

    if demo_page == "단기 흐름":
        st.subheader("단기 흐름 점검")
        if st.button("단기 흐름 계산 시작", key="public_demo_short_trend_run", use_container_width=True):
            st.session_state["public_demo_short_trend_ready"] = True
        if st.session_state.get("public_demo_short_trend_ready", False):
            render_short_trend_tab(holdings_table, st.session_state.watchlist)
        else:
            st.info("단기 흐름은 여러 종목의 가격 데이터를 읽어서 버튼을 누를 때만 계산합니다.")
        return

    if demo_page == "신호 검증":
        st.subheader("신호 검증")
        if st.button("신호 검증 시작", key="public_demo_backtest_run", use_container_width=True):
            st.session_state["public_demo_backtest_ready"] = True
        if st.session_state.get("public_demo_backtest_ready", False):
            render_signal_backtest_tab(holdings_table, st.session_state.watchlist)
        else:
            st.info("신호 검증은 과거 가격을 길게 계산하므로 데모에서는 버튼을 누른 뒤 실행합니다.")
        return

    if demo_page == "돈흐름":
        st.subheader("돈흐름 레이더")
        if st.button("돈흐름 계산 시작", key="public_demo_money_flow_run", use_container_width=True):
            st.session_state["public_demo_money_flow_ready"] = True
        if st.session_state.get("public_demo_money_flow_ready", False):
            render_money_flow_tab()
        else:
            st.info("돈흐름은 ETF/섹터 가격을 여러 개 조회해서 무겁습니다. 필요할 때만 계산합니다.")
        return

    if demo_page == "월배당 ETF":
        st.subheader("월배당 ETF")
        if st.button("월배당 ETF 화면 열기", key="public_demo_kr_etf_run", use_container_width=True):
            st.session_state["public_demo_kr_etf_ready"] = True
        if st.session_state.get("public_demo_kr_etf_ready", False):
            render_kr_etf_lab_tab()
        else:
            st.info("월배당 ETF 데이터 화면도 표가 커서 버튼을 누를 때만 엽니다.")
        return

    if demo_page == "피드백":
        render_feedback_tab()
        return

    render_user_guide_tab()
    render_manual_tab()


# -------------------------------------------------
# 8. 메인 UI 렌더링
# -------------------------------------------------
macro_res, final_macro_risk, macro_penalty, move_val = get_public_demo_macro_analysis() if IS_PUBLIC_DEMO else get_macro_analysis()
# globals() 의존 제거: 핵심 앱 상태를 session_state에 등록
st.session_state["_app_final_macro_risk"] = final_macro_risk
st.caption(f"모드: {app_mode_label} | 매크로 리스크: {final_macro_risk:.1f} | 매크로 패널티: -{macro_penalty}")
if IS_PUBLIC_DEMO:
    st.warning("체험모드입니다. 화면 조작은 가능하지만 보유자산, 관심종목, 재무점수, ETF 데이터, 복구/저장은 서버에 반영되지 않습니다.")

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
auto_usdkrw = None if IS_PUBLIC_DEMO else load_usdkrw_rate()
usdkrw = float(auto_usdkrw) if auto_usdkrw and auto_usdkrw > 0 else saved_usdkrw
usdkrw_source = "자동 환율" if auto_usdkrw and auto_usdkrw > 0 else "저장 환율"
effective_settings = dict(settings)
effective_settings["usdkrw"] = usdkrw
reserve_target_weight = float(settings.get("reserve_target_weight", 10.0))      

render_refresh_control_panel()

holdings_table = build_holdings_table(holdings_df, krw_cash, usd_cash, usdkrw)
# globals() 의존 제거: 현금/환율/보유자산 테이블을 session_state에 등록
st.session_state["_app_krw_cash"] = krw_cash
st.session_state["_app_usd_cash"] = usd_cash
st.session_state["_app_usdkrw"] = usdkrw
st.session_state["_app_holdings_table"] = holdings_table
portfolio_summary = calc_portfolio_summary(holdings_table, seed_money, krw_cash, usd_cash, usdkrw, dividends_df)
total_eval = portfolio_summary["current_asset"]


def render_print_report_v2():
    def _num(value, default=0.0):
        try:
            return clean_float(value, default)
        except Exception:
            try:
                return float(value)
            except Exception:
                return default

    def _fmt_money(value):
        value = _num(value, np.nan)
        return "-" if not np.isfinite(value) else f"{value:,.0f}원"

    def _fmt_pct(value, digits=2):
        value = _num(value, np.nan)
        return "-" if not np.isfinite(value) else f"{value:.{digits}f}%"

    def _fmt_ratio(value, digits=2):
        value = _num(value, np.nan)
        return "-" if not np.isfinite(value) else f"{value:.{digits}f}"

    def _make_report_asset_df():
        base_df = holdings_table.copy() if isinstance(holdings_table, pd.DataFrame) else pd.DataFrame()
        total_asset = _num(portfolio_summary.get("current_asset"), 0.0)
        report_df = append_cash_rows(base_df, krw_cash, usd_cash, usdkrw, total_asset)
        if report_df is None or report_df.empty:
            return pd.DataFrame()

        for col in ["원화환산", "현재비중", "목표비중", "리밸런싱목표비중", "비중차이", "평가손익", "수익률"]:
            if col in report_df.columns:
                report_df[col] = pd.to_numeric(report_df[col], errors="coerce").fillna(0.0)

        if "리밸런싱목표비중" not in report_df.columns and "목표비중" in report_df.columns:
            report_df["리밸런싱목표비중"] = report_df["목표비중"]
        if "비중차이" not in report_df.columns:
            target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in report_df.columns else "목표비중"
            if "현재비중" in report_df.columns and target_col in report_df.columns:
                report_df["비중차이"] = report_df["현재비중"] - report_df[target_col]

        if "평가손익_원화" not in report_df.columns:
            if "평가손익" in report_df.columns:
                def _pnl_krw(row):
                    ticker = str(row.get("티커", "")).upper()
                    pnl = _num(row.get("평가손익"), 0.0)
                    code = ticker.replace(".KS", "").replace(".KQ", "")
                    is_kr = (
                        ticker.endswith((".KS", ".KQ"))
                        or "CASH" in ticker
                        or (len(code) == 6 and code[0].isdigit() and code.isalnum())
                    )
                    if is_kr:
                        return pnl
                    return pnl * _num(usdkrw, 1400.0)
                report_df["평가손익_원화"] = report_df.apply(_pnl_krw, axis=1)
            else:
                report_df["평가손익_원화"] = 0.0

        if "수익률_pct" not in report_df.columns:
            if "수익률" in report_df.columns:
                report_df["수익률_pct"] = report_df["수익률"] * 100
            else:
                report_df["수익률_pct"] = 0.0

        return report_df

    def _print_table(df, columns, max_rows=20):
        if df is None or df.empty:
            st.caption("표시할 데이터가 없습니다.")
            return
        show_cols = [col for col in columns if col in df.columns]
        if not show_cols:
            show_cols = list(df.columns[:8])
        st.table(df.loc[:, show_cols].head(max_rows))

    def _format_asset_table(df, max_rows=30):
        if df is None or df.empty:
            return pd.DataFrame()
        view = df.copy()
        target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in view.columns else "목표비중"
        rename_map = {
            "자산명": "자산명",
            "티커": "티커",
            "원화환산": "평가금액",
            "현재비중": "현재비중",
            target_col: "목표비중",
            "비중차이": "비중차이",
            "평가손익_원화": "평가손익",
            "수익률_pct": "수익률",
        }
        cols = [col for col in rename_map if col in view.columns]
        view = view[cols].rename(columns=rename_map)
        for col in ["평가금액", "평가손익"]:
            if col in view.columns:
                view[col] = view[col].apply(_fmt_money)
        for col in ["현재비중", "목표비중", "비중차이", "수익률"]:
            if col in view.columns:
                view[col] = view[col].apply(_fmt_pct)
        return view.head(max_rows)

    def _format_generic_table(df, max_rows=12):
        if df is None or df.empty:
            return pd.DataFrame()
        view = df.copy().head(max_rows)
        for col in view.columns:
            col_text = str(col)
            if any(key in col_text for key in ["금액", "평가자산", "투입원금", "손익", "원화환산", "현재가", "배당"]):
                view[col] = view[col].apply(_fmt_money)
            elif any(key in col_text for key in ["비중", "수익률", "변동성", "MDD", "VaR"]):
                view[col] = view[col].apply(_fmt_pct)
            elif any(key in col_text for key in ["상관", "샤프", "소르티노", "칼마"]):
                view[col] = view[col].apply(_fmt_ratio)
        return view

    def _active_plan_rows():
        if holdings_table is None or holdings_table.empty:
            return pd.DataFrame()
        df = holdings_table.copy()
        target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in df.columns else "목표비중"
        if target_col not in df.columns:
            return pd.DataFrame()
        if "bucket" in df.columns:
            df = df[~df["bucket"].apply(lambda b: normalize_bucket(str(b)) in {"reserve", "cash"})].copy()
        if "운용대상" in df.columns:
            df = df[df["운용대상"].apply(clean_bool)].copy()
        df[target_col] = pd.to_numeric(df[target_col], errors="coerce").fillna(0.0)
        df = df[df[target_col] > 0].copy()
        df["_print_target_weight"] = df[target_col]
        return df

    def _build_monthly_plan_report():
        monthly = _num(st.session_state.get("rebcalc_monthly", 750000), 750000)
        carryover = _num(st.session_state.get("rebcalc_carryover", 0), 0.0)
        total_invest = max(monthly + carryover, 0.0)
        active_df = _active_plan_rows()
        empty_metrics = {
            "monthly": monthly,
            "carryover": carryover,
            "total_invest": total_invest,
            "total_rec_krw": 0.0,
            "krw_buy": 0.0,
            "usd_buy_krw": 0.0,
            "usd_buy": 0.0,
            "underalloc_count": 0,
        }
        if active_df.empty or total_invest <= 0:
            return pd.DataFrame(), empty_metrics

        target_sum = float(active_df["_print_target_weight"].sum())
        if target_sum <= 0:
            return pd.DataFrame(), empty_metrics

        signal_cache = st.session_state.get("_ticker_signal_cache", {})
        accum_map = st.session_state.get("rebcalc_accum", {})
        rows = []
        for _, row in active_df.iterrows():
            ticker = sanitize_ticker_value(row.get("티커", ""))
            name = sanitize_asset_name(row.get("자산명", ""), ticker)
            bucket = normalize_bucket(str(row.get("bucket", "core")))
            target_w = _num(row.get("_print_target_weight"), 0.0)
            current_price = _num(row.get("현재가"), 0.0)
            avg_price = _num(row.get("매입가"), 0.0)
            is_usd = bool(ticker and not ticker.upper().endswith((".KS", ".KQ")) and ticker not in ("KRW_CASH", "USD_CASH"))
            unit_price_krw = current_price * _num(usdkrw, 1400.0) if is_usd else current_price
            base_alloc = total_invest * (target_w / target_sum)

            signal = str(signal_cache.get(ticker, "") or "").strip()
            dip_level = 0
            if bucket == "leverage" and avg_price > 0 and current_price > 0:
                pct_drop = (current_price - avg_price) / avg_price
                if pct_drop <= -0.15:
                    dip_level = 3
                elif pct_drop <= -0.10:
                    dip_level = 2
                elif pct_drop <= -0.05:
                    dip_level = 1
            try:
                multiplier = _rebcalc_signal_multiplier(signal, bucket, dip_level=dip_level) if signal else 1.0
            except Exception:
                multiplier = 1.0

            alloc = base_alloc * multiplier
            rows.append({
                "name": name,
                "ticker": ticker,
                "bucket": bucket,
                "target_w": target_w,
                "signal": signal or "목표비중 기준",
                "multiplier": multiplier,
                "base_alloc": base_alloc,
                "alloc": alloc,
                "unit_price_krw": unit_price_krw,
                "is_usd": is_usd,
                "accum": _num(accum_map.get(ticker), 0.0),
            })

        blocked_total = sum(r["base_alloc"] for r in rows if r["multiplier"] <= 0)
        investable = [r for r in rows if r["multiplier"] > 0]
        inv_target_sum = sum(r["target_w"] for r in investable) or 1.0
        redistribute = bool(st.session_state.get("rebcalc_redistribute", True))
        for r in rows:
            if r["multiplier"] <= 0:
                r["final_alloc"] = 0.0
            else:
                bonus = blocked_total * (r["target_w"] / inv_target_sum) if redistribute else 0.0
                r["final_alloc"] = r["alloc"] + bonus

        total_final = sum(r["final_alloc"] for r in rows)
        if total_final > total_invest and total_final > 0:
            scale = total_invest / total_final
            for r in rows:
                r["final_alloc"] *= scale

        table_rows = []
        total_rec_krw = 0.0
        krw_buy = 0.0
        usd_buy_krw = 0.0
        underalloc_count = 0
        for r in rows:
            effective_alloc = r["final_alloc"] + r["accum"]
            shares = int(effective_alloc / r["unit_price_krw"]) if r["unit_price_krw"] > 0 and r["final_alloc"] > 0 else 0
            rec_krw = shares * r["unit_price_krw"]
            total_rec_krw += rec_krw
            if r["is_usd"]:
                usd_buy_krw += rec_krw
            else:
                krw_buy += rec_krw
            if r["final_alloc"] > 0 and shares == 0:
                underalloc_count += 1
            status = "매수 가능" if shares > 0 else ("1주 미달/누적" if r["final_alloc"] > 0 else "이번달 제외")
            table_rows.append({
                "자산명": r["name"],
                "티커": r["ticker"],
                "버킷": r["bucket"],
                "목표비중": r["target_w"],
                "판정기준": r["signal"],
                "이번달 배분": r["final_alloc"],
                "1주 가격": r["unit_price_krw"],
                "예상 주수": shares,
                "예상 매수금": rec_krw,
                "현재 누적금": r["accum"],
                "상태": status,
            })

        metrics = {
            "monthly": monthly,
            "carryover": carryover,
            "total_invest": total_invest,
            "total_rec_krw": total_rec_krw,
            "krw_buy": krw_buy,
            "usd_buy_krw": usd_buy_krw,
            "usd_buy": usd_buy_krw / _num(usdkrw, 1400.0) if _num(usdkrw, 0.0) > 0 else 0.0,
            "underalloc_count": underalloc_count,
        }
        return pd.DataFrame(table_rows), metrics

    def _build_total_needed_shares_report():
        active_df = _active_plan_rows()
        if active_df.empty:
            return pd.DataFrame()
        total_asset = _num(portfolio_summary.get("current_asset"), 0.0)
        rows = []
        for _, row in active_df.iterrows():
            ticker = sanitize_ticker_value(row.get("티커", ""))
            name = sanitize_asset_name(row.get("자산명", ""), ticker)
            current_price = _num(row.get("현재가"), 0.0)
            qty_now = _num(row.get("보유량"), 0.0)
            target_w = _num(row.get("_print_target_weight"), 0.0)
            bucket = normalize_bucket(str(row.get("bucket", "core")))
            is_usd = bool(ticker and not ticker.upper().endswith((".KS", ".KQ")) and ticker not in ("KRW_CASH", "USD_CASH"))
            unit_price_krw = current_price * _num(usdkrw, 1400.0) if is_usd else current_price
            target_value = total_asset * target_w / 100 if total_asset > 0 else 0.0
            target_shares = target_value / unit_price_krw if unit_price_krw > 0 else 0.0
            needed_shares = target_shares - qty_now
            needed_value = max(needed_shares, 0.0) * unit_price_krw
            rows.append({
                "자산명": name,
                "티커": ticker,
                "버킷": bucket,
                "목표비중": target_w,
                "목표 주수": target_shares,
                "현재 주수": qty_now,
                "추가 필요 주수": needed_shares,
                "추가 필요 금액": needed_value,
                "상태": "매수 필요" if needed_shares >= 0.5 else ("비중 초과" if needed_shares < -0.5 else "거의 도달"),
            })
        return pd.DataFrame(rows)

    def _format_monthly_plan_table(df, max_rows=24):
        if df is None or df.empty:
            return pd.DataFrame()
        view = df.copy().sort_values(["상태", "이번달 배분"], ascending=[True, False]).head(max_rows)
        for col in ["이번달 배분", "1주 가격", "예상 매수금", "현재 누적금"]:
            if col in view.columns:
                view[col] = view[col].apply(_fmt_money)
        if "목표비중" in view.columns:
            view["목표비중"] = view["목표비중"].apply(_fmt_pct)
        return view

    def _format_needed_shares_table(df, max_rows=24):
        if df is None or df.empty:
            return pd.DataFrame()
        view = df.copy().sort_values("추가 필요 금액", ascending=False).head(max_rows)
        for col in ["목표 주수", "현재 주수", "추가 필요 주수"]:
            if col in view.columns:
                view[col] = view[col].apply(lambda v: "-" if not np.isfinite(_num(v, np.nan)) else f"{_num(v):,.2f}")
        if "목표비중" in view.columns:
            view["목표비중"] = view["목표비중"].apply(_fmt_pct)
        if "추가 필요 금액" in view.columns:
            view["추가 필요 금액"] = view["추가 필요 금액"].apply(_fmt_money)
        return view

    def _render_asset_report_charts(df):
        if df is None or df.empty or "원화환산" not in df.columns:
            return

        chart_df = df.copy()
        for col in ["원화환산", "수익률_pct", "현재비중", "목표비중", "리밸런싱목표비중", "비중차이", "평가손익_원화"]:
            if col in chart_df.columns:
                chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce").fillna(0.0)
        chart_df = chart_df[chart_df["원화환산"] > 0].copy()
        if chart_df.empty:
            return

        if "자산명" not in chart_df.columns:
            chart_df["자산명"] = chart_df.get("티커", "")
        if "티커" not in chart_df.columns:
            chart_df["티커"] = ""
        target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in chart_df.columns else "목표비중"
        if target_col not in chart_df.columns:
            chart_df[target_col] = 0.0
        if "비중차이" not in chart_df.columns:
            chart_df["비중차이"] = chart_df["현재비중"] - chart_df[target_col]

        st.markdown("#### 포트폴리오 히트맵 / 타점·비중·수익률 매트릭스")
        c1, c2 = st.columns(2)
        with c1:
            fig_tree = go.Figure(go.Treemap(
                labels=chart_df["자산명"],
                parents=[""] * len(chart_df),
                values=chart_df["원화환산"],
                marker=dict(
                    colors=chart_df["수익률_pct"],
                    colorscale=[[0, "#dc2626"], [0.5, "#64748b"], [1, "#16a34a"]],
                    cmid=0,
                    colorbar=dict(title="수익률"),
                ),
                customdata=chart_df[[target_col, "현재비중", "평가손익_원화", "수익률_pct"]],
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "평가금액: ₩%{value:,.0f}<br>"
                    "현재/목표: %{customdata[1]:.2f}% / %{customdata[0]:.2f}%<br>"
                    "평가손익: ₩%{customdata[2]:,.0f}<br>"
                    "수익률: %{customdata[3]:.2f}%<extra></extra>"
                ),
            ))
            fig_tree.update_layout(template="plotly_dark", height=360, margin=dict(t=36, l=8, r=8, b=8), title="포트폴리오 히트맵")
            st.plotly_chart(fig_tree, use_container_width=True)

        with c2:
            matrix_df = chart_df.copy()
            if "bucket" in matrix_df.columns:
                matrix_df = matrix_df[~matrix_df["bucket"].apply(lambda b: normalize_bucket(str(b)) in {"cash", "reserve"})].copy()
            if matrix_df.empty:
                st.info("매트릭스로 표시할 운용 자산이 없습니다.")
            else:
                signal_cache = st.session_state.get("_ticker_signal_cache", {})
                matrix_df["타점"] = matrix_df["티커"].apply(lambda t: str(signal_cache.get(sanitize_ticker_value(t), "-") or "-"))
                max_value = max(float(matrix_df["원화환산"].max() or 0), 1.0)
                matrix_df["_size"] = np.clip(np.sqrt(matrix_df["원화환산"] / max_value) * 46, 12, 46)
                matrix_df["_label"] = ""
                top_label_idx = matrix_df.sort_values("원화환산", ascending=False).head(12).index
                matrix_df.loc[top_label_idx, "_label"] = matrix_df.loc[top_label_idx, "자산명"]
                fig_matrix = go.Figure(go.Scatter(
                    x=matrix_df["비중차이"],
                    y=matrix_df["수익률_pct"],
                    mode="markers+text",
                    text=matrix_df["_label"],
                    textposition="top center",
                    marker=dict(
                        size=matrix_df["_size"],
                        color=matrix_df["현재비중"],
                        colorscale="Viridis",
                        showscale=True,
                        colorbar=dict(title="현재비중"),
                        opacity=0.86,
                    ),
                    customdata=matrix_df[["자산명", "티커", "타점", "현재비중", target_col, "원화환산"]],
                    hovertemplate=(
                        "<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
                        "타점: %{customdata[2]}<br>"
                        "비중차이: %{x:.2f}%p<br>"
                        "수익률: %{y:.2f}%<br>"
                        "현재/목표: %{customdata[3]:.2f}% / %{customdata[4]:.2f}%<br>"
                        "평가금액: ₩%{customdata[5]:,.0f}<extra></extra>"
                    ),
                ))
                fig_matrix.add_vline(x=0, line_dash="dash", line_color="#94a3b8")
                fig_matrix.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
                fig_matrix.update_layout(
                    template="plotly_dark",
                    height=360,
                    margin=dict(t=36, l=8, r=8, b=8),
                    title="타점/비중/수익률 매트릭스",
                    xaxis_title="비중차이(%p)",
                    yaxis_title="수익률(%)",
                )
                st.plotly_chart(fig_matrix, use_container_width=True)

    def _render_monthly_report_charts(monthly_perf_df):
        if monthly_perf_df is None or monthly_perf_df.empty:
            return
        required = {"month_label", "evaluated_value", "total_invested", "cum_profit", "cum_return_pct"}
        if not required.issubset(set(monthly_perf_df.columns)):
            return

        st.markdown("#### 월별 흐름 차트")
        chart_df = monthly_perf_df.copy()
        for col in ["evaluated_value", "total_invested", "cum_profit", "cum_return_pct", "dividend"]:
            if col in chart_df.columns:
                chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce").fillna(0.0)
        if "dividend" not in chart_df.columns:
            chart_df["dividend"] = 0.0

        p1, p2 = st.columns(2)
        with p1:
            fig_monthly_asset = go.Figure()
            fig_monthly_asset.add_trace(go.Scatter(
                x=chart_df["month_label"],
                y=chart_df["evaluated_value"],
                mode="lines+markers",
                name="평가자산",
                line=dict(color="#ef4444", width=3),
                hovertemplate="%{x}<br>평가자산: ₩%{y:,.0f}<extra></extra>",
            ))
            fig_monthly_asset.add_trace(go.Scatter(
                x=chart_df["month_label"],
                y=chart_df["total_invested"],
                mode="lines+markers",
                name="투입원금",
                line=dict(color="#cbd5e1", width=2),
                hovertemplate="%{x}<br>투입원금: ₩%{y:,.0f}<extra></extra>",
            ))
            fig_monthly_asset.update_layout(
                template="plotly_dark",
                height=350,
                title=dict(text="월별 투자 기록", y=0.97, x=0.5, xanchor="center"),
                yaxis_title="원",
                legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
                margin=dict(t=40, l=8, r=8, b=70),
            )
            st.plotly_chart(fig_monthly_asset, use_container_width=True)

        with p2:
            fig_pnl_div = make_subplots(specs=[[{"secondary_y": True}]])
            pnl_colors = np.where(chart_df["cum_profit"] >= 0, "#22d3ee", "#ef4444")
            fig_pnl_div.add_trace(go.Bar(
                x=chart_df["month_label"],
                y=chart_df["cum_profit"],
                name="누적손익",
                marker_color=pnl_colors,
                hovertemplate="%{x}<br>누적손익: ₩%{y:,.0f}<extra></extra>",
            ), secondary_y=False)
            fig_pnl_div.add_trace(go.Scatter(
                x=chart_df["month_label"],
                y=chart_df["dividend"],
                mode="lines+markers",
                name="월별배당금",
                line=dict(color="#fbbf24", width=3),
                hovertemplate="%{x}<br>월별배당금: ₩%{y:,.0f}<extra></extra>",
            ), secondary_y=True)
            fig_pnl_div.add_hline(y=0, line_color="#94a3b8")
            fig_pnl_div.update_layout(
                template="plotly_dark",
                height=350,
                title=dict(text="누적손익 / 월별배당금", y=0.97, x=0.5, xanchor="center"),
                legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
                margin=dict(t=40, l=8, r=8, b=70),
            )
            fig_pnl_div.update_yaxes(title_text="누적손익(원)", secondary_y=False)
            fig_pnl_div.update_yaxes(title_text="배당금(원)", secondary_y=True)
            st.plotly_chart(fig_pnl_div, use_container_width=True)

        p3, p4 = st.columns(2)
        with p3:
            fig_cum_return = go.Figure(go.Scatter(
                x=chart_df["month_label"],
                y=chart_df["cum_return_pct"],
                mode="lines+markers",
                name="월별 누적수익률",
                line=dict(color="#22c55e", width=3),
                hovertemplate="%{x}<br>누적수익률: %{y:.2f}%<extra></extra>",
            ))
            fig_cum_return.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
            fig_cum_return.update_layout(
                template="plotly_dark",
                height=320,
                title=dict(text="월별 누적수익률", y=0.97, x=0.5, xanchor="center"),
                yaxis_title="수익률(%)",
                margin=dict(t=40, l=8, r=8, b=30),
            )
            st.plotly_chart(fig_cum_return, use_container_width=True)

        with p4:
            try:
                benchmark_df = build_benchmark_return_df(monthly_perf_df)
            except Exception:
                benchmark_df = pd.DataFrame()
            if benchmark_df is None or benchmark_df.empty:
                st.info("벤치마크 비교 데이터를 계산할 수 없습니다.")
            else:
                fig_benchmark = go.Figure()
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
                        line=dict(
                            color=color_map.get(label, "#cbd5e1"),
                            width=3 if label == "내 기간수익률" else 2,
                            dash="solid" if label == "내 기간수익률" else "dot",
                        ),
                        hovertemplate=f"%{{x}}<br>{label}: %{{y:.2f}}%<extra></extra>",
                    ))
                fig_benchmark.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
                fig_benchmark.update_layout(
                    template="plotly_dark",
                    height=320,
                    title=dict(text="첫 기록월 대비 수익률 변화 vs 벤치마크", y=0.97, x=0.5, xanchor="center"),
                    yaxis_title="수익률(%)",
                    legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
                    margin=dict(t=40, l=8, r=8, b=70),
                )
                st.plotly_chart(fig_benchmark, use_container_width=True)

    with st.sidebar:
        st.success("인쇄 모드")
        st.caption("브라우저에서 Ctrl + P를 누르면 현재 리포트를 출력할 수 있습니다.")
        if st.button("인쇄 모드 끄기", key="print_mode_off_v2"):
            st.session_state["print_mode_toggle_final"] = False
            st.rerun()

    st.markdown(
        """
        <style>
        @media print {
            [data-testid="stSidebar"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
            .main .block-container { max-width: 100% !important; padding: 12px 24px !important; }
            .print-page-break { page-break-before: always; }
        }
        .print-note {
            border: 1px solid rgba(148, 163, 184, .35);
            border-radius: 8px;
            padding: 12px 14px;
            color: #cbd5e1;
            background: rgba(15, 23, 42, .45);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    report_df = _make_report_asset_df()
    reserve_summary = calc_reserve_summary(report_df, reserve_target_weight) if not report_df.empty else {}
    current_asset = _num(portfolio_summary.get("current_asset"), 0.0)
    stock_value = _num(portfolio_summary.get("stock_value"), 0.0)
    cash_value = _num(portfolio_summary.get("cash_value"), 0.0)
    cum_profit = _num(portfolio_summary.get("cum_profit"), 0.0)
    cum_return = _num(portfolio_summary.get("cum_return"), 0.0)
    total_dividend = _num(portfolio_summary.get("total_dividend"), 0.0)
    waiting_value = _num(reserve_summary.get("waiting_value"), cash_value)
    waiting_pct = _num(reserve_summary.get("waiting_pct"), 0.0)
    target_waiting_pct = _num(reserve_summary.get("target_pct"), reserve_target_weight)

    st.title("Stock Lab 출력 리포트")
    st.caption(f"생성일시: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} / 기준 환율: {_num(usdkrw, 0):,.2f}원")
    st.markdown(
        "<div class='print-note'>투자 추천서가 아니라 현재 자산, 포트폴리오 리스크, 오늘 점검할 항목을 한 번에 보기 위한 개인용 관리 리포트입니다.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("## 1. 자산현황")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총자산", _fmt_money(current_asset), f"투자자산 {_fmt_money(stock_value)}")
    k2.metric("누적손익", _fmt_money(cum_profit), _fmt_pct(cum_return))
    k3.metric("누적수익률", _fmt_pct(cum_return), f"누적배당 {_fmt_money(total_dividend)}")
    k4.metric("대기자금", _fmt_money(waiting_value), f"{waiting_pct:.2f}% / 목표 {target_waiting_pct:.2f}%")

    if not report_df.empty:
        st.markdown("#### 자산 구성/비중 상세")
        asset_detail_df = report_df.sort_values("현재비중", ascending=False) if "현재비중" in report_df.columns else report_df
        st.table(_format_asset_table(asset_detail_df, max_rows=35))
        _render_asset_report_charts(report_df)
    else:
        st.info("출력할 보유 자산이 없습니다.")

    st.markdown("<div class='print-page-break'></div>", unsafe_allow_html=True)
    st.markdown("## 2. 이번달 운용계획")
    plan_df, plan_metrics = _build_monthly_plan_report()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("이번달 투입 가능", _fmt_money(plan_metrics["total_invest"]), f"적립 {_fmt_money(plan_metrics['monthly'])}")
    m2.metric("예상 매수금", _fmt_money(plan_metrics["total_rec_krw"]))
    m3.metric("달러 환전 필요", f"${plan_metrics['usd_buy']:,.2f}", _fmt_money(plan_metrics["usd_buy_krw"]))
    m4.metric("1주 미달", f"{plan_metrics['underalloc_count']}개", f"이월 {_fmt_money(plan_metrics['carryover'])}")

    st.markdown("#### 이번달 분배계획")
    if plan_df.empty:
        st.info("이번달 분배계획을 계산할 목표비중 또는 적립금이 없습니다.")
    else:
        st.table(_format_monthly_plan_table(plan_df, max_rows=24))
        st.caption("인쇄 리포트의 분배계획은 월 적립 리밸런싱 계산기의 월 적립금, 이월금, 누적금을 읽어와 목표비중 기준으로 요약합니다.")

    st.markdown("#### 총 필요 주수")
    needed_df = _build_total_needed_shares_report()
    if needed_df.empty:
        st.info("총 필요 주수를 계산할 운용 대상 자산이 없습니다.")
    else:
        st.table(_format_needed_shares_table(needed_df, max_rows=24))

    st.markdown("<div class='print-page-break'></div>", unsafe_allow_html=True)
    st.markdown("## 3. 포트폴리오 분석 및 월별 성과")
    try:
        metrics, asset_risk_df, notes_df, corr_df, portfolio_curve, risk_contrib_df = build_portfolio_analysis_report(
            holdings_table,
            krw_cash,
            usd_cash,
            usdkrw,
            reserve_target_weight,
            period="1y",
            analysis_start_date=get_portfolio_analysis_start_date(monthly_logs_df),
        )
    except Exception as exc:
        metrics, asset_risk_df, notes_df, corr_df, portfolio_curve, risk_contrib_df = {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=float), pd.DataFrame()
        st.warning(f"포트폴리오 분석 계산 중 일부 데이터를 불러오지 못했습니다: {exc}")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("위험도", f"{metrics.get('risk_grade', '-')}", f"{_num(metrics.get('risk_index'), 0):.0f}/100")
    p2.metric("연환산 변동성", _fmt_pct(metrics.get("portfolio_vol"), 1))
    p3.metric("분석기간 MDD", _fmt_pct(metrics.get("portfolio_mdd"), 1))
    p4.metric("상위 3개 비중", _fmt_pct(metrics.get("top3_weight"), 1))

    if asset_risk_df is not None and not asset_risk_df.empty:
        st.markdown("#### 자산별 위험 요약")
        _print_table(
            _format_generic_table(asset_risk_df, max_rows=20),
            ["자산명", "티커", "원화환산", "전체비중", "운용비중", "기간수익률", "연환산변동성", "MDD", "데이터"],
            max_rows=20,
        )
    if notes_df is not None and not notes_df.empty:
        st.markdown("#### 확인할 리스크")
        st.table(notes_df.head(12))

    try:
        monthly_perf_df = prepare_monthly_performance_df(monthly_logs_df)
    except Exception:
        monthly_perf_df = pd.DataFrame()
    if monthly_perf_df is not None and not monthly_perf_df.empty:
        st.markdown("#### 월별 성과 기록")
        latest_month = monthly_perf_df.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("최근 기록월", str(latest_month.get("month_label", "-")))
        c2.metric("기록 평가자산", _fmt_money(latest_month.get("evaluated_value")))
        c3.metric("기록 누적손익", _fmt_money(latest_month.get("cum_profit")))
        c4.metric("기록 누적수익률", _fmt_pct(latest_month.get("cum_return_pct")))

        perf_cols = ["month_label", "evaluated_value", "total_invested", "cum_profit", "cum_return_pct", "dividend"]
        perf_df = monthly_perf_df.tail(12).copy()
        perf_df = perf_df[[c for c in perf_cols if c in perf_df.columns]].rename(columns={
            "month_label": "월",
            "evaluated_value": "평가자산",
            "total_invested": "투입원금",
            "cum_profit": "누적손익",
            "cum_return_pct": "누적수익률",
            "dividend": "월배당",
        })
        st.table(_format_generic_table(perf_df, max_rows=12))
        _render_monthly_report_charts(monthly_perf_df)
    else:
        st.info("월별 성과 기록이 없습니다.")


# 자산 현황 인쇄 전용 리포트  (render_full_print_report)
# ════════════════════════════════════════════════════════════════════════════
def render_full_print_report():
    """자산 현황 요약 및 포트폴리오 상세 인쇄 전용 리포트."""

    # ── 공통 포매터 ───────────────────────────────────────────────────────
    def _num(value, default=0.0):
        try:
            return clean_float(value, default)
        except Exception:
            try:
                return float(value)
            except Exception:
                return default

    def _fmt_money(value):
        v = _num(value, np.nan)
        return "-" if not np.isfinite(v) else f"{v:,.0f}원"

    def _fmt_pct(value, digits=2):
        v = _num(value, np.nan)
        return "-" if not np.isfinite(v) else f"{v:.{digits}f}%"

    def _fmt_price(value):
        v = _num(value, np.nan)
        return "-" if not np.isfinite(v) else f"{v:,.2f}"

    # ── 보유 자산 DataFrame 구성 ──────────────────────────────────────────
    def _make_report_df():
        base_df = holdings_table.copy() if isinstance(holdings_table, pd.DataFrame) else pd.DataFrame()
        total_asset = _num(portfolio_summary.get("current_asset"), 0.0)
        rdf = append_cash_rows(base_df, krw_cash, usd_cash, usdkrw, total_asset)
        if rdf is None or rdf.empty:
            return pd.DataFrame()
        for col in ["원화환산", "현재비중", "목표비중", "리밸런싱목표비중", "비중차이", "평가손익", "수익률"]:
            if col in rdf.columns:
                rdf[col] = pd.to_numeric(rdf[col], errors="coerce").fillna(0.0)
        # 평가손익 원화 환산
        if "평가손익_원화" not in rdf.columns:
            if "평가손익" in rdf.columns:
                def _pnl_krw(row):
                    ticker = str(row.get("티커", "")).upper()
                    pnl = _num(row.get("평가손익"), 0.0)
                    code = ticker.replace(".KS", "").replace(".KQ", "")
                    is_kr = (
                        ticker.endswith((".KS", ".KQ"))
                        or "CASH" in ticker
                        or (len(code) == 6 and code[0].isdigit() and code.isalnum())
                    )
                    return pnl if is_kr else pnl * _num(usdkrw, 1400.0)
                rdf["평가손익_원화"] = rdf.apply(_pnl_krw, axis=1)
            else:
                rdf["평가손익_원화"] = 0.0
        # 수익률 % 컬럼
        if "수익률_pct" not in rdf.columns:
            rdf["수익률_pct"] = rdf["수익률"] * 100 if "수익률" in rdf.columns else 0.0
        # 리밸런싱 목표비중 폴백
        if "리밸런싱목표비중" not in rdf.columns and "목표비중" in rdf.columns:
            rdf["리밸런싱목표비중"] = rdf["목표비중"]
        # 비중차이 폴백
        if "비중차이" not in rdf.columns:
            tcol = "리밸런싱목표비중" if "리밸런싱목표비중" in rdf.columns else "목표비중"
            if "현재비중" in rdf.columns and tcol in rdf.columns:
                rdf["비중차이"] = rdf["현재비중"] - rdf[tcol]
        return rdf

    # ── 보유 자산 표 포매팅 ───────────────────────────────────────────────
    def _format_holdings_table(df, max_rows=35):
        if df is None or df.empty:
            return pd.DataFrame()
        tcol = "리밸런싱목표비중" if "리밸런싱목표비중" in df.columns else "목표비중"
        rename_map = {
            "자산명": "자산명",
            "티커": "티커",
            "bucket": "버킷",
            "보유량": "보유량",
            "매입가": "평균매입가",
            "현재가": "현재가",
            "원화환산": "평가금액",
            "현재비중": "현재비중",
            tcol: "목표비중",
            "비중차이": "비중차이",
            "평가손익_원화": "평가손익",
            "수익률_pct": "수익률",
        }
        cols = [c for c in rename_map if c in df.columns]
        view = df[cols].rename(columns=rename_map)
        for col in ["평가금액", "평가손익"]:
            if col in view.columns:
                view[col] = view[col].apply(_fmt_money)
        for col in ["평균매입가", "현재가"]:
            if col in view.columns:
                view[col] = view[col].apply(_fmt_price)
        for col in ["현재비중", "목표비중", "비중차이", "수익률"]:
            if col in view.columns:
                view[col] = view[col].apply(_fmt_pct)
        return view.head(max_rows)

    # ── 월별 성과 표 포매팅 ───────────────────────────────────────────────
    def _format_monthly_table(df, max_rows=24):
        if df is None or df.empty:
            return pd.DataFrame()
        view = df.tail(max_rows).copy()
        for col in view.columns:
            ct = str(col)
            if any(k in ct for k in ["금액", "자산", "원금", "손익", "배당"]):
                view[col] = view[col].apply(_fmt_money)
            elif any(k in ct for k in ["수익률", "비중"]):
                view[col] = view[col].apply(_fmt_pct)
        return view

    # ── 사이드바 ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.success("자산 현황 인쇄 모드")
        st.caption("브라우저에서 Ctrl+P 를 누르면 현재 리포트를 출력할 수 있습니다.")
        if st.button("인쇄 모드 끄기", key="full_print_mode_off"):
            st.session_state["full_print_mode"] = False
            st.rerun()

    # ── 인쇄 CSS ──────────────────────────────────────────────────────────
    st.markdown(
        """
        <style>
        @media print {
            [data-testid="stSidebar"],
            [data-testid="stToolbar"],
            [data-testid="stDecoration"] { display: none !important; }
            .main .block-container { max-width: 100% !important; padding: 12px 24px !important; }
            .fpr-page-break { page-break-before: always; }
        }
        .fpr-note {
            border: 1px solid rgba(148,163,184,.35);
            border-radius: 8px;
            padding: 12px 14px;
            color: #cbd5e1;
            background: rgba(15,23,42,.45);
            margin-bottom: 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── 헤더 ──────────────────────────────────────────────────────────────
    st.title("Stock Lab — 자산 현황 리포트")
    st.caption(
        f"생성일시: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} "
        f"/ 기준 환율: {_num(usdkrw, 0):,.2f}원"
    )
    st.markdown(
        "<div class='fpr-note'>현재 자산 현황 및 포트폴리오 구성 요약 개인용 인쇄 리포트입니다.</div>",
        unsafe_allow_html=True,
    )

    # ── 기본 수치 ─────────────────────────────────────────────────────────
    report_df      = _make_report_df()
    reserve_summary = calc_reserve_summary(report_df, reserve_target_weight) if not report_df.empty else {}
    current_asset  = _num(portfolio_summary.get("current_asset"), 0.0)
    stock_value    = _num(portfolio_summary.get("stock_value"), 0.0)
    cash_value     = _num(portfolio_summary.get("cash_value"), 0.0)
    cum_profit     = _num(portfolio_summary.get("cum_profit"), 0.0)
    cum_return     = _num(portfolio_summary.get("cum_return"), 0.0)
    total_dividend = _num(portfolio_summary.get("total_dividend"), 0.0)
    waiting_value  = _num(reserve_summary.get("waiting_value"), cash_value)
    waiting_pct    = _num(reserve_summary.get("waiting_pct"), 0.0)

    # ══════════════════════════════════════════════════════════════════════
    # 1장 : 자산 현황 요약
    # ══════════════════════════════════════════════════════════════════════
    st.markdown("## 1. 자산 현황 요약")

    k1, k2, k3 = st.columns(3)
    k1.metric("총자산",    _fmt_money(current_asset), f"환율 {_num(usdkrw, 0):,.0f}원")
    k2.metric("투자자산",  _fmt_money(stock_value),   f"현금 {_fmt_money(cash_value)}")
    k3.metric("대기자금",  _fmt_money(waiting_value), f"{waiting_pct:.2f}%")

    k4, k5, k6 = st.columns(3)
    k4.metric("누적손익",    _fmt_money(cum_profit))
    k5.metric("누적수익률",  _fmt_pct(cum_return))
    k6.metric("누적수령배당", _fmt_money(total_dividend))

    if not report_df.empty:
        st.markdown("#### 보유 자산 요약")
        sorted_df = (
            report_df.sort_values("현재비중", ascending=False)
            if "현재비중" in report_df.columns
            else report_df
        )
        st.table(_format_holdings_table(sorted_df, max_rows=35))
    else:
        st.info("보유 자산 데이터가 없습니다.")

    # ══════════════════════════════════════════════════════════════════════
    # 2장 : 포트폴리오 상세
    # ══════════════════════════════════════════════════════════════════════
    st.markdown("<div class='fpr-page-break'></div>", unsafe_allow_html=True)
    st.markdown("## 2. 포트폴리오 상세")

    if not report_df.empty and "원화환산" in report_df.columns:
        chart_df = report_df.copy()
        for col in ["원화환산", "수익률_pct", "현재비중", "비중차이", "평가손익_원화"]:
            if col in chart_df.columns:
                chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce").fillna(0.0)
        chart_df = chart_df[chart_df["원화환산"] > 0].copy()

        if "자산명" not in chart_df.columns:
            chart_df["자산명"] = chart_df.get("티커", "")
        tcol = "리밸런싱목표비중" if "리밸런싱목표비중" in chart_df.columns else "목표비중"
        if tcol not in chart_df.columns:
            chart_df[tcol] = 0.0

        c1, c2 = st.columns(2)
        with c1:
            # 트리맵 (수익률 히트맵)
            fig_tree = go.Figure(go.Treemap(
                labels=chart_df["자산명"],
                parents=[""] * len(chart_df),
                values=chart_df["원화환산"],
                marker=dict(
                    colors=chart_df["수익률_pct"],
                    colorscale=[[0, "#dc2626"], [0.5, "#64748b"], [1, "#16a34a"]],
                    cmid=0,
                    showscale=True,
                    colorbar=dict(title="수익률%", thickness=12),
                ),
                customdata=chart_df[["티커", "현재비중", tcol, "평가손익_원화", "수익률_pct"]],
                hovertemplate=(
                    "<b>%{label}</b> (%{customdata[0]})<br>"
                    "평가금액: ₩%{value:,.0f}<br>"
                    "현재/목표: %{customdata[1]:.2f}% / %{customdata[2]:.2f}%<br>"
                    "평가손익: ₩%{customdata[3]:,.0f}<br>"
                    "수익률: %{customdata[4]:.2f}%<extra></extra>"
                ),
            ))
            fig_tree.update_layout(
                template="plotly_dark",
                height=360,
                margin=dict(t=36, l=8, r=8, b=8),
                title="포트폴리오 히트맵 (수익률)",
            )
            st.plotly_chart(fig_tree, use_container_width=True)

        with c2:
            # 현재비중 vs 목표비중 가로 막대
            bar_df = chart_df[chart_df[tcol] > 0].copy() if tcol in chart_df.columns else pd.DataFrame()
            if not bar_df.empty:
                bar_df = bar_df.sort_values("현재비중", ascending=True).tail(15)
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    y=bar_df["자산명"], x=bar_df["현재비중"],
                    name="현재비중", orientation="h",
                    marker_color="#22d3ee",
                ))
                fig_bar.add_trace(go.Bar(
                    y=bar_df["자산명"], x=bar_df[tcol],
                    name="목표비중", orientation="h",
                    marker_color="#f59e0b", opacity=0.55,
                ))
                fig_bar.update_layout(
                    barmode="overlay",
                    template="plotly_dark",
                    height=360,
                    title="현재비중 vs 목표비중",
                    xaxis_title="비중(%)",
                    legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
                    margin=dict(t=36, l=8, r=8, b=60),
                )
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("목표비중이 설정된 자산이 없습니다.")

        # 버킷별 요약
        if "bucket" in chart_df.columns:
            st.markdown("#### 버킷별 비중 요약")
            inv_df = chart_df[
                ~chart_df["bucket"].apply(lambda b: normalize_bucket(str(b)) in {"reserve", "cash"})
            ].copy()
            if not inv_df.empty:
                bucket_grp = (
                    inv_df.groupby("bucket")
                    .agg(평가금액=("원화환산", "sum"), 개수=("자산명", "count"), 평균수익률=("수익률_pct", "mean"))
                    .reset_index()
                )
                total_val = max(float(bucket_grp["평가금액"].sum()), 1.0)
                bucket_grp["비중"] = (bucket_grp["평가금액"] / total_val * 100).apply(_fmt_pct)
                bucket_grp["평가금액"] = bucket_grp["평가금액"].apply(_fmt_money)
                bucket_grp["평균수익률"] = bucket_grp["평균수익률"].apply(_fmt_pct)
                st.table(bucket_grp.rename(columns={"bucket": "버킷"}))
    else:
        st.info("포트폴리오 차트를 표시할 자산 데이터가 없습니다.")

    # ══════════════════════════════════════════════════════════════════════
    # 3장 : 월별 성과
    # ══════════════════════════════════════════════════════════════════════
    st.markdown("<div class='fpr-page-break'></div>", unsafe_allow_html=True)
    st.markdown("## 3. 월별 성과")

    try:
        monthly_perf_df = prepare_monthly_performance_df(monthly_logs_df)
    except Exception:
        monthly_perf_df = pd.DataFrame()

    if monthly_perf_df is not None and not monthly_perf_df.empty:
        latest = monthly_perf_df.iloc[-1]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("최근 기록월",    str(latest.get("month_label", "-")))
        m2.metric("기록 평가자산",  _fmt_money(latest.get("evaluated_value")))
        m3.metric("기록 누적손익",  _fmt_money(latest.get("cum_profit")))
        m4.metric("기록 누적수익률", _fmt_pct(latest.get("cum_return_pct")))

        # 월별 성과 표 (최근 24개월)
        perf_cols = ["month_label", "evaluated_value", "total_invested", "cum_profit", "cum_return_pct", "dividend"]
        perf_view = monthly_perf_df.tail(24).copy()
        perf_view = perf_view[[c for c in perf_cols if c in perf_view.columns]].rename(columns={
            "month_label": "월",
            "evaluated_value": "평가자산",
            "total_invested": "투입원금",
            "cum_profit": "누적손익",
            "cum_return_pct": "누적수익률(%)",
            "dividend": "월배당",
        })
        st.table(_format_monthly_table(perf_view, max_rows=24))

        # 차트
        _c = monthly_perf_df.copy()
        for col in ["evaluated_value", "total_invested", "cum_profit", "cum_return_pct", "dividend"]:
            if col in _c.columns:
                _c[col] = pd.to_numeric(_c[col], errors="coerce").fillna(0.0)
        if "dividend" not in _c.columns:
            _c["dividend"] = 0.0

        p1, p2 = st.columns(2)
        with p1:
            fig_asset = go.Figure()
            fig_asset.add_trace(go.Scatter(
                x=_c["month_label"], y=_c["evaluated_value"],
                mode="lines+markers", name="평가자산",
                line=dict(color="#ef4444", width=3),
                hovertemplate="%{x}<br>평가자산: ₩%{y:,.0f}<extra></extra>",
            ))
            fig_asset.add_trace(go.Scatter(
                x=_c["month_label"], y=_c["total_invested"],
                mode="lines+markers", name="투입원금",
                line=dict(color="#cbd5e1", width=2),
                hovertemplate="%{x}<br>투입원금: ₩%{y:,.0f}<extra></extra>",
            ))
            fig_asset.update_layout(
                template="plotly_dark", height=320,
                title=dict(text="월별 투자 기록", y=0.97, x=0.5, xanchor="center"),
                yaxis_title="원",
                legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
                margin=dict(t=40, l=8, r=8, b=70),
            )
            st.plotly_chart(fig_asset, use_container_width=True)

        with p2:
            fig_ret = go.Figure()
            fig_ret.add_trace(go.Scatter(
                x=_c["month_label"], y=_c["cum_return_pct"],
                mode="lines+markers", name="누적수익률",
                line=dict(color="#22d3ee", width=3),
                hovertemplate="%{x}<br>누적수익률: %{y:.2f}%<extra></extra>",
            ))
            fig_ret.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
            fig_ret.update_layout(
                template="plotly_dark", height=320,
                title=dict(text="누적 수익률 추이", y=0.97, x=0.5, xanchor="center"),
                yaxis_title="수익률(%)",
                legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
                margin=dict(t=40, l=8, r=8, b=70),
            )
            st.plotly_chart(fig_ret, use_container_width=True)

        # 벤치마크 비교
        try:
            bench_df = build_benchmark_return_df(monthly_perf_df)
        except Exception:
            bench_df = pd.DataFrame()

        if bench_df is not None and not bench_df.empty and "month_label" in bench_df.columns:
            st.markdown("#### 벤치마크 비교")
            color_map = {
                "내 기간수익률": "#ef4444",
                "S&P500": "#22d3ee",
                "나스닥100": "#f59e0b",
                "KODEX200": "#a78bfa",
            }
            fig_bench = go.Figure()
            for label in bench_df["구분"].drop_duplicates():
                part = bench_df[bench_df["구분"] == label]
                if part.empty:
                    continue
                fig_bench.add_trace(go.Scatter(
                    x=part["month_label"], y=part["수익률_pct"],
                    mode="lines+markers", name=label,
                    line=dict(
                        color=color_map.get(label, "#cbd5e1"),
                        width=3 if label == "내 기간수익률" else 2,
                        dash="solid" if label == "내 기간수익률" else "dot",
                    ),
                    hovertemplate=f"%{{x}}<br>{label}: %{{y:.2f}}%<extra></extra>",
                ))
            fig_bench.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
            fig_bench.update_layout(
                template="plotly_dark", height=320,
                title=dict(text="첫 기록월 대비 수익률 변화 vs 벤치마크", y=0.97, x=0.5, xanchor="center"),
                yaxis_title="수익률(%)",
                legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
                margin=dict(t=40, l=8, r=8, b=70),
            )
            st.plotly_chart(fig_bench, use_container_width=True)
    else:
        st.info("월별 성과 기록이 없습니다.")


if st.session_state.get("print_mode_toggle_final", False):
    render_print_report_v2()
    st.stop()

if st.session_state.get("full_print_mode", False):
    render_full_print_report()
    st.stop()


if IS_PUBLIC_DEMO:
    render_public_demo_fast_shell(
        effective_settings,
        holdings_df,
        holdings_table,
        dividends_df,
        monthly_logs_df,
        portfolio_summary,
        krw_cash,
        usd_cash,
        usdkrw,
        reserve_target_weight,
    )
    st.stop()

MAIN_PAGE_OPTIONS = {
    "asset": "💼 자산 현황",
    "today": "✅ 오늘 점검",
    "portfolio": "📊 포트폴리오 분석",
    "dashboard": "📋 전광판",
    "precision": "🔍 정밀관측소",
    "scenario": "📉 시나리오 점검",
    "short": "📈 단기 흐름 점검",
    "backtest": "🧪 신호 검증",
    "money": "💸 돈흐름 레이더",
    "kr_etf": "💰 월배당 ETF",
    "feedback": "🎤 피드백/Q&A",
    "data": "🧪 데이터 점검",
    "speed": "⏱ 속도 점검",
    "manual": "📘 판정 매뉴얼",
    "guide": "📖 사용 가이드",
}
main_page = st.sidebar.radio(
    "화면 이동",
    list(MAIN_PAGE_OPTIONS.keys()),
    format_func=lambda key: MAIN_PAGE_OPTIONS[key],
    key="main_page_nav",
)
st.caption(f"현재 화면: {MAIN_PAGE_OPTIONS[main_page]}")
if main_page == "dashboard":
    st.subheader("CCTV 통합 통제실")
    render_data_basis_caption("전광판", include_fin=True)
    st.write(
        f"현재자산: {portfolio_summary['current_asset']:,.0f}원 | "
        f"누적손익: {portfolio_summary['cum_profit']:,.0f}원 | "
        f"누적수익률: {portfolio_summary['cum_return']:.2f}% | "
        f"누적배당금: {portfolio_summary['total_dividend']:,.0f}원"
    )
    st.caption("전광판 등록 종목만 표시됩니다.")

    # ── 전광판 일괄 제거 ──────────────────────────────────────────────
    if st.session_state.watchlist:
        _wl_label_to_ticker = {
            f"{sanitize_asset_name(item.get('name', ''), item.get('ticker', ''))}  ({sanitize_ticker_value(item.get('ticker', ''))})": sanitize_ticker_value(item.get("ticker", ""))
            for item in st.session_state.watchlist
        }
        _rm_col, _rm_btn_col = st.columns([3.5, 1])
        with _rm_col:
            remove_targets = st.multiselect(
                "전광판에서 제거할 종목 선택 (복수 선택 가능)",
                options=list(_wl_label_to_ticker.keys()),
                key="remove_watchlist_multiselect",
                placeholder="제거할 종목을 선택하세요...",
            )
        with _rm_btn_col:
            st.write("")
            st.write("")
            if remove_targets:
                if st.button(
                    f"🗑 선택 {len(remove_targets)}개 제거",
                    key="remove_watchlist_btn",
                    use_container_width=True,
                    type="primary",
                ):
                    tickers_to_remove = {
                        normalize_ticker(_wl_label_to_ticker[lbl])
                        for lbl in remove_targets
                        if lbl in _wl_label_to_ticker
                    }
                    st.session_state.watchlist = [
                        item for item in st.session_state.watchlist
                        if normalize_ticker(item["ticker"]) not in tickers_to_remove
                    ]
                    persist_watchlist()
                    sync_watchlist_to_query()
                    st.rerun()
            else:
                st.button("제거", key="remove_watchlist_btn", use_container_width=True, disabled=True)

    # ── 전광판 일괄 재계산 ───────────────────────────────────────────
    with st.expander("🔄 일괄 재계산 (재무 + 기술)", expanded=False):
        st.caption(
            "전광판 등록 종목의 재무점수(개별주만)와 기술신호를 모두 새로 계산합니다. "
            "종목 수에 따라 수십 초~수 분 소요될 수 있습니다. 필요할 때만 실행하세요."
        )
        _stock_items = [
            item for item in st.session_state.watchlist
            if not is_fin_score_exempt_asset(
                sanitize_ticker_value(item.get("ticker", "")),
                item.get("is_etf", False),
                item.get("asset_class", ""),
                item.get("name", ""),
            )
        ]
        _etf_items = [
            item for item in st.session_state.watchlist
            if is_fin_score_exempt_asset(
                sanitize_ticker_value(item.get("ticker", "")),
                item.get("is_etf", False),
                item.get("asset_class", ""),
                item.get("name", ""),
            )
        ]
        st.caption(
            f"대상: 개별주 {len(_stock_items)}개 (재무 재계산) · ETF {len(_etf_items)}개 (기술만 새로고침)"
        )
        if st.button(
            "▶ 일괄 재계산 실행",
            key="dashboard_bulk_recalc_btn",
            use_container_width=True,
            type="primary",
        ):
            # 1) 기술 캐시 비우기
            clear_price_and_chart_cache()
            clear_financial_api_cache()

            # 2) 개별주 재무 재계산 (순차 — API rate limit 고려)
            if _stock_items:
                prog = st.progress(0, text="재무 재계산 중...")
                ok_list, fail_list = [], []
                for idx, item in enumerate(_stock_items, 1):
                    tkr = sanitize_ticker_value(item.get("ticker", ""))
                    name = sanitize_asset_name(item.get("name", ""), tkr)
                    a_class = item.get("asset_class", "")
                    try:
                        get_final_fin_score(tkr, False, a_class)
                        ok_list.append(name or tkr)
                    except Exception as e:
                        fail_list.append(f"{name or tkr} ({e})")
                    prog.progress(
                        idx / len(_stock_items),
                        text=f"재무 재계산 중... {idx}/{len(_stock_items)} — {name or tkr}",
                    )
                prog.empty()
                if ok_list:
                    st.success(f"재무 재계산 완료 ({len(ok_list)}개): {', '.join(ok_list)}")
                if fail_list:
                    st.warning(f"재무 조회 실패 ({len(fail_list)}개): {', '.join(fail_list)}")
            else:
                st.info("재무 재계산 대상 개별주가 없습니다 (ETF만 등록됨).")

            st.success("기술신호 캐시를 비웠습니다. 아래 전광판이 자동으로 재계산됩니다.")
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
                        st.success("정밀관측소 선택값을 바꿨습니다. 왼쪽 사이드바에서 정밀관측소 화면을 열어 확인하세요.")
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

if main_page == "precision":
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
                with st.spinner("DART/FMP/SEC 재무 자동 계산 중..."):
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
                {"항목": "source", "값": str(fin_meta.get("source") or "-")},
                {"항목": "mode", "값": str(fin_meta.get("mode") or "-")},
                {"항목": "auto_score", "값": str(fin_meta.get("auto_score") or "-")},
                {"항목": "manual_score", "값": str(fin_meta.get("manual_score") or "-")},
                {"항목": "final_score", "값": str(fin_meta.get("final_score") or "-")},
            ]
            st.dataframe(pd.DataFrame(meta_rows), use_container_width=True, hide_index=True)

            if weighted:
                weighted_rows = [
                    {"항목": "weighted score", "값": str(weighted.get("weighted_net_score") or "-")},
                    {"항목": "S_sum", "값": str(weighted.get("s_sum") or "-")},
                    {"항목": "A_sum", "값": str(weighted.get("a_sum") or "-")},
                    {"항목": "B_sum", "값": str(weighted.get("b_sum") or "-")},
                    {"항목": "danger_count", "값": str(weighted.get("danger_count") or "-")},
                    {"항목": "범용판단", "값": str(weighted.get("generic_score") or "-")},
                    {"항목": "수주판단", "값": str(weighted.get("order_score") or "-")},
                    {"항목": "중간형판단", "값": str(weighted.get("middle_score") or "-")},
                    {"항목": "selected_mode", "값": str(weighted.get("selected_mode") or "-")},
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
                dca_html = ""
                if clean_float(c.get("core_dca_rate"), 0.0) > 0:
                    dca_html = (
                        "<hr style='margin:8px 0; border-color:#334155;'>"
                        f"코어 적립안: <b>{escape_html_value(c.get('core_dca_label', ''))}</b><br>"
                        f"참고금액: <b>{clean_float(c.get('core_dca_amt'), 0.0):,.0f}원</b><br>"
                        f"재원: {escape_html_value(c.get('core_dca_pool_label', '예수금'))} "
                        f"{clean_float(c.get('core_dca_pool'), 0.0):,.0f}원"
                    )
                # ── 달러 표시 + 매수 주수 계산 ──────────────────────────
                _buy_amt_krw = clean_float(c.get("buy_amt"), 0.0)
                _cur_p = clean_float(display_cur_p, 0.0)
                _fx = clean_float(usdkrw, 1400.0)
                _is_us = not tkr.upper().endswith((".KS", ".KQ"))
                if _is_us:
                    _buy_usd = _buy_amt_krw / _fx if _fx > 0 else 0.0
                    _buy_display = f"${_buy_usd:,.0f} (≈{_buy_amt_krw:,.0f}원)"
                    _shares = _buy_usd / _cur_p if _cur_p > 0 else 0.0
                    _shares_txt = f"약 {_shares:.2f}주" if _shares > 0 else "-"
                else:
                    _buy_display = f"{_buy_amt_krw:,.0f}원"
                    _shares = _buy_amt_krw / _cur_p if _cur_p > 0 else 0.0
                    _shares_txt = f"약 {_shares:.2f}주" if _shares > 0 else "-"
                st.markdown(
                    f"<div class='info-panel'><b>비중</b><br>"
                    f"목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>"
                    f"부족 매수액: <b>{_buy_display}</b><br>"
                    f"현재가({format_currency(_cur_p, tkr)}) 기준 <b>{_shares_txt}</b>"
                    f"{dca_html}</div>",
                    unsafe_allow_html=True,
                )
                _sizing = c.get("sizing_hint", "")
                if _sizing:
                    st.markdown(
                        f"<div class='info-panel' style='border-left:4px solid #7c3aed;'>"
                        f"🎯 <b>포지션 사이징</b><br><span style='color:#c4b5fd'>{escape_html_value(_sizing)}</span></div>",
                        unsafe_allow_html=True,
                    )

                _reasons = c.get("decision_reasons", ())
                if _reasons:
                    with st.expander("🔍 판단근거 보기", expanded=False):
                        for _r in _reasons:
                            st.caption(f"• {_r}")

            if app_mode == "범용모드":
                dca_html = ""
                if clean_float(c.get("core_dca_rate"), 0.0) > 0:
                    dca_html = (
                        "<hr style='margin:8px 0; border-color:#334155;'>"
                        f"코어 적립안: <b>{escape_html_value(c.get('core_dca_label', ''))}</b><br>"
                        f"참고금액: <b>{clean_float(c.get('core_dca_amt'), 0.0):,.0f}원</b>"
                    )
                # ── 달러 표시 + 매수 주수 계산 ──────────────────────────
                _buy_amt_krw = clean_float(c.get("buy_amt"), 0.0)
                _cur_p = clean_float(display_cur_p, 0.0)
                _fx = clean_float(usdkrw, 1400.0)
                _is_us = not tkr.upper().endswith((".KS", ".KQ"))
                if _is_us:
                    _buy_usd = _buy_amt_krw / _fx if _fx > 0 else 0.0
                    _buy_display = f"${_buy_usd:,.0f} (≈{_buy_amt_krw:,.0f}원)"
                    _shares = _buy_usd / _cur_p if _cur_p > 0 else 0.0
                    _shares_txt = f"약 {_shares:.2f}주" if _shares > 0 else "-"
                else:
                    _buy_display = f"{_buy_amt_krw:,.0f}원"
                    _shares = _buy_amt_krw / _cur_p if _cur_p > 0 else 0.0
                    _shares_txt = f"약 {_shares:.2f}주" if _shares > 0 else "-"
                st.markdown(
                    f"<div class='info-panel'><b>입력 기준</b><br>"
                    f"총 자산: {u_asset:,.0f}원 | 평단가: {format_currency(u_price, tkr)}<br>"
                    f"목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>"
                    f"부족 매수액: <b>{_buy_display}</b><br>"
                    f"현재가({format_currency(_cur_p, tkr)}) 기준 <b>{_shares_txt}</b>"
                    f"{dca_html}</div>",
                    unsafe_allow_html=True,
                )

            st.markdown(f'<div class="signal-box" style="background-color: {c["col"]};"><div style="font-size: 1.5em;">{c["dec"]}</div><div class="score-detail">Adj: {c["adj"]:.1f}점</div></div>', unsafe_allow_html=True)

            fin_text = "해당없음" if is_etf else f"{c['fin_score']}/4"
            st.markdown(
                f"<div class='info-panel' style='border-left: 5px solid #8b5cf6;'><b>📌 후보 등급 판정</b><br>"
                f"<span class='highlight' style='font-size:1.1em;'>{c['grade']}</span> (총점: {c['t_score']}점)<br>"
                f"└ 🛠️기술: {c['tech_total']} (RS:{c['rs_s']} {c['rs_slope_label']}, MFI:{c['mfi_s']}, 추세:{c['trend_s']}, MACD:{c['macd_s']}, SQZ:{c['sqz_s']}) Adj보정:{c['rs_slope_s']:+d}<br>"
                f"└ 💰재무: {fin_text}</div>", unsafe_allow_html=True
            )

        with R:
            p_line = u_price if app_mode == "범용모드" else my_p
            _show_avg = p_line > 0 and (
                (app_mode == "범용모드" and c['current_w'] > 0)
                or (app_mode == "개인모드" and not is_free and has_p)
            )
            _lwc_rendered = render_lwc_candlestick(
                df,
                avg_price=p_line if _show_avg else 0.0,
                key=f"lwc_candle_{tkr}",
            )
            if not _lwc_rendered:
                # LWC 미설치 시 Plotly fallback
                fig = go.Figure(data=[go.Candlestick(
                    x=df.index, open=df["Open"], high=df["High"],
                    low=df["Low"], close=df["Close"], name="Price",
                )])
                fig.add_trace(go.Scatter(x=df.index, y=df["MA5"],   line=dict(color="#22c55e", width=1.4), name="MA5"))
                fig.add_trace(go.Scatter(x=df.index, y=df["MA20"],  line=dict(color="#fbbf24", width=2),   name="MA20"))
                fig.add_trace(go.Scatter(x=df.index, y=df["MA50"],  line=dict(color="#60a5fa", width=1.6), name="MA50"))
                fig.add_trace(go.Scatter(x=df.index, y=df["MA120"], line=dict(color="#94a3b8", width=1.5, dash="dot"), name="MA120"))
                if _show_avg:
                    fig.add_hline(y=p_line, line_dash="dash", line_color="#2ecc71", annotation_text="내 평단가")
                fig.update_layout(
                    template="plotly_dark", height=600,
                    xaxis_rangeslider_visible=False,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown(
                build_precision_narrative(name, tkr, c, fin_score, has_p, my_p),
                unsafe_allow_html=True,
            )

        st.markdown("---")
        b1, b2 = st.columns(2)
        with b1: 
            f_txt = f"{c['fvg_type']} | {'미충족' if c['fvg_active'] else '터치됨'}" if c['fvg_type'] != "없음" else "없음"
            _rr_str = f"{c['rr_ratio']:.2f} (목표 {format_currency(c['rr_target'], tkr)} / 손절 {format_currency(c['rr_stop'], tkr)})" if c.get('rr_ratio') else "산출불가"
            _sf_str = c.get('sector_flow_state', '-')
            _bk_badge = " <span style='color:#a78bfa;'>🚀52주 돌파</span>" if c.get('is_52w_breakout') else ""
            st.markdown(f"<div class='info-panel' style='border-left: 5px solid #e67e22;'><b>🛡️ SMC 구조 해석</b><br>• 외부구조: <b>{c['ext_structure']}</b><br>• 내부구조: <b>{c['int_structure']}</b><br>• 내부 이벤트: <b>{c['int_event']}</b><br>• 외부 이벤트: <b>{c['ext_event']}</b><br>• 유동성 상태: <b>{c['liq_state']}</b><br>• FVG 상태: <b>{f_txt}</b><br>• P/D Zone: <b>{c['pd_zone']}</b><br>• 실시간 MACD: <b>{c['rt_macd']}</b><br>• SQZ: <b>{c['sqz']}</b><br>• R/R 비율: <b>{_rr_str}</b><br>• 섹터 머니플로우: <b>{_sf_str}</b>{_bk_badge}<hr style='margin:10px 0; border-color:#334155;'>🎯 <b>실행 해석:</b> {c['smc_action']}</div>", unsafe_allow_html=True)
        with b2: 
            structure_note = "주의" if c.get("structure_risk") else "정상"
            structure_color = "#fbbf24" if c.get("structure_risk") else "#10b981"
            st.markdown(f"<div class='info-panel' style='border-left: 5px solid #10b981;'><b>📐 전술 지표</b><br>• 추세: <b>{c['trend']}</b> | MACD: <b>{c['macd']}</b><br>• RS: <b>{c['rs_label']}</b> | RSI: <b>{c['rsi']:.1f}</b> | MFI: <b>{c['mfi']:.1f}</b><br>• 볼린저 %B: <b>{c['pct_b']:.2f}</b> | SQZ: <b>{c['sqz']}</b><br>• 전일등락: <b>{c['day_ret']*100:.1f}%</b> | 거래량20일비: <b>{c['vol_ratio']:.1f}x</b> | 구조위험: <b style='color:{structure_color};'>{structure_note}</b><hr style='margin:10px 0; border-color:#334155;'><span class='smc-tag'>MA5</span> {format_currency(c['ma5'], tkr)}<br><span class='smc-tag'>MA20</span> {format_currency(c['ma20'], tkr)}<br><span class='smc-tag'>MA50</span> {format_currency(c['ma50'], tkr)}<br><span class='smc-tag'>MA120</span> {format_currency(c['ma120'], tkr)}<hr style='margin:10px 0; border-color:#334155;'>💡 <b>보조 해석:</b> {c['smc_insight']}</div>", unsafe_allow_html=True)

        render_personal_stock_analysis_panel(name, tkr, is_etf, a_class, c, fin_score, fin_meta, has_p, my_p)

        render_valuation_price_panel(name, tkr, is_etf, c, fin_score)

        render_pre_buy_final_check_panel(name, tkr, is_etf, c, fin_score, has_p, my_p)
        render_hold_or_cut_panel(name, tkr, is_etf, fin_score, fin_meta, c, my_p, has_p)
           
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

if main_page == "asset":
    st.subheader("앱 내부 자산 관리")
    render_data_basis_caption("자산관리", include_fin=True)
    render_asset_overview_dashboard(holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw, reserve_target_weight)
    render_asset_quick_quality_summary(effective_settings, holdings_df, dividends_df, monthly_logs_df)
    render_monthly_record_status(monthly_logs_df, portfolio_summary)
    render_dart_disclosure_panel(holdings_table)

    # ── 인쇄 리포트 버튼 ─────────────────────────────────────────────────
    _pr1, _pr2, _pr3 = st.columns([2, 2, 4])
    if _pr1.button("🖨️ 자산 현황 리포트", use_container_width=True, key="btn_full_print_mode"):
        st.session_state["full_print_mode"] = True
        st.rerun()
    if _pr2.button("🖨️ 종합 리포트 (운용계획 포함)", use_container_width=True, key="btn_print_mode_v2"):
        st.session_state["print_mode_toggle_final"] = True
        st.rerun()

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
                st.warning("복구 실행 시 보유자산/배당/월별 로그/관심목록 등 저장 데이터가 업로드 데이터로 대체될 수 있습니다.")

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
            if save_settings_db(new_seed, new_krw, new_usd, new_fx, new_reserve_target):
                st.success("기본 설정 저장 완료")
                st.rerun()
    
        st.markdown("### 2) 보유 종목 관리")
        holdings_editor_df = load_holdings_db()
        if holdings_editor_df.empty: holdings_editor_df = pd.DataFrame(columns=["name", "ticker", "qty", "avg_price", "target_weight", "asset_class", "is_etf", "account_type"])
        if "bucket" not in holdings_editor_df.columns:
            holdings_editor_df["bucket"] = "core"
    
        holdings_editor_df["bucket"] = holdings_editor_df.apply(
            lambda r: infer_bucket(r.get("ticker", ""), r.get("bucket", "core")),
            axis=1
        )
        if "account_type" not in holdings_editor_df.columns: holdings_editor_df["account_type"] = "일반"
    
        st.caption("bucket: core=장기투자, swing=스윙후보, reserve=비상대기/파킹. 원화/달러 예수금은 자동 cash 처리됩니다.")
            
        edited_holdings = st.data_editor(
            holdings_editor_df,
            num_rows="dynamic",
            use_container_width=True,
            key="holdings_editor",
            column_config={
                "owner_email": None,
                # ── 소수점 입력 보장: 명시적 NumberColumn ──────────────────────
                "qty": st.column_config.NumberColumn(
                    "보유량",
                    min_value=0,
                    step=0.0001,
                    format="%.4f",
                    help="소수점 입력 가능 (예: 1.5, 0.001)",
                ),
                "avg_price": st.column_config.NumberColumn(
                    "매입가",
                    min_value=0,
                    step=0.01,
                    format="%.4f",
                    help="소수점 입력 가능 (예: 79500.5)",
                ),
                "target_weight": st.column_config.NumberColumn(
                    "목표비중(%)",
                    min_value=0,
                    max_value=100,
                    step=0.5,
                    format="%.1f",
                ),
                # ──────────────────────────────────────────────────────────────
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
                    options=["core", "leverage", "swing", "reserve"],
                    help="core=장기적립 / leverage=레버리지ETF(QLD·TQQQ 등, 타점+하락감지 배율 적용) / swing=스윙후보 / reserve=파킹자산"
                ),
                "account_type": st.column_config.SelectboxColumn(
                    "계좌 종류",
                    options=["일반", "ISA", "연금저축", "IRP"],
                    help="세금 혜택 계좌를 구분합니다."
                )
            }
        )
    
        if st.button("보유 종목 저장"):
            if save_holdings_db(edited_holdings.fillna("")):
                st.success("보유 종목 저장 완료")
                # 에디터 세션 상태 초기화 — 동일 티커 다계좌 편집 시
                # Streamlit 내부 인덱스 불일치로 행이 잘못 병합되는 문제 방지
                if "holdings_editor" in st.session_state:
                    del st.session_state["holdings_editor"]
                st.rerun()
    
        st.markdown("### 3) 배당 내역 관리")
        dividends_editor_df = load_dividends_db()
        if dividends_editor_df.empty: dividends_editor_df = pd.DataFrame(columns=DIVIDENDS_COLUMNS)
        for col in DIVIDENDS_COLUMNS:
            if col not in dividends_editor_df.columns:
                dividends_editor_df[col] = ""
        dividends_editor_df = dividends_editor_df[DIVIDENDS_COLUMNS]
        edited_dividends = st.data_editor(
            dividends_editor_df,
            num_rows="dynamic",
            use_container_width=True,
            key="dividends_editor",
            column_order=["date", "ticker", "amount", "currency", "id"],
            disabled=["id"],
            column_config={
                "id": st.column_config.TextColumn(
                    "ID",
                    help="DB 내부 ID입니다. 기존 배당 수정/삭제를 안전하게 구분하기 위해 자동 관리합니다.",
                ),
                "amount": st.column_config.NumberColumn(
                    "amount",
                    min_value=0.0,
                    step=1.0,
                ),
                "currency": st.column_config.SelectboxColumn(
                    "currency",
                    options=["KRW", "USD"],
                ),
            },
        )
    
        if st.button("배당 내역 저장"):
            if save_dividends_db(edited_dividends.fillna("")):
                if "dividends_editor" in st.session_state:
                    del st.session_state["dividends_editor"]
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


        def _dash_pnl_krw(r):
            ticker = str(r["티커"]).upper()
            code = ticker.replace(".KS", "").replace(".KQ", "")
            is_kr = (
                ticker.endswith((".KS", ".KQ"))
                or "CASH" in ticker
                or (len(code) == 6 and code[0].isdigit() and code.isalnum())
            )
            return r["평가손익"] if is_kr else r["평가손익"] * usdkrw
        dash_df["평가손익_원화"] = dash_df.apply(_dash_pnl_krw, axis=1)
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
            # 리밸런싱 계산기 등 다른 UI 위치에서 신호를 읽을 수 있도록 session_state에 캐시
            st.session_state["_ticker_signal_cache"] = {
                str(row["티커"]): str(row["기술적타점"])
                for _, row in signal_df.iterrows()
            }
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

        # ── 리밸런싱 계산기: 신호 캐시(_ticker_signal_cache) 저장 이후 렌더링 ──
        # 이 위치에서는 _ticker_signal_cache가 이미 갱신된 상태이므로
        # "분석 실행" 클릭과 동일한 렌더 사이클에서 최신 신호가 반영됩니다.
        render_monthly_rebalancing_calculator(
            holdings_table, usdkrw, portfolio_summary, monthly_logs_df=monthly_logs_df
        )

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
            "자산명", "티커", "보유량", "매입가", "손익분기점", "본전까지%", "현재가", "평가금액", "평가손익",
            "평가손익_원화", "수익률_pct", "원화환산", "목표비중", "현재비중", "비중차이",
            "기술적타점", "ADJ점수", "후보등급", "추세", "RS", "RSI", "MFI", "MACD", "SQZ", "bucket", "운용대상", "리밸런싱목표비중"
        ]
        _summary_display_cols = [c for c in show_cols if c in dash_df.columns]
        _summary_edit_df = dash_df[_summary_display_cols].copy()

        # 편집 불가 컬럼: 보유량/매입가를 제외한 전체
        _readonly_cols = [c for c in _summary_display_cols if c not in ("보유량", "매입가")]
        # 예수금 행(티커가 KRW_CASH/USD_CASH)은 보유량/매입가도 읽기전용 처리를 위해 표시만 분리
        _cash_mask = _summary_edit_df["티커"].isin(["KRW_CASH", "USD_CASH"]) if "티커" in _summary_edit_df.columns else pd.Series([False] * len(_summary_edit_df))

        st.caption("✏️ 보유량·매입가 셀을 직접 클릭해 수정할 수 있습니다. 예수금 행은 기본 설정에서 변경하세요.")
        _edited_summary = st.data_editor(
            _summary_edit_df,
            use_container_width=True,
            hide_index=True,
            key="asset_summary_inline_editor",
            disabled=_readonly_cols,
            column_config={
                "보유량": st.column_config.NumberColumn(
                    "보유량",
                    min_value=0,
                    step=0.0001,
                    format="%.4f",
                    help="소수점 입력 가능. 예수금 행은 기본 설정에서 변경하세요.",
                ),
                "매입가": st.column_config.NumberColumn(
                    "매입가",
                    min_value=0,
                    step=0.01,
                    format="%.4f",
                    help="소수점 입력 가능. 예수금 행은 기본 설정에서 변경하세요.",
                ),
                "수익률_pct": st.column_config.NumberColumn("수익률(%)", format="%.2f"),
                "ADJ점수": st.column_config.TextColumn("ADJ점수"),
            },
        )

        if st.button("보유량·매입가 변경사항 저장", key="save_inline_qty_price"):
            _holdings_raw = load_holdings_db()
            _changed = False
            if not _holdings_raw.empty and "티커" in _edited_summary.columns:
                for _, _erow in _edited_summary.iterrows():
                    _tkr = str(_erow.get("티커", "")).strip()
                    if _tkr in ("KRW_CASH", "USD_CASH", ""):
                        continue
                    _new_qty = clean_float(_erow.get("보유량"), None)
                    _new_price = clean_float(_erow.get("매입가"), None)
                    _mask = _holdings_raw["ticker"] == _tkr
                    if _mask.any():
                        if _new_qty is not None and _new_qty >= 0:
                            _holdings_raw.loc[_mask, "qty"] = _new_qty
                            _changed = True
                        if _new_price is not None and _new_price >= 0:
                            _holdings_raw.loc[_mask, "avg_price"] = _new_price
                            _changed = True
            if _changed:
                if save_holdings_db(_holdings_raw.fillna("")):
                    st.success("보유량·매입가 저장 완료 — 입력/수정 영역에도 반영됩니다.")
                    st.rerun()
            else:
                st.info("변경된 내용이 없습니다.")

        # --- 1. 메인 대시보드 엑셀 다운로드 버튼 추가 ---
        # (io는 파일 상단에서 이미 import됨 - 중복 제거)
        output = io.BytesIO()
        # xlsxwriter 엔진을 사용하여 한글 깨짐을 원천 봉쇄합니다.
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            dash_df.to_excel(writer, index=False, sheet_name='Main_Dashboard')
        
        st.download_button(
            label="📥 엑셀 다운로드 (한글 깨짐 방지용)",
            data=output.getvalue(),
            file_name=f"stock_lab_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    else:
        st.info("등록된 보유 종목이 없습니다.")

if main_page == "portfolio":
    render_portfolio_analysis_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight, monthly_logs_df)

if main_page == "scenario":
    render_scenario_check_tab(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight)

if main_page == "short":
    render_short_trend_tab(holdings_table, st.session_state.watchlist)

if main_page == "backtest":
    render_signal_backtest_tab(holdings_table, st.session_state.watchlist)

if main_page == "money":
    render_money_flow_tab()

if main_page == "kr_etf":
    render_kr_etf_lab_tab()

if main_page == "today":
    render_today_queue_tab(app_mode)

if main_page == "feedback":
    render_feedback_tab()

if main_page == "data":
    render_data_quality_tab(effective_settings, holdings_df, holdings_table, dividends_df, monthly_logs_df, st.session_state.watchlist)

if main_page == "speed":
    render_speed_check_tab()

if main_page == "manual":
    render_manual_tab() 

if main_page == "guide":
    render_user_guide_tab()


# ════════════════════════════════════════════════════════════════════════════
