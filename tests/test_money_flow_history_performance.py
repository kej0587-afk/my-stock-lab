from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, current_thread
from time import sleep

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import money_flow as flow
from stock_lab_core.performance import PerformanceTrace, timed_call


def history(rows=252, direction=1):
    close = 100 + direction * np.arange(rows) * 0.1 + np.sin(np.arange(rows))
    return pd.DataFrame({"Close": close, "High": close + 2, "Low": close - 2,
                         "Volume": 1000 + np.arange(rows) * 2},
                        index=pd.bdate_range("2025-01-02", periods=rows))


def serial_metrics(data, universe):
    result = {}
    for item in universe:
        ticker = item["ticker"]
        if ticker not in result:
            px = flow.get_money_flow_ohlc(data, ticker)
            result[ticker] = flow._compute_ticker_metrics(px) if not px.empty and len(px) >= 20 else None
    return result


@pytest.mark.parametrize("kind", ["etf", "all_themes", "selected_theme"])
def test_parallel_tables_equal_serial_results_including_missing_and_duplicate_tickers(monkeypatch, kind):
    universe = [
        {"ticker": ticker, "name": f"name-{i}", "테마": "A" if i % 2 else "B",
         "하위테마": str(i % 3), "구분": "test", "섹터": str(i), "랭킹보조점수": float(i % 2)}
        for i, ticker in enumerate(["005930.KS", "NVDA", "000660.KS", "005930.KS",
                                    "098120.KQ", "0167A0.KS", "AMD", "7203.T"])
    ]
    frames = {ticker: history(direction=(-1 if i % 2 else 1))
              for i, ticker in enumerate(dict.fromkeys(item["ticker"] for item in universe))}
    frames["098120.KQ"] = pd.DataFrame()
    frames["0167A0.KS"] = history(19)
    frames["AMD"] = history(20)
    calls = []
    metric_threads = []
    main_thread = current_thread().ident
    original_metric = flow._compute_ticker_metrics

    def get_history(data, ticker):
        calls.append(ticker)
        return frames[ticker].copy()

    def compute(px):
        metric_threads.append(current_thread().ident)
        return original_metric(px)

    monkeypatch.setattr(flow, "download_money_flow_prices", lambda _: pd.DataFrame())
    monkeypatch.setattr(flow, "get_money_flow_ohlc", get_history)
    monkeypatch.setattr(flow, "_compute_ticker_metrics", compute)
    monkeypatch.setattr(flow, "build_money_flow_universe_with_naver_rankings", lambda: universe)
    monkeypatch.setattr(flow, "IMAGE_THEME_UNIVERSE", universe)
    calculate = (lambda: flow.calculate_money_flow_df.__wrapped__()) if kind == "etf" else (
        lambda: flow.calculate_image_theme_flow_df.__wrapped__("A" if kind == "selected_theme" else "")
    )
    parallel = flow._load_universe_metrics
    monkeypatch.setattr(flow, "_load_universe_metrics", serial_metrics)
    expected = calculate()
    expected_counts = Counter(calls)
    calls.clear()
    monkeypatch.setattr(flow, "_load_universe_metrics", parallel)
    actual = calculate()
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert Counter(calls) == expected_counts
    assert all(count == 1 for count in Counter(calls).values())
    assert set(metric_threads) == {main_thread}


def test_shared_cap_between_sessions_and_no_parallel_us_fallback(monkeypatch):
    lock = Lock()
    state = {"active": 0, "peak": 0}
    non_kr_threads = []

    def get_history(data, ticker):
        if not flow._is_krx_money_flow_ticker(ticker):
            non_kr_threads.append(current_thread().ident)
            return pd.DataFrame()
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            sleep(0.015)
            return pd.DataFrame()
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(flow, "get_money_flow_ohlc", get_history)

    def run(start):
        caller = current_thread().ident
        universe = [{"ticker": f"{i:06d}.KS"} for i in range(start, start + 12)]
        universe += [{"ticker": "NVDA"}, {"ticker": "7203.T"}]
        flow._load_universe_metrics(pd.DataFrame(), universe)
        return caller

    with ThreadPoolExecutor(max_workers=2) as pool:
        callers = set(pool.map(run, [1, 21]))
    assert 1 < state["peak"] <= 4
    assert state["active"] == 0
    assert set(non_kr_threads) <= callers


def test_provider_order_and_failure_visibility_preserved(monkeypatch):
    calls = []
    lock = Lock()

    def krx(ticker):
        with lock:
            calls.append((ticker, "krx"))
        return pd.DataFrame()

    def fdr(ticker):
        with lock:
            calls.append((ticker, "fdr"))
        return history(20)

    monkeypatch.setattr(flow, "_fetch_pykrx_ohlc", krx)
    monkeypatch.setattr(flow, "_fetch_fdr_ohlc", fdr)
    monkeypatch.setattr(flow, "_FDR_AVAILABLE", True)
    universe = [{"ticker": ticker} for ticker in ["005930.KS", "0167A0.KS"]]
    metrics = flow._load_universe_metrics(pd.DataFrame(), universe)
    for ticker in metrics:
        assert [provider for key, provider in calls if key == ticker] == ["krx", "fdr"]
        assert metrics[ticker] is not None

    def fail(data, ticker):
        raise RuntimeError("unexpected provider failure")

    monkeypatch.setattr(flow, "get_money_flow_ohlc", fail)
    with pytest.raises(RuntimeError, match="unexpected provider"):
        flow._load_universe_metrics(pd.DataFrame(), universe)
    # Failed calls release the shared slots; a later attempt still works.
    monkeypatch.setattr(flow, "get_money_flow_ohlc", lambda *args: history(20))
    assert all(flow._load_universe_metrics(pd.DataFrame(), universe).values())


@pytest.mark.parametrize("tickers", [[], ["005930.KS"], ["NVDA", "AMD"]])
def test_empty_single_and_non_kr_paths_do_not_create_thread_pool(monkeypatch, tickers):
    def unexpected_pool(*args, **kwargs):
        raise AssertionError("no pool needed")

    monkeypatch.setattr(flow, "ThreadPoolExecutor", unexpected_pool)
    monkeypatch.setattr(flow, "get_money_flow_ohlc", lambda *args: history(20))
    result = flow._load_universe_metrics(pd.DataFrame(), [{"ticker": ticker} for ticker in tickers])
    assert list(result) == tickers


def test_worker_timings_stay_in_current_performance_report(monkeypatch):
    @timed_call("prices", "get_money_flow_ohlc")
    def fetch(data, ticker):
        return history(20)

    monkeypatch.setattr(flow, "get_money_flow_ohlc", fetch)
    with PerformanceTrace() as trace:
        flow._load_universe_metrics(pd.DataFrame(), [{"ticker": "005930.KS"}, {"ticker": "000660.KS"}])
    entries = {row["name"]: row for row in trace.report()["functions"]}
    assert entries["get_money_flow_ohlc"]["calls"] == 2
    assert entries["flow_history_and_metrics"]["calls"] == 1
    assert entries["_compute_ticker_metrics"]["calls"] == 2
