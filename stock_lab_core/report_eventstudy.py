"""Bounded official-result/event-calendar bridge; never fetch prices or results."""

from functools import lru_cache

import pandas as pd

from stock_lab_core.market_observation import (
    _clock, _records, _schedule, build_event_study, historical_earnings_events,
)
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

CALENDARS = {"US": "XNYS", "KR": "XKRX"}
CALENDAR_SOURCE = "https://github.com/gerrymanoim/exchange_calendars"
MAX_EVENTS = 128
HISTORY_DAYS = 400


@lru_cache(maxsize=8)
def _exchange_schedule(market, start, end):
    import exchange_calendars as calendars

    raw = calendars.get_calendar(CALENDARS[market], start=start, end=end).schedule
    frame = raw.loc[start:end, ["open", "close"]].rename(
        columns={"open": "market_open", "close": "market_close"})
    checked = _schedule(frame)
    if checked is None:
        raise ValueError("invalid_exchange_calendar")
    checked.attrs.update(source="exchange_calendars " + CALENDARS[market],
                         source_url=CALENDAR_SOURCE, version=calendars.__version__)
    return checked


def collect_event_study_context(context, now, *, window=5):
    """Return events/schedules/diagnostics for the existing observation panel.

    Read only existing earnings_results/calendar_events/price_frames. At most
    two local exchange calendars and 128 evidence rows are inspected; cached
    calendars cover 400 past days plus 40 calendar days for window validation.
    Only complete N-session windows are returned as events. Date-only official
    results explicitly assume their actual session close; build_event_study
    keeps these out of confirmed counts. Missing dependencies, calendars,
    dates, prices or completed windows remain diagnostics, never invented data.
    This does not modify the input context, fetch prices, or change any gate.
    """
    now = _clock(now)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("window must be a positive integer number of sessions")
    output = {"events": [], "schedules": {}, "diagnostics": []}
    results = _records(context.get("earnings_results"))
    calendar = _records(context.get("calendar_events"))
    supplied = results + calendar
    if not supplied:
        output["diagnostics"].append({"status": "unavailable", "reason": "no_connected_official_results"})
        return output
    if len(supplied) > MAX_EVENTS:
        output["diagnostics"].append({"status": "partial", "reason": "event_limit", "limit": MAX_EVENTS})
    selected = {"earnings_results": results[:MAX_EVENTS],
                "calendar_events": calendar[:max(0, MAX_EVENTS - len(results))]}
    tickers = {str(row.get("ticker") or "").upper() for row in supplied[:MAX_EVENTS] if row.get("ticker")}
    markets = {"KR" if ticker.endswith((".KS", ".KQ")) else "US" for ticker in tickers}
    start = (now - pd.Timedelta(days=HISTORY_DAYS)).date().isoformat()
    end = (now + pd.Timedelta(days=40)).date().isoformat()
    for market in sorted(markets):
        try:
            frame = _exchange_schedule(market, start, end).copy(deep=True)
        except (ImportError, ModuleNotFoundError):
            output["diagnostics"].append({"market": market, "status": "unavailable",
                                          "reason": "exchange_calendars_not_installed"})
        except Exception:
            # Calendar coverage/schema failures must not fabricate weekdays.
            output["diagnostics"].append({"market": market, "status": "unavailable",
                                          "reason": "exchange_calendar_unavailable"})
        else:
            output["schedules"][market] = frame
            output["diagnostics"].append({"market": market, "status": "connected",
                "calendar": CALENDARS[market], "source_url": CALENDAR_SOURCE,
                "version": frame.attrs.get("version"), "start": start, "end": end})
    mapped = historical_earnings_events(selected, as_of=now,
        session_schedules=output["schedules"], allow_conventional=True)
    study = build_event_study(mapped["events"], context.get("price_frames") or {},
        as_of=now, window=window, session_schedules=output["schedules"])
    accepted = {row["event_id"] for key in ("observations", "assumption_observations") for row in study[key]}
    output["events"] = [row for row in mapped["events"] if row["event_id"] in accepted]
    output["diagnostics"].extend(dict(row, status="deferred") for row in mapped["skipped"] + study["skipped"])
    output["diagnostics"].append({"status": "checked", "window": window,
        "confirmed_sample_count": study["sample_count"], "assumption_sample_count": study["assumption_sample_count"],
        "timing_note": "Date-only results use a separate exchange-close assumption, not a verified publication time."})
    return output
