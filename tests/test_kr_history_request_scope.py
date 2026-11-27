"""Exact-request replay against immutable pre-change code; no live prices."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import ast
from pathlib import Path
import subprocess
from threading import Lock
from time import perf_counter, sleep
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest
import requests

from stock_lab_core import kr_flow_history as history
from stock_lab_core.performance import PerformanceTrace, submit_with_context


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_COMMIT = "24244c3e"
XML = '<protocol>' + ''.join(
    f'<item data="{day:%Y%m%d}|100|120|90|{100 + i % 19}|{1000+i}"/>'
    for i, day in enumerate(pd.bdate_range("2024-01-01", "2026-11-06"))
) + '</protocol>'
REQUESTS = (
    ("005930.KS", None), ("005930", "2025-11-07"),
    ("005930.ks", "2025-11-07T12:00:00+09:00"),
    ("005930", "2026-08-07"), ("005930.KS", "2016-11-07"),
    # UTC-local period start at KST 04:00 is a different range: do not merge.
    ("005930", "2025-11-06"), ("0167a0.KS", None), ("0167A0", "2025-11-07"),
)


def old_module():
    source = subprocess.check_output(
        ["git", "show", f"{REFERENCE_COMMIT}:stock_lab_core/kr_flow_history.py"],
        cwd=ROOT, encoding="utf-8")
    module = ModuleType("kr_history_immutable_reference")
    exec(compile(source, "<kr_history_immutable_reference>", "exec"), module.__dict__)
    return module


class Transport:
    def __init__(self, delay=0):
        self.calls, self.delay, self.lock = [], delay, Lock()

    def __call__(self, url, **kwargs):
        with self.lock:
            self.calls.append((url, kwargs))
        sleep(self.delay)
        return SimpleNamespace(text=XML, raise_for_status=lambda: None, close=lambda: None)


def replay(module, delay=0):
    transport = Transport(delay)
    reader = module.KrFlowHistoryReader(request=transport)
    started = perf_counter()
    scope = module.reuse_kr_history_requests() if hasattr(module, "reuse_kr_history_requests") else nullcontext()
    with PerformanceTrace() as trace, scope:
        rows = [reader.read(ticker, now="2026-11-07", start=start) for ticker, start in REQUESTS]
    return rows, transport.calls, perf_counter()-started, trace.report()


def test_exact_response_parity_and_proven_duplicate_requests():
    before, old_calls, _, _ = replay(old_module())
    after, new_calls, _, report = replay(history)
    # 2026-11-26: shorter windows of the same code/end are sliced from a wider fetched window
    # (1-year minimum), so 8 old requests become 3; every returned frame stays identical.
    assert len(old_calls) == 8 and len(new_calls) == 3
    assert all(call in old_calls for call in new_calls)
    for expected, actual in zip(before, after):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
    assert report["transport_events"]["kr_history_scope.reuse"] == 5
    assert history._request_scope.get() is None


def test_concurrent_identical_requests_single_flight_and_copy_isolation():
    transport = Transport(.025)
    reader = history.KrFlowHistoryReader(request=transport)
    with PerformanceTrace() as trace, history.reuse_kr_history_requests():
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [submit_with_context(pool, reader.read, ticker, now="2026-11-07")
                       for ticker in ("005930", "005930.KS", "005930.ks") * 3]
            rows = [f.result(timeout=5) for f in futures]
        original = rows[1].copy(deep=True)
        rows[0].iloc[0, 0] = -1
        rows[0].attrs["source"] = "mutated"
        with history.reuse_kr_history_requests():
            again = reader.read("005930", now="2026-11-07")
        pd.testing.assert_frame_equal(again, original, check_exact=True)
        assert again.attrs == original.attrs
    assert len(transport.calls) == 1
    assert trace.report()["transport_events"]["kr_history_scope.reuse"] == 9
    reader.read("005930", now="2026-11-07")
    assert len(transport.calls) == 2


def test_failure_not_memoized_and_cooldown_unchanged():
    clock, calls = [0.0], []

    def unavailable(*args, **kwargs):
        calls.append(kwargs)
        raise requests.ReadTimeout()

    reader = history.KrFlowHistoryReader(request=unavailable, clock=lambda: clock[0])
    with history.reuse_kr_history_requests():
        for _ in range(7):
            assert reader.read("005930", now="2026-11-07").empty
        assert len(calls) == 3
        clock[0] = 61
        assert reader.read("005930", now="2026-11-07").empty
        assert len(calls) == 4


def test_expiry_clear_boundary_and_reader_identity():
    clock = [0.0]
    transport = Transport()
    reader = history.KrFlowHistoryReader(request=transport, clock=lambda: clock[0])
    other = history.KrFlowHistoryReader(request=transport, clock=lambda: clock[0])
    with history.reuse_kr_history_requests():
        reader.read("005930", now="2026-11-07")
        clock[0] = 899
        reader.read("005930.KS", now="2026-11-07")
        assert len(transport.calls) == 1
        clock[0] = 900
        reader.read("005930.KS", now="2026-11-07")
        history.load_kr_flow_history.clear()
        reader.read("005930", now="2026-11-07")
        reader.read("005930", now="2026-11-08")
        other.read("005930", now="2026-11-08")
        assert len(transport.calls) == 5


def test_cached_alias_does_not_extend_snapshot_ttl(monkeypatch):
    transport = Transport()
    reader = history.KrFlowHistoryReader(request=transport)
    monkeypatch.setattr(history, "_reader", SimpleNamespace(read=lambda ticker, start=None:
        reader.read(ticker, start=start, now="2026-11-07")))
    history.load_kr_flow_history.clear()
    try:
        with PerformanceTrace() as trace, history.reuse_kr_history_requests():
            history.load_kr_flow_history("005930.KS")
            history.load_kr_flow_history("005930", start="2025-11-07")
        assert len(transport.calls) == 1
        assert trace.report()["transport_events"]["cache.kr_history.bypass"] == 1
        # Alias must fetch anew in another run: no new persistent cache lifetime.
        with history.reuse_kr_history_requests():
            history.load_kr_flow_history("005930", start="2025-11-07")
        assert len(transport.calls) == 2
    finally:
        history.load_kr_flow_history.clear()


def test_all_app_functions_except_scope_wrapper_unchanged():
    before = subprocess.check_output(["git", "show", f"{REFERENCE_COMMIT}:app.py"],
                                     cwd=ROOT, encoding="utf-8")
    approved = subprocess.check_output(["git", "show", "661431f9:app.py"], cwd=ROOT, encoding="utf-8")
    after = (ROOT / "app.py").read_text(encoding="utf-8")
    def wrapper(tree):
        matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_today_queue_tab"]
        assert len(matches) == 1
        return matches[0]
    original, historical, current = map(ast.parse, (before, approved, after))
    extracted = wrapper(historical)
    assert ast.dump(wrapper(current)) == ast.dump(extracted)
    # Only this wrapper belongs to the request-scope change. The full historical
    # module (including every other function and top-level statement) is frozen.
    historical.body[historical.body.index(extracted)] = wrapper(original)
    assert ast.dump(original) == ast.dump(historical)


def test_diagnostics_separate_wait_headers_body_parse_and_hide_keys(monkeypatch):
    clock = [0.0]
    def advance(seconds):
        clock[0] += seconds
    def request(*args, **kwargs):
        advance(2)
        return SimpleNamespace(raise_for_status=lambda: None, close=lambda: None)
    def body(*args):
        advance(3)
        return XML
    original_parse = history.parse_history
    def parse(*args):
        advance(4)
        return original_parse(*args)
    monkeypatch.setattr(history, '_read_body', body)
    monkeypatch.setattr(history, 'parse_history', parse)
    reader = history.KrFlowHistoryReader(request=request)
    with PerformanceTrace(clock=lambda: clock[0]) as trace, history.reuse_kr_history_requests():
        first = reader.read('005930', now='2026-11-07')
        with history.reuse_kr_history_requests():
            second = reader.read('005930.KS', now='2026-11-07')
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    report = trace.report()
    rows = {r['name']: r for r in report['functions']}
    assert rows['kr_history_headers']['total_seconds'] == 2
    assert rows['kr_history_body']['total_seconds'] == 3
    assert rows['kr_history_http']['total_seconds'] == 5
    assert rows['kr_history_parse']['total_seconds'] == 4
    assert rows['kr_history_lock_wait']['total_seconds'] == 0
    assert report['transport_events']['kr_history.request_unique'] == 1
    assert report['transport_events']['kr_history_scope.reuse'] == 1
    assert '005930' not in str(report)
    assert history._request_audit.get() is None


def test_diagnostics_count_retries_and_unscoped_calls_without_deduplicating():
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.ReadTimeout()
        return SimpleNamespace(text=XML, raise_for_status=lambda: None, close=lambda: None)
    reader = history.KrFlowHistoryReader(request=request)
    with PerformanceTrace() as trace:
        with history.reuse_kr_history_requests():
            assert reader.read('005930', now='2026-11-07').empty
            assert not reader.read('005930', now='2026-11-07').empty
        reader.read('005930', now='2026-11-07')
    events = trace.report()['transport_events']
    assert len(calls) == events['kr_history.request'] == 3
    assert events['kr_history.request_repeat'] == 1
    assert events['kr_history.request_unique'] == 1
    assert events['kr_history.request_unscoped'] == 1
