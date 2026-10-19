"""Offline parity, isolation and controlled timing for run-scoped KR context."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
import json
from threading import Barrier, Lock
from time import perf_counter, sleep

import pandas as pd
import pytest

from stock_lab_core import kr_sector_snapshot as kr
from stock_lab_core import prices
from stock_lab_core.performance import PerformanceTrace, submit_with_context, timed_call


@pytest.fixture(autouse=True)
def offline_prices(monkeypatch):
    original_batch = prices.load_latest_kr_quotes_batch
    monkeypatch.setattr(prices, "load_latest_kr_quotes_batch", lambda tickers: {})
    monkeypatch.setattr(prices, "load_latest_prices_batch", lambda tickers: {})
    return original_batch


def _requests():
    pairs = [(cluster, "") for cluster in kr.KR_CLUSTER_INDUSTRY_MAP]
    pairs += [("AI·반도체", detail) for detail in kr.KR_DETAIL_GROUPS]
    pairs += [(cluster, cluster) for cluster in kr.KR_CLUSTER_INDUSTRY_MAP]
    return pairs + [("AI·반도체", detail) for detail in ("반도체", "전자부품·MLCC")]


def _quote(ticker):
    seed = sum(ord(char) for char in ticker)
    return {"price": float(10000 + seed), "change_pct": float(seed % 7 - 3),
            "change_abs": float(seed % 11 - 5)}


def _same(actual, expected):
    assert json.dumps(actual, ensure_ascii=False, sort_keys=True) == json.dumps(expected, ensure_ascii=False, sort_keys=True)


@pytest.mark.parametrize("mode", ["full", "partial", "invalid_values", "empty", "error"])
def test_preload_equals_unscoped_selection_fallbacks_and_classifications(monkeypatch, mode):
    quote_calls, fallback_calls = [], []

    def quotes(tickers):
        quote_calls.append(tuple(tickers))
        if mode == "error":
            raise TimeoutError("offline failure")
        if mode == "invalid_values":
            return {ticker: {"price": 0.0, "change_pct": float("nan")} for ticker in tickers}
        return {ticker: _quote(ticker) for ticker in tickers
                if mode == "full" or (mode == "partial" and sum(map(ord, ticker)) % 5 == 0)}

    def fallback(tickers):
        fallback_calls.append(tuple(tickers))
        return {ticker: float(20000 + sum(map(ord, ticker))) if sum(map(ord, ticker)) % 2 else 0.0
                for ticker in tickers}

    monkeypatch.setattr(prices, "load_latest_kr_quotes_batch", quotes)
    monkeypatch.setattr(prices, "load_latest_prices_batch", fallback)
    requests = _requests()
    original = kr.load_kospi_sector_constituents().copy(deep=True)
    expected = [kr.build_kr_cluster_snapshot(cluster, detail_name=detail) for cluster, detail in requests]
    selected_tickers = set(ticker for batch in quote_calls for ticker in batch)
    quote_calls.clear()
    fallback_calls.clear()
    with kr.kr_cluster_snapshot_scope(requests, owner_scope="owner-a"):
        actual = [kr.build_kr_cluster_snapshot(cluster, detail_name=detail) for cluster, detail in requests]
        kr.preload_kr_cluster_snapshots(reversed(requests))
        repeated = [kr.build_kr_cluster_snapshot(cluster, detail_name=detail) for cluster, detail in requests]
    _same(actual, expected)
    _same(repeated, expected)
    assert len(quote_calls) == 1
    assert set(quote_calls[0]) == selected_tickers
    assert len(quote_calls[0]) == len(selected_tickers)
    assert all(count == 1 for count in Counter(ticker for batch in fallback_calls for ticker in batch).values())
    pd.testing.assert_frame_equal(kr.load_kospi_sector_constituents(), original)


def test_failed_quotes_and_price_fallbacks_are_remembered_until_scope_exit(monkeypatch):
    quotes, fallbacks = [], []
    monkeypatch.setattr(prices, "load_latest_kr_quotes_batch", lambda tickers: quotes.append(tuple(tickers)) or {})

    def unavailable(tickers):
        fallbacks.append(tuple(tickers))
        raise TimeoutError("offline fallback failure")

    monkeypatch.setattr(prices, "load_latest_prices_batch", unavailable)
    a, b = "005930.KS", "000660.KS"
    with kr.kr_cluster_snapshot_scope(owner_scope="owner-a"):
        assert kr._load_latest_quotes_for_snapshot([a, b]) == {}
        assert kr._load_latest_quotes_for_snapshot([a]) == {}
        assert kr._load_latest_quotes_for_snapshot([b, a]) == {}
    assert quotes == fallbacks == [(a, b)]
    with kr.kr_cluster_snapshot_scope(owner_scope="owner-a"):
        assert kr._load_latest_quotes_for_snapshot([a]) == {}
    assert quotes[-1] == fallbacks[-1] == (a,)
    assert len(quotes) == len(fallbacks) == 2


def test_cached_snapshots_keep_arguments_and_nested_values_independent(monkeypatch):
    calls = []
    monkeypatch.setattr(prices, "load_latest_kr_quotes_batch", lambda tickers: calls.append(tuple(tickers)) or {
        ticker: _quote(ticker) for ticker in tickers})
    cluster, detail = "AI·반도체", "전자부품·MLCC"
    expected = {(top_n, live): kr.build_kr_cluster_snapshot(cluster, top_n, detail, live)
                for top_n in (1, 3) for live in (False, True)}
    calls.clear()
    config = deepcopy(kr.KR_DETAIL_GROUPS)
    with kr.kr_cluster_snapshot_scope(owner_scope="owner-a"):
        for (top_n, live), reference in expected.items():
            snapshot = kr.build_kr_cluster_snapshot(cluster, top_n, detail, live)
            _same(snapshot, reference)
            snapshot["sectors"].append("mutated")
            snapshot["industries"][0]["name"] = "mutated"
            _same(kr.build_kr_cluster_snapshot(cluster, top_n, detail, live), reference)
    assert len(calls) == 1
    assert kr.KR_DETAIL_GROUPS == config


def test_static_unknown_and_unscoped_preload_do_not_fetch(monkeypatch):
    def unexpected(*args):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(prices, "load_latest_kr_quotes_batch", unexpected)
    monkeypatch.setattr(prices, "load_latest_prices_batch", unexpected)
    kr.preload_kr_cluster_snapshots(_requests())
    with kr.kr_cluster_snapshot_scope(owner_scope="owner-a"):
        assert kr.build_kr_cluster_snapshot("unknown") == {}
        assert kr.build_kr_cluster_snapshot("AI·반도체", live_prices=False)


def test_owner_scopes_workers_and_nested_runs_do_not_share_memos(monkeypatch):
    calls = Counter()
    lock = Lock()
    barrier = Barrier(2)

    def quotes(tickers):
        owner = kr._KR_CLUSTER_RUN.get().owner_scope
        with lock:
            calls[owner] += 1
        return {ticker: {"price": 100, "change_pct": 2 if owner == "owner-a" else -2} for ticker in tickers}

    monkeypatch.setattr(prices, "load_latest_kr_quotes_batch", quotes)

    def run(owner):
        with kr.kr_cluster_snapshot_scope(owner_scope=owner):
            barrier.wait(timeout=10)
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [submit_with_context(workers, kr.build_kr_cluster_snapshot, "AI·반도체") for _ in range(2)]
                snapshots = [future.result(timeout=10) for future in futures]
            _same(*snapshots)
            return snapshots[0]

    with ThreadPoolExecutor(max_workers=2) as workers:
        a, b = list(workers.map(run, ["owner-a", "owner-b"]))
    assert a["status"] == "확산 우세"
    assert b["status"] == "확산 약함"
    assert calls == {"owner-a": 1, "owner-b": 1}
    with kr.kr_cluster_snapshot_scope(owner_scope="owner-a"):
        outer = kr.build_kr_cluster_snapshot("AI·반도체")
        with pytest.raises(RuntimeError, match="exit probe"):
            with kr.kr_cluster_snapshot_scope(owner_scope="owner-b"):
                assert kr.build_kr_cluster_snapshot("AI·반도체")["status"] == "확산 약함"
                raise RuntimeError("exit probe")
        _same(kr.build_kr_cluster_snapshot("AI·반도체"), outer)
    assert kr._KR_CLUSTER_RUN.get() is None


def test_invalid_owner_and_preload_exception_restore_the_context(monkeypatch):
    with pytest.raises(ValueError, match="owner_scope"):
        with kr.kr_cluster_snapshot_scope(owner_scope=""):
            pass
    with kr.kr_cluster_snapshot_scope(owner_scope="owner-a") as outer:
        def fail(*args):
            raise RuntimeError("selection failure")

        monkeypatch.setattr(kr, "_select_cluster_rows", fail)
        with pytest.raises(RuntimeError, match="selection failure"):
            with kr.kr_cluster_snapshot_scope([("AI·반도체", "")], owner_scope="owner-b"):
                pass
        assert kr._KR_CLUSTER_RUN.get() is outer
    assert kr._KR_CLUSTER_RUN.get() is None


def test_controlled_same_input_before_after_elapsed_and_provider_counts(monkeypatch, offline_prices):
    """Cold batch caches, fake 2ms providers; elapsed is local, never cloud."""
    counts = Counter()
    lock = Lock()

    def bulk(tickers):
        counts["bulk"] += 1
        return {}

    @timed_call("prices", "_fetch_naver_realtime_quote")
    def realtime(ticker):
        with lock:
            counts["realtime"] += 1
        sleep(0.002)
        quote = _quote(ticker)
        quote["change_pct"] = quote["change_pct"] or 1.0
        return quote

    def quote_batch(tickers):
        counts["quote_batch"] += 1
        return offline_prices(tickers)

    # Keep the real batch cache/fallback executor and its shared four-slot cap.
    monkeypatch.setattr(prices, "load_latest_kr_quotes_batch", quote_batch)
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", bulk)
    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", realtime)
    requests = _requests()
    reports, snapshots = {}, []
    try:
        for label, context in (("before", nullcontext()), ("after", kr.kr_cluster_snapshot_scope(requests, owner_scope="offline-owner"))):
            prices._load_latest_kr_quotes_batch_cached.clear()
            counts.clear()
            with PerformanceTrace(scope="controlled_offline_kr_clusters") as trace:
                with context:
                    snapshots.append([kr.build_kr_cluster_snapshot(cluster, detail_name=detail) for cluster, detail in requests])
            reports[label] = {"elapsed_seconds": trace.elapsed_seconds, "providers": dict(counts)}
            if label == "after":
                entries = {row["name"]: row for row in trace.report()["functions"]}
                assert entries["kr_quote_fallback_wait"]["calls"] == 1
                assert entries["_fetch_naver_realtime_quote"]["calls"] == counts["realtime"]
        _same(snapshots[0], snapshots[1])
        assert reports["before"]["providers"]["quote_batch"] == len(requests)
        assert reports["after"]["providers"]["quote_batch"] == 1
        assert reports["after"]["providers"]["bulk"] == 1
        assert reports["after"]["providers"]["realtime"] < reports["before"]["providers"]["realtime"]
        print("controlled_offline_kr_clusters=" + json.dumps({"cluster_requests": len(requests), **reports}, sort_keys=True))
    finally:
        prices._load_latest_kr_quotes_batch_cached.clear()


def test_existing_long_ttl_analyst_cache_reuses_same_input_without_parallelism(monkeypatch):
    from stock_lab_core import news
    from stock_lab_core.today_enrichment import attach_today_analyst_context

    calls = []

    def direct(ticker):
        calls.append(ticker)
        sleep(0.001)
        return {"targetMeanPrice": 120.0, "currentPrice": 100.0, "numberOfAnalystOpinions": 7}

    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", direct)
    frame = pd.DataFrame({"티커": [f"TEST{i:03}" for i in range(62)], "현재가": [100.0] * 62})
    news.get_analyst_snapshot.clear()
    try:
        started = perf_counter()
        cold = attach_today_analyst_context(frame)
        cold_elapsed = perf_counter() - started
        cold_calls = len(calls)
        started = perf_counter()
        warm = attach_today_analyst_context(frame)
        warm_elapsed = perf_counter() - started
        pd.testing.assert_frame_equal(cold, warm, check_exact=True)
        assert cold_calls == len(calls) == 62
        print("controlled_existing_analyst_cache=" + json.dumps({
            "cold_seconds": cold_elapsed, "warm_seconds": warm_elapsed,
            "cold_provider_calls": cold_calls, "warm_provider_calls": len(calls) - cold_calls,
            "note": "Existing 6h cache, no analyst implementation change, not cloud elapsed",
        }, sort_keys=True))
    finally:
        news.get_analyst_snapshot.clear()


def test_analyst_enrichment_keeps_global_provider_cooldown(monkeypatch):
    from stock_lab_core import news
    from stock_lab_core.today_enrichment import attach_today_analyst_context
    from stock_lab_core.yahoo_metadata import yahoo_metadata_reader
    from yfinance.exceptions import YFRateLimitError

    calls = []

    def limited(ticker):
        calls.append(ticker)
        raise YFRateLimitError()

    def unexpected(*args, **kwargs):
        pytest.fail("cooldown must block all subsequent Yahoo providers")

    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", limited)
    monkeypatch.setattr(news.yf, "Ticker", unexpected)
    news.get_analyst_snapshot.clear()
    try:
        frame = pd.DataFrame({"티커": ["TESTA", "TESTB", "TESTA"], "현재가": [100.0] * 3})
        result = attach_today_analyst_context(frame)
        assert result["애널목표상태"].tolist() == ["rate_limited"] * 3
        assert calls == ["TESTA"]
        retry_after = yahoo_metadata_reader._retry_after
        news.get_analyst_snapshot.clear()
        attach_today_analyst_context(frame)
        assert calls == ["TESTA"]
        assert yahoo_metadata_reader._retry_after == retry_after
    finally:
        news.get_analyst_snapshot.clear()
