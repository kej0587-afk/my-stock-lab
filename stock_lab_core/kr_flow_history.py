"""Bounded access to the Naver daily feed used by pykrx/FDR money flow."""

import logging
import re
import time
from threading import Lock
from xml.etree import ElementTree

import pandas as pd
import requests
from urllib3.exceptions import HTTPError as TransportError

from stock_lab_core.result_cache import cache_result
from stock_lab_core.http_body import read_response_body as _read_body


_URL = "https://fchart.stock.naver.com/sise.nhn"
_TIMEOUT = (2, 4)
_BODY_BUDGET_SECONDS = 6
_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _unavailable(reason):
    frame = pd.DataFrame()
    frame.attrs["transport_error"] = reason
    return frame


def parse_history(text, start, end):
    if isinstance(text, bytes):
        declaration = re.search(br"encoding\s*=\s*['\"]([^'\"]+)['\"]", text[:160], re.I)
        encoding = declaration[1].decode("ascii").lower().replace("_", "-") if declaration else "utf-8-sig"
        if encoding not in {"euc-kr", "cp949", "utf-8", "utf-8-sig"}:
            raise ValueError("Unsupported KR history XML encoding")
        text = text.decode(encoding)
    rows = []
    for item in ElementTree.fromstring(text).iter("item"):
        fields = item.get("data", "").split("|")
        if len(fields) == 6:
            rows.append(fields)
    frame = pd.DataFrame(rows, columns=["Date", *_COLUMNS])
    frame.index = pd.to_datetime(frame.pop("Date"), format="%Y%m%d", errors="coerce")
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.loc[~frame.index.isna()].dropna(subset=_COLUMNS)
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.loc[start:end]
    frame.attrs["source"] = "Naver daily (HTTPS)"
    return frame


class KrFlowHistoryReader:
    def __init__(self, *, request=None, clock=time.monotonic):
        self._request = request or requests.get
        self._clock = clock
        self._lock = Lock()
        self._failures = 0
        self._retry_after = 0.0

    def read(self, ticker, *, now=None, start=None):
        code = str(ticker).strip().upper().split(".", 1)[0]
        if not re.fullmatch(r"[0-9A-Z]{6}", code):
            return pd.DataFrame()
        with self._lock:
            if self._clock() < self._retry_after:
                return _unavailable("provider_cooldown")
        end = pd.Timestamp(now if now is not None else pd.Timestamp.now(tz="Asia/Seoul"))
        if end.tzinfo is not None:
            end = end.tz_convert("Asia/Seoul").tz_localize(None)
        end = end.normalize()
        start = end - pd.DateOffset(years=1) if start is None else pd.Timestamp(start)
        if start.tzinfo is not None:
            start = start.tz_convert("Asia/Seoul").tz_localize(None)
        start = start.normalize()
        if pd.isna(start) or start > end:
            return pd.DataFrame()
        response = None
        deadline = self._clock() + _BODY_BUDGET_SECONDS
        try:
            # Same adjusted daily feed as pykrx, without its unbounded HTTP call.
            response = self._request(
                _URL, params={"symbol": code, "timeframe": "day",
                              "count": (end - start).days + 2, "requestType": "0"},
                headers={"User-Agent": "StockLab/1.0", "Referer": "https://finance.naver.com/"},
                timeout=_TIMEOUT, stream=True,
            )
            response.raise_for_status()
            frame = parse_history(_read_body(response, deadline, self._clock), start, end)
        except (requests.RequestException, TransportError, OSError, ElementTree.ParseError, ValueError) as exc:
            with self._lock:
                self._failures += 1
                # Stop a provider outage becoming hundreds of sequential timeouts.
                if self._failures >= 3 and self._clock() >= self._retry_after:
                    self._retry_after = self._clock() + 60
                    logging.warning("KR flow history unavailable; pausing provider for 60s (%s)",
                                    type(exc).__name__)
            return _unavailable(type(exc).__name__)
        finally:
            if callable(getattr(response, "close", None)):
                response.close()
        with self._lock:
            if self._clock() >= self._retry_after:
                self._failures = 0
        return frame


_reader = KrFlowHistoryReader()


@cache_result(ttl=900, failure_ttl=15, is_success=lambda frame: not frame.empty)
def load_kr_flow_history(ticker, *, start=None):
    return _reader.read(ticker, start=start)
