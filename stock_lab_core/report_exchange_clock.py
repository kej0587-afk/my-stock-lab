"""Local exchange calendars for report clocks, never investment-rule inputs."""

from functools import lru_cache

import numpy as np
import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
ZONES = {"KR": "Asia/Seoul", "US": "America/New_York"}


def non_equity_daily(ticker):
    """Known macro feeds must not inherit a stock-exchange daily calendar."""
    return ticker.endswith(("=F", "=X", ".NYB")) or ticker in {"^TNX", "^TYX", "^IRX", "^FVX", "^MOVE"}


@lru_cache(maxsize=16)
def _year_schedule(market, year):
    # Reuse official exceptions already maintained in the shared calendar. Cache
    # bounded year keys, not ticker/second keys; no network or quote TTL changes.
    from stock_lab_core.report_eventstudy import _exchange_schedule
    if market not in ZONES:
        raise ValueError("Unsupported report exchange")
    frame = _exchange_schedule(market, f"{year}-01-01", f"{year}-12-31")
    if frame.empty or not frame.index.is_unique:
        raise ValueError("Invalid exchange schedule")
    return frame


def session_on_date(market, day):
    """A known holiday differs from an unavailable calendar."""
    try:
        at = pd.Timestamp(day).tz_localize(None).normalize()
        schedule = _year_schedule(market, at.year)
        if at not in schedule.index:
            return {"known": True, "trading_day": False, "source": schedule.attrs.get("source", "거래소 달력")}
        row = schedule.loc[at]
        opening, closing = pd.Timestamp(row.market_open), pd.Timestamp(row.market_close)
        if opening.tzinfo is None or closing.tzinfo is None or not opening < closing:
            raise ValueError("Invalid session clocks")
        return {"known": True, "trading_day": True, "open": opening, "close": closing,
                "source": schedule.attrs.get("source", "거래소 달력")}
    except Exception:
        # No weekday/normal-hours fallback that would certify completion.
        return {"known": False, "trading_day": None, "source": "거래소 달력 조회불가"}


def exchange_clock(market, now):
    clock = pd.Timestamp(now)
    if clock.tzinfo is None:
        raise ValueError("Report exchange clock requires timezone")
    local = clock.tz_convert(ZONES[market])
    session = session_on_date(market, local.date())
    phase = ("unknown" if not session["known"] else "holiday" if not session["trading_day"]
             else "preopen" if clock < session["open"] else "intraday" if clock < session["close"] else "closed")
    return dict(session, phase=phase, local_date=local.date().isoformat())


def eligible_daily_dates(dates, market, now, *, close_delay_minutes=0, include_current=False):
    """Mask supplied session-date labels by actual opens/closes; never fill prices.

    Each consumer owns its existing close delay. In current-bar mode today's bar
    is eligible only after its actual open. On calendar failure return no eligible
    dates, rather than silently making multi-session moves into daily returns.
    """
    dates = pd.DatetimeIndex(dates).tz_localize(None).normalize()
    missing = np.zeros(len(dates), dtype=bool)
    if dates.empty:
        return missing
    clock = pd.Timestamp(now)
    if clock.tzinfo is None:
        raise ValueError("Report exchange clock requires timezone")
    local_day = clock.tz_convert(ZONES[market]).date()
    years = sorted({at.year for at in dates if pd.notna(at) and at.date() <= local_day})
    if not years:
        return missing
    try:
        schedule = pd.concat([_year_schedule(market, year) for year in years])
        opening = pd.to_datetime(schedule.market_open.reindex(dates), utc=True)
        closing = pd.to_datetime(schedule.market_close.reindex(dates), utc=True)
        limit = opening if include_current else closing + pd.Timedelta(minutes=close_delay_minutes)
        return (limit.notna() & (limit <= clock)).to_numpy(dtype=bool)
    except Exception:
        return missing
