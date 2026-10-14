from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from stock_lab_core import news, prices
from stock_lab_core.earnings_calendar import EarningsCalendarReader
from stock_lab_core.today_enrichment import attach_today_analyst_context, build_today_analyst_upside_map
from stock_lab_core.yahoo_metadata import YahooMetadataReader, yahoo_metadata_reader
from stock_lab_core import yahoo_metadata


@pytest.mark.parametrize("error", [YFRateLimitError(), HTTPError("https://example.test", 429, "limited", {}, None)])
def test_limit_stops_other_symbols_and_calendar_and_backoff_increases(error):
    clock = [0.0]
    reader = YahooMetadataReader(clock=lambda: clock[0], min_interval=0)
    calls = []
    def failed(ticker):
        calls.append(ticker)
        raise error
    for i in range(10):
        assert reader.read("info", str(i), failed)["status"] == "rate_limited"
    calendar = EarningsCalendarReader(reader=reader)
    assert calendar.read("OTHER", failed)["status"] == "rate_limited"
    assert calls == ["0"]
    clock[0] = 181
    reader.read("info", "0", failed)
    assert len(calls) == 2
    assert reader._retry_after == 541
    clock[0] = 542
    assert reader.read("info", "0", lambda _: {"longName": "Recovered"})["ok"]


def test_last_success_is_marked_stale_without_refreshing_its_date():
    clock = [0.0]
    reader = YahooMetadataReader(clock=lambda: clock[0], min_interval=0, stale_ttl=100)
    original = reader.read("info", "TEST", lambda _: {"targetMeanPrice": 120}, ttl=10)
    original["data"]["targetMeanPrice"] = 999
    clock[0] = 11
    def failed(_):
        raise YFRateLimitError()
    stale = reader.read("info", "TEST", failed, ttl=10)
    assert not stale["ok"] and stale["status"] == "stale"
    assert stale["data"]["targetMeanPrice"] == 120
    assert stale["fetched_at"] == original["fetched_at"]
    clock[0] = 101
    assert reader.read("info", "TEST", failed, ttl=10)["data"] == {}


def test_parallel_views_share_one_info_fetch():
    reader = YahooMetadataReader(min_interval=0)
    calls = []
    def fetch(ticker):
        calls.append(ticker)
        return {"longName": "One company"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reader.read("info", "test", fetch), range(12)))
    assert calls == ["TEST"]
    assert all(result["ok"] for result in results)
    assert reader.counts()["cache_hits"] == 11


def test_empty_result_only_blocks_briefly_and_manual_refresh_cannot_bypass_429():
    clock = [0.0]
    reader = YahooMetadataReader(clock=lambda: clock[0], min_interval=0)
    calls = []
    def fetch(ticker):
        calls.append(ticker)
        return {} if len(calls) == 1 else {"longName": "Recovered"}
    assert not reader.read("info", "TEST", fetch)["ok"]
    assert not reader.read("info", "TEST", fetch)["ok"]
    clock[0] = 61
    assert reader.read("info", "TEST", fetch)["ok"]
    def limited(_):
        raise YFRateLimitError()
    reader.read("calendar", "OTHER", limited)
    reader.clear_cache()
    assert reader.read("info", "NEW", fetch)["status"] == "rate_limited"
    assert calls == ["TEST", "TEST"]


def test_analyst_rate_limit_skips_fallback_chain_and_keeps_status(monkeypatch):
    news.get_analyst_snapshot.clear()
    calls = []
    def limited(ticker):
        calls.append(ticker)
        raise YFRateLimitError()
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", limited)
    monkeypatch.setattr(news.yf, "Ticker", lambda *a, **kw: pytest.fail("fallback during cooldown"))
    try:
        for ticker in ("TEST_A", "TEST_B"):
            snapshot = news.get_analyst_snapshot(ticker)
            assert not snapshot["ok"] and snapshot["status"] == "rate_limited"
            result = attach_today_analyst_context(pd.DataFrame([{"티커": "TEST", "현재가": 100}]),
                                                 get_analyst_snapshot=lambda _: snapshot)
            assert result.iloc[0]["애널목표상태"] == "rate_limited"
        assert calls == ["TEST_A"]
    finally:
        news.get_analyst_snapshot.clear()


def test_stale_analyst_target_is_retained_for_audit_not_execution(monkeypatch):
    clock = [0.0]
    reader = YahooMetadataReader(clock=lambda: clock[0], min_interval=0)
    monkeypatch.setattr(news, "yahoo_metadata_reader", reader)
    calls = []
    def fetch(ticker):
        calls.append(ticker)
        if len(calls) > 1:
            raise YFRateLimitError()
        return {"targetMeanPrice": 120, "currentPrice": 100}
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", fetch)
    first = news.get_analyst_snapshot.__wrapped__("TEST")
    clock[0] = 21601
    snapshot = news.get_analyst_snapshot.__wrapped__("TEST")
    assert snapshot["status"] == "stale" and not snapshot["ok"]
    assert snapshot["data"]["targetMeanPrice"] == 120
    assert snapshot["fetched_at"] == first["fetched_at"]
    result = attach_today_analyst_context(pd.DataFrame([{"티커": "TEST", "현재가": 100}]),
                                         get_analyst_snapshot=lambda _: snapshot)
    assert result.iloc[0]["애널목표상태"] == "stale"
    assert pd.isna(result.iloc[0]["애널목표Upside값"])
    assert build_today_analyst_upside_map(result) == {}


def test_failed_current_price_does_not_repeat_provider_chain(monkeypatch):
    prices.clear_latest_price_cache()
    calls = []
    monkeypatch.setattr(prices, "_fetch_price_uncached", lambda ticker: calls.append(ticker) or 0.0)
    try:
        for _ in range(10):
            assert prices.load_latest_price("TEST") == 0.0
        assert calls == ["TEST"]
        prices.clear_latest_price_cache()
        monkeypatch.setattr(prices, "_fetch_price_uncached", lambda _: 123.4)
        assert prices.load_latest_price("TEST") == 123.4
    finally:
        prices.clear_latest_price_cache()


def test_crumb_429_is_not_swallowed_or_retried_on_second_host(monkeypatch):
    calls = []
    monkeypatch.setattr(news, "_get_yahoo_crumb", lambda: "test")
    def failed(host, ticker, crumb):
        calls.append(host)
        raise HTTPError("https://example.test", 429, "limited", {}, None)
    monkeypatch.setattr(news, "_try_one_host", failed)
    with pytest.raises(HTTPError):
        news._fetch_yahoo_analyst_data("TEST")
    assert calls == ["query1"]


def test_info_is_shared_between_name_and_target_views(app_module, monkeypatch):
    app_module.lookup_yfinance_info.clear()
    news.get_yfinance_company_names.clear()
    calls = []
    class Ticker:
        @property
        def info(self):
            calls.append("info")
            return {"longName": "Full company", "targetMeanPrice": 120}
        def get_info(self):
            return self.info
    monkeypatch.setattr(news.yf, "Ticker", lambda *a, **kw: Ticker())
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", lambda _: {})
    try:
        assert app_module.lookup_yfinance_info("TEST_SHARED")["longName"] == "Full company"
        assert news.get_yfinance_company_names("TEST_SHARED") == ["Full company"]
        assert news.get_analyst_snapshot.__wrapped__("TEST_SHARED")["data"]["targetMeanPrice"] == 120
        assert calls == ["info"]
    finally:
        app_module.lookup_yfinance_info.clear()
        news.get_yfinance_company_names.clear()


def test_name_cache_does_not_keep_old_targets_available_for_a_day(monkeypatch):
    clock = [0.0]
    reader = YahooMetadataReader(clock=lambda: clock[0], min_interval=0)
    reader.read("info", "TEST", lambda _: {"longName": "Company", "targetMeanPrice": 120})
    monkeypatch.setattr(news, "yahoo_metadata_reader", reader)
    clock[0] = 21601
    def limited(_):
        raise YFRateLimitError()
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", limited)
    snapshot = news.get_analyst_snapshot.__wrapped__("TEST")
    assert snapshot["status"] == "stale" and not snapshot["ok"]


def test_outer_snapshot_cache_expires_from_original_fetch_not_last_view(monkeypatch):
    clock = [0.0]
    base = datetime(2026, 10, 14, tzinfo=timezone.utc)
    class ClockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = base + timedelta(seconds=clock[0])
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)
    monkeypatch.setattr(news, "datetime", ClockDatetime)
    monkeypatch.setattr(yahoo_metadata, "datetime", ClockDatetime)
    reader = YahooMetadataReader(clock=lambda: clock[0], min_interval=0)
    reader.read("info", "TEST_AGE", lambda _: {"targetMeanPrice": 120})
    monkeypatch.setattr(news, "yahoo_metadata_reader", reader)
    def direct(_):
        if clock[0] > 21600:
            raise YFRateLimitError()
        return {}
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", direct)
    news.get_analyst_snapshot.clear()
    try:
        clock[0] = 18000
        fresh = news.get_analyst_snapshot("TEST_AGE")
        assert fresh["status"] == "available"
        assert fresh["fetched_at"] == base.isoformat()
        clock[0] = 21601
        stale = news.get_analyst_snapshot("TEST_AGE")
        assert stale["status"] == "stale" and not stale["ok"]
        assert stale["fetched_at"] == base.isoformat()
    finally:
        news.get_analyst_snapshot.clear()


def test_lookup_failure_is_not_reported_as_absent_coverage(monkeypatch):
    def failed(_):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", failed)
    monkeypatch.setattr(news.yf, "Ticker", lambda *a, **kw: type("Empty", (), {
        "get_info": lambda self: {}, "get_analyst_price_targets": lambda self: {},
    })())
    snapshot = news.get_analyst_snapshot.__wrapped__("TEST_ERROR")
    assert snapshot["status"] == "lookup_error" and not snapshot["ok"]
    result = attach_today_analyst_context(pd.DataFrame([{"티커": "TEST", "현재가": 100}]),
                                         get_analyst_snapshot=lambda _: snapshot)
    assert result.iloc[0]["애널목표상태"] == "lookup_error"


def test_full_chart_name_avoids_info_and_repeated_name_calls(app_module, monkeypatch):
    app_module.lookup_yfinance_display_name.clear()
    calls = []
    monkeypatch.setattr(app_module, "fetch_yahoo_display_metadata", lambda ticker: calls.append(ticker) or {
        "longName": "Full company name", "shortName": "Full company",
    })
    monkeypatch.setattr(app_module, "lookup_yfinance_info", lambda _: pytest.fail("unnecessary info"))
    try:
        for _ in range(10):
            assert app_module.lookup_yfinance_display_name("TEST_NAME") == "Full company name"
        assert calls == ["TEST_NAME"]
    finally:
        app_module.lookup_yfinance_display_name.clear()


def test_short_chart_name_keeps_full_info_fallback(app_module, monkeypatch):
    app_module.lookup_yfinance_display_name.clear()
    monkeypatch.setattr(app_module, "fetch_yahoo_display_metadata", lambda _: {"shortName": "Taiwan Semiconductor Manufactur"})
    monkeypatch.setattr(app_module, "lookup_yfinance_info", lambda _: {"longName": "Taiwan Semiconductor Manufacturing Company Limited"})
    try:
        assert app_module.lookup_yfinance_display_name("TEST_SHORT") == "Taiwan Semiconductor Manufacturing Company"
    finally:
        app_module.lookup_yfinance_display_name.clear()
