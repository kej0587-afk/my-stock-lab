from urllib.parse import parse_qs, urlsplit

from stock_lab_core import today_news
from stock_lab_core.report_news_selection import selected_category_lines, matching_categories
from tests.test_report_news_preferences import SESSIONS, NOW, row


def test_event_and_issuer_searches_survive_all_topics_without_extra_requests():
    categories = [p["category"] for p in today_news.TODAY_MARKET_STORY_RSS_PLAN]
    windows, _ = today_news._session_news_windows(SESSIONS, NOW)
    specs = today_news._session_query_specs(windows, categories, NOW,
        held_exposures=[{"Ticker": ticker} for ticker in ("GOOGL", "MSFT", "AMZN", "INTC", "SNDK")])
    assert len(specs) <= today_news._SESSION_QUERY_LIMIT == 16
    assert len([s for s in specs if s.get("query_kind") == "market_event"]) == 2
    assert len([s for s in specs if s.get("query_kind") == "issuer_catalyst"]) == 4
    assert {c for s in specs for c in s.get("selected_categories", [])} == set(categories)
    assert {s["market"] for s in specs[:len(windows)]} == {"KR", "US"}
    event_queries = [parse_qs(urlsplit(s["url"]).query)["q"][0] for s in specs if s.get("query_kind") == "market_event"]
    assert any("earnings" in q for q in event_queries)
    assert any("midterm election" in q for q in event_queries)
    assert all("after:" in q and "before:" in q for q in event_queries)


def test_earnings_not_displaced_by_newer_small_ai_investment():
    context = {"news_retrieval": {"requested_categories": ["반도체·AI"], "per_category": 1},
               "other_market_news": [
                   row("AI startup raises seed investment", "seed"),
                   dict(row("AMD semiconductor earnings beat estimates", "earnings"), published_at="2026-11-02T08:00:00+09:00"),
               ]}
    output = "\n".join(selected_category_lines(context, NOW))
    assert "/earnings" in output
    assert "/seed" not in output
    assert "한국/미국 등락 원인 미확정" in output


def test_election_classification_does_not_require_a_price_direction():
    assert matching_categories("US midterm election results pending", ["정책/규제"]) == ["정책/규제"]
    assert matching_categories("미국 중간선거 개표 진행", ["정책/규제"]) == ["정책/규제"]
