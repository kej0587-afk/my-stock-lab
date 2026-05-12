"""
stock_lab_core/ta_engine.py

순수 TA(기술 분석) 및 SMC(스마트 머니 컨셉) 헬퍼 함수 모음.
app.py 전역 상태에 의존하지 않는 순수 함수만 포함하므로 독립 테스트가 가능합니다.
"""

import numpy as np
import pandas as pd
import ta


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

def finite_num(x) -> bool:
    """NaN / inf / None이 아닌 유한 수치인지 확인합니다."""
    try:
        return x is not None and not pd.isna(x) and np.isfinite(float(x))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 기본 기술적 상태 판정
# ---------------------------------------------------------------------------

def get_sqz_status(last_sqz_on: bool, prev_sqz_on: bool) -> str:
    """볼린저-켈트너 스퀴즈 상태를 반환합니다."""
    if last_sqz_on and not prev_sqz_on:
        return "⏳재압축"
    elif last_sqz_on and prev_sqz_on:
        return "⏳압축중"
    elif (not last_sqz_on) and prev_sqz_on:
        return "🚀해제직후"
    return "➡️해제유지"


def get_macd_state(last_macd, last_sig, prev_macd, prev_sig) -> str:
    """MACD 크로스 상태를 반환합니다."""
    if last_macd > last_sig and prev_macd <= prev_sig:
        return "🔥매수신호(골든크로스)"
    elif last_macd > last_sig:
        return "📈추세유지(상승중)"
    elif last_macd < last_sig and prev_macd >= prev_sig:
        return "📉하락주의(데드크로스)"
    return "⏳추세관망"


# ---------------------------------------------------------------------------
# 지표 계산
# ---------------------------------------------------------------------------

def build_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame에 기술적 지표 컬럼을 추가하고 반환합니다."""
    df = df.copy()
    df["MA5"]   = df["Close"].rolling(5).mean()
    df["MA20"]  = df["Close"].rolling(20).mean()
    df["MA50"]  = df["Close"].rolling(50).mean()
    df["MA120"] = df["Close"].rolling(120).mean()
    df["RSI"]   = ta.momentum.RSIIndicator(df["Close"]).rsi()
    df["MFI"]   = ta.volume.MFIIndicator(df["High"], df["Low"], df["Close"], df["Volume"]).money_flow_index()
    macd        = ta.trend.MACD(df["Close"])
    df["MACD"]  = macd.macd()
    df["MACD_Sig"] = macd.macd_signal()
    bb          = ta.volatility.BollingerBands(df["Close"], 20, 2)
    df["%B"]    = (df["Close"] - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband())
    kc          = ta.volatility.KeltnerChannel(df["High"], df["Low"], df["Close"], 20, 20, 1.5)
    df["SQZ_ON"] = (
        (bb.bollinger_hband() < kc.keltner_channel_hband()) &
        (bb.bollinger_lband() > kc.keltner_channel_lband())
    )
    return df


def get_trend(last) -> str:
    """이동평균 배열로 추세를 판정합니다."""
    ma20  = last.get("MA20")
    ma50  = last.get("MA50")
    ma120 = last.get("MA120")
    if not finite_num(ma20) or not finite_num(ma50) or not finite_num(ma120):
        return "🆕신규상장/자료부족"
    if ma20 > ma50 > ma120:
        return "🚀정배열(상승)"
    if ma20 > ma50:
        return "⏳혼조세"
    return "🌊역배열(하락)"


# ---------------------------------------------------------------------------
# SMC(스마트 머니 컨셉) 헬퍼
# ---------------------------------------------------------------------------

def get_pivot_highs_lows(df: pd.DataFrame, l: int = 3, r: int = 3):
    """피벗 고점/저점 좌표 목록을 반환합니다."""
    highs, lows = [], []
    for i in range(l, len(df) - r):
        if df["High"].iloc[i] == df["High"].iloc[i - l: i + r + 1].max():
            highs.append((i, float(df["High"].iloc[i])))
        if df["Low"].iloc[i] == df["Low"].iloc[i - l: i + r + 1].min():
            lows.append((i, float(df["Low"].iloc[i])))
    return highs, lows


def get_recent_levels(df: pd.DataFrame) -> dict:
    """내부/외부 고점·저점을 담은 레벨 딕셔너리를 반환합니다."""
    ih, il = get_pivot_highs_lows(df, 3, 3)
    eh, el = get_pivot_highs_lows(df, 10, 10)
    return {
        "int_high": ih[-1][1] if ih else df["High"].tail(20).max(),
        "int_low":  il[-1][1] if il else df["Low"].tail(20).min(),
        "ext_high": eh[-1][1] if eh else df["High"].tail(120).max(),
        "ext_low":  el[-1][1] if el else df["Low"].tail(120).min(),
    }


def detect_structure_event(df: pd.DataFrame, levels: dict):
    """BoS / CHoCH 구조 이벤트를 감지합니다."""
    c_now  = float(df["Close"].iloc[-1])
    c_prev = float(df["Close"].iloc[-2])
    ie, ee = "None", "None"

    if c_prev <= levels["int_high"] < c_now:
        ie = "Bullish BoS"
    elif c_prev >= levels["int_low"] > c_now:
        ie = "Bearish BoS"

    if c_prev <= levels["ext_high"] < c_now:
        ee = "Bullish BoS"
    elif c_prev >= levels["ext_low"] > c_now:
        ee = "Bearish BoS"

    m20 = float(df["MA20"].iloc[-1])
    m50 = float(df["MA50"].iloc[-1])
    if not finite_num(m20) or not finite_num(m50):
        return ie, ee

    if "Bullish" in ee and m20 < m50:
        ee = "Bullish CHoCH"
    if "Bearish" in ee and m20 > m50:
        ee = "Bearish CHoCH"
    return ie, ee


def detect_liquidity_grab(df: pd.DataFrame, levels: dict, tol: float = 0.002) -> str:
    """유동성 청산 패턴을 감지합니다."""
    c = float(df["Close"].iloc[-1])
    h = float(df["High"].iloc[-1])
    l = float(df["Low"].iloc[-1])
    if h > levels["int_high"] * (1 + tol) and c < levels["int_high"]:
        return "상단 유동성 청산"
    if l < levels["int_low"] * (1 - tol) and c > levels["int_low"]:
        return "하단 유동성 청산"
    return "없음"


def detect_recent_fvg(df: pd.DataFrame) -> dict:
    """최근 FVG(공정가치갭)를 탐지합니다."""
    for i in range(len(df) - 1, 1, -1):
        h2 = float(df["High"].iloc[i - 2])
        l2 = float(df["Low"].iloc[i - 2])
        h0 = float(df["High"].iloc[i])
        l0 = float(df["Low"].iloc[i])
        if l0 > h2:
            return {"type": "Bullish FVG", "top": l0, "bottom": h2,
                    "active": float(df["Low"].iloc[-1]) > h2}
        if h0 < l2:
            return {"type": "Bearish FVG", "top": l2, "bottom": h0,
                    "active": float(df["High"].iloc[-1]) < l2}
    return {"type": "없음", "top": None, "bottom": None, "active": False}


def get_pd_zone(df: pd.DataFrame) -> str:
    """200일 이동평균 ±2σ 기준 Premium/Discount/Neutral 구간을 반환합니다."""
    c = float(df["Close"].iloc[-1])
    m = df["Close"].rolling(200).mean().iloc[-1]
    s = df["Close"].rolling(200).std().iloc[-1]
    if pd.isna(m):
        return "Neutral"
    if c >= m + 2 * s:
        return "Premium"
    if c <= m - 2 * s:
        return "Discount"
    return "Neutral"


def summarize_smc_action(ext: str, int_s: str, ie: str, ee: str,
                         liq: str, fvg: dict, pdz: str) -> str:
    """SMC 종합 액션 코멘트를 반환합니다."""
    if "CHoCH" in ee:
        return "구조적 반전 포착: 방향 재설정 필요"
    if liq == "상단 유동성 청산" and pdz == "Premium":
        return "상단 유동성 청산 후 조정 경계"
    if fvg["type"] == "Bullish FVG" and fvg["active"] and ext == "Bullish":
        return "상승 FVG 유지: 눌림 매수 유리"
    if ext == "Bullish":
        return "상승 추세 유지: 눌림 대기"
    return "구조 혼조: 관망"
