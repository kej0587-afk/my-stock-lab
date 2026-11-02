"""Evidence transitions, not investment performance or a market-wide census."""

from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock

import pytest

from stock_lab_core.earnings_collection import collect_report_earnings
from stock_lab_core.earnings_discovery import discover_earnings_news, issuer_catalog
from stock_lab_core.earnings_pipeline import build_earnings_pipeline
from stock_lab_core.earnings_reconciliation import reconcile_earnings
from stock_lab_core.report_calendar import earnings_calendar_lines, _result_detail_lines
from stock_lab_core.report_earnings import earnings_coverage_lines, earnings_story_lines
from tests.test_earnings_reconciliation import context, event, result, article, SOURCE

NOW = datetime.fromisoformat("2026-10-29T11:00:00+09:00")


def news(title, suffix="one", **changes):
    return article(title, link="https://www.cnbc.com/" + suffix, **changes)


@pytest.mark.parametrize("title,ticker", [
    ("JPMorgan Q3 2026 earnings beat estimates", "JPM"),
    ("Eli Lilly Q3 2026 earnings beat estimates", "LLY"),
    ("Walmart Q3 2026 earnings beat estimates", "WMT"),
    ("Caterpillar Q3 2026 earnings miss estimates", "CAT"),
    ("KB금융은 3분기 실적 발표, 순이익 증가", "105560.KS"),
    ("기아는 3분기 실적 발표", "000270.KS"),
    ("구글 실적 발표", "GOOGL"),
    ("메타의 실적 발표", "META"),
    ("Costco quarterly results top estimates", "COST"),
    ("Walmart EPS beats estimates", "WMT"),
    ("Alphabet 2026Q3 earnings beat estimates", "GOOGL"),
    ("Microsoft FY2027Q1 earnings beat estimates", "MSFT"),
    ("Microsoft fiscal year 2027 earnings beat estimates", "MSFT"),
])
def test_existing_market_universe_discovers_non_tech_without_network(title, ticker):
    market = "KR" if ticker.endswith(".KS") else "US"
    data = discover_earnings_news([news(title, market=market)], issuer_catalog(), NOW)
    assert [row["ticker"] for row in data["items"]] == [ticker]


@pytest.mark.parametrize("title", [
    "JPMorgan and Goldman Sachs earnings beat estimates",
    "ON track to report better earnings", "GE estimates for economic growth",
    "Amazon and Intel earnings disappoint", "Industry earnings outlook improves",
    "Adobe reports Q3 2026 earnings; Microsoft partnership expands",
    "Microsoft partnership expands after Adobe earnings beat estimates",
    "Alphabet supplier Adobe reports Q3 2026 earnings",
])
def test_ambiguous_or_generic_titles_do_not_assign_results(title):
    catalog = issuer_catalog(events=[event(ticker="INTC", event="Intel earnings")])
    found = discover_earnings_news([news(title)], catalog, NOW)
    # GE is only safe with a company name or an explicit ticker marker.
    assert found["items"] == []


def test_existing_news_is_deduped_and_bad_market_future_old_sources_are_excluded():
    row = news("Walmart Q3 2026 earnings beat estimates")
    data = discover_earnings_news([
        row, dict(row), news(row["title"], "wrong", market="KR"),
        news(row["title"], "future", published_at="2026-10-30T12:00:00-04:00"),
        news(row["title"], "old", published_at="2026-09-20T12:00:00-04:00"),
        dict(news(row["title"], "bad", publisher="anonymous promotion"), link="https://example.invalid/promo"),
    ], issuer_catalog(), NOW)
    assert len(data["items"]) == 1
    assert data["excluded"]["시장 불일치"] == 1


def test_news_only_candidate_does_not_invent_schedule_metrics_or_surprise():
    row = news("Eli Lilly Q3 2026 earnings beat estimates")
    original = {"calendar_events": [], "session_news": [row], "decision": {"code": "WAIT", "score": 2}}
    before = deepcopy(original)
    pipeline = build_earnings_pipeline(original, now=NOW)
    packet, = pipeline["packets"]
    assert packet["ticker"] == "LLY" and packet["official"] is False
    assert packet["metrics"] == {} and packet["date_basis"] == "보도일·발표일 아님"
    assert "상회" not in packet["release_status"]
    assert "주장" in packet["consensus_status"]
    assert pipeline["events"] == [] and pipeline["scoring_used"] is False
    assert original == before
    rendered = "\n".join(earnings_story_lines(pipeline))
    assert "Eli Lilly(LLY)" in rendered and "제목 기준·기사 주장" in rendered
    assert "공식 분기 자료와 대조되지 않아" in rendered


@pytest.mark.parametrize("title", [
    "Walmart will report Q3 2026 earnings",
    "Walmart Q3 2026 earnings expected to beat estimates",
    "Walmart Q3 2026 earnings forecast to beat estimates",
    "Walmart Q3 2026 earnings anticipated to beat estimates",
    "Walmart announces Q3 2026 earnings release date",
])
def test_preview_never_becomes_result_or_market_story(title):
    pipeline = build_earnings_pipeline({}, news=[news(title)], now=NOW)
    assert pipeline["packets"][0]["release_status"] == "발표 예정 보도"
    assert pipeline["highlights"] == []


def test_confirmed_events_and_six_metric_values_equal_previous_reconciler():
    data = context()
    before = deepcopy(data)
    previous = reconcile_earnings(data, NOW)
    pipeline = build_earnings_pipeline(data, now=NOW)
    assert pipeline["events"] == previous and data == before
    packet, = pipeline["packets"]
    assert packet["metrics"] == previous[0]["result_metrics"]
    assert packet["stages"]["revenue"] == "확인"
    assert packet["stages"]["guidance"] == "콜 대기"
    assert packet["stages"]["price_reaction"] == "미연결"
    assert "투자 후 현금 창출력" in packet["commentary"]
    assert "상회/하회 판단 보류" in packet["consensus_status"]
    rendered = "\n".join(earnings_calendar_lines(data, NOW, pipeline=pipeline))
    assert "\n".join(_result_detail_lines(previous[0])) in rendered
    assert "CAPEX: USD 50" in rendered and "FCF: USD -10" in rendered


def test_wrong_and_unknown_periods_cannot_borrow_official_metrics():
    data = context()
    pipeline = build_earnings_pipeline(data, news=[
        news("Alphabet Q2 2026 earnings beat estimates", "wrong"),
        news("Alphabet earnings disappoint on capital expenditure", "unknown"),
        news("Alphabet Q3 2026 earnings beat estimates", "same"),
    ], now=NOW)
    verified = next(p for p in pipeline["packets"] if p["official"])
    assert len(verified["articles"]) == 1
    for packet in pipeline["packets"]:
        if not packet["official"]:
            assert packet["metrics"] == {}
    assert pipeline["highlights"] == [verified]


def test_highlights_diversify_existing_evidence_and_do_not_fill_missing_sectors():
    rows = [news("JPMorgan Q3 2026 earnings beat estimates", "bank"),
            news("Eli Lilly Q3 2026 earnings miss estimates", "health"),
            news("Walmart Q3 2026 earnings beat estimates", "consumer")]
    pipeline = build_earnings_pipeline({}, news=rows, now=NOW)
    assert len({p["sector"] for p in pipeline["highlights"]}) == 3
    assert len(build_earnings_pipeline({}, news=rows[:1], now=NOW)["highlights"]) == 1


def test_source_failure_and_collection_limit_are_different_from_no_earnings():
    data = context(earnings_results=[], earnings_result_sources=[dict(ticker="GOOGL", status="unavailable", reason="http_403")],
                   earnings_collection_scope={"requested": ["GOOGL", "LLY"], "not_submitted": ["LLY"]})
    pipeline = build_earnings_pipeline(data, now=NOW)
    missing = {row["ticker"]: row["reason"] for row in pipeline["coverage"]["missing"]}
    assert missing == {"GOOGL": "공식 출처 HTTP 403", "LLY": "수집 한도 밖"}
    rendered = "\n".join(earnings_coverage_lines(pipeline))
    assert "미연결은 0·미발표·실적 부진이 아닙니다" in rendered


def test_collection_extraction_preserves_old_order_limits_outputs_and_call_counts(monkeypatch):
    from stock_lab_core import earnings_sources, earnings_result_sources
    summaries = [{"ticker": "MSFT"}, {"ticker": "LLY"}, {"ticker": "GOOGL"}, {"ticker": "LLY"}]
    calendar = {"events": [event(), {"indicator": "US_CPI"}], "sources": ["macro"]}
    before = deepcopy(calendar)
    sources = [dict(ticker="GOOGL", status="connected")]
    schedule_loader = Mock(return_value={"events": [event()], "sources": sources})
    result_loader = Mock(return_value={"results": [result()], "sources": []})
    monkeypatch.setattr(earnings_sources, "load_official_earnings", schedule_loader)
    monkeypatch.setattr(earnings_result_sources, "load_earnings_results", result_loader)
    supplied = list(dict.fromkeys(row["ticker"] for row in summaries))
    old_order = list(dict.fromkeys(["000660.KS", "005930.KS", "NVDA", "GOOGL", "META", "MSFT", "TSLA",
        *(ticker for ticker in supplied if ticker in earnings_sources._ISSUERS), *supplied]))
    collected = collect_report_earnings(summaries, calendar, NOW)
    schedule_loader.assert_called_once_with(old_order, NOW)
    result_loader.assert_called_once_with([event()], NOW)
    assert collected["calendar_events"] == [{"indicator": "US_CPI"}, event()]
    assert collected["earnings_results"] == [result()] and collected["earnings_sources"] == sources
    assert calendar == before
    # Rendering/analysis can repeat without any new provider requests.
    for _ in range(3):
        pipeline = build_earnings_pipeline(collected, summaries, now=NOW)
        earnings_calendar_lines(collected, NOW, pipeline=pipeline)
        earnings_story_lines(pipeline)
    assert schedule_loader.call_count == result_loader.call_count == 1


def test_collection_records_all_unsubmitted_issuers_without_increasing_budget(monkeypatch):
    from stock_lab_core import earnings_sources, earnings_result_sources
    summaries = [{"ticker": f"TEST{i}"} for i in range(60)]
    monkeypatch.setattr(earnings_sources, "load_official_earnings", lambda *a: {"events": [], "sources": []})
    monkeypatch.setattr(earnings_result_sources, "load_earnings_results", lambda *a: {"results": [], "sources": []})
    scope = collect_report_earnings(summaries, {"events": []}, NOW)["earnings_collection_scope"]
    assert len(scope["submitted"]) == earnings_sources.MAX_TICKERS
    assert len(scope["requested"]) == 67 and len(scope["not_submitted"]) == 35


@pytest.mark.parametrize("fcf", [
    "Free cash flow was $5 billion, compared with last year when free cash flow was negative $2 billion",
    "Last year free cash flow was negative $2 billion; this year it was positive $5 billion",
    "잉여현금흐름은 5조원 흑자, 지난해 잉여현금흐름은 2조원 적자",
    "Free cash flow was negative $2 billion last year, compared with positive $5 billion this quarter",
])
def test_historical_fcf_deficit_is_not_a_current_deficit(fcf):
    actual = result()
    actual["metrics"]["free_cash_flow"]["text"] = fcf
    pipeline = build_earnings_pipeline(context(earnings_results=[actual]), now=NOW)
    assert "FCF 적자가 확인" not in pipeline["packets"][0]["commentary"]
    assert fcf.replace("$", r"\$") in "\n".join(earnings_story_lines(pipeline))


def test_coverage_canonicalizes_aliases_and_excludes_funds_without_metadata():
    data = context(earnings_collection_scope={"requested": ["GOOG", "RAM", "379810.KS", "SOXX"]})
    summaries = [{"티커": ticker} for ticker in ("GOOG", "RAM", "379810.KS", "SOXX")]
    pipeline = build_earnings_pipeline(data, summaries, now=NOW)
    assert pipeline["coverage"]["missing"] == []
    assert pipeline["coverage"]["registered"] == 1
    assert not {"RAM", "379810.KS", "SOXX"} & issuer_catalog(summaries).keys()


def test_alias_collection_limit_diagnostic_is_canonical():
    pipeline = build_earnings_pipeline({"earnings_collection_scope": {
        "requested": ["GOOG"], "not_submitted": ["GOOG"]}}, now=NOW)
    assert pipeline["coverage"]["missing"] == [dict(ticker="GOOGL", name="Alphabet", reason="수집 한도 밖")]
    pipeline = build_earnings_pipeline({"earnings_collection_scope": {
        "requested": ["005935"], "not_submitted": ["005935"]}}, now=NOW)
    assert pipeline["coverage"]["missing"] == [dict(ticker="005930.KS", name="삼성전자", reason="수집 한도 밖")]


@pytest.mark.parametrize("title", [
    "Walmart Q3 2026 earnings beat estimates, lifts full-year forecast",
    "메타 3분기 실적 예상 상회",
])
def test_realized_results_with_estimates_or_outlook_are_not_previews(title):
    pipeline = build_earnings_pipeline({}, news=[news(title)], now=NOW)
    assert pipeline["highlights"] and pipeline["highlights"][0]["official"] is False


def test_story_escapes_currency_and_separates_guidance_target_period():
    actual = result()
    actual["metrics"]["free_cash_flow"]["text"] = "Free cash flow was $5 billion, compared with $2 billion"
    actual["metrics"]["capex"] = {}
    actual["metrics"]["guidance"] = dict(status="available", text="Next quarter revenue $20 to $30 billion", source_url=SOURCE)
    pipeline = build_earnings_pipeline(context(earnings_results=[actual]), now=NOW)
    rendered = "\n".join(earnings_story_lines(pipeline))
    assert r"\$5 billion, compared with \$2 billion" in rendered
    assert "전망 대상 기간은 원문 기준" in rendered
    assert "기업·확인된 사실 | 해석과 남은 확인" in rendered
    assert "Next quarter revenue $20 to $30 billion" == pipeline["packets"][0]["metrics"]["guidance"]["text"]
