"""Equivalent ticker spelling must not multiply provider calls."""

from unittest.mock import Mock

import pytest

from stock_lab_core import prices


@pytest.mark.parametrize("ticker", ["RAM", "BITX", "MAGS", "0167A0.KS", "098120.KQ"])
def test_equivalent_ticker_spelling_shares_quote_cache(monkeypatch, ticker):
    provider = Mock(return_value=123.45)
    monkeypatch.setattr(prices, "_fetch_price_uncached", provider)
    prices._load_latest_price_cached.clear()
    try:
        for spelling in (ticker, ticker.lower(), " " + ticker + " "):
            assert prices.load_latest_price(spelling) == 123.45
        provider.assert_called_once_with(ticker)
    finally:
        prices._load_latest_price_cached.clear()


def test_different_venues_are_not_coalesced(monkeypatch):
    provider = Mock(side_effect=[100, 200])
    monkeypatch.setattr(prices, "_fetch_price_uncached", provider)
    prices._load_latest_price_cached.clear()
    try:
        assert prices.load_latest_price("abc.ks") == 100
        assert prices.load_latest_price("abc.kq") == 200
        assert provider.call_count == 2
    finally:
        prices._load_latest_price_cached.clear()
