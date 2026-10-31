"""Offline provider contracts. All portfolio values below are synthetic."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pytest
import requests

from stock_lab_core import etf_holdings as eh


NOW = datetime(2026, 10, 31, 3, tzinfo=timezone.utc)
ISHARES = '''iShares Semiconductor ETF
Fund Holdings as of,"Oct 30, 2026"
Inception Date,"Jul 10, 2001"
Ticker,Name,Asset Class,Weight (%),Notional Value
NVDA,NVIDIA,Equity,8.123456789,123
USD,USD CASH,Cash,-0.02,20
FUT,TECH CONTRACT,Futures,0,900
XTSLA,BLK CASH FUND,Money Market,0.04,30
'''
DIREXION = '''Direxion Daily Semiconductor Bull 3X ETF
SOXL

TradeDate,AccountTicker,StockTicker,SecurityDescription,HoldingsPercent
10/30/2026 12:00:00 AM,SOXL,NVDA,NVIDIA CORP,5.1234567891
10/30/2026 12:00:00 AM,SOXL,ICESEMI,ICESEMI SWAP ASSET LEG,146.1234567891
10/30/2026 12:00:00 AM,SOXL,,DREYFUS GOVT CASH MAN INS,9.1884450305
10/30/2026 12:00:00 AM,SOXL,,JP MORGAN 100 US TRSY CAPITAL 3163,8.2
'''
INVESCO = dict(cusip="QQQ", effectiveDate="2026-10-30", effectiveBusinessDate="2026-10-31",
               totalNumberOfHoldings=2, holdings=[
                   dict(ticker="NVDA", issuerName="NVIDIA", percentageOfTotalNetAssets=8.123456,
                        securityTypeName="Common Stock"),
                   dict(ticker="CASH", issuerName="US Dollar", percentageOfTotalNetAssets=None,
                        securityTypeName="Cash")])
FIRST_TRUST = '''<html><head><title>Cybersecurity ETF (CIBR)</title></head><body>
<span id="ContentPlaceHolder1_HoldingsListing_lblHoldingsTitle">Holdings of the Fund as of 10/30/2026</span>
<p>NAV as of 10/31/2026</p><table><tr><td>Index Holdings</td></tr></table>
<table class="fundSilverGrid"><tr><td>Security Name</td><td>Identifier</td><td>Weighting</td></tr>
<tr><td>CrowdStrike</td><td>CRWD</td><td>8.60%</td></tr>
<tr><td>Foreign Share</td><td>4704.JP</td><td>1.00%</td></tr>
<tr><td>US Dollar</td><td>$USD</td><td>0.20%</td></tr></table></body></html>'''


def kr_row(code="005930", name="Samsung", isin="KR7005930003", **extra):
    return dict(itemCode="069500", componentItemCode=code, componentName=name,
                componentIsinCode=isin, componentReutersCode=None, weight="34.123456",
                referenceDate="2026-10-30", componentCount="1", **extra)


def load(ticker, data, **kwargs):
    return eh.load_etf_holdings(ticker, fetch=lambda url, **kw: deepcopy(data), now=NOW, **kwargs)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    eh.clear_etf_holdings_cache()
    monkeypatch.setattr(eh.requests, "get", lambda *a, **kw: pytest.fail("Unexpected HTTP"))


def test_soxx_actual_equity_precision_cash_futures_and_date():
    result = load(" soxx ", ISHARES.encode("utf-8-sig"))
    assert result["status"] == "ok"
    assert result["as_of"] == "2026-10-30"
    assert result["scope"] == "all_reported" and result["source_url"] == eh.SOXX_URL
    assert result["rows"][0] == dict(name="NVIDIA", ticker="NVDA", weight_pct=8.123456789,
                                     kind="equity", reviewable=True, source_ticker="NVDA")
    assert [r["kind"] for r in result["rows"]] == ["equity", "cash", "futures", "cash"]
    assert result["rows"][1]["weight_pct"] == -0.02
    assert result["rows"][2]["weight_pct"] == 0
    assert not any(r["reviewable"] or r["ticker"] for r in result["rows"][1:])


def test_soxl_actual_positions_never_expand_swaps_or_normalize_weights():
    result = load("SOXL", DIREXION)
    assert result["status"] == "ok" and result["as_of"] == "2026-10-30"
    assert [r["kind"] for r in result["rows"]] == ["security", "swap", "cash", "fund"]
    assert result["rows"][0]["reviewable"]
    assert result["rows"][1]["weight_pct"] == 146.1234567891
    assert result["rows"][1]["source_ticker"] == "ICESEMI"
    assert not any(r["ticker"] or r["reviewable"] for r in result["rows"][1:])
    assert "not_daily_exposure" in result["reason"]
    assert result["holdings_basis"] == "provider_reported_mixed"


def test_soxl_failure_is_not_a_proxy_or_yahoo_portfolio():
    urls = []
    def fail(url, **kwargs):
        urls.append(url)
        raise requests.Timeout()
    result = eh.load_etf_holdings("SOXL", fetch=fail, now=NOW)
    assert result["status"] == "unavailable" and result["rows"] == []
    assert urls == [eh.SOXL_URL]


def test_qqq_json_missing_weight_is_not_zero_and_date_is_holdings_date():
    result = load("QQQ", json.dumps(INVESCO))
    assert result["as_of"] == "2026-10-30"
    assert result["rows"][0]["weight_pct"] == 8.123456
    assert result["rows"][0]["reviewable"]
    assert result["rows"][1]["weight_pct"] is None
    assert result["status"] == "partial" and "weights_unavailable" in result["reason"]
    assert result["scope"] == "all_reported"


def test_incomplete_qqq_list_is_never_called_all():
    data = deepcopy(INVESCO)
    data["totalNumberOfHoldings"] = 106
    result = load("QQQ", data)
    assert result["scope"] == "partial" and result["status"] == "partial"


def test_cibr_reads_fund_table_and_preserves_unmapped_foreign_identifier():
    result = load("CIBR", FIRST_TRUST)
    assert result["status"] == "ok" and result["as_of"] == "2026-10-30"
    assert result["rows"][0]["ticker"] == "CRWD"
    assert result["rows"][1]["source_ticker"] == "4704.JP"
    assert result["rows"][1]["ticker"] is None and not result["rows"][1]["reviewable"]
    assert result["rows"][2]["kind"] == "cash" and not result["rows"][2]["reviewable"]


@pytest.mark.parametrize("symbol", ["069500", "069500.KS", "069500.KQ", 69500])
def test_kr_verified_code_keeps_zero_without_guessing_exchange(symbol):
    calls = []
    def fetch(url, *, timeout):
        calls.append((url, timeout))
        return [kr_row()]
    result = eh.load_etf_holdings(symbol, fetch=fetch, now=NOW)
    assert result["status"] == "ok" and result["as_of"] == "2026-10-30"
    assert result["rows"][0]["ticker"] == "005930"
    assert result["rows"][0]["reviewable"]
    assert result["rows"][0]["exchange_unknown"] is True
    assert result["holdings_basis"] == "creation_basket"
    assert calls == [(eh.NAVER_URL.format(code="069500"), 8.0)]


def test_alphanumeric_kr_fund_and_holding_codes():
    record = kr_row("00A123", isin="KR700A123003")
    record["itemCode"] = "00B123"
    result = load("00b123.KS", [record])
    assert result["ticker"] == "00B123" and result["rows"][0]["ticker"] == "00A123"
    assert result["rows"][0]["reviewable"]


@pytest.mark.parametrize("suffix", ["KS", "KQ"])
def test_kr_exchange_suffix_requires_matching_source_ric(suffix):
    record = kr_row()
    record["componentReutersCode"] = "005930." + suffix
    catalog = pd.DataFrame([dict(code="005930", ticker="005930." + suffix)])
    result = load("069500", [record], kr_catalog=catalog)
    row = result["rows"][0]
    assert row["ticker"] == "005930." + suffix
    assert row["exchange_unknown"] is False and row["reviewable"]
    assert row["kind"] == "fund"


def test_kr_mismatched_ric_never_guesses_market():
    record = kr_row()
    record["componentReutersCode"] = "000660.KQ"
    row = load("069500", [record])["rows"][0]
    assert row["ticker"] == "005930" and row["exchange_unknown"] is True


def test_kr_source_mapping_only_no_names_to_codes():
    records = [kr_row(), kr_row("000660", name="SK", isin="KR7000660001"),
               kr_row(None, name="Samsung", isin="KR7005930003"),
               kr_row("005930", name="Mismatch", isin="KR7000660001"),
               kr_row("371460", name="Verified Fund", isin="KR7371460007")]
    for record in records:
        record["componentCount"] = "5"
    catalog = pd.DataFrame([dict(code="371460", ticker="371460.KS")])
    result = load("069500", records, kr_catalog=catalog)
    assert [r["ticker"] for r in result["rows"]] == ["005930", "000660", None, None, "371460"]
    assert result["rows"][-1]["kind"] == "fund" and result["rows"][-1]["reviewable"]


def test_kr_verified_us_ric_and_derivatives():
    records = [kr_row(None, "NVIDIA", "US67066G1040"),
               kr_row("005930", "Index TRS 1", "KR7005930003"),
               kr_row(None, "Cash", "KRD010010001")]
    records[0]["componentReutersCode"] = "NVDA.O"
    for r in records:
        r["componentCount"] = "3"
    result = load("069500", records)
    assert result["rows"][0]["ticker"] == "NVDA"
    assert result["rows"][1]["kind"] == "swap" and not result["rows"][1]["reviewable"]
    assert result["rows"][2]["kind"] == "cash" and not result["rows"][2]["reviewable"]


def test_kr_partial_count_and_missing_date():
    record = kr_row()
    record.update(componentCount="200", referenceDate=None)
    result = load("069500", [record])
    assert result["as_of"] is None and result["scope"] == "partial"
    assert result["status"] == "partial" and "as_of_unavailable" in result["reason"]


def test_catalog_fallback_never_uses_generated_time_or_matches_names():
    catalog = pd.DataFrame([dict(code="069500", ticker="069500.KS", top_1="Samsung",
                                 top_1_weight_pct="34.123456789", top_2="Index TRS 1",
                                 top_2_weight_pct=None, data_generated_at="2026-10-31 12:00:00")])
    original = catalog.copy(deep=True)
    def fail(url, **kwargs):
        raise requests.Timeout()
    result = eh.load_etf_holdings("069500", kr_catalog=catalog, fetch=fail, now=NOW)
    assert result["source"] == "KR catalog" and result["source_url"] is None
    assert result["scope"] == "top5" and result["status"] == "partial"
    assert result["as_of"] is None and result["observed_at"] == NOW.isoformat()
    assert not any(r["reviewable"] or r["ticker"] for r in result["rows"])
    assert result["rows"][1]["weight_pct"] is None
    pd.testing.assert_frame_equal(catalog, original)


def test_yahoo_top_ten_are_unverified_fractional_weights_no_fake_date():
    data = dict(quoteSummary=dict(result=[dict(quoteType=dict(quoteType="ETF", symbol="SMH"),
                    topHoldings=dict(maxAge=1, holdings=[dict(symbol="NVDA", holdingName="NVIDIA",
                                                            holdingPercent=dict(raw=0.123456789))]))]))
    result = load("SMH", data)
    assert result["scope"] == "top10" and result["as_of"] is None
    assert result["rows"][0]["weight_pct"] == pytest.approx(12.3456789)
    assert result["rows"][0]["source_ticker"] == "NVDA"
    assert not result["rows"][0]["reviewable"] and result["status"] == "partial"


@pytest.mark.parametrize("value", [None, "", "-", "NaN", "Infinity", float("inf"), True])
def test_missing_or_invalid_weights_are_none(value):
    record = kr_row()
    record["weight"] = value
    assert load("069500", [record])["rows"][0]["weight_pct"] is None


@pytest.mark.parametrize("ticker", ["", None, True, "../../QQQ", "069500.KS/", "QQQ?x=1"])
def test_invalid_tickers_do_not_fetch(ticker):
    result = eh.load_etf_holdings(ticker, fetch=lambda *a, **kw: pytest.fail("Unexpected fetch"), now=NOW)
    assert result["status"] == "unavailable" and result["reason"] == "invalid_ticker"


@pytest.mark.parametrize("ticker,data", [
    ("SOXX", "<html>Access denied</html>"),
    ("SOXL", DIREXION.replace(",SOXL,", ",SOXS,")),
    ("QQQ", dict(INVESCO, cusip="SPY")),
    ("CIBR", FIRST_TRUST.replace("(CIBR)", "(SPY)")),
    ("069500", [dict(kr_row(), itemCode="005930")]),
    ("069500", [kr_row(), dict(kr_row(), referenceDate="2026-10-29")]),
    ("SOXX", b"x" * (eh.MAX_BYTES + 1)),
    ("069500", [kr_row()] * (eh.MAX_ROWS + 1)),
], ids=["html", "wrong-soxl", "wrong-qqq", "wrong-cibr", "wrong-kr", "mixed-dates", "too-large", "too-many"])
def test_bad_responses_fail_closed(ticker, data):
    result = load(ticker, data)
    assert result["status"] == "unavailable" and not result["rows"]


def test_missing_date_old_date_and_future_date():
    unknown = load("SOXX", ISHARES.replace('Fund Holdings as of,"Oct 30, 2026"', 'NAV as of,"Oct 31, 2026"'))
    assert unknown["as_of"] is None and unknown["status"] == "partial"
    old = load("SOXX", ISHARES.replace("Oct 30, 2026", "Sep 30, 2026"))
    assert old["as_of"] == "2026-09-30" and old["status"] == "stale"
    future = load("SOXX", ISHARES.replace("Oct 30, 2026", "Nov 10, 2026"))
    assert future["status"] == "unavailable" and future["rows"] == []


def test_cache_success_failure_short_ttl_stale_limit_force_and_copies():
    clock, calls, failing = [0.0], [], [False]
    cache = eh.ETFHoldingsCache(success_ttl=10, failure_ttl=2, stale_ttl=30, clock=lambda: clock[0])
    def fetch(url, *, timeout):
        calls.append(url)
        if failing[0]:
            raise requests.Timeout()
        return ISHARES
    def run(**kw):
        return eh.load_etf_holdings("SOXX", fetch=fetch, now=NOW + timedelta(seconds=clock[0]), cache=cache, **kw)
    first = run()
    first["rows"][0]["name"] = "Mutated"
    assert run()["rows"][0]["name"] == "NVIDIA" and len(calls) == 1
    clock[0], failing[0] = 11, True
    stale = run()
    assert stale["status"] == "stale" and stale["observed_at"] == NOW.isoformat()
    assert stale["as_of"] == "2026-10-30" and "refresh_failed" in stale["reason"]
    assert stale["last_attempt_at"] != stale["observed_at"]
    clock[0] = 12
    assert run()["status"] == "stale" and len(calls) == 2
    failing[0] = False
    assert run(force_refresh=True)["status"] == "ok" and len(calls) == 3
    clock[0], failing[0] = 43, True
    assert run()["status"] == "unavailable" and len(calls) == 4
    clock[0] = 44
    assert run()["from_cache"] and len(calls) == 4
    clock[0], failing[0] = 46, False
    assert run()["status"] == "ok" and len(calls) == 5


def test_failure_is_per_ticker_bounded_and_injected_fetch_is_isolated():
    cache = eh.ETFHoldingsCache(max_entries=2)
    calls = []
    def fetch(url, **kw):
        calls.append(url)
        return ISHARES if url == eh.SOXX_URL else b"bad"
    eh.load_etf_holdings("QQQ", fetch=fetch, cache=cache, now=NOW)
    assert eh.load_etf_holdings("SOXX", fetch=fetch, cache=cache, now=NOW)["status"] == "ok"
    eh.load_etf_holdings("CIBR", fetch=fetch, cache=cache, now=NOW)
    assert len(cache.entries) == 2
    assert load("SOXX", "bad")["status"] == "unavailable"
    assert load("SOXX", ISHARES)["status"] == "ok"


def test_degraded_catalog_fallback_does_not_overwrite_verified_success():
    cache = eh.ETFHoldingsCache()
    state = [False]
    catalog = pd.DataFrame([dict(code="069500", top_1="Unknown", top_1_weight_pct=50)])
    def fetch(url, **kw):
        if state[0]:
            raise requests.Timeout()
        return [kr_row()]
    good = eh.load_etf_holdings("069500", fetch=fetch, cache=cache, now=NOW, kr_catalog=catalog)
    state[0] = True
    result = eh.load_etf_holdings("069500", fetch=fetch, cache=cache, now=NOW, kr_catalog=catalog, force_refresh=True)
    assert result["status"] == "stale" and result["source"] == good["source"]
    assert result["rows"][0]["ticker"] == "005930"


def test_http_timeout_size_redirect_and_close_contract(monkeypatch):
    state = dict(status=200, content=ISHARES.encode(), headers={}, closed=0, kwargs=None)
    class Response:
        @property
        def status_code(self):
            return state["status"]
        @property
        def headers(self):
            return state["headers"]
        def iter_content(self, chunk_size):
            yield state["content"]
        def close(self):
            state["closed"] += 1
    def get(url, **kw):
        state["kwargs"] = kw
        return Response()
    monkeypatch.setattr(eh.requests, "get", get)
    assert eh.load_etf_holdings("SOXX", now=NOW)["status"] == "ok"
    assert state["kwargs"]["timeout"] == (2.0, 3.0)
    assert state["kwargs"]["stream"] and not state["kwargs"]["allow_redirects"]
    state["status"] = 302
    assert eh.load_etf_holdings("QQQ", now=NOW)["reason"] == "http_302"
    state["status"], state["headers"] = 200, {"Content-Length": str(eh.MAX_BYTES + 1)}
    assert eh.load_etf_holdings("SOXL", now=NOW)["reason"] == "response_too_large"
    assert state["closed"] == 3


def test_slow_injected_fetch_is_rejected_after_return(monkeypatch):
    cache = eh.ETFHoldingsCache(clock=lambda: 0)
    ticks = iter([0, 9])
    monkeypatch.setattr(eh.time, "monotonic", lambda: next(ticks))
    assert load("SOXX", ISHARES, cache=cache)["reason"] == "collection_deadline"


@pytest.mark.parametrize("url,naver_referer", [
    (eh.SOXX_URL, False), (eh.QQQ_URL, False), (eh.CIBR_URL, False),
    (eh.SOXL_URL, False), (eh.NAVER_URL.format(code="069500"), True),
    ("https://stock.naver.com.example.org/holdings", False),
], ids=["ishares", "invesco", "first-trust", "direxion", "naver", "non-naver"])
def test_http_referer_is_sent_only_to_naver(monkeypatch, url, naver_referer):
    captured = {}
    class Response:
        status_code, headers = 200, {}
        def iter_content(self, chunk_size):
            yield b"[]"
        def close(self):
            captured["closed"] = True
    def get(request_url, **kwargs):
        assert request_url == url
        captured.update(kwargs)
        return Response()
    monkeypatch.setattr(eh.requests, "get", get)
    assert eh._http_fetch(url, timeout=8.0) == b"[]"
    assert captured["closed"]
    if naver_referer:
        assert captured["headers"]["Referer"] == "https://stock.naver.com/"
    else:
        assert "Referer" not in captured["headers"]
