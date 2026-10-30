from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from stock_lab_core import prices, quote_prefetch
from stock_lab_core.performance import submit_with_context


@pytest.fixture(autouse=True)
def clean():
    prices.clear_latest_price_cache()
    yield
    prices.clear_latest_price_cache()


def test_fresh_batch_is_domestic_only_and_workers_reuse_same_values(monkeypatch):
    bulk = Mock(return_value={"379810.KS": 100.0, "0167A0.KS": 200.0})
    single = Mock(return_value=300.0)
    monkeypatch.setattr(prices, "_fetch_naver_prices_bulk", bulk)
    monkeypatch.setattr(prices, "_fetch_price_uncached", single)
    with prices.fresh_kr_quote_scope(["379810.ks", "RAM", "0167a0.ks", "379810.KS"]):
        with ThreadPoolExecutor(max_workers=2) as executor:
            values = [submit_with_context(executor, prices.load_latest_price, t).result()
                      for t in ["379810.KS", "0167A0.KS", "RAM", "379810.ks"]]
        assert values == [100.0, 200.0, 300.0, 100.0]
    bulk.assert_called_once_with(["379810.KS", "0167A0.KS"])
    single.assert_called_once_with("RAM")
    # The prefetched result is not promoted into another 15-second cache.
    assert prices.load_latest_price("379810.KS") == 300
    assert single.call_count == 2


def test_ttl_counts_provider_wait_and_hits_do_not_extend_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(quote_prefetch.time, "monotonic", lambda: clock[0])
    def bulk(keys):
        clock[0] = 4.0
        return {"379810.KS": 100}
    monkeypatch.setattr(prices, "_fetch_naver_prices_bulk", bulk)
    fallback = Mock(return_value=101)
    monkeypatch.setattr(prices, "_fetch_price_uncached", fallback)
    with prices.fresh_kr_quote_scope(["379810.KS"]):
        assert prices.load_latest_price("379810.KS") == 100
        clock[0] = 14.999
        assert prices.load_latest_price("379810.KS") == 100
        clock[0] = 15.0
        assert prices.load_latest_price("379810.KS") == 101
    fallback.assert_called_once_with("379810.KS")


@pytest.mark.parametrize("value", [None, 0, -1, float("nan"), float("inf"), True, "bad"])
def test_invalid_or_missing_value_keeps_original_fallback(monkeypatch, value):
    monkeypatch.setattr(prices, "_fetch_naver_prices_bulk", lambda keys: {"379810.KS": value})
    fallback = Mock(return_value=123)
    monkeypatch.setattr(prices, "_fetch_price_uncached", fallback)
    with prices.fresh_kr_quote_scope(["379810.KS", "379800.KS"]):
        assert prices.load_latest_price("379810.KS") == 123
        assert prices.load_latest_price("379800.KS") == 123
    assert fallback.call_count == 2


def test_failed_bulk_does_not_abort_original_lookup(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_naver_prices_bulk", Mock(side_effect=TimeoutError))
    monkeypatch.setattr(prices, "_fetch_price_uncached", lambda ticker: 123)
    with prices.fresh_kr_quote_scope(["379810.KS"]):
        assert prices.load_latest_price("379810.KS") == 123


def test_clear_during_request_invalidates_inflight_snapshot(monkeypatch):
    def bulk(keys):
        prices.clear_latest_price_cache()
        return {"379810.KS": 100}
    monkeypatch.setattr(prices, "_fetch_naver_prices_bulk", bulk)
    monkeypatch.setattr(prices, "_fetch_price_uncached", lambda ticker: 120)
    with prices.fresh_kr_quote_scope(["379810.KS"]):
        assert prices.load_latest_price("379810.KS") == 120


def test_clear_during_scope_and_nested_errors_restore_context(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_price_uncached", lambda ticker: 120)
    with quote_prefetch.fresh_quote_scope(["379810.KS"], lambda keys: {keys[0]: 100}, ttl=15):
        with pytest.raises(RuntimeError):
            with quote_prefetch.fresh_quote_scope(["379810.KS"], lambda keys: {keys[0]: 110}, ttl=15):
                assert prices.load_latest_price("379810.KS") == 110
                raise RuntimeError("cancel")
        assert prices.load_latest_price("379810.KS") == 100
        prices.clear_latest_price_cache()
        assert prices.load_latest_price("379810.KS") == 120
    assert quote_prefetch.prefetched_quote("379810.KS") is None


def test_parallel_scopes_do_not_share_prices():
    from threading import Barrier
    barrier = Barrier(2)
    def run(value):
        with quote_prefetch.fresh_quote_scope(["379810.KS"], lambda keys: {keys[0]: value}, ttl=15):
            barrier.wait(timeout=5)
            return prices.load_latest_price("379810.KS")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, value) for value in (100, 200)]
        assert [f.result() for f in futures] == [100, 200]


def test_bulk_batches_are_bounded_and_do_not_create_us_requests(monkeypatch):
    bulk = Mock(return_value={})
    monkeypatch.setattr(prices, "_fetch_naver_prices_bulk", bulk)
    with prices.fresh_kr_quote_scope(["RAM", "^GSPC", "NQ=F"]):
        bulk.assert_not_called()
    with prices.fresh_kr_quote_scope([f"{i:06d}.KS" for i in range(121)]):
        pass
    assert [len(call.args[0]) for call in bulk.call_args_list] == [50, 50, 21]
