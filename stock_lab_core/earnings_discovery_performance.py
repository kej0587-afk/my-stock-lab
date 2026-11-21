"""Run-local discovery measurements, never request caching or financial inputs."""

import hashlib
import json
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from stock_lab_core.performance import count_event, measure
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


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
            return self.get(url, **kwargs)

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
    allowed = {"sec_directory", "dart_codes", "issuer_accounts_v1", "dart_company", "dart_accounts"}
    bucket = key[0] if isinstance(key, tuple) and key and key[0] in allowed else "other"
    count_event("earnings_discovery.cache." + bucket + "." + outcome)
