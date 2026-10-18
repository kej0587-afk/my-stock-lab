from datetime import datetime, timezone
from email.utils import format_datetime
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

from stock_lab_core import today_news
from stock_lab_core.today_news import (
    build_today_action_news_brief,
    clean_today_action_news_asset_name,
    normalize_today_action_news_row,
    rank_today_action_news_rows,
)


def test_today_news_ranking_filters_low_quality_noise():
    rows = [
        normalize_today_action_news_row(
            {
                "title": "알바생 걱정한 사장님의 당부",
                "market_category": "국채/유동성",
                "publisher": "news.sbs.co.kr",
            },
            "시장/속보",
        ),
        normalize_today_action_news_row(
            {
                "title": "CPI outlook sends Treasury yields lower before Fed decision",
                "market_category": "외환/금리",
                "publisher": "Reuters",
            },
            "핵심속보",
        ),
    ]

    ranked = rank_today_action_news_rows(rows)

    assert len(ranked) == 1
    assert ranked[0]["출처"] == "Reuters"
    assert ranked[0]["읽기분류"] == "환율/금리"
    assert ranked[0]["중요도"] >= 8


def test_today_news_ranking_filters_market_name_noise():
    rows = [
        normalize_today_action_news_row(
            {
                "title": "구리문화재단 신임 대표이사에 송영한 씨 취임",
                "market_category": "원자재/금속",
                "publisher": "연합뉴스",
            },
            "시장/속보",
        ),
        normalize_today_action_news_row(
            {
                "title": "Semiconductor ETFs SMH, SOXX, SOXL Top Weekly Fund Flows",
                "market_category": "반도체/AI",
                "publisher": "Stocktwits",
            },
            "핵심속보",
        ),
    ]

    ranked = rank_today_action_news_rows(rows)

    assert len(ranked) == 1
    assert ranked[0]["읽기분류"] == "반도체/AI"


def test_today_news_brief_explains_priority_for_beginners():
    rows = [
        normalize_today_action_news_row(
            {
                "title": "Gold and copper prices rise on commodity demand",
                "market_category": "원자재/금속",
                "publisher": "Reuters",
            },
            "시장/속보",
        ),
        normalize_today_action_news_row(
            {
                "title": "TSMC revenue jumps on AI demand",
                "market_category": "실적/대장주",
                "publisher": "Reuters",
            },
            "핵심속보",
        ),
    ]

    ranked = rank_today_action_news_rows(rows)
    brief = build_today_action_news_brief(ranked)

    assert any("금" in line and "구리" in line for line in brief)
    assert any("반도체" in line or "실적" in line for line in brief)


def test_today_news_cleans_long_or_punctuated_stock_names():
    cibr = normalize_today_action_news_row(
        {
            "ticker": "CIBR",
            "name": "First Trust NASDAQ Cybersecurit",
            "title": "Precision Trading with First Trust Nasdaq Cea Cybersecurity Etf (CIBR) Risk Zones",
            "publisher": "news.stocktradersdaily.com",
        },
        "내 종목",
    )

    assert cibr["종목"] == "사이버보안 ETF(CIBR)"
    assert clean_today_action_news_asset_name("Palo Alto Networks,", "PANW") == "팔로알토 네트웍스"


SESSIONS = {"US": {"date": "2026-10-16", "previous_date": "2026-10-15"}}
NEWS_NOW = datetime.fromisoformat("2026-10-18T18:00:00+09:00")


def rss_response(rows):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for index, row in enumerate(rows):
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = row["title"]
        ET.SubElement(item, "link").text = row.get("link", f"https://news.google.com/rss/articles/{index}")
        ET.SubElement(item, "source", url=row.get("publisher_url", "https://www.reuters.com")).text = row.get("publisher", "Reuters")
        ET.SubElement(item, "pubDate").text = row.get("published", "Fri, 16 Oct 2026 19:00:00 GMT")
    return BytesIO(ET.tostring(root))


def test_session_fetch_uses_absolute_dates_and_separate_historical_latest_queries(monkeypatch):
    calls = []

    def fetch(request, timeout):
        calls.append((parse_qs(urlsplit(request.full_url).query), timeout))
        return rss_response([{"title": "US stock market closes higher"}])

    monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
    result = today_news.fetch_session_market_news(SESSIONS, now=NEWS_NOW)
    assert 1 <= len(calls) <= 16
    queries = [query["q"][0] for query, _ in calls]
    assert all("after:" in q and "before:" in q and "when:" not in q for q in queries)
    assert any("after:2026-10-14" in q for q in queries)
    assert any("after:2026-10-17" in q for q in queries)
    assert any("closing bell" in q for q in queries)
    assert all(timeout == 5 for _, timeout in calls)
    assert len(result["session_news"]) == 1
    assert result["session_news"][0]["market"] == "US"
    assert result["session_news"][0]["published_at"].startswith("2026-10-16T19:00:00")


def test_session_fetch_whitelist_dedup_is_scoped_to_each_time_bucket(monkeypatch):
    rows = [
        {"title": "CXMT semiconductor stocks slump", "link": "https://www.reuters.com/a"},
        {"title": "CXMT semiconductor stocks fall", "link": "https://www.cnbc.com/b", "publisher": "CNBC"},
        {"title": "US stocks close due to semiconductor slump", "link": "https://www.reuters.com/c"},
        {"title": "US stocks price today to USD", "publisher": "CoinMarketCap", "publisher_url": "https://coinmarketcap.com"},
        {"title": "Oil prices rise", "publisher": "Unknown blog", "publisher_url": "https://example.org"},
        {"title": "CXMT semiconductor stocks outlook", "link": "https://www.reuters.com/d", "published": "Sun, 18 Oct 2026 06:00:00 GMT"},
        {"title": "US stock market future", "published": "Mon, 19 Oct 2026 06:00:00 GMT"},
    ]
    monkeypatch.setattr(today_news.urllib.request, "urlopen", lambda *args, **kwargs: rss_response(rows))
    result = today_news.fetch_session_market_news(SESSIONS, now=NEWS_NOW)
    assert result["session_news"][0]["title"] == "US stocks close due to semiconductor slump"
    assert len(result["session_news"]) == 2
    assert len(result["next_session_news"]) == 1
    assert result["next_session_news"][0]["event_key"] == "cxmt"


def test_session_fetch_mixed_market_query_results_have_no_inferred_market(monkeypatch):
    sessions = dict(SESSIONS, KR={"date": "2026-10-16", "previous_date": "2026-10-15"})
    monkeypatch.setattr(today_news.urllib.request, "urlopen", lambda *args, **kwargs: rss_response([
        {"title": "Global stock market mixed after Fed decision"},
    ]))
    result = today_news.fetch_session_market_news(sessions, now=NEWS_NOW)
    assert not result["session_news"] and not result["next_session_news"]
    assert any("명시된 시장" in r for r in result["missing"])


def test_session_fetch_respects_market_specific_query_provenance(monkeypatch):
    sessions = dict(SESSIONS, KR={"date": "2026-10-16", "previous_date": "2026-10-15"})

    def fetch(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)["q"][0]
        if "코스피" in query:
            return rss_response([{"title": "코스피 증시 마감", "link": "https://news.google.com/kr", "published": "Fri, 16 Oct 2026 06:30:00 GMT"}])
        return rss_response([{"title": "US stock market closes higher", "link": "https://news.google.com/us"}])

    monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
    result = today_news.fetch_session_market_news(sessions, now=NEWS_NOW)
    assert {row["market"] for row in result["session_news"]} == {"KR", "US"}
    assert len(result["session_news"]) == 2


def test_session_fetch_bounds_queries_and_surfaces_errors(monkeypatch):
    calls = []

    def fail(request, timeout):
        calls.append(request.full_url)
        raise TimeoutError("network unavailable")

    monkeypatch.setattr(today_news.urllib.request, "urlopen", fail)
    categories = [plan["category"] for plan in today_news.TODAY_MARKET_STORY_RSS_PLAN]
    sessions = dict(SESSIONS, KR={"date": "2026-10-16", "previous_date": "2026-10-15"})
    result = today_news.fetch_session_market_news(sessions, now=NEWS_NOW, categories=categories)
    assert 0 < len(calls) <= 16
    assert any("수집 한도" in r for r in result["missing"])
    assert any("RSS 수집 실패" in r for r in result["missing"])
    assert not result["session_news"] and not result["next_session_news"]


def test_session_fetch_never_queries_missing_or_unclosed_sessions(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("must not query")

    monkeypatch.setattr(today_news.urllib.request, "urlopen", unexpected)
    for sessions in ({}, {"US": "2026-10-16"}, {"US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}):
        result = today_news.fetch_session_market_news(sessions, now=NEWS_NOW)
        assert not result["windows"] and result["missing"]


def test_generic_fetch_preserves_existing_query_and_display_contract(monkeypatch):
    queries = []
    pub = format_datetime(datetime.now(timezone.utc))

    def fetch(request, timeout):
        queries.append(parse_qs(urlsplit(request.full_url).query)["q"][0])
        return rss_response([{"title": "Oil prices rise as stocks fall", "published": pub}])

    monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
    result = today_news.fetch_today_market_story_news(selected_categories=("에너지/해운",), days=2)
    assert len(queries) == len(result) == 1
    assert "when:2d" in queries[0]
    assert "market" not in result[0]
    assert "/" in result[0]["published"] and "T" in result[0]["published_at"]


def test_session_fetch_caps_category_and_keeps_latest_post_close(monkeypatch):
    rows = [
        {"title": f"Stock market story {i}", "link": f"https://www.reuters.com/{i}"}
        for i in range(5)
    ] + [
        {"title": "Oil prices rise", "link": "https://www.reuters.com/oil", "published": "Sun, 18 Oct 2026 06:00:00 GMT"},
        {"title": "Stock market closes", "link": "https://www.reuters.com/wrap", "published": "Fri, 16 Oct 2026 20:01:00 GMT"},
    ]
    monkeypatch.setattr(today_news.urllib.request, "urlopen", lambda *args, **kwargs: rss_response(rows))
    result = today_news.fetch_session_market_news(SESSIONS, now=NEWS_NOW, per_category=1)
    counts = {}
    for row in result["session_news"]:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    assert all(count == 1 for count in counts.values())
    assert result["next_session_news"][0]["title"] == "Oil prices rise"


def test_session_fetch_deduplicates_revised_headlines_at_same_url(monkeypatch):
    rows = [
        {"title": "US stock market moves on oil", "link": "https://www.reuters.com/same"},
        {"title": "US stock market moves on Treasury yields", "link": "https://www.reuters.com/same"},
    ]
    monkeypatch.setattr(today_news.urllib.request, "urlopen", lambda *args, **kwargs: rss_response(rows))
    assert len(today_news.fetch_session_market_news(SESSIONS, now=NEWS_NOW)["session_news"]) == 1


def test_session_fetch_invalid_and_oversized_rss_is_closed_and_reported(monkeypatch):
    for data in (b"<html>not RSS</html>", b"x" * (512 * 1024 + 1)):
        responses = []

        def fetch(*args, **kwargs):
            response = BytesIO(data)
            responses.append(response)
            return response

        monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
        result = today_news.fetch_session_market_news(SESSIONS, now=NEWS_NOW)
        assert responses and all(response.closed for response in responses)
        assert any("RSS 수집 실패" in reason for reason in result["missing"])


def test_session_fetch_separates_empty_feed_from_failed_feed(monkeypatch):
    monkeypatch.setattr(today_news.urllib.request, "urlopen", lambda *args, **kwargs: rss_response([]))
    result = today_news.fetch_session_market_news(SESSIONS, now=NEWS_NOW)
    assert any("채택 뉴스 없음" in reason for reason in result["missing"])
    assert not any("RSS 수집 실패" in reason for reason in result["missing"])
