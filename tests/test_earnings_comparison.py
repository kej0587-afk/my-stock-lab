"""Fiscal dates, accounting bases and missing data never become trade scores."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from yfinance.exceptions import YFRateLimitError

from stock_lab_core import earnings_comparison as module
from stock_lab_core.yahoo_metadata import YahooMetadataReader


NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def payload():
    return {
        "quoteType": {"symbol": "MSFT", "quoteType": "EQUITY"},
        "financialData": {"financialCurrency": "USD"},
        "earningsHistory": {"defaultMethodology": "gaap", "history": [
            {"quarter": {"fmt": "2026-09-30"}, "epsActual": {"raw": 4.0},
             "epsEstimate": {"raw": 3.5}, "currency": "USD"}]},
        "incomeStatementHistoryQuarterly": {"incomeStatementHistory": [
            {"endDate": {"fmt": "2026-09-30"}, "totalRevenue": {"raw": 100_000_000_000}}]},
        "earningsTrend": {"defaultMethodology": "gaap", "trend": [
            {"period": "0q", "endDate": "2026-12-31",
             "earningsEstimate": {"avg": {"raw": 5.0}, "low": {"raw": 4.0}, "high": {"raw": 6.0},
                                  "numberOfAnalysts": {"raw": 30}, "earningsCurrency": "USD"},
             "revenueEstimate": {"avg": {"raw": 110_000_000_000}, "revenueCurrency": "USD"}},
            {"period": "0y", "endDate": "2027-06-30", "earningsEstimate": {"avg": {"raw": 20.0}}}]},
    }


def snapshot(data=None, **kwargs):
    return dict(ok=True, status="available", stale=False, fetched_at=NOW.isoformat(),
                data=payload() if data is None else data, **kwargs)


def stored_revenue(**kwargs):
    row = dict(period="quarter", date="2026-09-30", start="2026-07-01", end="2026-09-30",
               is_single_quarter=True, is_cumulative_ytd=False, unit="USD", revenue=100_000_000_000,
               provenance={"revenue": {"method": "reported", "facts": [
                   dict(start="2026-07-01", end="2026-09-30", value=100_000_000_000, unit="USD",
                        tag="Revenues", filed="2026-10-28", accession="0000000000-26-000001", form="10-Q")]}})
    row.update(kwargs)
    return dict(source="sec_edgar", manual_score=0, final_score=0, metrics={"quarter_latest": row})


def build(snap=None, **kwargs):
    return module.build_earnings_comparison(snapshot() if snap is None else snap, now=NOW, **kwargs)


def test_same_fiscal_end_preserves_values_and_does_not_mix_forward_estimates():
    snap, meta = snapshot(), stored_revenue()
    before = deepcopy((snap, meta))
    result = build(snap, fin_meta=meta)
    eps, revenue = result["actuals"]
    assert eps["period_end"] == revenue["period_end"] == "2026-09-30"
    assert (eps["actual"], eps["estimate"], eps["difference"]) == (4.0, 3.5, 0.5)
    assert revenue["estimate"] is None and revenue["difference"] is None
    assert "SEC 공시 매출 일치" in revenue["status"]
    assert revenue["stored_filing"] == meta["metrics"]["quarter_latest"]
    assert [(r["period_end"], r["metric"]) for r in result["forecasts"]] == [("2026-12-31", "EPS"), ("2026-12-31", "매출")]
    assert result["forecasts"][0]["analyst_count"] == 30
    assert result["release_date"] == result["consensus_asof"] == "미제공"
    assert not result["comparison_used_for_scoring"]
    assert (snap, meta) == before
    revenue["stored_filing"]["revenue"] = 1
    assert meta == before[1]


@pytest.mark.parametrize("actual,estimate,difference", [(0, 0, 0), (-1, -2, 1), (-2, -1, -1), (None, 1, None),
    (2, None, None), (float('nan'), 1, None), (float('inf'), 1, None), (True, 1, None), (2, False, None),
    (1e308, -1e308, None)])
def test_zero_losses_missing_and_nonfinite_values(actual, estimate, difference):
    data = payload()
    data["earningsHistory"]["history"][0].update(epsActual={"raw": actual}, epsEstimate={"raw": estimate})
    row = build(snapshot(data))["actuals"][0]
    assert row["difference"] == difference
    assert row["actual"] is None or not isinstance(row["actual"], bool)


@pytest.mark.parametrize("basis,currency", [(None, "USD"), ({}, "USD"), ("gaap", None), ("gaap", "$")])
def test_missing_currency_or_methodology_cannot_produce_comparison(basis, currency):
    data = payload()
    data["earningsHistory"]["defaultMethodology"] = basis
    data["earningsHistory"]["history"][0]["currency"] = currency
    result = build(snapshot(data))
    assert result["actuals"][0]["difference"] is None
    # Trading/reporting currency must not fill missing historical EPS currency.
    if currency is None:
        assert result["actuals"][0]["currency"] is None


def test_non_gaap_history_is_labeled_and_never_claimed_as_gaap():
    data = payload()
    data["earningsHistory"]["defaultMethodology"] = "nongaap"
    row = build(snapshot(data))["actuals"][0]
    assert row["basis"] == "조정(Non-GAAP)"
    assert row["difference"] == 0.5
    assert "공식 EPS 대조 미완료" in row["status"]


def test_missing_or_annual_only_estimates_are_not_cached_as_quarterly_success():
    assert not module._has_data({"earningsTrend": {"trend": [
        {"period": "0y", "endDate": "2027-06-30", "earningsEstimate": {"avg": {"raw": 20}}}]}})
    assert not module._has_data({"earningsHistory": {"history": [{"epsActual": {"raw": 4}}]}})
    assert module._has_data({"earningsHistory": {"history": [
        {"quarter": "2026-09-30", "epsActual": {"raw": 0}}]}})


@pytest.mark.parametrize("status,ok,stale,age", [("rate_limited", True, False, 0), ("error", False, False, 0),
    ("available", True, True, 0), ("available", True, False, 901), ("available", True, False, -1)])
def test_failed_stale_or_future_observation_never_resurrects_positive_actuals(status, ok, stale, age):
    snap = snapshot()
    snap.update(status=status, ok=ok, stale=stale, fetched_at=(NOW-timedelta(seconds=age)).isoformat())
    result = build(snap)
    assert not result["actuals"] and not result["forecasts"]
    assert result["diagnostics"]


def test_rolling_estimate_for_released_period_does_not_backfill_old_consensus():
    data = payload()
    data["earningsTrend"]["trend"][0]["endDate"] = "2026-09-30"
    data["earningsTrend"]["trend"][0]["revenueEstimate"]["avg"] = {"raw": 999}
    result = build(snapshot(data))
    assert result["actuals"][0]["estimate"] == 3.5
    assert result["actuals"][1]["estimate"] is None
    assert result["forecasts"][1]["estimate"] == 999
    assert "발표 당시 값 아님" in result["forecasts"][1]["status"]


@pytest.mark.parametrize("key", ["earningsHistory", "earningsTrend", "incomeStatementHistoryQuarterly"])
def test_duplicate_periods_are_withheld_not_selected_by_order(key):
    data = payload()
    rows = data[key][{"earningsHistory": "history", "earningsTrend": "trend", "incomeStatementHistoryQuarterly": "incomeStatementHistory"}[key]]
    rows.append(deepcopy(rows[0]))
    result = build(snapshot(data))
    if key == "earningsTrend":
        assert not result["forecasts"]
    else:
        assert len(result["actuals"]) == 1


@pytest.mark.parametrize("date_value", ["2026-11014", "FY2027Q1", "0q", "2026-02-30", "2027-09-30",
    {"fmt": "2026-09-30", "raw": 1767139200}])
def test_invalid_mixed_or_future_period_cannot_become_actual(date_value):
    data = payload()
    data["earningsHistory"]["history"][0]["quarter"] = date_value
    result = build(snapshot(data))
    assert not any(row["metric"] == "EPS" for row in result["actuals"])


@pytest.mark.parametrize("changed,expected", [({"date": "2026-06-30"}, "동일 분기 저장 공시 없음"),
    ({"unit": "KRW"}, "대조 보류"), ({"is_single_quarter": False}, "대조 보류"),
    ({"is_cumulative_ytd": True}, "대조 보류"), ({"provenance": {}}, "대조 보류"),
    ({"revenue": 50}, "대조 보류"), ({"revenue": None}, "미확인")])
def test_official_revenue_match_requires_period_currency_and_single_quarter(changed, expected):
    result = build(fin_meta=stored_revenue(**changed))
    assert expected in result["actuals"][1]["status"]


def test_stored_score_refresh_is_only_an_evidence_warning():
    meta = stored_revenue(date="2026-06-30")
    result = build(fin_meta=meta)
    assert "갱신 확인 필요" in result["stored_financial_status"]
    assert meta["manual_score"] == meta["final_score"] == 0


@pytest.mark.parametrize("change", [{"start": "2025-01-01", "end": "2025-12-31"}, {"value": 999},
    {"tag": "Assets"}, {"filed": "2026-11-02"}, {"accession": ""}, {"form": []}])
def test_matching_revenue_alone_is_not_proof_of_matching_official_facts(change):
    meta = stored_revenue()
    fact = meta["metrics"]["quarter_latest"]["provenance"]["revenue"]["facts"][0]
    fact.update(change)
    assert "산출 근거 대조 보류" in build(fin_meta=meta)["actuals"][1]["status"]


def test_cumulative_revenue_difference_requires_adjacent_same_concept_facts():
    meta = stored_revenue()
    provenance = meta["metrics"]["quarter_latest"]["provenance"]["revenue"]
    current = dict(provenance["facts"][0], start="2026-01-01", value=300_000_000_000)
    previous = dict(current, end="2026-06-30", value=200_000_000_000)
    provenance.update(method="cumulative_difference", facts=[current, previous])
    assert "SEC 공시 매출 일치" in build(fin_meta=meta)["actuals"][1]["status"]
    previous["end"] = "2026-03-31"
    assert "산출 근거 대조 보류" in build(fin_meta=meta)["actuals"][1]["status"]


def test_consistent_official_revenue_can_disagree_with_vendor_value():
    meta = stored_revenue(revenue=50)
    meta["metrics"]["quarter_latest"]["provenance"]["revenue"]["facts"][0]["value"] = 50
    assert "매출 불일치" in build(fin_meta=meta)["actuals"][1]["status"]


def test_eps_vendor_quarter_label_does_not_force_false_statement_refresh():
    data, meta = payload(), stored_revenue()
    data["incomeStatementHistoryQuarterly"]["incomeStatementHistory"][0]["endDate"] = "2026-09-26"
    row = meta["metrics"]["quarter_latest"]
    row.update(date="2026-09-26", end="2026-09-26")
    result = build(snapshot(data), fin_meta=meta)
    assert "갱신 확인 필요" not in result["stored_financial_status"]
    assert "2026-09-26" in result["stored_financial_status"]


def test_malformed_trend_cannot_crash_valid_history_or_be_cached_as_success_alone():
    data = payload()
    data["earningsTrend"]["trend"][0]["period"] = []
    result = build(snapshot(data))
    assert result["actuals"][0]["actual"] == 4
    assert result["forecasts"] == []
    assert not module._has_data({"earningsTrend": data["earningsTrend"]})


def test_adapter_requests_modules_once_with_timeout_and_validates_issuer(monkeypatch):
    import yfinance as yf
    response = {"quoteSummary": {"result": [payload()]}}
    fetch = Mock(return_value=response)
    monkeypatch.setattr(yf, "Ticker", Mock(return_value=SimpleNamespace(_data=SimpleNamespace(get_raw_json=fetch))))
    assert module._fetch("MSFT") == payload()
    assert fetch.call_count == 1
    assert fetch.call_args.kwargs["timeout"] == 6
    assert fetch.call_args.kwargs["params"]["modules"] == module.MODULES
    response["quoteSummary"]["result"][0]["quoteType"]["symbol"] = "GOOGL"
    assert module._fetch("MSFT") == {}


def test_shared_cache_and_429_circuit_breaker_bound_all_earnings_calls(monkeypatch):
    reader = YahooMetadataReader(min_interval=0)
    monkeypatch.setattr(module, "yahoo_metadata_reader", reader)
    fetch = Mock(return_value=payload())
    monkeypatch.setattr(module, "_fetch", fetch)
    assert module.get_earnings_comparison_snapshot("msft")["ok"]
    assert module.get_earnings_comparison_snapshot("MSFT")["ok"]
    assert fetch.call_count == 1
    reader.read("info", "GOOGL", Mock(side_effect=YFRateLimitError()))
    assert module.get_earnings_comparison_snapshot("NVDA")["status"] == "rate_limited"
    assert fetch.call_count == 1


def test_failure_is_short_lived_and_does_not_replace_last_success(monkeypatch):
    tick = [0.0]
    reader = YahooMetadataReader(clock=lambda: tick[0], min_interval=0)
    monkeypatch.setattr(module, "yahoo_metadata_reader", reader)
    fetch = Mock(side_effect=[payload(), RuntimeError("private"), payload()])
    monkeypatch.setattr(module, "_fetch", fetch)
    module.get_earnings_comparison_snapshot("MSFT")
    tick[0] = 901
    old = module.get_earnings_comparison_snapshot("MSFT")
    assert old["stale"] and not old["ok"] and old["data"] == payload()
    assert not build(old)["actuals"]
    tick[0] = 902
    module.get_earnings_comparison_snapshot("MSFT")
    assert fetch.call_count == 2
    tick[0] = 962
    assert module.get_earnings_comparison_snapshot("MSFT")["ok"]
    assert fetch.call_count == 3


@pytest.mark.parametrize("ticker,is_etf", [("SOXL", True), ("", False), ("https://bad", False)])
def test_etf_or_invalid_symbol_never_performs_external_lookups(monkeypatch, ticker, is_etf):
    fetch = Mock()
    monkeypatch.setattr(module, "_fetch", fetch)
    assert not module.get_earnings_comparison_snapshot(ticker, is_etf=is_etf)["ok"]
    fetch.assert_not_called()


def test_presentation_uses_tables_and_explicit_limits():
    ui = SimpleNamespace(caption=Mock(), dataframe=Mock())
    module.render_earnings_comparison(ui, build())
    assert ui.dataframe.call_count == 2
    actual = ui.dataframe.call_args_list[0].args[0]
    assert actual.iloc[0]["분기 종료일"] == "2026-09-30"
    assert actual.iloc[0]["실제−예상"] == "0.50 USD"
    assert actual.iloc[1]["과거 예상(공급자)"] == "미제공"
    captions = str(ui.caption.call_args_list)
    assert "공식 실적 서프라이즈 확정이 아닙니다" in captions
    assert "산출시점 미제공" in captions
