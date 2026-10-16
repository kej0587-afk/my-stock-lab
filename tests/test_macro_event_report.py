from datetime import date

import pandas as pd
import pytest

from stock_lab_core.macro_event_report import event_release_summary, merge_event_observations
from stock_lab_core.market_memo import MARKET_MEMO_VERSION, build_auto_market_memo, current_memo_text
from stock_lab_core.decision_workflow import attach_market_execution_context
from stock_lab_core.execution_gate import build_execution_gate


def release_row(actual="0.6%", forecast="0.5%", previous="0.4%", state="잔여"):
    return {
        "이벤트": "미국 PPI 발표", "상태": state, "D-Day": "D+1", "발표일": "2026-10-15",
        "시장": "미국 주식/달러/금리", "주식시장 해석": "OLD_SCHEDULE_WARNING",
        "발표항목": [{"series": "PPI m/m", "actual": actual, "forecast": forecast,
                   "previous": previous, "source": "합성 테스트"}],
    }


def test_completed_release_precedes_indicators_and_does_not_become_future_warning():
    frame = pd.DataFrame([release_row()])
    before = frame.copy(deep=True)
    memo = build_auto_market_memo(event_rows=frame)
    assert memo.index("발표 결과·다음 일정") < memo.index("🧠 핵심 해석")
    assert "PPI 전월비: 실제 0.6% / 예상 0.5% / 이전 0.4%" in memo
    assert "예상 대비 +0.1%p" in memo and "이전 발표 대비 +0.2%p" in memo
    assert "예상 상회" in memo
    assert "OLD_SCHEDULE_WARNING" not in memo
    assert "일정 때문에 장중 변동성" not in memo
    assert "다음 확인 일정: 미국 PPI" not in memo
    assert memo.count("실제 0.6%") == 1
    assert f"보고서 버전: {MARKET_MEMO_VERSION}" in memo
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("actual", [None, "", "-", float("nan"), pd.NA])
def test_missing_actual_never_uses_forecast_or_claims_surprise(actual):
    text = event_release_summary(release_row(actual=actual))
    assert "실제 결과 미수집" in text
    assert "예상 0.5% / 이전 0.4%" in text
    assert "실제 0.5%" not in text and "예상 상회" not in text
    assert "해석 보류" in text


def test_zero_actual_and_units_are_preserved():
    text = event_release_summary(release_row(actual="0.0%", forecast="0.2%", previous="0.1%"))
    assert "실제 0.0%" in text and "예상 대비 -0.2%p" in text
    assert "예상 하회" in text
    mixed = event_release_summary(release_row(actual="0.2%", forecast="0.2", previous="0.1%"))
    assert "예상 대비 +" not in mixed and "예상과 일치" not in mixed
    assert "예상 대비 판단 불가" in mixed


def test_past_missing_result_and_distant_fomc_are_both_visible():
    memo = build_auto_market_memo(event_rows=[
        release_row(actual=None, state="종료"),
        {"이벤트": "FOMC", "상태": "대기", "D-Day": "D-11", "시장": "미국"},
    ])
    assert "발표일 경과·실제 결과 미수집" in memo
    assert "FOMC D-11(대기)" in memo
    assert "다음 확인 일정: FOMC" in memo
    assert "다음 확인 일정: 미국 PPI" not in memo


def test_old_generated_draft_is_invalidated_but_manual_notes_are_kept():
    generated = "Stock Lab 자동 뉴스픽\n주의/차단 후보: old list"
    assert current_memo_text(generated, "old") == ""
    assert current_memo_text(generated, MARKET_MEMO_VERSION) == generated
    assert current_memo_text("직접 작성한 시황", "old") == "직접 작성한 시황"


def test_released_fomc_rate_is_not_treated_as_upcoming_without_news():
    memo = build_auto_market_memo(event_rows=[{
        "이벤트": "FOMC", "상태": "당일", "D-Day": "D-Day",
        "실제": "4.25%", "예상": "4.25%", "이전": "4.5%",
    }])
    assert "실제 4.25%" in memo
    assert "다음 확인 일정: FOMC" not in memo
    assert "FOMC 전후에는 QQQ/TQQQ" not in memo


def test_merging_does_not_overwrite_core_or_yoy_values():
    mom = {"raw_title": "CPI m/m", "actual": "0.6%", "forecast": "0.5%"}
    yoy = {"raw_title": "CPI y/y", "actual": "3.7%", "forecast": "3.6%"}
    core = {"raw_title": "Core CPI m/m", "actual": "0.3%", "forecast": "0.2%"}
    first = {"release_observations": merge_event_observations(mom, yoy)}
    merged = merge_event_observations(first, core)
    assert [item["actual"] for item in merged] == ["0.6%", "3.7%", "0.3%"]
    text = event_release_summary({"이벤트": "미국 CPI 발표", "상태": "잔여", "발표항목": merged})
    assert "CPI 전월비: 실제 0.6%" in text
    assert "CPI 전년비: 실제 3.7%" in text
    assert "Core CPI 전월비: 실제 0.3%" in text


@pytest.mark.parametrize("title,event", [
    ("Core PCE Price Index m/m", "미국 PCE 발표"),
    ("JOLTS Job Openings", "미국 JOLTS 발표"),
    ("Advance GDP q/q", "미국 GDP 발표"),
])
def test_new_release_coverage_does_not_raise_market_risk(app_module, monkeypatch, title, event):
    today = date(2026, 10, 16)
    item = app_module.ff_macro_event_from_title(title, "USD")
    assert item["event"] == event
    assert item["weight"] == 0.0
    item.update(date=today.isoformat(), actual="2.0%", forecast="1.9%", previous="1.8%")
    monkeypatch.setattr(app_module, "build_macro_event_candidates", lambda _today: [item])
    table, risk, active_count = app_module.build_macro_event_risk_table(today)
    assert risk == 0.0 and active_count == 0
    assert table.iloc[0]["발표항목"][0]["actual"] == "2.0%"
    assert "결과가 나오기 전" not in table.iloc[0]["주식시장 해석"]
    assert "실제 2.0%" in build_auto_market_memo(event_rows=table)


def test_app_event_merge_preserves_release_fields(app_module):
    base = {"event": "미국 CPI 발표", "date": "2026-10-14", "source": "자동: FF", "weight": 1.0}
    events = [{**base, "raw_title": "CPI m/m", "actual": "0.6%"},
              {**base, "raw_title": "CPI y/y", "actual": "3.7%"}]
    merged = app_module.dedupe_macro_events(events)
    assert len(merged) == 1 and merged[0]["weight"] == 1.0
    assert len(merged[0]["release_observations"]) == 2
    # A bare manual calendar entry must not displace four detailed CPI series.
    manual = {"event": "미국 CPI 발표"}
    details = merge_event_observations(manual, merged[0])
    assert len(details) == 2


@pytest.mark.parametrize("whole,action,expected", [
    ("위험", "신규매수 중단 · 현금/리스크 점검", "방어우선"),
    ("방어", "정찰만 · 시장별 노출 확인", "실행가능"),
])
def test_overall_stop_not_regional_caution_alone_blocks_ordinary_us_stock(whole, action, expected):
    source = pd.DataFrame([{"티커": "AMAT", "종목명": "Applied Materials", "판정분류": "buyish", "R/R": 2.0}])
    guard = {"mode": whole, "action": action, "kr_stats": {"mode": "방어"}, "us_stats": {"mode": "주의"}}
    row = attach_market_execution_context(source, guard).iloc[0].to_dict()
    row.update(build_execution_gate(row))
    assert row["게이트상태"] == expected
    memo = build_auto_market_memo(summary_rows=[{**row, "보유수량": 0}])
    if expected == "방어우선":
        assert "시장방어 게이트 1개" in memo
        assert "개별 종목 부실 판정과는 별개" in memo
