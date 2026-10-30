from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_lab_core.report_policy_panel import policy_evidence_lines


NOW = datetime(2026, 10, 30, 15, 25, tzinfo=ZoneInfo("Asia/Seoul"))


def test_official_decisions_and_reported_halts_are_separate_read_only():
    context = {"central_bank_results": [
        {"bank": "FOMC", "status": "official", "action": "hold", "rate_lower": 3.75, "rate_upper": 4,
         "release_at": "2026-10-29T03:00:00+09:00", "source": "Federal Reserve",
         "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"},
        {"bank": "BOJ", "status": "official", "action": "set_target", "policy_rate": 1.25,
         "release_at": "2026-10-30T12:02:00+09:00", "source": "Bank of Japan",
         "source_url": "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k261030a.pdf"}]}
    news = [{"title": "코스피 매도 사이드카 발동", "published_at": "2026-10-30T10:12:00+09:00",
             "publisher": "연합뉴스", "link": "https://www.yna.co.kr/view/test"}]
    before = deepcopy((context, news))
    output = "\n".join(policy_evidence_lines(context, news, NOW))
    assert "동결 · 연방기금 목표 3.75~4%" in output
    assert "익일물 콜금리 목표 약 1.25%" in output
    assert "전회 대비 변동은 별도 미대조" in output
    assert "03:00" in output and "12:02" in output
    assert "KOSPI 매도 사이드카" in output and "보도상 발동" in output
    assert (context, news) == before


def test_missing_results_are_not_holds_or_absence_of_halts():
    result = "\n".join(policy_evidence_lines({}, [], NOW))
    assert result.count("결과 미연결 · 추정하지 않음") == 2
    assert "미발동 의미 아님" in result
    assert "동결" not in result
