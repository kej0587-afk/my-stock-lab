from email.message import Message
from functools import cache
import gzip
import hashlib
from http.client import IncompleteRead
import importlib.util
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from stock_lab_core import quote_html, report_build
from stock_lab_core.performance import PerformanceTrace


MISSING = object()
HTML = b'<html>\x00\xef\xbb\xbf\xe9\x9f\x93\xff\xc3(\xed\xa0\x80"quote":123.45</html>\r\n'


class Response:
    def __init__(self, body, headers=MISSING):
        self.body = body
        self.reads = 0
        if headers is not MISSING:
            self.headers = headers

    def read(self):
        self.reads += 1
        if isinstance(self.body, BaseException):
            raise self.body
        return self.body


def headers(value, key="Content-Encoding"):
    result = Message()
    result[key] = value
    return result


@pytest.mark.parametrize("body", [b"", HTML, b"\xff\xfe\x80", HTML * 25000],
                         ids=["empty", "html", "bad_utf8", "large_html"])
@pytest.mark.parametrize("metadata", [
    MISSING, None, {}, headers(""), headers(" \t "),
    headers("identity"), headers(" IdEnTiTy, identity, "),
])
def test_identity_preserves_full_existing_parser_input(body, metadata):
    response = Response(body, metadata)
    with PerformanceTrace() as trace:
        assert quote_html.read_quote_html(response) == body.decode("utf-8", errors="ignore")
    assert response.reads == 1
    assert trace.report()["transport_events"] == {
        "yahoo_overnight.wire_bytes": len(body),
        "yahoo_overnight.identity_response": 1,
        "yahoo_overnight.decoded_bytes": len(body),
    }


@pytest.mark.parametrize("coding", [
    "gzip", " GZiP \t", " identity, GZip ", "gzip, identity",
    "identity, gzip, identity, GZIP, identity", " gzip, gzip, gzip ",
])
@pytest.mark.parametrize("key", ["Content-Encoding", "cOnTeNt-EnCoDiNg"])
def test_gzip_layers_preserve_exact_parser_input_and_count_once(coding, key):
    wire = HTML
    for token in coding.split(","):
        if token.strip().casefold() == "gzip":
            wire = gzip.compress(wire, mtime=0)
    response = Response(wire, headers(coding, key))
    with PerformanceTrace() as trace:
        result = quote_html.read_quote_html(response, provider="custom_quote")
    assert result == HTML.decode("utf-8", errors="ignore")
    assert response.reads == 1
    assert trace.report()["transport_events"] == {
        "custom_quote.wire_bytes": len(wire),
        "custom_quote.gzip_response": 1,
        "custom_quote.decoded_bytes": len(HTML),
    }


@pytest.mark.parametrize("body", [b"", HTML, HTML * 25000], ids=["empty", "html", "large_html"])
def test_multiple_gzip_members_join_bytes_before_utf8_decode(body):
    # A UTF-8 sequence crossing the member boundary must remain intact.
    parts = [b"<html>\xe9", b"\x9f\x93" + body, b"</html>"]
    wire = b"".join(gzip.compress(part, mtime=0) for part in parts)
    response = Response(wire, headers("gzip"))
    with PerformanceTrace() as trace:
        result = quote_html.read_quote_html(response)
    assert result == b"".join(parts).decode("utf-8", errors="ignore")
    assert response.reads == 1
    assert trace.report()["transport_events"]["yahoo_overnight.decoded_bytes"] == sum(map(len, parts))


@pytest.mark.parametrize("metadata", [MISSING, {}, headers("identity")])
def test_gzip_magic_without_encoding_is_not_sniffed(metadata):
    wire = gzip.compress(HTML, mtime=0)
    response = Response(wire, metadata)
    with PerformanceTrace() as trace:
        result = quote_html.read_quote_html(response)
    assert result == wire.decode("utf-8", errors="ignore")
    assert result != HTML.decode("utf-8", errors="ignore")
    assert response.reads == 1
    assert trace.report()["transport_events"] == {
        "yahoo_overnight.wire_bytes": len(wire), "yahoo_overnight.identity_response": 1,
        "yahoo_overnight.decoded_bytes": len(wire),
    }


@pytest.mark.parametrize("coding", [
    "br", "deflate", "gzip, br", "PRIVATE_HEADER_VALUE, gzip", 123, ["gzip"],
])
def test_unsupported_or_malformed_encoding_has_fixed_error(coding, caplog):
    response = Response(b"PRIVATE_BODY_VALUE", {"Content-Encoding": coding})
    with PerformanceTrace() as trace:
        with pytest.raises(ValueError) as caught:
            quote_html.read_quote_html(response)
    assert str(caught.value) == "Unsupported quote HTML content encoding"
    assert response.reads == 1
    report = trace.report()
    assert report["transport_events"] == {"yahoo_overnight.wire_bytes": len(response.body)}
    assert report["functions"][0]["failures"] == 1
    assert "PRIVATE" not in json.dumps(report) + caplog.text


GOOD_GZIP = gzip.compress(HTML, mtime=0)
BAD_CRC = GOOD_GZIP[:-8] + bytes([GOOD_GZIP[-8] ^ 1]) + GOOD_GZIP[-7:]


@pytest.mark.parametrize("wire, coding, error_type", [
    (b"PRIVATE_BODY_VALUE", "gzip", gzip.BadGzipFile),
    (GOOD_GZIP[:-1], "gzip", EOFError),
    (GOOD_GZIP[:12], "gzip", EOFError),
    (BAD_CRC, "gzip", gzip.BadGzipFile),
    (GOOD_GZIP + GOOD_GZIP[:-1], "gzip", EOFError),
    (gzip.compress(BAD_CRC, mtime=0), "gzip, gzip", gzip.BadGzipFile),
])
def test_corrupt_or_truncated_gzip_propagates_without_decoded_count_or_payloads(
    wire, coding, error_type, caplog,
):
    response = Response(wire, headers(coding))
    with PerformanceTrace() as trace:
        with pytest.raises(error_type) as caught:
            quote_html.read_quote_html(response)
    assert response.reads == 1
    report = trace.report()
    assert report["transport_events"] == {
        "yahoo_overnight.wire_bytes": len(wire), "yahoo_overnight.gzip_response": 1,
    }
    recorded = json.dumps(report) + caplog.text
    assert "PRIVATE" not in recorded
    assert str(caught.value) not in recorded
    assert report["functions"][0]["exceptions"][0]["message_redacted"] is True


@pytest.mark.parametrize("error", [
    TimeoutError("PRIVATE_RAW_ERROR https://private.invalid/PRIVATE_TICKER"),
    IncompleteRead(b"PRIVATE_PARTIAL_BODY", 900),
])
def test_read_failure_propagates_same_error_without_retry_or_recording_payloads(error, caplog):
    response = Response(error, headers("gzip"))
    with PerformanceTrace() as trace:
        with pytest.raises(type(error)) as caught:
            quote_html.read_quote_html(response)
    assert caught.value is error
    assert response.reads == 1
    report = trace.report()
    assert report["transport_events"] == {}
    assert report["functions"][0]["failures"] == 1
    assert "PRIVATE" not in json.dumps(report) + caplog.text
    assert str(error) not in json.dumps(report) + caplog.text


@pytest.mark.parametrize("body, error_type", [
    (None, TypeError), (123, TypeError), ("not raw bytes", AttributeError),
])
def test_missing_or_malformed_body_propagates_after_one_read(body, error_type):
    response = Response(body)
    with pytest.raises(error_type):
        quote_html.read_quote_html(response)
    assert response.reads == 1


def test_missing_read_method_propagates_without_events():
    with PerformanceTrace() as trace:
        with pytest.raises(AttributeError):
            quote_html.read_quote_html(SimpleNamespace())
    assert trace.report()["transport_events"] == {}


def test_helper_has_no_cache_and_outer_cache_hits_do_not_duplicate_counters():
    response = Response(GOOD_GZIP, headers("gzip"))

    @cache
    def fetch():
        return quote_html.read_quote_html(response)

    with PerformanceTrace() as trace:
        assert fetch() == fetch() == HTML.decode("utf-8", errors="ignore")
        assert response.reads == 1
        assert quote_html.read_quote_html(response) == fetch()
    assert response.reads == 2
    assert trace.report()["transport_events"] == {
        "yahoo_overnight.wire_bytes": 2 * len(GOOD_GZIP),
        "yahoo_overnight.gzip_response": 2,
        "yahoo_overnight.decoded_bytes": 2 * len(HTML),
    }
    assert trace.report()["functions"][0]["calls"] == 2
    with PerformanceTrace() as rerender:
        assert fetch() == HTML.decode("utf-8", errors="ignore")
    assert rerender.report()["transport_events"] == {}
    assert rerender.report()["functions"] == []


def test_timing_includes_read_decompression_and_decode_without_phase_callbacks(monkeypatch):
    now = [0]
    phases = []

    class DecodedBytes(bytes):
        def decode(self, *args, **kwargs):
            now[0] += 2
            return super().decode(*args, **kwargs)

    class SlowResponse(Response):
        def read(self):
            now[0] += 5
            return super().read()

    decompress = gzip.decompress

    def slow_decompress(raw):
        now[0] += 3
        return DecodedBytes(decompress(raw))

    monkeypatch.setattr(quote_html.gzip, "decompress", slow_decompress)
    response = SlowResponse(GOOD_GZIP, headers("gzip"))
    with PerformanceTrace(clock=lambda: now[0], on_phase=lambda *args: phases.append(args)) as trace:
        assert quote_html.read_quote_html(response) == HTML.decode("utf-8", errors="ignore")
    entries = trace.report()["functions"]
    assert len(entries) == 1
    assert (entries[0]["category"], entries[0]["name"]) == ("prices", "quote_html_body")
    assert entries[0]["total_seconds"] == 10
    assert response.reads == 1
    assert phases == []


def test_real_import_source_is_immutable_copy_and_can_restore_registry_without_disk_read(monkeypatch):
    snapshot = quote_html.IMPORTED_SOURCE
    original = dict(snapshot)
    assert quote_html.report_build is report_build
    assert isinstance(snapshot, MappingProxyType)
    assert original == {
        "path": str(Path(quote_html.__file__).resolve()),
        "sha256": hashlib.sha256(Path(quote_html.__file__).read_bytes()).hexdigest(),
    }
    with pytest.raises(TypeError):
        snapshot["sha256"] = "changed"
    with pytest.raises(TypeError):
        del snapshot["path"]

    monkeypatch.setattr(report_build, "_LOADED", {quote_html.__name__: dict(original)})
    report_build._LOADED[quote_html.__name__]["sha256"] = "changed registry value"
    assert dict(snapshot) == original
    report_build._LOADED[quote_html.__name__] = {"path": "other", "sha256": "other"}
    assert dict(snapshot) == original
    report_build._LOADED.clear()
    monkeypatch.setattr(report_build, "_file_hash", lambda _: pytest.fail("Unexpected disk hash"))
    assert quote_html.read_quote_html(Response(HTML)) == HTML.decode("utf-8", errors="ignore")
    assert report_build._LOADED == {}
    report_build._LOADED[quote_html.__name__] = dict(snapshot)
    assert report_build._LOADED[quote_html.__name__] == original


def test_module_execution_registers_real_source_exactly_once(monkeypatch):
    monkeypatch.setattr(report_build, "_LOADED", {})
    register = report_build.register_loaded_source
    calls = []

    def record(name, filename):
        calls.append((name, filename))
        register(name, filename)

    monkeypatch.setattr(report_build, "register_loaded_source", record)
    spec = importlib.util.spec_from_file_location("stock_lab_core._quote_html_import_test", quote_html.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert calls == [(spec.name, quote_html.__file__)]
    assert dict(module.IMPORTED_SOURCE) == report_build._LOADED[spec.name]
    assert module.IMPORTED_SOURCE is not report_build._LOADED[spec.name]
    assert module.read_quote_html(Response(HTML)) == HTML.decode("utf-8", errors="ignore")
    assert len(calls) == 1
