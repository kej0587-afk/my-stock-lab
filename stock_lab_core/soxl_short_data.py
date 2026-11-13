"""On-demand, bounded hourly data; never used by the daily scoring pipeline."""

import logging
from datetime import datetime, timezone

import pandas as pd

from stock_lab_core.price_batch_selection import DownloadFrameSelector
from stock_lab_core.result_cache import cache_result
from stock_lab_core.soxl_short_observation import SYMBOLS
from stock_lab_core.yahoo_transport import YAHOO_HISTORY_LOCK, yahoo_session_kwargs


@cache_result(ttl=300, failure_ttl=30, trace_name="soxl_short_hours")
def load_short_hours():
    import yfinance as yf

    captured = datetime.now(timezone.utc)
    result = {"ok": False, "frames": {}, "captured_at": captured.isoformat(), "issue": ""}
    acquired = YAHOO_HISTORY_LOCK.acquire(timeout=5)
    if not acquired:
        result["issue"] = "가격 조회 사용 중 · 잠시 후 재조회"
        return result
    try:
        data = yf.download(list(SYMBOLS), start=(captured - pd.Timedelta(days=59)).date().isoformat(),
                           interval="60m", prepost=False, auto_adjust=True, ignore_tz=False,
                           group_by="ticker", threads=4, progress=False, timeout=6,
                           **yahoo_session_kwargs())
        # A flat batch cannot prove symbol ownership; do not reuse it for all four.
        if not isinstance(data, pd.DataFrame) or not isinstance(data.columns, pd.MultiIndex):
            result["issue"] = "종목별 시간봉 응답 미확인"
            return result
        selector = DownloadFrameSelector(data)
        result["frames"] = {symbol: selector.select(symbol) for symbol in SYMBOLS}
        result["ok"] = all(not frame.empty for frame in result["frames"].values())
        if not result["ok"]:
            result["issue"] = "일부 시간봉 미수집 · 결측은 보완하지 않음"
    except Exception as exc:
        logging.warning("SOXL short-hour download failed: %s", type(exc).__name__)
        result["issue"] = "시간봉 조회 실패: " + type(exc).__name__
    finally:
        YAHOO_HISTORY_LOCK.release()
    return result


@cache_result(ttl=60, failure_ttl=30, trace_name="soxl_short_five")
def load_short_five():
    """One opt-in SOXX request, not added to daily scoring or background refresh."""
    import yfinance as yf

    captured = datetime.now(timezone.utc)
    result = {"ok": False, "frame": pd.DataFrame(), "captured_at": captured.isoformat(), "issue": ""}
    if not YAHOO_HISTORY_LOCK.acquire(timeout=5):
        result["issue"] = "5분 가격 조회 사용 중 · 잠시 후 재조회"
        return result
    try:
        data = yf.download(["SOXX"], period="5d", interval="5m", prepost=False,
                           auto_adjust=True, ignore_tz=False, group_by="ticker",
                           threads=False, progress=False, timeout=6, **yahoo_session_kwargs())
        if isinstance(data, pd.DataFrame) and isinstance(data.columns, pd.MultiIndex):
            result["frame"] = DownloadFrameSelector(data).select("SOXX")
        result["ok"] = not result["frame"].empty
        if not result["ok"]:
            result["issue"] = "SOXX 5분봉 미수집 · 보간하지 않음"
    except Exception as exc:
        logging.warning("SOXX five-minute download failed: %s", type(exc).__name__)
        result["issue"] = "5분봉 조회 실패: " + type(exc).__name__
    finally:
        YAHOO_HISTORY_LOCK.release()
    return result
