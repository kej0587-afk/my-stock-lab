"""Synthetic, offline regressions for report news coverage and causal scope."""

from copy import deepcopy
from datetime import datetime, timedelta
from email.utils import format_datetime
from io import BytesIO
from threading import Lock
from time import sleep
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

import pytest

from stock_lab_core import today_news
from stock_lab_core.report_analysis import sector_evidence
from stock_lab_core.report_presentation import (
    is_preopen_outlook, market_cause_candidates, news_theme,
    sector_news_topics, sector_related_news,
)


NOW = datetime.fromisoformat("2026-10-20T11:00:00-04:00")
CLOSED = {"KR": {"date": "2026-10-20", "previous_date": "2026-10-19"},
          "US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}
LIVE = {"US": {"date": "2026-10-20", "previous_date": "2026-10-19"}}


def story(title, **overrides):
    return dict(dict(title=title, market="US", session_date="2026-10-20",
                     news_bucket="current_session_news", publisher="Reuters",
                     published_at="2026-10-20T10:30:00-04:00",
                     link="https://www.reuters.com/exposure-fixture"), **overrides)


@pytest.mark.parametrize("title,expected", [
    ("U.S. Stocks Mostly Higher as AI Credit Worries Abate", "AI 신용우려 완화"),
    ("AI debt fears ease as technology stocks rebound", "AI 차입우려 완화"),
    ("AI credit worries weigh on Wall Street", "AI 신용우려"),
    ("AI-related credit risks pressure technology shares", "AI 신용우려"),
    ("Nasdaq rebounds but AI debt worries persist", "AI 차입 우려"),
    ("CoreWeave debt burden worries lenders", "AI 차입 우려"),
    ("Neocloud borrowing concerns shake stocks", "AI 차입 우려"),
    ("CoreWeave secures financing", "AI 자금조달"),
    ("CoreWeave debt refinancing completed", "AI 차입·부채"),
    ("CoreWeave gets Goldman upgrade", "AI 인프라 관련 보도"),
    ("AI stocks bounce back after selloff", "AI 관련주 반등"),
    ("코어위브 자금 조달 확대", "AI 자금조달"),
    ("AI 신용우려에 증시 하락", "AI 신용우려"),
    ("Consumer credit worries rise", ""),
    ("Airline debt financing completed", ""),
])
def test_theme_understands_english_credit_and_explicit_ai_infrastructure(title, expected):
    assert news_theme(title) == expected


@pytest.mark.parametrize("ticker", ["SOXX", "XLK", "IGV"])
@pytest.mark.parametrize("title", ["CoreWeave debt worries persist",
                                   "Neocloud financing pressures US stocks",
                                   "AI credit risks weigh on semiconductor stocks"])
def test_ai_financing_is_shared_background_even_with_sector_words(ticker, title):
    raw = story(title)
    before = deepcopy(raw)
    linked = sector_related_news(ticker, "2026-10-20", [raw])
    assert len(linked) == 1
    assert linked[0]["market_context_only"] is True
    assert linked[0]["news_relation"] == "market_common_theme"
    assert linked[0]["exposure_theme_context"] is True
    assert raw == before
    assert not sector_related_news("XLE", "2026-10-20", [raw])


@pytest.mark.parametrize("ticker,name,title,market", [
    ("XLE", "", "US energy stocks fall as oil prices ease", "US"),
    ("XLY", "", "US consumer shares rally on retail earnings", "US"),
    ("XLV", "", "US healthcare stocks rise on pharma earnings", "US"),
    ("XLC", "", "US communication services shares gain on advertising sales", "US"),
    ("XBI", "", "US biotech stocks rise after clinical trial results", "US"),
    ("999991.KS", "KODEX K-뷰티 화장품", "화장품 수출 개선에 뷰티주 강세", "KR"),
    ("999992.KS", "TIGER 헬스케어 바이오", "바이오 임상 결과 발표로 제약주 상승", "KR"),
    ("305540.KS", "TIGER 2차전지테마", "배터리 소재 기업 실적 발표에 2차전지 강세", "KR"),
    ("999993.KS", "KODEX 필수소비재", "음식료 소비재주 실적 개선", "KR"),
    ("139250.KS", "TIGER 200에너지화학", "정유주 실적 발표에 에너지주 반등", "KR"),
])
def test_sector_vocabulary_matches_full_korean_etf_names(ticker, name, title, market):
    row = story(title, market=market, news_bucket="session_news",
                published_at="2026-10-20T14:00:00+09:00" if market == "KR" else "2026-10-20T10:30:00-04:00")
    linked = sector_related_news(ticker, "2026-10-20", [row], sector_name=name)
    assert linked and not linked[0]["market_context_only"]
    assert linked[0]["news_relation"] == "sector_report"
    assert sector_news_topics(ticker, sector_name=name)


@pytest.mark.parametrize("overrides", [
    {"session_date": "2026-10-19"},
    {"published_at": "2026-10-19T11:00:00-04:00"},
    {"news_bucket": "next_session_news"},
    {"market": "KR"},
    {"market": "CN", "news_bucket": "other_market_news"},
    {"title": "코스피 AI 신용우려로 하락"},
    {"title": "Chinese stocks fall on AI credit risks"},
    {"title": "Wall Street doubts CXMT semiconductor technology"},
])
def test_wrong_day_market_and_next_session_cannot_be_us_sector_causes(overrides):
    row = dict(story("US AI credit worries weigh on semiconductor stocks"), **overrides)
    assert not sector_related_news("SOXX", "2026-10-20", [row])


@pytest.mark.parametrize("title", ["US stock futures rise on AI financing hopes",
                                   "Wall Street Futures Rise as Technology Stocks Recover and Oil Prices Ease",
                                   "Nasdaq futures rebound after CoreWeave financing",
                                   "Wall Street outlook: AI credit risks",
                                   "US stocks set to rebound on CoreWeave news",
                                   "뉴욕증시 전망: AI 차입 우려 완화"])
def test_forecasts_are_not_observed_session_evidence(title):
    row = story(title)
    assert is_preopen_outlook(row)
    assert not sector_related_news("SOXX", "2026-10-20", [row])
    assert not market_cause_candidates([row], "US", "2026-10-20")


def test_republished_old_close_never_enters_current_us_session():
    recap = story("Wall Street stocks closed Monday on AI debt fears")
    current = story("US AI stocks rebound on CoreWeave financing")
    result = today_news.partition_session_market_news([recap, current], CLOSED, current_sessions=LIVE, now=NOW)
    assert [item["title"] for item in result["current_session_news"]] == [current["title"]]
    assert not sector_related_news("SOXX", "2026-10-20", [recap])
    assert not market_cause_candidates([recap], "US", "2026-10-20")


def test_us_current_day_uses_exchange_clock_not_kst_date():
    row = story("US biotech stocks rise on trial results", published_at="2026-10-21T00:30:00+09:00")
    result = today_news.partition_session_market_news([row], CLOSED, current_sessions=LIVE, now=NOW + timedelta(hours=1))
    assert result["current_session_news"][0]["session_date"] == "2026-10-20"
    assert sector_related_news("XBI", "2026-10-20", result["current_session_news"])
    assert not sector_related_news("XBI", "2026-10-21", result["current_session_news"])


def test_mixed_korean_outlook_retains_prior_us_recap_as_cross_market_background_only():
    raw = story("美 AI·반도체 급락 쇼크에…코스피 다시 위기감 고조", market="KR",
                published_at="2026-10-19T07:39:04+09:00")
    closed = {market: {"date": "2026-10-16", "previous_date": "2026-10-15"} for market in ("KR", "US")}
    partition = today_news.partition_session_market_news([raw], closed, now="2026-10-19T09:39:00+09:00")
    linked = sector_related_news("SOXX", "2026-10-16", partition["session_news"])
    assert linked and linked[0]["news_relation"] == "related_cross_market"
    assert linked[0]["market_context_only"]
    assert not sector_related_news("SOXX", "2026-10-19", partition["session_news"])
    reading = sector_evidence({"Ticker": "SOXX", "기준일": "2026-10-16", "1일수익률": -.04}, {}, linked)
    assert "제목 기준 보도(기사 주장" in reading["reading"]
    assert "회고 맥락" in reading["reading"] and "직접 원인 아님" in reading["reading"]


def test_matching_us_sector_report_remains_linked_after_scope_validation():
    article = story("US semiconductor stocks gain on chip earnings", news_bucket="session_news")
    linked = sector_related_news("SOXX", "2026-10-20", [article])
    result = sector_evidence({"Ticker": "SOXX", "기준일": "2026-10-20", "1일수익률": .025}, {}, linked)
    assert article["title"] in result["reading"]
    assert "인과 기여 미확정" in result["reported_background"]
    assert not linked[0]["market_context_only"]


def test_positive_observation_background_and_unexplained_excess_are_separate():
    row = {"Ticker": "IGV", "기준일": "2026-10-20", "1일수익률": .035}
    observed = {"^GSPC": {"date": "2026-10-20", "return": .01, "kind": "확정 종가"}}
    background = story("CoreWeave stocks gain on financing deal", news_bucket="session_news")
    linked = sector_related_news("IGV", "2026-10-20", [background])
    result = sector_evidence(row, {}, linked, observations=observed)
    assert "업종 상승 관측" in result["reading"]
    assert background["title"] in result["reported_background"]
    assert "직접 원인 아님" in result["reported_background"]
    assert "+2.50%p" in result["unexplained_excess"]
    assert "개별 원인 미확인" in result["reading"]
    assert result["fact"].startswith("사실:") and result["unconfirmed"].startswith("미확인:")


def test_sector_observation_keeps_aligned_oil_and_does_not_invent_missing_returns():
    row = {"Ticker": "XLE", "기준일": "2026-10-20", "1일수익률": -.02}
    result = sector_evidence(row, {"유가": {"as_of": "2026-10-20", "day_ret": -.01}}, [])
    assert "WTI -1.00%" in result["reading"] and "같은 방향" in result["reading"]
    missing = sector_evidence({"Ticker": "XLE", "기준일": "2026-10-20"}, {}, [])
    assert "미수집" in missing["reading"] and "보합" not in missing["reading"]
    assert missing["reported_background"] == missing["unexplained_excess"] == ""


def exposure_rows():
    # Symbols ending in 999xxx are synthetic product identifiers.
    names = ["반도체", "메모리", "기술", "소프트웨어", "에너지", "유틸리티", "통신",
             "소비재", "헬스케어", "바이오", "화장품", "2차전지", "금융", "산업재"]
    return [{"Ticker": "999999.KS" if market == "KR" else "FIXTURE", "섹터": name}
            for market in ("KR", "US") for name in names]


def test_targeted_queries_cover_exposures_under_global_budget_with_explicit_dates():
    closed, _ = today_news._session_news_windows(CLOSED, NOW)
    live, _ = today_news._current_news_windows(LIVE, NOW)
    rows = exposure_rows()
    before = deepcopy(rows)
    specs = today_news._session_query_specs(live + closed, (), NOW, sector_rows=rows,
                                           held_exposures=[{"Ticker": "XBI"}])
    assert 1 <= len(specs) <= 16
    assert [item["market"] for item in specs[:3]] == ["US", "KR", "US"]
    for market in ("KR", "US"):
        topics = {topic for spec in specs if spec["market"] == market for topic in spec["query_topics"]}
        assert {"energy", "consumer", "healthcare", "communications", "biotech", "cosmetics", "battery"} <= topics
    assert next(spec for spec in specs if spec["query_topics"])["query_topics"][0] == "biotech"
    queries = [parse_qs(urlsplit(spec["url"]).query)["q"][0] for spec in specs]
    assert all("after:" in query and "before:" in query and "when:" not in query for query in queries)
    assert rows == before


def rss_bytes(title="US energy stocks rise as oil gains", published=NOW - timedelta(minutes=5)):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = title
    ET.SubElement(item, "link").text = "https://www.reuters.com/exposure-feed"
    ET.SubElement(item, "source", url="https://www.reuters.com").text = "Reuters"
    ET.SubElement(item, "pubDate").text = format_datetime(published)
    return ET.tostring(root)


def test_retrieval_caps_http_requests_workers_bytes_and_timeout(monkeypatch):
    lock = Lock()
    state = {"active": 0, "peak": 0, "calls": 0}
    reads, responses = [], []

    class Response(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def fetch(request, timeout):
        assert timeout == 5
        with lock:
            state["calls"] += 1
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        sleep(.015)
        with lock:
            state["active"] -= 1
        response = Response(rss_bytes())
        responses.append(response)
        return response

    monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
    result = today_news.fetch_session_market_news(CLOSED, now=NOW, current_sessions=LIVE,
                                                 sector_rows=exposure_rows())
    assert 0 < state["calls"] <= 16 and 1 < state["peak"] <= 4
    assert reads and set(reads) == {512 * 1024 + 1}
    assert all(response.closed for response in responses)
    assert result["news_retrieval"]["query_count"] == state["calls"]
    assert result["current_session_news"] and not result["session_news"]


def test_cached_feed_does_not_refetch_or_bypass_new_now_filtering(monkeypatch):
    today_news._cached_session_rss.clear()
    calls = []

    def fetch(request, timeout):
        calls.append(request.full_url)
        return BytesIO(rss_bytes(published=NOW + timedelta(minutes=1)))

    monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
    kwargs = dict(sessions=CLOSED, current_sessions=LIVE, sector_rows=[{"Ticker": "XLE"}], use_cache=True)
    try:
        early = today_news.fetch_session_market_news(now=NOW, **kwargs)
        count = len(calls)
        later = today_news.fetch_session_market_news(now=NOW + timedelta(minutes=2), **kwargs)
        assert count > 0 and len(calls) == count
        assert not early["current_session_news"] and later["current_session_news"]
        later["current_session_news"][0]["title"] = "mutated"
        again = today_news.fetch_session_market_news(now=NOW + timedelta(minutes=2), **kwargs)
        assert again["current_session_news"][0]["title"] != "mutated"
    finally:
        today_news._cached_session_rss.clear()


def test_context_passes_held_underlyings_and_uses_cached_targeted_retrieval(monkeypatch):
    from stock_lab_core.report_context import collect_report_context

    calls = []
    monkeypatch.setattr(today_news, "fetch_session_market_news", lambda *args, **kwargs: calls.append(kwargs) or {})
    collect_report_context(summary_rows=[{"티커": "SOXL", "보유량": 1},
                                         {"티커": "379810.KS", "보유량": 1}],
                           now=NOW, price_frames={}, economic_releases=[], calendar={"events": [], "sources": []},
                           scenario_frames={}, live_frames={}, include_news=True)
    options, = calls
    tickers = {item.get("Ticker") or item.get("티커") for item in options["held_exposures"]}
    assert {"SOXL", "SOXX", "379810.KS", "QQQ"} <= tickers
    assert options["use_cache"] and "sector_rows" in options
    assert options.get("categories", ()) != ("반도체·AI", "매크로/중국")


def test_asian_headline_subject_is_not_overridden_by_wall_street_recap():
    article = story("Asian shares mostly decline after AI stocks lead a rebound on Wall Street",
                    market="US", query_market="US", source="Google News RSS",
                    published_at="2026-10-20T12:20:00+09:00")
    result = today_news.partition_session_market_news([article], CLOSED, current_sessions=LIVE, now=NOW)
    assert not result["current_session_news"] and not result["session_news"]
    assert result["other_market_news"][0]["market"] == "ASIA"


def test_preopen_price_recap_cannot_explain_that_days_closed_sector_move():
    article = story("US stocks recover after AI sell-off", session_date="2026-10-19",
                    published_at="2026-10-19T01:35:00-04:00", news_bucket="session_news")
    from stock_lab_core.report_presentation import market_cause_candidates
    assert not market_cause_candidates([article], "US", "2026-10-19")
    assert not sector_related_news("SOXX", "2026-10-19", [article])


@pytest.mark.parametrize("title", ["Nasdaq climbs as chip and AI-linked stocks bounce back",
                                  "U.S. Stocks Mostly Higher as AI Credit Worries Abate",
                                  "Palantir, Datadog and chip stocks bounce back as Amazon lifts Wall Street"])
def test_near_close_rebound_stays_with_the_completed_us_session(title):
    article = story(title, published_at="2026-10-19T16:40:00-04:00")
    result = today_news.partition_session_market_news([article], CLOSED, current_sessions=LIVE, now=NOW)
    assert not result["current_session_news"]
    recap, = result["session_news"]
    assert recap["session_date"] == "2026-10-19" and recap["retrospective_close_wrap"]
    assert sector_related_news("SOXX", "2026-10-19", [recap])


@pytest.mark.parametrize("title", ["Nasdaq futures rebound as tech shares recover",
                                  "Nasdaq shares rebound in after-hours trading"])
def test_near_close_futures_or_after_hours_are_not_regular_session_recaps(title):
    window, _ = today_news._session_news_windows(CLOSED, NOW)
    us = next(row for row in window if row["market"] == "US")
    assert not today_news._us_close_recap(title, datetime.fromisoformat("2026-10-19T16:40:00-04:00"), us)
