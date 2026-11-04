from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_policy_catalysts import election_context_lines, policy_calendar_lines

NOW = datetime.fromisoformat("2026-11-04T11:00:00+09:00")


def article(title="미국 중간선거 시나리오별 증시 영향은?", **kwargs):
    result = dict(title=title, publisher="연합뉴스", link="https://www.yna.co.kr/view/EXAMPLE",
                  published_at="2026-11-04T09:00:00+09:00", market="US", session_date="2026-11-03")
    result.update(kwargs)
    return result


def test_calendar_official_vs_reported_and_dst_conversion():
    output = "\n".join(policy_calendar_lines({}, [], NOW))
    assert "2026-11-04 08:00 KST" in output
    assert "2026-11-04 22:30 KST" in output
    assert "2026-12-11" in output
    assert "공식 일정 확인" in output and "보도 기준·확정 상장일 미연결" in output
    assert "중순 특정일로 확정하지 않" in output
    assert "실시간 재조회가 아닙니다" in output
    assert "협상 | 일정·결과 미연결" in output
    assert "입찰 | 날짜·만기·규모 미연결" in output


@pytest.mark.parametrize("at", ["2026-11-04T09:50:00+09:00", "2026-12-12T10:00:00+09:00"])
def test_no_future_knowledge_or_expired_calendar(at):
    output = "\n".join(policy_calendar_lines({}, [], datetime.fromisoformat(at)))
    assert "미 재무부 분기 발행계획 |" not in output
    assert "미국 임시예산 지원 시한 |" not in output
    assert "보관값 미연결" in output


def test_news_does_not_become_confirmed_talks_or_future_evidence():
    news = [article("미국·이란 협상 가능성에 주식 상승"),
            article("미국·이란 협상 타결", published_at="2026-11-04T12:00:00+09:00", link="https://www.yna.co.kr/view/FUTURE")]
    output = "\n".join(policy_calendar_lines({}, news, NOW))
    assert "협상 가능성" in output and "합의·회담일 확정 아님" in output
    assert "협상 타결" not in output


def test_upcoming_deadline_remains_visible_but_stale_after_verification_expiry():
    output = "\n".join(policy_calendar_lines({}, [], datetime.fromisoformat("2026-11-12T10:00:00+09:00")))
    assert "2026-12-11" in output and "재확인 필요·현재 유효성 미확인" in output
    assert "앤트로픽 IPO |" not in output


def test_scenario_needs_verified_body_and_never_fills_unsupported_sectors():
    row = article(body_status="verified", body_published_at="2026-11-04T09:00:00+09:00",
                  body_modified_at="2026-11-04T09:10:00+09:00",
                  body_scenarios=[dict(condition="민주당 양원 확보 시", sectors=["AI·반도체"],
                                       evidence="민주당 양원 확보 시 AI 감독 강화 가능성이 제기됐다.")])
    original = deepcopy(row)
    output = "\n".join(election_context_lines({}, [row], [{"티커": "SOXL", "보유수량": 10}], NOW))
    assert "AI 감독 강화 가능성" in output
    assert "보유 SOXL" in output
    assert "근거 미연결 업종: 방산, 헬스케어, 금융" in output
    assert "기사의 조건부 주장" in output and "공식 인증 결과 아님" not in output
    assert row == original
    row["body_status"] = "fetch_unavailable"
    output = "\n".join(election_context_lines({}, [row], [], NOW))
    assert "본문 조건 미연결" in output and "AI 감독 강화 가능성" not in output


def test_future_body_not_reused_and_result_claim_is_not_certification():
    row = article(body_status="verified", body_published_at="2026-11-04T09:00:00+09:00",
                  body_modified_at="2026-11-04T12:00:00+09:00",
                  body_scenarios=[dict(condition="예시", sectors=["금융"], evidence="미래 본문")])
    current = article("미국 중간선거 개표, 의석 결과 보도", link="https://www.yna.co.kr/view/COUNT")
    output = "\n".join(election_context_lines({}, [row, current], [], NOW))
    assert "미래 본문" not in output
    assert "개표, 의석 결과 보도" in output
    assert "공식 인증 결과 아님" in output


def test_renderer_wired_without_gate_changes():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "stock_lab_core/report_evidence.py").read_text(encoding="utf-8")
    assert "policy_calendar_lines(context, news, now)" in source
    assert "election_context_lines(context, news, summary_rows, now)" in source


def test_election_results_survive_upstream_market_curation():
    from stock_lab_core.report_evidence import curate_news
    row = article("US midterm election results: counting continues")
    assert curate_news([row], now=NOW)


def test_non_us_negotiations_and_auctions_are_not_us_policy_evidence():
    news = [article("이란과 러시아 협상 재개, 증시 주목"),
            article("한국 국채 입찰 수요 증가", link="https://www.yna.co.kr/view/KR_AUCTION")]
    output = "\n".join(policy_calendar_lines({}, news, NOW))
    assert "미국·이란 협상 | 일정·결과 미연결" in output
    assert "미 국채 개별 입찰 | 날짜·만기·규모 미연결" in output
    us_news = [article("미·이란 협상 재개, 증시 주목"),
               article("미 국채 입찰 수요 증가", link="https://www.yna.co.kr/view/US_AUCTION")]
    output = "\n".join(policy_calendar_lines({}, us_news, NOW))
    assert "미국·이란 협상 | 미·이란 협상" in output
    assert "미 국채 개별 입찰 | 미 국채 입찰" in output
