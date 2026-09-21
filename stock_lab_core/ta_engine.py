"""
stock_lab_core/ta_engine.py

순수 TA(기술 분석) 및 SMC(스마트 머니 컨셉) 헬퍼 함수 모음.
app.py 전역 상태에 의존하지 않는 순수 함수만 포함하므로 독립 테스트가 가능합니다.
"""

import numpy as np
import pandas as pd

try:
    import ta
except Exception:
    ta = None

try:
    from stock_lab_core.formatters import finite_num
except Exception:
    def finite_num(value) -> bool:
        try:
            return value is not None and not pd.isna(value) and np.isfinite(float(value))
        except Exception:
            return False


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 기본 기술적 상태 판정
# ---------------------------------------------------------------------------

def get_sqz_status(last_sqz_on: bool, prev_sqz_on: bool, recent_sqz_on=None, release_lookback: int = 6) -> str:
    """볼린저-켈트너 스퀴즈 상태를 반환합니다.

    기존에는 현재/직전 봉이 모두 비압축이면 전부 ``해제유지``로 표시했습니다.
    실제 최근 압축이 없었던 종목까지 해제유지로 보이면 오해가 생기므로,
    최근 구간 안에 압축 이력이 있을 때만 해제유지로 보고 그 외에는 비압축으로 구분합니다.
    """
    if last_sqz_on and not prev_sqz_on:
        return "⏳재압축"
    if last_sqz_on and prev_sqz_on:
        return "⏳압축중"
    if (not last_sqz_on) and prev_sqz_on:
        return "🚀해제직후"

    if recent_sqz_on is not None:
        vals = []
        for value in recent_sqz_on:
            try:
                vals.append(bool(value) and not pd.isna(value))
            except Exception:
                vals.append(bool(value))
        if len(vals) >= 3:
            prior_window = vals[max(0, len(vals) - release_lookback - 2):-2]
            return "➡️해제유지" if any(prior_window) else "➖비압축"
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
    if ta is None:
        raise RuntimeError("build_indicators requires the optional 'ta' package")
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


def _smc_ohlc_source(df: pd.DataFrame, lookback: int = 160) -> pd.DataFrame:
    """SMC 보조 탐지용 OHLC 소스를 정리합니다."""
    if df is None or df.empty:
        return pd.DataFrame()
    required = ["High", "Low", "Close"]
    if any(col not in df.columns for col in required):
        return pd.DataFrame()
    cols = ["Open", "High", "Low", "Close"]
    source = df.copy()
    if "Open" not in source.columns:
        source["Open"] = source["Close"]
    source = source[cols].tail(max(30, int(lookback))).copy()
    for col in cols:
        source[col] = pd.to_numeric(source[col], errors="coerce")
    return source.dropna(subset=cols)


def detect_equal_highs_lows(
    df: pd.DataFrame,
    lookback: int = 160,
    tolerance: float = 0.003,
) -> list:
    """최근 유사 고점/저점(EQH/EQL) 후보를 반환합니다.

    TradingView SMC류 지표의 개념을 앱에서 읽기 쉽게 쓰기 위한 독립 구현입니다.
    반환값은 확정 매수·매도 신호가 아니라 유동성이 몰릴 수 있는 레벨 후보입니다.
    """
    source = _smc_ohlc_source(df, lookback=lookback)
    if len(source) < 20:
        return []
    highs, lows = get_pivot_highs_lows(source, 3, 3)
    results = []

    def _find_equal_level(points, label, direction):
        recent = points[-8:]
        for idx in range(len(recent) - 1, 0, -1):
            pos, price = recent[idx]
            for prev_pos, prev_price in reversed(recent[:idx]):
                denom = max((abs(price) + abs(prev_price)) / 2, 1e-9)
                if abs(price - prev_price) / denom <= tolerance:
                    level = (price + prev_price) / 2
                    return {
                        "type": label,
                        "direction": direction,
                        "level": float(level),
                        "first_index": source.index[prev_pos],
                        "last_index": source.index[pos],
                        "touches": 2,
                    }
        return None

    eqh = _find_equal_level(highs, "EQH", "resistance")
    eql = _find_equal_level(lows, "EQL", "support")
    if eqh:
        results.append(eqh)
    if eql:
        results.append(eql)
    return results


def detect_order_block_zones(df: pd.DataFrame, lookback: int = 160) -> list:
    """최근 구조 돌파 전 캔들을 간이 Order Block 후보로 반환합니다.

    원본 Pine 로직을 복제하지 않고, 최근 박스권 돌파/이탈 직전 반대색 캔들을
    지지·저항 후보로 표시하는 보수적 보조 로직입니다.
    """
    source = _smc_ohlc_source(df, lookback=lookback)
    if len(source) < 25:
        return []

    latest_close = float(source["Close"].iloc[-1])
    latest_low = float(source["Low"].iloc[-1])
    latest_high = float(source["High"].iloc[-1])
    candidates = []

    for i in range(12, len(source)):
        prev = source.iloc[i - 12:i]
        breakout_high = float(prev["High"].max())
        breakdown_low = float(prev["Low"].min())
        close_i = float(source["Close"].iloc[i])

        if close_i > breakout_high:
            impulse = source.iloc[max(0, i - 8):i]
            bearish = impulse[impulse["Close"] < impulse["Open"]]
            if not bearish.empty:
                ob = bearish.iloc[-1]
                zone_low = float(ob["Low"])
                zone_high = float(max(ob["Open"], ob["Close"]))
                if zone_high > zone_low:
                    candidates.append({
                        "type": "Bullish OB",
                        "direction": "support",
                        "low": zone_low,
                        "high": zone_high,
                        "index": bearish.index[-1],
                        "active": latest_close >= zone_low and latest_low >= zone_low * 0.995,
                    })

        if close_i < breakdown_low:
            impulse = source.iloc[max(0, i - 8):i]
            bullish = impulse[impulse["Close"] > impulse["Open"]]
            if not bullish.empty:
                ob = bullish.iloc[-1]
                zone_low = float(min(ob["Open"], ob["Close"]))
                zone_high = float(ob["High"])
                if zone_high > zone_low:
                    candidates.append({
                        "type": "Bearish OB",
                        "direction": "resistance",
                        "low": zone_low,
                        "high": zone_high,
                        "index": bullish.index[-1],
                        "active": latest_close <= zone_high and latest_high <= zone_high * 1.005,
                    })

    unique = []
    seen = set()
    for zone in reversed(candidates):
        key = (zone["type"], round(zone["low"], 4), round(zone["high"], 4))
        if key in seen:
            continue
        unique.append(zone)
        seen.add(key)
        if len(unique) >= 3:
            break
    return list(reversed(unique))


def build_smc_overlay_features(df: pd.DataFrame) -> dict:
    """차트에 표시할 SMC 보조 레이어를 묶어서 반환합니다."""
    has_ohlc = df is not None and (not df.empty) and all(col in df.columns for col in ["High", "Low", "Close"])
    fvg = detect_recent_fvg(df) if has_ohlc else {"type": "없음", "active": False}
    return {
        "fvg": fvg,
        "order_blocks": detect_order_block_zones(df),
        "equal_levels": detect_equal_highs_lows(df),
    }


def detect_smc_features(df: pd.DataFrame) -> dict:
    """최근 캔들 기준 FVG와 단기 지지선을 요약합니다."""
    if len(df) < 5:
        return {"fvg_label": "데이터 부족", "ob_label": "데이터 부족"}

    recent_df = df.tail(20).copy()
    bullish_fvgs = []
    bearish_fvgs = []

    for i in range(2, len(recent_df)):
        c1_high = float(recent_df["High"].iloc[i - 2])
        c1_low = float(recent_df["Low"].iloc[i - 2])
        c3_high = float(recent_df["High"].iloc[i])
        c3_low = float(recent_df["Low"].iloc[i])

        if c1_high < c3_low:
            bullish_fvgs.append((c1_high, c3_low))
        if c1_low > c3_high:
            bearish_fvgs.append((c3_high, c1_low))

    fvg_label = "FVG 갭 없음 (균형 상태)"
    if bullish_fvgs:
        latest_bull = bullish_fvgs[-1]
        fvg_label = f"🔼 지지 갭(FVG): {latest_bull[0]:.2f} ~ {latest_bull[1]:.2f}"
    elif bearish_fvgs:
        latest_bear = bearish_fvgs[-1]
        fvg_label = f"🔽 저항 갭(FVG): {latest_bear[0]:.2f} ~ {latest_bear[1]:.2f}"

    min_idx = recent_df["Low"].idxmin()
    ob_low = float(recent_df.loc[min_idx, "Low"])
    ob_high = float(recent_df.loc[min_idx, "High"])
    ob_label = f"🛡️ 단기 지지선: {ob_low:.2f} ~ {ob_high:.2f}"

    return {
        "fvg_label": fvg_label,
        "ob_label": ob_label,
    }


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
