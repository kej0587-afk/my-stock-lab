"""Only independent provider waits overlap; scoring and UI stay on the caller."""

from concurrent.futures import ThreadPoolExecutor as RealExecutor
from threading import Event, Lock, current_thread

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core import money_flow as flow
from stock_lab_core.performance import PerformanceTrace


def history(rows=150):
    close = 100 + np.arange(rows) * 0.1
    return pd.DataFrame({"Close": close, "High": close + 1, "Low": close - 1,
                         "Volume": 1000 + np.arange(rows)},
                        index=pd.bdate_range("2026-01-02", periods=rows))


def test_kr_history_starts_before_overseas_download_and_scoring_stays_ordered(monkeypatch):
    started, download_done = Event(), Event()
    caller = current_thread().ident
    scores, fallbacks, requests = [], [], []
    frames = {ticker: history() for ticker in ("005930.KS", "000660.KS", "NVDA", "7203.T")}
    real_compute = flow._compute_ticker_metrics
    seen = []
    lock = Lock()

    def fetch(data, ticker):
        if flow._is_krx_money_flow_ticker(ticker):
            with lock:
                seen.append(ticker)
                if len(seen) == 2:
                    started.set()
            assert download_done.wait(3)
        else:
            assert download_done.is_set()
            fallbacks.append((ticker, current_thread().ident))
        return frames[ticker]

    def download(tickers):
        assert current_thread().ident == caller
        requests.append(tuple(tickers))
        try:
            assert started.wait(3), "KR histories must start before the overseas batch wait"
            return pd.DataFrame()
        finally:
            download_done.set()

    def compute(frame):
        scores.append(current_thread().ident)
        return real_compute(frame)

    monkeypatch.setattr(flow, "get_money_flow_ohlc", fetch)
    monkeypatch.setattr(flow, "download_money_flow_prices", download)
    monkeypatch.setattr(flow, "_compute_ticker_metrics", compute)
    tickers = ("NVDA", "005930.KS", "7203.T", "000660.KS", "005930.KS")
    with PerformanceTrace() as trace:
        result = flow._load_universe_metrics(None, [{"ticker": t} for t in tickers],
                                             download_tickers=tickers)
    assert list(result) == list(dict.fromkeys(tickers))
    assert requests == [tickers]
    assert sorted(seen) == ["000660.KS", "005930.KS"]
    assert scores == [caller] * 4
    assert fallbacks == [("NVDA", caller), ("7203.T", caller)]
    assert not any(row["errors"] for row in trace.report()["functions"])


@pytest.mark.parametrize("tickers", [[], ["NVDA"], ["005930.KS"], ["NVDA", "7203.T"]])
def test_small_or_overseas_only_universe_keeps_no_pool_path(monkeypatch, tickers):
    calls = []
    frame = history()

    def unexpected(*args, **kwargs):
        raise AssertionError("no new worker pool needed")

    monkeypatch.setattr(flow, "ThreadPoolExecutor", unexpected)
    monkeypatch.setattr(flow, "download_money_flow_prices", lambda values: calls.append(tuple(values)) or frame)
    def fetch(data, ticker):
        if not flow._is_krx_money_flow_ticker(ticker):
            assert data is frame
        return frame

    monkeypatch.setattr(flow, "get_money_flow_ohlc", fetch)
    result = flow._load_universe_metrics(None, [{"ticker": t} for t in tickers],
                                         download_tickers=tuple(tickers))
    assert list(result) == tickers
    assert calls == [tuple(tickers)]


def test_download_failure_joins_all_history_workers_and_releases_slots(monkeypatch):
    workers = []
    frames = {"005930.KS": history(), "000660.KS": history()}

    class RecordingPool(RealExecutor):
        def submit(self, *args, **kwargs):
            future = super().submit(*args, **kwargs)
            workers.append(future)
            return future

    def fail(tickers):
        raise RuntimeError("injected batch failure")

    monkeypatch.setattr(flow, "ThreadPoolExecutor", RecordingPool)
    monkeypatch.setattr(flow, "download_money_flow_prices", fail)
    monkeypatch.setattr(flow, "get_money_flow_ohlc", lambda data, ticker: frames[ticker])
    universe = [{"ticker": ticker} for ticker in frames]
    with pytest.raises(RuntimeError, match="batch failure"):
        flow._load_universe_metrics(None, universe, download_tickers=tuple(frames))
    assert len(workers) == 2 and all(future.done() for future in workers)
    monkeypatch.setattr(flow, "download_money_flow_prices", lambda _: pd.DataFrame())
    assert all(flow._load_universe_metrics(None, universe, download_tickers=tuple(frames)).values())


def test_overlapped_transport_failure_remains_in_result_metadata(monkeypatch):
    failed = pd.DataFrame()
    failed.attrs["transport_error"] = "ReadTimeout"
    monkeypatch.setattr(flow, "download_money_flow_prices", lambda _: pd.DataFrame())
    monkeypatch.setattr(flow, "get_money_flow_ohlc", lambda data, ticker: failed if ticker == "000660.KS" else history())
    universe = [{"ticker": ticker, "name": ticker, "구분": "KR", "섹터": "semiconductor"}
                for ticker in ("005930.KS", "000660.KS")]
    monkeypatch.setattr(flow, "build_money_flow_universe_with_naver_rankings", lambda: universe)
    result = flow.calculate_money_flow_df.__wrapped__()
    assert result.attrs["history_failures"] == ["000660.KS"]
    assert list(result["Ticker"]) == ["005930.KS"]


@pytest.mark.parametrize("kind", ["etf", "theme"])
def test_mixed_provider_cache_replay_has_no_worker_ui_or_extra_requests(monkeypatch, kind):
    tickers = ("005930.KS", "000660.KS", "NVDA")
    universe = [{"ticker": t, "name": t, "구분": "KR", "섹터": "test",
                 "테마": "test", "하위테마": "test"} for t in tickers]
    calls = []
    frame = history()
    monkeypatch.setattr(flow, "build_money_flow_universe_with_naver_rankings", lambda: universe)
    monkeypatch.setattr(flow, "IMAGE_THEME_UNIVERSE", universe)
    monkeypatch.setattr(flow, "download_money_flow_prices", lambda _: pd.DataFrame())
    monkeypatch.setattr(flow, "get_money_flow_ohlc", lambda data, ticker: calls.append(ticker) or frame)
    fn = flow.calculate_money_flow_df if kind == "etf" else flow.calculate_image_theme_flow_df
    expression = "flow.calculate_money_flow_df()" if kind == "etf" else "flow.calculate_image_theme_flow_df('')"
    source = f'''
import streamlit as st
from stock_lab_core import money_flow as flow
from stock_lab_core.performance import PerformanceTrace, measure
progress = st.empty()
with PerformanceTrace(on_phase=lambda name, elapsed: progress.write(name)):
    with measure("phase", "outer_flow"):
        st.session_state["result"] = {expression}
'''
    fn.clear()
    try:
        app = AppTest.from_string(source, default_timeout=15).run()
        assert not app.exception
        expected = app.session_state["result"].copy(deep=True)
        for _ in range(2):
            app.run()
            assert not app.exception
            pd.testing.assert_frame_equal(app.session_state["result"], expected, check_exact=True)
        assert sorted(calls) == sorted(tickers)
        assert app.markdown[0].value == "outer_flow"
    finally:
        fn.clear()
