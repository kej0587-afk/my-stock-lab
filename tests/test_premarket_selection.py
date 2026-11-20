"""Fixed provider candidates for the Nov 21 pre-market routing correction.

The GOOGL supplier times below were observed in DISTINCT Nov 20 captures:
17:59:37 KST overnight in precision, 23:28:35 KST pre-market in later Today.
They and their GOOGL prices (273.02 overnight, 274.91 pre-market) are combined
only for a fixed selection replay, not represented as simultaneous live captures.
The SOXL/BITX prices and exact candidate timestamps are synthetic.
"""

import ast
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from stock_lab_core import prices
from stock_lab_core.overnight_quote import extract_overnight_quote
from stock_lab_core.quote_observation import quote_provenance
from tests.quote_observation_reference import before_provider_observation


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "6cdefff4"
TICKERS = ("GOOGL", "SOXL", "BITX")
OLD_AT = pd.Timestamp("2026-11-20T17:59:37+09:00")
PRE_AT = pd.Timestamp("2026-11-20T23:28:35+09:00")
NOW = pd.Timestamp("2026-11-20T23:29:00+09:00")
ROUTES = ("scalar", "cached_scalar", "uncached", "uncached_fallback", "batch", "batch_fallback")
SCALAR_PROVIDERS = (
    "_fetch_yahoo_quote", "_fetch_yahoo_overnight_page_price", "_fetch_yf_download_price",
    "_fetch_robinhood_us_quote", "_fetch_kis_us_quote_price", "_fetch_configured_us_quote_price",
    "_fetch_pyth_us_live_price", "_fetch_cboe_book_price", "_fetch_yahoo_regular_close_price",
    "_fetch_yf_fast_info_price", "_estimate_leveraged_target_etf_proxy_price",
)


def clock_at(monkeypatch, instant):
    fixed = pd.Timestamp(instant)
    assert fixed.tzinfo is not None
    real_timestamp = pd.Timestamp

    class FixedTimestamp:
        def __new__(cls, *args, **kwargs):
            return real_timestamp(*args, **kwargs)

        @classmethod
        def now(cls, tz=None):
            return fixed.tz_convert(tz) if tz else fixed.tz_convert("UTC").tz_localize(None)

    class PandasClock:
        Timestamp = FixedTimestamp

        def __getattr__(self, name):
            return getattr(pd, name)

    # Replace only prices' pandas reference, not pandas globally or other tests.
    monkeypatch.setattr(prices, "pd", PandasClock())
    monkeypatch.setattr(prices.time, "time", lambda: fixed.timestamp())
    return fixed


@pytest.fixture(autouse=True)
def isolate_price_cache():
    prices.clear_latest_price_cache()
    yield
    prices.clear_latest_price_cache()


@pytest.mark.parametrize("date,offset,utc_open,kst_open", [
    ("2026-01-15", "-05:00", "09:00", "18:00"),
    ("2026-07-02", "-04:00", "08:00", "17:00"),
])
@pytest.mark.parametrize("zone", ["America/New_York", "UTC", "Asia/Seoul"])
@pytest.mark.parametrize("at,pre,regular,post", [
    ("03:59:59", False, False, False), ("04:00:00", True, False, False),
    ("09:29:59", True, False, False), ("09:30:00", False, True, False),
    ("16:00:00", False, False, True), ("20:00:00", False, False, False),
])
def test_session_boundaries_in_summer_winter_utc_and_kst(monkeypatch, date, offset, utc_open, kst_open,
                                                       zone, at, pre, regular, post):
    opening = pd.Timestamp(f"{date}T04:00:00{offset}")
    assert opening.tz_convert("UTC").strftime("%H:%M") == utc_open
    assert opening.tz_convert("Asia/Seoul").strftime("%H:%M") == kst_open
    clock_at(monkeypatch, pd.Timestamp(f"{date}T{at}{offset}").tz_convert(zone))
    assert prices._us_equity_premarket_active() is pre
    assert prices._us_equity_regular_session_active() is regular
    assert prices._us_equity_after_hours_active() is post
    assert prices._us_equity_extended_session_active() is (pre or post)


@pytest.mark.parametrize("date,utc_open,kst_open", [
    ("2026-03-06", "09:00", "18:00"), ("2026-03-09", "08:00", "17:00"),
    ("2026-10-30", "08:00", "17:00"), ("2026-11-02", "09:00", "18:00"),
])
def test_dst_transition_trading_days(monkeypatch, date, utc_open, kst_open):
    opening = pd.Timestamp(f"{date} 04:00", tz="America/New_York")
    assert opening.tz_convert("UTC").strftime("%H:%M") == utc_open
    assert opening.tz_convert("Asia/Seoul").strftime("%H:%M") == kst_open
    clock_at(monkeypatch, opening - pd.Timedelta(seconds=1))
    assert not prices._us_equity_premarket_active()
    clock_at(monkeypatch, opening)
    assert prices._us_equity_premarket_active()


@pytest.mark.parametrize("date", [
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2026-11-21", "2026-11-22", "2026-03-08", "2026-11-01",
])
def test_existing_holidays_weekends_and_dst_sundays_are_closed(monkeypatch, date):
    clock_at(monkeypatch, pd.Timestamp(f"{date} 08:00", tz="America/New_York"))
    assert prices._us_equity_market_closed_today()
    assert not prices._us_equity_premarket_active()
    assert not prices._us_equity_extended_session_active()


def test_premarket_clock_failure_does_not_invent_open_session(monkeypatch):
    clock_at(monkeypatch, NOW)
    def failed_clock(*args, **kwargs):
        raise ValueError("clock unavailable")
    monkeypatch.setattr(prices.pd.Timestamp, "now", failed_clock)
    assert not prices._us_equity_premarket_active()
    assert not prices._us_equity_extended_session_active()


def candidates(ticker):
    # Same instrument, exact supplier fields; no separately fetched quote substitution.
    index = TICKERS.index(ticker)
    live_price, old_price = (274.91, 42.875, 31.625)[index], (273.02, 41.125, 30.25)[index]
    chart = {"meta": {"symbol": ticker, "currentTradingPeriod": {
        "pre": {"start": int(pd.Timestamp("2026-11-20T09:00:00Z").timestamp()),
                "end": int(pd.Timestamp("2026-11-20T14:30:00Z").timestamp())}}},
        "timestamp": [int(PRE_AT.timestamp())], "indicators": {"quote": [{"close": [live_price]}]}}
    live = prices._last_candle_close(chart, ticker=ticker)
    old = extract_overnight_quote(json.dumps({"symbol": ticker, "overnightMarketPrice": {"raw": old_price},
        "overnightMarketTime": {"raw": int(OLD_AT.timestamp())}}), ticker, prices._is_recent_epoch)
    return live, old


def install_providers(monkeypatch, winner, *, parsed=True):
    calls = []
    values = {ticker: candidates(ticker) for ticker in TICKERS} if parsed else {}

    def fetch(name):
        def invoke(ticker, **kwargs):
            label = name
            if name == "_fetch_yf_download_price":
                label += ":" + kwargs["interval"]
            if name == "_fetch_kis_us_quote_price":
                label += ":" + ("day" if kwargs.get("daytime_only") else "regular")
            calls.append((label, ticker))
            # Both candidates remain available even when the live source succeeds.
            if parsed and name == "_fetch_yahoo_overnight_page_price":
                return values[ticker][1]
            if name != winner:
                return 0.0
            if not parsed:
                return 123.125
            live, old = values[ticker]
            if name == "_fetch_yahoo_overnight_page_price":
                return old
            return float(live) if name == "_fetch_yf_download_price" else live
        return invoke

    for name in SCALAR_PROVIDERS:
        monkeypatch.setattr(prices, name, fetch(name))
    def batch_pyth(tickers):
        if tickers:
            calls.append(("pyth_batch", tuple(tickers)))
        return {}
    monkeypatch.setattr(prices, "_fetch_pyth_us_live_prices_batch", batch_pyth)
    monkeypatch.setattr(prices, "_accept_us_untimed_quote_price", lambda ticker, value: value)
    monkeypatch.setattr(prices.yf, "download", lambda *args, **kwargs: pd.DataFrame())
    return calls, values


def invoke_route(monkeypatch, route):
    if route.endswith("_fallback"):
        monkeypatch.setattr(prices, "_fetch_us_realtime_price", lambda ticker: 0.0)
    if route.startswith("batch"):
        return prices.load_latest_prices_batch(TICKERS)
    fn = {"scalar": prices._fetch_us_realtime_price, "cached_scalar": prices.load_latest_price,
          "uncached": prices._fetch_price_uncached, "uncached_fallback": prices._fetch_price_uncached}[route]
    return {ticker: fn(ticker) for ticker in TICKERS}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("winner", ["_fetch_yahoo_quote", "_fetch_yf_download_price", "_fetch_yahoo_overnight_page_price"])
def test_premarket_selects_live_before_old_overnight_and_keeps_fallback_evidence(monkeypatch, route, winner):
    clock_at(monkeypatch, NOW)
    assert prices._us_equity_premarket_active()
    assert prices._US_INTRADAY_QUOTE_MAX_AGE_SECONDS == 16 * 60 * 60
    assert prices._LATEST_PRICE_CACHE_TTL_SECONDS == 15
    assert prices._is_recent_epoch(OLD_AT.timestamp())  # Still accepted by unchanged 16h policy.
    calls, values = install_providers(monkeypatch, winner)
    result = invoke_route(monkeypatch, route)
    for ticker in TICKERS:
        own_calls = [name for name, symbol in calls if symbol == ticker]
        live, old = values[ticker]
        expected = old if winner == "_fetch_yahoo_overnight_page_price" else live
        assert float(result[ticker]).hex() == float(expected).hex()
        if winner == "_fetch_yf_download_price":
            assert quote_provenance(result[ticker], ticker) == {}  # Existing untimed fallback stays unknown.
            assert own_calls == ["_fetch_yahoo_quote", "_fetch_yf_download_price:1m"]
        else:
            assert quote_provenance(result[ticker], ticker) == quote_provenance(expected, ticker)
            assert quote_provenance(result[ticker], "SPY") == {}
            if winner == "_fetch_yahoo_quote":
                assert own_calls == ["_fetch_yahoo_quote"]
                assert quote_provenance(result[ticker])["session"] == "pre"
                assert quote_provenance(result[ticker])["timestamp_kind"] == "bar_start"
            else:
                prefix = ["_fetch_yahoo_quote", "_fetch_yf_download_price:1m"]
                if not route.endswith("_fallback"):
                    prefix += ["_fetch_yf_download_price:5m", "_fetch_robinhood_us_quote"]
                assert own_calls == prefix + ["_fetch_yahoo_overnight_page_price"]
                evidence = quote_provenance(result[ticker])
                assert evidence["session"] == "overnight"
                assert evidence["observed_at"] == OLD_AT.tz_convert("UTC").isoformat()
                assert (NOW - pd.Timestamp(evidence["observed_at"])).total_seconds() > 5 * 3600
    if winner != "_fetch_yahoo_overnight_page_price":
        assert all(name != "_fetch_yahoo_overnight_page_price" for name, _ in calls)
    if route in ("cached_scalar", "batch", "batch_fallback"):
        before = calls.copy()
        cached = invoke_route(monkeypatch, route)
        assert cached == result
        assert [quote_provenance(cached[t]) for t in TICKERS] == [quote_provenance(result[t]) for t in TICKERS]
        assert calls == before


@lru_cache
def historical_source():
    return subprocess.check_output(["git", "show", f"{BASELINE}:stock_lab_core/prices.py"],
                                   cwd=ROOT, encoding="utf-8")


def function_node(source, name):
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name)
    node.decorator_list = []
    return node


def historical_function(name):
    node = function_node(historical_source(), name)
    namespace = dict(vars(prices))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<before-premarket>", "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("name", ["_fetch_us_realtime_price", "_fetch_price_uncached", "load_latest_prices_batch"])
def test_same_fixed_candidates_old_route_selects_overnight_new_route_selects_pre(monkeypatch, name):
    # GOOGL observations came from separate captures; this controlled replay
    # supplies both together to isolate selection, without claiming live parity.
    clock_at(monkeypatch, NOW)
    calls, values = install_providers(monkeypatch, "_fetch_yahoo_quote")
    assert prices._is_recent_epoch(OLD_AT.timestamp())
    assert prices._is_recent_epoch(PRE_AT.timestamp())
    if name != "_fetch_us_realtime_price":
        monkeypatch.setattr(prices, "_fetch_us_realtime_price", lambda ticker: 0.0)
    before_fn = historical_function(name)
    after_fn = getattr(prices, name)
    def run(fn):
        return fn(TICKERS) if name == "load_latest_prices_batch" else {t: fn(t) for t in TICKERS}
    before = run(before_fn)
    assert calls == [("_fetch_yahoo_overnight_page_price", t) for t in TICKERS]
    calls.clear()
    after = run(after_fn)
    assert calls == [("_fetch_yahoo_quote", t) for t in TICKERS]
    assert before["GOOGL"] == 273.02 and after["GOOGL"] == 274.91
    for ticker in TICKERS:
        live, old = values[ticker]
        assert before[ticker] == old != live == after[ticker]
        assert quote_provenance(before[ticker], ticker) == quote_provenance(old, ticker)
        assert quote_provenance(after[ticker], ticker) == quote_provenance(live, ticker)
        assert quote_provenance(before[ticker])["observed_at"] == OLD_AT.tz_convert("UTC").isoformat()
        assert quote_provenance(after[ticker])["observed_at"] == PRE_AT.tz_convert("UTC").isoformat()


@pytest.mark.parametrize("instant", ["2026-11-20T15:00:00Z", "2026-11-20T22:00:00Z",
                                     "2026-11-20T08:00:00Z", "2026-11-21T14:00:00Z"])
@pytest.mark.parametrize("name", ["_fetch_us_realtime_price", "_fetch_price_uncached", "load_latest_prices_batch"])
@pytest.mark.parametrize("winner", ["_fetch_yahoo_quote", "_fetch_yf_download_price",
                                    "_fetch_yahoo_overnight_page_price", "_fetch_kis_us_quote_price", None])
def test_nonpremarket_prices_and_complete_provider_order_match_fixed_revision(monkeypatch, instant, name, winner):
    clock_at(monkeypatch, instant)
    assert not prices._us_equity_premarket_active()
    calls, _ = install_providers(monkeypatch, winner, parsed=False)
    if name != "_fetch_us_realtime_price":
        # Exercise these wrappers' own routing, independently of the first chain.
        monkeypatch.setattr(prices, "_fetch_us_realtime_price", lambda ticker: 0.0)
    argument = ("GOOGL", "RAM") if name == "load_latest_prices_batch" else "RAM"
    expected = historical_function(name)(argument)
    expected_calls = calls.copy()
    calls.clear()
    actual = getattr(prices, name)(argument)
    assert actual == expected
    assert calls == expected_calls


@pytest.mark.parametrize("name", ["_fetch_us_realtime_price", "_fetch_price_uncached", "load_latest_prices_batch"])
def test_only_the_reviewed_routing_assignment_changed(name):
    current = (ROOT / "stock_lab_core/prices.py").read_text(encoding="utf-8-sig")
    before = function_node(historical_source(), name)
    after = function_node(current, name)
    assignments = [node for node in ast.walk(after) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "after_hours_active" for target in node.targets)]
    assert len(assignments) == 1
    approved = ast.parse("after_hours_active = _us_equity_extended_session_active()").body[0]
    assert ast.dump(assignments[0]) == ast.dump(approved)
    assignments[0].value = ast.parse("_us_equity_after_hours_active()", mode="eval").body
    assert ast.dump(after) == ast.dump(before)


@pytest.mark.parametrize("replacement", ["_us_equity_extended_session_active(True)",
                                        "_us_equity_premarket_active()", "True"])
def test_historical_adapter_rejects_unapproved_routing_calls(replacement):
    current = (ROOT / "stock_lab_core/prices.py").read_text(encoding="utf-8-sig")
    node = function_node(current, "_fetch_us_realtime_price")
    assignment = next(n for n in ast.walk(node) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "after_hours_active" for t in n.targets))
    assignment.value = ast.parse(replacement, mode="eval").body
    with pytest.raises(AssertionError):
        before_provider_observation(deepcopy(node))
