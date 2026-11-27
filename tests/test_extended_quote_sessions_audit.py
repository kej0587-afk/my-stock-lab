"""SOXL/GOOGL synthetic response audit; display windows never change decision bars.

An intraday regularMarketTime cannot certify a closing reference, even when a
separate extended quote is fresh. These tests characterize that existing limit,
not a claim that an intraday quote should be promoted to a confirmed close.
"""

from copy import deepcopy
import json
import socket
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core import report_quotes as quotes
from stock_lab_core.report_session import market_session_states, us_extended_session


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    guards = []
    for target, name in ((socket, "getaddrinfo"), (socket.socket, "connect"),
                         (socket.socket, "connect_ex")):
        guard = Mock(side_effect=AssertionError("Unexpected network"))
        monkeypatch.setattr(target, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


@pytest.fixture(params=["SOXL", "GOOGL"])
def ticker(request):
    return request.param


def epoch(at):
    return int(pd.Timestamp(at).timestamp())


def raw_quote(ticker, close, field="pre", at="2026-11-27T08:29:00-05:00", price=101.):
    return {"symbol": ticker, "regularMarketTime": {"raw": epoch(close)},
            "regularMarketPrice": {"raw": 100.}, "regularMarketPreviousClose": {"raw": 110.},
            "regularMarketOpen": 109., "regularMarketDayHigh": 111.,
            "regularMarketDayLow": 98., "regularMarketVolume": 12345,
            field + "MarketTime": {"raw": epoch(at)}, field + "MarketPrice": {"raw": price}}


def page(*rows):
    body = json.dumps({"quoteResponse": {"result": rows}})
    return '<script type="application/json">' + json.dumps({"status": 200, "body": body}) + '</script>'


def parsed(row):
    # A neighboring symbol with newer quotes must never donate price or time.
    neighbor = dict(row, symbol="OTHER", preMarketPrice=999., preMarketTime=epoch("2026-12-01T08:00-05:00"))
    result = quotes.parse_us_quote_page(page(neighbor, row), row["symbol"])
    assert result == row
    return result


@pytest.mark.parametrize("now,close,field,phase,label,regular_ok", [
    ("2026-11-24T08:30-05:00", "2026-11-23T16:00-05:00", "pre", "preopen", "프리마켓", True),
    ("2026-11-24T10:00-05:00", "2026-11-24T09:59-05:00", "pre", "intraday", "", False),
    ("2026-11-24T17:00-05:00", "2026-11-24T16:00-05:00", "post", "closed", "애프터마켓", True),
    ("2026-11-26T08:30-05:00", "2026-11-25T16:00-05:00", "pre", "holiday", "", True),
    ("2026-11-27T08:30-05:00", "2026-11-25T16:00-05:00", "pre", "preopen", "프리마켓", True),
    ("2026-11-27T12:59-05:00", "2026-11-27T12:58-05:00", "post", "intraday", "", False),
    ("2026-11-27T13:20-05:00", "2026-11-27T13:00-05:00", "post", "closed", "애프터마켓", True),
    ("2026-11-27T16:20-05:00", "2026-11-27T13:00-05:00", "post", "closed", "애프터마켓", True),
    ("2026-11-28T08:30-05:00", "2026-11-27T13:00-05:00", "pre", "holiday", "", True),
    ("2026-11-30T08:30-05:00", "2026-11-27T13:00-05:00", "pre", "preopen", "프리마켓", True),
    ("2026-11-29T21:00-05:00", "2026-11-27T13:00-05:00", "overnight", "holiday", "데이마켓(야간)", True),
])
def test_raw_response_session_matrix(ticker, now, close, field, phase, label, regular_ok):
    clock = pd.Timestamp(now)
    row = parsed(raw_quote(ticker, close, field, clock - pd.Timedelta(minutes=1)))
    before = deepcopy(row)
    assert market_session_states(clock)["US"]["phase"] == phase
    regular = quotes.regular_quote_observation(row, ticker, clock)
    assert bool(regular) is regular_ok
    if regular:
        assert regular["price"] == 100. and regular["date"] == close[:10]
        assert regular["return"] == pytest.approx(100 / 110 - 1)
    extended = quotes.extended_quote_observation(row, ticker, clock)
    assert bool(extended) is bool(label)
    if extended:
        assert extended["kind"] == label
        assert extended["price"] == 101. and extended["previous_price"] == 100.
        assert extended["return"] == pytest.approx(.01)
        assert extended["regular_return"] == pytest.approx(100 / 110 - 1)
        assert extended["previous_date"] == close[:10]
        assert pd.Timestamp(extended["as_of"]) == clock - pd.Timedelta(minutes=1)
        assert quotes.extended_quote_status(row, ticker, clock) == "연결됨"
    assert row == before


@pytest.mark.parametrize("age,accepted", [(0, True), (1200, True), (1201, False)])
def test_same_price_new_trade_and_twenty_minute_freshness(ticker, age, accepted):
    now = pd.Timestamp("2026-11-27T08:30-05:00")
    row = parsed(raw_quote(ticker, "2026-11-25T16:00-05:00", at=now - pd.Timedelta(seconds=age), price=100.))
    current = quotes.extended_quote_observation(row, ticker, now)
    assert bool(current) is accepted  # unchanged price is still a valid new trade
    reference = quotes.extended_quote_observation(row, ticker, now, allow_delayed=True)
    assert reference["price"] == 100. and reference["return"] == 0.
    assert reference["delayed"] is (not accepted)
    assert reference["age_minutes"] == age / 60
    if not accepted:
        assert "시간외 시세 지연" in quotes.extended_quote_status(row, ticker, now)


@pytest.mark.parametrize("field,value,reason", [
    ("preMarketTime", None, "시간외 시각 미제공"),
    ("preMarketTime", {"raw": epoch("2026-11-27T08:31-05:00")}, "검증 실패"),
    ("preMarketPrice", None, "검증 실패"),
    ("preMarketPrice", 0, "검증 실패"),
    ("preMarketPrice", True, "검증 실패"),
])
def test_missing_future_or_invalid_quote_never_becomes_current(ticker, field, value, reason):
    now = pd.Timestamp("2026-11-27T08:30-05:00")
    row = raw_quote(ticker, "2026-11-25T16:00-05:00")
    row[field] = value
    row = parsed(row)
    assert not quotes.extended_quote_observation(row, ticker, now)
    assert not quotes.extended_quote_observation(row, ticker, now, allow_delayed=True)
    assert reason in quotes.extended_quote_status(row, ticker, now)


def test_unreceived_or_wrong_symbol_response_cannot_supply_quote(ticker):
    now = pd.Timestamp("2026-11-27T08:30-05:00")
    wrong = raw_quote("OTHER", "2026-11-25T16:00-05:00")
    assert quotes.parse_us_quote_page(page(wrong), ticker) == {}
    assert quotes.extended_quote_observation({}, ticker, now) == {}
    assert "미수집" in quotes.extended_quote_status({}, ticker, now)
    assert quotes.extended_quote_observation(wrong, ticker, now) == {}


def test_field_mismatch_and_prior_session_cannot_be_relabelled(ticker):
    now = pd.Timestamp("2026-11-27T08:30-05:00")
    wrong_field = parsed(raw_quote(ticker, "2026-11-25T16:00-05:00", field="post"))
    assert not quotes.extended_quote_observation(wrong_field, ticker, now, allow_delayed=True)
    assert "세션 불일치" in quotes.extended_quote_status(wrong_field, ticker, now)
    old = parsed(raw_quote(ticker, "2026-11-25T16:00-05:00", at="2026-11-25T08:29-05:00"))
    assert not quotes.extended_quote_observation(old, ticker, now, allow_delayed=True)


@pytest.mark.parametrize("now,close,field,intraday", [
    ("2026-11-27T08:30-05:00", "2026-11-25T16:00-05:00", "pre", "2026-11-25T14:30-05:00"),
    ("2026-11-24T17:00-05:00", "2026-11-24T16:00-05:00", "post", "2026-11-24T14:30-05:00"),
])
def test_intraday_regular_timestamp_blocks_fresh_extended_reference(ticker, now, close, field, intraday):
    clock = pd.Timestamp(now)
    good = parsed(raw_quote(ticker, close, field, clock - pd.Timedelta(minutes=1)))
    assert us_extended_session(clock)
    assert quotes.extended_quote_observation(good, ticker, clock)
    blocked = dict(good, regularMarketTime={"raw": epoch(intraday)})
    assert not quotes.regular_quote_observation(blocked, ticker, clock)
    assert not quotes.extended_quote_observation(blocked, ticker, clock)
    assert not quotes.extended_quote_observation(blocked, ticker, clock, allow_delayed=True)
    assert quotes.extended_quote_status(blocked, ticker, clock) == "비교 기준 정규장 종가·시각 검증 실패"


@pytest.mark.parametrize("clock,label", [("09:29:59", "프리마켓"), ("09:30:00", ""),
                                         ("15:59:59", ""), ("16:00:00", "애프터마켓")])
def test_regular_session_boundaries_are_half_open(clock, label):
    window = us_extended_session(pd.Timestamp("2026-11-24T" + clock + "-05:00"))
    assert window.get("label", "") == label


def test_extended_price_cannot_replace_decision_daily_close(ticker):
    now = pd.Timestamp("2026-11-27T08:30-05:00")
    row = parsed(raw_quote(ticker, "2026-11-25T16:00-05:00", price=130.))
    frame = pd.DataFrame({"Close": [110.]}, index=pd.to_datetime(["2026-11-24"]))
    before_frame, before_row = frame.copy(deep=True), deepcopy(row)
    repaired = quotes.repair_held_us_closes({ticker: frame}, {ticker: row}, now)
    assert repaired[ticker].loc["2026-11-25", "Close"] == 100.
    assert quotes.extended_quote_observation(row, ticker, now)["price"] == 130.
    existing = repaired[ticker].copy(deep=True)
    assert quotes.repair_held_us_closes({ticker: existing}, {ticker: row}, now)[ticker] is existing
    pd.testing.assert_frame_equal(frame, before_frame)
    assert row == before_row


@pytest.mark.parametrize("at,connected", [
    ("12:59:59", False), ("13:00:00", True), ("13:00:01", True),
    ("14:00:00", True), ("15:59:59", True), ("16:00:00", True),
    ("16:59:59", True), ("17:00:00", False), ("17:00:01", False),
    ("19:59:59", False), ("20:00:00", False), ("23:59:59", False),
])
def test_confirmed_20261127_window_boundaries_and_timezone_equivalence(at, connected):
    from stock_lab_core.report_session import display_market_status
    now = pd.Timestamp("2026-11-27T" + at + "-05:00")
    window = us_extended_session(now)
    assert bool(window) is connected
    assert us_extended_session(now.tz_convert("Asia/Seoul")) == window
    assert us_extended_session(now.tz_convert("UTC")) == window
    assert market_session_states(now)["US"]["phase"] == ("intraday" if at < "13:00:00" else "closed")
    if connected:
        assert window == {"label": "애프터마켓", "date": "2026-11-27",
                          "start": "2026-11-27T13:00:00-05:00", "end": "2026-11-27T17:00:00-05:00"}
        assert display_market_status(now, market="US") == "미국 애프터마켓 시간대"


@pytest.mark.parametrize("at", ["13:00:01", "15:00:00", "16:59:59"])
def test_confirmed_short_day_quotes_stay_separate_from_regular_close(ticker, at):
    now = pd.Timestamp("2026-11-27T" + at + "-05:00")
    row = parsed(raw_quote(ticker, "2026-11-27T13:00-05:00", "post", now, price=130.))
    original = deepcopy(row)
    regular = quotes.regular_quote_observation(row, ticker, now)
    observed = quotes.extended_quote_observation(row, ticker, now)
    assert regular["price"] == observed["previous_price"] == 100.
    assert observed["price"] == 130. and observed["return"] == pytest.approx(.3)
    assert observed["kind"] == "애프터마켓"
    frame = pd.DataFrame({"Close": [110.]}, index=pd.to_datetime(["2026-11-25"]))
    repaired = quotes.repair_held_us_closes({ticker: frame}, {ticker: row}, now)
    assert repaired[ticker].loc["2026-11-27", "Close"] == 100.
    assert row == original
    # Even a one-second-old trade stops being current/reference at the window end.
    end = pd.Timestamp("2026-11-27T17:00-05:00")
    row["postMarketTime"] = epoch(end - pd.Timedelta(seconds=1))
    assert not quotes.extended_quote_observation(row, ticker, end)
    assert not quotes.extended_quote_observation(row, ticker, end, allow_delayed=True)


@pytest.mark.parametrize("day", ["2026-12-24", "2027-11-26"])
@pytest.mark.parametrize("at", ["13:01", "16:01", "17:01"])
def test_unregistered_short_days_remain_unconfirmed(day, at):
    from stock_lab_core.report_exchange_clock import session_on_date
    now = pd.Timestamp(day + "T" + at + "-05:00")
    assert session_on_date("US", day)["close"].tz_convert("America/New_York").hour == 13
    assert us_extended_session(now) == {}


@pytest.mark.parametrize("session", [
    {"known": False}, {"known": True, "trading_day": False},
    {"known": True, "trading_day": True, "close": pd.Timestamp("2026-11-27T16:00-05:00")},
])
def test_confirmed_date_does_not_override_unknown_or_conflicting_regular_calendar(monkeypatch, session):
    from stock_lab_core import report_exchange_clock
    monkeypatch.setattr(report_exchange_clock, "session_on_date", lambda *args: session)
    assert us_extended_session(pd.Timestamp("2026-11-27T14:00-05:00")) == {}
