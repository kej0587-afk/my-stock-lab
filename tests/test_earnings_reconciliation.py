"""Fiscal-period/source/session boundaries, not investment performance tests."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from stock_lab_core.earnings_reconciliation import reconcile_earnings
from stock_lab_core.report_calendar import earnings_calendar_lines

NOW = datetime.fromisoformat("2026-10-29T11:00:00+09:00")
SOURCE = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm"


def event(**changes):
    return dict(dict(ticker="GOOGL", event="Alphabet earnings", fiscal_period="2026Q3", market="US",
                     timezone="America/New_York", date="2026-10-28", event_kind="scheduled_release",
                     event_status="elapsed_unconfirmed", status="elapsed_unconfirmed",
                     source_url="https://abc.xyz/investor/schedule", conference_call_at="2026-10-28T16:30:00-04:00"), **changes)


def result(**changes):
    # Deliberately synthetic figures; values must come from the collector, not the renderer.
    return dict(dict(ticker="GOOGL", fiscal_period="2026Q3", status="official_result", release_date="2026-10-28",
                     release_at="2026-10-28", release_precision="date", checked_at="2026-10-29T10:59:00+09:00",
                     source_url=SOURCE, metrics={
                         "revenue": {"status": "available", "text": "Revenue: USD 100 (current quarter)", "source_url": SOURCE},
                         "profit": {"status": "available", "text": "GAAP EPS 2; adjusted EPS 3", "source_url": SOURCE},
                         "capex": {"status": "available", "text": "CAPEX: USD 50", "source_url": SOURCE},
                         "free_cash_flow": {"status": "available", "text": "FCF: USD -10", "source_url": SOURCE},
                         "guidance": {"status": "deferred", "text": "콜에서 전망 안내 예정", "source_url": SOURCE},
                     }), **changes)


def article(title="Alphabet Q3 2026 earnings beat estimates", **changes):
    return dict(dict(title=title, publisher="CNBC", market="US", published_at="2026-10-28T17:30:00-04:00",
                     link="https://www.cnbc.com/fixture-earnings"), **changes)


def context(**changes):
    return dict(dict(calendar_events=[event()], earnings_results=[result()]), **changes)


def test_official_result_promotes_elapsed_schedule_and_keeps_six_dimensions_separate():
    data = context()
    before = deepcopy(data)
    row, = reconcile_earnings(data, NOW)
    assert row["event_status"] == "released" and row["result_confirmation"] == "official_result"
    assert row["scheduled_event_kind"] == "scheduled_release"
    assert row["schedule_source_url"] == before["calendar_events"][0]["source_url"]
    assert row["next_schedule_status"] == "unconfirmed"
    assert row["result_metrics"]["free_cash_flow"]["text"] == "FCF: USD -10"
    assert row["result_metrics"]["guidance"]["status"] == "deferred"
    assert row["result_metrics"]["price_reaction"]["status"] == "missing"
    assert data == before
    again = reconcile_earnings(dict(data, calendar_events=[row]), NOW)
    assert again == [row]
    rendered = "\n".join(earnings_calendar_lines(data, NOW))
    assert "결과 미확인" not in rendered
    for label in ("공식 결과 발표 확인", "매출", "이익·EPS", "설비투자(CAPEX)", "잉여현금흐름(FCF)", "회사 전망", "주가 반응"):
        assert label in rendered
    assert "발표 분 시각 미제공" in rendered and "서프라이즈로 판정하지" in rendered


@pytest.mark.parametrize("changes", [
    {"ticker": "MSFT"}, {"fiscal_period": "2026Q2"}, {"status": "scheduled"},
    {"release_date": "2026-10-30"}, {"checked_at": "2026-10-30T10:00:00+09:00"},
    {"source_url": "javascript:alert(1)"}, {"release_date": "2026-09-28"},
    {"source_url": "https://unknown.invalid/results"},
    {"source_url": "https://news.microsoft.com/source/2026/10/28/microsoft-announces-first-quarter-results-2/"},
    {"release_precision": "datetime", "release_at": "2026-10-29T16:00:00-04:00"},
])
def test_wrong_future_or_unverified_results_do_not_promote(changes):
    row, = reconcile_earnings(context(earnings_results=[result(**changes)]), NOW)
    assert row["event_status"] == "elapsed_unconfirmed"
    assert "result_metrics" not in row


def test_date_only_result_does_not_invent_release_minute_or_call_release_equivalence():
    data = context(calendar_events=[event(event_kind="conference_call")])
    row, = reconcile_earnings(data, NOW)
    assert row["event_kind"] == "results" and row["scheduled_event_kind"] == "conference_call"
    assert not row["release_time_confirmed"]
    rendered = "\n".join(earnings_calendar_lines(data, NOW))
    assert "결과 공개일은 별도 미확인" not in rendered
    assert "콜" in rendered and "발표 분 시각 미제공" in rendered


def test_headline_only_result_has_separate_confirmation_and_no_invented_numbers():
    data = context(earnings_results=[], next_session_news=[article()])
    row, = reconcile_earnings(data, NOW)
    assert row["event_status"] == "reported_results"
    assert row["result_metrics"]["revenue"]["status"] == "missing"
    rendered = "\n".join(earnings_calendar_lines(data, NOW))
    assert "실적 보도 확인·공식 대조 대기" in rendered
    assert "[결과 보도]" in rendered and "공식 결과 발표 확인" not in rendered


@pytest.mark.parametrize("row", [
    article("Alphabet will report Q3 2026 earnings"),
    article("Alphabet Q3 2026 earnings preview"),
    article("Alphabet announces Q3 2026 earnings release date"),
    article("Alphabet Q2 2026 earnings beat estimates"),
    article("Alphabet Q3 2025 earnings beat estimates"),
    article("Alphabet Q3 2025 results compared with 2026 outlook"),
    article("Microsoft Q3 2026 earnings beat estimates"),
    article("Alphabet and Microsoft Q3 2026 earnings results"),
    article("Fortinet reports Q3 2026 results; Alphabet stock in focus"),
    article("Alphabet supplier Fortinet reports Q3 2026 results"),
    article(market="KR"),
    article(published_at="2026-10-27T17:30:00-04:00"),
    article(published_at="2026-10-29T17:30:00-04:00"),
    article(publisher="Unknown", link="https://unknown.invalid/earnings"),
    article("Alphabet Q3 2026 revenue guidance disappoints investors"),
])
def test_preview_wrong_period_or_wrong_issuer_news_does_not_confirm(row):
    data = context(earnings_results=[], next_session_news=[row])
    assert reconcile_earnings(data, NOW)[0]["event_status"] == "elapsed_unconfirmed"


def test_us_fiscal_year_is_not_calendar_year():
    data = context(calendar_events=[event(ticker="MSFT", event="Microsoft earnings", fiscal_period="FY2027Q1")],
                   earnings_results=[], session_news=[article("Microsoft Q1 2027 earnings beat estimates")])
    assert reconcile_earnings(data, NOW)[0]["event_status"] == "reported_results"
    data["session_news"] = [article("Microsoft Q1 2026 earnings beat estimates")]
    assert reconcile_earnings(data, NOW)[0]["event_status"] == "elapsed_unconfirmed"
    data["session_news"] = [article("Microsoft reports Q1 FY2026 earnings results")]
    assert reconcile_earnings(data, NOW)[0]["event_status"] == "elapsed_unconfirmed"


def test_price_response_is_not_inferred_from_negative_fcf_or_positive_profit():
    row, = reconcile_earnings(context(next_session_news=[article("Alphabet Q3 2026 free cash flow falls after hours")]), NOW)
    assert row["result_metrics"]["price_reaction"]["status"] == "missing"
    data = context(next_session_news=[article("Alphabet stock falls after hours as Q3 2026 earnings disappoint")])
    reaction = reconcile_earnings(data, NOW)[0]["result_metrics"]["price_reaction"]
    assert reaction["status"] == "reported" and "기사 주장" in reaction["text"]
    data["next_session_news"] = [article("Alphabet stock falls after hours as Q3 2025 earnings disappoint")]
    assert reconcile_earnings(data, NOW)[0]["result_metrics"]["price_reaction"]["status"] == "missing"


def test_news_before_known_release_time_is_not_a_result_reaction():
    data = context(earnings_results=[result(release_precision="datetime", release_at="2026-10-28T16:05:00-04:00")],
                   next_session_news=[article("Alphabet stock fell after hours", published_at="2026-10-28T08:00:00-04:00")])
    assert reconcile_earnings(data, NOW)[0]["result_metrics"]["price_reaction"]["status"] == "missing"


def test_existing_official_release_is_never_downgraded_by_detail_fetch_failure():
    data = context(calendar_events=[event(event_status="released", event_kind="results", source_verified_at=NOW.isoformat())],
                   earnings_results=[], next_session_news=[article()])
    row, = reconcile_earnings(data, NOW)
    assert row["event_status"] == "released" and row["result_confirmation"] == "official_snapshot"
    assert row["result_metrics"]["revenue"]["status"] == "missing"


def test_live_quote_uses_real_observation_schema_and_preserves_reference_basis():
    quote = dict(return_value=-.03, previous_date="2026-10-28", as_of=(NOW - timedelta(minutes=1)).isoformat(),
                 source="Fixture quote", kind="데이마켓(야간)")
    quote["return"] = quote.pop("return_value")
    data = context(extended_prices={"GOOGL": quote})
    reaction = reconcile_earnings(data, NOW)[0]["result_metrics"]["price_reaction"]
    assert reaction["status"] == "observed_quote"
    assert "데이마켓(야간) -3.00%" in reaction["text"] and "직전 정규장 종가 대비" in reaction["text"]
    assert "발표일 시세·발표 전후 순서 미확인" in reaction["text"]
    quote["delayed"] = True
    assert reconcile_earnings(data, NOW)[0]["result_metrics"]["price_reaction"]["status"] == "missing"


def test_last_confirmed_result_is_visible_as_stale_not_forgotten():
    rendered = "\n".join(earnings_calendar_lines(context(earnings_results=[result(stale=True, collection_reason="http_503")]), NOW))
    assert "공식 결과 발표 확인" in rendered
    assert "수집 실패, 마지막 확인 결과" in rendered


def test_source_failure_displays_status_without_turning_missing_data_into_zero():
    data = context(earnings_results=[], earnings_result_sources=[{
        "ticker": "GOOGL", "status": "unavailable", "reason": "http_403", "attempted": True}])
    rendered = "\n".join(earnings_calendar_lines(data, NOW))
    assert "예정일 경과·결과 미확인" in rendered and "GOOGL HTTP 403" in rendered
    assert "0.0" not in rendered and "공식 결과 발표 확인" not in rendered


def test_no_evidence_keeps_schedule_and_all_other_context_exact():
    data = context(earnings_results=[])
    data["decision"] = {"code": "HARD_BLOCK", "score": 3}
    before = deepcopy(data)
    assert reconcile_earnings(data, NOW) == data["calendar_events"]
    assert data == before


def test_real_report_context_collects_once_and_render_never_refetches(monkeypatch):
    from unittest.mock import Mock
    import pandas as pd
    from stock_lab_core import prices, report_live, economic_releases, economic_bulletins
    from stock_lab_core import report_consensus, earnings_sources, earnings_result_sources
    from stock_lab_core.report_context import collect_report_context
    from stock_lab_core.report_build import _RENDER_MODULES

    monkeypatch.setattr(prices, "load_price_frames_batch", lambda *a, **k: {})
    monkeypatch.setattr(prices, "load_price_df", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(report_live, "supplement_kr_indices", lambda frames: frames)
    monkeypatch.setattr(economic_releases, "_api_key", lambda *a: "")
    monkeypatch.setattr(economic_releases, "load_economic_releases", lambda **k: ([], {"events": [], "sources": []}))
    monkeypatch.setattr(economic_bulletins, "apply_official_bulletins", lambda rows, now: rows)
    monkeypatch.setattr(report_consensus, "attach_economic_consensus", lambda rows, now, **k: (rows, {}))
    monkeypatch.setattr(earnings_sources, "load_official_earnings", lambda *a: {"events": [event()], "sources": []})
    loader = Mock(return_value={"results": [result()], "sources": [{"ticker": "GOOGL", "status": "connected"}]})
    monkeypatch.setattr(earnings_result_sources, "load_earnings_results", loader)
    data = collect_report_context(now=NOW, quote_data={}, scenario_frames={}, live_frames={})
    loader.assert_called_once_with([event()], NOW)
    before = deepcopy(data)
    assert "공식 결과 발표 확인" in "\n".join(earnings_calendar_lines(data, NOW))
    assert "공식 결과 발표 확인" in "\n".join(earnings_calendar_lines(data, NOW))
    loader.assert_called_once()
    for ticker, frame in data["price_frames"].items():
        pd.testing.assert_frame_equal(frame, before["price_frames"][ticker])
    assert {key: value for key, value in data.items() if key != "price_frames"} == {
        key: value for key, value in before.items() if key != "price_frames"}
    assert {"earnings_reconciliation", "earnings_result_sources"}.issubset(_RENDER_MODULES)
