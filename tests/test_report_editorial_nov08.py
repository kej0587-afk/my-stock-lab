from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_dashboard import current_state_lines
from stock_lab_core.report_editorial import editorial_lines, reading_order
from stock_lab_core.report_news_selection import matching_categories
from stock_lab_core.report_session import market_session_states
from stock_lab_core.report_view import split_report_sections

NOW = datetime.fromisoformat("2026-11-08T00:48:00+09:00")


def context():
    return {"sessions": {"KR": "2026-11-06", "US": "2026-11-06"}, "prices": {
        "^KS11": {"date": "2026-11-06", "return": -.0602},
        "^GSPC": {"date": "2026-11-06", "return": .0031},
        "^IXIC": {"date": "2026-11-06", "return": .0109},
        "^SOX": {"date": "2026-11-06", "return": .0421}},
        "scenario_observations": {"latest": {"NQ=F": {"return": .99}}}}


def test_weekend_is_closed_not_failed_live_and_no_old_futures():
    ctx = context()
    saved = deepcopy(ctx)
    out = current_state_lines(ctx, market_session_states(NOW), NOW, {})[1]
    assert "휴장 · 최근 확정 종가" in out
    assert all(x in out for x in ("+0.31%", "+1.09%", "+4.21%", "2026-11-06"))
    assert "미연결" not in out and "미확정" not in out and "NQ=F" not in out
    assert ctx == saved


@pytest.mark.parametrize("field,value", [("stale", True), ("date", "2026-11-05"), ("date", "2026-11-09")])
def test_weekend_does_not_promote_invalid_close(field, value):
    ctx = context()
    for row in ctx["prices"].values():
        row[field] = value
    line = current_state_lines(ctx, market_session_states(NOW), NOW, {})[1]
    assert "종가 자료 미연결" in line and "+4.21%" not in line


def test_sunday_night_us_overnight_window_is_not_holiday_fallback():
    now = datetime.fromisoformat("2026-11-09T10:48:00+09:00")
    line = current_state_lines(context(), market_session_states(now), now, {})[1]
    assert "데이마켓" in line and "최근 확정 종가" not in line


def test_friday_after_extended_close_uses_dated_close():
    now = datetime.fromisoformat("2026-11-07T11:00:00+09:00")
    line = current_state_lines(context(), market_session_states(now), now, {})[1]
    assert "거래시간 외 · 최근 확정 종가" in line and "+4.21%" in line


@pytest.mark.parametrize("title", ["IBK기업은행, GS칼텍스 꺾고 2연승 (V리그)",
    "마나베 돌풍 기업은행 2연승…디펜딩 챔프 첫 패", "Bank team wins basketball championship"])
def test_sponsored_sports_are_not_financial_news(title):
    assert matching_categories(title, ["금융·은행"]) == []


def test_sports_business_financial_results_still_allowed():
    assert matching_categories("기업은행 배구 후원 비용 늘어 순이익 감소", ["금융·은행"]) == ["금융·은행"]


@pytest.mark.parametrize('title', ['금융감독원, 은행 대출금리 점검', '금융감독원, 은행권 가계대출 관리 강화'])
def test_financial_regulator_is_not_a_sports_coach(title):
    assert matching_categories(title, ['금융·은행']) == ['금융·은행']


def body(**changes):
    row = dict(title="AI 투자 우려에 코스피 하락", publisher="연합뉴스", link="https://www.yna.co.kr/view/example",
        market="KR", session_date="2026-11-06", published_at="2026-11-06T16:00:00+09:00", body_status="verified",
        body_facts=[dict(topic="ai_credit", summary="출처는 AI 투자 회수 우려를 거론했습니다.",
                        implication="조달 부담이 공급망 발주에 전해질 가능성을 점검합니다.", check="다음 공식 실적의 투자·현금흐름 비교")])
    row.update(changes)
    return row


def render(row=None, ctx=None):
    ctx = ctx or context()
    return "\n".join(editorial_lines(ctx, {"headline": "기존 출처 대조를 통과한 시장 해석.",
        "background_news": [body() if row is None else row]},
        [{"티커": "SOXL", "보유량": 1}], market_session_states(NOW, ctx["sessions"]), NOW))


def test_opposite_markets_and_verified_cause_holding_check_are_connected_without_mutation():
    ctx, row = context(), body()
    saved = deepcopy((ctx, row))
    out = render(row, ctx)
    assert "방향이 엇갈렸습니다" in out and "동시에 마감한 결과가 아닙니다" in out
    assert "SOXL" in out and "조달 부담" in out and row["link"] in out
    assert "AI 투자와 회수" in out and "반대 관측" in out
    assert (ctx, row) == saved


@pytest.mark.parametrize("changes", [{"body_status": "unsupported_source"},
    {"published_at": "2026-11-09T00:00:00+09:00"}, {"published_at": "2026-10-01T00:00:00+09:00"}])
def test_unverified_future_old_article_not_promoted_to_body_analysis(changes):
    out = render(body(**changes))
    assert "근거가 부족" not in out or "제목" in out
    assert "AI 투자와 회수 |" not in out and "조달 부담이" not in out


def test_open_session_missing_live_cannot_create_cross_market_thesis():
    ctx = context()
    now = datetime.fromisoformat("2026-11-09T10:00:00+09:00")
    out = "\n".join(editorial_lines(ctx, {}, [], market_session_states(now, ctx['sessions']), now))
    assert "방향이 엇갈렸습니다" not in out


def test_reverse_divergence_does_not_call_korean_rise_a_decline():
    ctx = context()
    ctx['prices']['^KS11']['return'] = .02
    ctx['prices']['^IXIC']['return'] = -.03
    out = render(ctx=ctx)
    assert '코스피 +2.00%' in out and '나스닥 -3.00%' in out
    assert '한국 하락의 배경' not in out and '미국 반등만으로' not in out


def test_explanations_precede_audits_and_every_section_survives():
    lines = ["# report", "", "## 기준일", "date", "", "## 지수·매크로 한눈에", "table", "",
             "## 오늘의 시장 스토리", "story", "", "## 핵심 해석", "thesis", ""]
    out = "\n".join(reading_order(lines))
    assert out.index("## 핵심 해석") < out.index("## 오늘의 시장 스토리") < out.index("## 지수·매크로")
    assert sorted(split_report_sections(out)) == sorted(split_report_sections("\n".join(lines)))


def test_full_report_integrates_editorial_without_touching_inputs():
    from stock_lab_core.report_evidence import report_sections
    from stock_lab_core.report_build import get_report_build_info
    ctx = context()
    ctx.pop('scenario_observations')
    original = deepcopy(ctx)
    lines, _ = report_sections(context=ctx, news=[], flow_rows=[], event_rows=[], summary_rows=[], now=NOW)
    out = "\n".join(lines)
    assert out.count("## 핵심 해석") == 1
    assert out.index("## 핵심 해석") < out.index("## 내 보유 종목 영향") < out.index("## 지수·매크로 한눈에")
    assert "미국 · 휴장 · 최근 확정 종가" in out and ctx == original
    build = get_report_build_info()['sources']['stock_lab_core.report_editorial']
    assert build['sha256'] == build['disk_sha256']
