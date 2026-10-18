"""Confirmed BLS releases and FOMC meeting end dates, without app imports.

All published reference months are retained for observation matching. Consumers
filter events to their own horizon. A connected source with no events in that
horizon is different from an unavailable source. FOMC dates have day precision:
the calendar does not publish a release time, so none is manufactured.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import re
import threading
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


REQUEST_TIMEOUT = 4.0
CACHE_TTL = 900
SCHEDULE_URLS = {
    group: f"https://www.bls.gov/schedule/news_release/{group}.htm"
    for group in ("cpi", "ppi", "empsit")
}
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
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


def _load_source(name, url, parser, now):
    key = (url, now.year)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL and cached[1] <= now.isoformat():
            return deepcopy(cached[2]), {"name": name, "status": "connected", "reason": ""}
    try:
        events = parser(_request(url))
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


def load_release_calendar(now=None):
    """Return {events, sources, connected}; connected means at least one source.

    Four independent official pages, four workers, 4-second request timeouts.
    Successful parsed pages alone are cached; failures are retried next call.
    No weekday rules, inferred release months, FOMC times, or forecast values.
    """
    now = _clock(now)
    jobs = [(_GROUPS[group][2], url, lambda html, g=group: _bls_events(html, g))
            for group, url in SCHEDULE_URLS.items()]
    jobs.append(("Federal Reserve FOMC", FOMC_URL, lambda html: _fomc_events(html, now)))
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_load_source, name, url, parser, now) for name, url, parser in jobs]
        results = [future.result() for future in futures]
    events = [event for rows, _ in results for event in rows]
    sources = [source for _, source in results]
    events.sort(key=lambda event: (event["date"], event["indicator"]))
    return {"events": events, "sources": sources,
            "connected": any(source["status"] == "connected" for source in sources)}


load_release_calendar.clear = clear_release_calendar_cache
