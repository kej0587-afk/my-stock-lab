"""At most three official pages, on explicit review or report generation."""

from datetime import datetime, timezone
import time

import requests
from lxml import etree

from stock_lab_core.msft_ir_review import (
    HOME, source_identity, discover_msft_release, parse_msft_release, attach_msft_call,
)

MAX_SECONDS, MAX_BYTES = 12, 2_000_000

from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)


def read_official_page(url, deadline):
    if not source_identity(url):
        raise ValueError("untrusted_ir_url")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("request_deadline")
    response = requests.get(url, timeout=(min(2, remaining), min(4, remaining)),
        allow_redirects=False, stream=True, headers={"User-Agent": "StockLab-MSFT-IRReview/1.0"})
    try:
        if response.status_code != 200:
            raise ValueError("http_" + str(response.status_code))
        if "html" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("unexpected_content_type")
        data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError("response_too_large")
            if time.monotonic() > deadline:
                raise ValueError("request_deadline")
        return bytes(data)
    finally:
        response.close()


def load_msft_business_evidence(now=None, *, read_page=read_official_page):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    deadline = time.monotonic() + MAX_SECONDS
    candidate = discover_msft_release(read_page(HOME, deadline))
    packet = parse_msft_release(read_page(candidate["release"], deadline), candidate, now)
    if candidate.get("call"):
        try:
            attach_msft_call(packet, read_page(candidate["call"], deadline), candidate)
        except (requests.RequestException, ValueError, TypeError, KeyError, etree.LxmlError):
            # No old transcript fallback and no provider body in logs/downloads.
            packet["issues"].append("call_unavailable_or_unverified")
    else:
        packet["issues"].append("call_link_missing")
    expected = {"company_revenue", "cloud_revenue", "azure_growth", "reported_capex", "cash_ppe", "ocf", "reported_fcf", "next_capex"}
    packet["missing_metrics"] = sorted(expected - {m["key"] for m in packet["metrics"]})
    packet["status"] = "confirmed" if not packet["missing_metrics"] and not packet["issues"] else "partial"
    packet["discovery_url"] = HOME
    return packet
