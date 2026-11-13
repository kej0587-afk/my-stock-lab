import json

import pytest

from stock_lab_core.overnight_quote import extract_overnight_quote


def quote(symbol="UUP", price=29.35, stamp=100, prefix="overnight"):
    return {"symbol": symbol, prefix + "MarketPrice": {"raw": price},
            prefix + "MarketTime": {"raw": stamp}}


def page(rows):
    body = json.dumps({"quoteResponse": {"result": rows}})
    return '<script type="application/json" data-sveltekit-fetched>' + json.dumps({"body": body}) + '</script>'


def read(text):
    return extract_overnight_quote(text, "UUP", lambda stamp: stamp >= 100)


@pytest.mark.parametrize("rows", [
    [quote("TLT", 79.72)],
    [{"symbol": "UUP", "regularMarketPrice": {"raw": 29.35}}, quote("TLT", 79.72)],
    [{"symbol": "UUP", "children": [quote("TLT", 79.72)]}],
    [{"symbol": "UUP", "overnightMarketPrice": {"raw": 29.35}}, quote("TLT", 79.72)],
    [dict(quote(), symbol="UUPX")],
    [dict(quote(), symbol="")],
])
def test_nearby_symbol_price_or_timestamp_never_used(rows):
    assert read(page(rows)) == 0


def test_valid_symbol_can_be_far_from_its_own_price():
    target = {"symbol": "UUP", "description": "x" * 4000, **quote()}
    assert read(page([quote("TLT", 79.72, 120), target])) == 29.35


def test_latest_same_symbol_and_field_priority():
    assert read(page([quote(price=29), quote(price=30, stamp=101),
                      quote(price=31, stamp=102, prefix="day")])) == 30


def test_stale_quote_uses_own_fresh_day_quote():
    assert read(page([quote(stamp=99), quote(price=30, prefix="day")])) == 30


@pytest.mark.parametrize("price", [None, -1, 0, float("nan"), float("inf"), "bad"])
def test_invalid_price_is_missing(price):
    assert read(page([quote(price=price)])) == 0


def test_scalar_values_and_escaped_standalone_payload():
    raw = json.dumps({"symbol": "UUP", "dayMarketPrice": 29.35, "dayMarketTime": 100})
    assert read(raw) == 29.35
    assert read(raw.replace('"', '\\"')) == 29.35


def test_script_does_not_require_symbol_first_or_compact_spacing():
    target = quote()
    target["symbol"] = target.pop("symbol")
    assert read(page([target])) == 29.35


def test_missing_quote_continues_existing_fallback(monkeypatch):
    from stock_lab_core import prices
    prices.clear_latest_price_cache()
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: False)
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: False)
    monkeypatch.setattr(prices, "_is_live_priority_us_ticker", lambda ticker: False)
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda ticker: read(page([quote("TLT", 79.72)])))
    monkeypatch.setattr(prices, "_fetch_yahoo_quote", lambda ticker: 29.35)
    assert prices._fetch_us_realtime_price("UUP") == 29.35
