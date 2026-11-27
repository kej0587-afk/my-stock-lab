"""Opt-in official watch schedules; no inferred dates, values or price effects.

Reuse release_calendar's 4s request and 900s success-only cache unchanged.
Cboe dates are a finite visually verified mapping, gated by the PDF digest.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
from html import unescape
from io import BytesIO
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stock_lab_core import release_calendar as calendar
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

CENSUS_URL = "https://www.census.gov/retail/release_schedule.html"
CENSUS_PDF_URL = "https://www.census.gov/retail/marts/www/marts_current.pdf"
APEC_URL = "https://www.apec.org/press/blogs/2026/apec-economic-leaders-week-2026-why-it-matters"
CBOE_URL = "https://res-certification.cboe.com/resources/options/Cboe2026OPTIONSCalendar.pdf"
CBOE_SHA256 = "421a0699055b99ebc2dea6da53666939bc0918882d1f615da5664582a52b3c9e"
CBOE_VERIFIED_AT = "2026-11-15"
CBOE_EXPIRES_AT = datetime(2027, 1, 1, tzinfo=timezone.utc)
# Visual verification of the official PDF, not a recurring weekday formula.
_CBOE_DATES = (
    ("2026-11-17", "US_VIX_LAST_TRADE", "VIX options last trading day", "last_trade_date"),
    ("2026-11-18", "US_VIX_STANDARD_EXPIRY", "VIX options standard expiration", "option_expiration"),
    ("2026-11-19", "US_AM_INDEX_OPTIONS_LAST_TRADE", "AM-settled equity index options last trading day", "last_trade_date"),
    ("2026-11-20", "US_STANDARD_OPTIONS_EXPIRY", "Equity, equity index, ETF and ETN options standard expiration", "option_expiration"),
    ("2026-12-15", "US_VIX_LAST_TRADE", "VIX options last trading day", "last_trade_date"),
    ("2026-12-16", "US_VIX_STANDARD_EXPIRY", "VIX options standard expiration", "option_expiration"),
    ("2026-12-17", "US_AM_INDEX_OPTIONS_LAST_TRADE", "AM-settled equity index options last trading day", "last_trade_date"),
    ("2026-12-18", "US_STANDARD_OPTIONS_EXPIRY", "Equity, equity index, ETF and ETN options standard expiration", "option_expiration"),
)


def _text(html):
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _stamp_event(event, now):
    event.update(source_verified_at=now.isoformat(),
                 coverage_expires_at=(now + timedelta(seconds=calendar.CACHE_TTL)).isoformat(),
                 schedule_status="confirmed")
    zone = event.get("timezone") or {"US": "America/New_York", "KR": "Asia/Seoul"}.get(event.get("market"))
    try:
        local_day = now.astimezone(ZoneInfo(zone)).date() if zone else None
    except (ZoneInfoNotFoundError, ValueError):
        local_day = None
    elapsed = bool(local_day and event.get("end_date", event["date"]) < local_day.isoformat())
    if event.get("release_precision") == "datetime":
        elapsed = datetime.fromisoformat(event["release_at"]) <= now
    event["event_status"] = "elapsed_unconfirmed" if elapsed else "scheduled"
    return event


def parse_census_advance(html, now):
    """Read only the ADVANCE table; the adjacent monthly table has other periods."""
    now = calendar._clock(now)
    if not isinstance(html, str) or len(html) > 2_000_000:
        raise calendar._InvalidCalendar("invalid_response")
    headings = list(re.finditer(r"<(h[1-6])\b[^>]*>(.*?)</\1>", html, re.I | re.S))
    sections = [html[h.end():headings[i + 1].start() if i + 1 < len(headings) else len(html)]
                for i, h in enumerate(headings)
                if _text(h[2]).casefold() == "advance monthly retail trade report"]
    if len(sections) != 1:
        raise calendar._InvalidCalendar("advance_section_unrecognized")
    tables = re.findall(r"<table\b[^>]*>.*?</table>", sections[0], re.I | re.S)
    if len(tables) != 1:
        raise calendar._InvalidCalendar("advance_table_unrecognized")
    table = calendar._ScheduleTable()
    table.feed(tables[0])
    if not table.rows or len(table.rows[0]) != 2:
        raise calendar._InvalidCalendar("advance_header_unrecognized")
    header = " ".join(table.rows[0])
    if not re.search(r"Data Month.*Release Date", header, re.I):
        raise calendar._InvalidCalendar("advance_header_unrecognized")
    has_clock = bool(re.search(r"\b8:30\s*a\.?m\.?\b", header, re.I))
    eastern = bool(re.search(r"\b(?:ET|Eastern(?: Standard| Daylight)? Time)\b", header, re.I)
                   or re.search(r"\bAll\b[^.]{0,60}\b(?:releases?|release times)\b[^.]{0,80}\bEastern(?: Standard| Daylight)? Time\b", _text(html), re.I))
    events = {}
    for cells in table.rows[1:121]:
        if len(cells) != 2:
            continue
        try:
            period = datetime.strptime(cells[0], "%B %Y").strftime("%Y-%m")
            day = datetime.strptime(cells[1], "%B %d, %Y").date()
        except ValueError:
            continue  # TBA/malformed rows never receive a guessed date.
        if day.strftime("%Y-%m") <= period:
            continue
        at, zone = day.isoformat(), ""
        if has_clock and eastern:
            try:
                zone = "America/New_York"
                at = datetime.combine(day, time(8, 30), ZoneInfo(zone)).isoformat()
            except ZoneInfoNotFoundError:
                zone = ""
        event = _stamp_event({"event": "US Advance Retail Sales", "indicator": "US_RETAIL_SALES",
            "period": period, "market": "US", "date": day.isoformat(), "release_at": at,
            "release_precision": "datetime" if "T" in at else "date", "timezone": zone,
            "release_time_confirmed": "T" in at, "event_kind": "scheduled_release",
            "source": "US Census Bureau Advance Retail", "source_url": CENSUS_URL,
            "time_note": "" if "T" in at else "공식 표의 발표시각·시간대 조합 미확인; 날짜만 사용"}, now)
        if period in events and events[period]["date"] != event["date"]:
            raise calendar._InvalidCalendar("conflicting_advance_dates")
        events[period] = event
    if not events:
        raise calendar._InvalidCalendar("advance_rows_unrecognized")
    return sorted(events.values(), key=lambda e: e["date"])


def parse_apec_meeting(html, now):
    """The named leaders' meeting only; never a bilateral-meeting confirmation."""
    now = calendar._clock(now)
    if not isinstance(html, str) or len(html) > 2_000_000:
        raise calendar._InvalidCalendar("invalid_response")
    events = {}
    for raw in re.findall(r"<p\b[^>]*>(.*?)</p>", html, re.I | re.S):
        paragraph = _text(raw).replace("’", "'")
        match = re.search(r"APEC Economic Leaders' Meeting on (\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)", paragraph)
        year = re.search(r"APEC Economic Leaders' (?:Week|Meeting) (20\d{2})", paragraph)
        if not match or not year:
            continue
        try:
            start = datetime.strptime(f"{match[1]} {match[3]} {year[1]}", "%d %B %Y").date()
            end = datetime.strptime(f"{match[2]} {match[3]} {year[1]}", "%d %B %Y").date()
        except ValueError:
            continue
        if not 0 <= (end - start).days <= 7:
            continue
        event = _stamp_event({"event": "APEC Economic Leaders' Meeting", "indicator": "APEC_LEADERS_MEETING",
            "market": "GLOBAL", "date": start.isoformat(), "start_date": start.isoformat(), "end_date": end.isoformat(),
            "release_at": start.isoformat(), "release_precision": "date", "release_time_confirmed": False,
            "timezone": "Asia/Shanghai" if "Shenzhen, China" in paragraph else "",
            "event_kind": "scheduled_meeting", "source": "APEC Secretariat", "source_url": APEC_URL,
            "scope_note": "공식 정상회의 일정; 별도 양자회담·합의 확정 근거 아님"}, now)
        events[(start, end)] = event
    if len(events) != 1:
        raise calendar._InvalidCalendar("apec_meeting_range_unrecognized")
    return list(events.values())


def _fetch_pdf(url, label):
    """One request, existing timeout, no redirects, at most 2 MB; no disk writes."""
    from stock_lab_core.report_io_audit import http_call, provider_label
    response = http_call(provider_label(url), calendar.requests.get, url, timeout=calendar.REQUEST_TIMEOUT, allow_redirects=False,
        stream=True, headers={"User-Agent": "StockLab-Release-Calendar/1.0"})
    try:
        if response.status_code != 200:
            raise calendar._InvalidCalendar(f"http_{response.status_code}")
        data = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if len(data) + len(chunk) > 2_000_000:
                raise calendar._InvalidCalendar(label + "_pdf_size_limit")
            data.extend(chunk)
        if data[:5] != b"%PDF-":
            raise calendar._InvalidCalendar(label + "_response_not_pdf")
        return bytes(data)
    finally:
        response.close()


def _fetch_cboe_sha256():
    return sha256(_fetch_pdf(CBOE_URL, "cboe")).hexdigest()


def parse_census_next_release_text(page, now):
    """An exact period/date/clock sentence, not the prior release's page-1 clock."""
    now = calendar._clock(now)
    text = " ".join(page.split())
    match = re.search(r"The ([A-Za-z]+ \d{4}) Advance Monthly Retail report is scheduled for release on "
        r"([A-Za-z]+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2})\s*(a\.?m\.?|p\.?m\.?)\s+(EST|EDT|ET)\b", text, re.I)
    if not match:
        raise calendar._InvalidCalendar("census_next_release_clock_unrecognized")
    period = datetime.strptime(match[1], "%B %Y").strftime("%Y-%m")
    day = datetime.strptime(match[2], "%B %d, %Y").date()
    clock = datetime.strptime(match[3] + " " + match[4].replace(".", "").upper(), "%I:%M %p").time()
    at = datetime.combine(day, clock, ZoneInfo("America/New_York"))
    if match[5].upper() != "ET" and at.tzname() != match[5].upper():
        raise calendar._InvalidCalendar("census_next_release_timezone_conflict")
    return [_stamp_event({"indicator": "US_RETAIL_SALES", "period": period, "date": day.isoformat(),
        "release_at": at.isoformat(), "release_precision": "datetime", "release_time_confirmed": True,
        "timezone": "America/New_York", "market": "US", "source_url": CENSUS_PDF_URL,
        "source_kind": "official_next_release_time"}, now)]


def _parse_census_next_release_pdf(data, now):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    try:
        reader = PdfReader(BytesIO(data))
        if len(reader.pages) < 2:
            raise calendar._InvalidCalendar("census_next_release_page_missing")
        page = reader.pages[1].extract_text() or ""
    except (PyPdfError, OSError) as exc:
        raise calendar._InvalidCalendar("census_next_release_pdf_unreadable") from exc
    return parse_census_next_release_text(page, now)


def _attach_census_clock(events, now):
    """One optional proof fetch, only when a collected retail date lacks a clock."""
    if not any(e["indicator"] == "US_RETAIL_SALES" and e["release_precision"] == "date" for e in events):
        return None
    proofs, source = calendar._load_source("US Census Bureau next-release clock", CENSUS_PDF_URL,
        lambda data: _parse_census_next_release_pdf(data, now), now,
        fetch=lambda: _fetch_pdf(CENSUS_PDF_URL, "census"), cache_scope="market_watch_next_retail_clock_v1")
    for event in events:
        for proof in proofs:
            if (event["indicator"], event.get("period"), event["date"]) != (proof["indicator"], proof["period"], proof["date"]):
                continue
            if event["release_precision"] != "date":
                continue
            event["calendar_source_url"] = event["source_url"]
            for key in ("release_at", "release_precision", "release_time_confirmed", "timezone", "source_url", "source_kind", "event_status"):
                event[key] = proof[key]
            event["source_verified_at"] = min(event["source_verified_at"], proof["source_verified_at"])
            event["coverage_expires_at"] = min(event["coverage_expires_at"], proof["coverage_expires_at"])
            event["time_note"] = "공식 MARTS PDF의 동일 대상 월·발표일 문장 확인"
    metadata = {key: proofs[0][key] for key in ("source_verified_at", "coverage_expires_at")} if proofs else {}
    return dict(source, source_url=CENSUS_PDF_URL, **metadata)


def _cboe_events(document_hash, now):
    if document_hash != CBOE_SHA256:
        raise calendar._InvalidCalendar("cboe_pdf_sha256_changed")
    events = []
    for day, indicator, event, kind in _CBOE_DATES:
        row = _stamp_event({"event": event, "indicator": indicator, "event_kind": kind,
            "market": "US", "date": day, "release_at": day, "release_precision": "date",
            "release_time_confirmed": False, "timezone": "America/New_York",
            "source": "Cboe options expiration calendar", "source_url": CBOE_URL,
            "source_kind": "verified_calendar_mapping", "verified_at": CBOE_VERIFIED_AT,
            "expires_at": CBOE_EXPIRES_AT.isoformat(), "source_sha256": CBOE_SHA256,
            "scope_note": "2026년 11–12월 시각 검증 매핑; 마지막 거래일과 만기일 구분, 시각 미확인"}, now)
        row["coverage_expires_at"] = min(datetime.fromisoformat(row["coverage_expires_at"]), CBOE_EXPIRES_AT).isoformat()
        events.append(row)
    return events


def _load_cboe_source(now):
    name = "Cboe options expiration calendar"
    # Check before cache access, so an otherwise fresh cache cannot extend the
    # manually verified year/coverage window or be replayed before verification.
    if now.date().isoformat() < CBOE_VERIFIED_AT or now >= CBOE_EXPIRES_AT:
        return [], {"name": name, "status": "unavailable", "reason": "cboe_verified_mapping_outside_validity"}
    return calendar._load_source(name, CBOE_URL, lambda digest: _cboe_events(digest, now), now,
        fetch=_fetch_cboe_sha256, cache_scope="market_watch_cboe_" + CBOE_SHA256)


def load_market_watch_calendar(now=None):
    """Return {events, sources, connected}; up to four requests, success cache.

    Events retain all explicit source dates; the report selects its own horizon.
    Date-only release_at is a date, never midnight or an assumed 08:30 ET.
    """
    now = calendar._clock(now)
    specs = (("US Census Bureau Advance Retail", CENSUS_URL, parse_census_advance),
             ("APEC Secretariat", APEC_URL, parse_apec_meeting))
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(calendar._load_source, name, url, lambda html, p=parser: p(html, now), now,
                                   cache_scope="market_watch_calendar_v1") for name, url, parser in specs]
        futures.append(executor.submit(_load_cboe_source, now))
        results = [future.result() for future in futures]
    events, sources = [], []
    for url, (rows, source) in zip([s[1] for s in specs] + [CBOE_URL], results):
        events.extend(rows)
        metadata = {key: rows[0][key] for key in ("source_verified_at", "coverage_expires_at", "source_kind",
                    "verified_at", "expires_at", "source_sha256") if key in rows[0]} if rows else {}
        sources.append(dict(source, source_url=url, **metadata))
    clock_source = _attach_census_clock(events, now)
    if clock_source is not None:
        sources.append(clock_source)
    return {"events": sorted(events, key=lambda e: (e["date"], e["indicator"])), "sources": sources,
            "connected": any(source["status"] == "connected" for source in sources)}
