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
    assert result.count("결과 미연결 · 추정하지 않음") == 3
    assert "미발동 의미 아님" in result
    assert "동결" not in result


BOK_ROW = {"bank": "BOK", "status": "official", "action": "hike", "policy_rate": 3.25, "previous_rate": 3.0,
           "date": "2026-11-26", "decision_date": "2026-11-26", "release_at": None, "indicator": "KR_BOK_RATE_DECISION",
           "source": "Bank of Korea",  # synthetic values, layout of the 2026-11-26 page survey
           "source_url": "https://www.bok.or.kr/portal/bbs/P0000559/view.do?nttId=11000001&menuNo=200690"}


def test_bok_official_row_shows_previous_and_new_rate_without_time():
    output = "\n".join(policy_evidence_lines({"central_bank_results": [BOK_ROW]}, [], NOW))
    line = next(l for l in output.splitlines() if l.startswith("한국은행 금통위"))
    assert "인상 · 기준금리 3.00% → 3.25%" in line and "2026-11-26 · 시각 미제공" in line
    assert "결정문 확인" in line and "bok.or.kr" in line
    hold = dict(BOK_ROW, action="hold", policy_rate=3.0, previous_rate=3.0)
    assert "동결 · 기준금리 3.00%" in "\n".join(policy_evidence_lines({"central_bank_results": [hold]}, [], NOW))


def test_bok_daily_change_and_calendar_state():
    from stock_lab_core.report_daily_change import completed_event_changes
    from stock_lab_core.report_event_watch import _central_bank_result
    changes = completed_event_changes({"sessions": {"KR": "2026-11-26"}, "central_bank_results": [BOK_ROW]}, {})
    assert changes == ["한국은행 금통위 기준금리 결정 발표 완료: 인상 · 기준금리 3.00% → 3.25%(2026-11-26 · 시각 미제공, 공식 결정문)"]
    calendar_row = {"indicator": "KR_BOK_RATE_DECISION", "date": "2026-11-26"}
    assert _central_bank_result(calendar_row, {"central_bank_results": [BOK_ROW]}) == BOK_ROW
    assert _central_bank_result(dict(calendar_row, date="2026-10-22"), {"central_bank_results": [BOK_ROW]}) is None
    assert _central_bank_result(calendar_row, {"central_bank_results": [dict(BOK_ROW, status="missing")]}) is None
