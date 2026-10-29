"""Offline preload equivalence, connection lifetime, and bounded benchmark."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean
from threading import Barrier, Lock, get_ident
from time import perf_counter, sleep
from types import SimpleNamespace
import json

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from stock_lab_core import kr_flow_history as history, prices
from stock_lab_core.formatters import sanitize_ticker_value
from stock_lab_core.performance import PerformanceTrace, submit_with_context, timed_call


TICKERS = tuple(f"{i:06d}.KS" for i in range(1, 25))


def legacy_preload(tickers, period="1y", max_workers=8, *, load_batch=None, load_one=None):
    """The app's pre-change preload, without importing its authenticated UI."""
    load_batch = prices.load_price_frames_batch if load_batch is None else load_batch
    load_one = prices.load_price_df if load_one is None else load_one
    if not tickers:
        return {}
    unique = list(dict.fromkeys(sanitize_ticker_value(t) for t in tickers if sanitize_ticker_value(t)))
    try:
        frames = dict(load_batch(tuple(sorted(unique)), period))
    except Exception:
        frames = {}

    def fetch(ticker):
        try:
            return load_one(ticker, period)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {submit_with_context(executor, fetch, ticker): ticker for ticker in unique if ticker not in frames}
        for future in as_completed(futures):
            frames[futures[future]] = future.result()
    return frames


class Transport:
    def __init__(self, connect_delay=0, request_delay=0):
        self.connect_delay, self.request_delay = connect_delay, request_delay
        self.sessions, self.calls, self.responses = [], [], []
        self.lock = Lock()
        self.barrier = None

    def session(self):
        transport = self

        class Session:
            def __init__(self):
                self.owner, self.closed, self.count, self.active = get_ident(), False, 0, False
                self.cookies = requests.cookies.RequestsCookieJar()
                with transport.lock:
                    transport.sessions.append(self)

            def get(self, url, **kwargs):
                assert get_ident() == self.owner and not self.closed and not self.active
                assert not self.cookies
                self.active = True
                try:
                    if self.count == 0:
                        if transport.barrier is not None:
                            transport.barrier.wait(timeout=5)
                        sleep(transport.connect_delay)
                    self.count += 1
                    sleep(transport.request_delay)
                    self.cookies.set("discard", "between_requests")
                    value = int(kwargs["params"]["symbol"]) + 100
                    xml = f'<protocol><item data="20261028|{value}|{value+2}|{value-2}|{value+1}|1000"/></protocol>'
                    response = SimpleNamespace(text=xml, raise_for_status=lambda: None, closed=False)
                    response.close = lambda: setattr(response, "closed", True)
                    with transport.lock:
                        transport.calls.append((url, kwargs))
                        transport.responses.append(response)
                    return response
                finally:
                    self.active = False

            def close(self):
                assert not self.active and not self.closed
                self.closed = True

        return Session()

    def get(self, *args, **kwargs):
        session = self.session()
        try:
            return session.get(*args, **kwargs)
        finally:
            session.close()


def clear_caches():
    for loader in (prices.load_price_df, prices._fetch_pykrx_ohlcv,
                   prices.load_price_frames_batch, history.load_kr_flow_history):
        loader.clear()


@pytest.fixture
def offline(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(history.requests, "get", transport.get)
    monkeypatch.setattr(history.requests, "Session", transport.session)
    reader = history.KrFlowHistoryReader()
    monkeypatch.setattr(history, "_reader", SimpleNamespace(
        read=lambda ticker, start=None: reader.read(ticker, now="2026-10-29", start=start)))
    monkeypatch.setattr(prices, "_period_start_timestamp", lambda period: pd.Timestamp(
        {"3mo": "2026-07-29", "1y": "2025-10-29", "10y": "2016-10-29"}[period]))

    def unexpected(*args, **kwargs):
        raise AssertionError("Unexpected Yahoo network path")

    monkeypatch.setattr(prices.yf, "download", unexpected)
    clear_caches()
    yield transport
    clear_caches()


def same_frames(actual, expected):
    assert set(actual) == set(expected)
    for ticker in actual:
        if expected[ticker] is None:
            assert actual[ticker] is None
        else:
            pd.testing.assert_frame_equal(actual[ticker], expected[ticker], check_exact=True)
            assert actual[ticker].attrs == expected[ticker].attrs


@pytest.mark.parametrize("period", ["3mo", "1y", "10y"])
def test_same_requests_periods_frames_worker_local_cleanup_and_warm_cache(offline, period):
    offline.barrier = Barrier(4)
    expected = legacy_preload(TICKERS[:8], period, 4)
    before = sorted(offline.calls, key=lambda call: call[1]["params"]["symbol"])
    assert len(before) == len(offline.sessions) == 8
    clear_caches()
    offline.calls.clear()
    actual = prices.prefetch_price_data_parallel(TICKERS[:8], period, 4)
    same_frames(actual, expected)
    assert sorted(offline.calls, key=lambda call: call[1]["params"]["symbol"]) == before
    assert len(offline.sessions) == 12  # Eight individual connections, then four worker sessions.
    assert all(session.closed for session in offline.sessions)
    assert all(response.closed for response in offline.responses)
    assert history._connections.get() is None
    same_frames(prices.prefetch_price_data_parallel(TICKERS[:8], period, 4), expected)
    assert len(offline.calls) == 8 and len(offline.sessions) == 12
    clear_caches()
    prices.prefetch_price_data_parallel(TICKERS[:8], period, 4)
    assert len(offline.sessions) == 16 and all(session.closed for session in offline.sessions)


def test_injected_app_loaders_keep_instrumentation_and_missing_fallbacks(offline):
    calls = []
    frame = pd.DataFrame({"Close": [123.0]})

    @timed_call("prices", "injected_batch")
    def batch(tickers, period):
        calls.append(("batch", tickers, period))
        return {"SPY": frame}

    @timed_call("prices", "injected_one")
    def one(ticker, period):
        calls.append(("one", ticker, period))
        if ticker == "ERROR":
            raise RuntimeError("fixture")
        return pd.DataFrame() if ticker == "EMPTY" else prices.load_price_df(ticker, period)

    with PerformanceTrace() as trace:
        actual = prices.prefetch_price_data_parallel(
            [" spy ", "SPY", "000001.KS", "EMPTY", "ERROR", ""], "3mo", 4,
            load_batch=batch, load_one=one)
    assert set(actual) == {"SPY", "000001.KS", "EMPTY", "ERROR"}
    assert actual["SPY"] is frame and actual["EMPTY"].empty and actual["ERROR"] is None
    assert not actual["000001.KS"].empty
    assert sorted(call[1] for call in calls if call[0] == "one") == ["000001.KS", "EMPTY", "ERROR"]
    functions = {row["name"]: row["calls"] for row in trace.report()["functions"]}
    assert functions["injected_batch"] == 1 and functions["injected_one"] == 3
    assert all(session.closed for session in offline.sessions)


def test_batch_failure_keeps_single_loader_and_empty_input(offline):
    def failed(*args):
        raise RuntimeError("batch unavailable")

    assert prices.prefetch_price_data_parallel([], load_batch=failed, load_one=failed) == {}
    actual = prices.prefetch_price_data_parallel(TICKERS[:4], load_batch=failed)
    assert set(actual) == set(TICKERS[:4]) and all(not frame.empty for frame in actual.values())
    assert all(session.closed for session in offline.sessions)


def test_kr_failure_preserves_existing_yahoo_fallback_and_session_cleanup(offline, monkeypatch):
    get = offline.session

    def failing_session():
        session = get()
        session.get = lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout("fixture"))
        return session

    fallback = []
    monkeypatch.setattr(history.requests, "Session", failing_session)
    monkeypatch.setattr(prices, "_fetch_yfinance_ohlcv", lambda ticker, period: (
        fallback.append((ticker, period)) or pd.DataFrame({"Close": [321.0]})))
    result = prices.prefetch_price_data_parallel(["000001.KS"], "10y")
    assert result["000001.KS"].iloc[0]["Close"] == 321
    assert fallback == [("000001.KS", "10y")]
    assert len(offline.sessions) == 1 and offline.sessions[0].closed
    assert history._connections.get() is None


def test_real_streamlit_cache_inside_apptest_completes_and_reuses(offline):
    app = AppTest.from_string('''
import streamlit as st
from stock_lab_core.prices import prefetch_price_data_parallel
@st.cache_data(show_spinner=False)
def collect():
    return prefetch_price_data_parallel(tuple(f"{i:06d}.KS" for i in range(1, 9)), max_workers=4)
st.session_state["frames"] = collect()
''').run(timeout=10)
    assert not app.exception
    assert len(app.session_state["frames"]) == 8
    assert all(not frame.empty for frame in app.session_state["frames"].values())
    calls = len(offline.calls)
    app.run(timeout=10)
    assert not app.exception and len(offline.calls) == calls == 8
    assert all(session.closed for session in offline.sessions)


def benchmark():
    rows = []
    with pytest.MonkeyPatch.context() as patch:
        generator = offline.__wrapped__(patch)
        transport = next(generator)
        transport.connect_delay, transport.request_delay = 0.030, 0.005
        try:
            for repeat in range(1, 4):
                result, outputs, requests_by_mode = {"repeat": repeat}, {}, {}
                for mode, loader in (("before", legacy_preload), ("after", prices.prefetch_price_data_parallel)):
                    clear_caches()
                    transport.sessions.clear()
                    transport.calls.clear()
                    transport.responses.clear()
                    transport.barrier = Barrier(4)
                    started = perf_counter()
                    outputs[mode] = loader(TICKERS, "1y", 4)
                    result[mode + "_ms"] = round((perf_counter() - started) * 1000, 3)
                    assert all(frame is not None and not frame.empty for frame in outputs[mode].values())
                    result[mode + "_requests"] = len(transport.calls)
                    result[mode + "_connections"] = len(transport.sessions)
                    requests_by_mode[mode] = sorted(transport.calls, key=lambda call: call[1]["params"]["symbol"])
                    assert all(session.closed for session in transport.sessions)
                    assert all(response.closed for response in transport.responses)
                same_frames(outputs["after"], outputs["before"])
                assert requests_by_mode["before"] == requests_by_mode["after"]
                result["equal"] = True
                rows.append(result)
        finally:
            next(generator, None)
    print(json.dumps({"synthetic": True, "tickers": len(TICKERS), "workers": 4,
                      "connect_ms": 30, "request_ms": 5, "runs": rows,
                      "before_mean_ms": mean(row["before_ms"] for row in rows),
                      "after_mean_ms": mean(row["after_ms"] for row in rows)}, indent=2))


if __name__ == "__main__":
    benchmark()
