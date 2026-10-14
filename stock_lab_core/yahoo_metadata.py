"""Share successful Yahoo metadata and throttling across dashboard views."""

from collections import Counter, OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import logging
import threading
import time

from yfinance.exceptions import YFRateLimitError


def is_rate_limit_error(exc):
    return isinstance(exc, YFRateLimitError) or getattr(exc, "code", None) == 429 or getattr(
        getattr(exc, "response", None), "status_code", None
    ) == 429


class YahooMetadataReader:
    def __init__(self, *, clock=time.monotonic, sleep=time.sleep, cooldown=180,
                 min_interval=0.1, max_entries=512, stale_ttl=7 * 86400):
        self._clock, self._sleep = clock, sleep
        self._cooldown, self._min_interval = cooldown, min_interval
        self._max_entries, self._stale_ttl = max_entries, stale_ttl
        self._lock = threading.RLock()
        self._successes, self._failures = OrderedDict(), OrderedDict()
        self._retry_after, self._last_started = 0.0, float("-inf")
        self._rate_limit_streak = 0
        self._counts = Counter()

    def _remember(self, store, key, value):
        store[key] = value
        store.move_to_end(key)
        while len(store) > self._max_entries:
            store.popitem(last=False)

    def _unavailable(self, key, status, allow_stale):
        entry = self._successes.get(key)
        if allow_stale and entry and self._clock() - entry[0] <= self._stale_ttl:
            self._counts["stale_hits"] += 1
            return {"ok": False, "status": "stale", "data": deepcopy(entry[2]),
                    "fetched_at": entry[1], "stale": True, "reason": status}
        return {"ok": False, "status": status, "data": {}, "fetched_at": "", "stale": False}

    def read(self, operation, ticker, fetch, *, ttl=86400, failure_ttl=60,
             is_success=bool, allow_stale=True):
        key = (operation, str(ticker or "").strip().upper())
        # Hold the lock through HTTP completion so only one view probes Yahoo.
        with self._lock:
            now = self._clock()
            entry = self._successes.get(key)
            if entry and now - entry[0] < ttl:
                self._counts["cache_hits"] += 1
                return {"ok": True, "status": "available", "data": deepcopy(entry[2]),
                        "fetched_at": entry[1], "stale": False}
            if now < self._retry_after:
                self._counts["blocked"] += 1
                return self._unavailable(key, "rate_limited", allow_stale)
            failure = self._failures.get(key)
            if failure and now < failure[0]:
                self._counts["blocked"] += 1
                return self._unavailable(key, failure[1], allow_stale)
            delay = self._min_interval - (now - self._last_started)
            if delay > 0:
                self._sleep(delay)
            self._last_started = self._clock()
            self._counts["attempts"] += 1
            try:
                value = fetch(key[1])
                success = is_success(value)
            except Exception as exc:
                if is_rate_limit_error(exc):
                    self._rate_limit_streak = min(self._rate_limit_streak + 1, 5)
                    pause = min(self._cooldown * 2 ** (self._rate_limit_streak - 1), 1800)
                    self._retry_after = self._clock() + pause
                    self._counts["rate_limits"] += 1
                    logging.warning("Yahoo metadata rate limited; pausing requests for %ss", pause)
                    return self._unavailable(key, "rate_limited", allow_stale)
                success, value, status = False, None, "error"
            else:
                status = "no_data"
            if success:
                fetched_at = datetime.now(timezone.utc).isoformat()
                self._remember(self._successes, key, (self._clock(), fetched_at, deepcopy(value)))
                self._failures.pop(key, None)
                self._rate_limit_streak = 0
                return {"ok": True, "status": "available", "data": deepcopy(value),
                        "fetched_at": fetched_at, "stale": False}
            self._remember(self._failures, key, (self._clock() + failure_ttl, status))
            return self._unavailable(key, status, allow_stale)

    def clear_cache(self):
        # Manual refresh must not bypass the provider's active rate limit.
        with self._lock:
            self._successes.clear()
            self._failures.clear()

    def counts(self):
        with self._lock:
            return dict(self._counts)


yahoo_metadata_reader = YahooMetadataReader()
