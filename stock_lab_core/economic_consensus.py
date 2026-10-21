"""Exact-release survey consensus from Trading Economics API/public tables.

``load_economic_consensus(release_rows, now=None, *, api_key=None, fetch=None,
public_fallback=True)``
returns ``{"events": [...], "diagnostics": {...}}``. Events use the existing
economic_releases input schema. Match all of indicator, observation month,
basis, unit and UTC release date before attaching their forecast fields.

TE API ``Forecast`` is survey consensus; ``TEForecast`` is proprietary. Neither
actuals nor previous values are used as forecasts. The API requires ReferenceDate.
Four unrestricted indicator pages also expose complete release dates and separate
Consensus/TEForecast columns. Their yearless reference month is only a check
against the caller's verified official period, never a source for its year.
Public matching requires official observation and release-schedule source URLs
and a unique indicator/basis/unit/release-date key among ALL caller rows.
No environment variables, Streamlit secrets, or other credentials are read.

Setup: subscribe for economic-calendar access including US/Korea and the
requested date range at https://tradingeconomics.com/api/pricing.aspx ; obtain
the API credential at https://developer.tradingeconomics.com/ and pass it as
api_key. The documented guest account returned HTTP 410 on 2026-10-21.
Docs: https://docs.tradingeconomics.com/get_started/
https://docs.tradingeconomics.com/economic_calendar/country/
https://docs.tradingeconomics.com/economic_calendar/schema/

Fetch injection follows requests.get(url, **kwargs) and returns a response with
status_code, iter_content() and close(). Only a bounded JSON body is consumed.
``now`` bounds retrieval time, not a historical data vintage. Never treat this
endpoint as a point-in-time archive of pre-release survey expectations.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
from itertools import islice
import json
import math
import re
import threading
import time
from urllib.parse import quote, urlsplit

from lxml import etree, html
import requests

from stock_lab_core.report_build import register_loaded_source


register_loaded_source(__name__, __file__)


API_URL = "https://api.tradingeconomics.com/calendar/country/"
SCHEMA_URL = "https://docs.tradingeconomics.com/economic_calendar/schema/"
SETUP_URL = "https://docs.tradingeconomics.com/get_started/"
PRICING_URL = "https://tradingeconomics.com/api/pricing.aspx"
PROVIDER = "Trading Economics survey consensus"
REQUEST_TIMEOUT = 4.0
CACHE_TTL = 900
FAILURE_TTL = 60
MAX_RELEASE_ROWS = 64
MAX_PROVIDER_ROWS = 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_WINDOW_DAYS = 45
_CACHE_LIMIT = 16
_CACHE = OrderedDict()
_LOCK = threading.Lock()

# Exact event names keep headline/core and total/ex-auto variants separate.
_EVENTS = {
    ("United States", "Inflation Rate MoM"): ("US_CPI", "MoM", "%"),
    ("United States", "Inflation Rate YoY"): ("US_CPI", "YoY", "%"),
    ("United States", "Core Inflation Rate MoM"): ("US_CORE_CPI", "MoM", "%"),
    ("United States", "Core Inflation Rate YoY"): ("US_CORE_CPI", "YoY", "%"),
    ("United States", "PPI MoM"): ("US_PPI", "MoM", "%"),
    ("United States", "PPI YoY"): ("US_PPI", "YoY", "%"),
    ("United States", "Core PPI MoM"): ("US_CORE_PPI", "MoM", "%"),
    ("United States", "Core PPI YoY"): ("US_CORE_PPI", "YoY", "%"),
    ("United States", "Non Farm Payrolls"): ("US_NONFARM_PAYROLLS", "MoM", "thousand persons"),
    ("United States", "Unemployment Rate"): ("US_UNEMPLOYMENT", "level", "%"),
    ("United States", "Retail Sales MoM"): ("US_RETAIL_SALES", "MoM", "%"),
    ("United States", "Retail Sales Ex Autos MoM"): ("US_CORE_RETAIL_SALES", "MoM", "%"),
    ("South Korea", "Inflation Rate MoM"): ("KR_CPI", "MoM", "%"),
    ("South Korea", "Inflation Rate YoY"): ("KR_CPI", "YoY", "%"),
    ("South Korea", "Core Inflation Rate YoY"): ("KR_CORE_CPI", "YoY", "%"),
    ("South Korea", "Exports YoY"): ("KR_EXPORTS", "YoY", "%"),
}
_SUPPORTED = set(_EVENTS.values())
_PUBLIC_ROOT = "https://tradingeconomics.com/united-states/"
# Only these four pages were inspected; do not extrapolate sibling URL schemas.
_PUBLIC_PAGES = {
    ("US_CPI", "YoY", "%"): (_PUBLIC_ROOT + "inflation-cpi", "Inflation Rate YoY", "Inflation Rate", "bls.gov"),
    ("US_PPI", "YoY", "%"): (_PUBLIC_ROOT + "producer-prices-change", "PPI YoY", "Producer Prices Change", "bls.gov"),
    ("US_NONFARM_PAYROLLS", "MoM", "thousand persons"): (
        _PUBLIC_ROOT + "non-farm-payrolls", "Non Farm Payrolls", "Non Farm Payrolls", "bls.gov"),
    ("US_RETAIL_SALES", "MoM", "%"): (_PUBLIC_ROOT + "retail-sales", "Retail Sales MoM", "Retail Sales MoM", "census.gov"),
}
_PUBLIC_BY_URL = {entry[0]: (spec, entry) for spec, entry in _PUBLIC_PAGES.items()}
_MONTHS = {name.lower(): f"{index:02d}" for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


class _Unavailable(ValueError):
    pass


def clear_economic_consensus_cache():
    """Clear the bounded process-local cache, including short-lived failures."""
    with _LOCK:
        _CACHE.clear()


def _clock(now):
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime")
    return (now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now).astimezone(timezone.utc)


def _date(value, *, provider=False):
    text = str(value or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text).isoformat()
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if at.tzinfo is None:
            if not provider:
                return None
            at = at.replace(tzinfo=timezone.utc)  # TE documents Date as UTC.
        return at.astimezone(timezone.utc).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def consensus_key(row):
    """Return (indicator, period, basis, unit, UTC release date), else None.

    Only complete, supported monthly keys are accepted. In particular, a rate
    decision/range is not equated with the Fed's daily upper target limit.
    """
    if not isinstance(row, dict):
        return None
    indicator, basis, unit = (row.get(field) for field in ("indicator", "basis", "unit"))
    if not all(isinstance(value, str) for value in (indicator, basis, unit)):
        return None
    if (indicator, basis, unit) not in _SUPPORTED:
        return None
    period = row.get("period")
    if not isinstance(period, str) or not re.fullmatch(r"\d{4}-\d{2}", period):
        return None
    try:
        date.fromisoformat(period + "-01")
    except ValueError:
        return None
    release = _date(row.get("release_at"))
    if (not release or row.get("release_precision") == "schedule_rule"
            or row.get("release_time_confirmed") is False):
        return None
    return indicator, period, basis, unit, release


def _forecast(value, unit, provider_unit):
    if value is None or isinstance(value, bool):
        return None
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([%KkMm]?)", str(value).strip())
    if not match:
        return None
    number, suffix = float(match[1]), match[2].upper()
    reported = str(provider_unit or "").strip().upper()
    if unit == "%":
        if reported != "%" or suffix not in {"", "%"}:
            return None
    else:
        # Provider Unit K/M describes scaled payroll changes, not percent rates.
        if reported not in {"K", "M"} or suffix not in {"", reported}:
            return None
        if reported == "M":
            number *= 1000
    return number if math.isfinite(number) else None


def _normalize(item, retrieved_at, source_url):
    if not isinstance(item, dict):
        return None
    names = item.get("Country"), item.get("Event")
    if not all(isinstance(value, str) for value in names):
        return None
    spec = _EVENTS.get(names)
    if spec is None or str(item.get("DateSpan")) != "0":
        return None
    release = _date(item.get("Date"), provider=True)
    reference = _date(item.get("ReferenceDate"), provider=True)
    if not release or not reference or reference[:7] > release[:7]:
        return None
    indicator, basis, unit = spec
    forecast = _forecast(item.get("Forecast"), unit, item.get("Unit"))
    if forecast is None:
        return None
    return _event(spec, reference[:7], release, forecast, names[1], retrieved_at, source_url)


def _event(spec, period, release, forecast, title, retrieved_at, source_url):
    indicator, basis, unit = spec
    return {
        "indicator": indicator, "period": period, "basis": basis, "unit": unit,
        "release_at": release, "release_precision": "date",
        "release_time_confirmed": True, "raw_title": title,
        "actual": None, "previous": None, "forecast": forecast,
        "forecast_unit": unit, "forecast_basis": basis,
        "source": PROVIDER, "source_url": source_url,
        "forecast_source": PROVIDER, "forecast_source_url": source_url,
        "forecast_kind": "survey_consensus", "retrieved_at": retrieved_at,
    }


def _public_table(body, url):
    """Parse only the inspected, visible recent-release table, never scripts."""
    try:
        tables = html.fromstring(body).xpath("//table[@id='calendar']")
    except (etree.ParserError, ValueError):
        raise _Unavailable("public_schema_changed") from None
    expected = ["Calendar", "GMT", "Reference", "Actual", "Previous", "Consensus", "TEForecast"]
    if len(tables) != 1 or [" ".join(th.text_content().split())
                            for th in tables[0].xpath(".//th")] != expected:
        raise _Unavailable("public_schema_changed")
    spec, (_, event, category, _) = _PUBLIC_BY_URL[url]
    rows = tables[0].xpath(".//tr[td]")
    if len(rows) > 16:
        raise _Unavailable("too_many_public_rows")
    records = []
    for row in rows:
        cells = row.xpath("./td")
        # The GMT heading spans the otherwise hidden event-name column.
        if (len(cells) != 8 or row.get("data-country") != "United States"
                or row.get("data-category") != category or not row.get("data-id")
                or " ".join(cells[2].text_content().split()) != event
                or [cell.get("id") for cell in cells[3:6]] != ["reference", "actual", "previous"]):
            raise _Unavailable("public_schema_changed")
        release_text, reference, forecast_text = (
            " ".join(cells[index].text_content().split()) for index in (0, 3, 6))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_text) or not _date(release_text):
            raise _Unavailable("public_full_release_date_required")
        month = _MONTHS.get(reference.lower())
        if not month:
            continue
        # Public values must carry their units; a bare number is ambiguous.
        suffix = forecast_text[-1:].upper()
        if (spec[2] == "%" and suffix != "%") or (spec[2] != "%" and suffix not in {"K", "M"}):
            continue
        forecast = _forecast(forecast_text, spec[2], suffix)
        if forecast is not None:
            records.append({"release": release_text, "month": month,
                            "reference": reference, "forecast": forecast})
    return records


def _request(url, api_key, fetch):
    public = url in _PUBLIC_BY_URL
    kwargs = {"headers": {"User-Agent": "StockLab-Economic-Consensus/1.0"},
              "timeout": REQUEST_TIMEOUT, "allow_redirects": False, "stream": True}
    if not public:
        kwargs["headers"]["Authorization"] = api_key
        kwargs["params"] = {"f": "json"}
    session, response = None, None
    if fetch is requests.get:
        session = requests.Session()
        session.trust_env = False
        fetch = session.get
    started = time.monotonic()
    try:
        response = fetch(url, **kwargs)
        status = response.status_code
        if status != 200:
            reason = {401: "api_key_rejected", 403: "calendar_subscription_required",
                      410: "guest_access_discontinued", 429: "rate_limited"}.get(status, "http_error")
            if public and status in {401, 403}:
                reason = "public_access_denied"
            return [], reason, status
        body = bytearray()
        for chunk in response.iter_content(chunk_size=16384):
            if time.monotonic() - started > 6:
                raise _Unavailable("response_deadline")
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise _Unavailable("response_too_large")
        if public:
            return _public_table(bytes(body), url), "", status
        payload = json.loads(body)
        if not isinstance(payload, list):
            raise _Unavailable("invalid_response")
        if len(payload) > MAX_PROVIDER_ROWS:
            raise _Unavailable("too_many_provider_rows")
        return payload, "", status
    finally:
        if response is not None:
            response.close()
        if session is not None:
            session.close()


def _cached(url, api_key, fetch, now):
    key = (url, hashlib.sha256(api_key.encode()).digest(), id(fetch))
    tick = time.monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and entry[1] is fetch:
            _, _, stored, payload, reason, status, retrieved_at = entry
            ttl = FAILURE_TTL if reason else CACHE_TTL
            if tick - stored < ttl and retrieved_at <= now.isoformat():
                _CACHE.move_to_end(key)
                return deepcopy(payload), reason, status, retrieved_at, True
    try:
        payload, reason, status = _request(url, api_key, fetch)
    except _Unavailable as exc:
        payload, reason, status = [], str(exc), 200
    except requests.RequestException:
        payload, reason, status = [], "request_failed", None
    except (ValueError, TypeError, AttributeError, OverflowError):
        payload, reason, status = [], "invalid_response", None
    retrieved_at = now.isoformat()
    with _LOCK:
        _CACHE[key] = (url, fetch, time.monotonic(), deepcopy(payload), reason, status, retrieved_at)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return payload, reason, status, retrieved_at, False


def _official_url(value, domain):
    try:
        parts = urlsplit(str(value or ""))
        return (parts.scheme in {"http", "https"} and not parts.username and not parts.password
                and (parts.hostname == domain or (parts.hostname or "").endswith("." + domain)))
    except ValueError:
        return False


def _public_fallback(rows, keys, now, fetch, result):
    diagnostics = result["diagnostics"]
    public = {"status": "unavailable", "reason": "verified_official_release_required", "sources": []}
    diagnostics["public"] = public
    # Ambiguous caller periods sharing one release date cannot lend a year.
    periods = {}
    for row in rows:
        key = consensus_key(row)
        if key:
            periods.setdefault((key[0], key[2], key[3], key[4]), set()).add(key[1])
    targets = {}
    for row in rows:
        key = consensus_key(row)
        if key not in keys:
            continue
        spec = key[0], key[2], key[3]
        if spec not in _PUBLIC_PAGES:
            continue
        url, _, _, domain = _PUBLIC_PAGES[spec]
        if (row.get("value_kind") not in {"official_observation", "calculated_from_official_levels"}
                or not _official_url(row.get("source_url"), domain)
                or not _official_url(row.get("release_source_url"), domain)
                or len(periods[(key[0], key[2], key[3], key[4])]) != 1
                or key[1] > key[4][:7]):
            continue
        targets.setdefault(url, set()).add(key)
    matches, conflicts = {}, set()
    ordered_targets = sorted(targets.items())
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda item: _cached(item[0], "", fetch, now), ordered_targets))
    for (url, wanted), response in zip(ordered_targets, responses):
        payload, reason, status, retrieved_at, cached = response
        public["sources"].append({"source_url": url, "reason": reason, "http_status": status,
                                  "from_cache": cached, "retrieved_at": retrieved_at})
        diagnostics["attempted"] |= not cached
        spec, (_, title, _, _) = _PUBLIC_BY_URL[url]
        if reason:
            continue
        for item in payload:
            for key in wanted:
                if item["release"] != key[4] or item["month"] != key[1][5:7]:
                    continue
                event = _event(spec, key[1], key[4], item["forecast"], title, retrieved_at, url)
                event.update(forecast_period_source="verified_official_row_exact_release_join",
                             provider_reference=item["reference"])
                if key in matches and matches[key]["forecast"] != event["forecast"]:
                    conflicts.add(key)
                matches[key] = event
    events = [matches[key] for key in sorted(matches) if key not in conflicts]
    result["events"].extend(events)
    if public["sources"]:
        public.update(status="available" if events else "unavailable", reason="" if events else
                      "conflicting_consensus" if conflicts else "exact_public_consensus_unavailable")
    elif not any((key[0], key[2], key[3]) in _PUBLIC_PAGES for key in keys):
        public["reason"] = "public_indicator_not_supported"
    public["matched_count"] = len(events)
    if not diagnostics.get("endpoint_url"):
        diagnostics.update(access_mode="public", from_cache=bool(public["sources"]) and
                           all(source["from_cache"] for source in public["sources"]))
        if len(public["sources"]) == 1:
            diagnostics["http_status"] = public["sources"][0]["http_status"]
    elif events:
        diagnostics["access_mode"] = "api_and_public"
    if events or not diagnostics.get("endpoint_url"):
        diagnostics.update(status="available" if result["events"] else "unavailable",
                           matched_count=len(result["events"]), reason="" if events else public["reason"])
    return result


def load_economic_consensus(release_rows, now=None, *, api_key=None, fetch=None, public_fallback=True):
    """Load consensus for at most 64 exact releases in a 45-day window.

    At most one API request and four allowlisted public pages, no retries or
    redirects, 4-second request timeout, 2 MiB/1024-row body limit per response,
    16 cache entries; successful cache TTL is 15 minutes and errors
    60 seconds. Unavailable results always contain an empty events list, and
    diagnostics never include response bodies, request exceptions or API keys.
    Caller supplies already-normalized release rows (iterable, dict or frame).
    Public fallback is enabled without a key and for missing API matches. It
    requires value_kind official_observation/calculated_from_official_levels,
    official source_url and release_source_url on each joined caller row.
    """
    now = _clock(now)
    diagnostics = {
        "provider": PROVIDER, "status": "unavailable", "reason": "api_key_required",
        "setup_url": SETUP_URL, "pricing_url": PRICING_URL, "source_url": SCHEMA_URL,
        "setup": "Subscribe for economic-calendar country/date access; obtain the API credential at "
                 "https://developer.tradingeconomics.com/ and pass api_key explicitly.",
        "attempted": False, "from_cache": False, "http_status": None,
        "requested_count": 0, "matched_count": 0,
    }
    result = {"events": [], "diagnostics": diagnostics}
    configured = isinstance(api_key, str) and bool(api_key.strip())
    if configured and api_key.strip().lower() in {"guest", "guest:guest"}:
        diagnostics["reason"] = "guest_access_discontinued"
        configured = False
    if not configured and not public_fallback:
        return result
    if hasattr(release_rows, "to_dict") and not isinstance(release_rows, dict):
        release_rows = release_rows.head(MAX_RELEASE_ROWS + 1).to_dict("records")
    if isinstance(release_rows, dict):
        release_rows = [release_rows]
    try:
        rows = list(islice(release_rows if release_rows is not None else (), MAX_RELEASE_ROWS + 1))
    except TypeError:
        diagnostics["reason"] = "complete_release_keys_required"
        return result
    if len(rows) > MAX_RELEASE_ROWS:
        diagnostics["reason"] = "too_many_release_rows"
        return result
    keys = {key for row in rows if (key := consensus_key(row)) is not None}
    diagnostics["requested_count"] = len(keys)
    if not keys:
        diagnostics["reason"] = "complete_release_keys_required"
        return result
    dates = sorted(key[4] for key in keys)
    if (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days >= MAX_WINDOW_DAYS:
        diagnostics["reason"] = "release_window_too_wide"
        return result
    fetch = fetch or requests.get
    if not configured:
        return _public_fallback(rows, keys, now, fetch, result)
    countries = sorted({"united states" if key[0].startswith("US_") else "south korea" for key in keys})
    url = API_URL + quote(",".join(countries), safe=",") + "/" + dates[0] + "/" + dates[-1]
    diagnostics["endpoint_url"] = url
    payload, reason, status, retrieved_at, cached = _cached(url, api_key.strip(), fetch, now)
    diagnostics.update(access_mode="api", attempted=not cached, from_cache=cached,
                       http_status=status, retrieved_at=retrieved_at)
    if reason:
        diagnostics["reason"] = reason
        if public_fallback:
            return _public_fallback(rows, keys, now, fetch, result)
        return result
    matches, conflicts = {}, set()
    for item in payload:
        event = _normalize(item, retrieved_at, url)
        key = consensus_key(event)
        if key not in keys:
            continue
        if key in matches and matches[key]["forecast"] != event["forecast"]:
            conflicts.add(key)
        matches[key] = event
    result["events"] = [matches[key] for key in sorted(matches) if key not in conflicts]
    count = len(result["events"])
    diagnostics.update(status="available" if count else "unavailable", matched_count=count,
                       reason="" if count else "conflicting_consensus" if conflicts else "exact_consensus_unavailable")
    missing = keys - set(matches)
    if public_fallback and missing:
        return _public_fallback(rows, missing, now, fetch, result)
    return result
