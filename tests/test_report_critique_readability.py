"""Offline regression cases for the report critique; values are test inputs."""

from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_analysis import economic_reaction_text, sector_evidence
from stock_lab_core.report_evidence import macro_stress
from stock_lab_core.report_presentation import account_live_estimate, macro_change, market_cause_candidates


NOW = datetime.fromisoformat("2026-10-20T23:48:00+09:00")


def wrap(**overrides):
    return dict(dict(title="[마감] 코스피, AI 신용우려에 하락", market="KR", session_date="2026-10-20",
                     publisher="조선비즈", link="https://biz.chosun.com/stock/fixture",
                     published_at="2026-10-20T16:15:00+09:00", news_bucket="session_news",
                     retrospective_close_wrap=True, news_timing="마감 후 보도"), **overrides)


def report_case():
    context = dict(sessions={"KR": "2026-10-20", "US": "2026-10-19"}, prices={
        "^KS11": {"date": "2026-10-20", "return": -.0373, "return_5d": -.08},
        "^GSPC": {"date": "2026-10-19", "return": .0041},
        "SOXX": {"date": "2026-10-19", "return": .0173},
        "IGV": {"date": "2026-10-19", "return": .0158},
        "305540.KS": {"date": "2026-10-20", "return": -.0572}},
        session_news=[wrap(), wrap(title="코스피 하락 마감", link="https://biz.chosun.com/stock/second")],
        sector_rows=[{"Ticker": "305540.KS", "섹터": "2차전지", "구분": "한국 섹터", "기준일": "2026-10-20",
                      "1일수익률": -.0572, "3개월수익률": .099, "가속도": .309, "상태": "급반등"}],
        economic_releases=[dict(indicator="KR_EXPORTS", period="2026-09", basis="YoY", unit="%",
                                actual=83.7, previous=68.9, status="released", source="Official fixture",
                                source_url="https://www.customs.go.kr/fixture", release_at="2026-10-01")],
        calendar_events=[dict(title="Test earnings", date="2026-10-21", source="Official fixture",
                              source_url="https://example.org/earnings", session_timing="after_market_close",
                              conference_call_at="2026-10-21T13:30:00-07:00")])
    rows = [{"티커": "SOXX", "종목명": "반도체", "현재비중": 25, "보유량": 1},
            {"티커": "305540.KS", "종목명": "2차전지", "현재비중": 75, "보유량": 1},
            {"티커": "TEST", "종목명": "후보 | 검증", "보유량": 0, "후보품질": "S급",
             "게이트상태": "방어우선", "게이트근거": "시장방어 | 추세훼손", "Adj점수": 9}]
    return context, rows


def test_postclose_candidate_is_cited_once_without_explaining_sector_excess():
    context, rows = report_case()
    before = deepcopy((context, rows))
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    story = report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    sectors = report.split("## 업종별 왜")[1].split("## 관심 후보")[0]
    assert "보도상 배경 후보 | 대상 거래일 | 출처·보도 시각" in story
    assert context["session_news"][0]["title"] in story and "10/20 16:15 KST" in story
    assert "인과·기여도는 미확정" in story and "파급 범위" in story
    # Cite the market conclusion and its evidence table, not an extra news item.
    assert report.count(context["session_news"][0]["link"]) == 2
    assert "개별 원인 미확인" in sectors and "AI 신용우려" not in sectors
    assert (context, rows) == before


@pytest.mark.parametrize("overrides", [
    {"session_date": "2026-10-19"}, {"market": "JP"}, {"link": ""},
    {"published_at": "2026-10-19T16:15:00+09:00"},
    {"news_bucket": "next_session_news"}, {"news_bucket": "other_market_news"},
    {"title": "[증시전망] 코스피 AI 신용우려에 하락 예상"},
    {"title": "코스피 AI 신용우려 후속 소식", "retrospective_close_wrap": False},
])
def test_candidate_excludes_forecasts_wrong_dates_markets_and_followups(overrides):
    assert not market_cause_candidates([wrap(**overrides)], "KR", "2026-10-20")


@pytest.mark.parametrize("status,actual,release_at,expected", [
    ("unavailable", None, "", "공급처 HTTP 오류"),
    ("released", .6, "", "발표일 미연결"),
    ("pending", None, "2026-11-10", "발표 예정 상태"),
    ("stale", .5, "2026-09-10", "마지막 성공값 표시"),
])
def test_collection_status_is_not_an_unpublished_release(status, actual, release_at, expected):
    row = dict(status=status, actual=actual, release_at=release_at, missing_reason="http_500",
               reaction="발표일 미연결/미발표로 동일일 비교 보류", reaction_source="Daily fixture")
    result = economic_reaction_text(row)
    assert expected in result and "미연결/미발표" not in result
    if actual is None and status == "unavailable":
        assert "발표 여부 미확인" in result and "예정" not in result


def test_key_failure_and_valid_release_reaction_remain_explicit():
    context, rows = report_case()
    context["economic_releases"] = [dict(indicator="US_CPI", basis="MoM", unit="%", actual=None,
        status="unavailable", source="BLS", missing_reason="API_KEY_missing", api_key_configured=False)]
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    assert "키 미설정 · 키 미감지" in report
    assert economic_reaction_text(dict(actual=.6, status="released", release_at="2026-10-14",
        reaction_source="Daily fixture", reaction="10Y +4.00bp")) == "10Y +4.00bp"


def test_monthly_exports_are_compared_outside_current_news_story():
    context, rows = report_case()
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    story = report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    table = report.split("월간 실물·단기 가격 비교")[1].split("## 업종별 왜")[0]
    assert "83.7" not in story
    assert "전년비 +83.7%" in table and "5D -8.00%" in table
    assert "관측월 2026-09" in table and "발표 2026-10-01" in table
    assert "원인을 확정하지 않습니다" in table
    context["economic_releases"][0]["status"] = "stale"
    assert "월간 실물·단기 가격 비교" not in build_auto_market_memo(report_context=context, now=NOW)


def test_stress_shows_zero_contributions_while_values_change_without_rescaling():
    current = {name: dict(val=value, chg=change, as_of="2026-10-19") for name, value, change in
               (("10Y 금리", 5.14, 2.76), ("VIX", 18.44, 24.51), ("MOVE", 101.30, 32.9),
                ("유가", 103.66, 3.35), ("환율", 1333.43, -3.34))}
    previous = deepcopy(current)
    previous["VIX"].update(val=19.0, chg=25.0, as_of="2026-10-16")
    before = deepcopy((previous, current))
    result = macro_change(previous, current)
    assert macro_stress(previous)["score"] == macro_stress(current)["score"] == 92
    assert "스트레스 92→92" in result and "19.00→18.44" in result
    assert "+25.00%→+24.51%" in result
    rows = [line for line in result.splitlines() if line.startswith(("10Y 금리 |", "VIX |", "MOVE |", "WTI 선물", "환율 |"))]
    assert len(rows) == 5 and all(line.endswith(" | +0") for line in rows)
    assert "기여 Δ 0은 가격 불변을 뜻하지 않습니다" in result and "신용 스프레드" in result
    assert (previous, current) == before


def test_live_quote_time_single_value_or_real_range():
    held = [{"티커": ticker, "현재비중": 25} for ticker in ("SOXX", "IGV")]
    live = {ticker: dict(date="2026-10-20", **{"return": .01}, as_of="2026-10-20T23:45:00+09:00")
            for ticker in ("SOXX", "IGV")}
    assert "시세 2026-10-20 23:45 KST ·" in account_live_estimate(held, live)
    live["IGV"]["as_of"] = "2026-10-20T23:40:00+09:00"
    assert "23:40 KST~2026-10-20 23:45 KST" in account_live_estimate(held, live)


def test_tables_keep_dates_returns_weights_gates_and_calendar_sources():
    context, rows = report_case()
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    sector = next(line for line in report.splitlines() if line.startswith("2차전지(305540.KS) |") and "일간 -5.72%" in line)
    assert "일간 -5.72% · 2026-10-20" in sector
    assert "3M +9.9% · 가속도 +30.9%p · [3M 중기] 급반등" in sector
    holding = next(line for line in report.splitlines() if line.startswith("반도체(SOXX) |"))
    assert "현재비중 25.00%" in holding and "일간 기여 +0.43%p(내부 추정)" in holding
    assert "후보 / 검증(TEST) · 개별 신호 S급, 게이트로 보류" in report
    assert "시장방어 / 추세훼손" in report and "일봉·주봉 추세훼손 해제" in report
    assert "Test earnings · D-2 | 미국 2026-10-21 장 마감 후" in report
    assert "실적 콜 2026-10-22 05:30 KST" in report and "https://example.org/earnings" in report
    assert "다음 세션 재료가 비어 있어도 마감 후 회고" in report
    # Pipes inside source text must not add cells to any generated table.
    width = None
    for line in report.splitlines():
        if " | " not in line:
            width = None
        elif line.startswith("--- |"):
            width = len(line.split(" | "))
        elif width:
            assert len(line.split(" | ")) == width, line


def test_sector_state_exposes_price_location_without_changing_source_grade():
    row = {"Ticker": "XLE", "기준일": "2026-10-19", "1일수익률": -.0064,
           "3개월수익률": .159, "가속도": .097, "상태": "과열경보", "가격수준": .91}
    before = deepcopy(row)
    result = sector_evidence(row, {}, [])
    assert "수집기간 가격위치 91.0%" in result["medium"]
    assert "[3M 중기] 과열경보" in result["medium"] and row == before
