"""Bounded, period-specific official earnings evidence; no forecasts or prices.

Only the verified result URLs below are collected. This is not quarterly URL
discovery. Date-only releases retain an unknown release minute and an explicit
observation timestamp. Cached evidence never travels backwards across that
timestamp. A failed transport can expose a labelled, bounded last success;
changed or contradictory source evidence cannot.
"""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
from itertools import islice
import json
import re
import threading
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import etree, html
import requests

from stock_lab_core.earnings_sources import _ALIASES, _ISSUERS
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

REQUEST_TIMEOUT = (2, 4)
SUCCESS_TTL = 6 * 3600
FAILURE_TTL = 60
LAST_SUCCESS_MAX_AGE = 7 * 86400
MAX_EVENTS = 64
MAX_BYTES = 2_000_000
MAX_PDF_BYTES = 8_000_000
MAX_SECONDS = 8
_CACHE, _LAST_SUCCESS = {}, {}
_LOCK = threading.Lock()
_ISSUER_LOCKS = {ticker: threading.Lock() for ticker in _ISSUERS}

_PROFILES = {
    ticker: dict(ticker=ticker, name=spec["name"], fiscal_period=spec["quarter"],
                 release_date=spec["date"], timezone="Asia/Seoul" if spec["market"] == "KR" else "America/New_York",
                 source_url=spec["url"] if spec["kind"] == "results" else None)
    for ticker, spec in _ISSUERS.items()
}
_PROFILES["GOOGL"]["source_url"] = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm"
_PROFILES["MSFT"]["source_url"] = "https://news.microsoft.com/source/2026/10/28/microsoft-announces-first-quarter-results-2/"
_PROFILES["005930.KS"]["source_url"] = "https://news.samsung.com/global/samsung-electronics-announces-third-quarter-2026-results"
# Linked from the issuers' IR earnings lists, not guessed quarterly URLs.
_ALTERNATE_PDFS = {
    "GOOGL": "https://s206.q4cdn.com/479360582/files/doc_financials/2026/q3/2026q3-alphabet-earnings-release.pdf",
    "005930.KS": "https://images.samsung.com/is/content/samsung/assets/global/ir/docs/2026_3Q_conference_eng.pdf",
}
_HEADINGS = {
    "GOOGL": r"Alphabet Announces Third Quarter 2026 Results",
    "MSFT": r"Microsoft announces first quarter results",
    "005930.KS": r"Samsung Electronics Announces Third Quarter 2026 Results",
    "000660.KS": r"SK hynix Announces 3Q26 Financial Results",
    "META": r"Meta Reports Third Quarter 2026 Results",
    "TSLA": r"Tesla Releases Third Quarter 2026 Financial Results",
}
_HOSTS = {"www.sec.gov", "news.microsoft.com", "news.samsung.com", "news.skhynix.com", "investor.atmeta.com", "ir.tesla.com",
          "s206.q4cdn.com", "images.samsung.com"}
_METRICS = {
    "revenue": r"\b(?:revenues?|sales)\b",
    "profit": r"\b(?:operating (?:income|profit)|net (?:income|profit))\b",
    "capex": r"\b(?:capital expenditures?|capex|purchases of property and equipment)\b",
    "free_cash_flow": r"\bfree cash flow\b",
    "guidance": r"\bguidance\b|\boutlook\b",
}
_MONEY = re.compile(r"\$\s*\(?[\d,.]+|\b(?:KRW|USD)\s*[\d,.]+|[\d,.]+\s*(?:billion|million|trillion)\b", re.I)
_FORWARD = re.compile(r"\b(?:expects?|expected|anticipates?|projects?|plans?|will|would|guidance|outlook)\b", re.I)
_MONTHS = {name: index for index, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}


def _canonical(ticker):
    value = str(ticker or "").strip().upper()
    return _ALIASES.get(value, value)


def _stamp(value):
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo and value.utcoffset() is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _text(node):
    return " ".join(" ".join(node.itertext()).split())


def is_official_result_url(ticker, url):
    """Exact, issuer-bound covered result URL, not a general official-host check."""
    ticker = _canonical(ticker)
    expected = [_PROFILES.get(ticker, {}).get("source_url"), _ALTERNATE_PDFS.get(ticker)]
    if not any(expected) or not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in _HOSTS and not parsed.username
                and not parsed.password and parsed.port is None and not parsed.query and not parsed.fragment
                and any(parsed.hostname == urlsplit(target).hostname
                        and parsed.path.rstrip("/") == urlsplit(target).path.rstrip("/")
                        for target in expected if target))
    except ValueError:
        return False


def clear_earnings_result_cache():
    with _LOCK:
        _CACHE.clear()
        _LAST_SUCCESS.clear()


def _metadata_dates(root):
    published, modified = [], []
    for node in root.xpath("//meta"):
        key = (node.get("property") or node.get("name") or "").lower()
        if key in {"article:published_time", "datepublished", "date"}:
            published.append(node.get("content", ""))
        elif key in {"article:modified_time", "datemodified"}:
            modified.append(node.get("content", ""))
    for script in root.xpath('//script[@type="application/ld+json"]')[:12]:
        try:
            data = json.loads(script.text or "")
        except (TypeError, ValueError):
            continue
        queue = data if isinstance(data, list) else [data]
        for obj in list(queue):
            if isinstance(obj, dict):
                queue.extend(obj.get("@graph", []) if isinstance(obj.get("@graph"), list) else [])
        for obj in queue[:100]:
            if not isinstance(obj, dict):
                continue
            kind = obj.get("@type", [])
            if not set(kind if isinstance(kind, list) else [kind]) & {"Article", "NewsArticle", "ReportageNewsArticle"}:
                continue
            published.append(obj.get("datePublished", ""))
            modified.append(obj.get("dateModified", ""))
    return [v for v in published if v], [v for v in modified if v]


def _date_evidence(text):
    months = "|".join(name + "|" + name[:3] + r"\.?" for name in _MONTHS)
    found = []
    for match in re.finditer(r"\b(" + months + r")\s+(\d{1,2}),?\s+(20\d{2})\b", text, re.I):
        month = next(number for name, number in _MONTHS.items() if name[:3].lower() == match[1][:3].lower())
        try:
            value = date(int(match[3]), month, int(match[2])).isoformat()
            if value not in found:
                found.append(value)
        except ValueError:
            pass
    return found


def _release_timing(root, spec, now):
    published, modified = _metadata_dates(root)
    zone = ZoneInfo(spec["timezone"])
    stamps = []
    for value in published:
        stamp = _stamp(value)
        day = stamp.astimezone(zone).date().isoformat() if stamp else str(value)[:10]
        if day != spec["release_date"]:
            raise ValueError("publication_date_mismatch")
        if stamp:
            stamps.append(stamp)
    if any(stamp > now for stamp in stamps):
        raise ValueError("publication_after_cutoff")
    versions = [_stamp(value) for value in modified]
    if any(not stamp and re.match(r"^\d{4}-\d{2}-\d{2}", str(value))
           and str(value)[:10] > now.astimezone(zone).date().isoformat()
           for value, stamp in zip(modified, versions)):
        raise ValueError("page_version_after_cutoff")
    for value, stamp in zip(modified, versions):
        if stamp or not re.match(r"^\d{4}-\d{2}-\d{2}[T ]", str(value)):
            continue
        try:
            naive = datetime.fromisoformat(str(value))
        except ValueError:
            continue
        # Use the issuer zone only as a conservative cutoff check, not as a
        # fabricated confirmed timestamp. Choose the later DST interpretation.
        if naive.tzinfo is None and max(naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                                       for fold in (0, 1)) > now:
            raise ValueError("page_version_after_cutoff")
    if any(stamp and stamp > now for stamp in versions):
        raise ValueError("page_version_after_cutoff")
    if any(stamp and stamps and stamp < min(stamps) for stamp in versions):
        raise ValueError("invalid_page_version")
    # Consistent dates with conflicting minutes confirm only a date, not a time.
    precise = len(set(stamps)) == 1
    return (stamps[0] if precise else None, max((stamp for stamp in versions if stamp), default=None),
            "consistent" if precise else "conflicting_minutes_date_only" if stamps else "date_only")


def _body(root, spec):
    for node in root.xpath("//script|//style|//nav|//footer|//aside|//noscript"):
        node.drop_tree()
    candidates = root.xpath("//article|//main|//*[@role='main']")
    content = next((node for node in candidates if re.search(_HEADINGS[spec["ticker"]], _text(node), re.I)), root)
    headings = [_text(node) for node in content.xpath(".//h1|.//h2|.//h3")]
    result_heading = next((heading for heading in headings if re.search(r"results", heading, re.I)
                           and re.search(r"Alphabet|Microsoft|Samsung|SK hynix|Meta|Tesla", heading, re.I)), "")
    if result_heading and not re.fullmatch(_HEADINGS[spec["ticker"]], result_heading, re.I):
        raise ValueError("result_identity_or_period_mismatch")
    title = next((heading for heading in headings if re.fullmatch(_HEADINGS[spec["ticker"]], heading, re.I)), "")
    # SEC exhibits use styled divs rather than semantic headings.
    if not title and spec["ticker"] == "GOOGL":
        match = re.search(_HEADINGS["GOOGL"], _text(content)[:800], re.I)
        title = match[0] if match else ""
    if not title:
        raise ValueError("result_identity_or_period_mismatch")
    first_heading = next(iter(headings), "")
    if re.search(r"preview|release date|announces date|will announce|to announce", first_heading, re.I):
        raise ValueError("schedule_or_preview")
    text = _text(content)
    dates = _date_evidence(text[:6000])
    if not dates or dates[0] != spec["release_date"]:
        raise ValueError("release_date_not_in_body")
    if spec["ticker"] == "MSFT" and not re.search(r"first quarter of fiscal year 2027|fiscal year 2027 first.quarter", text, re.I):
        raise ValueError("fiscal_period_not_in_body")
    if not re.search(r"(?:today\s+(?:announced|reported)|announced\s+today|has\s+released|Reports\s+revenues|financial\s+results\s+for)", text[:9000], re.I):
        raise ValueError("result_publication_unconfirmed")
    blocks = []
    for node in content.xpath(".//p|.//li|.//div")[:3000]:
        if node.xpath("ancestor::table|.//table|.//p|.//li|.//div|.//h1|.//h2|.//h3"):
            continue
        if any(re.search(r"ai[-_ ]?summary", parent.get("class", ""), re.I) for parent in node.iterancestors()):
            continue
        block = _text(node)
        for sentence in re.split(r"(?<=[.!?;])\s+(?=[A-Z])", block):
            if 10 <= len(sentence) <= 380:
                blocks.append(sentence)
    return content, title, list(dict.fromkeys(blocks))


def _metric(text, status, spec, **extra):
    return dict(text=text, status=status, source_url=spec["source_url"], **extra)


def _outside_current_quarter(block, spec):
    if re.search(r"\b(?:nine|six|twelve|9|6|12)[ -]months?\b|\byear[ -]to[ -]date\b|\bYTD\b|\bTTM\b|\btrailing\b|\bfull[ -]year\b|\bcumulative\b|January[ -]+September", block, re.I):
        return True
    _, year, quarter = re.fullmatch(r"(FY)?(20\d{2})Q([1-4])", spec["fiscal_period"]).groups()
    fiscal_years = re.findall(r"\b(?:FY\s*|fiscal\s+(?:year\s+)?)(20\d{2})\b", block, re.I)
    if any(value != year for value in fiscal_years):
        return True
    periods = [(y, q) for q, y in re.findall(r"\bQ([1-4])\s*(?:FY\s*)?(20\d{2})\b", block, re.I)]
    periods += re.findall(r"\b(?:FY\s*)?(20\d{2})\s*Q([1-4])\b", block, re.I)
    ordinals = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
    for name, y in re.findall(r"\b(first|second|third|fourth)[ -]quarter\s+(?:of\s+)?(?:fiscal\s+(?:year\s+)?)?(20\d{2})\b", block, re.I):
        periods.append((y, ordinals[name.lower()]))
    return any((y, q) != (year, quarter) for y, q in periods)


def _prose_metrics(blocks, spec):
    metrics = {key: _metric("", "missing", spec, reason="not_in_supported_source_text") for key in _METRICS}
    for key, pattern in _METRICS.items():
        if key == "guidance":
            continue
        for block in blocks:
            if not re.search(pattern, block, re.I) or not _MONEY.search(block) or _FORWARD.search(block):
                continue
            if key in {"revenue", "profit"} and re.search(r"\b(?:division|segment|business|Google Cloud|Google Services|Azure|Samsung Display|Agents and Infra|Devices and Consumer)\b", block, re.I):
                continue
            # Prior-period notes and definitions are not this quarter's results.
            if re.search(r"\b(?:define|defined|definition)\b", block, re.I) or _outside_current_quarter(block, spec):
                continue
            metrics[key] = _metric(block, "reported", spec, period_scope=spec["fiscal_period"], extraction="source_sentence")
            break
    deferred = next((b for b in blocks if re.search(r"will (?:provide|discuss).{0,80}(?:guidance|outlook)", b, re.I)
                     and re.search(r"conference call|webcast", b, re.I)), None)
    guidance = next((b for b in blocks if _FORWARD.search(b) and re.search(r"guidance|outlook|revenue|capital expenditure", b, re.I)
                     and _MONEY.search(b) and not re.search(r"risks? and uncertainties|may differ", b, re.I)), None)
    if guidance:
        metrics["guidance"] = _metric(guidance, "reported", spec, period_scope="management_outlook", extraction="source_sentence")
    elif deferred:
        metrics["guidance"] = _metric(deferred, "deferred", spec, reason="guidance_deferred_to_call", period_scope="management_outlook")
    return metrics


def _table_grid(table):
    """Expand HTML row/column spans so a value stays under its actual header."""
    occupied, grid = {}, []
    for r, row in enumerate(table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")[:40]):
        col = 0
        for cell in row.xpath("./td|./th"):
            while (r, col) in occupied:
                col += 1
            try:
                width, height = int(cell.get("colspan", "1")), int(cell.get("rowspan", "1"))
            except ValueError:
                return []
            if not 1 <= width <= 128 or not 1 <= height <= 40 or col + width > 128:
                return []
            for dr in range(height):
                for dc in range(width):
                    occupied[r + dr, col + dc] = _text(cell)
            col += width
        grid.append([occupied.get((r, c), "") for c in range(128)])
    return grid


def _alphabet_cash_flow(content, spec):
    """Only the explicit quarter reconciliation, never YTD or TTM columns."""
    result, matching_tables = {}, 0
    year, quarter = re.fullmatch(r"(20\d{2})Q([1-4])", spec["fiscal_period"]).groups()
    column = f"Q{quarter} {year}"
    for table in content.xpath(".//table")[:80]:
        text = _text(table)
        if not re.search(r"Free cash flow", text, re.I) or column not in text:
            continue
        context = " ".join(_text(node) for node in table.xpath("preceding-sibling::*[position() <= 5]"))[-1800:]
        if not re.search(r"Reconciliation.{0,180}Free Cash Flow", context, re.I) or not re.search(r"in millions", context + text, re.I) or "$" not in text:
            continue
        grid = _table_grid(table)
        start = next((i for i, row in enumerate(grid) if any("Net cash provided by operating activities" in cell for cell in row)), None)
        if start is None:
            continue
        columns = [c for c in range(128) if column in " ".join(row[c] for row in grid[:start])
                   and re.search(r"Quarter Ended", " ".join(row[c] for row in grid[:start]), re.I)
                   and not re.search(r"TTM|trailing", " ".join(row[c] for row in grid[:start]), re.I)]
        if not columns:
            continue
        matching_tables += 1
        if matching_tables > 1:
            return {}
        for key, label in (("capex", "purchases of property and equipment"), ("free_cash_flow", "Free cash flow")):
            rows = [row for row in grid[start:] if any(re.fullmatch(r"(?:Less:\s*)?" + label, cell, re.I) for cell in row)]
            if len(rows) != 1:
                continue
            values = {rows[0][c] for c in columns if re.fullmatch(r"\(?-?\$?\s*\d[\d,]*(?:\.\d+)?\)?", rows[0][c])}
            if len(values) != 1:
                continue
            value = values.pop()
            source_label = "Less: purchases of property and equipment" if key == "capex" else "Free cash flow"
            result[key] = _metric(f"{column} | {source_label}: {value} | USD millions (unaudited)", "reported", spec,
                                  period_scope=spec["fiscal_period"], extraction="explicit_quarter_reconciliation",
                                  column=column, unit="USD millions", source_label=source_label, source_value=value)
    return result


def parse_earnings_result(data, ticker, now):
    """Pure strict parser, also usable by offline fixtures. Raises a reason code."""
    ticker, now = _canonical(ticker), _stamp(now)
    if now is None or ticker not in _HEADINGS:
        raise ValueError("unsupported_result_or_timestamp")
    spec = _PROFILES[ticker]
    if now.astimezone(ZoneInfo(spec["timezone"])).date().isoformat() < spec["release_date"]:
        raise ValueError("future_result")
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError("invalid_document_size")
    root = html.fromstring(data.decode("utf-8-sig"), parser=html.HTMLParser(no_network=True))
    release_at, modified_at, time_status = _release_timing(root, spec, now)
    content, title, blocks = _body(root, spec)
    metrics = _prose_metrics(blocks, spec)
    if ticker == "GOOGL":
        # Do not fall back to another comparative table or a generic FCF definition.
        for key in ("capex", "free_cash_flow"):
            metrics[key] = _metric("", "missing", spec, reason="explicit_quarter_reconciliation_unavailable")
        metrics.update(_alphabet_cash_flow(content, spec))
    return dict(ticker=ticker, fiscal_period=spec["fiscal_period"], release_date=spec["release_date"],
                release_precision="datetime" if release_at else "date", release_at=release_at.isoformat() if release_at else None,
                source_url=spec["source_url"], checked_at=now.isoformat(), observed_at=now.isoformat(),
                status="official_result", stale=False, collection_reason="official_page", metrics=metrics,
                provenance=dict(provider="official_result_page", coverage="verified_url_and_period_only",
                                title=title, content_sha256=hashlib.sha256(data).hexdigest(),
                                page_modified_at=modified_at.isoformat() if modified_at else None,
                                publication_time_status=time_status,
                                timing_basis="source_publication_timestamp" if release_at else "date_only_observed_at",
                                observed_at=now.isoformat(), price_reaction_verified=False))


def _request_source(ticker, now, url, *, pdf=False):
    """One bounded source attempt. Parser rejection is not a transport failure."""
    spec = dict(_PROFILES[ticker], source_url=url)
    diagnostic = dict(ticker=ticker, fiscal_period=spec["fiscal_period"], source_url=spec["source_url"],
                      checked_at=now.isoformat(), attempted=True, from_cache=False, status="unavailable",
                      reason="", fallback_allowed=False)
    if not is_official_result_url(ticker, spec["source_url"]):
        diagnostic.update(attempted=False, reason="url_not_allowed")
        return None, diagnostic
    started = time.monotonic()
    try:
        response = requests.get(spec["source_url"], timeout=REQUEST_TIMEOUT, allow_redirects=False, stream=True,
                                headers={"User-Agent": "StockLab-OfficialResults/1.0",
                                         "Accept": "application/pdf" if pdf else "text/html"})
        try:
            diagnostic["http_status"] = response.status_code
            if response.status_code != 200:
                diagnostic.update(reason=f"http_{response.status_code}",
                                  fallback_allowed=response.status_code in {403, 408, 429, 500, 502, 503, 504})
                return None, diagnostic
            if not is_official_result_url(ticker, response.url):
                diagnostic["reason"] = "response_url_not_allowed"
                return None, diagnostic
            data = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                data.extend(chunk)
                if len(data) > (MAX_PDF_BYTES if pdf else MAX_BYTES):
                    raise ValueError("page_too_large")
                if time.monotonic() - started > MAX_SECONDS:
                    diagnostic.update(reason="request_deadline", fallback_allowed=True)
                    return None, diagnostic
            if pdf:
                from stock_lab_core.earnings_result_pdf import parse_official_result_pdf
                result = parse_official_result_pdf(bytes(data), ticker, spec, now)
            else:
                result = parse_earnings_result(bytes(data), ticker, now)
            diagnostic.update(status="connected", reason="official_result")
            return result, diagnostic
        finally:
            response.close()
    except requests.RequestException as exc:
        diagnostic.update(reason="request_failed:" + type(exc).__name__, fallback_allowed=True)
    except ValueError as exc:
        # Only our fixed parser reason codes are exposed, never response/exception text.
        reasons = {"future_result", "invalid_document_size", "result_identity_or_period_mismatch", "schedule_or_preview",
                   "release_date_not_in_body", "fiscal_period_not_in_body", "result_publication_unconfirmed",
                   "publication_date_mismatch", "publication_after_cutoff", "page_version_after_cutoff",
                   "invalid_page_version", "conflicting_publication_times", "page_too_large", "pdf_reader_unavailable"}
        diagnostic["reason"] = str(exc) if str(exc) in reasons else "invalid_document"
    except (etree.LxmlError, TypeError, AttributeError):
        diagnostic["reason"] = "invalid_document"
    return None, diagnostic


def _request_result(ticker, now):
    """Try one verified IR alternate only when the primary transport fails."""
    result, diagnostic = _request_source(ticker, now, _PROFILES[ticker]["source_url"])
    alternate = _ALTERNATE_PDFS.get(ticker)
    if result or not alternate or not diagnostic.get("fallback_allowed"):
        return result, diagnostic
    first = deepcopy(diagnostic)
    result, diagnostic = _request_source(ticker, now, alternate, pdf=True)
    diagnostic["attempts"] = [first, deepcopy(diagnostic)]
    if result:
        diagnostic.update(reason="official_alternative_result", alternate_used=True)
        result["provenance"]["primary_failure"] = first["reason"]
    return result, diagnostic


def _safe_age(result, now, max_age):
    checked = _stamp(result.get("checked_at"))
    return checked is not None and 0 <= (now - checked).total_seconds() <= max_age


def _collect(ticker, now, refresh):
    key = (ticker, _PROFILES[ticker]["fiscal_period"])
    with _ISSUER_LOCKS[ticker]:
        with _LOCK:
            cached, last = deepcopy(_CACHE.get(key)), deepcopy(_LAST_SUCCESS.get(key))
        diagnostic = dict(ticker=ticker, fiscal_period=key[1], source_url=_PROFILES[ticker]["source_url"],
                          checked_at=now.isoformat(), attempted=False, from_cache=False, status="unavailable", reason="refresh_disabled")
        if cached and _stamp(cached["diagnostic"]["checked_at"]) > now:
            diagnostic["reason"] = "cached_observation_after_cutoff"
            return None, diagnostic
        if cached and _safe_age(cached["diagnostic"], now, SUCCESS_TTL if cached["result"] else FAILURE_TTL):
            ttl = SUCCESS_TTL if cached["result"] else FAILURE_TTL
            if time.monotonic() - cached["clock"] < ttl:
                diagnostic = dict(cached["diagnostic"], attempted=False, from_cache=True)
                if cached["result"]:
                    return dict(cached["result"], collection_reason="success_cache"), diagnostic
                refresh = False
        if refresh:
            result, diagnostic = _request_result(ticker, now)
            with _LOCK:
                _CACHE[key] = dict(clock=time.monotonic(), result=deepcopy(result), diagnostic=deepcopy(diagnostic))
                if result:
                    _LAST_SUCCESS[key] = deepcopy(result)
                elif not diagnostic.get("fallback_allowed"):
                    _LAST_SUCCESS.pop(key, None)
                    last = None
            if result:
                return result, diagnostic
        if last and _safe_age(last, now, LAST_SUCCESS_MAX_AGE) and (diagnostic.get("fallback_allowed") or diagnostic["reason"] == "refresh_disabled"):
            result = dict(last, stale=True, collection_reason="last_success:" + diagnostic["reason"])
            diagnostic.update(status="fallback", fallback_used=True, last_success_at=last["checked_at"])
            return result, diagnostic
        return None, diagnostic


def load_earnings_results(events, now, *, refresh=True):
    """One primary plus one verified alternate per issuer, three workers.

    Input events require ticker, fiscal_period and date (or release_date).
    now is the caller's offset-aware capture cutoff. Same-day date-only source
    evidence is observed at that cutoff, not assigned an assumed release hour.
    Metric statuses are reported/missing/deferred; guidance is management
    outlook, never a realized result. refresh=False only reads existing evidence.
    """
    now = _stamp(now)
    if now is None:
        raise ValueError("now must be an offset-aware datetime")
    if hasattr(events, "to_dict"):
        events = events.to_dict("records")
    if isinstance(events, Mapping):
        events = [events]
    supplied = list(islice(events or (), MAX_EVENTS + 1))
    eligible, sources, seen = [], [], set()
    for event in supplied[:MAX_EVENTS]:
        if not isinstance(event, Mapping):
            continue
        ticker = _canonical(event.get("ticker") or event.get("Ticker"))
        period = str(event.get("fiscal_period") or "").strip().upper().replace(" ", "")
        key = ticker, period
        if key in seen:
            continue
        seen.add(key)
        spec = _PROFILES.get(ticker)
        reason = ""
        if not spec:
            reason = "issuer_not_supported"
        elif period != spec["fiscal_period"]:
            reason = "fiscal_period_not_covered"
        elif str(event.get("date") or event.get("release_date") or "") != spec["release_date"]:
            reason = "event_release_date_mismatch"
        elif now.astimezone(ZoneInfo(spec["timezone"])).date().isoformat() < spec["release_date"]:
            reason = "future_event"
        elif not spec["source_url"]:
            reason = "result_url_not_connected"
        if reason:
            sources.append(dict(ticker=ticker, fiscal_period=period, status="skipped", reason=reason,
                                attempted=False, checked_at=now.isoformat()))
        elif ticker not in eligible:
            eligible.append(ticker)
    with ThreadPoolExecutor(max_workers=3) as pool:
        collected = list(pool.map(lambda ticker: _collect(ticker, now, refresh), eligible))
    results = [result for result, _ in collected if result]
    sources.extend(diagnostic for _, diagnostic in collected)
    if len(supplied) > MAX_EVENTS:
        sources.append(dict(status="skipped", reason="event_limit", attempted=False))
    return dict(results=sorted(results, key=lambda row: (row["release_date"], row["ticker"])), sources=sources)


load_earnings_results.clear = clear_earnings_result_cache
