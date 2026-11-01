"""Read quote HTML without changing its UTF-8 parser input or recording payloads."""

import gzip
from types import MappingProxyType

from stock_lab_core import report_build
from stock_lab_core.performance import count_event, timed_call


report_build.register_loaded_source(__name__, __file__)
IMPORTED_SOURCE = MappingProxyType(dict(report_build._LOADED[__name__]))


@timed_call("prices", "quote_html_body")
def read_quote_html(response, *, provider="yahoo_overnight") -> str:
    """Read once, undo declared gzip layers, then use the existing UTF-8 policy."""
    raw = response.read()
    count_event(provider + ".wire_bytes", len(raw))
    headers = getattr(response, "headers", {}) or {}
    encoding = headers.get("Content-Encoding", "") or ""
    if not isinstance(encoding, str):
        raise ValueError("Unsupported quote HTML content encoding")
    codings = [coding.strip().casefold() for coding in encoding.split(",")]
    if any(coding not in {"", "identity", "gzip"} for coding in codings):
        raise ValueError("Unsupported quote HTML content encoding")

    if "gzip" in codings:
        count_event(provider + ".gzip_response")
        # Content codings are applied in header order and removed in reverse.
        for coding in reversed(codings):
            if coding == "gzip":
                raw = gzip.decompress(raw)
    else:
        count_event(provider + ".identity_response")
    count_event(provider + ".decoded_bytes", len(raw))
    return raw.decode("utf-8", errors="ignore")
