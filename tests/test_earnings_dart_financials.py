"""Synthetic DART accounts, fiscal calendars and report-only integration."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pytest

from stock_lab_core import earnings_filing_sources as sources
from stock_lab_core.earnings_collection import _merge_discovered, collect_report_earnings
from stock_lab_core.earnings_dart_financials import parse_financials, report_spec, matched_financial_result
from stock_lab_core.earnings_filing_evidence import latest_dart_report
from stock_lab_core.earnings_pipeline import build_earnings_pipeline
from stock_lab_core.report_calendar import earnings_calendar_lines
from stock_lab_core.report_earnings import earnings_story_lines, compact_catalyst_lines
from stock_lab_core.report_event_watch import event_watch_rows
from tests.test_earnings_filing_discovery import NOW, Response, dart_payload

CORP = "00123456"
TICKER = "123456.KS"
COMPANY = dict(status="000", corp_code=CORP, stock_code="123456", acc_mt="12")


def event():
    return latest_dart_report(dart_payload(corp_name="Example Korea"), CORP, TICKER, NOW)


def row(account="ifrs-full_Revenue", name="매출액", current="100,000", cumulative="250,000", statement="IS", **changes):
    return dict(rcept_no="20261116000001", corp_code=CORP, bsns_year="2026", reprt_code="11014",
                sj_div=statement, account_id=account, account_nm=name, thstrm_amount=current,
                thstrm_add_amount=cumulative, currency="KRW", **changes)


def payload():
    return dict(status="000", list=[row(), row("dart_OperatingIncomeLoss", "영업이익", "(5,000)", "20,000"),
        row("ifrs-full_ProfitLoss", "당기순이익", "0", "10,000", "CIS"),
        row("ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "60,000", "", "CF"),
        row("ifrs-full_PurchaseOfPropertyPlantAndEquipment", "유형자산의 취득", "30,000", "", "CF")])


def pair(data=None, basis="CFS"):
    e = event()
    return parse_financials(data or payload(), e, report_spec(e, COMPANY, CORP), basis, NOW)


def test_quarter_income_and_ytd_cash_never_subtract_or_impute_fcf():
    original = payload(); before = deepcopy(original)
    e, actual = pair(original)
    values = actual["financial_values"]
    assert e["fiscal_period"] == "FY2026Q3" and not e["release_date_confirmed"]
    assert actual["release_date"] is None and actual["filing_date"] == "2026-11-16"
    assert values["revenue"]["quarter_value"] == "100000"
    assert values["revenue"]["cumulative_value"] == "250000"
    assert values["operating_profit"]["quarter_value"] == "-5000"
    assert values["net_income"]["quarter_value"] == "0"
    assert values["operating_cash_flow"]["quarter_value"] is None
    assert values["operating_cash_flow"]["cumulative_value"] == "60000"
    assert values["capex"]["status"] == values["free_cash_flow"]["status"] == "missing"
    assert values["tangible_purchases"]["cumulative_value"] == "30000"
    assert actual["metrics"]["guidance"]["status"] == "missing"
    assert original == before


@pytest.mark.parametrize("close,month,title,year,code,fiscal", [
    ("12", "2026-03", "분기", "2026", "11013", "FY2026Q1"),
    ("12", "2026-06", "반기", "2026", "11012", "FY2026Q2"),
    ("12", "2025-12", "사업", "2025", "11011", "FY2025 연간·4분기값 아님"),
    ("03", "2026-09", "반기", "2027", "11012", "FY2027Q2"),
    ("06", "2026-09", "분기", "2027", "11013", "FY2027Q1"),
])
def test_report_code_requires_official_fiscal_close_and_matching_payload(close, month, title, year, code, fiscal):
    e = {**event(), "reporting_period_end_month": month, "event": f"{title}보고서 ({month.replace('-', '.')})"}
    spec = report_spec(e, {**COMPANY, "acc_mt": close}, CORP)
    assert (spec["year"], spec["report_code"], spec["fiscal_period"]) == (year, code, fiscal)
    data = payload()
    for account in data["list"]:
        account.update(bsns_year=year, reprt_code=code)
    _, actual = parse_financials(data, e, spec, "CFS", NOW)
    if code == "11011":
        revenue = actual["metrics"]["revenue"]
        assert revenue["annual_value"] == "100000" and revenue["quarter_value"] is None
        assert revenue["cumulative_value"] is None


@pytest.mark.parametrize("changes", [dict(acc_mt=""), dict(acc_mt="13"), dict(acc_mt="11"),
                                    dict(corp_code="99999999"), dict(stock_code="999999"), dict(status="020")])
def test_unknown_calendar_or_issuer_never_fills_quarter(changes):
    with pytest.raises(ValueError):
        report_spec(event(), {**COMPANY, **changes}, CORP)


@pytest.mark.parametrize("key,value", [("corp_code", "99999999"), ("bsns_year", "2025"),
    ("reprt_code", "11012"), ("rcept_no", "20261117000002"), ("currency", "USD"), ("fs_div", "OFS")])
def test_mixed_identity_revision_currency_or_basis_is_rejected(key, value):
    data = payload(); data["list"][0][key] = value
    with pytest.raises(ValueError):
        pair(data)


@pytest.mark.parametrize("amount", ["", "-", "N/A", "1,00", "NaN", "1e6"])
def test_missing_quarter_is_not_replaced_by_cumulative(amount):
    data = payload(); data["list"][0]["thstrm_amount"] = amount
    _, actual = pair(data)
    metric = actual["metrics"]["revenue"]
    assert metric["quarter_value"] is None and metric["cumulative_value"] == "250000"


def test_provider_amount_type_contract_is_preserved():
    data = payload(); data["list"][0]["thstrm_amount"] = 0
    with pytest.raises(ValueError, match="invalid_row_value"):
        pair(data)
    data["list"][0]["thstrm_amount"] = "0"
    assert pair(data)[1]["metrics"]["revenue"]["quarter_value"] == "0"


def test_null_optional_fields_do_not_hide_other_reported_accounts():
    data = payload(); data["list"][0].update(currency=None, account_detail=None)
    _, actual = pair(data)
    assert actual["metrics"]["revenue"]["reason"] == "currency_unavailable"
    assert actual["financial_values"]["operating_profit"]["quarter_value"] == "-5000"
    data["list"][0]["currency"] = "KRW"
    assert pair(data)[1]["metrics"]["revenue"]["quarter_value"] == "100000"


def test_ambiguous_values_are_missing_and_parent_or_segment_profit_is_not_total():
    data = payload(); data["list"] += [row(current="90,000")]
    data["list"][2]["account_id"] = "ifrs-full_ProfitLossAttributableToOwnersOfParent"
    _, actual = pair(data)
    assert actual["metrics"]["revenue"]["status"] == "missing"
    assert actual["financial_values"]["net_income"]["status"] == "missing"
    assert actual["financial_values"]["operating_profit"]["quarter_value"] == "-5000"


def test_explicit_custom_accounts_and_duplicate_is_cis_agree_without_summing():
    data = payload(); data["list"] += [dict(data["list"][0], sj_div="CIS")]
    data["list"] += [row("-표준계정코드 미사용-", "잉여현금흐름", "0", "", "CF")]
    _, actual = pair(data, "OFS")
    assert actual["metrics"]["revenue"]["quarter_value"] == "100000"
    assert actual["metrics"]["free_cash_flow"]["cumulative_value"] == "0"
    assert "별도" in actual["metrics"]["revenue"]["text"]


def test_receipt_bound_join_rejects_mismatched_or_future_result():
    e, actual = pair()
    assert matched_financial_result(e, [actual], NOW) == actual
    for key, value in [("ticker", "999999.KS"), ("fiscal_period", "FY2026Q2"),
                       ("filing_date", "2026-11-17"), ("source_url", "https://example.com"),
                       ("checked_at", (NOW + timedelta(seconds=1)).isoformat())]:
        assert matched_financial_result(e, [{**actual, key: value}], NOW) is None
    assert matched_financial_result({**e, "filing_receipt": "20261117000002"}, [actual], NOW) is None
    assert matched_financial_result({**e, "filing_corp_code": "99999999"}, [actual], NOW) is None


def test_report_links_actuals_but_not_receipt_as_catalyst_and_preserves_inputs():
    e, actual = pair()
    context = dict(calendar_events=[e], earnings_results=[actual])
    holdings = [dict(ticker=TICKER, name="Example Korea", 보유수량=3, 현재가원값=100, 판정코드="blocked")]
    before = deepcopy((context, holdings))
    pipeline = build_earnings_pipeline(context, holdings, now=NOW)
    assert pipeline["highlights"] == [] and pipeline["coverage"]["official"] == 0
    assert pipeline["coverage"]["filings"] == 1 and not pipeline["scoring_used"]
    assert compact_catalyst_lines(pipeline, "KR") == []
    assert event_watch_rows(context, [], NOW, pipeline=pipeline) == []
    from stock_lab_core.report_market_connections import _evidence
    assert list(_evidence(context, pipeline, [], NOW)) == []
    summary = "\n".join(earnings_story_lines(pipeline))
    detail = "\n".join(earnings_calendar_lines(context, NOW, pipeline=pipeline))
    assert "분기(3개월) 100,000 KRW" in summary and "누적 250,000 KRW" in summary
    assert "한국 공시 실제 실적" in detail and "60,000 KRW" in detail
    assert "공시 접수일 2026-11-16 · 실적 발표일 미확인" in detail
    assert "누적·분기 역산 안 함" in detail and "전체 CAPEX 아님" in detail
    assert "공식 결과 발표 확인" not in detail
    from stock_lab_core.report_reading import compose_reading_report, AUDIT_TITLE
    rendered = compose_reading_report("# Report", context=context, news=[], summary_rows=holdings, now=NOW)
    reading = rendered.split("## " + AUDIT_TITLE)[0]
    korean = reading.split("## 한국 시황")[1].split("## 미국 시황")[0]
    assert "한국 공시 실제 실적" in korean and "분기(3개월) 100,000 KRW" in korean
    assert korean.count("한국 공시 실제 실적") == 1
    assert (context, holdings) == before


def test_unmatched_result_cannot_reuse_previously_reconciled_values():
    e, actual = pair()
    first = build_earnings_pipeline(dict(calendar_events=[e], earnings_results=[actual]), now=NOW)
    second = build_earnings_pipeline(dict(calendar_events=first["events"], earnings_results=[]), now=NOW)
    assert "financial_values" not in second["events"][0]
    assert earnings_story_lines(second) == []


def test_verified_announcement_and_receipt_of_same_quarter_both_survive():
    e, actual = pair()
    announcement = {**e, "source_kind": "verified_snapshot", "date": "2026-10-29", "event_kind": "results",
                    "event": "Example earnings", "financial_discovery": {}, "release_date_confirmed": True}
    merged, results = _merge_discovered([announcement], [], dict(events=[e], results=[actual]))
    pipeline = build_earnings_pipeline(dict(calendar_events=merged, earnings_results=results), now=NOW)
    assert len(pipeline["packets"]) == 2
    assert pipeline["coverage"]["official"] == pipeline["coverage"]["filings"] == 1
    assert next(p for p in pipeline["packets"] if p["event"]["source_kind"] == "verified_snapshot")["date"] == "2026-10-29"


def setup_codes(monkeypatch):
    from stock_lab_core import dart_corporate_codes, dart_corporate_snapshot
    sources.clear_cache()
    codes = dart_corporate_codes.CorporateCodeMap({"123456": CORP}, diagnostic={"mapping_source": "live"})
    monkeypatch.setattr(dart_corporate_codes, "fetch_corporate_codes", Mock(return_value=codes))
    monkeypatch.setattr(dart_corporate_snapshot, "use_corporate_snapshot", lambda data, **kw: data)


def test_collector_caches_accounts_and_rendering_does_not_query(monkeypatch):
    setup_codes(monkeypatch)
    get = Mock(side_effect=[Response(dart_payload()), Response(COMPANY), Response(payload())])
    args = dict(sec_user_agent="", dart_api_key="test-secret", get=get)
    first = sources.collect_filing_earnings([TICKER], NOW, **args)
    second = sources.collect_filing_earnings([TICKER], NOW + timedelta(seconds=1), **args)
    assert get.call_count == 3 and first["results"] == second["results"]
    assert second["sources"][0]["financial_from_cache"] and not second["sources"][0]["financial_attempted"]
    assert "test-secret" not in str(first)
    for _ in range(2):
        pipeline = build_earnings_pipeline(dict(calendar_events=first["events"], earnings_results=first["results"]), now=NOW)
        earnings_calendar_lines({}, NOW, pipeline=pipeline)
    assert get.call_count == 3


@pytest.mark.parametrize("api_status,expected_calls,connected", [("013", 4, True), ("020", 3, False), ("010", 3, False)])
def test_ofs_fallback_only_on_no_data_not_api_or_auth_failure(monkeypatch, api_status, expected_calls, connected):
    setup_codes(monkeypatch)
    get = Mock(side_effect=[Response(dart_payload()), Response(COMPANY), Response(dict(status=api_status)), Response(payload())])
    collected = sources.collect_filing_earnings([TICKER], NOW, sec_user_agent="", dart_api_key="test", get=get)
    assert get.call_count == expected_calls and bool(collected["results"]) == connected
    assert collected["events"] and not collected["events"][0]["release_date_confirmed"]
    if connected:
        assert collected["results"][0]["provenance"]["fs_div"] == "OFS"
    else:
        assert collected["sources"][0]["financial_reason"] == "dart_financial_api_error"


def test_filings_do_not_suppress_existing_ir_announcement_collection(monkeypatch):
    from stock_lab_core import earnings_sources, earnings_result_sources
    e, actual = pair()
    monkeypatch.setattr(sources, "collect_filing_earnings", Mock(return_value=dict(events=[e], results=[actual], sources=[])))
    ir = Mock(return_value=dict(events=[], sources=[]))
    monkeypatch.setattr(earnings_sources, "load_official_earnings", ir)
    monkeypatch.setattr(earnings_result_sources, "load_earnings_results", Mock(return_value=dict(results=[], sources=[])))
    collected = collect_report_earnings([dict(ticker=TICKER)], dict(events=[]), NOW)
    assert ir.call_args.args[0] == [TICKER]
    assert collected["earnings_results"] == [actual]


def test_financial_timeout_preserves_receipt_and_retries_after_failure_ttl(monkeypatch):
    import requests
    setup_codes(monkeypatch)
    get = Mock(side_effect=[Response(dart_payload()), Response(COMPANY), requests.Timeout(), Response(payload())])
    args = dict(sec_user_agent="", dart_api_key="test", get=get)
    first = sources.collect_filing_earnings([TICKER], NOW, **args)
    assert first["events"] and not first["results"]
    assert first["sources"][0]["financial_reason"] == "request_timeout"
    again = sources.collect_filing_earnings([TICKER], NOW + timedelta(seconds=1), **args)
    assert get.call_count == 3 and again["sources"][0]["financial_from_cache"]
    retried = sources.collect_filing_earnings([TICKER], NOW + timedelta(seconds=91), **args)
    assert get.call_count == 4 and retried["results"]


def test_financial_budget_exhaustion_preserves_verified_receipt(monkeypatch):
    setup_codes(monkeypatch)
    get = Mock(side_effect=[Response(dart_payload()), Response(COMPANY), Response(payload())])
    args = dict(sec_user_agent="", dart_api_key="test", get=get)
    first = sources.collect_filing_earnings([TICKER], NOW, **args)
    sources._CACHE.pop(next(key for key in sources._CACHE if key[0] == "dart_accounts"))
    monkeypatch.setattr(sources, "MAX_SECONDS", 0)
    second = sources.collect_filing_earnings([TICKER], NOW + timedelta(seconds=1), **args)
    assert second["events"][0]["filing_receipt"] == first["events"][0]["filing_receipt"]
    assert not second["results"] and get.call_count == 3
    assert second["sources"][0]["financial_reason"] == "collection_time_budget"


@pytest.mark.parametrize("cause,retry", [("connect_timeout", True), ("read_timeout", True),
                                       ("api_error", False), ("http_error", False)])
def test_directory_retries_transport_once_inside_original_budget(monkeypatch, cause, retry):
    from stock_lab_core import dart_corporate_codes
    setup_codes(monkeypatch)
    failed = dart_corporate_codes.CorporateCodeMap(diagnostic={"cause": cause})
    success = dart_corporate_codes.CorporateCodeMap({"123456": CORP}, diagnostic={"mapping_source": "live"})
    fetch = Mock(side_effect=[failed, success])
    monkeypatch.setattr(dart_corporate_codes, "fetch_corporate_codes", fetch)
    get = Mock(side_effect=[Response(dart_payload()), Response(COMPANY), Response(payload())])
    collected = sources.collect_filing_earnings([TICKER], NOW, sec_user_agent="", dart_api_key="test", get=get)
    assert fetch.call_count == (2 if retry else 1)
    assert bool(collected["results"]) == retry
    if retry:
        assert collected["sources"][0]["mapping_attempts"] == 2


def test_directory_retry_does_not_expand_time_budget(monkeypatch):
    from stock_lab_core import dart_corporate_codes
    setup_codes(monkeypatch)
    failed = dart_corporate_codes.CorporateCodeMap(diagnostic={"cause": "connect_timeout"})
    fetch = Mock(return_value=failed)
    monkeypatch.setattr(dart_corporate_codes, "fetch_corporate_codes", fetch)
    monkeypatch.setattr(sources, "MAX_SECONDS", 5)
    collected = sources.collect_filing_earnings([TICKER], NOW, sec_user_agent="", dart_api_key="test", get=Mock())
    assert fetch.call_count == 1 and not collected["events"]


def test_receipt_keyed_accounts_survive_filing_list_refresh_for_one_day(monkeypatch):
    # User-approved 2026-11-24: statements for one receipt are reused for a day;
    # the 10-minute filing list still refreshes and a new receipt is fetched anew.
    setup_codes(monkeypatch)
    get = Mock(side_effect=[Response(dart_payload()), Response(COMPANY), Response(payload()),
                            Response(dart_payload()), Response(dart_payload())])
    args = dict(sec_user_agent="", dart_api_key="test", get=get)
    first = sources.collect_filing_earnings([TICKER], NOW, **args)
    later = sources.collect_filing_earnings([TICKER], NOW + timedelta(minutes=11), **args)
    assert get.call_count == 4  # filing list refreshed; company (1 day) and accounts reused
    assert later["sources"][0]["financial_from_cache"] and later["results"] == first["results"]
    sources.collect_filing_earnings([TICKER], NOW + timedelta(hours=23, minutes=50), **args)
    assert get.call_count == 5  # still inside a day: only the filing list again
    assert sources.ACCOUNTS_TTL == 86400 and sources.CACHE_TTL == 600
