"""Bound earnings-calendar retries after provider-wide throttling."""

import logging
import threading
import time

from yfinance.exceptions import YFRateLimitError


class EarningsCalendarReader:
    def __init__(self, *, clock=time.monotonic, cooldown=180):
        self._clock = clock
        self._cooldown = cooldown
        self._retry_after = 0.0
        self._lock = threading.Lock()

    def read(self, ticker, fetch):
        # Serialize the first probe so a batch does not hammer an already
        # throttled provider. The injected fetch must set its own HTTP timeout.
        with self._lock:
            if self._clock() < self._retry_after:
                return {"ok": False, "status": "rate_limited", "label": "실적일 조회 제한 · 잠시 후 재시도"}
            try:
                return {"ok": True, "calendar": fetch(ticker)}
            except YFRateLimitError:
                self._retry_after = self._clock() + self._cooldown
                logging.warning("Yahoo earnings calendar rate limited; pausing calendar requests for %ss", self._cooldown)
                return {"ok": False, "status": "rate_limited", "label": "실적일 조회 제한 · 잠시 후 재시도"}
            except Exception as exc:
                logging.warning("Earnings calendar unavailable for %s (%s)", ticker, type(exc).__name__)
                return {"ok": False, "status": "lookup_error", "label": "실적발표일 조회 실패"}


earnings_calendar_reader = EarningsCalendarReader()
