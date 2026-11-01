"""Source timing must not change quote selection, retries, caches or payloads."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
import urllib.error

import pytest

from stock_lab_core import prices
from stock_lab_core.performance import PerformanceTrace


ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "_fetch_us_realtime_price", "_fetch_yahoo_overnight_page_price",
    "_fetch_yahoo_chart", "_fetch_yahoo_regular_close_price",
    "_fetch_yf_fast_info_price", "_fetch_yf_download_price",
)


class RemoveDiagnostics(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node.decorator_list = []
        return self.generic_visit(node)

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            if node.value.func.id == "_quote_transport_event":
                return None
        return self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        node = self.generic_visit(node)
        if node.name and not any(isinstance(n, ast.Name) and n.id == node.name for n in ast.walk(node)):
            node.name = None
        return node


@pytest.mark.parametrize("name", NAMES)
def test_provider_body_matches_fixed_revision_except_diagnostics(name):
    before = subprocess.run(
        ["git", "show", "5a859433:stock_lab_core/prices.py"], cwd=ROOT,
        capture_output=True, check=True, encoding="utf-8",
    ).stdout
    after = (ROOT / "stock_lab_core/prices.py").read_text(encoding="utf-8-sig")
    functions = []
    for source in (before, after):
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
        functions.append(ast.dump(RemoveDiagnostics().visit(deepcopy(node)), include_attributes=False))
    assert functions[0] == functions[1]


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


@pytest.mark.parametrize("kind", ["chart", "overnight", "regular_close"])
@pytest.mark.parametrize("outcome", ["success", "empty", "timeout", "http_429", "bad_json"])
def test_transport_counts_actual_requests_without_exposing_payload(monkeypatch, kind, outcome):
    prices._fetch_yahoo_regular_close_price.clear()
    monkeypatch.setattr(prices, "_looks_like_us_equity_ticker", lambda ticker: True)
    monkeypatch.setattr(prices, "_last_candle_close", lambda result: 145.25)
    monkeypatch.setattr(prices, "_extract_yahoo_overnight_price_from_html",
                        lambda text, ticker: 145.25 if outcome == "success" else 0.)
    row = {"meta": {"symbol": "TEST"}, "indicators": {"quote": [{"close": [None, 145.25]}]}}
    payload = {"chart": {"result": [row] if outcome == "success" else []}}
    body = b"not-json secret-payload" if outcome == "bad_json" else json.dumps(payload).encode()
    effect = None
    if outcome == "timeout":
        effect = urllib.error.URLError(TimeoutError("secret-payload timed out"))
    elif outcome == "http_429":
        effect = urllib.error.HTTPError("https://example.invalid/secret-payload", 429, "Too Many Requests", {}, None)
    request = Mock(side_effect=effect, return_value=Response(body))
    monkeypatch.setattr(prices.urllib.request, "urlopen", request)
    with PerformanceTrace() as trace:
        if kind == "chart":
            actual = prices._fetch_yahoo_chart("TEST", "1m", "1d")
            expected = (145.25, row["meta"]) if outcome == "success" else (-1., {}) if outcome == "http_429" else (0., {})
        elif kind == "overnight":
            actual = prices._fetch_yahoo_overnight_page_price("TEST")
            expected = 145.25 if outcome == "success" else 0.
        else:
            actual = prices._fetch_yahoo_regular_close_price("TEST")
            expected = 145.25 if outcome == "success" else 0.
    assert actual == expected
    report = trace.report()
    events = report["transport_events"]
    provider = "yahoo_" + kind
    attempts = 1 if kind == "overnight" or outcome == "success" or (kind == "chart" and outcome == "http_429") else 2
    assert request.call_count == attempts
    assert events[provider + ".request"] == attempts
    assert events.get(provider + ".response", 0) == (0 if effect else attempts)
    error = outcome in {"timeout", "http_429"} or (outcome == "bad_json" and kind != "overnight")
    assert events.get(provider + (".timeout" if outcome == "timeout" else ".error"), 0) == (attempts if error else 0)
    assert events.get(provider + ".http_429", 0) == (attempts if outcome == "http_429" else 0)
    serialized = json.dumps(report)
    assert "secret-payload" not in serialized
    assert "https://" not in serialized
    prices._fetch_yahoo_regular_close_price.clear()


def test_close_cache_hit_does_not_claim_another_http_request(monkeypatch):
    prices._fetch_yahoo_regular_close_price.clear()
    payload = {"chart": {"result": [{"indicators": {"quote": [{"close": [123.45]}]}}]}}
    request = Mock(return_value=Response(json.dumps(payload).encode()))
    monkeypatch.setattr(prices.urllib.request, "urlopen", request)
    try:
        with PerformanceTrace() as trace:
            assert prices._fetch_yahoo_regular_close_price("TEST") == 123.45
            assert prices._fetch_yahoo_regular_close_price("TEST") == 123.45
        assert request.call_count == 1
        report = trace.report()
        assert report["transport_events"] == {"yahoo_regular_close.request": 1, "yahoo_regular_close.response": 1}
        row = next(r for r in report["functions"] if r["name"] == "_fetch_yahoo_regular_close_price")
        assert row["calls"] == 2
    finally:
        prices._fetch_yahoo_regular_close_price.clear()


@pytest.mark.parametrize("forced", [False, True])
def test_watch_wrapper_keeps_original_cache_and_forced_refresh_thread(monkeypatch, forced):
    source = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "build_leveraged_precision_watch_rows")
    assert ast.unparse(node.decorator_list[0]) == "st.cache_data(ttl=300, show_spinner=False)"
    node.decorator_list = []
    watch = [("SPY", "role", "label")]
    helper, quote, history, pct, judge = (Mock() for _ in range(5))
    env = dict(LEVERAGED_ETF_PRECISION_PROFILES={"fixture": {"watch": watch}},
               build_leveraged_watch_rows=helper, load_display_live_price=quote,
               load_price_df=history, _leveraged_precision_pct_text=pct,
               _leveraged_precision_proxy_judgement=judge)
    monkeypatch.setattr(prices, "_force_live_price_refresh_active", lambda: forced)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "app.py"), "exec"), env)
    assert env[node.name]("fixture") is helper.return_value
    helper.assert_called_once_with(watch, load_quote=quote, load_history=history,
                                   pct_text=pct, judge=judge, parallel=not forced)


@pytest.mark.parametrize("stale", [False, True])
def test_watch_source_metadata_keeps_real_import_hash_with_old_name_list(monkeypatch, stale):
    from stock_lab_core import leveraged_watch, precision_build, report_build

    name = leveraged_watch.__name__
    captured = deepcopy(report_build._LOADED[name])
    if stale:
        captured["sha256"] = "old-import-hash"
    monkeypatch.setattr(report_build, "_LOADED", {name: captured})
    monkeypatch.setattr(report_build, "get_report_build_info", lambda *args: {"sources": {}, "stale_modules": []})
    monkeypatch.setattr(precision_build, "MODULES", ())
    node = next(n for n in ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig")).body
                if isinstance(n, ast.FunctionDef) and n.name == "get_precision_build_info")
    warnings = []
    env = {"__file__": str(ROOT / "app.py"), "st": SimpleNamespace(warning=warnings.append)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "app.py"), "exec"), env)
    result = env[node.name]()
    assert result["sources"][name]["sha256"] == captured["sha256"]
    assert result["restart_required"] == stale
    assert bool(warnings) == stale


def test_real_watch_cache_hits_do_not_repeat_work_and_clear_keeps_force_policy(monkeypatch):
    import streamlit as st

    node = next(n for n in ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig")).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_leveraged_precision_watch_rows")
    forced = [False]
    monkeypatch.setattr(prices, "_force_live_price_refresh_active", lambda: forced[0])
    helper = Mock(return_value=[{"Ticker": "SPY", "_1d": 1.0}])
    env = dict(st=st, LEVERAGED_ETF_PRECISION_PROFILES={"fixture": {"watch": []}},
               build_leveraged_watch_rows=helper, load_display_live_price=Mock(), load_price_df=Mock(),
               _leveraged_precision_pct_text=Mock(), _leveraged_precision_proxy_judgement=Mock())
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "app.py"), "exec"), env)
    cached = env[node.name]
    cached.clear()
    try:
        cached("fixture")[0]["Ticker"] = "CALLER-EDIT"
        forced[0] = True
        assert cached("fixture") == [{"Ticker": "SPY", "_1d": 1.0}]
        assert helper.call_count == 1
        assert helper.call_args.kwargs["parallel"] is True
        cached.clear()
        cached("fixture")
        assert helper.call_count == 2
        assert helper.call_args.kwargs["parallel"] is False
    finally:
        cached.clear()
