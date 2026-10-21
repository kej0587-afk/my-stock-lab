"""Keep prior US close recaps and pre-open forecasts out of close evidence."""

from copy import deepcopy
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from stock_lab_core.report_presentation import (
    is_preopen_outlook,
    market_cause_candidates,
    sector_related_news,
)
from stock_lab_core.today_news import partition_session_market_news
from stock_lab_core import today_news


MOSTLY_HIGHER = "U.S. Stocks Mostly Higher as AI Credit Worries Abate"
MIXED = "U.S. Stocks Mixed as Strong Earnings Offset AI Credit Fears"
LOWER_OPEN = "Wall St set for lower open as oil prices jump, earnings in focus"
NOW = datetime.fromisoformat("2026-10-21T20:15:00+09:00")
CLOSED = {"US": {"date": "2026-10-20", "previous_date": "2026-10-19"}}


def article(title, published_at):
    return dict(title=title, published_at=published_at, market="US",
                publisher="Reuters", link="https://www.reuters.com/" + title.split()[0])


def test_korean_supplier_counterparty_mention_is_not_a_us_sector_cause():
    raw = article('두산, 엔비디아 파트너사 행사에 잇달아 참가…"CCL 공급사 입지 강화"',
                  "2026-10-21T05:00:00+09:00")
    raw.update(source="Google News RSS", query_market="US", market_category="기업 재료")
    result = partition_session_market_news([raw], CLOSED, now=NOW)
    assert not result["session_news"] and not result["current_session_news"]


def test_european_earnings_do_not_explain_the_us_energy_session():
    raw = article("Europe's earnings boom widens beyond energy and AI", "2026-10-20T14:00:00-04:00")
    raw.update(source="Google News RSS", query_market="US", market_category="섹터:energy")
    result = partition_session_market_news([raw], CLOSED, now=NOW)
    assert not result["session_news"] and not result["current_session_news"]
    assert result["other_market_news"][0]["market"] == "EU"
    assert not sector_related_news("XLE", "2026-10-20", result["other_market_news"])


@pytest.mark.parametrize("previous,stamp,now", [
    ("2026-10-19", "2026-10-20T05:58:00+09:00", NOW),
    ("2026-10-16", "2026-10-17T05:58:00+09:00", NOW),
    ("2026-10-30", "2026-10-31T05:58:00+09:00",
     datetime.fromisoformat("2026-11-03T20:15:00+09:00")),
])
def test_prior_close_recap_uses_supplied_previous_session(previous, stamp, now):
    current = "2026-11-02" if previous == "2026-10-30" else "2026-10-20"
    sessions = {"US": {"date": current, "previous_date": previous}}
    raw = article(MOSTLY_HIGHER, stamp)
    original = deepcopy(raw)
    result = partition_session_market_news([raw], sessions, now=now)

    assert not result["session_news"]
    assert not result["current_session_news"]
    assert not result["next_session_news"]
    prior, = result["other_market_news"]
    assert prior["market"] == "US" and prior["session_date"] == previous
    assert prior["news_bucket"] == "other_market_news"
    assert prior["is_close_wrap"] and prior["retrospective_close_wrap"]
    assert not market_cause_candidates([prior], "US", current)
    assert not sector_related_news("XLK", current, [prior])
    assert raw == original
    assert partition_session_market_news([prior], sessions, now=now) == result


def test_current_close_recap_remains_in_confirmed_session():
    result = partition_session_market_news([
        article(MOSTLY_HIGHER, "2026-10-20T05:58:00+09:00"),
        article(MIXED, "2026-10-21T06:06:00+09:00"),
    ], CLOSED, now=NOW)

    current, = result["session_news"]
    assert current["title"] == MIXED
    assert current["session_date"] == "2026-10-20"
    assert current["retrospective_close_wrap"]
    assert result["other_market_news"][0]["title"] == MOSTLY_HIGHER


def test_live_us_keeps_prior_recap_in_supplied_closed_session():
    closed = {"US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}
    live = {"US": {"date": "2026-10-20", "previous_date": "2026-10-19"}}
    now = datetime.fromisoformat("2026-10-20T12:00:00-04:00")
    result = partition_session_market_news([
        article(MOSTLY_HIGHER, "2026-10-20T05:58:00+09:00"),
        article("U.S. chip stocks rise", "2026-10-20T11:30:00-04:00"),
    ], closed, current_sessions=live, now=now)

    recap, = result["session_news"]
    assert recap["title"] == MOSTLY_HIGHER
    assert recap["session_date"] == "2026-10-19"
    assert recap["retrospective_close_wrap"]
    current, = result["current_session_news"]
    assert current["session_date"] == "2026-10-20"
    assert not result["other_market_news"]


def test_new_overnight_event_after_previous_close_remains_current_material():
    raw = article("U.S. chipmaker announces new AI credit facility",
                  "2026-10-20T05:58:00+09:00")
    result = partition_session_market_news([raw], CLOSED, now=NOW)

    current, = result["session_news"]
    assert current["session_date"] == "2026-10-20"
    assert not current["is_close_wrap"]
    assert not result["other_market_news"]


@pytest.mark.parametrize("title", [
    LOWER_OPEN,
    "Wall Street set for higher open as earnings improve",
    "U.S. stocks set for rebound as AI credit worries abate",
    "Stocks are poised for gains ahead of earnings",
    "Stocks expected to rise as oil prices ease",
])
def test_preopen_forecasts_cannot_supply_close_or_sector_evidence(title):
    row = article(title, "2026-10-20T20:00:00+09:00")
    row.update(session_date="2026-10-20", news_bucket="session_news")

    assert is_preopen_outlook(row)
    assert not market_cause_candidates([row], "US", "2026-10-20")
    assert not sector_related_news("XLE", "2026-10-20", [row])
    assert not sector_related_news("XLK", "2026-10-20", [row])


@pytest.mark.parametrize("title", [
    MOSTLY_HIGHER,
    MIXED,
    "U.S. stocks rebound as AI credit worries abate",
    "Oil prices jump as producers cut supply",
])
def test_observed_moves_are_not_preopen_forecasts(title):
    assert not is_preopen_outlook({"title": title, "market": "US"})


def test_korean_company_query_preserves_background_and_topic_budget():
    now = datetime.fromisoformat("2026-10-20T11:00:00-04:00")
    closed = {"KR": {"date": "2026-10-20", "previous_date": "2026-10-19"},
              "US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}
    live = {"US": {"date": "2026-10-20", "previous_date": "2026-10-19"}}
    windows, _ = today_news._session_news_windows(closed, now)
    active, _ = today_news._current_news_windows(live, now)
    names = ["반도체", "메모리", "기술", "소프트웨어", "에너지", "유틸리티", "통신",
             "소비재", "헬스케어", "바이오", "화장품", "2차전지", "금융", "산업재"]
    rows = [{"Ticker": "999999.KS" if market == "KR" else "FIXTURE", "섹터": name}
            for market in ("KR", "US") for name in names]
    specs = today_news._session_query_specs(active + windows, (), now, sector_rows=rows,
                                           held_exposures=[{"Ticker": "XBI"}])

    assert len(specs) <= 16
    assert [item["market"] for item in specs[:3]] == ["US", "KR", "US"]
    company_specs = [spec for spec in specs if spec["category"] == "기업 재료"]
    assert 1 <= len(company_specs) <= 2
    background_specs = [spec for spec in specs if spec["category"] == "시장 공통 배경" and spec["market"] == "US"]
    assert len(background_specs) == 2
    assert all("credit OR debt OR financing" in parse_qs(urlsplit(spec["url"]).query)["q"][0]
               for spec in background_specs)
    for spec in company_specs:
        params = parse_qs(urlsplit(spec["url"]).query)
        query = params["q"][0]
        assert spec["market"] == "US" and not spec["query_topics"]
        assert params["hl"] == ["ko"] and params["ceid"] == ["KR:ko"]
        assert query.startswith("(엔비디아 OR 아마존 OR AWS OR 메타 OR 마이크론 OR 코어위브)")
        assert "칩 OR 공급 OR 자금조달 OR 실적" in query
        assert "after:" in query and "before:" in query
        assert "Wall Street" not in query and "U.S." not in query
    for market in ("KR", "US"):
        topics = {topic for spec in specs if spec["market"] == market for topic in spec["query_topics"]}
        assert {"energy", "consumer", "healthcare", "communications", "biotech", "cosmetics", "battery"} <= topics
    assert next(spec for spec in specs if spec["query_topics"])["query_topics"][0] == "biotech"


@pytest.mark.parametrize("ticker", ["SOXX", "DRAM", "XLK", "IGV"])
def test_ai_exposure_enables_one_company_query_per_us_window(ticker):
    windows, _ = today_news._session_news_windows(CLOSED, NOW)
    specs = today_news._session_query_specs(windows, (), NOW, held_exposures=[{"Ticker": ticker}])
    assert sum(spec["category"] == "기업 재료" for spec in specs) == 1


@pytest.mark.parametrize("company", ["엔비디아", "아마존 AWS", "메타", "마이크론", "코어위브"])
def test_korean_company_headlines_remain_us_live_material(company):
    now = datetime.fromisoformat("2026-10-20T11:00:00-04:00")
    closed = {"US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}
    live = {"US": {"date": "2026-10-20", "previous_date": "2026-10-19"}}
    raw = article(company + " 신규 칩 공급 및 실적 발표", "2026-10-20T10:30:00-04:00")
    raw.update(source="Google News RSS", query_market="US", market_category="기업 재료")
    result = partition_session_market_news([raw], closed, current_sessions=live, now=now)

    current, = result["current_session_news"]
    assert current["market"] == "US" and current["session_date"] == "2026-10-20"
    assert current["market_basis"] == "explicit_headline_market"
    assert current["market_category"] != "기업 재료"


def test_company_query_category_is_not_sector_or_market_evidence():
    raw = article("Dow leads Wall Street higher on earnings", "2026-10-20T14:00:00-04:00")
    raw.update(source="Google News RSS", query_market="US", market_category="기업 재료")
    result = partition_session_market_news([raw], CLOSED, now=NOW)
    row, = result["session_news"]
    assert row["market_category"] == "시장"
    assert not sector_related_news("SOXX", "2026-10-20", [row])

    korean = dict(raw, title="코스피 엔비디아 반도체 강세 마감", published_at="2026-10-21T16:00:00+09:00")
    sessions = dict(CLOSED, KR={"date": "2026-10-21", "previous_date": "2026-10-20"})
    result = partition_session_market_news([korean], sessions, now=NOW)
    assert result["session_news"][0]["market"] == "KR"
    assert not sector_related_news("SOXX", "2026-10-20", result["session_news"])


@pytest.mark.parametrize("title", [
    "(마감) 코스피 3% 상승, 美 실적 기대감… 돌아온 외인 매수",
    "[마감] 코스닥 상승, 미국 실적 기대감에 외인 매수",
    "코스피 3% 상승 마감, 뉴욕증시 반등에 외국인 매수",
    "美 AI 실적 기대감에 코스피 3% 상승 마감",
])
def test_explicit_kr_close_subject_wins_over_us_background(title):
    sessions = dict(CLOSED, KR={"date": "2026-10-21", "previous_date": "2026-10-20"})
    raw = article(title, "2026-10-21T16:17:00+09:00")
    raw.update(source="Google News RSS", query_market="US")
    original = deepcopy(raw)
    result = partition_session_market_news([raw], sessions, now=NOW)

    row, = result["session_news"]
    assert row["market"] == "KR" and row["session_date"] == "2026-10-21"
    assert row["post_close_context"]
    assert row["query_market"] == "US"
    assert not market_cause_candidates([row], "US", "2026-10-20")
    assert not sector_related_news("SOXX", "2026-10-20", [row])
    windows, _ = today_news._session_news_windows(sessions, NOW)
    us = next(window for window in windows if window["market"] == "US")
    assert not today_news._us_close_recap(title, datetime.fromisoformat(raw["published_at"]), us)
    assert raw == original
    assert partition_session_market_news([row], sessions, now=NOW) == result


def test_explicit_us_shock_can_still_supply_cross_market_recap():
    sessions = {market: {"date": "2026-10-16", "previous_date": "2026-10-15"}
                for market in ("KR", "US")}
    raw = article("美 AI·반도체 급락 쇼크에…코스피 다시 위기감 고조",
                  "2026-10-19T07:39:04+09:00")
    raw.update(source="Google News RSS", query_market="KR", market="KR")
    result = partition_session_market_news([raw], sessions, now="2026-10-19T09:39:00+09:00")

    row, = result["session_news"]
    assert row["market"] == "US" and row["session_date"] == "2026-10-16"
    linked, = sector_related_news("SOXX", "2026-10-16", [row])
    assert linked["market_context_only"]
    assert linked["news_relation"] == "related_cross_market"


@pytest.mark.parametrize("market", ["KR", "US"])
def test_us_close_with_domestic_outlook_is_not_pure_market_evidence(market):
    title = "[마켓뷰] 메타 실적발표 앞두고 뉴욕증시 혼조 마감…코스피 향방은"
    row = article(title, "2026-10-21T08:08:00+09:00")
    row.update(market=market, session_date="2026-10-20", news_bucket="session_news")

    assert is_preopen_outlook(row)
    assert not market_cause_candidates([row], "US", "2026-10-20")
    assert not sector_related_news("XLC", "2026-10-20", [row])
    windows, _ = today_news._session_news_windows(CLOSED, NOW)
    assert not today_news._us_close_recap(title, datetime.fromisoformat(row["published_at"]), windows[0])
    row.update(source="Google News RSS", query_market=market)
    sessions = dict(CLOSED, KR={"date": "2026-10-21", "previous_date": "2026-10-20"})
    result = partition_session_market_news([row], sessions, now=NOW)
    assert not result["session_news"]
    assert not result["current_session_news"]


def test_pure_us_closing_fact_is_not_domestic_outlook():
    row = article("메타 실적발표 앞두고 뉴욕증시 혼조 마감", "2026-10-21T08:08:00+09:00")
    row.update(source="Google News RSS", query_market="US")
    assert not is_preopen_outlook(row)
    result = partition_session_market_news([row], CLOSED, now=NOW)
    recap, = result["session_news"]
    assert recap["market"] == "US" and recap["session_date"] == "2026-10-20"
    assert recap["retrospective_close_wrap"]
