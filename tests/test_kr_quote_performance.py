import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Lock
from time import sleep

import pytest

from stock_lab_core import prices
from stock_lab_core.performance import PerformanceTrace


@pytest.fixture(autouse=True)
def clear_quote_cache():
    prices._load_latest_kr_quotes_batch_cached.clear()
    yield
    prices._load_latest_kr_quotes_batch_cached.clear()


def _serial_reference(tickers, bulk, realtime, basic):
    quotes = deepcopy(bulk)
    for ticker in tickers:
        key = prices.normalize_price_lookup_key(ticker)
        quote = quotes.get(key, {})
        if quote.get("price", 0.0) and quote.get("change_pct", 0.0):
            continue
        direct = realtime(ticker)
        if not direct or not direct.get("change_pct", 0.0):
            direct = basic(ticker)
        if direct:
            merged = dict(quote)
            merged.update({key: value for key, value in direct.items() if value not in ("", None, 0.0)})
            quotes[key] = merged
    return quotes


def test_parallel_matches_original_provider_order_merging_and_empty_results(monkeypatch):
    tickers = tuple(f"{index:06d}.KS" for index in range(1, 6))
    bulk = {
        tickers[0]: {"price": 100, "change_pct": -2.0, "source": "bulk"},
        tickers[1]: {"price": 101, "source": "bulk"},
        tickers[2]: {"price": 102, "change_pct": 0.0},
    }
    calls = {ticker: [] for ticker in tickers}
    def realtime(ticker):
        calls[ticker].append("realtime")
        return {"price": 200, "change_pct": 3} if ticker == tickers[1] else {}
    def basic(ticker):
        calls[ticker].append("basic")
        return {"price": 300, "change_pct": 0.0, "empty": None} if ticker == tickers[2] else {}
    expected = _serial_reference(tickers, bulk, realtime, basic)
    expected_calls = deepcopy(calls)
    for ticker in calls:
        calls[ticker].clear()
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda _: deepcopy(bulk))
    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", realtime)
    monkeypatch.setattr(prices, "_fetch_naver_basic_quote", basic)
    actual = prices._load_latest_kr_quotes_batch_cached.__wrapped__(tickers)
    assert actual == expected
    assert calls == expected_calls
    assert bulk[tickers[2]]["change_pct"] == 0.0
    assert list(actual) == list(expected)


def test_fallback_cap_is_shared_between_simultaneous_batches(monkeypatch):
    lock = Lock()
    state = {"active": 0, "peak": 0}
    def realtime(ticker):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            sleep(0.03)
            return {"price": 100, "change_pct": 1}
        finally:
            with lock:
                state["active"] -= 1
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda _: {})
    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", realtime)
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(prices._load_latest_kr_quotes_batch_cached.__wrapped__, tuple(f"{i:06d}.KS" for i in range(1, 13)))
        b = executor.submit(prices._load_latest_kr_quotes_batch_cached.__wrapped__, tuple(f"{i:06d}.KS" for i in range(21, 33)))
        assert len(a.result()) == len(b.result()) == 12
    assert 1 < state["peak"] <= 4
    assert state["active"] == 0


def test_cache_hits_skip_fallback_and_workers_keep_timings(monkeypatch):
    calls = []
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda _: {})
    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", lambda ticker: calls.append(ticker) or {"price": 100, "change_pct": 1})
    tickers = ["005930.KS", "000660.KS"]
    with PerformanceTrace() as trace:
        first = prices.load_latest_kr_quotes_batch(tickers)
        second = prices.load_latest_kr_quotes_batch(list(reversed(tickers)))
    assert first == second
    assert len(calls) == 2
    entries = trace.report()["functions"]
    assert next(row for row in entries if row["name"] == "kr_quote_fallback")["calls"] == 2
    assert next(row for row in entries if row["name"] == "kr_quote_fallback_wait")["calls"] == 1


def test_unexpected_provider_exception_still_propagates(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda _: {})
    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", lambda _: (_ for _ in ()).throw(RuntimeError("probe")))
    with pytest.raises(RuntimeError, match="probe"):
        prices._load_latest_kr_quotes_batch_cached.__wrapped__(("005930.KS", "000660.KS"))


def test_kr_batch_cache_ttl_and_clear_contract_stay_unchanged():
    tree = ast.parse(Path(prices.__file__).read_text(encoding="utf-8-sig"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_load_latest_kr_quotes_batch_cached")
    cache = next(node for node in fn.decorator_list if isinstance(node, ast.Call))
    assert next(keyword.value.value for keyword in cache.keywords if keyword.arg == "ttl") == 45
    assert callable(prices._load_latest_kr_quotes_batch_cached.clear)
