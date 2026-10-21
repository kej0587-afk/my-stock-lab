"""Session-aligned report prices and same-day comparisons, not causal claims."""

import math
import logging
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
import pandas as pd
from stock_lab_core.report_evidence import closed_daily_frame
from stock_lab_core.report_reference import REFERENCE_SYMBOLS, macro_reference
from stock_lab_core.result_cache import cache_result

MACRO_SYMBOLS = {"10Y 금리": "^TNX", "유가": "CL=F", "환율": "USDKRW=X", "VIX": "^VIX", "MOVE": "^MOVE"}
SECTORS = {"XLK": "기술", "XLC": "통신", "XLE": "에너지", "XLU": "유틸리티", "SOXX": "반도체", "DRAM": "메모리", "IGV": "소프트웨어", "305540.KS": "2차전지", "139250.KS": "에너지", "396500.KS": "한국 반도체"}


def align_us_report_frames(frames, tickers, now, *, reload_batch=None):
    """Retry lagging report histories once, without relabeling or filling prices.

    The newest observed index close is the reference, never a guessed calendar
    date. Both return endpoints must match before accepting the retry.
    """
    from stock_lab_core.report_evidence import price_observation

    result = dict(frames)
    indices = [price_observation(frames.get(t), t, now) for t in ("^GSPC", "^IXIC", "^DJI")]
    reference = max(indices, key=lambda row: (row["date"], row.get("previous_date", "")))
    expected = reference["date"]
    status = {"expected_date": expected, "requested": [], "refreshed": [], "unaligned": [], "missing": []}
    if not expected:
        return result, status
    symbols = sorted(t for t in tickers if not t.endswith((".KS", ".KQ", "=X", "=F", "-USD"))
                     and t not in {"^KS11", "^KQ11", *MACRO_SYMBOLS.values()})

    def aligned(frame, ticker):
        obs = price_observation(frame, ticker, now)
        return obs["date"] == expected and obs.get("previous_date") == reference.get("previous_date")

    lagging = [t for t in symbols if not aligned(frames.get(t), t)]
    if lagging and reload_batch is not None:
        status["requested"] = lagging
        try:
            fresh = reload_batch(tuple(lagging), "1y")
        except Exception as exc:
            logging.warning("Report-only US history retry failed (%s)", type(exc).__name__)
            fresh = {}
        for ticker in lagging:
            candidate = fresh.get(ticker) if isinstance(fresh, dict) else None
            if aligned(candidate, ticker):
                result[ticker] = candidate.copy(deep=True)
                status["refreshed"].append(ticker)
    for ticker in lagging:
        if not aligned(result.get(ticker), ticker):
            status["unaligned"].append(ticker)
            actual = price_observation(result.get(ticker), ticker, now)["date"] or "미수집"
            status["missing"].append(f"{ticker}: 미국 종가 기준일 {expected} 대비 {actual} · 수익률 비교일 미정합")
    return result, status


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


def aligned_macro(frames, reference_date, now, *, scenario_frames=None, cache_dir=None):
    """Use fixed NY 16:00 references for 24h assets, daily closes for indices.

    The collector must pass its Yahoo 5m scenario frames, including CL=F and
    USDKRW=X. No network call or untimed daily fallback is made here. Missing
    matching anchors omit returns, not substitute a different daily baseline.
    Surface each row's comparison_missing separately from its price source;
    stress_incomplete requires a partial/unavailable aggregate, not risk relief.
    """
    result = {}
    if not reference_date:
        return result
    sessions = closed_daily_frame(frames.get("^GSPC"), "^GSPC", now)
    if not sessions.empty:
        sessions = sessions.loc[sessions.index.strftime("%Y-%m-%d") <= reference_date]
    dates = list(dict.fromkeys(sessions.index.strftime("%Y-%m-%d"))) if not sessions.empty else []
    aligned_dates = bool(dates) and dates[-1] == reference_date
    previous_date = dates[-2] if aligned_dates and len(dates) >= 2 else ""
    base_date = dates[-22] if aligned_dates and len(dates) >= 22 else ""
    for name, ticker in MACRO_SYMBOLS.items():
        if ticker in REFERENCE_SYMBOLS:
            reference = macro_reference((scenario_frames or {}).get(ticker), ticker, reference_date, now,
                                        previous_date=previous_date, base_date=base_date, cache_dir=cache_dir)
            if reference:
                result[name] = reference
            continue
        frame = closed_daily_frame(frames.get(ticker), ticker, now)
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
    if row.get("status") == "pending":
        return "발표 대기: 동일일 시장 반응 비교 보류"
    if row.get("actual") is None:
        return "발표치 수집 실패·발표 여부 미확인: 동일일 비교 보류"
    if not at:
        return "발표치는 수집됨·발표일 미확인: 동일일 비교 보류"
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
