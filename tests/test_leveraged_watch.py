"""Offline proxy-row parity against the cached function at a fixed revision."""

import ast
from concurrent.futures import ThreadPoolExecutor as RealExecutor
from contextvars import ContextVar
from copy import deepcopy
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import struct
import subprocess
from threading import Event, Lock, current_thread

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import leveraged_watch as module
from stock_lab_core import report_build
from stock_lab_core.formatters import clean_float, finite_num, format_currency, sanitize_ticker_value
from stock_lab_core.performance import PerformanceTrace


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "5a859433"
BASELINE_FUNCTION = "build_leveraged_precision_watch_rows"
WAIT = 10


@lru_cache(maxsize=1)
def baseline_code():
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:app.py"], cwd=ROOT, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    names = {BASELINE_FUNCTION, "_leveraged_precision_pct_text",
             "_leveraged_precision_proxy_judgement"}
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    for node in nodes:
        node.decorator_list = []
    return compile(ast.Module(body=nodes, type_ignores=[]), f"{BASELINE}:app.py", "exec")


def baseline_scope():
    scope = dict(np=np, pd=pd, clean_float=clean_float, finite_num=finite_num,
                 format_currency=format_currency, sanitize_ticker_value=sanitize_ticker_value)
    exec(baseline_code(), scope)
    return scope


def baseline_rows(watch, *, load_quote, load_history, pct_text, judge):
    scope = baseline_scope()
    scope.update(
        LEVERAGED_ETF_PRECISION_PROFILES={"test": {"watch": watch}},
        load_display_live_price=load_quote, load_price_df=load_history,
        _leveraged_precision_pct_text=pct_text, _leveraged_precision_proxy_judgement=judge,
    )
    return scope[BASELINE_FUNCTION]("test")


def assert_exact_rows(actual, expected):
    assert type(actual) is type(expected) is list
    assert len(actual) == len(expected)
    for result, baseline in zip(actual, expected):
        assert type(result) is type(baseline) is dict
        assert list(result) == list(baseline)
        for key, value in baseline.items():
            assert type(result[key]) is type(value), key
            if isinstance(value, float):
                if math.isnan(value):
                    assert math.isnan(result[key]), key
                else:
                    assert struct.pack("!d", result[key]) == struct.pack("!d", value), key
            else:
                assert result[key] == value, key


@pytest.fixture
def callbacks():
    scope = baseline_scope()
    return dict(pct_text=scope["_leveraged_precision_pct_text"],
                judge=scope["_leveraged_precision_proxy_judgement"])


# These tests have no provider caches and must not load the app's dependencies.
@pytest.fixture(autouse=True)
def isolate_yahoo_metadata_cache():
    yield


@pytest.fixture(autouse=True)
def isolate_public_economic_disk_cache():
    yield


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("length", [0, 1, 2, 5, 6, 21, 22, 23])
@pytest.mark.parametrize("quote", [0.0, None, 150.0])
def test_full_baseline_parity_at_return_window_boundaries(callbacks, parallel, length, quote):
    watch = [(" a a p l ", "role", "US"), ("005930.ks", "role", "KR")]
    frame = pd.DataFrame({"Close": np.arange(length, dtype=float) + 100})
    providers = dict(load_quote=lambda ticker: quote, load_history=lambda ticker, period: frame)
    expected = baseline_rows(watch, **providers, **callbacks)
    actual = module.build_leveraged_watch_rows(watch, **providers, **callbacks, parallel=parallel)
    assert_exact_rows(actual, expected)
    if length < 2:
        assert all(math.isnan(actual[0][key]) for key in ("_1d", "_1w", "_1m"))


@pytest.mark.parametrize("quote", ["", "bad", float("nan"), float("inf"), -10, "1,234.567", 0.00000001])
@pytest.mark.parametrize("parallel", [False, True])
def test_quote_cleaning_currency_and_input_values_match_baseline(callbacks, quote, parallel):
    watch = [("SEARCH: a a p l", None, 7), ("005930.ks", "", None),
             (None, "blank", ""), (123456, "numeric", "label")]
    providers = dict(load_quote=lambda ticker: quote,
                     load_history=lambda ticker, period: pd.DataFrame({"Close": [10, 20]}))
    actual = module.build_leveraged_watch_rows(watch, **providers, **callbacks, parallel=parallel)
    assert_exact_rows(actual, baseline_rows(watch, **providers, **callbacks))
    price = clean_float(quote, 0.0)
    assert [row["Ticker"] for row in actual] == ["AAPL", "005930.KS", "", "123456"]
    assert [row["현재가"] for row in actual] == [
        format_currency(price, row["Ticker"]) if price > 0 else "-" for row in actual
    ]


@pytest.mark.parametrize("history", [
    None, pd.DataFrame(), pd.DataFrame({"Other": [1, 2]}),
    pd.DataFrame({"Close": ["bad", None, "100", "110", np.nan]}),
    pd.DataFrame({"Close": [None, "bad"]}),
    pd.DataFrame({"Close": [0, -2, 100]}),
    pd.DataFrame({"Close": [np.inf, 100, -np.inf]}),
    pd.DataFrame([[1, 2], [3, 4]], columns=["Close", "Close"]),
])
@pytest.mark.parametrize("parallel", [False, True])
def test_history_shapes_nan_and_invalid_bases_match_baseline(callbacks, history, parallel):
    watch = [("A", "role", "label"), ("B", "role", "label")]
    providers = dict(load_quote=lambda ticker: 0, load_history=lambda ticker, period: history)
    assert_exact_rows(
        module.build_leveraged_watch_rows(watch, **providers, **callbacks, parallel=parallel),
        baseline_rows(watch, **providers, **callbacks),
    )


@pytest.mark.parametrize("parallel", [False, True])
def test_history_error_is_swallowed_after_quote_and_original_formatters_are_called(callbacks, parallel):
    watch = [("A", "role", "label"), ("B", "role", "label")]

    def run(builder, **kwargs):
        calls = {"A": [], "B": []}
        local = ContextVar("row_ticker")

        def quote(ticker):
            local.set(ticker)
            calls[ticker].append("quote")
            return 125.5

        def history(ticker, period):
            calls[ticker].append(("history", period))
            raise RuntimeError("synthetic history failure")

        def pct_text(value):
            calls[local.get()].append(("pct_text", math.isnan(value)))
            return callbacks["pct_text"](value)

        def judge(*values):
            calls[local.get()].append(("judge", tuple(math.isnan(value) for value in values)))
            return callbacks["judge"](*values)

        rows = builder(watch, load_quote=quote, load_history=history,
                       pct_text=pct_text, judge=judge, **kwargs)
        return rows, calls

    expected, expected_calls = run(baseline_rows)
    actual, calls = run(module.build_leveraged_watch_rows, parallel=parallel)
    assert_exact_rows(actual, expected)
    assert calls == expected_calls
    assert all(events == ["quote", ("history", "6mo"), ("pct_text", True),
                          ("pct_text", True), ("pct_text", True), ("judge", (True, True, True))]
               for events in calls.values())


def test_inputs_frames_duplicates_and_generator_order_are_preserved(callbacks):
    watch = [[" b ", "role", "first"], ["A", None, "second"], [" b ", "other", "third"]]
    frames = {ticker: pd.DataFrame({"Close": [100.0, np.nan, 110.0, 120.0]}) for ticker in ("A", "B")}
    for frame in frames.values():
        frame.attrs = {"source": "synthetic", "nested": {"values": [1, 2]}}
    saved_watch, saved_frames = deepcopy(watch), deepcopy(frames)
    providers = dict(load_quote=lambda ticker: 130, load_history=lambda ticker, period: frames[ticker])
    actual = module.build_leveraged_watch_rows(iter(watch), **providers, **callbacks)
    assert_exact_rows(actual, baseline_rows(watch, **providers, **callbacks))
    assert watch == saved_watch
    assert [row["Ticker"] for row in actual] == ["B", "A", "B"]
    for ticker in frames:
        pd.testing.assert_frame_equal(frames[ticker], saved_frames[ticker], check_exact=True)
        assert frames[ticker].attrs == saved_frames[ticker].attrs


@pytest.mark.parametrize("watch,parallel", [([], True), ([], False),
    ([("A", "role", "label")], True), ([("A", "role", "label")], False),
    ([("A", "role", "label"), ("B", "role", "label")], False)])
def test_empty_single_and_serial_use_caller_without_pool_or_permits(monkeypatch, callbacks, watch, parallel):
    caller = current_thread().ident
    seen = []

    def forbidden(*args, **kwargs):
        raise AssertionError("caller path must bypass the pool and global permits")

    class NoSlots:
        __enter__ = forbidden

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(module, "ThreadPoolExecutor", forbidden)
    monkeypatch.setattr(module, "_PARALLEL_ROW_SLOTS", NoSlots())

    def quote(ticker):
        seen.append(current_thread().ident)
        return 120

    def history(ticker, period):
        seen.append(current_thread().ident)
        return pd.DataFrame({"Close": [100, 110]})

    actual = module.build_leveraged_watch_rows(iter(watch), load_quote=quote, load_history=history,
                                              **callbacks, parallel=parallel)
    assert len(actual) == len(watch)
    assert seen == [caller] * (2 * len(watch))


def test_two_rows_overlap_but_results_follow_input_order(monkeypatch, callbacks):
    first_quote, second_done = Event(), Event()
    pool_sizes = []
    watch = [("FIRST", "role", "first"), ("SECOND", "role", "second")]

    class RecordingPool(RealExecutor):
        def __init__(self, *args, **kwargs):
            pool_sizes.append(kwargs.get("max_workers", args[0] if args else None))
            self.submitted = 0
            super().__init__(*args, **kwargs)

        def submit(self, *args, **kwargs):
            future = super().submit(*args, **kwargs)
            self.submitted += 1
            if self.submitted == 2:
                future.add_done_callback(lambda done: second_done.set())
            return future

    monkeypatch.setattr(module, "ThreadPoolExecutor", RecordingPool)

    def quote(ticker):
        if ticker == "FIRST":
            first_quote.set()
            assert second_done.wait(WAIT), "second row must finish before first quote returns"
        else:
            assert first_quote.wait(WAIT)
        return 120

    def history(ticker, period):
        assert period == "6mo"
        return pd.DataFrame({"Close": [100, 110]})

    actual = module.build_leveraged_watch_rows(watch, load_quote=quote, load_history=history, **callbacks)
    assert [row["Ticker"] for row in actual] == ["FIRST", "SECOND"]
    assert pool_sizes == [2]


def test_simultaneous_profiles_share_two_slots_for_entire_rows(monkeypatch, callbacks):
    slots = module._PARALLEL_ROW_SLOTS
    attempted_all, two_judges, release_rows = Event(), Event(), Event()
    lock = Lock()
    attempts = active = peak = judges = 0
    started = []

    class ObservedSlots:
        def __enter__(self):
            nonlocal attempts
            with lock:
                attempts += 1
                if attempts == 4:
                    attempted_all.set()
            slots.acquire()
            return self

        def __exit__(self, *args):
            slots.release()

    monkeypatch.setattr(module, "_PARALLEL_ROW_SLOTS", ObservedSlots())

    def quote(ticker):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            started.append(ticker)
        return 120

    def history(ticker, period):
        return pd.DataFrame({"Close": [100, 110]})

    def judge(*values):
        nonlocal active, judges
        with lock:
            judges += 1
            if judges == 2:
                two_judges.set()
        try:
            assert release_rows.wait(WAIT)
            return callbacks["judge"](*values)
        finally:
            with lock:
                active -= 1

    with RealExecutor(max_workers=2) as profiles:
        futures = [profiles.submit(
            module.build_leveraged_watch_rows,
            [(f"P{index}A", "role", "label"), (f"P{index}B", "role", "label")],
            load_quote=quote, load_history=history, pct_text=callbacks["pct_text"], judge=judge,
        ) for index in range(2)]
        try:
            assert attempted_all.wait(WAIT), "both profile pools must reach the shared semaphore"
            assert two_judges.wait(WAIT)
            with lock:
                assert len(started) == active == peak == 2
        finally:
            release_rows.set()
        assert [len(future.result(timeout=WAIT)) for future in futures] == [2, 2]
    assert active == 0 and peak == 2 and len(started) == 4


def test_context_propagates_per_row_and_timings_have_no_phase_status(callbacks):
    context = ContextVar("leveraged_watch_test_context", default="missing")
    token = context.set("profile")
    caller = current_thread().ident
    watch = [(f"T{index}", "role", "label") for index in range(4)]
    phases = []

    def quote(ticker):
        assert current_thread().ident != caller
        assert context.get() == "profile"
        context.set(ticker)
        return 120

    def history(ticker, period):
        assert context.get() == ticker
        assert period == "6mo"
        return pd.DataFrame({"Close": [100, 110]})

    try:
        with PerformanceTrace(on_phase=lambda *args: phases.append(args)) as trace:
            rows = module.build_leveraged_watch_rows(watch, load_quote=quote, load_history=history, **callbacks)
        assert context.get() == "profile"
    finally:
        context.reset(token)
    assert len(rows) == 4 and phases == []
    entries = {row["name"]: row for row in trace.report()["functions"]}
    assert set(entries) == {"build_leveraged_watch_rows", "_build_watch_row",
                            "leveraged_watch_quote", "leveraged_watch_history_6mo"}
    assert entries["build_leveraged_watch_rows"]["calls"] == 1
    assert entries["_build_watch_row"]["calls"] == 4
    assert all(row["errors"] == 0 for row in entries.values())
    assert entries["leveraged_watch_quote"]["category"] == "prices"
    assert entries["leveraged_watch_history_6mo"]["calls"] == 4


class RowAbort(BaseException):
    pass


@pytest.mark.parametrize("stage", ["quote", "pct_text", "judge", "control_flow"])
def test_callback_exceptions_propagate_and_all_permits_are_released(callbacks, stage):
    failure = RowAbort("synthetic abort") if stage == "control_flow" else RuntimeError("synthetic row error")
    watch = [("A", "role", "label"), ("B", "role", "label")]

    def fail(*args):
        raise failure

    providers = dict(load_quote=lambda ticker: 120,
                     load_history=lambda ticker, period: pd.DataFrame({"Close": [100, 110]}),
                     **callbacks)
    broken = dict(providers)
    broken["load_quote" if stage in {"quote", "control_flow"} else stage] = fail
    with pytest.raises(type(failure)) as caught:
        module.build_leveraged_watch_rows(watch, **broken)
    assert caught.value is failure
    acquired = 0
    try:
        for _ in range(2):
            assert module._PARALLEL_ROW_SLOTS.acquire(blocking=False)
            acquired += 1
        assert not module._PARALLEL_ROW_SLOTS.acquire(blocking=False)
    finally:
        for _ in range(acquired):
            module._PARALLEL_ROW_SLOTS.release()
    assert_exact_rows(module.build_leveraged_watch_rows(watch, **providers), baseline_rows(watch, **providers))


@pytest.mark.parametrize("watch", [None, 1, [("A",)], [("A", "role", "label", "extra")], [None]])
@pytest.mark.parametrize("parallel", [False, True])
def test_invalid_watch_errors_match_baseline(callbacks, watch, parallel):
    providers = dict(load_quote=lambda ticker: 120, load_history=lambda ticker, period: None, **callbacks)
    with pytest.raises((TypeError, ValueError)) as baseline:
        baseline_rows(watch, **providers)
    with pytest.raises(type(baseline.value)) as actual:
        module.build_leveraged_watch_rows(watch, **providers, parallel=parallel)
    assert str(actual.value) == str(baseline.value)


def test_serial_stops_before_later_rows_after_quote_error(callbacks):
    calls = []
    failure = RuntimeError("synthetic quote error")

    def quote(ticker):
        calls.append(ticker)
        raise failure

    with pytest.raises(RuntimeError) as caught:
        module.build_leveraged_watch_rows(
            [("A", "role", "label"), ("B", "role", "label")], load_quote=quote,
            load_history=lambda ticker, period: None, **callbacks, parallel=False,
        )
    assert caught.value is failure and calls == ["A"]


def test_loaded_source_is_registered_at_import():
    source = Path(module.__file__).resolve()
    assert report_build._LOADED[module.__name__] == {
        "path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
