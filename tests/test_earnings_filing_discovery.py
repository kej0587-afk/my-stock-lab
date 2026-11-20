"""Synthetic multi-sector releases; no real amounts, prices or decision changes."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
from unittest.mock import Mock

import pytest

from stock_lab_core import earnings_filing_sources as sources
from stock_lab_core.earnings_filing_evidence import (
    latest_dart_report, latest_sec_filing, parse_sec_release, sec_base, sec_release_link,
)
from stock_lab_core.earnings_collection import collect_report_earnings, _merge_discovered
from stock_lab_core.earnings_pipeline import build_earnings_pipeline
from stock_lab_core.earnings_reconciliation import reconcile_earnings
from stock_lab_core.report_calendar import earnings_calendar_lines

NOW = datetime.fromisoformat("2026-11-20T08:00:00+09:00")
ACCESSION = "0000001234-26-000123"
BASE = sec_base("1234", ACCESSION)
FILING = dict(accessionNumber=ACCESSION, primaryDocument="current.htm", filingDate="2026-11-19",
              acceptanceDateTime="2026-11-19T21:30:00Z", form="8-K", items="2.02, 9.01")


def release(name="Example Cyber", quarter="First Quarter Fiscal 2027", facts=None):
    facts = facts or """<p>Revenue was $3 billion compared to $2 billion last year.</p>
      <p>Net income was $400 million.</p><p>Capital expenditures were $100 million.</p>
      <p>Free cash flow was $200 million for the first quarter of fiscal 2027.</p>
      <p>For the second quarter of fiscal 2027, we expect revenue of $4 billion.</p>"""
    return (f"<html><h1>{name} Reports {quarter} Financial Results</h1>"
            f"<p>NEW YORK, November 19, 2026 -- {name} today announced financial results.</p>"
            f"{facts}</html>").encode()


def parsed(**kwargs):
    return parse_sec_release(release(**kwargs), "CYBR", "1234", FILING, BASE + "results.htm", NOW,
                             issuer_name=kwargs.get("name", "Example Cyber") + " Inc.")


@pytest.mark.parametrize("name,quarter,period", [
    ("Example Cyber", "First Quarter Fiscal 2027", "FY2027Q1"),
    ("Example Retail", "Third Quarter 2026", "2026Q3"),
    ("Example Health", "Fiscal 2027 Second Quarter", "FY2027Q2"),
    ("Example Bank", "Q3 2026", "2026Q3"),
    ("Example Cyber", "Fiscal First Quarter 2027", "FY2027Q1"),
])
def test_generic_release_period_dates_and_metrics(name, quarter, period):
    event, result = parsed(name=name, quarter=quarter)
    assert event["fiscal_period"] == result["fiscal_period"] == period
    assert result["release_date"] == "2026-11-19"
    assert result["release_at"] is None and result["release_precision"] == "date"
    assert result["provenance"]["accepted_at"] != result["release_at"]
    assert result["metrics"]["revenue"]["status"] == "reported"
    assert result["metrics"]["guidance"]["period_scope"] == "management_outlook"
    if period != "FY2027Q1":
        assert result["metrics"]["free_cash_flow"]["status"] == "missing"


@pytest.mark.parametrize("change,reason", [
    (lambda b: b.replace(b"November 19, 2026", b"October 19, 2026"), "release_filing_date_mismatch"),
    (lambda b: b.replace(b"First Quarter Fiscal 2027", b"Quarterly"), "explicit_fiscal_quarter_unavailable"),
    (lambda b: b.replace(b"Reports", b"Will Report"), "result_heading_unavailable"),
    (lambda b: b.replace(b"Example Cyber", b"Other Company"), "release_issuer_mismatch"),
])
def test_ambiguous_publication_is_not_promoted(change, reason):
    with pytest.raises(ValueError, match=reason):
        parse_sec_release(change(release()), "CYBR", "1234", FILING, BASE + "results.htm", NOW,
                          issuer_name="Example Cyber")


def test_outlook_annual_and_segment_numbers_never_become_quarter_actuals():
    _, result = parsed(facts="""<p>We expect free cash flow of $900 million.</p>
      <p>Full-year capital expenditures were $5 billion.</p>
      <p>AWS segment revenue was $3 billion.</p><p>Net income for fiscal 2026 was $2 billion.</p>""")
    assert all(result["metrics"][key]["status"] == "missing" for key in ("revenue", "profit", "capex", "free_cash_flow"))


def test_outlook_bullets_inherit_period_and_never_fill_missing_actuals():
    _, result = parsed(facts="""<h2>Financial Outlook</h2>
      <p>For the fiscal second quarter 2027, we expect:</p>
      <p>• Total revenue in the range of $3.530 billion to $3.550 billion.</p>
      <p>• Capital expenditures of $100 million.</p><p>• Free cash flow of $200 million.</p>""")
    assert all(result["metrics"][key]["status"] == "missing" for key in ("revenue", "capex", "free_cash_flow"))
    guidance = result["metrics"]["guidance"]
    assert guidance["status"] == "reported" and "second quarter 2027" in guidance["text"]
    assert "$3.530 billion to $3.550 billion" in guidance["text"]


def test_adjusted_accounting_definition_is_not_company_outlook():
    _, result = parsed(facts="""<h2>Financial Outlook</h2>
      <p>Example Cyber defines non-GAAP operating income as GAAP balances adjusted for
      (1) stock-based compensation and (2) an assumed provision for income taxes
      based on our long-term projected tax rate.</p>""")
    assert result["metrics"]["guidance"]["status"] == "missing"
    assert result["metrics"]["guidance"]["text"] == ""


def test_ceo_mention_of_guidance_does_not_cut_off_realized_results():
    _, result = parsed(facts="""<p>We are raising our full year guidance.</p>
      <p>Revenue was $3 billion.</p><p>Free cash flow was $200 million.</p>
      <h2>Financial Outlook</h2><p>For the fiscal second quarter 2027, we expect:</p>
      <p>• Total revenue of $4 billion.</p>""")
    assert result["metrics"]["revenue"]["status"] == "reported"
    assert result["metrics"]["free_cash_flow"]["status"] == "reported"
    assert result["metrics"]["guidance"]["status"] == "reported"


def submissions(**changes):
    return dict(cik="1234", name="Example Cyber Inc.", tickers=["CYBR"],
                filings={"recent": {key: [value] for key, value in {**FILING, **changes}.items()}})


def test_submissions_identity_cutoff_and_exhibit_boundary():
    assert latest_sec_filing(submissions(), "CYBR", "1234", NOW) == FILING
    with pytest.raises(ValueError, match="issuer_ticker"):
        latest_sec_filing(submissions(), "OTHER", "1234", NOW)
    with pytest.raises(ValueError, match="recent_earnings"):
        latest_sec_filing(submissions(), "CYBR", "1234", NOW - timedelta(days=1))
    primary = b'<table><tr><td>99.1</td><td><a href="results.htm">Results</a></td></tr></table>'
    assert sec_release_link(primary, BASE) == BASE + "results.htm"
    for bad in (b"../../other.htm", b"https://evil.example/result.htm", b"results.htm?x=1"):
        with pytest.raises(ValueError, match="exhibit"):
            sec_release_link(primary.replace(b"results.htm", bad), BASE)


def test_discovered_result_reaches_report_without_mutating_decisions():
    event, result = parsed()
    summary = [dict(ticker="CYBR", name="Example Cyber", verdict="blocked", score=7, shares=8)]
    context = dict(calendar_events=[event], earnings_results=[result])
    before = deepcopy((summary, context))
    reconciled = reconcile_earnings(context, NOW)[0]
    assert reconciled["result_confirmation"] == "official_result"
    assert reconciled["result_metrics"]["free_cash_flow"]["status"] == "reported"
    pipeline = build_earnings_pipeline(context, summary, now=NOW)
    assert pipeline["packets"][0]["stages"]["guidance"] == "확인"
    assert pipeline["highlights"][0]["ticker"] == "CYBR"
    assert pipeline["scoring_used"] is False and (summary, context) == before
    context["earnings_results"][0]["source_url"] = BASE + "wrong.htm"
    assert reconcile_earnings(context, NOW)[0]["result_confirmation"] != "official_result"


def test_latest_period_replaces_past_but_preserves_next_schedule():
    event, result = parsed()
    old = {**event, "fiscal_period": "FY2026Q4", "date": "2026-08-20"}
    future = {**event, "fiscal_period": "FY2027Q2", "date": "2027-02-19", "event_status": "scheduled"}
    events, results = _merge_discovered([old, future], [], dict(events=[event], results=[result]))
    assert events == [future, event] and results == [result]
    events, results = _merge_discovered([event], [result], dict(events=[old], results=[]))
    assert events == [event] and results == [result]
    call = {**event, "event_kind": "conference_call", "event_status": "scheduled",
            "conference_call_at": "2026-11-20T22:00:00Z"}
    events, _ = _merge_discovered([call], [], dict(events=[event], results=[result]))
    assert events[0]["conference_call_at"] == call["conference_call_at"]
    assert events[0]["date"] == event["date"]


def test_same_quarter_cached_evidence_is_retained_but_not_carried_to_new_period():
    event, result = parsed()
    old = deepcopy(result)
    old["metrics"]["capex"] = dict(status="reported", text="Capital expenditures were $10 million.", source_url=BASE + "results.htm")
    result["metrics"]["capex"] = dict(status="missing", text="")
    before = deepcopy(old)
    _, results = _merge_discovered([], [old], dict(events=[event], results=[result]))
    assert results[0]["metrics"]["capex"]["text"] == old["metrics"]["capex"]["text"]
    assert old == before
    old["fiscal_period"] = "FY2026Q4"
    _, results = _merge_discovered([], [old], dict(events=[event], results=[result]))
    assert results[0]["metrics"]["capex"]["status"] == "missing"


def dart_payload(**changes):
    return dict(status="000", list=[dict(corp_code="00123456", stock_code="123456", report_nm="분기보고서 (2026.09)",
                                        rcept_dt="20261116", rcept_no="20261116000001", **changes)])


@pytest.mark.parametrize("name", ["Example Korea", "", None])
def test_dart_company_name_never_uses_the_filing_title(name):
    event = latest_dart_report(dart_payload(corp_name=name), "00123456", "123456.KS", NOW)
    expected = name or "123456.KS"
    assert event["name"] == expected
    assert event["event"] == "분기보고서 (2026.09)"
    pipeline = build_earnings_pipeline(dict(calendar_events=[event]), now=NOW)
    assert pipeline["packets"][0]["name"] == expected


def test_dart_receipt_is_not_announcement_or_inferred_fiscal_quarter():
    event = latest_dart_report(dart_payload(), "00123456", "123456.KS", NOW)
    assert event["release_date_confirmed"] is False
    assert event["reporting_period_end_month"] == "2026-09"
    data = dict(calendar_events=[event])
    pipeline = build_earnings_pipeline(data, [dict(ticker="123456.KS", name="Example Korea")], now=NOW)
    assert pipeline["packets"][0]["date_basis"] == "공시 접수일·실적 발표일 미확인"
    assert pipeline["highlights"] == []
    assert pipeline["coverage"]["official"] == 0 and pipeline["coverage"]["filings"] == 1
    from stock_lab_core.report_earnings import compact_catalyst_lines, earnings_coverage_lines
    assert compact_catalyst_lines(pipeline, "KR", limit=None) == []
    assert "정기보고서 확인 1개(실적 발표일 별도)" in "\n".join(earnings_coverage_lines(pipeline))
    assert all(state == "미연결" for state in pipeline["packets"][0]["stages"].values())
    assert "공시 접수일 · 실적 발표일/회계분기 미확인" in "\n".join(earnings_calendar_lines(data, NOW, pipeline=pipeline))
    with pytest.raises(ValueError, match="dart_period"):
        latest_dart_report(dart_payload(), "wrong", "123456.KS", NOW)


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def iter_content(self, _):
        yield self.payload

    def close(self):
        pass


def test_cached_discovery_uses_one_directory_one_filing_chain_and_no_render_io(monkeypatch):
    sources.clear_cache()
    responses = [Response({"0": dict(ticker="CYBR", cik_str=1234)}), Response(submissions()),
                 Response(b'<table><tr><td>99.1</td><td><a href="results.htm">release</a></td></tr></table>'), Response(release())]
    get = Mock(side_effect=responses)
    first = sources.collect_filing_earnings(["CYBR"], NOW, sec_user_agent="Research contact@example.com", dart_api_key="", get=get)
    second = sources.collect_filing_earnings(["CYBR"], NOW + timedelta(seconds=10), sec_user_agent="Research contact@example.com", dart_api_key="", get=get)
    assert len(first["results"]) == 1
    assert first["results"] == second["results"] and get.call_count == 4
    assert second["sources"][0]["from_cache"] and not second["sources"][0]["attempted"]
    for _ in range(3):
        build_earnings_pipeline(dict(calendar_events=first["events"], earnings_results=first["results"]), now=NOW)
    assert get.call_count == 4


def test_absent_configuration_is_explicit_and_makes_no_requests():
    get = Mock()
    collected = sources.collect_filing_earnings(["CYBR", "123456.KS"], NOW, sec_user_agent="", dart_api_key="", get=get)
    assert collected["results"] == collected["events"] == []
    assert {row["reason"] for row in collected["sources"]} == {"sec_user_agent_missing", "dart_api_key_missing"}
    get.assert_not_called()


def test_cached_failure_is_not_a_new_external_attempt():
    sources.clear_cache()
    response = Response(b"")
    response.status_code = 403
    get = Mock(side_effect=[Response({"0": dict(ticker="CYBR", cik_str=1234)}), response])
    args = dict(sec_user_agent="Research contact@example.com", dart_api_key="", get=get)
    first = sources.collect_filing_earnings(["CYBR"], NOW, **args)["sources"][0]
    second = sources.collect_filing_earnings(["CYBR"], NOW + timedelta(seconds=1), **args)["sources"][0]
    assert first["attempted"] and first["reason"] == "http_403"
    assert second["from_cache"] and not second["attempted"] and get.call_count == 2


def test_future_cache_cannot_fill_a_historical_cutoff():
    sources.clear_cache()
    loader = Mock(return_value="future")
    sources._cached("test", NOW, loader)
    older, cached = sources._cached("test", NOW - timedelta(days=1), Mock(return_value="past"))
    assert older == "past" and cached is False


def test_actual_holdings_and_watchlist_not_fixed_issuers_drive_discovery(monkeypatch):
    from stock_lab_core import earnings_sources, earnings_result_sources
    monkeypatch.setattr(earnings_sources, "load_official_earnings", lambda *a: dict(events=[], sources=[]))
    monkeypatch.setattr(earnings_result_sources, "load_earnings_results", lambda *a: dict(results=[], sources=[]))
    loader = Mock(return_value=dict(events=[], results=[], sources=[]))
    monkeypatch.setattr(sources, "collect_filing_earnings", loader)
    rows = [dict(ticker="LLY"), dict(ticker="CYBR", name="Example Cyber", 보유수량=3),
            dict(ticker="SOXL", is_etf=True), dict(ticker="GOOG"), dict(ticker="GOOGL")]
    collected = collect_report_earnings(rows, dict(events=[]), NOW)
    assert set(loader.call_args.args[0]) == {"CYBR", "LLY", "GOOGL"}
    assert collected["earnings_collection_scope"]["excluded_non_issuers"] == ["SOXL"]


def test_exported_fund_type_is_not_a_company_even_without_etf_in_name():
    from stock_lab_core.earnings_discovery import issuer_catalog
    rows = [{"티커": "0025N0.KS", "종목명": "TDF 2045", "유형": "ETF"},
            {"티커": "123456.KS", "종목명": "Example Industries", "유형": "주식"}]
    catalog = issuer_catalog(rows)
    assert "0025N0.KS" not in catalog and catalog["123456.KS"]["registered"]


def test_dart_transport_snapshot_identity_does_not_supply_financial_values(monkeypatch):
    from stock_lab_core import dart_corporate_codes, dart_corporate_snapshot
    sources.clear_cache()
    live = dart_corporate_codes.CorporateCodeMap(diagnostic={"cause": "read_timeout"})
    snapshot = dart_corporate_codes.CorporateCodeMap({"123456": "00123456"}, diagnostic={
        "mapping_source": "official_snapshot", "snapshot_asof": "2026-11-20T00:00:00+00:00"})
    monkeypatch.setattr(dart_corporate_codes, "fetch_corporate_codes", Mock(return_value=live))
    fallback = Mock(return_value=snapshot)
    monkeypatch.setattr(dart_corporate_snapshot, "use_corporate_snapshot", fallback)
    get = Mock(return_value=Response(dart_payload()))
    collected = sources.collect_filing_earnings(["123456.KS"], NOW, sec_user_agent="", dart_api_key="test", get=get)
    fallback.assert_called_once_with(live, now=NOW)
    assert collected["events"][0]["release_date_confirmed"] is False
    assert collected["results"] == [] and get.call_count == 1
    assert collected["sources"][0]["mapping_source"] == "official_snapshot"


@pytest.mark.parametrize("reason,expected", [
    ("dart_corporate_mapping_read_timeout", "시간초과"),
    ("dart_corporate_mapping_api_error_020", "API 오류"),
    ("dart_no_reports", "정기보고서 없음"),
    ("dart_ticker_mapping_unavailable", "식별자 미연결"),
])
def test_dart_failure_stage_is_visible_without_credentials(reason, expected):
    from stock_lab_core.earnings_pipeline import _source_reason
    context = dict(earnings_sources=[dict(ticker="123456.KS", status="unavailable", reason=reason)])
    assert expected in _source_reason("123456.KS", context)


def test_cached_dart_identity_cannot_outlive_snapshot_validity():
    import hashlib
    sources.clear_cache()
    auth = hashlib.sha256(b"\0test").hexdigest()
    sources._cached(("dart_codes", auth), NOW, lambda: ({"123456": "00123456"}, {
        "snapshot_valid_until": (NOW + timedelta(minutes=1)).isoformat()}))
    get = Mock()
    collected = sources.collect_filing_earnings(["123456.KS"], NOW + timedelta(minutes=2),
                                              sec_user_agent="", dart_api_key="test", get=get)
    assert collected["events"] == [] and not collected["sources"][0]["attempted"]
    assert collected["sources"][0]["reason"] == "dart_corporate_mapping_snapshot_expired"
    get.assert_not_called()
