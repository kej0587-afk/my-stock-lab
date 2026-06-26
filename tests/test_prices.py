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
