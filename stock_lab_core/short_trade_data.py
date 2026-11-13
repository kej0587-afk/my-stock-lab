"""Opt-in single-instrument research data, isolated from production price caches."""

from datetime import datetime, timezone
import logging
import re

import pandas as pd

from stock_lab_core.price_batch_selection import DownloadFrameSelector
from stock_lab_core.result_cache import cache_result
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.yahoo_transport import YAHOO_HISTORY_LOCK, yahoo_session_kwargs

register_loaded_source(__name__, __file__)
RULE = "channel-own-risk-v1"


def research_profile(ticker):
    ticker = str(ticker).strip().upper()
    if re.fullmatch(r"[0-9A-Z]{6}\.(KS|KQ)", ticker):
        market, zone, currency = "KR", "Asia/Seoul", "KRW"
    elif re.fullmatch(r"[A-Z]{1,8}(?:[.-][A-Z])?", ticker):
        market, zone, currency = "US", "America/New_York", "USD"
    else:
        return None
    # Only the previously verified same-market SOXL reference is inherited.
    # Other products use their OWN price, not an inferred underlying mapping.
    reference = "SOXX" if ticker == "SOXL" else ticker
    return dict(ticker=ticker, reference=reference, market=market, timezone=zone,
                currency=currency, rule="soxl-linked-v1" if ticker == "SOXL" else RULE)


def _download(ticker, days):
    profile = research_profile(ticker)
    captured = datetime.now(timezone.utc)
    result = dict(ok=False, frames={}, captured_at=captured.isoformat(), issue="")
    if not profile:
        result["issue"] = "한국·미국 상장 종목만 지원 · 현물 코인/선물/기타 시장은 별도 검증 필요"
        return result
    symbols = tuple(dict.fromkeys((profile["reference"], profile["ticker"])))
    if not YAHOO_HISTORY_LOCK.acquire(timeout=5):
        result["issue"] = "가격 조회 사용 중 · 잠시 후 재조회"
        return result
    try:
        import yfinance as yf
        raw = yf.download(list(symbols), start=(captured - pd.Timedelta(days=days)).date().isoformat(),
                          interval="60m", prepost=False, auto_adjust=True, ignore_tz=False,
                          group_by="ticker", threads=False, progress=False, timeout=10,
                          **yahoo_session_kwargs())
        if not isinstance(raw, pd.DataFrame) or raw.empty:
            result["issue"] = "시간봉 응답 없음 · 승률 미산출"
            return result
        if len(symbols) > 1 and not isinstance(raw.columns, pd.MultiIndex):
            result["issue"] = "종목별 응답 구분 불가 · 다른 종목 가격으로 대체하지 않음"
            return result
        selector = DownloadFrameSelector(raw)
        result["frames"] = {t: selector.select(t) for t in symbols}
        result["ok"] = all(not f.empty for f in result["frames"].values())
        if not result["ok"]:
            result["issue"] = "일부 종목 시간봉 미확보 · 추정/보간하지 않음"
    except Exception as exc:
        logging.warning("Short research download %s: %s", profile["ticker"], type(exc).__name__)
        result["issue"] = "시간봉 조회 실패: " + type(exc).__name__
    finally:
        YAHOO_HISTORY_LOCK.release()
    return result


@cache_result(ttl=86400, failure_ttl=30, trace_name="short_research_history")
def load_history(ticker):
    return _download(ticker, 729)


@cache_result(ttl=300, failure_ttl=30, trace_name="short_research_current")
def load_current(ticker):
    return _download(ticker, 59)
