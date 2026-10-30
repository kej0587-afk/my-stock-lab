"""Real exchange-calendar bridge with offline official-result fixtures."""

from copy import deepcopy
import socket

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import report_eventstudy as bridge
from stock_lab_core.market_observation import build_event_study


SOURCE = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Event context must not fetch prices, results or calendars online")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    clear = bridge._exchange_schedule.cache_clear
    clear()
    yield
    clear()


@pytest.fixture
def context():
    pytest.importorskip("exchange_calendars")
    sessions = bridge._exchange_schedule("US", "2026-09-01", "2026-11-30")
    return {"earnings_results": [dict(ticker="GOOGL", fiscal_period="2026Q3", status="official_result",
        release_date="2026-10-28", release_precision="date", release_at=None,
        checked_at="2026-10-29T10:59:00+09:00", source_url=SOURCE)],
        "price_frames": {"GOOGL": pd.DataFrame({"Close": 100 + np.arange(len(sessions))}, index=sessions.index)}}


def test_actual_xnys_holiday_early_close_and_xkrx_timezone_are_preserved():
    pytest.importorskip("exchange_calendars")
    us = bridge._exchange_schedule("US", "2026-11-20", "2026-11-30")
    assert pd.Timestamp("2026-11-26") not in us.index
    assert us.loc["2026-11-27", "market_close"] == pd.Timestamp("2026-11-27T18:00:00Z")
    kr = bridge._exchange_schedule("KR", "2026-10-01", "2026-10-30")
    assert pd.Timestamp("2026-10-09") not in kr.index
    assert kr.loc["2026-10-28", "market_close"] == pd.Timestamp("2026-10-28T06:30:00Z")
    assert str(kr.market_open.dt.tz) == "UTC"


def test_complete_official_date_only_results_produce_separate_assumption_samples(context):
    before = deepcopy(context["earnings_results"])
    output = bridge.collect_event_study_context(context, "2026-11-13T22:00:00Z")
    assert set(output) == {"events", "schedules", "diagnostics"}
    event, = output["events"]
    assert event["date"] == "2026-10-28" and event["release_precision"] == "schedule_rule"
    assert event["release_at"] == "2026-10-28T20:00:00+00:00"
    assert event["release_time_confirmed"] is False and "assumption" in event["schedule_rule"]
    result = build_event_study(output["events"], context["price_frames"],
        as_of="2026-11-13T22:00:00Z", session_schedules=output["schedules"])
    assert result["sample_count"] == 0 and result["assumption_sample_count"] == 1
    assert context["earnings_results"] == before
    output["schedules"]["US"].iloc[0, 0] = pd.NaT
    again = bridge.collect_event_study_context(context, "2026-11-13T22:00:00Z")
    assert pd.notna(again["schedules"]["US"].iloc[0, 0])


def test_verified_timestamp_remains_confirmed_not_conventional(context):
    context["earnings_results"][0].update(release_precision="datetime", release_at="2026-10-28T16:05:00-04:00")
    output = bridge.collect_event_study_context(context, "2026-11-13T22:00:00Z")
    assert len(output["events"]) == 1
    assert output["events"][0]["release_time_confirmed"] is True
    assert output["diagnostics"][-1]["confirmed_sample_count"] == 1
    assert output["diagnostics"][-1]["assumption_sample_count"] == 0


@pytest.mark.parametrize("defect,reason", [
    ("unfinished", "unfinished_post_window"), ("prices", "missing_price_in_event_window"),
    ("date", "missing_confirmed_release_date"), ("future", "future_event"),
    ("unknown", "missing_event_identity_or_official_source"), ("scheduled", "unconfirmed_publication"),
])
def test_missing_unfinished_future_and_unknown_results_are_not_samples(context, defect, reason):
    now = "2026-11-13T22:00:00Z"
    row = context["earnings_results"][0]
    if defect == "unfinished":
        now = "2026-10-30T22:00:00Z"
    elif defect == "prices":
        context["price_frames"]["GOOGL"] = context["price_frames"]["GOOGL"].drop(pd.Timestamp("2026-10-29"))
    elif defect == "date":
        row["release_date"] = None
    elif defect == "future":
        row["release_date"] = "2027-01-01"
    elif defect == "unknown":
        row["source_url"] = "https://unknown.test/result"
    else:
        row["status"] = "scheduled"
    output = bridge.collect_event_study_context(context, now)
    assert output["events"] == []
    assert reason in {item.get("reason") for item in output["diagnostics"]}


@pytest.mark.parametrize("error,reason", [(ModuleNotFoundError("private_path"), "exchange_calendars_not_installed"),
                                          (ValueError("private_path"), "exchange_calendar_unavailable")])
def test_calendar_failure_never_falls_back_to_weekdays(context, monkeypatch, error, reason):
    def fail(*args):
        raise error
    monkeypatch.setattr(bridge, "_exchange_schedule", fail)
    result = bridge.collect_event_study_context(context, "2026-11-13T22:00:00Z")
    assert not result["events"] and not result["schedules"]
    assert result["diagnostics"][0]["reason"] == reason
    assert "private_path" not in str(result)


def test_empty_context_does_not_even_build_a_calendar(monkeypatch):
    def fail(*args):
        pytest.fail("No calendar needed without connected evidence")
    monkeypatch.setattr(bridge, "_exchange_schedule", fail)
    result = bridge.collect_event_study_context({}, "2026-11-13T22:00:00Z")
    assert not result["events"] and not result["schedules"]


def test_future_ir_calendar_and_elapsed_call_are_not_published_results():
    context = {"calendar_events": [dict(ticker="NVDA", fiscal_period="FY2027Q3", date="2026-11-17",
        event_status="scheduled", event_kind="conference_call", release_date_confirmed=False,
        source_url="https://investor.nvidia.com/", source_verified_at="2026-10-28T00:00:00Z")]}
    output = bridge.collect_event_study_context(context, "2026-10-30T12:00:00Z")
    assert not output["events"]
    assert "unconfirmed_publication" in {row.get("reason") for row in output["diagnostics"]}
