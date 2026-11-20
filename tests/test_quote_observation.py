"""Evidence must belong to the same selected scalar through provider/cache layers."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import pickle
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core import prices, report_build
from stock_lab_core.overnight_quote import extract_overnight_quote
from stock_lab_core.quote_observation import QuoteObservation, observed_price, quote_provenance
from stock_lab_core.signal_input_contract import price_input_identity


STAMP = int(datetime(2026, 11, 19, 21, tzinfo=timezone.utc).timestamp())
PRICE = 42.77000000000001


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def observed(value=PRICE, **kwargs):
    options = dict(ticker="SOXL", source="yahoo_chart", observed_at=STAMP,
                   session="post", timestamp_kind="trade")
    options.update(kwargs)
    return observed_price(value, **options)


def chart(closes, stamps=None, **meta):
    result = {"meta": {"symbol": "SOXL", **meta}, "indicators": {"quote": [{"close": closes}]}}
    if stamps is not None:
        result["timestamp"] = stamps
    return result


@pytest.fixture(autouse=True)
def isolated_quotes(monkeypatch):
    prices.clear_latest_price_cache()
    monkeypatch.setattr(prices, "_YAHOO_BLOCK_UNTIL", 0.0)
    monkeypatch.setattr(prices, "_is_recent_epoch", lambda ts: ts >= STAMP - 120)
    yield
    prices.clear_latest_price_cache()


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_float_and_pickle_contract(protocol):
    value = observed()
    assert isinstance(value, float)
    assert float(value).hex() == PRICE.hex()
    assert hash(value) == hash(PRICE)
    assert repr(value) == repr(PRICE)
    assert json.dumps(value) == json.dumps(PRICE)
    restored = pickle.loads(pickle.dumps(value, protocol=protocol))
    assert isinstance(restored, QuoteObservation)
    assert float(restored).hex() == PRICE.hex()
    assert quote_provenance(restored, " soxl ") == quote_provenance(value)


def test_deepcopy_isolated_dict_and_numeric_identity():
    value = observed()
    restored = deepcopy({"price": value})["price"]
    info = quote_provenance(restored)
    assert info == dict(source="yahoo_chart", symbol="SOXL", observed_at=iso(STAMP),
                        session="post", timestamp_kind="trade", price=PRICE)
    info["symbol"] = "QQQ"
    assert quote_provenance(value)["symbol"] == "SOXL"
    frame = pd.DataFrame({"Close": [40., 42.]}, index=pd.to_datetime(["2026-11-18", "2026-11-19"]))
    assert price_input_identity(frame, frame, ticker="SOXL", input_price=value) == price_input_identity(
        frame, frame, ticker="SOXL", input_price=PRICE)
    assert quote_provenance(float(value)) == quote_provenance(value + 1) == {}
    assert "stock_lab_core.quote_observation" in report_build._LOADED


def test_observation_helper_is_in_actual_precision_build_manifest(monkeypatch):
    from stock_lab_core import precision_build
    assert "quote_observation" in precision_build.MODULES
    monkeypatch.setattr(precision_build, "MODULES", ("quote_observation",))
    monkeypatch.setattr(report_build, "get_report_build_info", lambda _: {"sources": {}, "stale_modules": []})
    info = precision_build.precision_build_info()
    row = info['sources']['stock_lab_core.quote_observation']
    assert row['sha256'] == row['disk_sha256']
    assert not info['restart_required']


@pytest.mark.parametrize("value", [None, True, "42.77", PRICE, 0., -1., float("nan"), float("inf")])
def test_plain_or_invalid_values_have_no_provenance(value):
    assert quote_provenance(value, "SOXL") == {}


@pytest.mark.parametrize("value", [0., -1., float("nan"), float("inf"), -float("inf")])
def test_invalid_carrier_has_no_provenance(value):
    assert quote_provenance(observed(value)) == {}


def test_only_same_symbol_evidence_is_exposed():
    assert quote_provenance(observed(), "QQQ") == {}
    assert quote_provenance(observed(ticker="")) == {}
    assert quote_provenance(observed(source="")) == {}
    assert quote_provenance(observed(ticker=" soxl "), "SOXL")["price"] == PRICE


@pytest.mark.parametrize("stamp", [None, "", 0, -1, True, float("nan"), float("inf"),
                                 "bad", "2026-11-19", "2026-11-19T21:00:00", 10**100])
def test_missing_invalid_or_naive_time_is_never_filled(stamp):
    info = quote_provenance(observed(observed_at=stamp))
    assert info["price"] == PRICE
    assert "observed_at" not in info


@pytest.mark.parametrize("stamp", [STAMP, str(STAMP), iso(STAMP), "2026-11-20T06:00:00+09:00",
                                 datetime(2026, 11, 19, 21, tzinfo=timezone.utc)])
def test_supplier_time_normalizes_to_utc(stamp):
    assert quote_provenance(observed(observed_at=stamp))["observed_at"] == iso(STAMP)


@pytest.mark.parametrize("last", [None, 0, -1])
def test_candle_timestamp_belongs_to_selected_close_not_invalid_recent_last(last):
    result = chart([41., PRICE, last], [STAMP - 120, STAMP - 60, STAMP], marketState="POST")
    value = prices._last_candle_close(result, ticker="SOXL")
    assert float(value).hex() == PRICE.hex()
    assert quote_provenance(value) == dict(source="yahoo_chart", symbol="SOXL", price=PRICE,
                                         observed_at=iso(STAMP - 60), timestamp_kind="bar_start", session="unknown")


def test_stale_last_candle_retains_selected_earlier_timestamp():
    value = prices._last_candle_close(chart([PRICE, 99.], [STAMP, STAMP - 3600]))
    assert value == PRICE
    assert quote_provenance(value)["observed_at"] == iso(STAMP)


def test_candle_missing_timestamp_and_mismatched_symbol_do_not_relabel():
    value = prices._last_candle_close(chart([PRICE]), ticker="SOXL")
    assert "observed_at" not in quote_provenance(value)
    assert quote_provenance(value)["session"] == "unknown"
    wrong = prices._last_candle_close(chart([PRICE], [STAMP], symbol="QQQ"), ticker="SOXL")
    assert wrong == PRICE
    assert quote_provenance(wrong, "SOXL") == {}


def periods():
    return {"pre": {"start": STAMP - 120, "end": STAMP},
            "regular": {"start": STAMP, "end": STAMP + 120},
            "post": {"start": STAMP + 120, "end": STAMP + 240}}


@pytest.mark.parametrize("offset,session", [(-121, "unknown"), (-120, "pre"), (-1, "pre"),
                                          (0, "regular"), (119, "regular"), (120, "post"),
                                          (239, "post"), (240, "unknown")])
def test_chart_supplier_session_boundaries(monkeypatch, offset, session):
    monkeypatch.setattr(prices, "_is_recent_epoch", lambda stamp: True)
    value = prices._last_candle_close(chart([PRICE], [STAMP + offset], currentTradingPeriod=periods()))
    info = quote_provenance(value)
    assert value == PRICE
    assert info["session"] == session
    assert info["timestamp_kind"] == "bar_start"
    assert info["observed_at"] == iso(STAMP + offset)


@pytest.mark.parametrize("invalid", [None, {}, {"pre": None},
    {"regular": {"start": 0, "end": STAMP + 1}},
    {"regular": {"start": -1, "end": STAMP + 1}},
    {"regular": {"start": True, "end": STAMP + 1}},
    {"regular": {"start": STAMP, "end": STAMP}},
    {"regular": {"start": STAMP, "end": STAMP - 1}},
    {"regular": {"start": STAMP, "end": float("inf")}},
    {"regular": {"start": "bad", "end": STAMP + 1}},
    {**periods(), "pre": {"start": STAMP - 120, "end": STAMP + 1}},
])
def test_absent_malformed_overlapping_session_evidence_stays_unknown(invalid):
    value = prices._last_candle_close(chart([PRICE], [STAMP], currentTradingPeriod=invalid, marketState="REGULAR"))
    assert value == PRICE
    assert quote_provenance(value)["session"] == "unknown"


def test_selected_candle_session_uses_same_index():
    value = prices._last_candle_close(chart([PRICE, None], [STAMP - 1, STAMP], currentTradingPeriod=periods()))
    assert quote_provenance(value)["session"] == "pre"


@pytest.mark.parametrize("prefix,session", [("post", "post"), ("pre", "pre"), ("regular", "regular")])
def test_meta_session_and_time_belong_to_selected_price_field(prefix, session):
    meta = {"symbol": "SOXL", "regularMarketPrice": 40., "regularMarketTime": STAMP - 60,
            "postMarketPrice": 41., "postMarketTime": STAMP - 120,
            "preMarketPrice": 39., "preMarketTime": STAMP - 120,
            prefix + "MarketPrice": PRICE, prefix + "MarketTime": STAMP,
            "marketState": "CLOSED"}
    value = prices._meta_best_price(meta, ticker="SOXL")
    assert float(value).hex() == PRICE.hex()
    assert quote_provenance(value) == dict(source="yahoo_chart", symbol="SOXL", price=PRICE,
                                         observed_at=iso(STAMP), timestamp_kind="trade", session=session)


def test_meta_tie_keeps_original_post_priority():
    value = prices._meta_best_price({"symbol": "SOXL", "postMarketPrice": PRICE, "postMarketTime": STAMP,
                                    "preMarketPrice": 99., "preMarketTime": STAMP})
    assert value == PRICE
    assert quote_provenance(value)["session"] == "post"


@pytest.mark.parametrize("key,session", [("regularMarketPrice", "regular"),
                                       ("currentPrice", "unknown"), ("chartPreviousClose", "unknown")])
def test_meta_fallback_does_not_borrow_time_or_session(key, session):
    value = prices._meta_best_price({"symbol": "SOXL", key: PRICE, "postMarketTime": STAMP,
                                    "marketState": "POST"})
    assert value == PRICE
    assert "observed_at" not in quote_provenance(value)
    assert quote_provenance(value)["session"] == session


def test_meta_stale_regular_fallback_retains_actual_time():
    value = prices._meta_best_price({"symbol": "SOXL", "regularMarketPrice": PRICE,
                                    "regularMarketTime": STAMP - 3600, "postMarketTime": STAMP})
    assert value == PRICE
    assert quote_provenance(value)["observed_at"] == iso(STAMP - 3600)


@pytest.mark.parametrize("prefix", ["overnight", "day"])
def test_overnight_raw_fields_use_own_symbol_price_time_and_session(prefix):
    other = {"symbol": "QQQ", prefix + "MarketPrice": {"raw": 999}, prefix + "MarketTime": {"raw": STAMP + 1}}
    own = {"symbol": "SOXL", prefix + "MarketPrice": {"raw": PRICE}, prefix + "MarketTime": {"raw": STAMP}}
    value = extract_overnight_quote(json.dumps([own, other]), "SOXL", lambda stamp: True)
    assert float(value).hex() == PRICE.hex()
    assert quote_provenance(value) == dict(source="yahoo_overnight", symbol="SOXL", price=PRICE,
                                         observed_at=iso(STAMP), timestamp_kind="trade", session=prefix)
    assert quote_provenance(value, "QQQ") == {}


def test_overnight_priority_timestamp_and_tie_behavior_unchanged():
    rows = [{"symbol": "SOXL", "overnightMarketPrice": 1., "overnightMarketTime": STAMP - 1},
            {"symbol": "SOXL", "overnightMarketPrice": PRICE, "overnightMarketTime": STAMP},
            {"symbol": "SOXL", "overnightMarketPrice": 2., "overnightMarketTime": STAMP},
            {"symbol": "SOXL", "dayMarketPrice": 99., "dayMarketTime": STAMP + 1}]
    value = extract_overnight_quote(json.dumps(rows), "SOXL", lambda stamp: True)
    assert value == PRICE
    assert quote_provenance(value)["observed_at"] == iso(STAMP)
    assert quote_provenance(value)["session"] == "overnight"


def test_overnight_never_borrows_other_object_timestamp():
    rows = [{"symbol": "SOXL", "overnightMarketPrice": PRICE},
            {"symbol": "QQQ", "overnightMarketTime": STAMP}]
    assert extract_overnight_quote(json.dumps(rows), "SOXL", lambda stamp: True) == 0.


@pytest.mark.parametrize("symbol", ["SOXL", "QQQ", None])
def test_fetch_chart_propagates_request_symbol_without_overwriting_supplier(monkeypatch, symbol):
    result = chart([PRICE], [STAMP], symbol=symbol, currentTradingPeriod=periods())
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps({"chart": {"result": [result]}}).encode()
    request = Mock(return_value=response)
    monkeypatch.setattr(prices, "open_yahoo_chart", request)
    value, meta = prices._fetch_yahoo_chart("SOXL", "1m", "1d")
    assert value == PRICE
    assert meta == result["meta"]
    assert request.call_count == 1
    assert "interval=1m&range=1d&includePrePost=true" in request.call_args.args[0].full_url
    assert quote_provenance(value)["symbol"] == (symbol or "SOXL")
    assert quote_provenance(value)["session"] == "regular"
    assert bool(quote_provenance(value, "SOXL")) == (symbol != "QQQ")


@pytest.mark.parametrize("route,expected_calls", [("1m", ["1m"]), ("5m", ["1m", "5m"]),
                                                ("meta", ["1m", "5m"])])
def test_yahoo_selector_preserves_exact_selected_observation(monkeypatch, route, expected_calls):
    calls = []
    def fetch(ticker, interval, range_):
        calls.append(interval)
        meta = {"symbol": ticker, "preMarketPrice": PRICE if interval == "1m" else 99., "preMarketTime": STAMP}
        return (observed() if interval == route else 0.), meta
    monkeypatch.setattr(prices, "_fetch_yahoo_chart", fetch)
    value = prices._fetch_yahoo_quote("SOXL")
    assert value == PRICE
    assert quote_provenance(value)["observed_at"] == iso(STAMP)
    assert quote_provenance(value)["session"] == ("pre" if route == "meta" else "post")
    assert calls == expected_calls


@pytest.mark.parametrize("regular,after_hours", [(True, False), (False, True), (False, False)])
def test_realtime_scalar_and_streamlit_cache_keep_evidence(monkeypatch, regular, after_hours):
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: regular)
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: after_hours)
    selected = observed()
    primary = Mock(return_value=selected)
    other = Mock(side_effect=AssertionError("unselected provider called"))
    primary_name = "_fetch_yahoo_quote" if regular or after_hours else "_fetch_yahoo_overnight_page_price"
    other_name = "_fetch_yahoo_overnight_page_price" if regular or after_hours else "_fetch_yahoo_quote"
    monkeypatch.setattr(prices, primary_name, primary)
    monkeypatch.setattr(prices, other_name, other)
    with prices.realtime_quote_scope():
        assert prices._fetch_us_realtime_price("SOXL") is selected
        first = prices.load_latest_price(" soxl ")  # scoped success bypasses cache storage
        assert quote_provenance(first) == quote_provenance(selected)
    first = prices.load_latest_price("SOXL")
    cached = prices.load_latest_price(" soxl ")
    assert quote_provenance(cached) == quote_provenance(first) == quote_provenance(selected)
    assert primary.call_count == 2
    other.assert_not_called()


def test_batch_cache_keeps_each_symbols_own_evidence(monkeypatch):
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: True)
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: False)
    monkeypatch.setattr(prices, "_us_equity_market_closed_today", lambda: False)
    provider = Mock(side_effect=lambda ticker: observed(PRICE if ticker == "SOXL" else 100., ticker=ticker))
    monkeypatch.setattr(prices, "_fetch_yahoo_quote", provider)
    first = prices.load_latest_prices_batch(["SOXL", "QQQ"])
    cached = prices.load_latest_prices_batch(["SOXL", "QQQ"])
    for ticker in first:
        assert quote_provenance(cached[ticker], ticker) == quote_provenance(first[ticker], ticker)
        assert quote_provenance(cached[ticker])["symbol"] == ticker
    assert provider.call_count == 2


def test_uninstrumented_fallback_stays_unknown(monkeypatch):
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: True)
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: False)
    monkeypatch.setattr(prices, "_fetch_yahoo_quote", lambda ticker: 0.)
    fallback = Mock(return_value=PRICE)
    monkeypatch.setattr(prices, "_fetch_yf_download_price", fallback)
    value = prices._fetch_us_realtime_price("SOXL")
    assert value == PRICE
    assert quote_provenance(value) == {}
    fallback.assert_called_once_with("SOXL", interval="1m", prepost=True)
