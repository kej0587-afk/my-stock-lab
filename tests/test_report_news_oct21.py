"""Replay report (8) headlines without external requests or trading changes."""

from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.economic_cache import collection_status
from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_evidence import curate_news
from stock_lab_core.today_news import partition_session_market_news


NOW = datetime.fromisoformat("2026-10-21T12:45:00+09:00")
CLOSED = {market: {"date": "2026-10-20", "previous_date": "2026-10-19"} for market in ("KR", "US")}
LIVE = {"KR": {"date": "2026-10-21", "previous_date": "2026-10-20"}}
REBOUND = "코스피, 국제유가·금리 안정에 반등…삼전·SK닉스 3%대 상승"
DECLINE = "코스피, 외국인·기관 매도에 3.73% 급락…5500선 후퇴"
MIXED = "U.S. Stocks Mixed as Strong Earnings Offset AI Credit Fears"


def article(title, timestamp, path, *, market="KR", publisher="서울경제"):
    return dict(title=title, published_at=timestamp, link="https://example.com/" + path,
                publisher=publisher, market=market, query_market=market, source="Google News RSS")


def partition(rows):
    return partition_session_market_news(rows, CLOSED, current_sessions=LIVE, now=NOW)


def context(rows):
    return dict(partition(rows), news_sessions=CLOSED, current_news_sessions=LIVE,
                sessions={market: row["date"] for market, row in CLOSED.items()},
                intraday_prices={"^KS11": {"date": "2026-10-21", "return": .0304,
                                          "as_of": NOW.isoformat()}},
                prices={"^KS11": {"date": "2026-10-20", "return": -.0373}})


def test_previous_postclose_is_not_reassigned_to_today_preopen():
    rows = [article(DECLINE, "2026-10-20T16:23:00+09:00", "close"),
            article("2번 연속 금리 올린 한국은행…또 올리나", "2026-10-20T17:52:00+09:00", "bok", market="US"),
            article(REBOUND, "2026-10-21T09:20:00+09:00", "rebound"),
            article("코스피, 반등 전망", "2026-10-21T08:18:00+09:00", "outlook")]
    original = deepcopy(rows)
    result = partition(rows)
    assert {row["link"] for row in result["session_news"]} == {rows[0]["link"], rows[1]["link"]}
    assert all(row["news_timing"] == "마감 후 보도" and row["session_date"] == "2026-10-20"
               and row["market"] == "KR" for row in result["session_news"])
    live = {row["title"]: row for row in result["current_session_news"]}
    assert live[REBOUND]["news_timing"] == "장중 보도"
    assert live[rows[3]["title"]]["news_timing"] == "장전 보도"
    assert rows == original
    assert partition(result["session_news"] + result["current_session_news"]) == result


def test_us_mixed_recap_is_closed_but_afterhours_forecast_and_late_story_are_not():
    rows = [article(MIXED, "2026-10-21T06:06:00+09:00", "mixed", market="US"),
            article("U.S. stocks mixed in after-hours trading", "2026-10-21T06:06:00+09:00", "after", market="US"),
            article("U.S. stock futures mixed ahead of earnings", "2026-10-21T06:06:00+09:00", "futures", market="US"),
            article(MIXED, "2026-10-21T09:06:00+09:00", "late", market="US")]
    result = partition(rows)
    recap, = result["session_news"]
    assert recap["session_date"] == "2026-10-20" and recap["retrospective_close_wrap"]
    assert recap["news_timing"] == "미국장 마감 회고 · 기사 주장"
    assert {row["link"] for row in result["next_session_news"]} == {row["link"] for row in rows[1:]}


def test_rebound_background_is_connected_once_and_wrong_session_is_not_reused():
    rebound = article(REBOUND, "2026-10-21T09:20:00+09:00", "rebound")
    report = build_auto_market_memo(report_context=context([rebound]), now=NOW)
    assert "배경 보도 | 유가·금리 안정(기사 주장" in report
    assert report.count(rebound["link"]) == 1
    assert "당일 시장 방향과 연결할 배경 보도 미확보" not in report
    old = dict(rebound, published_at="2026-10-20T09:20:00+09:00")
    report = build_auto_market_memo(report_context=context([old]), now=NOW)
    assert "배경 보도 | 당일 시장 방향과 연결할 배경 보도 미확보" in report
    falling = context([rebound])
    falling["intraday_prices"]["^KS11"]["return"] = -.03
    report = build_auto_market_memo(report_context=falling, now=NOW)
    assert "배경 보도 | 유가·금리 안정" not in report


def test_cross_publisher_same_closing_move_group_keeps_sources_once():
    rows = [article(DECLINE, "2026-10-20T16:23:00+09:00", "one"),
            article("코스피 3.73% 급락 마감, 외국인 매도", "2026-10-20T16:10:00+09:00", "two", publisher="뉴시스"),
            article("코스피 3.73% 하락 마감, 연기금 저가 매수", "2026-10-20T15:46:00+09:00", "three", publisher="이데일리")]
    collected = partition(rows)["session_news"]
    original = deepcopy(collected)
    grouped = curate_news(collected + [collected[0]], now=NOW, limit=10, session_scoped=True)
    assert len(grouped) == 1 and grouped[0]["duplicate_count"] == 3
    assert {row["publisher"] for row in [grouped[0], *grouped[0]["related_articles"]]} == {"서울경제", "뉴시스", "이데일리"}
    assert curate_news(grouped, now=NOW, session_scoped=True) == grouped
    assert collected == original
    report = build_auto_market_memo(report_context=context(rows), now=NOW)
    assert "같은 시장·거래일 마감 등락 보도 3건 묶음" in report
    for row in rows:
        assert report.count(row["link"]) == 1
    assert "연기금 저가 매수" in report
    assert DECLINE not in report.split("## 추가 핵심 뉴스")[1]


@pytest.mark.parametrize("change", [
    {"session_date": "2026-10-19"},
    {"title": "코스닥 3.73% 급락 마감"},
    {"title": "코스피 3.73% 상승 마감"},
    {"title": "코스피 3.74% 급락 마감"},
    {"title": "코스피 혼조, 코스닥 3.73% 급락 마감"},
    {"news_bucket": "current_session_news", "is_close_wrap": False},
])
def test_different_market_day_move_or_live_session_is_not_same_event(change):
    base = partition([article(DECLINE, "2026-10-20T16:23:00+09:00", "one")])["session_news"][0]
    other = dict(base, title="코스피 3.73% 급락 마감", link="https://example.com/two")
    other.update(change)
    assert len(curate_news([base, other], now=NOW, limit=10, session_scoped=True)) == 2


@pytest.mark.parametrize("row,expected", [
    ({"status": "released", "actual": 83.7}, "관측치 수집 성공"),
    ({"status": "released", "actual": 0, "missing_reason": "release_date_unavailable"}, "관측치 수집 성공 · 발표일 미확인"),
    ({"status": "stale", "actual": 83.7, "collection_error": "ReadTimeout"}, "응답 시간 초과"),
    ({"status": "stale", "actual": 83.7}, "최신 관측치 미확인 · 과거 성공값 사용"),
    ({"status": "verified_snapshot", "actual": 83.7}, "수동 보완값 사용 · 자동 수집 성공 아님"),
    ({"status": "pending", "actual": None}, "발표 대기"),
    ({"status": "unavailable", "actual": None, "request_metadata": {"http_status": 200}}, "HTTP 응답 정상 · 유효 관측치 미확인"),
    ({"status": "released", "actual": float("nan")}, "공급처 응답/관측치 확인 실패"),
])
def test_collection_status_distinguishes_value_transport_and_fallback(row, expected):
    assert collection_status(row) == expected


def test_successful_exports_diagnostic_does_not_report_failure():
    ctx = context([])
    ctx["economic_releases"] = [{"indicator": "KR_EXPORTS", "status": "released", "actual": 83.7,
        "period": "2026-09", "unit": "%", "basis": "YoY", "source": "Korea Customs Service",
        "bulletin_request_metadata": {"listing": {"http_status": 200}, "detail": {"http_status": 200}}}]
    report = build_auto_market_memo(report_context=ctx, now=NOW)
    diagnostic = next(line for line in report.splitlines() if line.startswith("한국 수출 자동 수집:"))
    assert "관측치 수집 성공" in diagnostic and "실패" not in diagnostic
