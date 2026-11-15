from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_event_watch import event_watch_lines, event_watch_rows

NOW = datetime.fromisoformat("2026-11-15T21:00:00+09:00")


def event(**changes):
    return dict({"indicator": "US_RETAIL_SALES", "event": "미국 소매판매", "period": "2026-10",
        "date": "2026-11-17", "release_at": "2026-11-17T08:30:00-05:00", "release_precision": "datetime",
        "timezone": "America/New_York", "source": "Census", "market": "US",
        "source_url": "https://www.census.gov/retail/release_schedule.html"}, **changes)


def context(*rows):
    return {"calendar_events": list(rows), "market_watch_sources": [{"name": "Census", "status": "connected"}]}


def test_scheduled_event_has_local_kst_time_conditions_and_no_unfounded_rate_prediction():
    c = context(event())
    before = deepcopy(c)
    rendered = "\n".join(event_watch_lines(c, [], [], NOW))
    assert "11/17 08:30 EST / 11/17 22:30 KST" in rendered
    assert "자동차 제외·통제그룹" in rendered and "소비만 약하면 경기·이익 둔화" in rendered
    assert "한 지표로 25/50bp나 확률을 결정하지 않음" in rendered
    assert "AI 활용·생산성 확산" in rendered and "유료 고객" in rendered
    assert c == before


def test_elapsed_time_does_not_invent_result_and_later_release_updates_same_event():
    now = datetime.fromisoformat("2026-11-18T03:00:00+09:00")
    c = context(event())
    assert "결과 미확인" in event_watch_rows(c, [], now)[0]["state"]
    c["economic_releases"] = [dict(indicator="US_RETAIL_SALES", period="2026-10", release_at="2026-11-17T08:30:00-05:00",
                                  actual=.1, previous=.5, forecast=.3, unit="%", basis="MoM")]
    row = event_watch_rows(c, [], now)[0]
    assert row["state"] == "공식 결과 확인"
    assert "결과 2026-10 전월비 0.1% / 이전 0.5% / 발표 당시 예상 0.3%" == row["observed"]
    assert len(event_watch_rows(c, [], now)) == 1


@pytest.mark.parametrize("changes", [{"period": "2026-09"}, {"stale": True}, {"status": "stale"}, {"release_at": "2026-11-19T08:30:00-05:00"}])
def test_wrong_period_stale_or_future_release_cannot_complete_event(changes):
    c = context(event())
    c["economic_releases"] = [dict(indicator="US_RETAIL_SALES", period="2026-10", actual=.1,
                                  release_at="2026-11-17T08:30:00-05:00", **{k:v for k,v in changes.items() if k not in {"period","release_at"}})]
    c["economic_releases"][0].update(changes)
    assert "미확인" in event_watch_rows(c, [], datetime.fromisoformat("2026-11-18T03:00:00+09:00"))[0]["state"]


def test_fomc_result_date_uses_us_local_date_not_next_kst_day():
    c = context(event(indicator="US_FED_RATE_DECISION", date="2026-11-17", release_at="2026-11-17T14:00:00-05:00", period="2026-11"))
    c["economic_releases"] = [dict(indicator="US_FED_RATE_DECISION", period="2026-11", actual=4., release_at="2026-11-17T14:00:00-05:00")]
    assert event_watch_rows(c, [], datetime.fromisoformat("2026-11-18T06:00:00+09:00"))[0]["state"] == "공식 결과 확인"


@pytest.mark.parametrize("changes", [{"source_url": ""}, {"source": "fallback"}, {"date": "2026-10-01"},
    {"coverage_expires_at": "2026-11-15"}, {"source_verified_at": "2026-11-16"}, {"timezone": "invalid"},
    {"schedule_status": "unconfirmed"}, {"date": "2027-03-01"}, {"source_url": "https://[invalid"}])
def test_unverified_expired_or_out_of_scope_events_are_not_promoted(changes):
    assert event_watch_rows(context(event(**changes)), [], NOW) == []


def test_pipeline_result_replaces_schedule_without_mutating_decision_rows():
    scheduled = event(ticker="NVDA", indicator="US_NVDA_EARNINGS", event="NVIDIA earnings",
                      event_status="scheduled", date="2026-11-13")
    result = dict(scheduled, event_status="released", release_at="2026-11-13T16:30:00-05:00",
                  result_metrics={"revenue": {"status": "reported", "text": "synthetic"}})
    summary = [{"티커": "NVDA", "판정코드": "BLOCK", "Adj점수": 7, "보유여부": True}]
    before = deepcopy(summary)
    rows = event_watch_rows(context(scheduled), summary, NOW, pipeline={"events": [result]})
    assert len(rows) == 1 and rows[0]["state"] == "공식 결과 확인"
    assert "고객 금융지원" in rows[0]["check"] and "다음 정규장 종가" in rows[0]["conditional"]
    assert summary == before


def test_schedule_is_not_fabricated_from_ipo_news_and_future_news_not_used():
    c = context()
    c["other_market_news"] = [{"title": "Anthropic IPO proposed offering", "publisher": "Reuters",
        "link": "https://www.reuters.com/technology/synthetic-ipo", "published_at": "2026-11-15T12:00:00+09:00",
        "market": "US"}]
    rendered = "\n".join(event_watch_lines(c, [], [], NOW))
    assert "보도·일정 확정과 별도" in rendered
    assert "11/19" not in rendered
    c["other_market_news"][0]["published_at"] = "2026-11-16T12:00:00+09:00"
    assert "synthetic-ipo" not in "\n".join(event_watch_lines(c, [], [], NOW))


def test_missing_collection_keeps_existing_report_fallback():
    assert event_watch_lines({}, [], [], NOW) == []
    output = "\n".join(event_watch_lines({"market_watch_sources": [{"name": "Census", "status": "unavailable"}]}, [], [], NOW))
    assert "일정이 없다는 뜻은 아닙니다" in output and "일정 연결 미완료: Census" in output


def test_latest_nvidia_ir_supersedes_only_after_verification_date():
    from stock_lab_core.earnings_sources import _issuer
    old, _ = _issuer("NVDA", ["NVDA"], datetime.fromisoformat("2026-11-14T12:00:00+00:00"), False)
    new, _ = _issuer("NVDA", ["NVDA"], NOW, False)
    assert old[0]["event_kind"] == "conference_call"
    assert new[0]["event_kind"] == "scheduled_release"
    assert new[0]["conference_call_at"] == "2026-11-17T17:00:00-05:00"
    assert new[0]["session_timing"] == "after_market_close"
    assert "11/18 07:00 KST" in event_watch_rows(context(new[0]), [], NOW)[0]["timing"]


def test_multi_day_meeting_is_not_finished_on_its_second_day():
    meeting = event(indicator="APEC_LEADERS_MEETING", date="2026-11-18", end_date="2026-11-19",
                    release_precision="date", release_at="2026-11-18", timezone="Asia/Shanghai")
    row = event_watch_rows(context(meeting), [], datetime.fromisoformat("2026-11-19T12:00:00+09:00"))[0]
    assert row["state"] == "예정 행사 기간·결과 미확인"
    assert row["event"] == "APEC 정상회의"


def test_cancellation_is_not_promoted_to_scheduled_or_completed():
    row = event_watch_rows(context(event(event_status="cancelled")), [], NOW)[0]
    assert row["state"] == "취소·연기 확인"


def test_next_month_macro_stays_visible_and_standard_time_is_not_exact_confirmation():
    c = context(event(indicator="US_CPI", date="2026-12-10", release_at="2026-12-10T08:30:00-05:00",
                      release_precision="schedule_rule"))
    output = "\n".join(event_watch_lines(c, [], [], NOW))
    assert "이후 확정 일정·90일 이내" in output
    assert "12/10 22:30 KST · 표준시각·예외 미확인" in output


def test_existing_next_release_inside_ninety_days_stays_visible():
    c = context(event(date="2027-01-15", release_at="2027-01-15", release_precision="date"))
    assert "2027-01-15 현지" in "\n".join(event_watch_lines(c, [], [], NOW))


def test_fomc_date_only_keeps_existing_labelled_standard_clock():
    c = context(event(indicator="US_FED_RATE_DECISION", date="2026-12-09", release_at="2026-12-09", release_precision="date"))
    output = "\n".join(event_watch_lines(c, [], [], NOW))
    assert "12/09 14:00 EST / 12/10 04:00 KST · 표준시각·예외 미확인" in output


def test_invalid_fomc_clock_cannot_crash_valid_date_report():
    c = context(event(indicator="US_FED_RATE_DECISION", date="2026-12-09", release_at="2026-99-99", release_precision="date"))
    output = "\n".join(event_watch_lines(c, [], [], NOW))
    assert "2026-12-09 현지 · 시각 미확인" in output


def test_ipo_tracking_groups_same_issuer_links_without_losing_other_ipo():
    c = context()
    c['other_market_news'] = [dict(title=title, link=f'https://www.reuters.com/{i}', publisher='Reuters',
        published_at='2026-11-15T12:00:00+09:00', market='US') for i, title in enumerate(
        ['Anthropic IPO proposed offering', 'Anthropic IPO expected demand', 'Another company IPO proposed offering'])]
    output = '\n'.join(event_watch_lines(c, [], [], NOW))
    assert '관련 보도 2건' in output and 'Another company' in output
    assert all(f'https://www.reuters.com/{i}' in output for i in range(3))


@pytest.mark.parametrize("status", ["released", "reported_results"])
def test_future_official_or_news_result_is_not_presented_as_confirmed(status):
    row = event_watch_rows(context(event(event_status=status)), [], NOW)[0]
    assert row["state"] == "결과 시점 불일치·재확인 필요"


def test_stale_status_does_not_leak_actuals_into_result_summary():
    c = context(event())
    c["economic_releases"] = [dict(indicator="US_RETAIL_SALES", period="2026-10", actual=99,
        status="stale", release_at="2026-11-17T08:30:00-05:00")]
    row = event_watch_rows(c, [], datetime.fromisoformat("2026-11-18T03:00:00+09:00"))[0]
    assert row["observed"] == "" and "결과 미확인" in row["state"]


def test_date_only_macro_calendar_connects_verified_same_day_release_period():
    c = context(event(indicator="US_PPI", period="", date="2026-11-13", release_at="2026-11-13",
                      release_precision="date"))
    c["economic_releases"] = [dict(indicator="US_PPI", period="2026-10", actual=.3,
        status="released", basis="MoM", unit="%", release_at="2026-11-13T08:30:00-05:00")]
    row = event_watch_rows(c, [], NOW)[0]
    assert row["state"] == "공식 결과 확인" and row["observed"].startswith("결과 2026-10")
    c["economic_releases"][0]["release_at"] = "2026-10-15T08:30:00-04:00"
    assert "결과 미확인" in event_watch_rows(c, [], NOW)[0]["state"]


def test_identical_option_interpretation_is_not_repeated_per_trading_date():
    c = context(event(indicator="US_VIX_LAST_TRADE"), event(indicator="US_VIX_STANDARD_EXPIRY", date="2026-11-18"))
    rendered = "\n".join(event_watch_lines(c, [], [], NOW))
    assert rendered.count("만기만으로 상승·하락을 예측하지 않음") == 1


def test_reader_connects_watch_once_without_changing_audit_or_decisions():
    from stock_lab_core.report_reading import compose_reading_report, AUDIT_TITLE
    original = "# 합성 리포트\n## 다가오는 일정\n일정·촉매 | 시점·상태 | 근거\n--- | --- | ---\n정부 지원 시한 | 재확인 필요 | 공식 보관값\n## 내 보유 종목 영향\n판정 원문 유지"
    c = context(event())
    rows = [{"티커": "NVDA", "보유여부": True, "판정코드": "BLOCK", "Adj점수": 7}]
    before = deepcopy((c, rows))
    output = compose_reading_report(original, context=c, news=[], summary_rows=rows, now=NOW)
    main, audit = output.split("## " + AUDIT_TITLE, 1)
    assert main.count("**계속 볼 흐름**") == 1
    assert "미국 소매판매(속보)" in main and "11/17 22:30 KST" in main
    assert "정부 지원 시한 | 재확인 필요" in main
    assert audit.endswith(original) and (c, rows) == before


@pytest.mark.parametrize("changes", [{"price_kind": "intraday"}, {"is_active": True}, {"stale": True}, {"date": "2026-11-16"}])
def test_ongoing_watch_does_not_present_unconfirmed_prices_as_close(changes):
    c = context()
    c.update(sessions={"US": changes.get("date", "2026-11-13")},
             prices={"IGV": dict({"date": "2026-11-13", "return": .03}, **changes)})
    assert "IGV +3.00%" not in "\n".join(event_watch_lines(c, [], [], NOW))
