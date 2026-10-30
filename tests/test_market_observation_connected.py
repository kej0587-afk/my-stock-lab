"""Finite rotation universe and explicit conventional-time study buckets."""

from copy import deepcopy
import json
import socket
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.market_observation import (
    DEFAULT_SECTOR_MAP, ROTATION_UNIVERSE, build_event_study,
    build_observation_hypotheses, build_sector_rotation, historical_earnings_events,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Connected observation tests are offline")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def prices(dates):
    return pd.DataFrame({"Close": 100 + np.arange(len(dates))}, index=dates)


def schedule(dates):
    return pd.DataFrame({
        "market_open": [pd.Timestamp(f"{day.date()} 09:30", tz="America/New_York") for day in dates],
        "market_close": [pd.Timestamp(f"{day.date()} 16:00", tz="America/New_York") for day in dates],
    }, index=dates)


def test_fixed_30_etfs_are_grounded_in_existing_universe_and_markets_stay_separate():
    from stock_lab_core.money_flow import MONEY_FLOW_UNIVERSE
    grounded = {row["ticker"] for row in MONEY_FLOW_UNIVERSE}
    assert set(ROTATION_UNIVERSE) <= grounded
    assert len(ROTATION_UNIVERSE) == len(set(ROTATION_UNIVERSE)) == 30
    assert sum(row["market"] == "US" for row in DEFAULT_SECTOR_MAP.values()) == 20
    dates = pd.bdate_range("2025-01-02", periods=150)
    frames = {ticker: prices(dates if meta["market"] == "US" else dates[:-1])
              for ticker, meta in DEFAULT_SECTOR_MAP.items()}
    frames.update({"^GSPC": prices(dates), "^KS11": prices(dates[:-1])})
    result = build_sector_rotation(frames, sessions={"US": str(dates[-1].date()), "KR": str(dates[-2].date())},
                                   as_of="2026-01-01T00:00:00Z")
    assert not result["excluded"]
    assert result["markets"]["US"]["sample_count"] == 20
    assert result["markets"]["KR"]["sample_count"] == 10
    assert result["markets"]["US"]["date"] != result["markets"]["KR"]["date"]


@pytest.mark.parametrize("ticker,extra", [("SGOV", {}), ("BIL", {}), ("SHV", {}), ("459580.KS", {}),
    ("488770.KS", {}), ("NEW", {"name": "Cash management ETF"}),
    ("NEW", {"sector": "머니마켓"}), ("NEW", {"name": "CD금리액티브"})])
def test_cash_cannot_enter_sector_rotation_through_custom_mapping(ticker, extra):
    mapping = {ticker: {"market": "US", "kind": "sector_etf", "sector": "fake sector", **extra}}
    result = build_sector_rotation({}, sessions={"US": "2026-10-28"}, as_of="2026-10-30T00:00:00Z", sector_map=mapping)
    assert result["excluded"][0]["reason"] == "not_unlevered_sector_etf"


def test_report_collects_rotation_histories_without_expanding_live_quote_requests(monkeypatch):
    from stock_lab_core import prices as provider, report_quotes, report_live
    from stock_lab_core.report_context import collect_report_context
    from stock_lab_core.report_prices import SECTORS
    batch, quotes = Mock(return_value={}), Mock(return_value={})
    monkeypatch.setattr(provider, "load_price_frames_batch", batch)
    monkeypatch.setattr(provider, "load_price_df", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(report_live, "supplement_kr_indices", lambda frames: frames)
    monkeypatch.setattr(report_quotes, "load_report_quotes", quotes)
    collect_report_context(now=pd.Timestamp("2026-10-30T08:00:00+09:00"), economic_releases=[],
        calendar={"events": [], "sources": []}, scenario_frames={})
    assert set(ROTATION_UNIVERSE) <= set(batch.call_args_list[0].args[0])
    quotes.assert_called_once()
    assert set(quotes.call_args.args[0]) == {ticker for ticker in SECTORS if not ticker.endswith((".KS", ".KQ"))}
    assert set(quotes.call_args.kwargs["kr_tickers"]) == {ticker for ticker in SECTORS if ticker.endswith((".KS", ".KQ"))} | {"0167A0.KS"}


@pytest.fixture
def event_input():
    dates = pd.bdate_range("2025-03-03", "2025-04-04")
    event = {"event_id": "release-1", "ticker": "XLK", "market": "US", "event_type": "earnings",
             "confirmed": True, "release_at": "2025-03-14T08:30:00-04:00", "source_url": "https://example.test/release",
             "release_precision": "schedule_rule", "release_time_confirmed": False, "date": "2025-03-14",
             "release_date_confirmed": True, "schedule_rule": "08:30 America/New_York",
             "schedule_rule_source_url": "https://example.test/schedule"}
    return event, prices(dates), schedule(dates)


def study(data, events=None, **kwargs):
    event, frame, sessions = data
    return build_event_study(events if events is not None else [event], {"XLK": frame},
        as_of=kwargs.pop("as_of", "2025-04-10T00:00:00Z"), window=2,
        session_schedules={"US": sessions}, **kwargs)


def test_conventional_times_stay_out_of_confirmed_counts_groups_and_hypotheses(event_input):
    event, _, _ = event_input
    events = [dict(event, event_id=f"e{i}", date=f"2025-03-{day}", release_at=f"2025-03-{day}T08:30:00-04:00")
              for i, day in enumerate((14, 21, 28))]
    before = deepcopy(events)
    result = study(event_input, events)
    assert result["sample_count"] == 0 and result["observations"] == result["groups"] == []
    assert result["assumption_sample_count"] == result["assumption_groups"][0]["sample_count"] == 3
    assert all(row["announced_at"] is None and row["assumed_release_at"] and row["time_assumption"]
               and row["release_time_confirmed"] is False for row in result["assumption_observations"])
    assert result["assumption_observations"][0]["post_return"] == pytest.approx(110 / 108 - 1)
    assert build_observation_hypotheses(event_study=result)[2]["status"] == "insufficient_data"
    assert events == before
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("changes,reason", [
    ({"release_date_confirmed": False}, "missing_confirmed_release_date"),
    ({"date": None}, "missing_confirmed_release_date"),
    ({"date": "2025-02-30"}, "missing_confirmed_release_date"),
    ({"schedule_rule": None}, "missing_time_assumption_or_source"),
    ({"schedule_rule_source_url": None}, "missing_time_assumption_or_source"),
    ({"release_at": None}, "missing_assumed_timestamp"),
    ({"release_at": "2025-03-14"}, "missing_assumed_timestamp"),
    ({"release_at": "2025-03-15T08:30:00-04:00"}, "assumed_timestamp_date_mismatch"),
    ({"date": "2027-03-14", "release_at": "2027-03-14T08:30:00-04:00"}, "future_event"),
    ({"known_at": "2027-01-01T00:00:00Z"}, "confirmation_not_available_as_of"),
    ({"release_at": "2025-03-14T14:00:00-04:00"}, "intraday_requires_intraday_prices"),
    ({"release_precision": "estimated", "release_time_confirmed": True}, "unconfirmed_event"),
])
def test_assumed_time_never_supplies_a_missing_date_or_bypasses_existing_checks(event_input, changes, reason):
    event_input[0].update(changes)
    result = study(event_input)
    assert result["sample_count"] == result["assumption_sample_count"] == 0
    assert result["skipped"][0]["reason"] == reason


def test_assumption_window_must_finish_and_missing_prices_do_not_compress_it(event_input):
    result = study(event_input, as_of="2025-03-17T15:59:59-04:00")
    assert result["skipped"][0]["reason"] == "unfinished_post_window"
    event, frame, sessions = event_input
    result = study((event, frame.drop(pd.Timestamp("2025-03-14")), sessions))
    assert result["skipped"][0]["reason"] == "missing_price_in_event_window"


@pytest.mark.parametrize("reverse", [False, True])
def test_confirmed_timestamp_supersedes_assumed_same_id_or_alias_without_mixing(event_input, reverse):
    event = event_input[0]
    exact = dict(event, event_id="exact", release_precision="datetime", release_time_confirmed=True)
    events = [event, exact]
    result = study(event_input, events[::-1] if reverse else events)
    assert result["sample_count"] == 1 and result["assumption_sample_count"] == 0
    assert result["skipped"][0]["reason"] == "superseded_by_confirmed_timestamp"


def test_conventional_duplicates_and_conflicts_do_not_multiply_samples(event_input):
    event = event_input[0]
    result = study(event_input, [event, dict(event, event_id="alias")])
    assert result["assumption_sample_count"] == 1
    assert result["skipped"][0]["reason"] == "duplicate_event"
    result = study(event_input, [event, dict(event, release_at="2025-03-14T08:00:00-04:00")])
    assert result["assumption_sample_count"] == 0
    assert {row["reason"] for row in result["skipped"]} == {"conflicting_event_timestamp"}


SOURCE = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm"


@pytest.fixture
def connected_earnings():
    dates = pd.bdate_range("2026-09-01", "2026-11-13")
    result = dict(ticker="GOOGL", fiscal_period="2026Q3", status="official_result", release_date="2026-10-28",
        release_precision="datetime", release_at="2026-10-28T16:05:00-04:00", checked_at="2026-10-29T10:59:00+09:00",
        source_url=SOURCE)
    return {"earnings_results": [result]}, {"GOOGL": prices(dates)}, {"US": schedule(dates)}


def test_connected_official_results_map_to_completed_confirmed_events(connected_earnings):
    context, frames, schedules = connected_earnings
    before = deepcopy(context)
    adapted = historical_earnings_events(context, as_of="2026-11-13T22:00:00Z")
    assert not adapted["skipped"] and len(adapted["events"]) == 1
    result = build_event_study(adapted["events"], frames, as_of="2026-11-13T22:00:00Z", session_schedules=schedules)
    assert result["sample_count"] == 1 and result["assumption_sample_count"] == 0
    assert context == before


def test_connected_date_only_result_needs_explicit_assumption_and_supplied_actual_close(connected_earnings):
    context, frames, schedules = connected_earnings
    context["earnings_results"][0].update(release_precision="date", release_at=None)
    schedules["US"].loc["2026-10-28", "market_close"] = pd.Timestamp("2026-10-28T13:00:00-04:00")
    args = dict(as_of="2026-11-13T22:00:00Z", session_schedules=schedules)
    assert not historical_earnings_events(context, **args)["events"]
    assert not historical_earnings_events(context, as_of=args["as_of"], allow_conventional=True)["events"]
    adapted = historical_earnings_events(context, allow_conventional=True, **args)
    event, = adapted["events"]
    assert event["date"] == "2026-10-28"
    assert event["release_at"] == "2026-10-28T17:00:00+00:00"
    assert not event["release_time_confirmed"] and event["release_precision"] == "schedule_rule"
    result = build_event_study(adapted["events"], frames, **args)
    assert result["sample_count"] == 0 and result["assumption_sample_count"] == 1
    incomplete = build_event_study(adapted["events"], frames, as_of="2026-10-30T22:00:00Z", session_schedules=schedules)
    assert incomplete["assumption_sample_count"] == 0
    assert incomplete["skipped"][0]["reason"] == "unfinished_post_window"


@pytest.mark.parametrize("changes", [
    {"status": "scheduled"}, {"source_url": "https://unknown.test/result"},
    {"release_date": None}, {"release_date": "2027-01-01"},
    {"checked_at": "2027-01-01T00:00:00Z"}, {"checked_at": None},
    {"release_at": "2026-10-27T16:00:00-04:00"}, {"release_time_confirmed": False},
])
def test_connected_adapter_rejects_missing_future_or_mismatched_evidence(connected_earnings, changes):
    context, _, schedules = connected_earnings
    context["earnings_results"][0].update(changes)
    result = historical_earnings_events(context, as_of="2026-11-13T22:00:00Z", session_schedules=schedules, allow_conventional=True)
    assert not result["events"] and result["skipped"]


def test_calendar_only_requires_actual_released_result_not_elapsed_or_call(connected_earnings):
    _, _, schedules = connected_earnings
    event = dict(ticker="META", fiscal_period="2026Q3", event_status="released", event_kind="results",
        date="2026-10-21", release_date_confirmed=True, release_time_confirmed=False, release_precision="date",
        source_url="https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Third-Quarter-2026-Results/default.aspx",
        source_verified_at="2026-10-28T08:25:44+00:00")
    args = dict(as_of="2026-11-13T22:00:00Z", session_schedules=schedules, allow_conventional=True)
    assert len(historical_earnings_events({"calendar_events": [event]}, **args)["events"]) == 1
    for changes in ({"event_status": "elapsed_unconfirmed"}, {"event_kind": "conference_call"},
                    {"release_date_confirmed": False}, {"event_status": "reported_results"}):
        assert not historical_earnings_events({"calendar_events": [dict(event, **changes)]}, **args)["events"]
