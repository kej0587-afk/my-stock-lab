"""Official release dates and source-stamped policy/earnings schedules.

All published reference months are retained for observation matching. Consumers
filter events to their own horizon. A connected source with no events in that
horizon is different from an unavailable source. FOMC dates have day precision:
the calendar does not publish a release time, so none is manufactured.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
import threading
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from stock_lab_core.earnings_sources import (
    VERIFIED_AT as EARNINGS_VERIFIED_AT, clear_earnings_source_cache, load_official_earnings,
)
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


FRED_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
_FRED_RELEASES = {"cpi": 10, "ppi": 46, "empsit": 50}


REQUEST_TIMEOUT = 4.0
CACHE_TTL = 900
SCHEDULE_URLS = {
    group: f"https://www.bls.gov/schedule/news_release/{group}.htm"
    for group in ("cpi", "ppi", "empsit")
}
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BOK_URL = "https://www.bok.or.kr/portal/bbs/B0000502/view.do?nttId=10094300&menuNo=201265"
META_IR_URL = ("https://investor.atmeta.com/investor-news/press-release-details/"
               "2026/Meta-to-Announce-Third-Quarter-2026-Results/default.aspx")
TESLA_IR_URL = "https://ir.tesla.com/press-release/tesla-third-quarter-2026-production-deliveries-and-deployments"
# The BOK page delegates its calendar to an attachment which blocks automated
# retrieval. These are policy decisions, excluding general/stability meetings.
_BOK_2026_DATES = ("2026-01-15", "2026-02-26", "2026-04-10", "2026-05-28",
                   "2026-07-16", "2026-08-27", "2026-10-22", "2026-11-26")
_VERIFIED_ON = "2026-10-20"
_GROUPS = {
    "cpi": ("Consumer Price Index", "US_CPI", "BLS CPI"),
    "ppi": ("Producer Price Index", "US_PPI", "BLS PPI"),
    "empsit": ("Employment Situation", "US_NONFARM_PAYROLLS", "BLS Employment Situation"),
}
_CACHE = OrderedDict()
_LOCK = threading.Lock()


def clear_release_calendar_cache():
    with _LOCK:
        _CACHE.clear()
    clear_earnings_source_cache()


def _clock(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, date) and not isinstance(now, datetime):
        now = datetime.combine(now, datetime.min.time())
    if not isinstance(now, datetime):
        raise TypeError("now must be a date or datetime")
    return (now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now).astimezone(timezone.utc)


class _InvalidCalendar(ValueError):
    pass


def _request(url):
    response = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False,
                            headers={"User-Agent": "StockLab-Release-Calendar/1.0"})
    try:
        if response.status_code != 200:
            raise _InvalidCalendar(f"http_{response.status_code}")
        return response.text
    finally:
        response.close()


class _ScheduleTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        elif tag in {"th", "td"} and self.cells is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            self.rows.append(self.cells)
            self.cells = None


def _bls_events(html, group):
    parser = _ScheduleTable()
    parser.feed(html)
    event, indicator, source = _GROUPS[group]
    events = []
    for cells in parser.rows[:120]:
        if len(cells) != 3:
            continue
        try:
            period = datetime.strptime(cells[0], "%B %Y").strftime("%Y-%m")
            day = cells[1].replace("Sept.", "Sep").replace(".", "")
            try:
                day = datetime.strptime(day, "%b %d, %Y").date()
            except ValueError:
                day = datetime.strptime(day, "%B %d, %Y").date()
            clock = datetime.strptime(cells[2], "%I:%M %p").time()
            try:
                at = datetime.combine(day, clock, ZoneInfo("America/New_York")).isoformat()
            except ZoneInfoNotFoundError:
                at = day.isoformat()
        except ValueError:
            continue
        events.append({"event": event, "indicator": indicator, "period": period,
                       "release_at": at, "date": day.isoformat(), "market": "US",
                       "source": source, "source_url": SCHEDULE_URLS[group]})
    if not events:
        raise _InvalidCalendar("calendar_rows_unrecognized")
    return events


class _FomcTable(HTMLParser):
    """Read the Fed's year headings and explicit meeting month/date fields."""

    def __init__(self):
        super().__init__()
        self.rows, self.year, self.heading = [], None, None
        self.depth, self.meeting, self.meeting_depth = 0, None, None
        self.field, self.field_depth, self.parts = None, None, []

    def handle_starttag(self, tag, attrs):
        if tag == "h4":
            self.heading = []
        if tag != "div":
            return
        self.depth += 1
        classes = dict(attrs).get("class", "").split()
        if "fomc-meeting" in classes:
            self.meeting, self.meeting_depth = {"year": self.year}, self.depth
        elif self.meeting is not None:
            for field in ("month", "date"):
                if "fomc-meeting__" + field in classes:
                    self.field, self.field_depth, self.parts = field, self.depth, []

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.field is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h4" and self.heading is not None:
            match = re.fullmatch(r"\s*(\d{4}) FOMC Meetings\s*", "".join(self.heading))
            self.year = int(match[1]) if match else None
            self.heading = None
        if tag != "div":
            return
        if self.field_depth == self.depth:
            self.meeting[self.field] = "".join(self.parts).strip()
            self.field, self.field_depth = None, None
        if self.meeting_depth == self.depth:
            self.rows.append(self.meeting)
            self.meeting, self.meeting_depth = None, None
        self.depth -= 1


def _fomc_events(html, now):
    parser = _FomcTable()
    parser.feed(html)
    events = []
    for row in parser.rows:
        if row.get("year") not in {now.year - 1, now.year, now.year + 1}:
            continue
        # An asterisk denotes projections, not an uncertain meeting date.
        match = re.fullmatch(r"(\d{1,2})(?:[-\u2013](\d{1,2}))?\*?", row.get("date", ""))
        if not match:
            continue
        try:
            months = row["month"].split("/")
            first = datetime.strptime(months[0][:3], "%b").month
            last = datetime.strptime(months[-1][:3], "%b").month
            start = date(row["year"], first, int(match[1]))
            end = date(row["year"], last, int(match[2] or match[1]))
            if (end - start).days not in {0, 1}:
                continue
        except (ValueError, KeyError):
            continue
        events.append({"event": "FOMC meeting", "indicator": "US_FED_RATE_DECISION",
                       "release_at": end.isoformat(), "date": end.isoformat(),
                       "start_date": start.isoformat(), "market": "US",
                       "source": "Federal Reserve FOMC", "source_url": FOMC_URL})
    if not events:
        raise _InvalidCalendar("calendar_rows_unrecognized")
    return events


def _fred_dates(group, now, api_key):
    response = requests.get(
        FRED_DATES_URL,
        params={"release_id": _FRED_RELEASES[group], "api_key": api_key,
                "file_type": "json", "include_release_dates_with_no_data": "true",
                "realtime_start": (now.date() - timedelta(days=90)).isoformat(),
                "realtime_end": (now.date() + timedelta(days=90)).isoformat(),
                "limit": 1000, "sort_order": "asc"},
        headers={"User-Agent": "StockLab-Release-Calendar/1.0"},
        timeout=REQUEST_TIMEOUT, allow_redirects=False,
    )
    try:
        if response.status_code != 200:
            raise _InvalidCalendar("http_" + str(response.status_code))
        return response.json()
    finally:
        response.close()


def _fred_events(payload, group, now):
    rows = payload.get("release_dates") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise _InvalidCalendar("calendar_rows_unrecognized")
    release_id = _FRED_RELEASES[group]
    dates = set()
    for row in rows:
        if not isinstance(row, dict) or str(row.get("release_id")) != str(release_id):
            continue
        raw_date = row.get("date")
        if not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            continue
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if abs((day - now.date()).days) <= 90:
            dates.add(raw_date)
    if not dates:
        raise _InvalidCalendar("calendar_rows_unrecognized")
    # FRED confirms the day only. The usual BLS clock is a rule, not evidence
    # that an exceptional/delayed announcement occurred at that instant.
    events = []
    for day in sorted(dates):
        try:
            at = datetime.combine(date.fromisoformat(day), datetime_time(8, 30),
                                  ZoneInfo("America/New_York")).isoformat()
        except ZoneInfoNotFoundError:
            at = day
        events.append({"event": _GROUPS[group][0], "indicator": _GROUPS[group][1],
                       "release_at": at, "date": day,
                       "release_precision": "schedule_rule" if "T" in at else "date",
                       "release_time_confirmed": False, "date_precision": "date",
                       "schedule_rule": "08:30 America/New_York",
                       "schedule_rule_source": "BLS standard release schedule; exceptions unconfirmed",
                       "schedule_rule_source_url": SCHEDULE_URLS[group],
                       "market": "US", "source": "FRED release calendar",
                       "source_url": f"https://fred.stlouisfed.org/release?rid={release_id}"})
    return events


def _bok_source(now):
    name = "Bank of Korea MPC"
    if now.year != 2026 or now.date() < date(2025, 10, 30):
        return [], {"name": name, "status": "unavailable", "reason": "verified_year_unavailable"}
    events = [{"event": "한국은행 금융통화위원회 통화정책방향 결정회의",
               "indicator": "KR_BOK_RATE_DECISION", "market": "KR", "date": day,
               "release_at": day, "release_precision": "date", "timezone": "Asia/Seoul",
               "source": name, "source_url": BOK_URL, "source_published_at": "2025-10-30",
               "source_verified_at": _VERIFIED_ON, "source_kind": "verified_fixture"}
              for day in _BOK_2026_DATES]
    return events, {"name": name, "status": "connected", "reason": "",
                    "provider": "verified_fixture", "coverage_year": 2026,
                    "source_url": BOK_URL, "source_verified_at": _VERIFIED_ON}


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _meta_events(html, url):
    parser = _PageText()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).split())
    match = re.search(
        r"(?:company['\u2019]s )?(first|second|third|fourth) quarter (20\d{2}) financial results "
        r"will be released after market close on (?:\w+,? )?"
        r"([A-Z][a-z]+) (\d{1,2})(?:st|nd|rd|th)?,? (20\d{2})", text, re.I)
    if not match or match[1].lower() != "third" or match[2] != "2026" or match[2] != match[5]:
        raise _InvalidCalendar("calendar_rows_unrecognized")
    try:
        day = datetime.strptime(f"{match[3]} {match[4]} {match[5]}", "%B %d %Y").date().isoformat()
    except ValueError:
        raise _InvalidCalendar("calendar_rows_unrecognized") from None
    event = {"event": "Meta earnings", "indicator": "US_META_EARNINGS", "ticker": "META",
             "market": "US", "date": day, "release_at": day, "release_precision": "date",
             "timezone": "America/New_York", "session_timing": "after_market_close",
             "release_time_confirmed": False, "source": "Meta Investor Relations",
             "source_url": url}
    call = re.search(r"conference call.{0,100}?at.{0,60}?/\s*(\d{1,2}):(\d{2})\s*p\.m\.\s*ET the same day", text, re.I)
    if call:
        try:
            clock = datetime_time(int(call[1]) % 12 + 12, int(call[2]))
            event["conference_call_at"] = datetime.combine(date.fromisoformat(day), clock,
                                                            ZoneInfo("America/New_York")).isoformat()
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return [event]


def _meta_source(now):
    # This announced quarter has verified fallback coverage; no dates for other
    # quarters are extrapolated from previous earnings or third-party calendars.
    name = "Meta Investor Relations"
    if now >= datetime.fromisoformat(EARNINGS_VERIFIED_AT):
        result = load_official_earnings(["META"], now, refresh=False)
        return result["events"], result["sources"][0]
    if not date(2026, 10, 12) <= now.date() <= date(2026, 12, 31):
        return [], {"name": name, "status": "unavailable", "reason": "verified_quarter_unavailable"}
    events, source = _load_source(name, META_IR_URL, lambda html: _meta_events(html, META_IR_URL), now)
    if source["status"] == "connected":
        return events, source
    event = {"event": "Meta earnings", "indicator": "US_META_EARNINGS", "ticker": "META",
             "market": "US", "date": "2026-10-21", "release_at": "2026-10-21",
             "release_precision": "date", "timezone": "America/New_York",
             "session_timing": "after_market_close", "release_time_confirmed": False,
             "source": name, "source_url": META_IR_URL, "source_published_at": "2026-10-12",
             "source_verified_at": _VERIFIED_ON, "source_kind": "verified_fixture",
             "conference_call_at": "2026-10-21T16:30:00-04:00"}
    return [event], {"name": name, "status": "connected", "reason": "",
                     "provider": "verified_fixture", "fallback_connected": True,
                     "primary_reason": source["reason"], "source_url": META_IR_URL,
                     "source_verified_at": _VERIFIED_ON}


def _tesla_events(html):
    parser = _PageText()
    parser.feed(html)
    page = " ".join(" ".join(parser.parts).split())
    match = re.search(r"Tesla will post its financial results for the third quarter of (2026) after market close on "
                      r"(?:\w+,? )?([A-Z][a-z]+) (\d{1,2}),? (2026)", page, re.I)
    if not match:
        raise _InvalidCalendar("calendar_rows_unrecognized")
    day = datetime.strptime(f"{match[2]} {match[3]} {match[4]}", "%B %d %Y").date().isoformat()
    event = {"event": "Tesla earnings", "indicator": "US_TSLA_EARNINGS", "ticker": "TSLA",
             "market": "US", "date": day, "release_at": day, "release_precision": "date",
             "timezone": "America/New_York", "session_timing": "after_market_close",
             "release_time_confirmed": False, "source": "Tesla Investor Relations", "source_url": TESLA_IR_URL}
    if re.search(r"5:30\s*p\.?m\.?\s*(?:Eastern Time|ET)", page, re.I):
        event["conference_call_at"] = datetime.combine(date.fromisoformat(day), datetime_time(17, 30),
                                                        ZoneInfo("America/New_York")).isoformat()
    return [event]


def _tesla_source(now):
    name = "Tesla Investor Relations"
    if now >= datetime.fromisoformat(EARNINGS_VERIFIED_AT):
        result = load_official_earnings(["TSLA"], now, refresh=False)
        return result["events"], result["sources"][0]
    if not date(2026, 10, 2) <= now.date() <= date(2026, 12, 31):
        return [], {"name": name, "status": "unavailable", "reason": "verified_quarter_unavailable"}
    # Reuse this independently verified announcement without adding a request
    # to each render. Coverage ends with the explicitly announced quarter.
    event = _tesla_events("Tesla will post its financial results for the third quarter of 2026 after market close on "
                          "Wednesday, October 21, 2026. Webcast 5:30 p.m. Eastern Time")
    event[0].update(source_published_at="2026-10-02", source_verified_at="2026-10-21", source_kind="verified_fixture")
    return event, {"name": name, "status": "connected", "reason": "", "provider": "verified_fixture",
                   "source_url": TESLA_IR_URL,
                   "source_verified_at": "2026-10-21"}


def _load_source(name, url, parser, now, *, fetch=None, cache_scope=""):
    key = (url, now.year, cache_scope)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL and cached[1] <= now.isoformat():
            return deepcopy(cached[2]), {"name": name, "status": "connected", "reason": ""}
    try:
        events = parser(fetch() if fetch is not None else _request(url))
    except _InvalidCalendar as exc:
        reason = str(exc)
    except requests.RequestException as exc:
        reason = "request_failed:" + type(exc).__name__
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        reason = "invalid_response"
    else:
        with _LOCK:
            _CACHE[key] = (time.monotonic(), now.isoformat(), deepcopy(events))
            _CACHE.move_to_end(key)
            while len(_CACHE) > 16:
                _CACHE.popitem(last=False)
        return events, {"name": name, "status": "connected", "reason": ""}
    return [], {"name": name, "status": "unavailable", "reason": reason}


def _load_bls_source(group, url, now, fred_api_key):
    name = _GROUPS[group][2]
    events, source = _load_source(name, url, lambda html: _bls_events(html, group), now)
    if source["status"] == "connected" or not fred_api_key:
        return events, source
    public_url = f"https://fred.stlouisfed.org/release?rid={_FRED_RELEASES[group]}"
    scope = (sha256(fred_api_key.encode()).hexdigest(), now.date().isoformat())
    fallback, fallback_source = _load_source(
        name, public_url, lambda payload: _fred_events(payload, group, now), now,
        fetch=lambda: _fred_dates(group, now, fred_api_key), cache_scope=scope,
    )
    if fallback_source["status"] == "connected":
        fallback_source.update(provider="FRED", primary_reason=source["reason"],
                               fallback_connected=True, primary_status="unavailable")
        return fallback, fallback_source
    source["fallback_reason"] = fallback_source["reason"]
    return [], source


def load_release_calendar(now=None, *, fred_api_key="", earnings_tickers=None):
    """Return {events, sources, connected}; connected means at least one source.

    Four workers, 4-second request timeouts; failed BLS pages may use FRED dates.
    Pass earnings_tickers for bounded holdings/watch coverage (no universe scan).
    Omitting it preserves legacy Meta/Tesla coverage. Recent published results
    and next schedules are separate; date-only evidence has no guessed minute.
    Macro pages cache only successes; earnings checks also cool down failures.
    No guessed dates, inferred release months, FOMC times, or forecast values.
    """
    now = _clock(now)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_load_bls_source, group, url, now, fred_api_key)
                   for group, url in SCHEDULE_URLS.items()]
        futures.append(executor.submit(_load_source, "Federal Reserve FOMC", FOMC_URL,
                                       lambda html: _fomc_events(html, now), now))
        if earnings_tickers is None:
            futures.append(executor.submit(_meta_source, now))
            futures.append(executor.submit(_tesla_source, now))
        results = [future.result() for future in futures]
    results.append(_bok_source(now))
    if earnings_tickers is not None:
        earnings = load_official_earnings(earnings_tickers, now)
        results.extend(([], source) for source in earnings["sources"])
        results.append((earnings["events"], None))
    events = [event for rows, _ in results for event in rows]
    sources = [source for _, source in results if source is not None]
    for event in events:
        if event.get("ticker") and "event_status" not in event:
            local_day = now.astimezone(ZoneInfo(event["timezone"])).date().isoformat()
            event["event_status"] = "elapsed_unconfirmed" if event["date"] < local_day else "scheduled"
            event["event_kind"] = "scheduled_release"
    events.sort(key=lambda event: (event["date"], event["indicator"]))
    return {"events": events, "sources": sources,
            "recent_earnings": [deepcopy(e) for e in events if e.get("event_status") == "released"],
            "upcoming_earnings": [deepcopy(e) for e in events if e.get("event_status") == "scheduled"],
            "elapsed_earnings": [deepcopy(e) for e in events if e.get("event_status") == "elapsed_unconfirmed"],
            "connected": any(source["status"] == "connected" for source in sources)}


load_release_calendar.clear = clear_release_calendar_cache
