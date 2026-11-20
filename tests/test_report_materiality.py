"""Pure main-path selection; synthetic evidence, no provider requests."""

from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_brief import (
    brief_theme, build_news_brief, explicit_news_market, material_news, news_observation,
)
from stock_lab_core.report_coverage import context_news_lines
from tests.test_report_brief import article, CONTEXT, NOW


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests
    import urllib.request
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: pytest.fail("Unexpected HTTP"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("Unexpected HTTP"))


@pytest.mark.parametrize("title", [
    "우리은행, 임직원과 폐전자제품 모아 재활용",
    "국민은행, 비대면 상속서비스 제공",
    "반도체 캠퍼스 인접한 신규 분양 단지",
    "(인물열전) 중동 평화의 역사적 인물",
    "바이오 주가의 지난 이야기(급등주 지금은)",
    "금리 방향 고민…회사채 단기 투자 (채권투자 길라잡이)",
    "코스닥 반도체 주식을 담았다 (이런 펀드 어때요?)",
    "Is Earnings Beat Altering The Investment Case For Fortinet Stock?",
    "Is Example Company Cheap On Earnings And Guidance?",
    "Example Company Keeps Guidance Intact, Is The Stock A Bargain?",
    "Amazon is cheaper than Walmart on earnings",
    "Intel Stock Sees Fair Value Fall After Guidance",
    "How Earnings And Guidance Will Impact BP Stock Investors",
    "테슬라 반도체",
])
def test_nonmaterial_mentions_stay_out_of_both_main_tables_without_mutating_original(title):
    row = article(title)
    before = deepcopy(row)
    assert not build_news_brief(CONTEXT, [row], [], NOW, limit=None, compact=True)["article_keys"]
    global_row = dict(row, market="GLOBAL", news_bucket="other_market_news")
    assert context_news_lines({"other_market_news": [global_row]}, NOW, bucket="other_market_news") == []
    assert row == before  # The original evidence remains available to the appendix.


@pytest.mark.parametrize("title", [
    "Fed financial stability report warns about stock market valuations",
    "Fed's Williams says central bank has work to do on inflation",
    "Walmart reports stronger revenue and raises guidance",
    "JPMorgan raises loan loss provisions as credit defaults increase",
    "Eli Lilly clinical trial results meet primary endpoint",
    "Exxon Mobil raises capital expenditure plan",
    "CoreWeave debt refinancing announced",
    "NVIDIA export restrictions expanded",
    "NVIDIA announces CEO succession plan",
    "Oracle signs new cloud contract",
    "Modine shares rise on acquisition talks",
    "BOJ cuts bond purchases in liquidity policy update",
    "은행 수수료이익 증가…분기 실적 발표",
])
def test_material_events_do_not_need_fetched_body_or_fixed_issuer_membership(title):
    assert material_news(article(title))
    row = article(title, market="GLOBAL")
    output = "\n".join(context_news_lines({"other_market_news": [row]}, NOW, bucket="other_market_news"))
    assert title in output and row["link"] in output


def test_valuation_question_with_collected_body_fact_retains_fact_source_and_reading():
    row = article("Is Walmart Cheap On Earnings?")
    row.update(body_status="verified", body_facts=[dict(topic="earnings", summary="Collected revenue result",
               implication="Conditional demand reading", check="Next guidance release")])
    output = "\n".join(build_news_brief(CONTEXT, [row], [], NOW, limit=None, compact=True)["lines"])
    for value in (row["link"], "Collected revenue result", "Conditional demand reading", "Next guidance release"):
        assert value in output
    assert "해석(추정)" in output and "공식 확인" not in output


@pytest.mark.parametrize("title", [
    "Fed's Williams says central bank needs to curb inflation",
    "뉴욕연은 윌리엄스 총재, 금리 정책 발언",
    "Bank of Japan announces interest rate decision",
])
def test_policy_speakers_never_become_commercial_bank_issuer_sector(title):
    assert brief_theme(article(title), comprehensive=True) == "금리·경제지표"


def test_domestic_issuer_query_mistag_is_dated_context_never_us_holding_attribution():
    row = article("제주반도체 분기 실적 발표", market_basis="search_query_only", query_market="US")
    context = dict(CONTEXT, session_news=[row])
    before = deepcopy(context)
    assert explicit_news_market(row) == "KR"
    assert not build_news_brief(context, [row], [{"티커": "SOXL", "보유량": 1}], NOW, limit=None)["article_keys"]
    output = "\n".join(context_news_lines(context, NOW, bucket="other_market_news"))
    assert row["link"] in output and "KR 기업·시장 재료" in output and "종가 귀속 미확인" in output
    assert "SOXL" not in output and "US 2026-10-20 종가 세션" not in output
    assert context == before


def test_current_closing_wrap_precedes_morning_body_and_both_observation_times_survive():
    morning = article("코스피, 장초반 은행주 상승", market="KR", session_date="2026-10-21",
                      published_at="2026-10-21T09:26:00+09:00", body_status="verified",
                      body_facts=[dict(topic="earnings", summary="Collected morning fact", implication="Conditional reading", check="Closing follow-up")])
    close = article("코스피, 은행주 약세에 하락 마감", market="KR", session_date="2026-10-21",
                    published_at="2026-10-21T16:00:00+09:00", is_close_wrap=True, link="https://www.reuters.com/closing")
    result = build_news_brief(CONTEXT, [morning, close], [], NOW, limit=None, compact=True)
    assert result["article_keys"] == [close["link"], morning["link"]]
    output = "\n".join(result["lines"])
    assert "마감 보도 · 기사 주장" in output and "장중 관측 · 종가와 구분" in output
    assert "Collected morning fact" in output and "왜 움직였나" not in output


@pytest.mark.parametrize("day,previous,published,now", [
    ("2026-10-20", "2026-10-19", "2026-10-20T05:02:00+09:00", "2026-10-21T20:00:00+09:00"),
    ("2026-11-06", "2026-11-05", "2026-11-06T06:02:00+09:00", "2026-11-07T20:00:00+09:00"),
])
def test_previous_us_close_is_not_relabelled_to_korean_calendar_day(day, previous, published, now):
    context = {"sessions": {"US": day}, "news_sessions": {"US": {"date": day, "previous_date": previous}}}
    row = article("나스닥 하락…유가 상승에 에너지주 강세", published_at=published, session_date=day)
    result = build_news_brief(context, [row], [], datetime.fromisoformat(now), limit=None, compact=True)
    output = "\n".join(result["lines"])
    assert row["link"] in output
    # The headline does not claim a closing recap; retain the prior local date
    # without promoting a generic report to an observed close.
    assert f"US {previous} 이전 거래일 보도·장전 재료" in output and f"{day} 종가 원인 미확인" in output
    assert "이전 종가 관측" not in output
    assert f"US {day} 종가 세션" not in output


def test_intraday_window_end_is_collection_clock_not_exchange_close():
    context = {"current_windows": [{"market": "US", "date": "2026-10-20", "open_at": "2026-10-20T09:30:00-04:00",
                "end": "2026-10-20T15:00:00-04:00", "scheduled_close": "2026-10-20T16:00:00-04:00"}]}
    assert "장중 관측" in news_observation(article("Stocks rise"), context)[1]


def test_news_capture_end_next_day_is_not_exchange_close_in_either_table():
    context = {**CONTEXT, "windows": [{"market": "US", "date": "2026-10-20",
                "end": "2026-10-21T23:59:00-04:00"}]}
    wrap = article("US stocks close higher", published_at="2026-10-20T16:02:00-04:00", is_close_wrap=True)
    assert "마감 보도" in news_observation(wrap, context)[1]
    later = article("Oracle reports earnings", published_at="2026-10-20T17:00:00-04:00", news_bucket="next_session_news")
    context["next_session_news"] = [later]
    output = "\n".join(context_news_lines(context, NOW, bucket="next_session_news", market="US"))
    assert later["link"] in output and "마감 후·다음 세션" in output


@pytest.mark.parametrize("field", ["scheduled_close", "close_at"])
def test_explicit_short_session_close_takes_precedence_over_news_boundary(field):
    context = {"news_sessions": {"US": {"date": "2026-10-20", field: "2026-10-20T13:00:00-04:00"}},
               "windows": [{"market": "US", "date": "2026-10-20", "end": "2026-10-21T23:59:00-04:00"}]}
    row = article("Stocks close higher", published_at="2026-10-20T13:02:00-04:00", is_close_wrap=True)
    assert "마감 보도" in news_observation(row, context)[1]


def test_already_partitioned_previous_close_keeps_prior_label_and_missing_session_is_safe():
    row = article("US stocks close higher", session_date="2026-10-19", published_at="2026-10-19T16:02:00-04:00",
                  news_bucket="other_market_news", is_close_wrap=True)
    output = "\n".join(context_news_lines({**CONTEXT, "other_market_news": [row]}, NOW, bucket="other_market_news"))
    assert "US 2026-10-19 이전 종가 관측" in output
    row["session_date"] = "unconfirmed"
    assert "거래일 귀속 미확인" in news_observation(row, CONTEXT)[1]


@pytest.mark.parametrize("changes", [
    {"published_at": "2026-10-20"}, {"published_at": "2026-10-22T00:00:00+09:00"},
    {"publisher": "Unverified", "link": "https://invalid.example/news"},
])
def test_context_materiality_does_not_relax_time_or_source_validation(changes):
    row = dict(article("BOJ raises rates"), market="JP", **changes)
    assert context_news_lines({"other_market_news": [row]}, NOW, bucket="other_market_news") == []
