import io
import json
from urllib.parse import parse_qs, urlparse

import pytest

from stock_lab_core import prices
from stock_lab_core.performance import PerformanceTrace


def test_bulk_uses_one_area_with_comma_separated_symbols(monkeypatch):
    calls = []
    symbols = ["005930", "000660", "0167A0"]

    def request(req, timeout):
        query = parse_qs(urlparse(req.full_url).query)["query"][0]
        calls.append(query)
        assert timeout == 6
        assert query == "SERVICE_ITEM:" + ",".join(symbols)
        payload = {"result": {"areas": [{"name": "SERVICE_ITEM", "datas": [
            {"cd": symbol, "nv": 100 + i, "cr": i, "cv": i, "rf": "2"}
            for i, symbol in enumerate(symbols)
        ]}]}}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(prices.urllib.request, "urlopen", request)
    tickers = [symbol + ".KS" for symbol in symbols]
    with PerformanceTrace() as trace:
        quotes = prices._fetch_naver_quotes_bulk(tickers + [tickers[0]])
    assert list(quotes) == tickers
    assert quotes[tickers[0]]["change_pct"] == 0
    assert len(calls) == 1
    assert trace.report()["transport_events"] == {"naver_bulk.request": 1, "naver_bulk.response": 1}


@pytest.mark.parametrize("raw", [0, "0", "0.00", "0.0%"])
def test_zero_change_is_valid_and_does_not_trigger_fallback(monkeypatch, raw):
    quote = prices._extract_naver_quote_from_obj({"nv": 100, "cr": raw})
    assert quote == {"price": 100, "change_pct": 0}
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda _: {"005930.KS": quote})

    def forbidden(_):
        pytest.fail("A valid flat quote must not trigger a second provider request")

    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", forbidden)
    assert prices._load_latest_kr_quotes_batch_cached.__wrapped__(("005930.KS",)) == {"005930.KS": quote}


@pytest.mark.parametrize("raw", [None, "", "-", "NaN", "inf", True])
def test_missing_or_invalid_change_is_not_flat(raw):
    assert prices._extract_naver_quote_from_obj({"nv": 100, "cr": raw}) == {"price": 100}


def test_flat_fallback_replaces_previous_change(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda _: {"005930.KS": {"price": 100}})
    monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", lambda _: {"price": 101, "change_pct": 0})
    monkeypatch.setattr(prices, "_fetch_naver_basic_quote", lambda _: pytest.fail("Already has change"))
    assert prices._load_latest_kr_quotes_batch_cached.__wrapped__(("005930.KS",)) == {
        "005930.KS": {"price": 101, "change_pct": 0}
    }


def test_empty_bulk_does_not_repeat_identical_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda _: calls.append(1) or {})
    monkeypatch.setattr(prices.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Duplicate bulk call"))
    assert prices._fetch_naver_prices_bulk(["005930.KS"]) == {}
    assert calls == [1]
