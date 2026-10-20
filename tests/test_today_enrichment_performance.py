"""Offline concurrency, equivalence and repeatable fake-I/O timing checks."""

from collections import Counter
from datetime import datetime, timezone
from threading import Barrier, Event, Lock, get_ident
from time import perf_counter, sleep

import pandas as pd
import pytest

from stock_lab_core import today_enrichment as enrichment
from stock_lab_core.performance import PerformanceTrace, measure, timed_call


class FrozenDatetime:
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 20, 8, tzinfo=timezone.utc)


def representative_input():
    tickers = [f"{700000 + i}.KQ" for i in range(30)] + [f"LAB{i}" for i in range(32)]
    rows = [
        {"ticker": ticker, "price": 100 if i % 2 else None, "grade": "A", "decision": "WAIT"}
        for i, ticker in enumerate(tickers)
    ]
    rows += [{"ticker": ticker.removesuffix(".KQ").lower(), "price": None}
             for ticker in tickers[:12]]
    rows += [{"ticker": "QQQ"}, {"ticker": "invalid/ticker"}, {"ticker": None}] * 4
    frame = pd.DataFrame(rows, index=[i % 17 for i in range(len(rows))])
    frame.attrs["basis"] = "unchanged"
    return frame, tickers


class FakeProvider:
    def __init__(self, tickers, delay=0):
        self.positions = {ticker: i for i, ticker in enumerate(tickers)}
        self.delay = delay
        self.calls = Counter()
        self.lock = Lock()
        self.active = self.peak = 0
        self.caller = get_ident()
        self.price_threads = []
        self.snapshot = timed_call("external_data", "get_analyst_snapshot")(self._snapshot)

    def _snapshot(self, ticker):
        with self.lock:
            self.calls[("snapshot", ticker)] += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            i = self.positions[ticker]
            sleep(self.delay * (1 + (i % 4) / 4))
            if i == 0:
                raise TimeoutError("provider timeout")
            if i == 1:
                return None
            if i == 2:
                return {"data": None, "source": "invalid provider"}
            data = {"targetMeanPrice": 120 + i / 10, "numberOfAnalystOpinions": 12}
            if i % 3:
                data["currentPrice"] = 101
            snapshot = {"ok": True, "data": data, "source": "fake", "asof": "2026-10-19",
                        "fetched_at": "2026-10-20T07:00:00+00:00"}
            if i in (3, 4, 7):
                snapshot.update(ok=False, status={3: "stale", 4: "rate_limited", 7: "lookup_error"}[i],
                                reason="provider unavailable")
            if i == 5:
                data.pop("targetMeanPrice")
                data["targetHighPrice"] = 999
            if i == 6:
                data["quoteType"] = "ETF"
            if i == 8:
                data["targetMedianPrice"] = data.pop("targetMeanPrice")
                snapshot["field_sources"] = {
                    "targetMedianPrice": {"source": "median provider", "asof": "2026-10-18"}
                }
            return snapshot
        finally:
            with self.lock:
                self.active -= 1

    def price(self, ticker):
        self.calls[("price", ticker)] += 1
        self.price_threads.append(get_ident())
        if self.positions[ticker] == 12:
            raise TimeoutError("price timeout")
        return 100


def enrich(frame, provider, **kwargs):
    return enrichment.attach_today_analyst_context(
        frame, ticker_col="ticker", price_col="price",
        get_analyst_snapshot=provider.snapshot, load_latest_price=provider.price, **kwargs,
    )


def test_serial_parallel_exact_outputs_and_three_repeat_benchmark(monkeypatch):
    # Freeze only lookup timestamps; compare every column, dtype, index and attr.
    monkeypatch.setattr(enrichment, "datetime", FrozenDatetime)
    frame, tickers = representative_input()
    pristine = frame.copy(deep=True)
    timings = []
    for _ in range(3):
        serial, parallel = FakeProvider(tickers, .02), FakeProvider(tickers, .02)
        started = perf_counter()
        expected = enrich(frame, serial, max_workers=1)
        serial_seconds = perf_counter() - started
        with PerformanceTrace() as trace:
            with measure("phase", "analyst_enrichment"):
                started = perf_counter()
                actual = enrich(frame, parallel)
                parallel_seconds = perf_counter() - started
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
        assert list(actual.attrs["today_analyst_snapshots"]) == tickers
        assert parallel.calls == serial.calls
        assert all(count == 1 for count in parallel.calls.values())
        assert sum(count for (kind, _), count in parallel.calls.items() if kind == "snapshot") == 62
        assert 1 < parallel.peak <= 4
        assert set(parallel.price_threads) == {parallel.caller}
        entry = next(item for item in trace.report()["functions"] if item["name"] == "get_analyst_snapshot")
        assert entry["calls"] == 62 and entry["failures"] == 1
        assert entry["active_wall_seconds"] < entry["total_seconds"]
        timings.append((round(serial_seconds, 4), round(parallel_seconds, 4)))
    pd.testing.assert_frame_equal(frame, pristine, check_exact=True)
    assert frame.attrs == pristine.attrs
    print(f"\nFake I/O 86 rows / 62 snapshots, serial/parallel seconds: {timings}")


def test_workers_overlap_with_a_hard_bound_and_restore_input_order():
    barrier = Barrier(4)
    last_finished = Event()
    caller = get_ident()
    completions = []

    def snapshot(ticker):
        assert get_ident() != caller
        barrier.wait(timeout=5)
        if ticker != "LAB3":
            assert last_finished.wait(timeout=5)
        completions.append(ticker)
        if ticker == "LAB3":
            last_finished.set()
        return {"data": {"targetMeanPrice": 120, "currentPrice": 100}}

    frame = pd.DataFrame({"ticker": [f"LAB{i}" for i in range(4)]}, index=[9, 2, 9, 1])
    out = enrichment.attach_today_analyst_context(frame, ticker_col="ticker", get_analyst_snapshot=snapshot)
    assert completions[0] == "LAB3"
    assert out.index.tolist() == [9, 2, 9, 1]
    assert list(out.attrs["today_analyst_snapshots"]) == frame["ticker"].tolist()
    assert out["애널목표상태"].tolist() == ["available"] * 4


@pytest.mark.parametrize("max_workers", [0, -1, 5, True, 1.5, "4", None])
def test_invalid_worker_bound_rejected(max_workers):
    with pytest.raises(ValueError, match="max_workers"):
        enrichment.attach_today_analyst_context(pd.DataFrame(), max_workers=max_workers)


@pytest.mark.parametrize("tickers", [[], ["QQQ", "invalid/ticker"], ["LAB0", "lab0"]])
def test_zero_or_one_unique_lookup_never_starts_workers(monkeypatch, tickers):
    caller = get_ident()
    calls = []

    def no_pool(**kwargs):
        pytest.fail("No pool needed")

    def snapshot(ticker):
        assert get_ident() == caller
        calls.append(ticker)
        return {"data": {"targetMeanPrice": 120, "currentPrice": 100}}

    monkeypatch.setattr(enrichment, "ThreadPoolExecutor", no_pool)
    enrichment.attach_today_analyst_context(
        pd.DataFrame({"ticker": tickers}), ticker_col="ticker", get_analyst_snapshot=snapshot,
    )
    assert calls == (["LAB0"] if "LAB0" in tickers else [])


def test_serial_opt_out_preserves_caller_thread():
    caller = get_ident()

    def snapshot(ticker):
        assert get_ident() == caller
        return {"data": {"targetMeanPrice": 120, "currentPrice": 100}}

    result = enrichment.attach_today_analyst_context(
        pd.DataFrame({"ticker": ["LAB0", "LAB1"]}),
        ticker_col="ticker", get_analyst_snapshot=snapshot, max_workers=1,
    )
    assert result["애널목표상태"].tolist() == ["available"] * 2


@pytest.mark.parametrize("use_default", [True, False])
def test_provider_caches_and_yahoo_lock_survive_workers(monkeypatch, use_default):
    from stock_lab_core import news
    from stock_lab_core.yahoo_metadata import YahooMetadataReader

    class NoUI:
        def __getattr__(self, name):
            pytest.fail(f"Provider must not access Streamlit: {name}")

    calls = []
    active = peak = 0
    lock = Lock()
    caller = get_ident()

    def fetch(ticker):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            calls.append((ticker, get_ident()))
            sleep(.01)
            return {"targetMeanPrice": 120, "currentPrice": 100}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(news, "st", NoUI())
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", fetch)
    monkeypatch.setattr(news, "yahoo_metadata_reader", YahooMetadataReader(min_interval=0))
    news.get_analyst_snapshot.clear()
    try:
        frame = pd.DataFrame({"ticker": [f"LAB{i}" for i in range(8)]})
        kwargs = {} if use_default else {"get_analyst_snapshot": news.get_analyst_snapshot}
        first = enrichment.attach_today_analyst_context(frame, ticker_col="ticker", **kwargs)
        second = enrichment.attach_today_analyst_context(frame, ticker_col="ticker", **kwargs)
        pd.testing.assert_frame_equal(first, second, check_exact=True)
        assert first.attrs == second.attrs
        assert first["애널목표상태"].tolist() == ["available"] * 8
        assert Counter(ticker for ticker, _ in calls) == Counter(frame["ticker"])
        if use_default:
            assert calls[0][1] == caller
        else:
            assert all(thread != caller for _, thread in calls)
        assert any(thread != caller for _, thread in calls)
        assert peak == 1
    finally:
        news.get_analyst_snapshot.clear()
