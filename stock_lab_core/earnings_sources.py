"""Finite primary-source earnings coverage, restricted to requested issuers.

These are verified announcements, not an all-market calendar or a prediction
of the next quarter. Result publication and conference calls are different
events. Date-only evidence never supplies a fabricated release minute.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from itertools import islice
import threading
import time
from zoneinfo import ZoneInfo

import requests

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

VERIFIED_AT = "2026-10-28T08:25:44+00:00"
REQUEST_TIMEOUT = (2, 4)
CACHE_TTL = 900
FAILURE_TTL = 180
MAX_TICKERS = 32
_CACHE = {}
_LOCK = threading.Lock()

# The NVIDIA transcript, p.15, confirms only the call day. No PDF download is
# added to dashboard renders. Samsung's IR event likewise confirms a call.
_ISSUERS = {
    "000660.KS": dict(name="SK hynix", market="KR", date="2026-10-28", quarter="2026Q3",
        kind="results", published="2026-10-28", expires="2026-11-28",
        url="https://news.skhynix.com/en/q3-2026-business-results/",
        evidence=("SK hynix Announces 3Q26 Financial Results", "Seoul, October 28, 2026")),
    "005930.KS": dict(name="Samsung Electronics", market="KR", date="2026-10-29", quarter="2026Q3",
        kind="conference_call", published=None, expires="2026-11-05",
        call="2026-10-29T10:00:00+09:00",
        url="https://www.samsung.com/global/ir/ir-events-presentations/events/",
        evidence=("3Q26 Earnings Conference Call October 29, 2026, 10:00 a.m. KST",)),
    "NVDA": dict(name="NVIDIA", market="US", date="2026-11-17", quarter="FY2027Q3",
        kind="conference_call", published="2026-08-26", expires="2026-11-24",
        url="https://investor.nvidia.com/files/content_files/TRANSCRIPT_-NVIDIA-Corp-NVDA-US-Q2-2027-Earnings-Call-26-August-2026-5_00-PM-ET.pdf",
        evidence=(), source_page=15),
    "GOOGL": dict(name="Alphabet", market="US", date="2026-10-28", quarter="2026Q3",
        kind="scheduled_release", published="2026-10-06", expires="2026-11-04",
        call="2026-10-28T16:30:00-04:00", session="before_conference_call",
        url="https://abc.xyz/investor/news/news-details/2026/Alphabet-Announces-Date-of-Third-Quarter-2026-Financial-Results-Conference-Call-2026-8tpGZsLS6v/default.aspx",
        evidence=("third quarter 2026 financial results on Wednesday, October 28",
                  "1:30pm Pacific Time (4:30pm Eastern Time)", "October 28, 2026")),
    "META": dict(name="Meta", market="US", date="2026-10-21", quarter="2026Q3",
        kind="results", published="2026-10-21", expires="2026-11-21",
        url="https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Third-Quarter-2026-Results/default.aspx",
        evidence=("Meta Reports Third Quarter 2026 Results", "October 21, 2026")),
    "MSFT": dict(name="Microsoft", market="US", date="2026-10-28", quarter="FY2027Q1",
        kind="scheduled_release", published="2026-10-07", expires="2026-11-04",
        call="2026-10-28T14:30:00-07:00", session="after_market_close",
        url="https://news.microsoft.com/source/2026/10/07/microsoft-announces-quarterly-earnings-release-date-69",
        evidence=("fiscal year 2027 first-quarter financial results", "Wednesday, Oct. 28, 2026",
                  "2:30 p.m. Pacific Time", "after the close of the market")),
    "TSLA": dict(name="Tesla", market="US", date="2026-10-21", quarter="2026Q3",
        kind="results", published="2026-10-21", expires="2026-11-21",
        url="https://ir.tesla.com/press-release/tesla-releases-third-quarter-2026-financial-results",
        evidence=("Tesla Releases Third Quarter 2026 Financial Results", "October 21, 2026")),
}
_ALIASES = {"000660": "000660.KS", "005930": "005930.KS", "005935": "005930.KS",
            "005935.KS": "005930.KS", "GOOG": "GOOGL"}


def clear_earnings_source_cache():
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


class _Text(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.parts, self.ignored = [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored = tag

    def handle_endtag(self, tag):
        if tag == self.ignored:
            self.ignored = None

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def _check_source(spec, now):
    """One bounded HTML check per issuer; failures have a short cooldown."""
    url = spec["url"]
    with _LOCK:
        cached = _CACHE.get(url)
        if cached and cached[1] <= now.isoformat() and time.monotonic() - cached[0] < cached[2]:
            return dict(cached[3], attempted=False, from_cache=True)
    check = dict(attempted=True, from_cache=False, checked_at=now.isoformat(),
                 http_status=None, status="unavailable", reason="")
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False,
                                headers={"User-Agent": "StockLab-Earnings/1.0"})
        try:
            check["http_status"] = response.status_code
            if response.status_code != 200:
                check["reason"] = "http_" + str(response.status_code)
            elif len(response.content) > 2_000_000:
                check["reason"] = "page_too_large"
            else:
                text = " ".join(" ".join(_Text(response.text).parts).split()).casefold()
                if all(fragment.casefold() in text for fragment in spec["evidence"]):
                    check["status"] = "connected"
                else:
                    check["reason"] = "announcement_evidence_changed"
        finally:
            response.close()
    except requests.RequestException as exc:
        check["reason"] = "request_failed:" + type(exc).__name__
    except (ValueError, TypeError, AttributeError):
        check["reason"] = "invalid_response"
    with _LOCK:
        _CACHE[url] = (time.monotonic(), now.isoformat(),
                       CACHE_TTL if check["status"] == "connected" else FAILURE_TTL, dict(check))
    return check


def _issuer(ticker, requested, now, refresh):
    spec = _ISSUERS.get(ticker)
    source = dict(name=(spec["name"] + " Investor Relations") if spec else ticker + " earnings",
                  ticker=ticker, requested_tickers=requested, status="unavailable",
                  reason="issuer_not_connected", coverage_status="unconnected",
                  next_schedule_status="unconfirmed")
    if spec is None:
        return [], source
    source.update(source_url=spec["url"], source_verified_at=VERIFIED_AT,
                  coverage_expires_at=spec["expires"])
    # No look-ahead into a same-day results page whose publication minute is unknown.
    if now < datetime.fromisoformat(VERIFIED_AT) or now.date().isoformat() >= spec["expires"]:
        source.update(reason="verified_coverage_unavailable", coverage_status="expired_or_not_yet_verified")
        return [], source
    check = (_check_source(spec, now) if refresh and spec["evidence"] else
             dict(status="not_attempted", reason="manual_pdf_evidence" if not spec["evidence"] else "refresh_disabled",
                  attempted=False, from_cache=False))
    source["request"] = check
    live = check["status"] == "connected"
    source.update(status="connected", reason="", provider="official_page" if live else "verified_snapshot",
                  fallback_connected=not live, primary_status=check["status"], primary_reason=check["reason"])
    # A changed successful page is contradictory/unrecognized evidence, not a
    # transport outage. Do not silently promote an old schedule over that page.
    if check["reason"] == "announcement_evidence_changed":
        source.update(status="unavailable", reason=check["reason"], coverage_status="evidence_changed",
                      fallback_connected=False)
        return [], source
    zone = "Asia/Seoul" if spec["market"] == "KR" else "America/New_York"
    local_day = now.astimezone(ZoneInfo(zone)).date().isoformat()
    state = "released" if spec["kind"] == "results" else "scheduled"
    if state == "scheduled" and (spec["date"] < local_day or
            (spec.get("call") and
             datetime.fromisoformat(spec["call"]) <= now)):
        state = "elapsed_unconfirmed"
    source.update(coverage_status="recent_results_only" if state == "released" else state,
                  next_schedule_status="confirmed" if state == "scheduled" else "unconfirmed")
    event = dict(event=spec["name"] + (" earnings call" if spec["kind"] == "conference_call" else " earnings"),
                 indicator=spec["market"] + "_" + ticker.split(".")[0] + "_EARNINGS",
                 ticker=ticker, requested_tickers=requested, market=spec["market"],
                 date=spec["date"], release_at=spec["date"], release_precision="date",
                 event_at=spec["date"], event_precision="date",
                 release_time_confirmed=False, timezone=zone, fiscal_period=spec["quarter"],
                 event_kind=spec["kind"], status=state, event_status=state,
                 source=source["name"], source_url=spec["url"], source_kind=source["provider"],
                 source_published_at=spec["published"], source_verified_at=VERIFIED_AT,
                 coverage_expires_at=spec["expires"], next_schedule_status=source["next_schedule_status"])
    if spec.get("call"):
        event["conference_call_at"] = spec["call"]
    if spec["kind"] == "conference_call":
        event.update(release_date_confirmed=False, release_at=None, release_precision="unconfirmed",
                     conference_call_date=spec["date"], event_at=spec.get("call", spec["date"]),
                     event_precision="datetime" if spec.get("call") else "date")
    else:
        event["release_date_confirmed"] = True
    if spec.get("session"):
        event["session_timing"] = spec["session"]
    if spec.get("source_page"):
        event["source_page"] = spec["source_page"]
    return [event], source


def load_official_earnings(tickers, now=None, *, refresh=True):
    """At most seven issuers / six HTTP calls; unknown tickers never trigger I/O.

    Pass holdings/watch tickers, not the market universe. GOOG/GOOGL and Samsung
    common/preferred share one issuer. Recent results remain separate from next
    schedules; elapsed schedules are NOT evidence that results were published.
    """
    now = _clock(now)
    supplied = list(islice((tickers,) if isinstance(tickers, str) else tickers, MAX_TICKERS + 1))
    grouped = {}
    for raw in supplied[:MAX_TICKERS]:
        ticker = str(raw).strip().upper()
        if ticker and len(ticker) <= 24:
            canonical = _ALIASES.get(ticker, ticker)
            if ticker not in grouped.setdefault(canonical, []):
                grouped[canonical].append(ticker)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_issuer, ticker, requested, now, refresh) for ticker, requested in grouped.items()]
        results = [future.result() for future in futures]
    events = sorted([row for rows, _ in results for row in rows], key=lambda row: (row["date"], row["ticker"]))
    sources = [source for _, source in results]
    if len(supplied) > MAX_TICKERS:
        sources.append(dict(name="Earnings collection limit", status="unavailable", reason="ticker_limit",
                            coverage_status="not_collected", next_schedule_status="unconfirmed"))
    return dict(events=events, sources=sources, connected=any(s["status"] == "connected" for s in sources),
                recent_earnings=[deepcopy(row) for row in events if row["event_status"] == "released" and
                                 (now.date() - date.fromisoformat(row["date"])).days <= 30],
                upcoming_earnings=[deepcopy(row) for row in events if row["event_status"] == "scheduled"],
                elapsed_earnings=[deepcopy(row) for row in events if row["event_status"] == "elapsed_unconfirmed"])


load_official_earnings.clear = clear_earnings_source_cache
