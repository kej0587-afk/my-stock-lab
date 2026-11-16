"""Reader layout contracts: preserve dated data and decisions, shorten main path."""
from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_reading import AUDIT_TITLE, compose_reading_report, tables
from stock_lab_core.report_view import COLLAPSED_SECTIONS, split_report_sections
from stock_lab_core.report_brief import build_news_brief

NOW = datetime.fromisoformat("2026-11-15T18:00:00+09:00")
CONTEXT = {"sessions": {"KR": "2026-11-13", "US": "2026-11-13"}, "prices": {
    "^KS11": {"date": "2026-11-13", "return": .0123},
    "^GSPC": {"date": "2026-11-13", "return": -.004},
}}
REPORT = """# Stock Lab 자동 뉴스픽 · fixture
신규매수 허용 0개 / 보고서 매크로 스트레스 74 경고
## 지수·매크로 한눈에
대상 | 수준 | 등락·비교 기준 | 기준일·시각 | 출처
--- | --- | --- | --- | ---
코스피(^KS11) | 6,000.00 pt | +1.23% · 정규장 종가·전 거래일 대비 | 2026-11-13 | fixture
10Y 금리(^TNX) | 5.15 % | +2.20% · 1개월 변화 | 2026-11-13 | fixture
## 내 보유 종목 영향
구분 | 계좌 기여(추정) | 연결 비중 | 시작 종가일 → 관측일
--- | --- | --- | ---
연결분 기여(전체 추정 아님) | -0.17%p | 87.5% | 전체 추정 보류: 연결 90% 미만

종목 | 기준일 일간(실제) | 배수 참고(추정) | 당일 현재(실제) | 상태/사유
--- | --- | --- | --- | ---
Fixture(SOXL) | -11.00% (2026-11-13 확정 종가) | -11.01% 추정 | 해당없음 | 방어우선 · 레버리지 보유
## 관심 후보 상위 3개
후보·개별 신호·실행 상태 | 게이트 근거 | 해제 조건
--- | --- | ---
MSFT · 방어우선 | 시장방어 | 시장 게이트 해제 후 재계산
## 다가오는 일정
일정·남은 일수 | 발표·콜 시각 | 공식 출처
--- | --- | ---
CPI | 2026-12-10 | fixture

**기업 실적 촉매**
기업·상태 | 발표일 / 콜 시각 | 근거·연결 범위
--- | --- | ---
NVDA · 예정 | 2026-11-17 | 공식 IR
MSFT · 공식 결과 발표 확인 | 2026-10-28 | 공식 IR
## 주도 업종 교체 관측
반도체·AI가 회복하는지와 다른 업종으로 강세가 확산되는지를 나누어 봅니다.
시장·업종·기준일 | 실제 수익률 5일 / 20일 / 63일 | RS 변화 5일 / 20일 | 관측 해석 | 다음 확인
--- | --- | --- | --- | ---
US 기술 · 2026-11-13 | -5% / -3% / +1% | -2% / -1% | 상대 약세 | 차기 종가 확인
## 경제지표
PPI 근거 · 2026-11-13 원문
"""


def render(context=None, news=()):
    return compose_reading_report(REPORT, context=context or deepcopy(CONTEXT), news=news, summary_rows=[], now=NOW)


def test_reading_order_keeps_one_report_and_unique_audit_evidence():
    output = render()
    parts = split_report_sections(output.split("## " + AUDIT_TITLE, 1)[0])
    assert [title for title, _ in parts][1:] == ["오늘의 판단", "이번 주 테마 5개", "매크로", "지수", "한국 시황", "미국 시황",
        "포트폴리오 · 교체 검토", "돈흐름 · 업종 순환", "다음 일정"]
    main, audit = output.split("## " + AUDIT_TITLE, 1)
    assert "반도체·AI가 회복하는지와" not in main
    assert output.count("# Stock Lab 자동 뉴스픽 · fixture") == 1
    assert "PPI 근거 · 2026-11-13 원문" in audit
    assert "-11.01% 추정" in audit  # Projected reader table must not erase full source fields.
    assert "MSFT · 공식 결과 발표 확인" in audit
    assert "코스피(^KS11)" not in audit
    assert output.count("MSFT · 방어우선 | 시장방어 | 시장 게이트 해제 후 재계산") == 1
    assert output.count("신규매수 허용 0개 / 보고서 매크로 스트레스 74 경고") == 1
    assert AUDIT_TITLE in COLLAPSED_SECTIONS


def test_units_dates_partial_coverage_and_gate_do_not_disappear():
    sections = dict(split_report_sections(render()))
    assert "5.15 % | +2.20% · 1개월 변화 | 2026-11-13" in sections["매크로"]
    assert "코스피(^KS11)" not in sections["매크로"]
    assert "5.15" not in sections["지수"]
    portfolio = sections["포트폴리오 · 교체 검토"]
    assert "전체 추정 보류: 연결 90% 미만" in portfolio
    assert "실제 계좌 수익률이 아닙니다" in portfolio
    assert "-11.00% (2026-11-13 확정 종가)" in portfolio
    assert "방어우선 · 레버리지 보유" in portfolio
    assert "시장 게이트 해제 후 재계산" in portfolio
    assert "배수 참고" not in portfolio and "당일 현재" not in portfolio
    assert "NVDA · 예정" in sections["다음 일정"]
    assert "MSFT · 공식 결과" not in sections["다음 일정"]


def article(**kwargs):
    return dict(title="NVIDIA announces chip supply update", publisher="Reuters",
        link="https://www.reuters.com/fixture", market="US", session_date="2026-11-13",
        news_bucket="session_news", published_at="2026-11-13T15:00:00-05:00", **kwargs)


@pytest.mark.parametrize("mutations", [
    {"session_date": "2026-11-12"}, {"news_bucket": "next_session_news"},
    {"published_at": "2026-11-16T01:00:00+09:00"},
])
def test_compact_news_obeys_same_session_future_and_post_close_filters(mutations):
    row = article()
    row.update(mutations)
    result = build_news_brief(CONTEXT, [row], [], NOW, compact=True)
    assert not result["article_keys"]


def test_title_only_claim_not_promoted_and_inputs_immutable():
    context, rows = deepcopy(CONTEXT), [article()]
    original = deepcopy((context, rows))
    result = render(context, rows)
    main = result.split("## " + AUDIT_TITLE)[0]
    assert "제목 확인·기사 주장" in main
    assert "본문 근거:" not in main
    assert (context, rows) == original


def test_compact_render_keeps_same_selected_articles_as_full_brief():
    rows = [article()]
    full = build_news_brief(CONTEXT, rows, [], NOW)
    compact = build_news_brief(CONTEXT, rows, [], NOW, compact=True)
    assert full["article_keys"] == compact["article_keys"]
    assert len("\n".join(compact["lines"])) < len("\n".join(full["lines"]))


def test_empty_report_still_has_named_missing_states():
    result = compose_reading_report("# Empty", context={}, news=[], summary_rows=[], now=NOW)
    assert "종가 미수집" in result and "업종 비교 자료 미연결" in result


def test_summary_citation_does_not_hide_article_details_from_main(monkeypatch):
    row = article()
    monkeypatch.setattr("stock_lab_core.report_market_summary.market_summary", lambda *a: {
        "market_readings": {"US": "시장 혼조 [배경 보도](" + row["link"] + ")"}, "background_news": [row]})
    main = render(news=[row]).split("## " + AUDIT_TITLE, 1)[0]
    assert row["title"] in main and "제목 확인·기사 주장" in main


def test_pipe_prose_is_not_a_table():
    assert tables("this | is prose\nnot a table\nnext | line") == []


def test_power_company_name_does_not_become_oil_sector_cause():
    from stock_lab_core.report_presentation import sector_related_news
    row = article()
    row["title"] = "Has Constellation Energy (CEG) Fallen Below Fair Value After Raising Earnings Guidance?"
    assert not sector_related_news("XLE", "2026-11-13", [row])
    row["title"] = "Constellation Energy comments on oil prices and energy stocks"
    assert sector_related_news("XLE", "2026-11-13", [row])


def test_macro_summary_only_promotes_recent_verified_period_rows():
    from stock_lab_core.report_reading import _recent_releases
    current = dict(indicator="US_PPI", period="2026-10", basis="MoM", unit="%", actual=.3,
                   previous=.2, status="released", release_at="2026-11-13", source_url="https://www.bls.gov/ppi/")
    old = dict(current, indicator="US_CPI", release_at="2026-11-01")
    context = dict(CONTEXT, economic_releases=[old, current])
    source = "지표 | 발표치 | 예상 | 이전 | 해석 | 반응\n--- | --- | --- | --- | --- | ---\nCPI | 4% | 3% | 2% | old | old\nPPI | 0.3% | 0.4% | 0.2% | pressure | +2bp"
    result = "\n".join(_recent_releases({"경제지표": source}, context, NOW))
    assert "PPI |" not in result  # date and source are attached to its label
    assert "발표 2026-11-13" in result and "0.3% | 0.4% | 0.2%" in result
    assert "+2bp" in result and result.count("0.3% | 0.4% | 0.2%") == 1
    assert "CPI" not in result
    context["economic_releases"] = [old, dict(current, status="stale")]
    assert not _recent_releases({"경제지표": source}, context, NOW)
