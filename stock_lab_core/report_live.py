"""Bounded, report-only recent index corrections and timestamped live quotes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import math
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.result_cache import cache_result

register_loaded_source(__name__, __file__)


@cache_result(ttl=900, failure_ttl=15, is_success=lambda frame: not frame.empty)
def load_kr_index_history(code):
    if code not in {"KOSPI", "KOSDAQ"}:
        return pd.DataFrame()
    try:
        response = requests.get(f"https://api.stock.naver.com/chart/domestic/index/{code}",
                                params={"periodType": "month"}, timeout=4)
        response.raise_for_status()
        rows = response.json()["priceInfos"]
        frame = pd.DataFrame(rows).rename(columns={"closePrice": "Close", "openPrice": "Open",
            "highPrice": "High", "lowPrice": "Low", "accumulatedTradingVolume": "Volume"})
        frame.index = pd.to_datetime(frame["localDate"], format="%Y%m%d", errors="raise")
        frame = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
        frame = frame.loc[frame.Close.gt(0) & frame.Close.map(math.isfinite)].sort_index()
        frame.attrs["source"] = "Naver 지수 일봉(month daily)"
        return frame
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return pd.DataFrame()


def supplement_kr_indices(frames):
    frames = dict(frames)
    with ThreadPoolExecutor(max_workers=2) as pool:
        recent = list(pool.map(load_kr_index_history, ("KOSPI", "KOSDAQ")))
    for ticker, update in zip(("^KS11", "^KQ11"), recent):
        old = frames.get(ticker)
        if update.empty or (old is not None and not old.empty and old.index[-1].date() >= update.index[-1].date()):
            continue
        if old is not None and not old.empty:
            old = old.copy()
            old.index = old.index.tz_localize(None).normalize()
            update = pd.concat([old, update])
            update = update.loc[~update.index.duplicated(keep="last")].sort_index()
        update.attrs["source"] = "Yahoo 이력 + Naver 최신 지수 일봉"
        frames[ticker] = update
    return frames


@cache_result(ttl=60, failure_ttl=15, is_success=lambda frames: bool(frames))
def load_us_live_frames(tickers):
    import yfinance as yf
    from stock_lab_core.prices import _select_download_ohlcv
    from stock_lab_core.yahoo_transport import YAHOO_HISTORY_LOCK, yahoo_session_kwargs

    if not tickers:
        return {}
    try:
        with YAHOO_HISTORY_LOCK:
            data = yf.download(list(tickers), period="5d", interval="5m", auto_adjust=True,
                               group_by="ticker", threads=4, progress=False, timeout=4,
                               **yahoo_session_kwargs())
        return {ticker: frame for ticker in tickers
                if not (frame := _select_download_ohlcv(data, ticker)).empty and frame.index.tz is not None}
    except (ValueError, TypeError, KeyError, requests.RequestException):
        return {}


def us_live_observation(frame, ticker, previous, now):
    """Use only completed 5m bars from the active NY session, never future bars."""
    from stock_lab_core.report_session import market_session_states

    state = market_session_states(now)["US"]
    if state["phase"] != "intraday" or frame is None or frame.empty or frame.index.tz is None:
        return {}
    from stock_lab_core.prices import _us_equity_market_holidays
    previous_session = pd.Timestamp(state["active_date"]).date() - timedelta(days=1)
    while previous_session.weekday() >= 5 or previous_session in _us_equity_market_holidays(previous_session.year):
        previous_session -= timedelta(days=1)
    if previous.get("date") != previous_session.isoformat():
        return {}
    cutoff = pd.Timestamp(now)
    ends = frame.index + pd.Timedelta(minutes=5)
    ny = frame.index.tz_convert(ZoneInfo("America/New_York"))
    mask = ((ny.strftime("%Y-%m-%d") == state["active_date"]) & (ends <= cutoff)
            & (ny.hour * 60 + ny.minute >= 570) & (ny.hour * 60 + ny.minute < 960))
    eligible = frame.loc[mask].sort_index()
    prior = previous.get("price")
    if eligible.empty or not prior or not math.isfinite(prior) or prior <= 0:
        return {}
    close = pd.to_numeric(eligible.Close, errors="coerce").dropna()
    if close.empty or not math.isfinite(close.iloc[-1]) or close.iloc[-1] <= 0:
        return {}
    as_of = close.index[-1] + pd.Timedelta(minutes=5)
    return {"ticker": ticker, "date": state["active_date"], "return": float(close.iloc[-1] / prior - 1),
            "price": float(close.iloc[-1]), "previous_date": previous.get("date", ""),
            "retrieved_at": now.isoformat(), "as_of": as_of.isoformat(), "kind": "장중 진행·확정 아님",
            "source": "Yahoo 정규장 5분봉(완료 봉, 지연 가능)"}
