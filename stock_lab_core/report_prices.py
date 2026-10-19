"""Session-aligned report prices and same-day comparisons, not causal claims."""

import math
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
import pandas as pd
from stock_lab_core.report_evidence import closed_daily_frame
from stock_lab_core.result_cache import cache_result

MACRO_SYMBOLS = {"10Y 금리": "^TNX", "유가": "CL=F", "환율": "USDKRW=X", "VIX": "^VIX", "MOVE": "^MOVE"}
SECTORS = {"XLK": "기술", "XLC": "통신", "XLE": "에너지", "XLU": "유틸리티", "SOXX": "반도체", "DRAM": "메모리", "IGV": "소프트웨어", "305540.KS": "2차전지", "139250.KS": "에너지", "396500.KS": "한국 반도체"}


def btc_at_us_close(frame, current_date, previous_date):
    from zoneinfo import ZoneInfo
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        return {}
    frame = frame.sort_index()
    points = []
    for day in (previous_date, current_date):
        cutoff = pd.Timestamp(day + " 16:00", tz=ZoneInfo("America/New_York"))
        # Yahoo timestamps mark bar starts; the 5-minute close arrives at +5m.
        eligible = frame.loc[(frame.index + pd.Timedelta(minutes=5) <= cutoff) &
                             (frame.index + pd.Timedelta(minutes=5) >= cutoff - pd.Timedelta(minutes=5))]
        if eligible.empty:
            return {}
        value = pd.to_numeric(eligible["Close"], errors="coerce").iloc[-1]
        if not pd.notna(value) or not math.isfinite(value) or value <= 0:
            return {}
        points.append(float(value))
    return {"date": current_date, "previous_date": previous_date, "return": points[1] / points[0] - 1,
            "source": "Yahoo BTC 5분봉, NY 16:00 마감 시점", "price": points[1]}


@cache_result(ttl=900, failure_ttl=30, is_success=lambda frame: not frame.empty)
def load_btc_close_frame():
    import requests
    try:
        with requests.get("https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD",
                          params={"range": "1mo", "interval": "5m"}, timeout=4,
                          headers={"User-Agent": "Mozilla/5.0"}) as response:
            response.raise_for_status()
            result = response.json()["chart"]["result"][0]
        return pd.DataFrame({"Close": result["indicators"]["quote"][0]["close"]},
                            index=pd.to_datetime(result["timestamp"], unit="s", utc=True))
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return pd.DataFrame()


def aligned_macro(frames, reference_date, now):
    result = {}
    for name, ticker in MACRO_SYMBOLS.items():
        frame = closed_daily_frame(frames.get(ticker), ticker, now)
        if not reference_date:
            continue
        frame = frame.loc[frame.index.strftime("%Y-%m-%d") <= reference_date] if not frame.empty else frame
        if frame.empty or str(frame.index[-1].date()) != reference_date:
            continue
        close = frame["Close"].astype(float)
        result[name] = {"val": float(close.iloc[-1]), "as_of": reference_date,
                        "symbol": ticker, "retrieved_at": now.isoformat(),
                        "source": "Yahoo Finance daily (거래일 정렬)",
                        "chg": float(close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) >= 22 else None,
                        "base_date": str(close.index[-22].date()) if len(close) >= 22 else "",
                        "day_ret": float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else None,
                        "day_change_bp": float(close.iloc[-1] - close.iloc[-2]) * 100 if len(close) >= 2 and name == "10Y 금리" else None}
    return result


def release_day_reaction(row, frames, now):
    at = row.get("release_at")
    if not at or row.get("actual") is None:
        return "발표일 미연결/미발표로 동일일 비교 보류"
    kr = str(row.get("indicator", "")).startswith("KR_")
    try:
        dt = pd.Timestamp(at)
    except (ValueError, TypeError, OverflowError):
        return "발표일 해석 불가로 동일일 비교 보류"
    if pd.isna(dt):
        return "발표일 미연결로 동일일 비교 보류"
    if dt.tzinfo is not None:
        dt = dt.tz_convert("Asia/Seoul" if kr else "America/New_York")
    day = str(dt.date())
    parts = []
    assets = (("코스피", "^KS11"), ("원/달러", "USDKRW=X")) if kr else (("10Y", "^TNX"), ("원/달러", "USDKRW=X"), ("나스닥", "^IXIC"))
    for label, ticker in assets:
        frame = closed_daily_frame(frames.get(ticker), ticker, now)
        if not frame.empty:
            frame = frame.loc[frame.index.strftime("%Y-%m-%d") <= day]
        if len(frame) < 2 or str(frame.index[-1].date()) != day:
            parts.append(label + " 동일일 종가 없음")
            continue
        previous, current = frame["Close"].astype(float).iloc[-2:]
        value = (current - previous) * 100 if ticker == "^TNX" else (current / previous - 1) * 100
        parts.append(f"{label} {value:+.2f}" + ("bp" if ticker == "^TNX" else "%"))
    return day + " · " + ", ".join(parts) + " · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)"
