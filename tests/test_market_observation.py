"""Offline contracts for observation-only calculations and their integration API."""

from copy import deepcopy
import json
import socket

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.market_observation import (
    DEFAULT_NEWS_TAGS,
    DEFAULT_SECTOR_MAP,
    build_event_study,
    build_observation_hypotheses,
    build_sector_rotation,
    tag_candidate_news,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Observations must not access the network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def ohlcv(dates, values):
    return pd.DataFrame({"Open": values, "High": values, "Low": values,
                         "Close": values, "Volume": 1000}, index=dates)


def mapping(*tickers, market="US"):
    return {ticker: {"market": market, "sector": ticker, "kind": "sector_etf"} for ticker in tickers}


@pytest.fixture
def rotation_input():
    dates = pd.bdate_range("2025-01-02", periods=150)
    base = 100 * 1.001 ** np.arange(len(dates))
    return {"^GSPC": ohlcv(dates, base), "XLK": ohlcv(dates, 50 * 1.003 ** np.arange(len(dates)))}, dates


def rotation(frames, dates, flows=None, **kwargs):
    return build_sector_rotation(frames, flows, sessions={"US": dates[-1].date().isoformat()},
        as_of="2026-01-01T00:00:00Z", sector_map=kwargs.pop("sector_map", mapping("XLK")), **kwargs)


def only_row(result):
    return result["markets"]["US"]["rows"][0]


def test_rotation_is_ratio_change_not_rs_level_and_has_nonoverlapping_acceleration(rotation_input):
    frames, dates = rotation_input
    flows = pd.DataFrame([{"Ticker": "XLK", "기준일": dates[-1].date().isoformat(), "돈흐름점수": 17,
                           "3개월수익률": 99, "가속도": 99}])
    row = only_row(rotation(frames, dates, flows))
    assert row["rs_5d_change"] == pytest.approx((1.003 / 1.001) ** 5 - 1)
    assert row["rs_20d_change"] == pytest.approx((1.003 / 1.001) ** 20 - 1)
    assert row["return_3m"] == pytest.approx(1.003 ** 63 - 1)
    assert row["accel_3m"] == pytest.approx(0)
    assert row["money_flow_score"] == 17
    assert row["rs_20d_start"] == dates[-21].date().isoformat()
    assert row["missing"] == []


def test_rotation_uses_nonoverlapping_prior_63_sessions(rotation_input):
    frames, dates = rotation_input
    frames["XLK"]["Close"] = np.r_[np.full(87, 100.0), np.linspace(101, 150, 63)]
    row = only_row(rotation(frames, dates))
    assert row["return_3m"] == pytest.approx(.5)
    assert row["accel_3m"] == pytest.approx(.5)


@pytest.mark.parametrize("defect", ["gap", "stale", "nan", "inf", "zero", "duplicate", "undated"])
def test_rotation_excludes_missing_without_compressing_benchmark_sessions(rotation_input, defect):
    frames, dates = rotation_input
    if defect == "gap":
        frames["XLK"] = frames["XLK"].drop(dates[-8])
    elif defect == "stale":
        frames["XLK"] = frames["XLK"].iloc[:-1]
    elif defect == "duplicate":
        frames["XLK"] = pd.concat([frames["XLK"], frames["XLK"].iloc[[-8]]])
    elif defect == "undated":
        frames["XLK"] = frames["XLK"].reset_index(drop=True)
    else:
        frames["XLK"].loc[dates[-8], "Close"] = {"nan": np.nan, "inf": np.inf, "zero": 0}[defect]
    result = rotation(frames, dates)
    assert not result["markets"]
    assert result["excluded"]


def test_rotation_does_not_relabel_missing_benchmark_date(rotation_input):
    frames, dates = rotation_input
    frames["^GSPC"] = frames["^GSPC"].iloc[:-1]
    assert rotation(frames, dates)["excluded"][0]["reason"] == "missing_benchmark_close"


def test_future_prices_cannot_change_rotation_or_price_basis(rotation_input):
    frames, dates = rotation_input
    expected = only_row(rotation(frames, dates))
    for ticker in frames:
        future = ohlcv(pd.DatetimeIndex(["2027-01-04"]), [1e9])
        future["Adj Close"] = 10.0
        frames[ticker] = pd.concat([frames[ticker], future])
    assert only_row(rotation(frames, dates)) == expected


@pytest.mark.parametrize("as_of", ["2025-07-30T14:00:00Z", "2024-01-01T00:00:00Z"])
def test_future_or_unfinished_reference_session_is_rejected(rotation_input, as_of):
    frames, dates = rotation_input
    result = build_sector_rotation(frames, sessions={"US": "2025-07-30"}, as_of=as_of, sector_map=mapping("XLK"))
    assert result["excluded"][0]["reason"] == "unfinished_market_session"


def test_shared_adjustment_basis_and_no_mix(rotation_input):
    frames, dates = rotation_input
    frames["XLK"]["Adj Close"] = 10.0
    assert only_row(rotation(frames, dates))["price_basis"] == "Close"
    frames["^GSPC"]["Adj Close"] = 10.0
    assert only_row(rotation(frames, dates))["rs_20d_change"] == 0
    frames["^GSPC"] = frames["^GSPC"].drop(columns="Close")
    frames["XLK"] = frames["XLK"].drop(columns="Adj Close")
    assert not rotation(frames, dates)["markets"]


@pytest.mark.parametrize("flow", [[], [{"Ticker": "XLK", "돈흐름점수": 99}],
    [{"Ticker": "XLK", "기준일": "2099-01-01", "돈흐름점수": 99}]])
def test_missing_or_undated_flow_is_not_zero(rotation_input, flow):
    frames, dates = rotation_input
    row = only_row(rotation(frames, dates, flow))
    assert row["money_flow_score"] is None
    assert "money_flow_score" in row["missing"]


def test_conflicting_flow_rows_not_last_write_wins(rotation_input):
    frames, dates = rotation_input
    rows = [{"Ticker": "XLK", "기준일": str(dates[-1].date()), "돈흐름점수": score} for score in (1, 2)]
    assert only_row(rotation(frames, dates, rows))["money_flow_score"] is None


def test_short_3m_history_is_explicit_not_fabricated(rotation_input):
    frames, dates = rotation_input
    frames = {key: value.tail(21) for key, value in frames.items()}
    row = only_row(rotation(frames, dates))
    assert row["return_3m"] is None and row["accel_3m"] is None
    assert len(row["missing"]) == 3


def test_rankings_top_bottom_and_improving_laggards_are_bounded(rotation_input):
    frames, dates = rotation_input
    tickers = [f"ETF{i}" for i in range(9)]
    for i, ticker in enumerate(tickers):
        values = 100 * (1.0005 + i * .0001) ** np.arange(len(dates))
        if i < 3:
            values[-5:] *= 1.001 ** np.arange(1, 6)
        frames[ticker] = ohlcv(dates, values)
    market = rotation(frames, dates, sector_map=mapping(*tickers))["markets"]["US"]
    assert len(market["rows"]) == 9
    assert [row["ticker"] for row in market["top3"]] == ["ETF8", "ETF7", "ETF6"]
    assert len(market["bottom3"]) == len(market["improving_laggards3"]) == 3
    assert all(row["rs_20d_change"] < 0 < row["rs_5d_change"] for row in market["improving_laggards3"])


@pytest.mark.parametrize("ticker,extra", [("SOXL", {}), ("RAM", {}), ("PSQ", {}), ("TECL", {}), ("^VIX", {}), ("TLT", {}),
    ("GLD", {}), ("USDKRW=X", {}), ("SPY", {}), ("NEW", {"inverse": True}),
    ("NEW", {"name": "2X sector ETF"}), ("NEW", {"kind": "macro"})])
def test_explicit_mappings_cannot_include_macros_or_leveraged_products(rotation_input, ticker, extra):
    frames, dates = rotation_input
    frames[ticker] = frames["XLK"]
    sectors = mapping(ticker)
    sectors[ticker].update(extra)
    result = rotation(frames, dates, sector_map=sectors)
    assert not result["markets"]
    assert result["excluded"][0]["reason"] == "not_unlevered_sector_etf"


def test_market_benchmarks_have_separate_dates_and_rankings(rotation_input):
    frames, dates = rotation_input
    kr_dates = dates[:-1]
    frames["^KS11"] = ohlcv(kr_dates, np.full(len(kr_dates), 100.0))
    frames["396500.KS"] = ohlcv(kr_dates, np.arange(len(kr_dates)) + 100.0)
    sectors = dict(mapping("XLK"), **mapping("396500.KS", market="KR"))
    result = build_sector_rotation(frames, sessions={"US": str(dates[-1].date()), "KR": str(kr_dates[-1].date())},
        as_of="2026-01-01T00:00:00Z", sector_map=sectors)
    assert result["markets"]["KR"]["date"] != result["markets"]["US"]["date"]
    assert result["markets"]["KR"]["top3"][0]["benchmark"] == "^KS11"


@pytest.fixture
def event_input():
    dates = pd.bdate_range("2025-03-03", "2025-04-04")
    schedule = pd.DataFrame({"market_open": [pd.Timestamp(f"{d.date()} 09:30", tz="America/New_York") for d in dates],
                             "market_close": [pd.Timestamp(f"{d.date()} 16:00", tz="America/New_York") for d in dates]}, index=dates)
    frame = ohlcv(dates, 100 + np.arange(len(dates), dtype=float))
    event = {"event_id": "release-1", "ticker": "XLK", "market": "US", "event_type": "earnings",
             "confirmed": True, "announced_at": "2025-03-14T16:01:00-04:00", "source_url": "https://example.test/release/1"}
    return event, frame, schedule


def study(event_input, events=None, **kwargs):
    event, frame, schedule = event_input
    return build_event_study([event] if events is None else events, {"XLK": frame},
        as_of=kwargs.pop("as_of", "2025-04-10T00:00:00Z"), window=kwargs.pop("window", 2),
        session_schedules={"US": schedule}, **kwargs)


@pytest.mark.parametrize("announced_at,expected", [
    ("2025-03-14T08:00:00-04:00", "2025-03-14"),
    ("2025-03-14T09:30:00-04:00", "2025-03-14"),
    ("2025-03-14T16:00:00-04:00", "2025-03-17"),
    ("2025-03-14T16:01:00-04:00", "2025-03-17"),
    ("2025-03-15T10:00:00-04:00", "2025-03-17"),
    ("2025-03-17T21:00:00+09:00", "2025-03-17"),
    ("2025-03-07T16:01:00-05:00", "2025-03-10"),
])
def test_event_announcement_alignment_including_dst_and_weekend(event_input, announced_at, expected):
    event_input[0]["announced_at"] = announced_at
    result = study(event_input)
    assert result["sample_count"] == 1
    assert result["observations"][0]["reaction_date"] == expected


def test_event_actual_early_close_and_holiday_schedule(event_input):
    event, frame, schedule = event_input
    schedule.loc["2025-03-14", "market_close"] = pd.Timestamp("2025-03-14 13:00", tz="America/New_York")
    schedule = schedule.drop(pd.Timestamp("2025-03-17"))
    event["announced_at"] = "2025-03-14T13:01:00-04:00"
    result = study((event, frame, schedule))
    assert result["observations"][0]["reaction_date"] == "2025-03-18"


def test_event_n_session_return_distributions_and_counts(event_input):
    event, frame, schedule = event_input
    events = [dict(event, event_id=f"e-{i}", announced_at=f"2025-03-{day}T08:00:00-04:00")
              for i, day in enumerate((14, 21, 28))]
    result = study(event_input, events)
    group = result["groups"][0]
    assert result["sample_count"] == group["sample_count"] == 3
    sample = result["observations"][0]
    assert sample["baseline_date"] == "2025-03-13"
    assert sample["pre_return"] == pytest.approx(108 / 106 - 1)
    assert sample["post_return"] == pytest.approx(110 / 108 - 1)
    assert group["post"]["median"] == pytest.approx(np.median([s["post_return"] for s in result["observations"]]))
    assert group["post"]["positive_fraction"] == 1
    assert group["post"]["min"] <= group["post"]["p25"] <= group["post"]["p75"] <= group["post"]["max"]


@pytest.mark.parametrize("changes,reason", [
    ({"confirmed": False}, "unconfirmed_event"),
    ({"confirmed": "true"}, "unconfirmed_event"),
    ({"release_time_confirmed": False}, "unconfirmed_event"),
    ({"release_precision": "date"}, "unconfirmed_event"),
    ({"announced_at": "2025-03-14"}, "missing_confirmed_timestamp"),
    ({"announced_at": "2025-03-14T16:01:00"}, "missing_confirmed_timestamp"),
    ({"announced_at": None, "date": "2025-03-14"}, "missing_confirmed_timestamp"),
    ({"announced_at": "2027-01-01T08:00:00Z"}, "future_event"),
    ({"confirmed_at": "2027-01-01T08:00:00Z"}, "confirmation_not_available_as_of"),
    ({"source_url": None}, "missing_event_identity_or_source"),
    ({"event_id": None}, "missing_event_identity_or_source"),
    ({"announced_at": "2025-03-14T12:00:00-04:00"}, "intraday_requires_intraday_prices"),
])
def test_event_does_not_invent_dates_or_include_unconfirmed_or_future_evidence(event_input, changes, reason):
    event_input[0].update(changes)
    result = study(event_input)
    assert result["sample_count"] == 0 and not result["groups"]
    assert result["skipped"][0]["reason"] == reason


def test_unfinished_post_window_cannot_use_future_rows_already_in_frame(event_input):
    result = study(event_input, as_of="2025-03-18T15:59:59-04:00")
    assert result["sample_count"] == 0
    assert result["skipped"][0]["reason"] == "unfinished_post_window"
    assert study(event_input, as_of="2025-03-18T16:00:00-04:00")["sample_count"] == 1


def test_event_missing_day_cannot_compress_window(event_input):
    event, frame, schedule = event_input
    frame = frame.drop(pd.Timestamp("2025-03-17"))
    result = study((event, frame, schedule))
    assert result["sample_count"] == 0
    assert result["skipped"][0]["reason"] == "missing_price_in_event_window"


def test_event_deduplicates_ids_and_same_occurrence_aliases(event_input):
    event = event_input[0]
    result = study(event_input, [event, dict(event), dict(event, event_id="alias")])
    assert result["sample_count"] == 1
    assert [row["reason"] for row in result["skipped"]] == ["duplicate_event", "duplicate_event"]


def test_event_equivalent_timezone_timestamps_are_duplicates_not_conflicts(event_input):
    event = event_input[0]
    result = study(event_input, [event, dict(event, announced_at="2025-03-14T20:01:00Z")])
    assert result["sample_count"] == 1
    assert result["skipped"][0]["reason"] == "duplicate_event"


def test_event_conflicting_id_timestamps_exclude_both(event_input):
    event = event_input[0]
    result = study(event_input, [event, dict(event, announced_at="2025-03-13T16:01:00-04:00")])
    assert result["sample_count"] == 0
    assert {row["reason"] for row in result["skipped"]} == {"conflicting_event_timestamp"}


def test_event_release_schema_alias_and_dataframe(event_input):
    event = dict(event_input[0])
    event["release_at"] = event.pop("announced_at")
    event["indicator"] = event.pop("event_type")
    assert study(event_input, pd.DataFrame([event]))["sample_count"] == 1


def test_schedule_is_required_not_guessed_from_ohlcv(event_input):
    event, frame, _ = event_input
    result = build_event_study([event], {"XLK": frame}, as_of="2025-04-10T00:00:00Z")
    assert result["skipped"][0]["reason"] == "missing_or_invalid_session_schedule"


@pytest.mark.parametrize("defect", ["naive", "duplicate", "reversed"])
def test_invalid_session_schedules_fail_closed(event_input, defect):
    event, frame, schedule = event_input
    if defect == "naive":
        schedule["market_open"] = schedule.market_open.dt.tz_localize(None)
    elif defect == "duplicate":
        schedule = pd.concat([schedule, schedule.iloc[[0]]])
    else:
        schedule["market_close"] = schedule.market_open - pd.Timedelta(minutes=1)
    assert study((event, frame, schedule))["skipped"][0]["reason"] == "missing_or_invalid_session_schedule"


def test_news_tags_are_candidates_not_official_calendar_and_mapping_is_editable():
    news = [{"title": "Acme IPO and earnings policy discussion", "url": "https://example.test/news", "published_at": "2025-03-14",
             "confirmed": True, "release_at": "2025-04-01T08:00:00Z", "official_date": "2025-04-01"}]
    candidates = tag_candidate_news(news + news, entity_keywords={"ACME": ("Acme",)})
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["candidate_tags"] == ["earnings", "ipo", "policy"]
    assert candidate["candidate_tickers"] == ["ACME"]
    assert candidate["status"] == "unconfirmed" and candidate["confirmed"] is False
    assert candidate["official_date"] is None and candidate["release_at"] is None
    assert candidate["news_published_at"] == "2025-03-14"
    assert tag_candidate_news(news, tag_keywords={"custom": ("Acme",)})[0]["candidate_tags"] == ["custom"]
    assert tag_candidate_news(news, tag_keywords={}) == []
    assert tag_candidate_news([{"title": "A tripod and diplomatic visit"}]) == []


@pytest.mark.parametrize("keyword", ["FOMC", "fomc", "Federal Open Market Committee", "금통위", "금융통화위원회"])
def test_policy_committee_keywords_remain_unconfirmed_candidates(keyword):
    candidate = tag_candidate_news([{"title": f"{keyword} discussion", "official_date": "2026-11-01"}])[0]
    assert candidate["candidate_tags"] == ["policy"]
    assert candidate["confirmed"] is False
    assert candidate["official_date"] is None and candidate["release_at"] is None


@pytest.mark.parametrize("keyword", ["IPO", "상장 추진", "신규상장"])
def test_ipo_tags_do_not_infer_listing_status_and_respect_manual_context(keyword):
    news = [{"title": f"Acme {keyword} discussion"}]
    entities = {"ACME": ("Acme",)}
    candidate = tag_candidate_news(news, entity_keywords=entities)[0]
    assert candidate["candidate_listing_status"] == {"ACME": "unknown"}
    for status, expected in (("listed", "listed"), ("ipo_candidate", "ipo_candidate"), ("unsupported", "unknown")):
        manual = {"ACME": status}
        candidate = tag_candidate_news(news, entity_keywords=entities, listing_status_map=manual)[0]
        assert candidate["candidate_listing_status"] == {"ACME": expected}
        assert candidate["listing_status_basis"] == "manual_unverified"
        assert candidate["candidate_tags"] == ["ipo"]
        assert candidate["status"] == "unconfirmed" and candidate["official_date"] is None
        assert manual == {"ACME": status}


@pytest.mark.parametrize("direction", ["positive", "negative"])
def test_event_hypothesis_describes_observed_distribution_without_predicting_next_event(event_input, direction):
    event, frame, schedule = event_input
    if direction == "negative":
        frame = frame.copy()
        frame["Close"] = frame["Close"].iloc[::-1].to_numpy()
    events = [dict(event, event_id=f"e-{i}", announced_at=f"2025-03-{day}T08:00:00-04:00")
              for i, day in enumerate((14, 21, 28))]
    hypotheses = build_observation_hypotheses(event_study=study((event, frame, schedule), events))
    assert len(hypotheses) == 3
    result = hypotheses[2]
    assert f"has a {direction} median across 3 completed observations" in result["hypothesis"]
    assert "association is hypothetical" in result["hypothesis"]
    assert "not causal or a next-event prediction" in result["hypothesis"]
    assert "may repeat" not in result["hypothesis"]
    assert "next confirmed" not in result["falsifier"].lower()
    assert "comparable non-event windows" in result["falsifier"]


def test_exactly_three_hypotheses_with_explicit_missing_evidence():
    result = build_observation_hypotheses(candidate_news=[{"status": "unconfirmed"}])
    assert len(result) == 3
    assert len({r["id"] for r in result}) == 3
    for row in result:
        assert row["status"] == "insufficient_data"
        assert row["generator"] == "rule_based_no_llm"
        assert row["missing"] and row["falsifier"] and row["check_schedule"]
        assert row["not_trade_signal"] is True and row["evidence"] == []
    assert "not event samples" in result[2]["hypothesis"]


def test_unavailable_history_integrates_as_explicit_zero_and_three_fallbacks():
    rotated = build_sector_rotation({}, [], sessions={}, as_of="2026-10-28T12:00:00+09:00")
    studied = build_event_study([], {}, as_of="2026-10-28T12:00:00+09:00")
    assert studied["sample_count"] == 0
    assert studied["groups"] == studied["observations"] == []
    hypotheses = build_observation_hypotheses(rotated, studied)
    assert len(hypotheses) == 3
    assert all(h["status"] == "insufficient_data" and not h["evidence"] for h in hypotheses)


def test_hypotheses_grounded_in_calculations_with_falsifiers(rotation_input, event_input):
    frames, dates = rotation_input
    frames["XLF"] = ohlcv(dates, 100 * 1.0005 ** np.arange(len(dates)))
    frames["XLF"].loc[dates[-5:], "Close"] *= 1.001 ** np.arange(1, 6)
    rotated = rotation(frames, dates, sector_map=mapping("XLK", "XLF"))
    event = event_input[0]
    events = [dict(event, event_id=f"e-{i}", announced_at=f"2025-03-{day}T08:00:00-04:00")
              for i, day in enumerate((14, 21, 28))]
    studied = study(event_input, events)
    result = build_observation_hypotheses(rotated, studied)
    assert len(result) == 3 and all(row["status"] == "supported_observation" for row in result)
    assert result[0]["evidence"][0]["ticker"] == "XLK"
    assert result[1]["evidence"][0]["ticker"] == "XLF"
    assert result[2]["evidence"][0]["sample_count"] == 3
    assert "may retain" not in result[0]["hypothesis"]
    assert "not its continuation" in result[0]["hypothesis"]
    assert "not a reversal forecast" in result[1]["hypothesis"]
    result[0]["evidence"][0]["rs_5d_change"] = 99
    assert rotated["markets"]["US"]["rows"][1]["rs_5d_change"] != 99


def test_inputs_and_defaults_remain_unchanged_and_results_are_json_safe(rotation_input, event_input):
    frames, dates = rotation_input
    original_frames = {key: value.copy(deep=True) for key, value in frames.items()}
    original_event, original_schedule = deepcopy(event_input[0]), event_input[2].copy(deep=True)
    sectors, keywords = deepcopy(DEFAULT_SECTOR_MAP), deepcopy(DEFAULT_NEWS_TAGS)
    rotated, studied = rotation(frames, dates), study(event_input)
    for ticker, frame in frames.items():
        pd.testing.assert_frame_equal(frame, original_frames[ticker])
    assert event_input[0] == original_event
    pd.testing.assert_frame_equal(event_input[2], original_schedule)
    assert sectors == DEFAULT_SECTOR_MAP and keywords == DEFAULT_NEWS_TAGS
    json.dumps([rotated, studied, build_observation_hypotheses(rotated, studied)], allow_nan=False)


@pytest.mark.parametrize("window", [0, -1, 1.5, True])
def test_invalid_window_rejected(event_input, window):
    with pytest.raises(ValueError, match="positive integer"):
        study(event_input, window=window)


def test_naive_clock_rejected(event_input):
    with pytest.raises(ValueError, match="timezone-aware"):
        study(event_input, as_of="2025-04-10")
