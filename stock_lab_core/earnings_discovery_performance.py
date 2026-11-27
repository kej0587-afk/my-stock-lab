"""Run-local discovery measurements, never request caching or financial inputs."""

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from stock_lab_core.performance import count_event, measure
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

# This context is carried into requests.Session.send by sec_rate's existing hook.
# get_calls include injected transports; http.attempt counts actual send entries,
# including redirects, after SEC admission. Neither is a count of TCP packets.
_http_source = ContextVar("earnings_http_source", default=None)
_SOURCES = {"sec", "dart", "dart_directory", "ir_schedule", "ir_html", "ir_pdf"}


def _source(value):
    return value if value in _SOURCES else "other"


def response_event(prefix, response):
    status = getattr(response, "status_code", None)
    label = str(status) if type(status) is int and 100 <= status <= 599 else "unknown"
    count_event(prefix + ".response." + label)


def transport_response_event(response, *, prefix=None):
    source = _http_source.get()
    if source is not None or prefix is not None:
        # An outer Session.send returns the final redirected response. Its first
        # history entry is this send's response; recursive sends record their own.
        history = getattr(response, "history", None)
        own_response = history[0] if isinstance(history, list) and history else response
        if source is not None:
            response_event("earnings_collection." + source + ".http", own_response)
        if prefix is not None:
            response_event(prefix, own_response)
    return response


def observed_get(source, get, *args, **kwargs):
    source = _source(source)
    prefix = "earnings_collection." + source
    count_event(prefix + ".get_calls")
    token = _http_source.set(source)
    try:
        with measure("external_data", prefix + ".provider_response"):
            response = get(*args, **kwargs)
        response_event(prefix + ".get", response)
        return response
    except Exception:
        count_event(prefix + ".get.transport_error")
        raise
    finally:
        _http_source.reset(token)


@contextmanager
def transport_measurement():
    """Called only at the existing Session.send boundary, after SEC admission."""
    source = _http_source.get()
    if source is None:
        yield
        return
    prefix = "earnings_collection." + source + ".http"
    count_event(prefix + ".attempt")
    try:
        with measure("external_data", prefix + ".send"):
            yield
    except Exception:
        count_event(prefix + ".transport_error")
        raise


@contextmanager
def observed_lock(lock, name):
    """Time acquisition only; preserve lock lifetime and reentrancy."""
    with measure("external_data", name + ".lock_wait"):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


def dart_status_event(status):
    allowed = {"000", "010", "011", "012", "013", "020", "021", "100", "101", "800", "900", "901"}
    count_event("earnings_collection.dart.api_status." + (status if type(status) is str and status in allowed else "other"))


def coverage_event(source, *, events=(), results=(), sources=()):
    """Aggregate row coverage; no issuer identities, URLs or raw reason strings."""
    label = source if source in {"filing", "ir_schedule", "ir_result", "merged"} else "other"
    prefix = "earnings_collection.coverage." + label
    for name, rows in (("events", events), ("results", results), ("sources", sources)):
        count_event(prefix + "." + name, len(rows))
    for status in ("connected", "unavailable", "skipped", "fallback"):
        count_event(prefix + "." + status, sum(row.get("status") == status for row in sources))
    for market in ("KR", "US"):
        selected = [row for row in sources if ("KR" if str(row.get("ticker", "")).endswith((".KS", ".KQ")) else "US") == market]
        count_event(prefix + "." + market + ".time_budget_skipped", sum(
            row.get("reason") in {"collection_time_budget", "request_deadline"}
            or row.get("financial_reason") == "collection_time_budget" for row in selected))
    for status in ("reported", "missing", "deferred"):
        count_event(prefix + ".metrics." + status, sum(
            metric.get("status") == status for row in results for metric in row.get("metrics", {}).values()))


class FilingProbe:
    """Export aggregates only; URLs, headers, credentials and issuer IDs stay out."""

    def __init__(self, get):
        self.get = get
        self._lock = Lock()
        self._identities = set()
        self._queue_us = []

    def request(self, url, **kwargs):
        host = urlsplit(url).hostname or ""
        provider = "sec" if host in {"www.sec.gov", "data.sec.gov"} else "dart" if host == "opendart.fss.or.kr" else "other"
        # Include every transport argument. Count only; do not reuse responses or
        # collapse retries. Digests exist only for the duration of this collection.
        identity = hashlib.sha256(json.dumps([url, kwargs], sort_keys=True).encode()).digest()
        with self._lock:
            duplicate = identity in self._identities
            self._identities.add(identity)
        prefix = "earnings_discovery.http." + provider
        count_event(prefix + ".attempt")
        count_event(prefix + (".duplicate_identity" if duplicate else ".unique_identity"))
        # Streaming SEC/DART JSON requests return headers here; the corporate ZIP
        # uses stream=False, so its get includes body transfer. Body span is separate
        # only for the streaming requests. Keep kwargs/response identity untouched.
        with measure("external_data", "earnings_discovery.http_get." + provider):
            source = "dart_directory" if provider == "dart" and urlsplit(url).path == "/api/corpCode.xml" else provider
            return observed_get(source, self.get, url, **kwargs)

    def worker(self, queued_at, collect, ticker):
        wait_us = max(0, round((monotonic() - queued_at) * 1_000_000))
        with self._lock:
            self._queue_us.append(wait_us)
        with measure("external_data", "earnings_discovery.worker"):
            return collect(ticker)

    def finish(self):
        with self._lock:
            waits = list(self._queue_us)
        count_event("earnings_discovery.collections", 1)
        count_event("earnings_discovery.workers_started", len(waits))
        # These durations are not request counts or non-overlapping wall time.
        count_event("earnings_discovery.queue_wait_us_total", sum(waits))
        # A trace can contain several collections; counters add their maxima.
        count_event("earnings_discovery.queue_wait_us_max_sum", max(waits, default=0))


def cache_event(key, outcome):
    allowed = {"sec_directory", "dart_codes", "issuer_accounts_v1", "dart_company", "dart_accounts", "sec_archive"}
    bucket = key[0] if isinstance(key, tuple) and key and key[0] in allowed else "other"
    count_event("earnings_discovery.cache." + bucket + "." + outcome)


def release_validation_event(reason):
    """Only actual parser calls, not cache hits; fixed vocabulary, no raw errors."""
    allowed = {"accepted", "result_heading_unavailable", "release_issuer_mismatch",
               "explicit_fiscal_quarter_unavailable", "release_dateline_unavailable",
               "release_filing_date_mismatch", "future_result"}
    count_event("earnings_discovery.sec_release." + (reason if reason in allowed else "other_validation_error"))
