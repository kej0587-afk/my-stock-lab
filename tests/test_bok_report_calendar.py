"""BOK schedule-to-report contracts, verified against primary sources 2026-11-15.

The November 26 meeting is already connected; these tests add no live collector.
Official date evidence (no announcement time or policy outcome inferred):
https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A&syear=2026
https://www.bok.or.kr/portal/singl/mainEvent/listCldr.do?date=2026-11&menuNo=200035
Original annual notice, published 2025-10-30:
https://www.bok.or.kr/portal/bbs/B0000502/view.do?nttId=10094300&menuNo=201265
"""

from copy import deepcopy
from datetime import datetime

import pytest
import requests

from stock_lab_core import release_calendar as calendar
from stock_lab_core.report_event_watch import event_watch_lines, event_watch_rows


NOW = datetime.fromisoformat("2026-11-15T23:08:00+09:00")
INDICATOR = "KR_BOK_RATE_DECISION"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("BOK report calendar contracts must not use the network")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


@pytest.fixture
def collected(monkeypatch):
    # Exercise the real public collector's BOK connection even when all unrelated
    # sources fail; only unrelated loaders are replaced, never _bok_source.
    def unavailable(name="other", *args, **kwargs):
        return [], {"name": str(name), "status": "unavailable", "reason": "offline_fixture"}

    for name in ("_load_bls_source", "_load_source", "_meta_source", "_tesla_source"):
        monkeypatch.setattr(calendar, name, unavailable)
    return calendar.load_release_calendar(now=NOW)


def report_context(collected):
    return {
        "calendar_events": deepcopy(collected["events"]),
        "calendar_sources": deepcopy(collected["sources"]),
        "market_watch_sources": [],
        "economic_releases": [],
    }


def test_bok_is_connected_when_other_calendars_fail(collected):
    source = next(s for s in collected["sources"] if s["name"] == "Bank of Korea MPC")
    assert collected["connected"] and source["status"] == "connected"
    assert source["provider"] == "verified_fixture" and source["coverage_year"] == 2026
    rows = event_watch_rows(report_context(collected), [], NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["indicator"] == INDICATOR and row["date"] == "2026-11-26"
    assert row["source_url"] == calendar.BOK_URL
    assert row["source_published_at"] == "2025-10-30"
    assert row["source_verified_at"] and row["source_kind"] == "verified_fixture"
    assert row["release_precision"] == "date" and row["release_at"] == row["date"]
    assert row["timezone"] == "Asia/Seoul" and "시각 미확인" in row["timing"]
    assert row["state"] == "예정" and row["observed"] == ""
    assert all(row.get(key) is None for key in ("actual", "policy_rate", "action", "result_release_at"))


def test_existing_reading_report_retains_bok_without_duplicates_or_input_changes(collected):
    from stock_lab_core.report_reading import AUDIT_TITLE, compose_reading_report

    context = report_context(collected)
    holdings = [{"티커": "005930.KS", "보유여부": True, "Adj점수": 7, "판정코드": "BLOCK"}]
    before = deepcopy((context, holdings))
    original = "# 합성 시황\n## 다가오는 일정\n## 내 보유 종목 영향\n판정 원문 유지"
    output = compose_reading_report(original, context=context, news=[], summary_rows=holdings, now=NOW)
    main, audit = output.split("## " + AUDIT_TITLE, 1)
    rows = [line for line in main.splitlines() if calendar.BOK_URL in line]
    assert len(rows) == 1
    assert "2026-11-26" in rows[0] and "예정" in rows[0] and "시각 미확인" in rows[0]
    assert "공식 결과 확인" not in rows[0]
    # The integrated report moves holdings to the portfolio section and retains
    # only remaining evidence below the audit heading, rather than appending a copy.
    portfolio = main.split("## 포트폴리오 · 교체 검토", 1)[1].split("\n## ", 1)[0]
    assert "판정 원문 유지" in portfolio
    assert output.count("판정 원문 유지") == 1
    assert (context, holdings) == before


@pytest.mark.parametrize(("at", "state"), [
    ("2026-11-25T23:59:00+09:00", "예정"),
    ("2026-11-26T00:01:00+09:00", "예정"),
    ("2026-11-26T23:59:00+09:00", "예정"),
    ("2026-11-27T00:01:00+09:00", "예정일 경과·결과 미확인"),
])
def test_calendar_date_passage_never_proves_a_policy_result(collected, at, state):
    rows = event_watch_rows(report_context(collected), [], datetime.fromisoformat(at))
    assert len(rows) == 1 and rows[0]["state"] == state
    assert rows[0]["observed"] == "" and "시각 미확인" in rows[0]["timing"]


@pytest.mark.parametrize(("indicator", "release_at", "expected_observation"), [
    (INDICATOR, "2026-10-22T10:00:00+09:00", "직전 관측(이번 예상 아님)"),
    ("KR_POLICY_RATE", "2026-11-13T10:00:00+09:00", ""),
    (INDICATOR, "2026-11-26T10:00:00+09:00", ""),
])
def test_prior_or_current_rate_and_future_value_do_not_confirm_next_meeting(
    collected, indicator, release_at, expected_observation,
):
    context = report_context(collected)
    # Deliberately synthetic rate/time: not a claim about any BOK decision.
    context["economic_releases"] = [{
        "indicator": indicator, "period": release_at[:7], "actual": 99.25,
        "unit": "%", "status": "released", "release_at": release_at,
    }]
    row = event_watch_rows(context, [], NOW)[0]
    assert row["state"] == "예정"
    if expected_observation:
        assert row["observed"].startswith(expected_observation)
    else:
        assert row["observed"] == ""


def test_repeated_bok_event_is_not_a_second_meeting(collected):
    context = report_context(collected)
    rows = event_watch_rows(context, [], NOW, pipeline={"events": deepcopy(context["calendar_events"])})
    assert len(rows) == 1 and rows[0]["date"] == "2026-11-26"


@pytest.mark.parametrize("year", [2025, 2027])
def test_unverified_year_never_reuses_2026_meetings(year):
    now = NOW.replace(year=year)
    events, source = calendar._bok_source(calendar._clock(now))
    assert events == [] and source["status"] == "unavailable"
    context = {"calendar_events": events, "calendar_sources": [source], "market_watch_sources": []}
    assert event_watch_rows(context, [], now) == []
    assert "일정이 없다는 뜻은 아닙니다" in "\n".join(event_watch_lines(context, [], [], now))


def test_official_bok_result_turns_the_meeting_row_into_a_result(collected):
    context = report_context(collected)
    # Synthetic rates; the collector only sets official after matching the posted 통화정책방향 to the meeting day.
    context["central_bank_results"] = [{
        "bank": "BOK", "status": "official", "indicator": INDICATOR, "action": "hike", "previous_rate": 3.0,
        "policy_rate": 3.25, "date": "2026-11-26", "decision_date": "2026-11-26", "release_at": None,
        "source_url": "https://www.bok.or.kr/portal/bbs/P0000559/view.do?nttId=11000001&menuNo=200690"}]
    row = event_watch_rows(context, [], datetime.fromisoformat("2026-11-26T20:40:00+09:00"))[0]
    assert row["state"] == "공식 결과 확인"
    assert row["observed"].startswith("결과 인상 · 기준금리 3.00% → 3.25% ([공식 결정 근거](https://www.bok.or.kr/")
    context["central_bank_results"][0]["status"] = "missing"
    assert event_watch_rows(context, [], datetime.fromisoformat("2026-11-26T20:40:00+09:00"))[0]["state"] == "예정"
