"""Report fallback close boundaries; public calendars and synthetic prices only."""

from copy import deepcopy
from unittest.mock import Mock
import socket

import pandas as pd
import pytest

from stock_lab_core import report_exchange_clock
from stock_lab_core.report_quotes import (
    extended_quote_observation, regular_quote_observation, repair_held_us_closes,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    guards = []
    for target, name in ((socket, "getaddrinfo"), (socket.socket, "connect"),
                         (socket.socket, "connect_ex")):
        guard = Mock(side_effect=AssertionError("Unexpected network request"))
        monkeypatch.setattr(target, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


def quote(at):
    return {"symbol": "SOXL", "regularMarketTime": pd.Timestamp(at).timestamp(),
            "regularMarketPrice": 90., "regularMarketPreviousClose": 100.,
            "regularMarketChange": -10., "regularMarketChangePercent": -10.,
            "regularMarketOpen": 95.,
            "regularMarketDayHigh": 98., "regularMarketDayLow": 89.,
            "regularMarketVolume": 1000000}


@pytest.mark.parametrize("closing,previous", [
    ("2026-10-16T16:00:00-04:00", "2026-10-15"),
    ("2026-11-20T16:00:00-05:00", "2026-11-19"),
    ("2026-11-27T13:00:00-05:00", "2026-11-25"),
])
@pytest.mark.parametrize("quote_seconds,now_seconds,accepted", [
    (-60, -1, False),       # market still trading
    (4, 0, False),         # future quote
    (4, 4, True),          # at/after actual close during grace
    (-1, 899, False),      # pre-close quote during grace
    (-60, 900, True),      # last-minute trade after grace expires
    (-61, 1200, False),    # too early
    (959, 1200, True),     # preserve minute precision at close+15:59
    (960, 1200, False),    # outside the regular-close quote window
    (4, 1200, True),
])
def test_actual_close_window_and_unchanged_normal_session(closing, previous, quote_seconds, now_seconds, accepted):
    close = pd.Timestamp(closing)
    row = quote(close + pd.Timedelta(seconds=quote_seconds))
    before = deepcopy(row)
    observed = regular_quote_observation(row, "SOXL", close + pd.Timedelta(seconds=now_seconds))
    assert bool(observed) is accepted
    if accepted:
        assert observed["date"] == close.date().isoformat()
        assert observed["previous_date"] == previous
        assert observed["price"] == 90. and observed["previous_price"] == 100.
        assert observed["return"] == pytest.approx(-.1)
    assert row == before


@pytest.mark.parametrize("now,at,previous", [
    ("2026-11-26T12:00-05:00", "2026-11-25T16:00-05:00", "2026-11-24"),
    ("2026-11-27T12:59-05:00", "2026-11-25T16:00-05:00", "2026-11-24"),
    ("2026-11-28T12:00-05:00", "2026-11-27T13:00-05:00", "2026-11-25"),
    ("2026-11-30T09:00-05:00", "2026-11-27T13:00-05:00", "2026-11-25"),
    ("2026-11-30T15:59-05:00", "2026-11-27T13:00-05:00", "2026-11-25"),
    ("2027-01-01T12:00-05:00", "2026-12-31T16:00-05:00", "2026-12-30"),
])
def test_previous_session_respects_holiday_weekend_and_year_boundary(now, at, previous):
    result = regular_quote_observation(quote(at), "SOXL", now)
    assert result["date"] == at[:10]
    assert result["previous_date"] == previous


@pytest.mark.parametrize("at", ["2026-11-27T16:00-05:00", "2026-11-25T16:00-05:00"])
def test_short_session_rejects_old_fixed_close_and_stale_day(at):
    assert not regular_quote_observation(quote(at), "SOXL", "2026-11-27T16:20-05:00")


@pytest.mark.parametrize("now", [None, "not a date", pd.NaT, "2026-11-27T13:20"])
def test_unverified_clock_cannot_certify_close(now):
    assert not regular_quote_observation(quote("2026-11-27T13:00-05:00"), "SOXL", now)


@pytest.mark.parametrize("unknown_day", ["2026-11-27", "2026-11-26", "2026-11-25"])
def test_unknown_calendar_does_not_guess_a_previous_session(monkeypatch, unknown_day):
    real_session = report_exchange_clock.session_on_date
    monkeypatch.setattr(report_exchange_clock, "session_on_date", lambda market, day:
        {"known": False} if str(day) == unknown_day else real_session(market, day))
    assert not regular_quote_observation(quote("2026-11-27T13:00-05:00"), "SOXL", "2026-11-27T13:20-05:00")


def test_calendar_with_no_sessions_is_bounded(monkeypatch):
    session = Mock(return_value={"known": True, "trading_day": False})
    monkeypatch.setattr(report_exchange_clock, "session_on_date", session)
    assert not regular_quote_observation(quote("2026-11-27T13:00-05:00"), "SOXL", "2026-11-27T13:20-05:00")
    assert session.call_count <= 32


@pytest.mark.parametrize("existing,prior,expected", [
    (None, 100., 90.),        # recover missing close after Thanksgiving
    (88., 100., 88.),        # never overwrite an existing valid daily close
    (None, 50., 50.),        # incompatible split/adjustment basis: do not splice
])
def test_repair_uses_short_session_and_preserves_input(existing, prior, expected):
    frame = pd.DataFrame({"Close": [prior]}, index=pd.to_datetime(["2026-11-25"]))
    if existing is not None:
        frame.loc[pd.Timestamp("2026-11-27"), "Close"] = existing
    original = frame.copy(deep=True)
    row = quote("2026-11-27T13:00:04-05:00")
    quotes = {"SOXL": row}
    before = deepcopy(quotes)
    result = repair_held_us_closes({"SOXL": frame}, quotes, "2026-11-27T13:20-05:00")
    assert result["SOXL"].Close.iloc[-1] == expected
    pd.testing.assert_frame_equal(frame, original)
    assert quotes == before
    if existing is None and prior == 100.:
        assert result["SOXL"].index[-1] == pd.Timestamp("2026-11-27")
        assert result["SOXL"].attrs["quote_as_of"] == "2026-11-27T18:00:04+00:00"


def test_confirmed_short_close_connects_separate_extended_quote():
    row = dict(quote("2026-11-27T13:00:04-05:00"), postMarketPrice=95.,
               postMarketTime=pd.Timestamp("2026-11-27T13:19-05:00").timestamp())
    assert regular_quote_observation(row, "SOXL", "2026-11-27T13:20-05:00")
    observed = extended_quote_observation(row, "SOXL", pd.Timestamp("2026-11-27T13:20-05:00"))
    assert observed["kind"] == "애프터마켓"
    assert observed["price"] == 95. and observed["previous_price"] == 90.
    assert observed["regular_date"] == "2026-11-27"
