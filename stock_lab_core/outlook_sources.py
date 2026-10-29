"""Bounded official IR discovery, separate from quarterly-result collection."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import threading
import time

import requests
from lxml import etree

from stock_lab_core.official_outlook import discover_oracle_outlook, parse_oracle_outlook
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

# Public feed and parameters used by Oracle's official Q4 news widget.
_PROFILES = {"ORCL": dict(
    url="https://investor.oracle.com/feed/PressRelease.svc/GetPressReleaseList",
    params=dict(LanguageId=1, bodyType=0, pressReleaseDateFilter=1,
                categoryId="1cb807d2-208f-4bc3-9133-6a9ad45ac3b0", pageSize=60,
                pageNumber=0, includeTags="true", year=-1, excludeSelection=1),
    discover=discover_oracle_outlook, parse=parse_oracle_outlook)}
SUCCESS_TTL, FAILURE_TTL = 6 * 3600, 60
MAX_BYTES, MAX_SECONDS = 2_000_000, 10
_CACHE = {}
_LOCK = threading.Lock()


def clear_outlook_cache():
    with _LOCK:
        _CACHE.clear()


def _read(url, deadline, *, params=None):
    if time.monotonic() >= deadline:
        raise ValueError("request_deadline")
    response = requests.get(url, params=params, timeout=(2, 3), allow_redirects=False,
                            stream=True, headers={"User-Agent": "StockLab-OfficialOutlook/1.0"})
    try:
        if response.status_code != 200:
            raise ValueError("http_" + str(response.status_code))
        data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError("response_too_large")
            if time.monotonic() >= deadline:
                raise ValueError("request_deadline")
        return bytes(data)
    finally:
        response.close()


def load_official_outlooks(now=None):
    """One list + at most one article; no render I/O or broad company scan.

    Single-flight cache avoids duplicate requests on simultaneous sessions.
    Failures are short-lived and explicit; no frozen manual guidance fallback.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    if not _LOCK.acquire(timeout=.1):
        return dict(events=[], sources=[dict(ticker="ORCL", status="unavailable", reason="collection_in_progress")])
    try:
        cached = _CACHE.get("ORCL")
        if cached and cached[1] <= now and time.monotonic() - cached[0] < cached[2]:
            result = deepcopy(cached[3])
            result["sources"][0]["from_cache"] = True
            return result
        spec = _PROFILES["ORCL"]
        source = dict(ticker="ORCL", status="unavailable", reason="", checked_at=now.isoformat(),
                      from_cache=False, source_url=spec["url"])
        result = dict(events=[], sources=[source])
        deadline = time.monotonic() + MAX_SECONDS
        try:
            payload = json.loads(_read(spec["url"], deadline, params=spec["params"]))
            if not isinstance(payload, dict):
                raise ValueError("invalid_ir_list")
            candidate = spec["discover"](payload, now)
            if candidate is None:
                source["reason"] = "no_recent_investor_day"
            else:
                event = spec["parse"](_read(candidate["source_url"], deadline), candidate, now)
                result["events"].append(event)
                source.update(status=event["status"], source_url=candidate["source_url"])
        except requests.RequestException as exc:
            source["reason"] = "request_failed:" + type(exc).__name__
        except (ValueError, TypeError, KeyError, UnicodeError, etree.LxmlError) as exc:
            source["reason"] = str(exc) if isinstance(exc, ValueError) and str(exc) in {
                "request_deadline", "response_too_large", "invalid_ir_list", "ir_layout_changed",
                "announcement_mismatch", "untrusted_ir_url"} else "invalid_source:" + type(exc).__name__
            if str(exc).startswith("http_"):
                source["reason"] = str(exc)
        if source["reason"]:
            logging.info("Official outlook ORCL: %s", source["reason"])
        ttl = SUCCESS_TTL if source["status"] in {"confirmed", "partial"} else FAILURE_TTL
        _CACHE["ORCL"] = (time.monotonic(), now, ttl, deepcopy(result))
        return result
    finally:
        _LOCK.release()


load_official_outlooks.clear = clear_outlook_cache
