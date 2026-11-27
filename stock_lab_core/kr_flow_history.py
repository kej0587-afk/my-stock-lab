"""Bounded access to the Naver daily feed used by pykrx/FDR money flow."""

import logging
from copy import deepcopy
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock, get_ident
from xml.etree import ElementTree

import pandas as pd
import requests
from urllib3.exceptions import HTTPError as TransportError

from stock_lab_core.result_cache import UncachedValue, cache_result
from stock_lab_core.http_body import read_response_body as _read_body
from stock_lab_core.performance import count_event, measure


_URL = "https://fchart.stock.naver.com/sise.nhn"
_TIMEOUT = (2, 4)
_BODY_BUDGET_SECONDS = 6
_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
_connections = ContextVar("kr_history_connections", default=None)
_request_scope = ContextVar("kr_history_request_scope", default=None)
_request_audit = ContextVar("kr_history_request_audit", default=None)
_cache_reuse_probe = ContextVar("kr_history_cache_reuse_probe", default=None)
_request_generation = object()


@contextmanager
def reuse_kr_history_requests():
    """Share only successful identical requests within one joined calculation.

    Keys are resolved inside the reader, after its original date normalization.
    Within the scope a request is served from an already fetched wider window of
    the same code and end date, sliced to the requested start (the feed returns the
    latest N daily bars and the parser slices start:end, so the rows are the same).
    Windows shorter than one year are fetched as the one-year window that the
    money-flow reader asks for anyway (2026-11-26: 384 requests for ~100 tickers).
    No cross-run retention or change to the provider cache TTL.
    """
    if _request_scope.get() is not None:
        yield
        return
    token = _request_scope.set(({}, Lock()))
    audit_token = _request_audit.set((set(), Lock()))
    count_event("kr_history_scope.enabled_v1")
    try:
        yield
    finally:
        _request_audit.reset(audit_token)
        _request_scope.reset(token)


@contextmanager
def reuse_kr_history_connections():
    """Reuse transport only within one batch; each worker owns its session."""
    if _connections.get() is not None:
        yield
        return
    sessions, lock = {}, Lock()
    token = _connections.set((sessions, lock))
    try:
        yield
    finally:
        _connections.reset(token)
        # The caller joins its workers before leaving this scope.
        for session in sessions.values():
            session.close()


def _request_history(*args, **kwargs):
    pool = _connections.get()
    if pool is None:
        return requests.get(*args, **kwargs)
    sessions, lock = pool
    with lock:
        session = sessions.get(get_ident())
        if session is None:
            session = sessions[get_ident()] = requests.Session()
    # Keep the original stateless feed request, while retaining TCP/TLS reuse.
    session.cookies.clear()
    return session.get(*args, **kwargs)


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


def _slice(frame, start, end):
    """Rows start..end of a fetched window, as parse_history would have returned them."""
    out = deepcopy(frame.loc[start:end])
    out.attrs = deepcopy(frame.attrs)
    return out


@contextmanager
def _wait_for_request(lock):
    # Measure acquisition only, never the provider work while holding the lock.
    with measure("prices", "kr_history_lock_wait"):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _record_request(code, start, end):
    audit = _request_audit.get()
    if audit is None:
        count_event("kr_history.request_unscoped")
        return
    seen, lock = audit
    # Run-local keys never leave the process. Only aggregate counts are exported.
    key = (_URL, code, start.value, end.value, "day", (end-start).days+2, "0")
    with lock:
        repeated = key in seen
        seen.add(key)
    # Repeated attempts can be retries/expiry/clear, not necessarily removable.
    count_event("kr_history.request_repeat" if repeated else "kr_history.request_unique")


class KrFlowHistoryReader:
    def __init__(self, *, request=None, clock=time.monotonic):
        self._request = request or _request_history
        self._clock = clock
        self._lock = Lock()
        self._failures = 0
        self._retry_after = 0.0

    def read(self, ticker, *, now=None, start=None):
        default_start = start is None
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
        scope = _request_scope.get()
        if scope is None:
            return self._read_resolved(code, start, end)
        entries, guard = scope
        generation = _request_generation
        wanted = start
        count_event("kr_history_scope.lookup")
        count_event("kr_history_scope.default_start" if default_start
                    else "kr_history_scope.explicit_start")
        with guard:
            wider = [entry for (gen, reader, url, c, s_value, e_value, *_), entry in entries.items()
                     if gen is generation and reader is self and url == _URL and c == code
                     and e_value == end.value and s_value <= wanted.value and entry["frame"] is not None
                     and 0 <= self._clock() - entry["at"] < 900]
        if wider:
            count_event("kr_history_scope.reuse")
            count_event("kr_history_scope.slice_reuse")
            marker = _cache_reuse_probe.get()
            if marker is not None:  # an alias must not start a fresh cache lifetime
                marker[0] = True
            return _slice(wider[0]["frame"], wanted, end)
        # A short window is fetched as the one-year window and sliced (same rows).
        start = min(start, end - pd.DateOffset(years=1))
        # Include the reader/endpoint and all effective request/parse semantics.
        key = (generation, self, _URL, code, start.value, end.value,
               "day", (end - start).days + 2, "0")
        with guard:
            if key not in entries:
                entries[key] = {"lock": Lock(), "frame": None, "at": 0.0}
                count_event("kr_history_scope.unique")
            else:
                count_event("kr_history_scope.repeat")
            entry = entries[key]
        # Different keys never wait on one another. The original bounded I/O
        # and cooldown remain in _read_resolved. A failed result is not memoized.
        with _wait_for_request(entry["lock"]):
            if (generation is _request_generation and entry["frame"] is not None
                    and 0 <= self._clock() - entry["at"] < 900):
                count_event("kr_history_scope.reuse")
                marker = _cache_reuse_probe.get()
                if marker is not None:
                    marker[0] = True
                return _slice(entry["frame"], wanted, end)
            count_event("kr_history_scope.miss")
            frame = self._read_resolved(code, start, end)
            if not frame.empty and generation is _request_generation:
                entry["frame"], entry["at"] = deepcopy(frame), self._clock()
            return _slice(frame, wanted, end) if wanted != start and not frame.empty else frame

    def _read_resolved(self, code, start, end):
        # A worker may have waited behind another request that opened cooldown.
        with self._lock:
            if self._clock() < self._retry_after:
                return _unavailable("provider_cooldown")
        response = None
        deadline = self._clock() + _BODY_BUDGET_SECONDS
        try:
            # Same adjusted daily feed as pykrx, without its unbounded HTTP call.
            with measure("prices", "kr_history_http"):
                count_event("kr_history.request")
                _record_request(code, start, end)
                with measure("prices", "kr_history_headers"):
                    response = self._request(
                        _URL, params={"symbol": code, "timeframe": "day",
                                      "count": (end - start).days + 2, "requestType": "0"},
                        headers={"User-Agent": "StockLab/1.0", "Referer": "https://finance.naver.com/"},
                        timeout=_TIMEOUT, stream=True,
                    )
                response.raise_for_status()
                with measure("prices", "kr_history_body"):
                    body = _read_body(response, deadline, self._clock)
                count_event("kr_history.response")
            with measure("prices", "kr_history_parse"):
                frame = parse_history(body, start, end)
        except (requests.RequestException, TransportError, OSError, ElementTree.ParseError, ValueError) as exc:
            count_event("kr_history.unavailable")
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


@cache_result(ttl=900, failure_ttl=15, is_success=lambda frame: not frame.empty,
              trace_name="kr_history")
def load_kr_flow_history(ticker, *, start=None):
    marker = [False]
    token = _cache_reuse_probe.set(marker)
    try:
        frame = _reader.read(ticker, start=start)
    finally:
        _cache_reuse_probe.reset(token)
    # An alias must not start a fresh 900s cache lifetime for an older snapshot.
    return UncachedValue(frame) if marker[0] else frame


_clear_cached_history = load_kr_flow_history.clear


def _clear_history(*args, **kwargs):
    global _request_generation
    _request_generation = object()
    _clear_cached_history(*args, **kwargs)


load_kr_flow_history.clear = _clear_history
