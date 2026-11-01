"""A valuation-local success memo must not replace provider/cache priorities."""

import ast
import json
from pathlib import Path
import subprocess

import pytest

from stock_lab_core import prices
from stock_lab_core.performance import PerformanceTrace


@pytest.fixture(autouse=True)
def clear_quotes():
    prices.clear_latest_price_cache()
    yield
    prices.clear_latest_price_cache()


def test_scope_successes_are_normalized_private_and_do_not_escape():
    calls = []
    wrapped = prices._reuse_realtime_quote(lambda t: calls.append(t) or 123.45)
    with PerformanceTrace() as trace:
        with prices.realtime_quote_scope():
            assert wrapped(" private ") == wrapped("PRIVATE") == 123.45
        assert wrapped("PRIVATE") == 123.45
    assert calls == [" private ", "PRIVATE"]
    assert trace.report()["transport_events"]["us_quote_scope.hit"] == 1
    assert "123.45" not in json.dumps(trace.report())
    assert "PRIVATE" not in json.dumps(trace.report())
    assert prices._REALTIME_QUOTE_MEMO.get() is None


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), "invalid", None])
def test_unusable_values_are_never_memoized(value):
    calls = []
    wrapped = prices._reuse_realtime_quote(lambda t: calls.append(t) or value)
    with prices.realtime_quote_scope():
        for _ in range(2):
            result = wrapped("TEST")
            assert result is value
    assert calls == ["TEST", "TEST"]


def test_ttl_is_from_call_start_not_last_hit_or_return(monkeypatch):
    now = [0.0]
    calls = []
    monkeypatch.setattr(prices.time, "monotonic", lambda: now[0])

    def fetch(ticker):
        calls.append(ticker)
        now[0] += 6
        return 100.0

    wrapped = prices._reuse_realtime_quote(fetch)
    with prices.realtime_quote_scope():
        assert wrapped("TEST") == 100.0
        now[0] = 14.999
        assert wrapped("TEST") == 100.0
        now[0] = 15.0
        assert wrapped("TEST") == 100.0
    assert len(calls) == 2


@pytest.mark.parametrize("duration", [15.0, -1.0])
def test_slow_or_backwards_clock_results_are_not_reused(monkeypatch, duration):
    now = [0.0]
    calls = []
    monkeypatch.setattr(prices.time, "monotonic", lambda: now[0])

    def fetch(ticker):
        calls.append(ticker)
        now[0] += duration
        return 100.0

    wrapped = prices._reuse_realtime_quote(fetch)
    with prices.realtime_quote_scope():
        wrapped("TEST")
        wrapped("TEST")
    assert len(calls) == 2


def test_nested_valuations_are_independent_and_restore_parent():
    calls = []
    wrapped = prices._reuse_realtime_quote(lambda t: calls.append(t) or float(len(calls)))
    with prices.realtime_quote_scope():
        assert wrapped("TEST") == 1.0
        with prices.realtime_quote_scope():
            assert wrapped("TEST") == 2.0
        assert wrapped("TEST") == 1.0
    with prices.realtime_quote_scope():
        assert wrapped("TEST") == 3.0


def test_concurrent_valuations_do_not_share_values():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def valuation(value):
        calls = []
        wrapped = prices._reuse_realtime_quote(lambda t: calls.append(t) or value)
        with prices.realtime_quote_scope():
            first = wrapped("TEST")
            barrier.wait(timeout=5)
            assert wrapped("TEST") == first == value
        return calls

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(valuation, value) for value in (100.0, 200.0)]
        assert [future.result(timeout=5) for future in results] == [["TEST"], ["TEST"]]


def test_clear_invalidates_existing_and_inflight_memo():
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        if len(calls) == 3:
            prices.clear_latest_price_cache()
        return float(len(calls))

    wrapped = prices._reuse_realtime_quote(fetch)
    with prices.realtime_quote_scope():
        assert wrapped("TEST") == 1.0
        prices.clear_latest_price_cache()
        assert wrapped("TEST") == 2.0
        assert wrapped("OTHER") == 3.0
        assert wrapped("OTHER") == 4.0
    assert len(calls) == 4


@pytest.mark.parametrize("error", [ValueError("provider error"), SystemExit("interrupted")])
def test_errors_propagate_without_cache_or_scope_leak(error):
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        if len(calls) == 1:
            raise error
        return 100.0

    wrapped = prices._reuse_realtime_quote(fetch)
    with pytest.raises(type(error)):
        with prices.realtime_quote_scope():
            wrapped("TEST")
    assert prices._REALTIME_QUOTE_MEMO.get() is None
    with prices.realtime_quote_scope():
        assert wrapped("TEST") == 100.0


@pytest.fixture
def first_overnight(monkeypatch):
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: False)
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: False)
    monkeypatch.setattr(prices, "_us_equity_market_closed_today", lambda: True)
    return []


def test_batch_and_display_reuse_same_successful_chain(first_overnight, monkeypatch):
    calls = first_overnight
    expected = {"TESTA": 100.0, "TESTB": 200.0}
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda t: calls.append(t) or expected[t])
    with prices.realtime_quote_scope():
        batch = prices.load_latest_prices_batch(("TESTA", "TESTB"))
        assert batch == expected
        assert prices.load_latest_price("testa") == 100.0
        assert prices.load_latest_price("testb") == 200.0
    assert calls == ["TESTA", "TESTB"]


def test_scoped_hit_does_not_restart_global_cache_ttl(first_overnight, monkeypatch):
    calls = first_overnight
    price = [100.0]
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda t: calls.append(t) or price[0])
    with prices.realtime_quote_scope():
        prices.load_latest_prices_batch(("TESTA", "TESTB"))
        assert prices.load_latest_price("TESTA") == 100.0
        assert prices.load_latest_price("TESTA") == 100.0
    assert calls == ["TESTA", "TESTB"]
    price[0] = 120.0
    assert prices.load_latest_price("TESTA") == 120.0
    assert calls == ["TESTA", "TESTB", "TESTA"]
    assert prices._SCOPED_QUOTE_USED.get() is None


def test_older_cache_module_disables_scope_instead_of_extending_age(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(prices, "_result_cache", SimpleNamespace())
    calls = []
    wrapped = prices._reuse_realtime_quote(lambda t: calls.append(t) or 100.0)
    with PerformanceTrace() as trace, prices.realtime_quote_scope():
        assert wrapped("TEST") == wrapped("TEST") == 100.0
    assert len(calls) == 2
    assert trace.report()["transport_events"] == {"us_quote_scope.unavailable": 1}


def test_existing_single_price_cache_still_wins_over_new_batch(first_overnight, monkeypatch):
    calls = first_overnight
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda t: calls.append(t) or (80.0 if len(calls) == 1 else 110.0))
    assert prices.load_latest_price("TESTA") == 80.0
    with prices.realtime_quote_scope():
        assert prices.load_latest_prices_batch(("TESTA", "TESTB"))["TESTA"] == 110.0
        assert prices.load_latest_price("TESTA") == 80.0
    assert calls == ["TESTA", "TESTA", "TESTB"]


def test_failed_chain_and_regular_fallback_do_not_block_fresh_display(first_overnight, monkeypatch):
    calls = first_overnight
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda t: calls.append(t) or (100.0 if len(calls) > 1 else 0.0))
    for name in ("_fetch_yahoo_quote", "_fetch_yf_download_price", "_fetch_robinhood_us_quote",
                 "_fetch_kis_us_quote_price", "_fetch_configured_us_quote_price", "_fetch_pyth_us_live_price", "_fetch_cboe_book_price"):
        monkeypatch.setattr(prices, name, lambda *a, **kw: 0.0)
    monkeypatch.setattr(prices, "_fetch_yahoo_regular_close_price", lambda *a: 80.0)
    with prices.realtime_quote_scope():
        assert prices.load_latest_prices_batch(("TESTA", "TESTB"))["TESTA"] == 80.0
        assert prices.load_latest_price("TESTA") == 100.0
    assert calls == ["TESTA", "TESTB", "TESTA"]


def test_holdings_manual_override_and_display_logic_are_unchanged():
    root = Path(__file__).resolve().parents[1]
    before = subprocess.check_output(["git", "show", "7e67afba:app.py"], cwd=root).decode("utf-8-sig")
    after = (root / "app.py").read_text(encoding="utf-8-sig")
    functions = [next(n for n in ast.parse(s).body if isinstance(n, ast.FunctionDef) and n.name == "build_holdings_table") for s in (before, after)]
    assert ast.dump(functions[0], include_attributes=False) == ast.dump(functions[1], include_attributes=False)
