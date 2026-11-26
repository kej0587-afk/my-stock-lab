"""Bounded SEC/DART discovery for requested issuers, separate from decisions."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import re
import threading
import time

import requests
from lxml import etree

from stock_lab_core.earnings_filing_evidence import (
    latest_dart_report, latest_sec_filing, parse_sec_release, sec_base, sec_document, sec_release_link,
)
from stock_lab_core.performance import measure, submit_with_context
from stock_lab_core.earnings_discovery_performance import FilingProbe, cache_event, release_validation_event
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

CACHE_TTL = 600
FAILURE_TTL = 90
ACCOUNTS_TTL = 86400  # receipt-keyed DART statements; user-approved 2026-11-24
MAX_SECONDS = 24
MARKET_WORKERS = 3
MAX_BYTES = 3_000_000
_CACHE = {}
_LOCK = threading.RLock()
_SEC_LOCK = threading.Lock()
_SEC_NEXT = 0.0
# Documents inside one EDGAR accession folder never change once filed, so a successful body
# is kept for a day and re-parsed with the current clock (2026-11-26 speed work: a rerun spent
# 43.9 s in SEC fair-access waits for 94 requests). Submissions JSON is not covered (it changes).
_ARCHIVE = re.compile(r"https://www\.sec\.gov/Archives/edgar/data/\d{1,10}/\d{18}/[A-Za-z0-9_.-]+")
ARCHIVE_TTL = 86400
ARCHIVE_MAX_BYTES = 40_000_000
_ARCHIVE_BODIES = {}


class CachedFailure(ValueError):
    from_cache = True


def clear_cache():
    with _LOCK:
        _CACHE.clear()
        _ARCHIVE_BODIES.clear()


def _archive_get(url):
    with _LOCK:
        saved = _ARCHIVE_BODIES.get(url)
        if saved and 0 <= time.monotonic() - saved[0] < ARCHIVE_TTL:
            cache_event(("sec_archive",), "hit")
            return saved[1]
    return None


def _archive_put(url, body):
    with _LOCK:
        _ARCHIVE_BODIES[url] = (time.monotonic(), body)
        while sum(len(v[1]) for v in _ARCHIVE_BODIES.values()) > ARCHIVE_MAX_BYTES and len(_ARCHIVE_BODIES) > 1:
            _ARCHIVE_BODIES.pop(min(_ARCHIVE_BODIES, key=lambda k: _ARCHIVE_BODIES[k][0]))


def _cached(key, now, loader, *, ttl=CACHE_TTL):
    with _LOCK:
        saved = _CACHE.get(key)
        if saved and 0 <= (now - saved[0]).total_seconds() < (ttl if saved[2] is None else FAILURE_TTL):
            if saved[2]:
                cache_event(key, "failure_hit")
                raise CachedFailure(saved[2])
            cache_event(key, "hit")
            return deepcopy(saved[1]), True
    cache_event(key, "miss")
    try:
        value = loader()
    except ValueError as error:
        with _LOCK:
            _CACHE[key] = (now, None, str(error))
        raise
    with _LOCK:
        _CACHE[key] = (now, deepcopy(value), None)
    return value, False


def _request(url, *, deadline, user_agent="", params=None, get=requests.get):
    global _SEC_NEXT
    archive = bool(user_agent and not params and _ARCHIVE.fullmatch(str(url)))
    if archive and (body := _archive_get(url)) is not None:
        return body
    remaining = deadline - time.monotonic()
    if remaining < 1:
        raise ValueError("collection_time_budget")
    if user_agent:
        # Shared workers stay below the SEC fair-access request rate.
        with measure("external_data", "earnings_discovery.sec_rate_wait"):
            with _SEC_LOCK:
                delay = max(0, _SEC_NEXT - time.monotonic())
                if delay:
                    time.sleep(delay)
                _SEC_NEXT = time.monotonic() + 0.2
    try:
        with measure("external_data", "earnings_official.request"):
            response = get(url, params=params, headers={"User-Agent": user_agent} if user_agent else {},
                           timeout=(min(2, remaining), min(3, remaining)), allow_redirects=False, stream=True)
            try:
                if response.status_code != 200:
                    raise ValueError(f"http_{response.status_code}")
                with measure("external_data", "earnings_discovery.http_body"):
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("document_size_limit")
                        if time.monotonic() > deadline:
                            raise ValueError("collection_time_budget")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if archive:
                        _archive_put(url, body)
                    return body
            finally:
                response.close()
    except requests.Timeout:
        raise ValueError("request_timeout") from None
    except requests.RequestException:
        raise ValueError("request_transport_error") from None


def _json(url, **kwargs):
    try:
        body = _request(url, **kwargs)
        with measure("external_data", "earnings_discovery.parse_json"):
            data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("invalid_provider_json")
        return data
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("invalid_provider_json") from None


def _sec_collect(ticker, directory, user_agent, now, deadline, get):
    candidates = [row for row in directory.values() if isinstance(row, dict)
                  and str(row.get("ticker", "")).replace(".", "-").upper() == ticker.replace(".", "-")]
    if len(candidates) != 1:
        raise ValueError("sec_ticker_mapping_unavailable")
    cik = str(int(candidates[0]["cik_str"]))
    options = dict(user_agent=user_agent, deadline=deadline, get=get)
    submissions = _json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", **options)
    with measure("external_data", "earnings_discovery.select_sec_filing"):
        filing = latest_sec_filing(submissions, ticker, cik, now)
    base = sec_base(cik, filing["accessionNumber"])
    primary = sec_document(base, filing["primaryDocument"])
    primary_body = _request(primary, **options)
    with measure("external_data", "earnings_discovery.parse_sec_link"):
        release_url = sec_release_link(primary_body, base)
    release_body = _request(release_url, **options)
    with measure("external_data", "earnings_discovery.parse_sec_release"):
        try:
            pair = parse_sec_release(release_body, ticker, cik, filing, release_url, now,
                                     issuer_name=submissions.get("name"))
        except ValueError as error:
            release_validation_event(str(error))
            raise
        release_validation_event("accepted")
        return pair


def _dart_financials(event, auth, api_key, now, deadline, get):
    from stock_lab_core.earnings_dart_financials import ENDPOINT, parse_financials, report_spec

    diagnostic = dict(financial_status="unavailable", financial_attempted=False, financial_from_cache=False)
    corp = event["filing_corp_code"]

    def request(url, **params):
        diagnostic["financial_attempted"] = True
        return _json(url, deadline=deadline, get=get, params=dict(crtfc_key=api_key, corp_code=corp, **params))

    def company():
        data = request("https://opendart.fss.or.kr/api/company.json")
        report_spec(event, data, corp)
        return {key: data[key] for key in ("status", "corp_code", "stock_code", "acc_mt") if key in data}

    try:
        profile, _ = _cached(("dart_company", corp, auth), now, company, ttl=86400)
        spec = report_spec(event, profile, corp)

        def financials():
            for basis in ("CFS", "OFS"):
                data = request(ENDPOINT, bsns_year=spec["year"], reprt_code=spec["report_code"], fs_div=basis)
                if data.get("status") == "013" and basis == "CFS":
                    continue
                with measure("external_data", "earnings_discovery.parse_dart_financials"):
                    return parse_financials(data, event, spec, basis, now)

        # Statements are keyed by the filing receipt number, whose content does not
        # change; a new filing has a new receipt. The 10-minute filing list (which
        # discovers new receipts) keeps its own TTL.
        pair, cached = _cached(("dart_accounts", event["ticker"], spec["receipt"], auth), now, financials,
                               ttl=ACCOUNTS_TTL)
        diagnostic.update(financial_status="connected", financial_reason="direct_reported_accounts", financial_from_cache=cached)
        return pair, diagnostic
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        reason = str(error)
        reason = reason if re.fullmatch(r"[a-z][a-z0-9_]{1,80}", reason) else "invalid_provider_schema"
        diagnostic.update(financial_reason=reason, financial_from_cache=getattr(error, "from_cache", False))
        return ({**event, "financial_reason": reason}, None), diagnostic


def collect_filing_earnings(tickers, now, *, sec_user_agent=None, dart_api_key=None, get=requests.get):
    """Every requested issuer gets a result or an explicit reason, never a guess.

    Cache entries are issuer/credential scoped; historical cutoffs cannot consume
    future cache entries. A shared wall budget bounds cold work across issuers.
    """
    from stock_lab_core.economic_releases import _api_key
    from stock_lab_core.dart_corporate_codes import fetch_corporate_codes
    from stock_lab_core.dart_corporate_snapshot import use_corporate_snapshot

    user_agent = _api_key("sec_user_agent") if sec_user_agent is None else sec_user_agent
    dart_key = _api_key("dart_api_key") if dart_api_key is None else dart_api_key
    deadline = time.monotonic() + MAX_SECONDS
    probe = FilingProbe(get)
    get = probe.request
    symbols = list(dict.fromkeys(tickers))
    directory, setup_errors = {}, {}
    auth = hashlib.sha256((user_agent + "\0" + dart_key).encode()).hexdigest()
    # The DART corporate directory is a multi-MB ZIP; a slow cold download must not
    # hold back SEC issuers. It runs beside the US pool; KR issuers wait for it.
    # Budget, timeouts, retry and snapshot rules are unchanged.
    kr_setup = {"codes": {}, "mapping": {}, "error": None}

    def setup_kr():
        if dart_key:
            try:
                def code_map():
                    data = fetch_corporate_codes(dart_key, get=get, timeout=5)
                    attempts = 1
                    # A transient directory failure must not remove every KR
                    # issuer; one retry shares the existing collection budget.
                    if (not data and data.diagnostic.get("cause") in
                            {"connect_timeout", "read_timeout", "timeout", "transport_error"}
                            and deadline - time.monotonic() >= 6):
                        data = fetch_corporate_codes(dart_key, get=get, timeout=5)
                        attempts += 1
                    data = use_corporate_snapshot(data, now=now)
                    if not data:
                        cause = data.diagnostic.get("cause", "unavailable")
                        status = str(data.diagnostic.get("api_status", ""))
                        suffix = "_" + status if re.fullmatch(r"\d{3}", status) else ""
                        raise ValueError("dart_corporate_mapping_" + cause + suffix)
                    return dict(data), {"mapping_attempts": attempts, **{key: data.diagnostic[key] for key in
                        ("mapping_source", "snapshot_origin", "snapshot_asof", "snapshot_valid_until")
                        if key in data.diagnostic}}
                with measure("external_data", "earnings_discovery.setup_dart"):
                    (kr_setup["codes"], kr_setup["mapping"]), _ = _cached(("dart_codes", auth), now, code_map, ttl=86400)
                if kr_setup["mapping"].get("snapshot_valid_until") and now > datetime.fromisoformat(kr_setup["mapping"]["snapshot_valid_until"]):
                    raise ValueError("dart_corporate_mapping_snapshot_expired")
            except ValueError as error:
                kr_setup["error"] = str(error)
        else:
            kr_setup["error"] = "dart_api_key_missing"

    kr_pool_setup = ThreadPoolExecutor(max_workers=1)
    kr_ready = submit_with_context(kr_pool_setup, setup_kr) if any(t.endswith((".KS", ".KQ")) for t in symbols) else None

    if any(not t.endswith((".KS", ".KQ")) for t in symbols):
        if user_agent:
            try:
                with measure("external_data", "earnings_discovery.setup_sec"):
                    directory, _ = _cached(("sec_directory", auth), now, lambda: _json(
                        "https://www.sec.gov/files/company_tickers.json", user_agent=user_agent, deadline=deadline, get=get), ttl=86400)
            except ValueError as error:
                setup_errors["US"] = str(error)
        else:
            setup_errors["US"] = "sec_user_agent_missing"
    def collect(ticker):
        market = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        diagnostic = dict(ticker=ticker, provider="official_filing_discovery", checked_at=now.isoformat(),
                          status="unavailable", attempted=False, from_cache=False)
        try:
            codes, mapping = {}, {}
            if market == "KR":
                kr_ready.result()
                codes, mapping = kr_setup["codes"], kr_setup["mapping"]
                diagnostic.update(mapping)
                if kr_setup["error"]:
                    raise ValueError(kr_setup["error"])
            if market in setup_errors:
                raise ValueError(setup_errors[market])
            def fetch():
                if time.monotonic() >= deadline:
                    raise ValueError("collection_time_budget")
                diagnostic["attempted"] = True
                if market == "US":
                    return _sec_collect(ticker, directory, user_agent, now, deadline, get)
                corp = codes.get(ticker.split(".")[0])
                if not corp:
                    # A dated list cannot know issuers listed after it was saved.
                    raise ValueError("dart_ticker_mapping_unavailable_in_snapshot"
                                     if mapping.get("mapping_source") == "official_snapshot"
                                     else "dart_ticker_mapping_unavailable")
                data = _json("https://opendart.fss.or.kr/api/list.json", deadline=deadline, get=get,
                             params=dict(crtfc_key=dart_key, corp_code=corp,
                                         bgn_de=(now - timedelta(days=200)).strftime("%Y%m%d"),
                                         end_de=now.strftime("%Y%m%d"), pblntf_ty="A", last_reprt_at="Y",
                                         page_count=100, sort="date", sort_mth="desc"))
                with measure("external_data", "earnings_discovery.select_dart_filing"):
                    return latest_dart_report(data, corp, ticker, now), None
            pair, cached = _cached(("issuer_accounts_v1", ticker, auth), now, fetch)
            if market == "KR":
                pair, financial_diagnostic = _dart_financials(pair[0], auth, dart_key, now, deadline, get)
                diagnostic.update(financial_diagnostic)
            diagnostic.update(status="connected", reason="official_filing", from_cache=cached,
                              fiscal_period=pair[0]["fiscal_period"], source_url=pair[0]["source_url"],
                              source_verified_at=pair[0]["source_verified_at"])
            return pair, diagnostic
        except (ValueError, TypeError, KeyError, AttributeError, etree.LxmlError) as error:
            # Never retain provider bodies, credentials or exception URLs.
            reason = str(error)
            diagnostic["from_cache"] = getattr(error, "from_cache", False)
            diagnostic["reason"] = reason if re.fullmatch(r"[a-z][a-z0-9_]{1,80}", reason) else "invalid_provider_schema"
            return (None, None), diagnostic

    try:
        # One pool per market: DART issuers no longer queue behind SEC fair-access
        # waits. Each provider still has at most MARKET_WORKERS concurrent issuers,
        # SEC keeps its shared rate lock, and the wall budget stays shared.
        with ThreadPoolExecutor(max_workers=MARKET_WORKERS) as kr_pool, \
                ThreadPoolExecutor(max_workers=MARKET_WORKERS) as us_pool:
            futures = [submit_with_context(kr_pool if ticker.endswith((".KS", ".KQ")) else us_pool,
                                           probe.worker, time.monotonic(), collect, ticker) for ticker in symbols]
            with measure("external_data", "earnings_discovery.worker_join"):
                collected = [future.result() for future in futures]
    finally:
        kr_pool_setup.shutdown(wait=True)
        probe.finish()
    return dict(events=[pair[0] for pair, _ in collected if pair[0]],
                results=[pair[1] for pair, _ in collected if pair[1]],
                sources=[source for _, source in collected])
