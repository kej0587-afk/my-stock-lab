"""App-wide SEC request limiter and access-limit pause (user decision A, 2026-11-27 02:06 KST).

Every HTTP request to an SEC host from this process (all users, screens, background work and
retries) passes one sliding-window limiter installed on ``requests.Session.send``:

* trial: at most 8 requests in any 1-second window, until ``TRIAL_ENDS_AT``; kept after it because ``ADOPTED``;
* legacy: at most 5 in any 1-second window (the previous 0.2 s spacing), used after the trial, after a
  second access limit, or if the window ever counts more than 8 starts.

A 429 (or a 403 page that says the request rate threshold was exceeded) pauses every SEC request for the
``Retry-After`` time (600 s when SEC gives none). Paused requests raise ``SecRateLimited`` so callers show
the filing as 일부 조회 실패. A second limit after resuming switches to legacy for good.
"""

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from urllib.parse import urlsplit

import requests

from stock_lab_core.performance import count_event, measure

KST = timezone(timedelta(hours=9))
SEC_HOSTS = {"www.sec.gov", "data.sec.gov", "efts.sec.gov"}
TRIAL_LIMIT = 8
LEGACY_LIMIT = 5
WINDOW = 1.0
DEFAULT_PAUSE = 600.0
# Trial A runs at most 7 days from its production start (recorded in HANDOFF); it is not extended.
TRIAL_STARTS_AT = datetime(2026, 11, 27, 2, 30, tzinfo=KST)
TRIAL_ENDS_AT = TRIAL_STARTS_AT + timedelta(days=7)
# Adopted 2026-11-27: 3 pairs (docs/maintenance/20261127_sec_rate_trial_a_pairs.md) met both rules: SEC wait median
# 44.4 -> 26.7 s (-40%), time-limit failures 16 -> 8, official count 21 -> 23. Limit and access-limit rules stay.
ADOPTED = True


def _forced_legacy():
    """Comparison switch: secret/env ``sec_rate_mode = "legacy"`` runs the old 5/s for a whole boot."""
    global _FORCED
    if _FORCED is None:
        try:
            from stock_lab_core.economic_releases import _api_key
            _FORCED = _api_key("sec_rate_mode").lower() == "legacy"
        except Exception:  # a missing secrets file must not stop SEC collection
            _FORCED = False
    return _FORCED


_FORCED = None


class SecRateLimited(requests.ConnectionError):
    """SEC access limit active: no request was sent."""


class SecLimiter:
    def __init__(self, *, clock=time.monotonic, sleep=time.sleep, wall=lambda: datetime.now(KST)):
        self._clock, self._sleep, self._wall = clock, sleep, wall
        self._lock = threading.Lock()
        self._starts = deque()
        self._paused_until = 0.0
        self._limits = 0
        self.legacy_reason = ""

    def limit(self):
        if self.legacy_reason or _forced_legacy():
            return LEGACY_LIMIT
        if ADOPTED or self._wall() < TRIAL_ENDS_AT:
            return TRIAL_LIMIT
        return LEGACY_LIMIT

    def mode(self):
        return "trial_8" if self.limit() == TRIAL_LIMIT else "legacy_5"

    def acquire(self):
        """Block until a slot is free in the 1 s window; raise while an SEC access limit is active."""
        with measure("external_data", "sec_rate_wait"):
            while True:
                with self._lock:
                    now = self._clock()
                    if now < self._paused_until:
                        count_event("sec.blocked_by_access_limit")
                        raise SecRateLimited("sec_rate_limited")
                    while self._starts and now - self._starts[0] >= WINDOW:
                        self._starts.popleft()
                    if len(self._starts) < self.limit():
                        self._starts.append(now)
                        if len(self._starts) > TRIAL_LIMIT:  # self-check: never more than 8 per second
                            self.legacy_reason = "window_over_8"
                        count_event("sec.request")
                        count_event("sec.mode." + self.mode())
                        return
                    delay = WINDOW - (now - self._starts[0])
                self._sleep(max(delay, 0.001))

    def access_limited(self, retry_after=None):
        with self._lock:
            self._limits += 1
            pause = DEFAULT_PAUSE
            try:
                pause = max(1.0, float(retry_after)) if retry_after not in (None, "") else DEFAULT_PAUSE
            except (TypeError, ValueError):
                pause = DEFAULT_PAUSE
            self._paused_until = max(self._paused_until, self._clock() + pause)
            if self._limits >= 2:
                self.legacy_reason = "repeated_access_limit"
        count_event("sec.access_limit")
        logging.warning("SEC access limit; pausing all SEC requests for %.0fs (mode %s)", pause, self.mode())

    def status(self):
        with self._lock:
            return {"mode": self.mode(), "paused_seconds": max(0.0, self._paused_until - self._clock()),
                    "access_limits": self._limits, "legacy_reason": self.legacy_reason,
                    "trial_ends_at": TRIAL_ENDS_AT.isoformat()}


limiter = SecLimiter()
_prepaid = ContextVar("sec_rate_prepaid", default=False)
_installed = False


@contextmanager
def slot():
    """Take one limiter slot for the next SEC request made in this context (no second count)."""
    limiter.acquire()
    token = _prepaid.set(True)
    try:
        yield
    finally:
        _prepaid.reset(token)
_original_send = None


def _is_access_limit(response):
    if response.status_code == 429:
        return True
    if response.status_code == 403:
        # A 403 body is small; reading it keeps it available to the caller's iter_content.
        try:
            return "Request Rate Threshold Exceeded" in (response.text or "")[:4000]
        except (requests.RequestException, RuntimeError):
            return False
    return False


def _send(self, request, **kwargs):
    if urlsplit(request.url).hostname not in SEC_HOSTS:
        return _original_send(self, request, **kwargs)
    if _prepaid.get():
        _prepaid.set(False)  # one prepaid slot covers exactly one send (redirect hops pay again)
    else:
        limiter.acquire()
    response = _original_send(self, request, **kwargs)
    if _is_access_limit(response):
        limiter.access_limited(response.headers.get("Retry-After"))
    return response


def install():
    """Route every requests call in this process through the SEC limiter (idempotent)."""
    global _installed, _original_send
    if _installed:
        return
    _original_send = requests.Session.send
    requests.Session.send = _send
    _installed = True


install()
