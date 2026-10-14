"""Bound earnings-calendar retries after provider-wide throttling."""

import time

from stock_lab_core.yahoo_metadata import YahooMetadataReader, yahoo_metadata_reader


class EarningsCalendarReader:
    def __init__(self, *, clock=time.monotonic, cooldown=180, reader=None):
        self._reader = reader or YahooMetadataReader(clock=clock, cooldown=cooldown, min_interval=0)

    def read(self, ticker, fetch):
        result = self._reader.read("calendar", ticker, fetch, ttl=0,
                                   is_success=lambda value: value is not None, allow_stale=False)
        if result["ok"]:
            return {"ok": True, "calendar": result["data"]}
        if result["status"] == "rate_limited":
            return {"ok": False, "status": "rate_limited", "label": "실적일 조회 제한 · 잠시 후 재시도"}
        return {"ok": False, "status": "lookup_error", "label": "실적발표일 조회 실패"}


earnings_calendar_reader = EarningsCalendarReader(reader=yahoo_metadata_reader)
