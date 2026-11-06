"""Keep history inputs/results identical while overlapping independent I/O."""

from collections import Counter
from threading import Event, Lock
from time import perf_counter, sleep
from statistics import mean
import json

import pandas as pd
import pytest

from stock_lab_core import prices
from stock_lab_core.kr_flow_history import reuse_kr_history_connections
from stock_lab_core.performance import PerformanceTrace
from tests.test_kr_preload_connections import legacy_preload, same_frames


@pytest.mark.parametrize("period", ["1y", "10y", "3mo"])
@pytest.mark.parametrize("workers", [1, 4])
def test_domestic_starts_before_batch_finishes_without_extra_requests(period, workers):
    started = Event()
    finished = Event()
    calls = []
    lock = Lock()
    frame = pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.to_datetime(["2026-11-04", "2026-11-05"]))
    frame.attrs["basis"] = "unchanged"

    def batch(tickers, requested_period):
        assert started.wait(5), "Domestic I/O must not wait for the overseas batch"
        with lock:
            calls.append(("batch", tickers, requested_period))
        finished.set()
        return {"SPY": frame}

    def one(ticker, requested_period):
        with lock:
            calls.append(("one", ticker, requested_period))
        if ticker.endswith(".KS"):
            started.set()
        else:
            assert finished.is_set(), "Overseas fallback must wait for the batch"
        if ticker == "ERROR":
            raise RuntimeError("provider unavailable")
        return pd.DataFrame() if ticker == "EMPTY" else frame.copy(deep=True)

    tickers = ["005930.KS", "SPY", "SPY", "BITX", "EMPTY", "ERROR", ""]
    actual = prices.prefetch_price_data_parallel(tickers, period, workers, load_batch=batch, load_one=one)
    after_calls = Counter(calls)
    calls.clear()
    expected = legacy_preload(tickers, period, workers, load_batch=batch, load_one=one)
    same_frames(actual, expected)
    assert Counter(calls) == after_calls
    assert actual["SPY"] is frame


def test_actual_cache_and_http_counts_are_separate():
    from tests.test_kr_preload_connections import offline, clear_caches

    with pytest.MonkeyPatch.context() as patch:
        generator = offline.__wrapped__(patch)
        transport = next(generator)
        try:
            with PerformanceTrace() as cold:
                prices.prefetch_price_data_parallel(["000001.KS", "000002.KS"], "1y", 1)
            with PerformanceTrace() as warm:
                prices.prefetch_price_data_parallel(["000001.KS", "000002.KS"], "1y", 1)
            events = cold.report()["transport_events"]
            assert events["cache.price_history.miss"] == events["kr_history.request"] == 2
            assert warm.report()["transport_events"]["cache.price_history.reuse"] == 2
            assert warm.report()["transport_events"].get("kr_history.request", 0) == 0
            assert len(transport.calls) == 2
        finally:
            clear_caches()
            next(generator, None)


def benchmark():
    """Fixed responses/delays isolate scheduling; not a Cloud speed claim."""
    rows = []
    frame = pd.DataFrame({"Close": [10.0]})
    tickers = [f"{i:06d}.KS" for i in range(1, 17)] + ["SPY", "BITX"]
    for repeat in range(3):
        result, outputs, counts = {"repeat": repeat + 1}, {}, {}
        for mode, loader in (("before", legacy_preload), ("after", prices.prefetch_price_data_parallel)):
            calls, lock = [], Lock()

            def batch(symbols, period):
                with lock:
                    calls.append(("batch", symbols, period))
                sleep(0.2)
                return {"SPY": frame}

            def one(symbol, period):
                with lock:
                    calls.append(("one", symbol, period))
                sleep(0.025)
                return frame.copy(deep=True)

            start = perf_counter()
            with reuse_kr_history_connections():
                outputs[mode] = loader(tickers, "10y", 4, load_batch=batch, load_one=one)
            result[mode + "_seconds"] = perf_counter() - start
            counts[mode] = Counter(calls)
        same_frames(outputs["after"], outputs["before"])
        assert counts["before"] == counts["after"]
        rows.append(result)
    print(json.dumps({"synthetic": True, "same_requests_and_frames": True, "runs": rows,
                      "before_mean": mean(r["before_seconds"] for r in rows),
                      "after_mean": mean(r["after_seconds"] for r in rows)}, indent=2))


if __name__ == "__main__":
    benchmark()
