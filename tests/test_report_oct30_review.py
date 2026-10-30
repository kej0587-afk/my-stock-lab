"""Recorded headline regressions and synthetic financial/session observations."""

from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core import catalyst_news as cn, earnings_sources, earnings_result_sources as er
from stock_lab_core.report_market_summary import market_participation_reading
from stock_lab_core.today_news import partition_session_market_news

NOW = datetime.fromisoformat("2026-10-30T09:35:00+09:00")
SESSIONS = {"US": {"date": "2026-10-29", "previous_date": "2026-10-28"}}


def article(title, key="one"):
    return dict(title=title, market="US", publisher="Reuters",
                link="https://www.reuters.com/markets/" + key,
                published_at="2026-10-30T08:31:00+09:00")


def test_delayed_alphabet_market_recap_is_not_new_after_hours_earnings():
    row = article("US stocks slump as Alphabet revenue miss reignites AI capex jitters")
    original = deepcopy(row)
    partition = partition_session_market_news([row], SESSIONS, now=NOW)
    assert len(partition["session_news"]) == 1
    assert partition["session_news"][0]["session_date"] == "2026-10-29"
    assert not partition["next_session_news"]
    assert not cn.after_close_catalysts([row], closed_end="2026-10-29T16:00:00-04:00", now=NOW)
    assert row == original


def test_overview_keeps_named_issuer_issue_in_matching_regular_session():
    from stock_lab_core.report_market_summary import market_summary
    from stock_lab_core.report_session import market_session_states
    row = article("US stocks slump as Alphabet revenue miss reignites AI capex jitters")
    news = partition_session_market_news([row], SESSIONS, now=NOW)["session_news"]
    context = {"sessions": {"US": "2026-10-29"}, "prices": {
        ticker: {"date": "2026-10-29", "return": -.01}
        for ticker in ("^GSPC", "^IXIC", "^DJI")}}
    states = market_session_states(NOW, context["sessions"])
    output = market_summary(context, news, [], states, NOW)
    assert "Alphabet 실적 기대 미달 보도·설비투자 부담(제목 기준)" in output["overview"]
    assert "잉여현금흐름 악화" not in output["overview"]
    news[0]["session_date"] = "2026-10-28"
    assert "Alphabet" not in market_summary(context, news, [], states, NOW)["overview"]
    assert not cn.issuer_reported_issue("Amazon shares fall after hours as revenue misses estimates")


@pytest.mark.parametrize("ticker,name", [("AMZN", "Amazon"), ("INTC", "Intel"), ("SNDK", "Sandisk")])
def test_new_issuer_extended_reaction_and_release_window(ticker, name):
    row = article(f"{name} shares fall after hours as earnings outlook disappoints")
    split = partition_session_market_news([row], SESSIONS, now=NOW)
    assert not split["session_news"]
    assert len(split["next_session_news"]) == 1
    found = cn.after_close_catalysts([row], closed_end="2026-10-29T16:00:00-04:00", now=NOW)
    assert found[0]["issuers"] == [ticker]
    assert found[0]["reaction"] == "reported_extended_decline"
    assert not found[0]["prior_close_cause"]


def test_query_budget_does_not_drop_amazon_intel_sandisk():
    specs = cn.exposure_catalyst_specs(["CIBR", "GOOGL", "MSFT", "AMZN", "INTC", "SNDK"], now=NOW)
    assert len(specs) == cn.MAX_CATALYST_QUERIES == 4
    assert {t for s in specs for t in s["query_issuers"]} == {"FFIV", "FTNT", "GOOGL", "MSFT", "AMZN", "INTC", "SNDK"}
    for ticker in ("AMZN", "INTC", "SNDK"):
        assert any(cn.matches_catalyst_query(f"{ticker} earnings results", s) for s in specs)


def test_watched_earnings_reach_live_news_query_plan_without_extra_requests(monkeypatch):
    from collections import Counter
    from stock_lab_core import today_news
    plans = []
    def retrieve(specs, **kwargs):
        plans.extend(specs)
        return {"rows": [], "failures": Counter(), "complete": False}
    monkeypatch.setattr(today_news, "_retrieve_session_rss", retrieve)
    today_news.fetch_session_market_news(
        SESSIONS, now=NOW, held_exposures=[{"티커": "CIBR"}],
        watched_exposures=[{"티커": t} for t in ("GOOGL", "MSFT", "AMZN", "INTC", "SNDK")])
    assert len(plans) <= today_news._SESSION_QUERY_LIMIT
    assert len([s for s in plans if s.get("query_kind") == "issuer_catalyst"]) == 4
    assert {"AMZN", "INTC", "SNDK"} <= {t for s in plans for t in s.get("query_issuers", ())}


def test_index_decline_can_coexist_with_other_sector_gains_not_fund_flows():
    context = {"sessions": {"US": "2026-10-29"}, "prices": {
        t: {"date": "2026-10-29", "return": r} for t, r in
        (("^IXIC", -.0138), ("^GSPC", -.003), ("XLV", .02), ("XLF", .01), ("IWM", .0096))}}
    before = deepcopy(context)
    message = market_participation_reading(context)
    assert all(name in message for name in ("헬스케어", "금융", "중소형주", "공존", "자금 이동 확인은 아닙니다"))
    assert "400" not in message
    context["prices"]["XLV"]["date"] = "2026-10-28"
    context["prices"]["XLF"]["stale"] = True
    assert "헬스케어" not in market_participation_reading(context)
    assert "금융" not in market_participation_reading(context)
    assert before["prices"]["XLV"]["date"] == "2026-10-29"


def test_amazon_sales_do_not_use_aws_run_rate_or_lose_comparison_sentence():
    blocks = ["AWS net sales grew to a $160 billion annualized revenue run rate.",
              "Net sales increased to $200 billion in third quarter 2026, compared with $180 billion in third quarter 2025.",
              "Free cash flow decreased to $42 billion for the trailing twelve months, compared with $80 billion last year.",
              "Net sales are expected to be between $230 billion and $240 billion."]
    metrics = er._prose_metrics(blocks, er._PROFILES["AMZN"])
    assert metrics["revenue"]["text"] == blocks[1]
    assert metrics["free_cash_flow"]["period_scope"] == "trailing_twelve_months"
    assert metrics["guidance"]["text"] == blocks[3]
    prior = er._prose_metrics(["Third quarter 2025 revenue was $180 billion, compared with $100 billion in third quarter 2024."], er._PROFILES["AMZN"])
    assert prior["revenue"]["status"] == "missing"


def test_intel_forecast_is_not_realized_revenue():
    metric = er._prose_metrics(["Forecasting fourth-quarter 2026 revenue of $15 billion to $16 billion."], er._PROFILES["INTC"])
    assert metric["revenue"]["status"] == "missing"
    assert metric["guidance"]["status"] == "reported"


def test_nested_amazon_segment_list_does_not_hide_consolidated_sales():
    body = b'''<main><h1>Amazon.com Announces Third Quarter Results</h1>
    <p>October 29, 2026 - Amazon today announced financial results for its third quarter.</p>
    <div class="ai-summary"><ul><li>Net sales were $999 billion.
    <ul><li>Unverified segment summary.</li></ul></li></ul></div>
    <ul><li>Net sales increased to $200 billion in the third quarter, compared with $180 billion in third quarter 2025.
    Excluding a timing shift, sales would have been higher.
    <ul><li>AWS segment sales increased to $40 billion.</li></ul></li>
    <li>Free cash flow decreased to an outflow of $42 billion for the trailing twelve months, driven by an increase of $90 billion in purchases of property and equipment.</li></ul></main>'''
    parsed = er.parse_earnings_result(body, "AMZN", NOW)
    metrics = parsed["metrics"]
    assert metrics["revenue"]["text"].startswith("Net sales increased to $200")
    assert metrics["capex"]["status"] == "missing"
    assert metrics["free_cash_flow"]["period_scope"] == "trailing_twelve_months"


def test_verified_release_coverage_never_leaks_back_to_earlier_reports():
    early = datetime.fromisoformat("2026-10-29T09:00:00+09:00")
    assert not earnings_sources.load_official_earnings(["AMZN", "INTC", "SNDK"], early, refresh=False)["events"]
    result = earnings_sources.load_official_earnings(["AMZN", "INTC", "SNDK"], NOW, refresh=False)
    assert {e["ticker"] for e in result["events"]} == {"AMZN", "INTC", "SNDK"}
    assert all(e["release_precision"] == "date" for e in result["events"])
    for ticker in ("AMZN", "INTC", "SNDK"):
        assert er.is_official_result_url(ticker, er._PROFILES[ticker]["source_url"])
        assert not er.is_official_result_url("GOOGL", er._PROFILES[ticker]["source_url"])
