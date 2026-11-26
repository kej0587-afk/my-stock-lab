"""Rebooted session: a report made before 오늘 점검 must say 미계산, not 0 results (2026-11-26)."""
from datetime import datetime

from stock_lab_core.earnings_pipeline import build_earnings_pipeline, coverage_state
from stock_lab_core.report_earnings import earnings_coverage_lines
from stock_lab_core.report_input_status import MISSING_ACCOUNT
from stock_lab_core.report_reading import _closing_lines

NOW = datetime.fromisoformat("2026-11-26T20:36:00+09:00")


def status_line(pipeline):
    return next(l for l in earnings_coverage_lines(pipeline) if l.startswith("실적 점검 상태"))


def test_empty_today_check_is_not_computed_not_zero():
    pipeline = build_earnings_pipeline({}, [], now=NOW)
    assert coverage_state(pipeline["coverage"])["not_computed"]
    assert "오늘 점검 미계산" in status_line(pipeline) and "0개가 아님" in status_line(pipeline)


def test_computed_states_are_counted_separately():
    coverage = dict(summary_available=True, registered=3, official=0, filings=0, discovered=0, missing=[
        dict(ticker="A", name="A", reason="공식 원문 조회 실패·시간초과"),
        dict(ticker="B", name="B", reason="공식 공시 수집 시간 한도·이번 조회 보류"),
        dict(ticker="C", name="C", reason="최근 SEC 실적 공시 미확인")])
    line = status_line(dict(coverage=coverage, packets=[], discovery={"excluded": {}}))
    assert "공식 발표 확인 결과 0개" in line and "일부 조회 실패 2개" in line and "공식값 없음 1개" in line
    assert "미계산" not in line


def test_unknown_input_is_not_labelled_not_computed():
    assert not coverage_state(build_earnings_pipeline({}, now=NOW)["coverage"])["not_computed"]


def test_closing_says_not_computed_when_account_input_missing():
    lines = _closing_lines(["", "## 내 보유 종목 영향", MISSING_ACCOUNT], [])
    assert any(l.startswith("오늘 점검 미계산 · 보유 종목 영향 확인 불가") for l in lines)
    assert any(l == "보유 종목 표 미연결 · 영향 미확인." for l in _closing_lines(["## 다른 표"], []))
