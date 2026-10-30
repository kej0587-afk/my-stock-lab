"""Exact-request history reuse, independent of the app and live providers."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import Context
from functools import wraps
from threading import Barrier

import pandas as pd
import pytest

from stock_lab_core import prices, result_cache
from stock_lab_core.performance import submit_with_context


def history(value=100.0):
    frame = pd.DataFrame({"Open": [value - 1], "High": [value + 2], "Low": [value - 2],
                          "Close": [value], "Adj Close": [value * .99], "Volume": [12345]},
                         index=pd.DatetimeIndex(["2026-10-29"], name="Date"))
    frame.attrs = {"source": "fixture", "basis": {"session": "regular", "adjusted": False}}
    return frame


def loader(provider=None):
    calls, clears = [], []

    def underlying(ticker, period="1y"):
        calls.append((ticker, period))
        return history(float(len(calls))) if provider is None else provider(ticker, period)

    underlying.clear = lambda *a, **kw: clears.append((a, kw))
    return prices._reuse_prefetched_history(underlying), calls, clears


def test_reuses_only_within_scope_and_preserves_first_and_later_call_mutation_isolation():
    source = history()
    expected = source.copy(deep=True)
    load, calls, _ = loader(lambda *a: source.copy(deep=True))
    with prices.price_frame_scope({}, "1y"):
        first = load("TEST")
        first.iloc[0, 3] = 999
        first.attrs["basis"]["session"] = "changed"
        second = load(ticker="TEST", period="1y")
        pd.testing.assert_frame_equal(second, expected, check_exact=True)
        assert second.attrs == expected.attrs
        second.iloc[0, 0] = 777
        pd.testing.assert_frame_equal(load("TEST", "1y"), expected, check_exact=True)
        assert calls == [("TEST", "1y")]
    load("TEST")
    load("TEST")
    assert len(calls) == 3
    with prices.price_frame_scope({}, "1y"):
        load("TEST")
    assert len(calls) == 4
    assert prices._HISTORY_REQUEST_MEMO.get() is None


def test_exact_request_does_not_merge_period_market_or_spelling():
    requests = [("005930", "1y"), ("005930.KS", "1y"), ("005930.KQ", "1y"),
                ("TEST", "3mo"), ("TEST", "6mo"), ("TEST", "1y"), ("test", "1y"), (" TEST ", "1y")]
    load, calls, _ = loader()
    with prices.price_frame_scope({}, "3mo"):
        expected = [load(*request) for request in requests]
        for request, frame in zip(requests, expected):
            pd.testing.assert_frame_equal(load(*request), frame, check_exact=True)
    assert calls == requests


def test_prefetched_exact_period_keeps_precedence_and_nested_scope_restores_on_error():
    load, calls, _ = loader()
    with prices.price_frame_scope({"TEST": history(100)}, "3mo"):
        assert load(" test ", "3mo").Close.iloc[-1] == 100
        parent = load("TEST", "6mo")
        with pytest.raises(RuntimeError, match="scope exit"):
            with prices.price_frame_scope({"TEST": history(200)}, "6mo"):
                assert load("TEST", "6mo").Close.iloc[-1] == 200
                assert load("TEST", "3mo").Close.iloc[-1] == 100
                load("CHILD", "1y")
                raise RuntimeError("scope exit")
        pd.testing.assert_frame_equal(load("TEST", "6mo"), parent)
        load("CHILD", "1y")
    assert calls == [("TEST", "6mo"), ("CHILD", "1y"), ("CHILD", "1y")]
    assert prices._PREFETCHED_HISTORY.get() is None
    assert prices._HISTORY_REQUEST_MEMO.get() is None


def test_nested_scope_inherits_parent_memo_without_leaking_child_requests():
    load, calls, _ = loader()
    with prices.price_frame_scope({}, "1y"):
        expected = load("TEST")
        with prices.price_frame_scope({}, "3mo"):
            pd.testing.assert_frame_equal(load("TEST"), expected)
            load("CHILD")
        load("CHILD")
    assert calls == [("TEST", "1y"), ("CHILD", "1y"), ("CHILD", "1y")]


def test_empty_none_and_exceptions_are_not_retained():
    results = iter([pd.DataFrame(), None, RuntimeError("retry"), history(123)])

    def provider(*a):
        value = next(results)
        if isinstance(value, Exception):
            raise value
        return value

    load, calls, _ = loader(provider)
    with prices.price_frame_scope({}, "1y"):
        assert load("TEST").empty
        assert load("TEST") is None
        with pytest.raises(RuntimeError, match="retry"):
            load("TEST")
        assert load("TEST").Close.iloc[-1] == 123
        assert load("TEST").Close.iloc[-1] == 123
    assert len(calls) == 4


def test_failure_cooldown_can_expire_and_recover_inside_scope(monkeypatch):
    clock, calls = [0], []

    def fake_cache(*, ttl, **options):
        def decorate(fn):
            values = {}

            @wraps(fn)
            def cached(*args, **kwargs):
                key = (args, tuple(sorted(kwargs.items())))
                if key not in values or clock[0] - values[key][0] >= ttl:
                    values[key] = (clock[0], fn(*args, **kwargs))
                return values[key][1]

            cached.clear = lambda *a, **kw: values.clear()
            return cached
        return decorate

    monkeypatch.setattr(result_cache.st, "cache_data", fake_cache)

    @prices._reuse_prefetched_history
    @result_cache.cache_result(ttl=300, failure_ttl=15, is_success=lambda frame: not frame.empty)
    def load(ticker, period="1y"):
        calls.append(clock[0])
        return pd.DataFrame() if len(calls) == 1 else history(123)

    with prices.price_frame_scope({}, "1y"):
        assert load("TEST").empty
        clock[0] = 14
        assert load("TEST").empty
        assert calls == [0]
        clock[0] = 16
        assert load("TEST").Close.iloc[-1] == 123
        assert load("TEST").Close.iloc[-1] == 123
    assert calls == [0, 16]


@pytest.mark.parametrize("targeted", [False, True])
def test_clear_from_another_context_invalidates_active_and_nested_memos(targeted):
    load, calls, clears = loader()
    args = ("TEST", "1y") if targeted else ()
    with prices.price_frame_scope({}, "1y"):
        assert load("TEST").Close.iloc[-1] == 1
        with prices.price_frame_scope({}, "3mo"):
            assert load("TEST").Close.iloc[-1] == 1
            Context().run(load.clear, *args)
            assert load("TEST").Close.iloc[-1] == 2
        assert load("TEST").Close.iloc[-1] == 3
    assert clears == [(args, {})]
    assert len(calls) == 3


def test_clear_during_miss_does_not_retain_inflight_value():
    def provider(*a):
        if len(calls) == 1:
            load.clear()
        return history(float(len(calls)))

    load, calls, _ = loader(provider)
    with prices.price_frame_scope({}, "1y"):
        assert load("TEST").Close.iloc[-1] == 1
        assert load("TEST").Close.iloc[-1] == 2
        assert load("TEST").Close.iloc[-1] == 2
    assert len(calls) == 2


def test_existing_context_submission_shares_memo_with_workers():
    load, calls, _ = loader()
    with prices.price_frame_scope({}, "1y"), ThreadPoolExecutor(max_workers=2) as executor:
        first = submit_with_context(executor, load, "TEST").result(timeout=5)
        second = submit_with_context(executor, load, "TEST").result(timeout=5)
        pd.testing.assert_frame_equal(first, second)
        pd.testing.assert_frame_equal(load("TEST"), first)
    assert calls == [("TEST", "1y")]


def test_independent_runs_do_not_share_memos_or_serialize_provider_io():
    barrier = Barrier(2)

    def provider(*a):
        barrier.wait(timeout=5)
        return history()

    load, calls, _ = loader(provider)

    def run():
        with prices.price_frame_scope({}, "1y"):
            first = load("TEST")
            pd.testing.assert_frame_equal(load("TEST"), first)
            return first

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(run), executor.submit(run)
        pd.testing.assert_frame_equal(a.result(timeout=10), b.result(timeout=10))
    assert len(calls) == 2


def test_live_prices_are_not_snapshotted_by_history_scope(monkeypatch):
    values = iter([101.0, 102.0])
    monkeypatch.setattr(prices, "_load_latest_price_cached", lambda ticker: next(values))
    with prices.price_frame_scope({}, "1y"):
        assert prices.load_latest_price("TEST") == 101
        assert prices.load_latest_price("TEST") == 102


def test_real_cache_decorator_keeps_clear_unwrapped_and_domestic_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(prices, "_fetch_pykrx_ohlcv", lambda *a: pd.DataFrame())
    monkeypatch.setattr(prices, "_fetch_yfinance_ohlcv", lambda *a: calls.append(a) or history())
    prices.load_price_df.clear()
    try:
        with prices.price_frame_scope({}, "1y"):
            first = prices.load_price_df("005930.KS", "1y")
            pd.testing.assert_frame_equal(prices.load_price_df("005930.KS", "1y"), first)
            assert len(calls) == 1
            prices.load_price_df.__wrapped__("005930.KS", "1y")
            assert len(calls) == 2
            prices.load_price_df.clear("005930.KS", "1y")
            prices.load_price_df("005930.KS", "1y")
            assert len(calls) == 3
    finally:
        prices.load_price_df.clear()
