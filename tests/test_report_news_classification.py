from copy import deepcopy
from datetime import datetime
from email.utils import format_datetime
from io import BytesIO
import xml.etree.ElementTree as ET

from stock_lab_core import today_news
from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_evidence import curate_news

NOW = datetime.fromisoformat("2026-10-19T17:40:00+09:00")
SESSIONS = {"KR": {"date": "2026-10-19", "previous_date": "2026-10-16"},
            "US": {"date": "2026-10-16", "previous_date": "2026-10-15"}}
MARKET_VIEW = "[마켓뷰] 반도체 불안에 급락 출발했지만… 코스피, 반등 성공"
PENSION = "[마감] 상승반전 코스피, 5700선 회복… 순매수 나선 연기금"
FOREIGN = "외인·기관 매수에 삼전닉스 반전…코스피, 1.8% 상승 마감"
US_DEBT = "美증시 덮친 AI 차입우려…삼전닉스 6%대 급락 [마켓시그널]"


def article(title, hour, link, **extra):
    return dict(title=title, published_at=f"2026-10-19T{hour}:00+09:00",
                publisher="연합뉴스", link=link, **extra)


def replay_feed(monkeypatch, rows):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for row in rows:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = row["title"]
        ET.SubElement(item, "link").text = row["link"]
        ET.SubElement(item, "source", url="https://www.yna.co.kr").text = row["publisher"]
        ET.SubElement(item, "pubDate").text = format_datetime(datetime.fromisoformat(row["published_at"]))
    data = ET.tostring(root)
    calls = []
    def fetch(request, timeout):
        calls.append(request.full_url)
        return BytesIO(data)
    monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
    return calls


def test_real_collection_replay_keeps_distinct_kr_wraps_from_both_queries(monkeypatch):
    rows = [article(MARKET_VIEW, "15:49", "https://example.com/marketview"),
            article(PENSION, "16:19", "https://example.com/pension"),
            article(FOREIGN, "16:07", "https://example.com/foreign"),
            article(US_DEBT, "08:25", "https://example.com/debt")]
    # Every RSS query returns the same stories, including the wrong search market.
    calls = replay_feed(monkeypatch, rows + [deepcopy(rows[0])])
    result = today_news.fetch_session_market_news(SESSIONS, now=NOW, per_category=5)
    assert 0 < len(calls) <= 16
    assert not result["next_session_news"]
    assert len(result["session_news"]) == 4
    by_title = {row["title"]: row for row in result["session_news"]}
    for title in (MARKET_VIEW, PENSION, FOREIGN):
        assert by_title[title]["market"] == "KR"
        assert by_title[title]["session_date"] == "2026-10-19"
        assert by_title[title]["news_timing"] == "마감 후 보도"
    assert by_title[US_DEBT]["market"] == "US"
    assert by_title[US_DEBT]["session_date"] == "2026-10-16"


def test_legacy_query_tag_corrects_on_repartition_without_mutating_input():
    raw = article(MARKET_VIEW, "15:49", "https://example.com/view",
                  market="US", source="Google News RSS")
    before = deepcopy(raw)
    result = today_news.partition_session_market_news([raw], SESSIONS, now=NOW)
    assert result["session_news"][0]["market"] == "KR"
    assert result["session_news"][0]["query_market"] == "US"
    assert not result["next_session_news"] and raw == before
    again = today_news.partition_session_market_news(result["session_news"], SESSIONS, now=NOW)
    assert again["session_news"] == result["session_news"]


def test_language_publisher_and_generic_global_title_do_not_assign_market(monkeypatch):
    replay_feed(monkeypatch, [article("Global stock market mixed", "15:49", "https://example.com/global")])
    result = today_news.fetch_session_market_news(SESSIONS, now=NOW)
    assert not result["session_news"] and not result["next_session_news"]
    assert any("명시된 시장" in line for line in result["missing"])


def test_mixed_headline_without_recap_is_not_forced_into_one_market():
    row = article("코스피와 나스닥 주가 전망", "16:00", "https://example.com/mixed",
                  market="US", query_market="US")
    result = today_news.partition_session_market_news([row], SESSIONS, now=NOW)
    assert not result["session_news"] and not result["next_session_news"]


def test_explicit_non_query_metadata_and_future_timestamp_stay_protected():
    explicit = article("코스피 증시 분석", "16:00", "https://example.com/x",
                       market="US", region="KR", source="manual")
    future = article(MARKET_VIEW, "19:00", "https://example.com/y",
                     market="US", source="Google News RSS")
    result = today_news.partition_session_market_news([explicit, future], SESSIONS, now=NOW)
    assert not result["session_news"] and not result["next_session_news"]


def test_report_does_not_repeat_participant_article_in_story_or_news_list(monkeypatch):
    rows = [article(PENSION, "16:19", "https://example.com/pension"),
            article(FOREIGN, "16:07", "https://example.com/foreign")]
    replay_feed(monkeypatch, rows)
    collected = today_news.fetch_session_market_news(SESSIONS, now=NOW, per_category=5)
    context = dict(collected, news_sessions=SESSIONS,
                   sessions={market: row["date"] for market, row in SESSIONS.items()})
    report = build_auto_market_memo(report_context=context, now=NOW)
    assert "수급 주체 보도 2건" in report
    assert report.count("[마감 후 보도]") == 2
    assert "10/19 16:19 KST" in report and "10/19 16:07 KST" in report
    for row in rows:
        assert report.count(row["link"]) == 1
        assert report.count(row["title"].replace("[", "(").replace("]", ")")) == 1
    assert "추가 기사 없음" in report
    assert "제목 기준 보도(기사 주장):" not in report


def test_full_report_routes_marketview_once_not_to_next_session(monkeypatch):
    row = article(MARKET_VIEW, "15:49", "https://example.com/marketview")
    replay_feed(monkeypatch, [row])
    context = dict(today_news.fetch_session_market_news(SESSIONS, now=NOW),
                   news_sessions=SESSIONS, sessions={m: v["date"] for m, v in SESSIONS.items()})
    report = build_auto_market_memo(report_context=context, now=NOW)
    late = report.split("## 다음 세션 재료")[1].split("## 매크로 수치 근거")[0]
    assert "마켓뷰" not in late
    assert report.count(row["link"]) == 1


def test_curator_drops_revised_title_at_same_url():
    original = article("코스피 주가 반등", "15:49", "https://example.com/same")
    updated = dict(original, title="코스피 기관 매수로 반등")
    assert len(curate_news([original, updated], now=NOW)) == 1
