"""Replay quote HTML through unchanged selection/parsing and real gzip decoding."""

import ast
from copy import deepcopy
from email.message import Message
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from types import MappingProxyType
from unittest.mock import Mock
import urllib.request

import pytest

from stock_lab_core import prices, quote_html
from stock_lab_core.formatters import is_kr_listed, normalize_ticker


ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000
APP_FETCH = "fetch_yahoo_daymarket_price_direct"
CORE_FETCH = "_fetch_yahoo_overnight_page_price"


@lru_cache
def source(path, baseline):
    if baseline:
        return subprocess.run(["git", "show", "b5e0c722:" + path], cwd=ROOT,
                              check=True, capture_output=True, encoding="utf-8").stdout
    return (ROOT / path).read_text(encoding="utf-8-sig")


def app_fetch(baseline=False):
    node = next(n for n in ast.parse(source("app.py", baseline)).body
                if isinstance(n, ast.FunctionDef) and n.name == APP_FETCH)
    env = dict(normalize_ticker=normalize_ticker, is_kr_listed=is_kr_listed,
               urllib=urllib, read_quote_html=quote_html.read_quote_html,
               _extract_yahoo_overnight_price_from_html=prices._extract_yahoo_overnight_price_from_html)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "app.py"), "exec"), env)
    return env[APP_FETCH]


def core_baseline():
    node = next(n for n in ast.parse(source("stock_lab_core/prices.py", True)).body
                if isinstance(n, ast.FunctionDef) and n.name == CORE_FETCH)
    node.decorator_list = []
    env = dict(vars(prices))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<baseline-quote-html>", "exec"), env)
    return env[CORE_FETCH]


class Response:
    def __init__(self, body, coding=""):
        self.body = body
        self.headers = Message()
        if coding:
            self.headers["cOnTeNt-EnCoDiNg"] = coding
        self.reads = self.closed = 0

    def read(self):
        self.reads += 1
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed += 1


def fixture_html(field, expired, escaped):
    payload = {"symbol": "TEST", field + "Price": {"raw": 123.45},
               field + "Time": {"raw": NOW - (1_000_000 if expired else 5)}}
    text = "<html>" + json.dumps(payload, separators=(",", ":")) + "</html>"
    if escaped:
        text = text.replace('"', "&quot;")
    return text.encode() + b"\xff"


@pytest.mark.parametrize("kind", ["app", "core"])
@pytest.mark.parametrize("field", ["overnightMarket", "dayMarket"])
@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("escaped", [False, True])
def test_compressed_and_identity_paths_match_fixed_uncompressed_price(monkeypatch, kind, field, expired, escaped):
    monkeypatch.setattr(prices, "_is_recent_epoch", lambda ts: 0 <= NOW - ts <= 60)
    body = fixture_html(field, expired, escaped)
    old = app_fetch(True) if kind == "app" else core_baseline()
    current = app_fetch() if kind == "app" else prices._fetch_yahoo_overnight_page_price
    response = Response(body)
    request = Mock(return_value=response)
    monkeypatch.setattr(prices.urllib.request, "urlopen", request)
    expected = old("TEST")
    assert expected == (0. if expired else 123.45)
    assert response.reads == response.closed == 1
    old_headers = dict(request.call_args.args[0].header_items())
    old_url = request.call_args.args[0].full_url
    for coding, wire in (("", body), ("gzip", gzip.compress(body))):
        response = Response(wire, coding)
        request.reset_mock(return_value=False, side_effect=False)
        request.return_value = response
        assert current("TEST") == expected
        assert response.reads == response.closed == request.call_count == 1
        assert request.call_args.kwargs == {"timeout": 8}
        req = request.call_args.args[0]
        assert req.full_url == old_url
        headers = dict(req.header_items())
        assert headers.pop("Accept-encoding") == "gzip"
        assert headers == old_headers


@pytest.mark.parametrize("wire,coding", [(b"corrupt", "gzip"), (b"", "br"),
                                          (gzip.compress(b"valid")[:-4], "gzip")])
def test_bad_encoding_keeps_existing_next_source_fallback(monkeypatch, wire, coding):
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: False)
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: False)
    monkeypatch.setattr(prices, "_is_live_priority_us_ticker", lambda ticker: False)
    request = Mock(return_value=Response(wire, coding))
    next_source = Mock(return_value=145.25)
    monkeypatch.setattr(prices.urllib.request, "urlopen", request)
    monkeypatch.setattr(prices, "_fetch_yahoo_quote", next_source)
    assert prices._fetch_us_realtime_price("TEST") == 145.25
    request.assert_called_once()
    next_source.assert_called_once_with("TEST")


def test_parser_remains_exactly_the_same_as_fixed_baseline():
    name = "_extract_yahoo_overnight_price_from_html"
    nodes = [next(n for n in ast.parse(source("stock_lab_core/prices.py", baseline)).body
                  if isinstance(n, ast.FunctionDef) and n.name == name) for baseline in (True, False)]
    assert ast.dump(nodes[0], include_attributes=False) == ast.dump(nodes[1], include_attributes=False)


@pytest.mark.parametrize("stale", [False, True])
def test_import_snapshot_recovers_only_missing_registry_without_relabeling_old_hash(monkeypatch, stale):
    from stock_lab_core import precision_build, report_build

    name = quote_html.__name__
    imported = deepcopy(dict(quote_html.IMPORTED_SOURCE))
    registered = dict(imported, sha256="old-loaded-hash") if stale else None
    monkeypatch.setattr(report_build, "_LOADED", {name: registered} if stale else {})
    monkeypatch.setattr(report_build, "get_report_build_info", lambda *args: {"sources": {}, "stale_modules": []})
    monkeypatch.setattr(precision_build, "MODULES", ())
    node = next(n for n in ast.parse(source("app.py", False)).body
                if isinstance(n, ast.FunctionDef) and n.name == "get_precision_build_info")
    warnings = []
    env = {"__file__": str(ROOT / "app.py"), "st": SimpleNamespace(warning=warnings.append)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "app.py"), "exec"), env)
    result = env[node.name]()
    assert result["sources"][name]["sha256"] == ("old-loaded-hash" if stale else imported["sha256"])
    assert result["restart_required"] == stale
    assert bool(warnings) == stale
    assert dict(quote_html.IMPORTED_SOURCE) == imported


def test_missing_registry_and_changed_disk_remain_stale_in_direct_and_app_metadata(monkeypatch, tmp_path):
    from stock_lab_core import precision_build, report_build

    path = tmp_path / "imported_quote_html.py"
    original = b"# original imported fixture\n"
    changed = b"# source edited after import\n"
    path.write_bytes(original)
    captured = {"path": str(path), "sha256": hashlib.sha256(original).hexdigest()}
    monkeypatch.setattr(quote_html, "IMPORTED_SOURCE", MappingProxyType(captured))
    path.write_bytes(changed)
    name = quote_html.__name__
    monkeypatch.setattr(report_build, "_LOADED", {})
    monkeypatch.setattr(report_build, "get_report_build_info", lambda *args: {"sources": {}, "stale_modules": []})
    monkeypatch.setattr(precision_build, "MODULES", ("quote_html",))
    direct = precision_build.precision_build_info()
    assert direct["sources"][name]["sha256"] == captured["sha256"]
    assert direct["sources"][name]["disk_sha256"] == hashlib.sha256(changed).hexdigest()
    assert direct["restart_required"] is True
    assert direct["stale_modules"] == [name]
    assert report_build._LOADED == {}

    monkeypatch.setattr(precision_build, "MODULES", ())
    node = next(n for n in ast.parse(source("app.py", False)).body
                if isinstance(n, ast.FunctionDef) and n.name == "get_precision_build_info")
    warnings = []
    env = {"__file__": str(ROOT / "app.py"), "st": SimpleNamespace(warning=warnings.append)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "app.py"), "exec"), env)
    wrapped = env[node.name]()
    assert wrapped["sources"][name]["sha256"] == captured["sha256"]
    assert wrapped["sources"][name]["disk_sha256"] == hashlib.sha256(changed).hexdigest()
    assert wrapped["restart_required"] is True
    assert wrapped["stale_modules"] == [name]
    assert len(warnings) == 1
