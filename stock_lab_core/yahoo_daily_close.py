"""Repair a missing last daily Close only from the same session's supplier quote."""

import math
import pandas as pd

from stock_lab_core.quote_observation import QuoteObservation, quote_provenance
from stock_lab_core.report_exchange_clock import session_on_date
from stock_lab_core.report_build import register_loaded_source


def missing_close_quote(result, ticker, *, now=None):
    """No prior-close, extended-hours, calendar-date or OHLC fabrication."""
    try:
        meta = result["meta"]
        if meta["symbol"].upper() != ticker.upper() or meta["exchangeTimezoneName"] != "America/New_York":
            return None
        stamps = result["timestamp"]
        bars = result["indicators"]["quote"][0]
        if not stamps or len(stamps) != len(bars["close"]) or pd.notna(bars["close"][-1]):
            return None
        day = pd.Timestamp(stamps[-1], unit="s", tz="UTC").tz_convert("America/New_York").date().isoformat()
        trade = pd.Timestamp(meta["regularMarketTime"], unit="s", tz="UTC")
        session = session_on_date("US", day)
        clock = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
        if (not session["known"] or not session["trading_day"] or pd.isna(trade)
                or pd.isna(clock) or clock.tzinfo is None
                or clock < session["close"] or trade > clock
                or trade < session["close"] - pd.Timedelta(minutes=1)
                or trade > session["close"] + pd.Timedelta(minutes=15)):
            return None
        price = float(meta["regularMarketPrice"])
        low, high, opening = (float(bars[k][-1]) for k in ("low", "high", "open"))
        if not all(math.isfinite(v) and v > 0 for v in (price, low, high, opening)):
            return None
        if not low <= min(opening, price) <= max(opening, price) <= high:
            return None
        return QuoteObservation(price, source="yahoo_regular_close_metadata", symbol=ticker,
                                observed_at=trade.to_pydatetime(), session="regular", timestamp_kind="trade")
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return None


def fill_history_close(frame, ticker, quote):
    """Fill only the existing missing tail Close; adjusted close remains unknown."""
    evidence = quote_provenance(quote, ticker)
    if evidence.get("source") != "yahoo_regular_close_metadata" or evidence.get("session") != "regular":
        return frame
    try:
        if (frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_unique
                or not frame.index.is_monotonic_increasing or pd.notna(frame.Close.iloc[-1])):
            return frame
        day = pd.Timestamp(evidence["observed_at"]).tz_convert("America/New_York").date()
        if frame.index[-1].date() != day:
            return frame
        low, high, opening = (float(frame[k].iloc[-1]) for k in ("Low", "High", "Open"))
        if not all(math.isfinite(v) and v > 0 for v in (low, high, opening)):
            return frame
        if not low <= min(opening, quote) <= max(opening, quote) <= high:
            return frame
        out = frame.copy(deep=True)
        out.loc[out.index[-1], "Close"] = float(quote)
        out.attrs["daily_close_repair"] = {**evidence, "date": day.isoformat(), "field": "Close"}
        return out
    except (KeyError, IndexError, AttributeError, TypeError, ValueError, OverflowError):
        return frame


register_loaded_source(__name__, __file__)
