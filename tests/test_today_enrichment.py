from collections import Counter
import math

import pandas as pd
import pytest

from stock_lab_core.today_enrichment import (
    attach_today_analyst_context,
    build_today_analyst_upside_map,
)


@pytest.fixture(autouse=True)
def isolated_yahoo_transport(monkeypatch):
    monkeypatch.setattr("stock_lab_core.news.yahoo_session_kwargs", lambda: {})


def _snapshot(target=120.0, current=100.0, **extra):
    return {
        "ok": True,
        "data": {
            "targetMeanPrice": target,
            "currentPrice": current,
            "numberOfAnalystOpinions": 12,
        },
        **extra,
    }


def _never_fetch(ticker):
    raise AssertionError(f"Unexpected price fetch: {ticker}")


def test_displayed_row_price_wins_and_provenance_and_wording_survive():
    original = pd.DataFrame([{
        "티커": "MSFT", "유형": "개별주", "현재가": "$525.94",
        "📌후보등급": "A급", "🔥기술적 타점": "눌림대기",
        "최종읽기": "정밀확인", "실행메모": "눌림/종가 확인",
        "판정코드": "WAIT", "차트목표": 900.0,
    }], index=[17])
    original.attrs["basis"] = "summary"
    snapshot = _snapshot(
        578.82245, 525.18, source="Yahoo v10",
        asof="2026-10-05", endpoint="financialData", api_status=200,
    )
    snapshot["data"]["numberOfAnalystOpinions"] = 53
    pristine = original.copy(deep=True)

    result = attach_today_analyst_context(
        original, get_analyst_snapshot=lambda ticker: snapshot,
        load_latest_price=_never_fetch,
    )

    row = result.iloc[0]
    assert row["애널목표Upside값"] == pytest.approx((578.82245 / 525.94 - 1) * 100)
    assert row["애널목표Upside"] == "+10.1%"
    assert row["애널목표가"] == 578.82245
    assert row["애널목표가표시"] == "$578.82"
    assert row["애널목표상태"] == "available"
    assert row["애널목표출처"] == "Yahoo v10"
    assert row["애널목표기준일"] == "2026-10-05"
    assert row["애널참여수"] == 53
    assert row["애널가격기준"] == 525.94
    assert row["애널가격출처"] == "현재가"
    assert row["애널가격상태"] == "row_price"
    assert result.attrs["today_analyst_snapshots"]["MSFT"] == snapshot
    assert result.attrs["basis"] == "summary"
    pd.testing.assert_frame_equal(result[original.columns], pristine)
    pd.testing.assert_frame_equal(original, pristine)


def test_snapshot_price_mismatch_is_flagged_without_changing_denominator():
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "NVDA", "현재가": "$236.02"}]),
        get_analyst_snapshot=lambda ticker: _snapshot(328.71695, 238.9),
        load_latest_price=_never_fetch,
    )
    row = result.iloc[0]
    assert row["애널가격상태"] == "row_snapshot_mismatch"
    assert row["애널가격괴리pct"] == pytest.approx((236.02 / 238.9 - 1) * 100)
    assert row["애널목표Upside값"] == pytest.approx((328.71695 / 236.02 - 1) * 100)


@pytest.mark.parametrize("price_field", ["currentPrice", "regularMarketPrice"])
def test_snapshot_price_is_fallback_when_displayed_price_is_missing(price_field):
    snapshot = {"ok": True, "data": {"targetMeanPrice": 90, price_field: 100}}
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST", "현재가": "-"}]),
        get_analyst_snapshot=lambda ticker: snapshot, load_latest_price=_never_fetch,
    )
    row = result.iloc[0]
    assert row["애널목표Upside값"] == pytest.approx(-10)
    assert row["애널목표Upside"] == "-10.0%"
    assert row["애널가격출처"] == price_field
    assert row["애널가격상태"] == "snapshot_fallback"
    assert row["애널참여수"] != row["애널참여수"]


def test_duplicate_aliases_fetch_snapshot_and_price_once_even_with_duplicate_index():
    calls = Counter()

    def snapshot(ticker):
        calls[("snapshot", ticker)] += 1
        return _snapshot(120, None)

    def price(ticker):
        calls[("price", ticker)] += 1
        return 100

    source = pd.DataFrame({"티커": [" test ", "TEST", "탐색: TEST"]}, index=[8, 8, 2])
    result = attach_today_analyst_context(source, get_analyst_snapshot=snapshot, load_latest_price=price)

    assert calls == {("snapshot", "TEST"): 1, ("price", "TEST"): 1}
    assert result.index.tolist() == [8, 8, 2]
    assert result["애널목표Upside"].tolist() == ["+20.0%"] * 3
    assert result["애널가격상태"].tolist() == ["latest_price_fallback"] * 3
    assert len(set(result["애널목표조회시각"])) == 1
    upside_map = build_today_analyst_upside_map(result)
    assert upside_map["TEST"] == pytest.approx(20)
    assert upside_map["test"] == pytest.approx(20)
    assert upside_map["탐색: TEST"] == pytest.approx(20)


def test_failed_snapshot_is_cached_per_ticker_and_does_not_block_next_stock():
    calls = Counter()

    def snapshot(ticker):
        calls[ticker] += 1
        if ticker == "FAIL":
            raise RuntimeError("provider unavailable")
        return _snapshot()

    result = attach_today_analyst_context(
        pd.DataFrame({"티커": ["fail", "FAIL", "GOOD"], "현재가": [100] * 3}),
        get_analyst_snapshot=snapshot, load_latest_price=_never_fetch,
    )
    assert calls == {"FAIL": 1, "GOOD": 1}
    assert result["애널목표상태"].tolist() == ["lookup_error", "lookup_error", "available"]
    assert "RuntimeError: provider unavailable" in result.iloc[0]["애널목표사유"]
    assert math.isnan(result.iloc[0]["애널목표Upside값"])


def test_price_exception_is_cached_and_other_rows_remain_available():
    calls = Counter()

    def price(ticker):
        calls[ticker] += 1
        if ticker == "FAIL":
            raise TimeoutError("price timeout")
        return 100

    result = attach_today_analyst_context(
        pd.DataFrame({"티커": ["FAIL", "FAIL", "GOOD"]}),
        get_analyst_snapshot=lambda ticker: _snapshot(120, None), load_latest_price=price,
    )
    assert calls == {"FAIL": 1, "GOOD": 1}
    assert result["애널목표상태"].tolist() == ["no_price", "no_price", "available"]
    assert "TimeoutError" in result.iloc[0]["애널목표사유"]
    assert result.iloc[0]["애널목표가"] == 120


@pytest.mark.parametrize("row", [
    {"티커": "QQQ"},
    {"티커": "UNKNOWN", "유형": "ETF"},
    {"티커": "UNKNOWN", "유형": "펀드"},
    {"티커": "UNKNOWN", "유형": "ETN"},
    {"티커": "UNKNOWN", "is_etf": True},
    {"티커": "UNKNOWN", "asset_class": "us_etf_nasdaq"},
    {"티커": "0227L0"},
])
def test_etf_and_fund_exclusions_never_fetch_or_inherit_old_targets(row):
    row.update({"현재가": 100, "애널목표Upside": "+999.0%", "애널목표가": 1000})
    calls = []
    result = attach_today_analyst_context(
        pd.DataFrame([row]), get_analyst_snapshot=lambda ticker: calls.append(ticker),
        load_latest_price=_never_fetch,
    )
    assert calls == []
    assert result.iloc[0]["애널목표상태"] == "etf_excluded"
    assert result.iloc[0]["애널목표Upside"] == "-"
    assert math.isnan(result.iloc[0]["애널목표가"])


def test_provider_quote_type_excludes_an_unknown_etf():
    snapshot = _snapshot()
    snapshot["data"]["quoteType"] = "ETF"
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "NEW", "현재가": 100}]),
        get_analyst_snapshot=lambda ticker: snapshot, load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널목표상태"] == "etf_excluded"
    assert math.isnan(result.iloc[0]["애널목표가"])


def test_kr_provider_data_and_suffix_aliases_use_existing_contract():
    calls = []
    snapshot = {
        "ok": True, "source": "existing KR provider", "asof": "2026-10-05",
        "data": {"targetMeanPrice": "210,000", "numberOfAnalystOpinions": "18"},
    }
    result = attach_today_analyst_context(
        pd.DataFrame({"티커": ["005930", "005930.KS"], "현재가": ["₩200,000"] * 2}),
        get_analyst_snapshot=lambda ticker: calls.append(ticker) or snapshot,
        load_latest_price=_never_fetch,
    )
    assert calls == ["005930.KS"]
    assert result["애널목표Upside"].tolist() == ["+5.0%", "+5.0%"]
    assert result.iloc[0]["애널목표가표시"] == "₩210,000"
    assert result.iloc[0]["애널참여수"] == 18
    assert result.iloc[0]["애널목표출처"] == "existing KR provider"


def test_bare_kosdaq_alias_uses_the_explicit_kq_suffix_once():
    calls = []
    result = attach_today_analyst_context(
        pd.DataFrame({"티커": ["042700", "042700.kq"], "현재가": [100, 100]}),
        get_analyst_snapshot=lambda ticker: calls.append(ticker) or _snapshot(),
        load_latest_price=_never_fetch,
    )
    assert calls == ["042700.KQ"]
    assert result["애널조회티커"].tolist() == ["042700.KQ"] * 2


@pytest.mark.parametrize("target", [None, 0, -1, "nan", "inf", float("inf"), "N/A", "10%"])
def test_absent_or_invalid_targets_are_not_replaced_by_chart_or_extremes(target):
    snapshot = _snapshot(target)
    snapshot["data"].update({"targetHighPrice": 200, "targetLowPrice": 50})
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST", "현재가": 100, "차트목표": 120}]),
        get_analyst_snapshot=lambda ticker: snapshot, load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널목표상태"] == "no_target"
    assert result.iloc[0]["애널목표Upside"] == "-"
    assert math.isnan(result.iloc[0]["애널목표가"])


def test_median_is_explicit_consensus_fallback_and_preserves_data_metadata():
    snapshot = {
        "ok": True,
        "data": {
            "targetMeanPrice": 0, "targetMedianPrice": {"raw": 110},
            "currentPrice": 100, "provider": "consensus", "as_of": "2026-10-04",
        },
    }
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST"}]), get_analyst_snapshot=lambda ticker: snapshot,
        load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널목표종류"] == "targetMedianPrice"
    assert result.iloc[0]["애널목표Upside"] == "+10.0%"
    assert result.iloc[0]["애널목표출처"] == "consensus"
    assert result.iloc[0]["애널목표기준일"] == "2026-10-04"


def test_ok_without_target_is_no_target_and_failed_snapshot_is_not_trusted():
    snapshots = {
        "PRICEONLY": {"ok": True, "data": {"currentPrice": 100}},
        "FAILED": {"ok": False, "data": {"targetMeanPrice": 120}, "reason": "provider failed"},
    }
    result = attach_today_analyst_context(
        pd.DataFrame({"티커": list(snapshots), "현재가": [100, 100]}),
        get_analyst_snapshot=snapshots.__getitem__, load_latest_price=_never_fetch,
    )
    assert result["애널목표상태"].tolist() == ["no_target", "no_target"]
    assert result.iloc[1]["애널목표사유"] == "provider failed"


@pytest.mark.parametrize("snapshot", [None, [], {}, {"ok": True, "data": None}, {"data": []}])
def test_malformed_snapshot_is_reported(snapshot):
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST", "현재가": 100}]),
        get_analyst_snapshot=lambda ticker: snapshot, load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널목표상태"] == "invalid_snapshot"


@pytest.mark.parametrize("ticker", [None, pd.NA, float("nan"), "-", "None", "", "bad/ticker", "탐색: None", 0])
def test_invalid_tickers_are_not_fetched(ticker):
    calls = []
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": ticker}]),
        get_analyst_snapshot=lambda ticker: calls.append(ticker), load_latest_price=_never_fetch,
    )
    assert not calls
    assert result.iloc[0]["애널목표상태"] == "invalid_ticker"


def test_legacy_loader_does_not_invent_source_provider_or_consensus_asof():
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST", "현재가": 100}]),
        get_analyst_snapshot=lambda ticker: _snapshot(), load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널목표출처"] == "get_analyst_snapshot"
    assert result.iloc[0]["애널목표기준일"] == ""
    assert result.iloc[0]["애널목표조회시각"]


def test_zero_upside_is_numeric_and_duplicate_prices_do_not_share_an_ambiguous_map():
    result = attach_today_analyst_context(
        pd.DataFrame({"티커": ["TEST", "TEST"], "현재가": [100, 120]}),
        get_analyst_snapshot=lambda ticker: _snapshot(120), load_latest_price=_never_fetch,
    )
    assert result["애널목표Upside값"].tolist() == pytest.approx([20, 0])
    assert result.iloc[1]["애널목표Upside"] == "+0.0%"
    assert build_today_analyst_upside_map(result) == {}


def test_empty_and_missing_ticker_schema_are_safe():
    calls = []
    empty = attach_today_analyst_context(
        pd.DataFrame(), get_analyst_snapshot=lambda ticker: calls.append(ticker),
    )
    no_ticker = attach_today_analyst_context(
        pd.DataFrame([{"현재가": 100}]), get_analyst_snapshot=lambda ticker: calls.append(ticker),
    )
    assert empty.empty and "애널목표Upside값" in empty.columns
    assert no_ticker.iloc[0]["애널목표상태"] == "invalid_ticker"
    assert not calls


def test_custom_column_names_support_parent_integration():
    result = attach_today_analyst_context(
        pd.DataFrame([{"ticker": "TEST", "price": "USD100.00"}]),
        ticker_col="ticker", price_col="price",
        get_analyst_snapshot=lambda ticker: _snapshot(), load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널가격출처"] == "price"
    assert build_today_analyst_upside_map(result, ticker_col="ticker")["TEST"] == pytest.approx(20)


def test_numeric_kr_csv_code_restores_leading_zeroes():
    calls = []
    result = attach_today_analyst_context(
        pd.DataFrame({"티커": [5930.0, "005930.KS"], "현재가": [100, 100]}),
        get_analyst_snapshot=lambda ticker: calls.append(ticker) or _snapshot(),
        load_latest_price=_never_fetch,
    )
    assert calls == ["005930.KS"]
    assert result["애널조회티커"].tolist() == ["005930.KS"] * 2


def test_invalid_snapshot_preserves_failure_provenance():
    snapshot = {"ok": False, "data": None, "source": "provider", "asof": "2026-10-05", "api_status": 429}
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST"}]), get_analyst_snapshot=lambda ticker: snapshot,
    )
    assert result.iloc[0]["애널목표상태"] == "invalid_snapshot"
    assert result.iloc[0]["애널목표출처"] == "provider"
    assert result.attrs["today_analyst_snapshots"]["TEST"] == snapshot


_FNGUIDE_HTML = """
<html><head><meta charset="utf-8"></head><body>
<input id="cmp_cd" value="005930">
<h1 id="giName">삼성전자</h1><h2>005930</h2>
<div><h2>시세현황</h2><span class="date">[2026/10/01]</span>
<table><tr><th>52주 최고/최저</th><td>999,999 / 1</td></tr></table></div>
<div id="div6" class="ul_wrap">
<div class="topbar_lft"><h2>투자의견 컨센서스</h2><span class="date">[2026/10/02]</span></div>
<table><thead><tr><th>투자의견</th><th>목표주가</th><th>EPS</th><th>PER</th><th>추정기관수</th></tr></thead>
<tbody><tr><td>4.0</td><td>489,762</td><td>47,142</td><td>5.9</td><td>21</td></tr></tbody></table>
</div></body></html>
"""


def test_public_fnguide_parser_reads_consensus_and_its_own_date():
    from stock_lab_core.news import _parse_fnguide_kr_consensus

    result = _parse_fnguide_kr_consensus(_FNGUIDE_HTML.encode("utf-8"), "005930")
    assert result["ok"]
    assert result["data"] == {"targetMeanPrice": 489762, "numberOfAnalystOpinions": 21}
    assert result["asof"] == "2026-10-02"
    assert "recommendationMean" not in result["data"]
    assert "targetHighPrice" not in result["data"]


@pytest.mark.parametrize("html", [
    _FNGUIDE_HTML.replace("489,762", "-"),
    _FNGUIDE_HTML.replace("489,762", "0"),
    _FNGUIDE_HTML.replace("489,762", "nan"),
    _FNGUIDE_HTML.replace("<td>21</td>", "<td>0</td>"),
    _FNGUIDE_HTML.replace("목표주가", "최고 목표주가"),
    _FNGUIDE_HTML.replace("투자의견 컨센서스", "2020년 증권사 리포트"),
    _FNGUIDE_HTML.replace("</tbody>", "<tr><td>4</td><td>100</td><td>1</td><td>1</td><td>1</td></tr></tbody>"),
])
def test_public_consensus_parser_rejects_missing_targets_extremes_and_broker_reports(html):
    from stock_lab_core.news import _parse_fnguide_kr_consensus

    result = _parse_fnguide_kr_consensus(html, "005930")
    assert not result["ok"]
    assert not result["data"]


def test_public_consensus_parser_rejects_a_default_company_or_code_disagreement():
    from stock_lab_core.news import _parse_fnguide_kr_consensus

    assert not _parse_fnguide_kr_consensus(_FNGUIDE_HTML, "000660")["ok"]
    disagreement = _FNGUIDE_HTML.replace('<input id="cmp_cd" value="005930">', '<input id="cmp_cd" value="000660">')
    assert not _parse_fnguide_kr_consensus(disagreement, "000660")["ok"]


def test_public_consensus_without_a_date_does_not_use_another_section_date():
    from stock_lab_core.news import _parse_fnguide_kr_consensus

    html = _FNGUIDE_HTML.replace('<span class="date">[2026/10/02]</span>', "")
    assert _parse_fnguide_kr_consensus(html, "005930")["asof"] == ""


def test_public_provider_attaches_source_url_and_skips_known_etfs(monkeypatch):
    from stock_lab_core import news

    calls = []

    class Response:
        url = "https://wcomp.fnguide.com/CompanyInfo/Snapshot?cmp_cd=005930"
        content = _FNGUIDE_HTML.encode("utf-8")

        def raise_for_status(self):
            pass

    monkeypatch.setattr(news, "_HAS_REQUESTS", True)
    monkeypatch.setattr(news._requests, "get", lambda url, **kwargs: calls.append((url, kwargs)) or Response())
    result = news.fetch_fnguide_kr_consensus("005930")
    assert result["ok"]
    assert result["source"] == "FnGuide"
    assert result["source_url"] == Response.url
    assert result["asof"] == "2026-10-02"
    assert calls[0][1]["timeout"] == 8
    assert not news.fetch_fnguide_kr_consensus("069500.KS")["ok"]
    assert not news.fetch_fnguide_kr_consensus("MSFT")["ok"]
    assert len(calls) == 1


def test_public_provider_http_failure_and_login_redirect_are_isolated(monkeypatch):
    from stock_lab_core import news

    class Response:
        url = "https://wcomp.fnguide.com/Account/Login"
        content = _FNGUIDE_HTML.encode("utf-8")

        def raise_for_status(self):
            pass

    monkeypatch.setattr(news, "_HAS_REQUESTS", True)
    monkeypatch.setattr(news._requests, "get", lambda *args, **kwargs: Response())
    result = news.fetch_fnguide_kr_consensus("005930.KS")
    assert not result["ok"]
    assert not result["data"]

    def unavailable(*args, **kwargs):
        raise TimeoutError("public source timeout")

    monkeypatch.setattr(news._requests, "get", unavailable)
    assert "TimeoutError" in news.fetch_fnguide_kr_consensus("005930.KS")["reason"]


@pytest.fixture
def isolated_analyst_provider(monkeypatch):
    from stock_lab_core import news

    class EmptyTicker:
        def get_info(self):
            return {}

        def get_analyst_price_targets(self):
            return {}

    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", lambda ticker: {})
    monkeypatch.setattr(news.yf, "Ticker", lambda ticker: EmptyTicker())
    monkeypatch.setattr(news, "fetch_fnguide_kr_consensus", lambda ticker: {"ok": False, "data": {}, "reason": "No coverage"})
    return news


def test_yfinance_official_target_api_is_used_when_get_info_has_only_extremes(isolated_analyst_provider, monkeypatch):
    news = isolated_analyst_provider
    calls = Counter()

    class Ticker:
        def get_info(self):
            calls["info"] += 1
            return {"targetHighPrice": 150, "targetLowPrice": 80}

        def get_analyst_price_targets(self):
            calls["targets"] += 1
            return {"current": 100, "low": 80, "high": 150, "mean": 120, "median": 115}

    monkeypatch.setattr(news.yf, "Ticker", lambda ticker: Ticker())
    result = news.get_analyst_snapshot.__wrapped__("TEST")
    assert calls == {"info": 1, "targets": 1}
    assert result["data"]["targetMeanPrice"] == 120
    assert result["data"]["targetMedianPrice"] == 115
    assert result["data"]["currentPrice"] == 100
    assert result["source"] == "yfinance.get_analyst_price_targets"
    assert result["source_url"] == "https://finance.yahoo.com/quote/TEST/analysis/"
    assert result["asof"] == ""
    assert result["field_sources"]["targetMeanPrice"]["source"] == result["source"]


def test_yfinance_target_api_still_runs_after_get_info_raises(isolated_analyst_provider, monkeypatch):
    news = isolated_analyst_provider

    class Ticker:
        def get_info(self):
            raise RuntimeError("get_info unavailable")

        def get_analyst_price_targets(self):
            return {"current": 100, "mean": 120}

    monkeypatch.setattr(news.yf, "Ticker", lambda ticker: Ticker())
    result = news.get_analyst_snapshot.__wrapped__("TEST")
    assert result["status"] == "available"
    assert result["source"] == "yfinance.get_analyst_price_targets"
    assert result["provider_attempts"][1]["status"] == "error"


def test_valid_direct_target_does_not_fetch_yfinance_and_keeps_provenance(isolated_analyst_provider, monkeypatch):
    news = isolated_analyst_provider
    calls = []
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", lambda ticker: _snapshot()["data"])
    monkeypatch.setattr(news.yf, "Ticker", lambda ticker: calls.append(ticker))
    result = news.get_analyst_snapshot.__wrapped__("MSFT")
    assert result["status"] == "available"
    assert result["source"] == "Yahoo Finance financialData"
    assert not calls


def test_kr_consensus_fallback_provenance_and_count_belong_to_the_target(isolated_analyst_provider, monkeypatch):
    news = isolated_analyst_provider
    source_url = "https://wcomp.fnguide.com/CompanyInfo/Snapshot?cmp_cd=005930"
    calls = []

    class Ticker:
        def get_info(self):
            return {"currentPrice": 276000, "numberOfAnalystOpinions": 99}

        def get_analyst_price_targets(self):
            return {}

    monkeypatch.setattr(news.yf, "Ticker", lambda ticker: Ticker())
    monkeypatch.setattr(news, "fetch_fnguide_kr_consensus", lambda ticker: calls.append(ticker) or {
        "ok": True, "data": {"targetMeanPrice": 489762, "numberOfAnalystOpinions": 21},
        "source": "FnGuide", "source_url": source_url, "asof": "2026-10-02",
    })
    result = news.get_analyst_snapshot.__wrapped__("005930")
    assert calls == ["005930.KS"]
    assert result["source"] == "FnGuide"
    assert result["source_url"] == source_url
    assert result["asof"] == "2026-10-02"
    assert result["data"]["numberOfAnalystOpinions"] == 21
    assert result["field_sources"]["currentPrice"]["source"] == "yfinance.get_info"
    assert result["field_sources"]["numberOfAnalystOpinions"]["source"] == "FnGuide"
    enriched = attach_today_analyst_context(
        pd.DataFrame([{"티커": "005930.KS", "현재가": "₩276,000"}]),
        get_analyst_snapshot=lambda ticker: result, load_latest_price=_never_fetch,
    )
    assert enriched.iloc[0]["애널목표출처"] == "FnGuide"
    assert enriched.iloc[0]["애널목표출처URL"] == source_url
    assert enriched.iloc[0]["애널목표기준일"] == "2026-10-02"
    assert enriched.iloc[0]["애널목표조회시각"] == result["fetched_at"]
    assert enriched.attrs["today_analyst_snapshots"]["005930.KS"]["source_url"] == source_url


def test_uncovered_kr_stock_and_high_low_only_data_remain_no_target(isolated_analyst_provider, monkeypatch):
    news = isolated_analyst_provider
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", lambda ticker: {"targetHighPrice": 150, "targetLowPrice": 50})
    result = news.get_analyst_snapshot.__wrapped__("TEST")
    assert result["status"] == "no_target"
    assert result["data"]["targetMeanPrice"] is None
    kr = news.get_analyst_snapshot.__wrapped__("005930.KS")
    assert kr["status"] == "no_target"
    assert kr["data"]["targetMeanPrice"] is None


def test_known_etf_snapshot_skips_all_providers(isolated_analyst_provider, monkeypatch):
    news = isolated_analyst_provider
    calls = []
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", lambda ticker: calls.append(ticker))
    result = news.get_analyst_snapshot.__wrapped__("QQQ")
    assert result["status"] == "etf_excluded"
    assert result["ok"] is False
    assert not calls


def test_provider_quote_type_fund_never_falls_back_to_a_consensus_target(isolated_analyst_provider, monkeypatch):
    news = isolated_analyst_provider
    calls = []

    class Ticker:
        def get_info(self):
            return {"quoteType": "MUTUALFUND", "currentPrice": 100}

        def get_analyst_price_targets(self):
            calls.append("targets")
            return {"mean": 120}

    monkeypatch.setattr(news.yf, "Ticker", lambda ticker: Ticker())
    result = news.get_analyst_snapshot.__wrapped__("TEST")
    assert result["status"] == "etf_excluded"
    assert result["data"]["targetMeanPrice"] is None
    assert not calls


def test_target_provenance_overrides_a_price_source_date_and_url():
    snapshot = _snapshot(source="price provider", source_url="https://example.test/price", asof="2026-10-06")
    snapshot["field_sources"] = {
        "targetMeanPrice": {"source": "consensus provider", "source_url": "https://example.test/consensus", "asof": "2026-10-02"},
        "currentPrice": {"source": "price provider", "asof": "2026-10-06"},
    }
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST", "현재가": 100}]),
        get_analyst_snapshot=lambda ticker: snapshot, load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널목표출처"] == "consensus provider"
    assert result.iloc[0]["애널목표출처URL"] == "https://example.test/consensus"
    assert result.iloc[0]["애널목표기준일"] == "2026-10-02"
    snapshot["field_sources"]["targetMeanPrice"]["asof"] = ""
    result = attach_today_analyst_context(
        pd.DataFrame([{"티커": "TEST", "현재가": 100}]),
        get_analyst_snapshot=lambda ticker: snapshot, load_latest_price=_never_fetch,
    )
    assert result.iloc[0]["애널목표기준일"] == ""
