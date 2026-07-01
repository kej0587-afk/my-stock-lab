import time

import pandas as pd

from stock_lab_core import prices
from stock_lab_core.prices import _extract_yahoo_overnight_price_from_html


def test_extract_yahoo_overnight_price_from_plain_json_html():
    ts = int(time.time())
    html = (
        '{"symbol":"MRVL","regularMarketPrice":{"raw":310.58},'
        f'"overnightMarketPrice":{{"raw":316.50}},'
        f'"overnightMarketTime":{{"raw":{ts}}}}}'
    )

    assert _extract_yahoo_overnight_price_from_html(html, "MRVL") == 316.50


def test_extract_yahoo_overnight_price_from_escaped_json_html():
    ts = int(time.time())
    html = (
        r'{\"symbol\":\"MRVL\",\"regularMarketPrice\":{\"raw\":310.58},'
        rf'\"overnightMarketPrice\":{{\"raw\":316.50}},'
        rf'\"overnightMarketTime\":{{\"raw\":{ts}}}}}'
    )

    assert _extract_yahoo_overnight_price_from_html(html, "MRVL") == 316.50


def test_extract_yahoo_overnight_price_ignores_stale_quote():
    stale_ts = int(time.time()) - (20 * 60 * 60)
    html = (
        '{"symbol":"MRVL","regularMarketPrice":{"raw":310.58},'
        f'"overnightMarketPrice":{{"raw":316.50}},'
        f'"overnightMarketTime":{{"raw":{stale_ts}}}}}'
    )

    assert _extract_yahoo_overnight_price_from_html(html, "MRVL") == 0.0


def test_ram_uses_dram_2x_proxy_price(monkeypatch):
    def fake_load_price_df(ticker, period):
        if ticker == "RAM":
            return pd.DataFrame({"Close": [100.0]})
        if ticker == "DRAM":
            return pd.DataFrame({"Close": [100.0]})
        return pd.DataFrame()

    monkeypatch.setattr(prices, "load_price_df", fake_load_price_df)

    assert prices._estimate_leveraged_target_etf_proxy_price("RAM", underlying_live_price=90.0) == 80.0


def test_non_proxy_ticker_does_not_estimate_leveraged_price():
    assert prices._estimate_leveraged_target_etf_proxy_price("SOXL", underlying_live_price=90.0) == 0.0


def test_extract_kis_quote_price_prefers_last_price():
    payload = {"output": {"last": "25.75", "base": "28.71"}}

    assert prices._extract_kis_quote_price(payload) == 25.75


def test_extract_kis_quote_price_accepts_extended_price_field():
    payload = {"output": {"last": "", "t_xprc": "25.80", "base": "28.71"}}

    assert prices._extract_kis_quote_price(payload) == 25.80


def test_extract_kis_quote_price_can_ignore_base_reference_price():
    payload = {"output": {"last": "", "t_xprc": "", "base": "28.71"}}

    assert prices._extract_kis_quote_price(payload, allow_base=False) == 0.0


def test_ram_kis_exchange_candidates_try_daytime_first():
    assert prices._kis_us_exchange_candidates("RAM")[:2] == ["BAA", "AMS"]


def test_extract_kis_intraday_price_from_output2():
    payload = {"output2": [{"xhms": "140101", "last": "25.75"}]}

    assert prices._extract_kis_intraday_price(payload) == 25.75


def test_us_price_prefers_yahoo_overnight_before_kis_regular(monkeypatch):
    calls = []

    def fake_kis_price(ticker, *, daytime_only=False, regular_only=False):
        calls.append(("kis", daytime_only, regular_only))
        if daytime_only:
            return 0.0
        if regular_only:
            return 310.58
        return 0.0

    monkeypatch.setattr(prices, "_fetch_kis_us_quote_price", fake_kis_price)
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda ticker: 316.50)

    assert prices._fetch_price_uncached("MRVL") == 316.50
    assert calls == [("kis", True, False)]


def test_ram_proxy_is_used_before_yfinance_fast_info(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_kis_us_quote_price", lambda ticker, **kwargs: 0.0)
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda ticker: 0.0)
    monkeypatch.setattr(prices, "_fetch_configured_us_quote_price", lambda ticker: 0.0)
    monkeypatch.setattr(prices, "_fetch_pyth_us_live_price", lambda ticker: 0.0)
    monkeypatch.setattr(prices, "_fetch_cboe_book_price", lambda ticker: 0.0)
    monkeypatch.setattr(prices, "_fetch_robinhood_us_quote", lambda ticker: 0.0)
    monkeypatch.setattr(prices, "_fetch_yahoo_quote", lambda ticker: 0.0)
    monkeypatch.setattr(prices, "_fetch_yf_download_price", lambda ticker, interval, prepost: 0.0)
    monkeypatch.setattr(prices, "_estimate_leveraged_target_etf_proxy_price", lambda ticker: 25.75)
    monkeypatch.setattr(prices, "_fetch_yf_fast_info_price", lambda ticker: 28.71)

    assert prices._fetch_price_uncached("RAM") == 25.75


def test_hon_ohlc_alignment_scales_split_like_gap(monkeypatch):
    df = pd.DataFrame({
        "Open": [460.0],
        "High": [468.0],
        "Low": [452.0],
        "Close": [464.42],
        "Volume": [1000],
    })

    monkeypatch.setattr(prices, "_fetch_price_uncached", lambda ticker: 232.21)

    fixed = prices._maybe_align_ohlcv_to_live_price("HON", df)

    assert round(float(fixed["Close"].iloc[-1]), 2) == 232.21
    assert round(float(fixed["Open"].iloc[-1]), 2) == 230.00


def test_non_alignment_ticker_keeps_ohlc(monkeypatch):
    df = pd.DataFrame({"Close": [464.42]})

    monkeypatch.setattr(prices, "_fetch_price_uncached", lambda ticker: 232.21)

    fixed = prices._maybe_align_ohlcv_to_live_price("AAPL", df)

    assert float(fixed["Close"].iloc[-1]) == 464.42


def test_parse_naver_realtime_quotes_extracts_price_and_change_pct():
    payload = '{"SERVICE_ITEM:000660":{"nv":"301,000","cv":"4,000","cr":"1.37","rf":"2"}}'

    quotes = prices._parse_naver_realtime_quotes(payload, ["000660.KS"])

    assert quotes["000660.KS"]["price"] == 301000.0
    assert quotes["000660.KS"]["change_pct"] == 1.37
    assert quotes["000660.KS"]["change_abs"] == 4000.0


def test_parse_naver_realtime_quotes_applies_falling_sign():
    payload = '{"SERVICE_ITEM:000660":{"nv":"301,000","cv":"4,000","cr":"1.37","rf":"5"}}'

    quotes = prices._parse_naver_realtime_quotes(payload, ["000660.KS"])

    assert quotes["000660.KS"]["price"] == 301000.0
    assert quotes["000660.KS"]["change_pct"] == -1.37
    assert quotes["000660.KS"]["change_abs"] == -4000.0


def test_latest_kr_quotes_falls_back_to_single_quote_when_bulk_has_no_change_pct(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda tickers: {"000660.KS": {"price": 301000.0}})
    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", lambda ticker: {})
    monkeypatch.setattr(
        prices,
        "_fetch_naver_basic_quote",
        lambda ticker: {"price": 301000.0, "change_pct": 1.37, "change_abs": 4000.0},
    )

    quotes = prices.load_latest_kr_quotes_batch(["000660.KS"])

    assert quotes["000660.KS"]["price"] == 301000.0
    assert quotes["000660.KS"]["change_pct"] == 1.37
    assert quotes["000660.KS"]["change_abs"] == 4000.0
