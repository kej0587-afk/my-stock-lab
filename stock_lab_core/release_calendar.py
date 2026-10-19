"""Confirmed BLS releases and FOMC meeting end dates, without app imports.

All published reference months are retained for observation matching. Consumers
filter events to their own horizon. A connected source with no events in that
horizon is different from an unavailable source. FOMC dates have day precision:
the calendar does not publish a release time, so none is manufactured.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
import threading
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


FRED_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
_FRED_RELEASES = {"cpi": 10, "ppi": 46, "empsit": 50}


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
    # FRED supplies dates, not publication times or the observation month.
    return [{"event": _GROUPS[group][0], "indicator": _GROUPS[group][1],
             "release_at": day, "date": day, "release_precision": "date",
             "market": "US", "source": "FRED release calendar",
             "source_url": f"https://fred.stlouisfed.org/release?rid={release_id}"}
            for day in sorted(dates)]


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
        fallback_source.update(provider="FRED", primary_reason=source["reason"])
        return fallback, fallback_source
    source["fallback_reason"] = fallback_source["reason"]
    return [], source


def load_release_calendar(now=None, *, fred_api_key=""):
    """Return {events, sources, connected}; connected means at least one source.

    Four workers, 4-second request timeouts; failed BLS pages may use FRED dates.
    Successful parsed pages alone are cached; failures are retried next call.
    No weekday rules, inferred release months, FOMC times, or forecast values.
    """
    now = _clock(now)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_load_bls_source, group, url, now, fred_api_key)
                   for group, url in SCHEDULE_URLS.items()]
        futures.append(executor.submit(_load_source, "Federal Reserve FOMC", FOMC_URL,
                                       lambda html: _fomc_events(html, now), now))
        results = [future.result() for future in futures]
    events = [event for rows, _ in results for event in rows]
    sources = [source for _, source in results]
    events.sort(key=lambda event: (event["date"], event["indicator"]))
    return {"events": events, "sources": sources,
            "connected": any(source["status"] == "connected" for source in sources)}


load_release_calendar.clear = clear_release_calendar_cache
