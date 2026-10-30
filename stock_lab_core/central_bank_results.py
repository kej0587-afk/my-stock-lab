"""Official FOMC/BOJ decisions, separate from calendars and daily rate series.

``fetch_central_bank_results(now=None)`` returns one row per bank. ``date`` is
the KST release date when its time is published; ``decision_date`` is the
bank-local official decision day. Missing results have no fact or rate values.
The most recent scheduled meeting ending on/before the bank-local report day
is checked, never silently replaced by a previous meeting. This is a live
collector, not a point-in-time archive. No news headline authorizes a result.
"""

from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, time as day_time, timedelta, timezone
from fractions import Fraction
from io import BytesIO
import re
import threading
import time
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html as html_parser
import requests

from stock_lab_core.release_calendar import FOMC_URL, _clock, _fomc_events
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

BOJ_CALENDAR_URL = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
BOJ_STATEMENTS_URL = "https://www.boj.or.jp/en/mopo/mpmdeci/state_{year}/"
REQUEST_TIMEOUT = (2.0, 3.0)
BANK_BUDGET_SECONDS = 15.0
CACHE_TTL = 900
MAX_BYTES = 4_000_000
MAX_PAGES = 12
_KST = timezone(timedelta(hours=9))
_CACHE = OrderedDict()
_LOCK = threading.Lock()
_MONTHS = {name: i for i, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_RATE = r"(?:\d+-\d+/\d+|\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"


class _Unavailable(ValueError):
    pass


def clear_central_bank_results_cache():
    """Clear only this collector's bounded, successful-result cache."""
    with _LOCK:
        _CACHE.clear()


def _flat(value):
    return " ".join(value.split())


def _official_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and not parsed.username and not parsed.password
            and parsed.netloc in {"www.federalreserve.gov", "www.boj.or.jp"}
            and not parsed.query and not parsed.fragment)


def _request(url, deadline):
    if not _official_url(url):
        raise _Unavailable("non_official_url")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _Unavailable("collection_deadline")
    response = requests.get(url, stream=True, allow_redirects=False,
                            timeout=tuple(min(t, remaining) for t in REQUEST_TIMEOUT),
                            headers={"User-Agent": "StockLab-Central-Bank-Results/1.0"})
    try:
        if response.status_code != 200:
            raise _Unavailable("http_" + str(response.status_code))
        if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
            raise _Unavailable("document_too_large")
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=16_384):
            size += len(chunk)
            if size > MAX_BYTES:
                raise _Unavailable("document_too_large")
            if time.monotonic() > deadline:
                raise _Unavailable("collection_deadline")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


def _document(data):
    if not data or len(data) > MAX_BYTES:
        raise _Unavailable("invalid_html")
    root = html_parser.fromstring(data)
    for element in root.xpath("//script|//style|//noscript"):
        element.drop_tree()
    return root


def _english_date(value):
    match = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", _flat(value))
    if not match or match[1][:3].lower() not in _MONTHS:
        raise _Unavailable("official_date_unrecognized")
    return date(int(match[3]), _MONTHS[match[1][:3].lower()], int(match[2]))


def _latest(days, local_day):
    eligible = [d for d in days if 0 <= (local_day - d).days <= 120]
    if not eligible:
        raise _Unavailable("recent_official_meeting_unavailable")
    return max(eligible)


def _boj_meeting_day(data, now):
    root = _document(data)
    days = []
    for table in root.xpath("//table"):
        caption = _flat(" ".join(table.xpath("./caption//text()")))
        year = re.fullmatch(r"Table\s*:\s*(\d{4})", caption)
        if not year:
            continue
        for row in table.xpath(".//tr")[:24]:
            cells = row.xpath("./td")
            if not cells:
                continue
            value = _flat(cells[0].text_content())
            match = re.match(r"([A-Za-z]+)\.? (\d{1,2}) \([^)]*\), (\d{1,2}) \([^)]*\)", value)
            if match and match[1][:3].lower() in _MONTHS:
                days.append(date(int(year[1]), _MONTHS[match[1][:3].lower()], int(match[3])))
    return _latest(days, now.astimezone(_KST).date())


def _statement_link(data, bank, day, base):
    root = _document(data)
    matches = set()
    if bank == "FOMC":
        path = f"/newsevents/pressreleases/monetary{day:%Y%m%d}a.htm"
        for href in root.xpath("//a/@href"):
            url = urljoin(base, href)
            if _official_url(url) and urlsplit(url).hostname == "www.federalreserve.gov" and urlsplit(url).path == path:
                matches.add(url)
    else:
        for row in root.xpath("//table//tr")[:100]:
            cells = row.xpath("./td")
            if len(cells) != 2:
                continue
            try:
                row_day = _english_date(cells[0].text_content())
            except ValueError:
                continue
            if row_day != day:
                continue
            for anchor in cells[1].xpath(".//a[@href]"):
                title = _flat(anchor.text_content()).split(" [PDF", 1)[0]
                url = urljoin(base, anchor.get("href"))
                path = rf"/en/mopo/mpmdeci/(?:mpr|state)_{day.year}/k{day:%y%m%d}a\.(?:pdf|htm)"
                if (title in {"Statement on Monetary Policy", "Change in the Guideline for Money Market Operations"}
                        and _official_url(url) and urlsplit(url).hostname == "www.boj.or.jp"
                        and re.fullmatch(path, urlsplit(url).path)):
                    matches.add(url)
    if len(matches) != 1:
        raise _Unavailable("official_statement_link_unavailable")
    return matches.pop()


def _number(value):
    parts = value.replace("-", " ").split()
    result = float(sum(Fraction(part) for part in parts))
    if not 0 <= result <= 100:
        raise _Unavailable("invalid_policy_rate")
    return result


def _fed_result(data, day, now):
    root = _document(data)
    dates = root.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' article__time ')]")
    if len(dates) != 1 or _english_date(dates[0].text_content()) != day:
        raise _Unavailable("decision_date_mismatch")
    headings = [_flat(h.text_content()) for h in root.xpath("//h3")]
    if "Federal Reserve issues FOMC statement" not in headings:
        raise _Unavailable("statement_identity_mismatch")
    paragraphs = [_flat(p.text_content()) for p in root.xpath("//p")]
    clocks = [re.fullmatch(r"For release at (\d{1,2}):(\d{2}) (a\.m\.|p\.m\.) (EDT|EST)", p) for p in paragraphs]
    clocks = [m for m in clocks if m]
    if len(clocks) != 1:
        raise _Unavailable("release_time_unconfirmed")
    clock = clocks[0]
    hour = int(clock[1])
    if not 1 <= hour <= 12:
        raise _Unavailable("release_time_unconfirmed")
    hour = hour % 12 + (12 if clock[3] == "p.m." else 0)
    release = datetime.combine(day, day_time(hour, int(clock[2])), ZoneInfo("America/New_York"))
    if release.tzname() != clock[4]:
        raise _Unavailable("release_timezone_mismatch")
    if release > now:
        raise _Unavailable("release_after_report_time")
    pattern = (r"\bThe Committee decided to (maintain|lower|raise) the target range for the federal funds rate "
               r"(?:by " + _RATE + r" percentage point(?:s)? )?(?:at|to) (" + _RATE + r") to (" + _RATE + r") percent\b")
    matches = [m for p in paragraphs for m in re.finditer(pattern, p, re.I)]
    if len(matches) != 1:
        raise _Unavailable("policy_decision_unrecognized")
    match = matches[0]
    low, high = _number(match[2]), _number(match[3])
    if low > high:
        raise _Unavailable("invalid_target_range")
    action = {"maintain": "hold", "lower": "cut", "raise": "hike"}[match[1].lower()]
    return dict(fact=f"FOMC target range: {low:g}-{high:g}% ({action}).",
                action=action, rate_lower=low, rate_upper=high, policy_rate=None,
                release_at=release.isoformat(), release_precision="datetime",
                date=release.astimezone(_KST).date().isoformat())


def _pdf_text(data, now):
    if len(data) > MAX_BYTES or not data.startswith(b"%PDF-"):
        raise _Unavailable("invalid_pdf")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise _Unavailable("pdf_reader_unavailable") from exc
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PAGES:
            raise _Unavailable("invalid_pdf_pages")
        for attr in ("creation_date", "modification_date"):
            version = getattr(reader.metadata, attr, None)
            if version and (version.replace(tzinfo=_KST) if version.tzinfo is None else version) > now:
                raise _Unavailable("document_version_after_report_time")
        pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
        if sum(len(page) for page in pages) > 200_000:
            raise _Unavailable("pdf_text_too_large")
        return _flat(" ".join(pages))
    except _Unavailable:
        raise
    except Exception as exc:
        raise _Unavailable("invalid_pdf") from exc


def _boj_result(data, day, now, *, pdf=True):
    body = _pdf_text(data, now) if pdf else _flat(_document(data).text_content())
    header = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})\s+Bank of Japan\s+"
                       r"(Statement on Monetary Policy|Change in the Guideline for Money Market Operations)", body)
    if not header or _english_date(header[1]) != day:
        raise _Unavailable("decision_date_mismatch")
    body = body[header.end():]
    if not re.search(r"At the Monetary Policy Meeting(?: \(MPM\))? held today, the Policy Board of the Bank of Japan decided", body[:1000]):
        raise _Unavailable("policy_decision_unrecognized")
    # The adopted guideline precedes dissenting proposals and reference material.
    adopted = body.split("[Note] Voting", 1)[0]
    matches = re.findall(r"The Bank will encourage the uncollateralized overnight call rate to remain at around (\d+(?:\.\d+)?) percent", adopted)
    if len(matches) != 1:
        raise _Unavailable("policy_rate_unrecognized")
    rate = _number(matches[0])
    release = None
    schedule = body.split("Release dates and times:", 1)
    if len(schedule) == 2:
        clock = re.search(r"Statement on Monetary Policy\s*[-\u2013\u2014]+\s*[A-Za-z]+,\s*"
                          r"([A-Za-z]+ \d{1,2}) at (\d{1,2}):(\d{2})", schedule[1])
        if clock:
            if _english_date(clock[1] + f", {day.year}") != day:
                raise _Unavailable("release_date_mismatch")
            release = datetime.combine(day, day_time(int(clock[2]), int(clock[3])), _KST)
    if release and release > now:
        raise _Unavailable("release_after_report_time")
    if not release and day >= now.astimezone(_KST).date():
        raise _Unavailable("same_day_release_time_unconfirmed")
    # "Remain at around" describes the target, not a change versus the last MPM.
    return dict(fact=f"BOJ overnight call-rate target: around {rate:g}%.",
                action="set_target", policy_rate=rate, rate_lower=None, rate_upper=None,
                release_at=release.isoformat() if release else None,
                release_precision="datetime" if release else "date", date=day.isoformat())


def _load_bank(bank, now):
    calendar_url = FOMC_URL if bank == "FOMC" else BOJ_CALENDAR_URL
    row = dict(bank=bank, event=f"{bank} policy decision", market="US" if bank == "FOMC" else "JP",
               indicator="US_FED_RATE_DECISION" if bank == "FOMC" else "JP_BOJ_RATE_DECISION",
               fact=None, date=None, decision_date=None, scheduled_date=None,
               source="Federal Reserve" if bank == "FOMC" else "Bank of Japan",
               source_url=calendar_url, calendar_url=calendar_url, status="missing", reason="",
               action=None, policy_rate=None, rate_lower=None, rate_upper=None, unit="%",
               release_at=None, release_precision="unconfirmed", checked_at=now.isoformat(),
               from_cache=False, price_reaction_verified=False)
    deadline = time.monotonic() + BANK_BUDGET_SECONDS
    try:
        calendar = _request(calendar_url, deadline)
        if bank == "FOMC":
            local = now.astimezone(ZoneInfo("America/New_York"))
            days = [date.fromisoformat(e["date"]) for e in _fomc_events(calendar.decode("utf-8"), local)]
            day = _latest(days, local.date())
        else:
            day = _boj_meeting_day(calendar, now)
        row.update(scheduled_date=day.isoformat())
        listing_url = calendar_url if bank == "FOMC" else BOJ_STATEMENTS_URL.format(year=day.year)
        listing = calendar if bank == "FOMC" else _request(listing_url, deadline)
        url = _statement_link(listing, bank, day, listing_url)
        row["source_url"] = url
        data = _request(url, deadline)
        result = _fed_result(data, day, now) if bank == "FOMC" else _boj_result(data, day, now, pdf=url.endswith(".pdf"))
        row.update(result, status="official", decision_date=day.isoformat())
    except _Unavailable as exc:
        row["reason"] = str(exc)
    except requests.RequestException as exc:
        row["reason"] = "request_failed:" + type(exc).__name__
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, html_parser.etree.ParserError):
        row["reason"] = "invalid_official_response"
    return row


def fetch_central_bank_results(now=None):
    """Return FOMC and BOJ rows; max five requests, no retries or failed cache.

    Naive ``now`` follows release_calendar's UTC convention. Each bank has a
    request/size budget. Only verified decisions are cached for 15 minutes;
    caller mutation, clock rollback and a new local day cannot reuse them.
    Missing ``scheduled_date`` means even the calendar could not be confirmed.
    """
    now = _clock(now)
    results = []
    for bank in ("FOMC", "BOJ"):
        local = now.astimezone(ZoneInfo("America/New_York") if bank == "FOMC" else _KST)
        key = (bank, local.date().isoformat())
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and 0 <= time.monotonic() - cached[0] < CACHE_TTL and cached[1] <= now:
                row = deepcopy(cached[2])
                row["from_cache"] = True
                results.append(row)
                continue
        row = _load_bank(bank, now)
        if row["status"] == "official":
            with _LOCK:
                _CACHE[key] = (time.monotonic(), now, deepcopy(row))
                _CACHE.move_to_end(key)
                while len(_CACHE) > 16:
                    _CACHE.popitem(last=False)
        results.append(row)
    return results
