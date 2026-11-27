"""Offline exchange-calendar boundaries for report consumers, not trade routing."""

from copy import deepcopy
import socket
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core import report_eventstudy, report_exchange_clock as clock
from stock_lab_core.market_board import completed_close_series
from stock_lab_core.report_evidence import closed_daily_frame
from stock_lab_core.report_session import market_session_states, report_mode, us_extended_session


SESSIONS = [
    pytest.param("KR", "379810.KS", "2026-11-20", "2026-11-19",
                 "2026-11-20T00:00Z", "2026-11-20T06:30Z", id="kr-normal"),
    pytest.param("KR", "379810.KS", "2026-11-19", "2026-11-18",
                 "2026-11-19T01:00Z", "2026-11-19T07:30Z", id="kr-special"),
    pytest.param("US", "GOOGL", "2026-10-16", "2026-10-15",
                 "2026-10-16T13:30Z", "2026-10-16T20:00Z", id="us-summer"),
    pytest.param("US", "GOOGL", "2026-11-20", "2026-11-19",
                 "2026-11-20T14:30Z", "2026-11-20T21:00Z", id="us-winter"),
    pytest.param("US", "GOOGL", "2026-11-27", "2026-11-25",
                 "2026-11-27T14:30Z", "2026-11-27T18:00Z", id="us-early-close"),
]


@pytest.fixture(autouse=True)
def offline_and_isolated_clock_cache(monkeypatch):
    # Hold the original cached callable: failure tests replace the module attribute.
    # Do not clear/mutate the existing event-study calendar cache owned elsewhere.
    cached_schedule = clock._year_schedule
    cached_schedule.cache_clear()
    guards = []
    for target, name in ((socket, "getaddrinfo"), (socket.socket, "connect"),
                         (socket.socket, "connect_ex")):
        guard = Mock(side_effect=AssertionError("Unexpected calendar network request"))
        monkeypatch.setattr(target, name, guard)
        guards.append(guard)
    yield
    cached_schedule.cache_clear()
    for guard in guards:
        guard.assert_not_called()


def history(*days):
    frame = pd.DataFrame({"Close": [100. + 10 * i for i in range(len(days))]},
                         index=pd.to_datetime(list(days)))
    frame.attrs = {"source": "synthetic", "audit": {"keep": ["original"]}}
    return frame


@pytest.mark.parametrize("market,ticker,day,previous,opening,closing", SESSIONS)
def test_real_schedule_exact_open_close_and_consistent_state(market, ticker, day, previous, opening, closing):
    opening, closing = pd.Timestamp(opening), pd.Timestamp(closing)
    session = clock.session_on_date(market, day)
    assert session["known"] is True and session["trading_day"] is True
    assert (session["open"], session["close"]) == (opening, closing)
    assert "exchange_calendars" in session["source"]
    for now, phase in ((opening - pd.Timedelta(seconds=1), "preopen"),
                       (opening, "intraday"), (closing - pd.Timedelta(seconds=1), "intraday"),
                       (closing, "closed")):
        reference = clock.exchange_clock(market, now)
        assert (reference["known"], reference["phase"], reference["local_date"]) == (True, phase, day)
        states = market_session_states(now.to_pydatetime(), {market: previous})
        assert states[market]["phase"] == phase
        assert states[market]["active_date"] == (day if phase == "intraday" else "")
        assert states[market]["last_close"] == previous
        if market == "KR":
            assert report_mode(now.to_pydatetime()) == phase


@pytest.mark.parametrize("market,day,previous,now", [
    ("KR", "2026-10-09", "2026-10-08", "2026-10-09T16:00+09:00"),
    ("US", "2026-11-26", "2026-11-25", "2026-11-26T17:00-05:00"),
    ("KR", "2026-11-21", "2026-11-20", "2026-11-21T16:00+09:00"),
    ("US", "2026-11-28", "2026-11-27", "2026-11-28T17:00-05:00"),
])
def test_holidays_and_weekends_are_known_but_never_daily_bars(market, day, previous, now):
    now = pd.Timestamp(now)
    reference = clock.exchange_clock(market, now)
    assert (reference["known"], reference["trading_day"], reference["phase"]) == (True, False, "holiday")
    dates = pd.to_datetime([previous, day])
    for current in (False, True):
        assert clock.eligible_daily_dates(dates, market, now, include_current=current).tolist() == [True, False]
    states = market_session_states(now.to_pydatetime())
    assert states[market]["active_date"] == ""
    if market == "KR":
        assert report_mode(now.to_pydatetime(), is_trading_day=True) == "holiday"


@pytest.mark.parametrize("market,ticker,day,previous,opening,closing", SESSIONS)
def test_consumers_preserve_different_buffers_at_actual_close(market, ticker, day, previous, opening, closing):
    frame = history(previous, day)
    closing = pd.Timestamp(closing)
    for seconds in (-1, 0, 899, 900):
        now = closing + pd.Timedelta(seconds=seconds)
        report = closed_daily_frame(frame, ticker, now)
        board, removed = completed_close_series(frame, market, now=now)
        report_includes = seconds >= (0 if market == "KR" else 900)
        board_includes = seconds >= 900
        assert report.index.strftime("%Y-%m-%d").tolist() == ([previous, day] if report_includes else [previous])
        assert board.index.strftime("%Y-%m-%d").tolist() == ([previous, day] if board_includes else [previous])
        assert removed == (0 if board_includes else 1)
        assert report.Close.iloc[-1] == (110. if report_includes else 100.)
        assert board.iloc[-1] == (110. if board_includes else 100.)


@pytest.mark.parametrize("market,previous,day,future,opening", [
    ("KR", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-19T01:00Z"),
    ("US", "2026-11-25", "2026-11-27", "2026-11-30", "2026-11-27T14:30Z"),
])
def test_current_bar_requires_actual_open_and_excludes_future(market, previous, day, future, opening):
    frame = history(previous, day, future)
    opening = pd.Timestamp(opening)
    for now, expected in ((opening - pd.Timedelta(seconds=1), [True, False, False]),
                          (opening, [True, True, False])):
        assert clock.eligible_daily_dates(frame.index, market, now, close_delay_minutes=15,
                                         include_current=True).tolist() == expected
        current, removed = completed_close_series(frame, market, now=now, include_current=True)
        assert current.index.tolist() == frame.index[expected].tolist()
        assert removed == expected.count(False)
    assert clock.eligible_daily_dates(frame.index, market, opening).tolist() == [True, False, False]


@pytest.mark.parametrize("helper", ["exchange_clock", "eligible_daily_dates"])
def test_shared_helpers_reject_naive_now_instead_of_guessing(helper):
    now = pd.Timestamp("2026-11-19T16:00")
    with pytest.raises(ValueError, match="requires timezone"):
        if helper == "exchange_clock":
            clock.exchange_clock("KR", now)
        else:
            clock.eligible_daily_dates(pd.to_datetime(["2026-11-19"]), "KR", now)


def test_consumers_keep_their_explicit_naive_clock_policies():
    naive = pd.Timestamp("2026-11-19T16:00").to_pydatetime()
    kst = pd.Timestamp("2026-11-19T16:00+09:00").to_pydatetime()
    utc = pd.Timestamp("2026-11-19T16:00Z").to_pydatetime()
    frame = history("2026-11-18", "2026-11-19")
    report = closed_daily_frame(frame, "379810.KS", naive)
    pd.testing.assert_frame_equal(report, closed_daily_frame(frame, "379810.KS", kst))
    assert report.index.strftime("%Y-%m-%d").tolist() == ["2026-11-18"]
    assert market_session_states(naive) == market_session_states(kst)
    assert report_mode(naive) == "intraday"
    assert report_mode(naive, is_trading_day=False) == "holiday"
    board, _ = completed_close_series(frame, "KR", now=naive)
    aware_board, _ = completed_close_series(frame, "KR", now=utc)
    pd.testing.assert_series_equal(board, aware_board)
    assert board.index.strftime("%Y-%m-%d").tolist() == ["2026-11-18", "2026-11-19"]


def test_daily_labels_do_not_shift_to_previous_holiday_with_timezone():
    # UTC conversion would incorrectly turn the Nov27 label into Thanksgiving.
    dates = pd.DatetimeIndex(["2026-11-25T00:00+09:00", "2026-11-27T00:00+09:00"])
    original = dates.copy()
    now = pd.Timestamp("2026-11-27T18:15Z")
    assert clock.eligible_daily_dates(dates, "US", now, close_delay_minutes=15).tolist() == [True, True]
    pd.testing.assert_index_equal(dates, original)
    frame = pd.DataFrame({"Close": [100., 110.]}, index=dates)
    assert closed_daily_frame(frame, "GOOGL", now).index.equals(dates)
    board, _ = completed_close_series(frame, "US", now=now)
    assert board.index.strftime("%Y-%m-%d").tolist() == ["2026-11-25", "2026-11-27"]


def test_all_history_holidays_and_nat_filtered_without_mutating_source_or_schedule():
    frame = history("2026-10-08", "2026-10-09", "2026-11-19", "2026-11-20")
    frame.attrs["report_close_pending_date"] = "2026-11-20"
    original = deepcopy(frame)
    schedule = clock._year_schedule("KR", 2026)
    saved_schedule = deepcopy(schedule)
    now = pd.Timestamp("2026-11-20T07:00Z")
    dates = frame.index.append(pd.DatetimeIndex([pd.NaT]))
    assert clock.eligible_daily_dates(dates, "KR", now).tolist() == [True, False, True, True, False]
    report = closed_daily_frame(frame, "379810.KS", now)
    assert report.index.strftime("%Y-%m-%d").tolist() == ["2026-10-08", "2026-11-19"]
    board, removed = completed_close_series(frame, "KR", now=now)
    assert board.tolist() == [100., 120., 130.] and removed == 1
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert frame.attrs == original.attrs
    pd.testing.assert_frame_equal(schedule, saved_schedule, check_exact=True)
    assert schedule.attrs == saved_schedule.attrs


@pytest.mark.parametrize("failure", ["unavailable", "invalid", "empty"])
def test_calendar_failure_stays_unknown_and_all_consumers_withhold_closes(monkeypatch, failure):
    def unavailable(_market, _year):
        if failure == "empty":
            raise ValueError("Invalid exchange schedule: empty")
        if failure == "invalid":
            raise ValueError("Invalid exchange schedule")
        raise OSError("calendar unavailable")

    monkeypatch.setattr(clock, "_year_schedule", unavailable)
    now = pd.Timestamp("2026-11-20T22:00Z")
    frame = history("2026-11-19", "2026-11-20")
    for market, ticker in (("KR", "379810.KS"), ("US", "GOOGL")):
        reference = clock.exchange_clock(market, now)
        assert (reference["known"], reference["trading_day"], reference["phase"]) == (False, None, "unknown")
        for current in (False, True):
            assert not clock.eligible_daily_dates(frame.index, market, now, include_current=current).any()
        assert closed_daily_frame(frame, ticker, now).empty
        series, removed = completed_close_series(frame, market, now=now)
        assert series.empty and removed == 2
    states = market_session_states(now.to_pydatetime())
    assert all(state["phase"] == "unknown" and state["active_date"] == "" for state in states.values())
    assert report_mode(now.to_pydatetime()) == "unknown"
    assert us_extended_session(now.to_pydatetime()) == {}


def test_one_missing_year_withholds_whole_history_instead_of_partial_daily_return(monkeypatch):
    real_schedule = clock._year_schedule

    def partial_schedule(market, year):
        if year == 2026:
            raise OSError("missing current year")
        return real_schedule(market, year)

    monkeypatch.setattr(clock, "_year_schedule", partial_schedule)
    frame = history("2025-12-30", "2025-12-31", "2026-01-02")
    now = pd.Timestamp("2026-01-02T22:00Z")
    assert clock.eligible_daily_dates(frame.index, "US", now).tolist() == [False, False, False]
    assert closed_daily_frame(frame, "GOOGL", now).empty
    board, removed = completed_close_series(frame, "US", now=now)
    assert board.empty and removed == 3


def test_year_cache_reused_across_seconds_consumers_and_tickers(monkeypatch):
    loader = Mock(wraps=report_eventstudy._exchange_schedule)
    monkeypatch.setattr(report_eventstudy, "_exchange_schedule", loader)
    frame = history("2026-11-19", "2026-11-20")
    for second in (0, 1, 59):
        now = pd.Timestamp("2026-11-20T22:00Z") + pd.Timedelta(seconds=second)
        market_session_states(now.to_pydatetime())
        for market, ticker in (("KR", "379810.KS"), ("KR", "005930.KS"), ("US", "GOOGL")):
            closed_daily_frame(frame, ticker, now)
            completed_close_series(frame, market, now=now)
    assert loader.call_count == 2
    assert {call.args for call in loader.call_args_list} == {
        ("KR", "2026-01-01", "2026-12-31"), ("US", "2026-01-01", "2026-12-31")}
    clock.session_on_date("US", "2025-12-31")
    clock.session_on_date("US", "2025-12-30")
    assert loader.call_count == 3


@pytest.mark.parametrize("now,end", [
    ("2026-11-20T17:00-05:00", "2026-11-20T20:00:00-05:00"),
    ("2026-11-27T13:01-05:00", "2026-11-27T17:00:00-05:00"),
    ("2026-11-27T16:01-05:00", "2026-11-27T17:00:00-05:00"),
    ("2026-11-27T17:00-05:00", ""),
])
def test_confirmed_short_day_extended_window_keeps_regular_state_closed(now, end):
    now = pd.Timestamp(now).to_pydatetime()
    assert market_session_states(now)["US"]["phase"] == "closed"
    window = us_extended_session(now)
    if end:
        assert window["label"] == "애프터마켓"
        assert window["end"] == end
    else:
        assert window == {}


def test_overnight_uses_target_session_date_and_holiday_does_not_get_a_window():
    sunday = pd.Timestamp("2026-11-22T21:00-05:00").to_pydatetime()
    assert market_session_states(sunday)["US"]["phase"] == "holiday"
    window = us_extended_session(sunday)
    assert window["date"] == "2026-11-23"
    assert window["start"] == "2026-11-22T20:00:00-05:00"
    assert window["end"] == "2026-11-23T04:00:00-05:00"
    before_holiday = pd.Timestamp("2026-11-25T21:00-05:00").to_pydatetime()
    assert us_extended_session(before_holiday) == {}


def test_empty_and_future_only_dates_do_not_load_calendar(monkeypatch):
    loader = Mock(side_effect=AssertionError("no eligible year to load"))
    monkeypatch.setattr(clock, "_year_schedule", loader)
    now = pd.Timestamp("2026-11-20T22:00Z")
    for dates in (pd.DatetimeIndex([]), pd.to_datetime(["2027-01-04", None])):
        mask = clock.eligible_daily_dates(dates, "US", now)
        assert len(mask) == len(dates) and mask.dtype == bool and not mask.any()
    loader.assert_not_called()


@pytest.mark.parametrize("at,count", [
    ("2026-11-26T14:00-05:00", 2),
    ("2026-11-26T16:15-05:00", 3),
    ("2026-11-27T13:15-05:00", 3),
    ("2026-11-27T16:14:59-05:00", 3),
    ("2026-11-27T16:15-05:00", 4),
])
def test_non_equity_report_and_energy_keep_old_dates_on_holiday_and_early_close(at, count, monkeypatch):
    from stock_lab_core.report_energy_basis import energy_daily_observations

    # Synthetic supplied bars, not a claim about any futures venue's actual hours.
    frame = history("2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27", "2026-11-30")
    original = deepcopy(frame)
    now = pd.Timestamp(at)
    tickers = ("CL=F", "BZ=F", "NG=F", "USDKRW=X", "KRW=X", "DX-Y.NYB",
               "^TNX", "^TYX", "^IRX", "^FVX", "^MOVE")
    calendar = Mock(side_effect=AssertionError("macro dates must not use equity calendar"))
    monkeypatch.setattr(clock, "_year_schedule", calendar)
    for ticker in tickers:
        actual = closed_daily_frame(frame, ticker, now)
        pd.testing.assert_frame_equal(actual, frame.iloc[:count])
    energy = energy_daily_observations({ticker: frame for ticker in tickers}, now)
    for ticker in ("CL=F", "BZ=F", "NG=F", "^TYX", "DX-Y.NYB"):
        row = energy[ticker]
        assert row["date"] == str(frame.index[count - 1].date())
        assert row["previous_date"] == str(frame.index[count - 2].date())
        assert row["price"] == frame.Close.iloc[count - 1]
        assert row["return"] == pytest.approx(frame.Close.iloc[count - 1] / frame.Close.iloc[count - 2] - 1)
    assert energy["CL=F"]["basis"] == "공급처 일봉 · 공식 정산가 아님"
    calendar.assert_not_called()
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert frame.attrs == original.attrs


@pytest.mark.parametrize("at,active", [
    ("2026-11-26T14:00-05:00", False),
    ("2026-11-27T14:00-05:00", True),
])
def test_futures_fx_intraday_keeps_old_window_and_supplied_holiday_comparison(at, active):
    from stock_lab_core.report_evidence import intraday_observation

    frame = history("2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27")
    original = deepcopy(frame)
    now = pd.Timestamp(at)
    for ticker in ("CL=F", "USDKRW=X"):
        row = intraday_observation(frame, ticker, now)
        if active:
            assert (row["date"], row["price"]) == ("2026-11-27", 130.)
            assert row["return"] == pytest.approx(130 / 120 - 1)
            assert row["kind"] == "장중 진행·확정 아님"
        else:
            assert row == {}
    # The equity path is closed/holiday at both instants; do not revert its fix.
    assert intraday_observation(frame, "GOOGL", now) == {}
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


@pytest.mark.parametrize("at,raw_count,guarded_count,expected_date", [
    ("2026-11-26T17:00-05:00", 3, 2, "2026-11-25"),
    ("2026-11-27T13:15-05:00", 3, 3, "2026-11-27"),
    ("2026-11-27T16:15-05:00", 4, 4, "2026-11-27"),
])
def test_macro_mixed_feed_keeps_legacy_filter_then_its_existing_expected_guard(at, raw_count, guarded_count, expected_date):
    from stock_lab_core.macro_monitor import completed_price_history

    frame = history("2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27", "2026-11-30")
    original = deepcopy(frame)
    now = pd.Timestamp(at)
    raw, removed = completed_close_series(frame, "US", now=now, use_exchange_calendar=False)
    assert raw.index.tolist() == frame.index[:raw_count].tolist()
    assert removed == len(frame) - raw_count
    actual = completed_price_history(frame, "US", now)
    assert actual.index.tolist() == frame.index[:guarded_count].tolist()
    assert actual.tolist() == frame.Close.iloc[:guarded_count].tolist()
    assert actual.attrs["expected_date"] == expected_date
    # At 13:15 the expected equity date advances, but the mixed feed still waits
    # for its old 16:15 cutoff. A stale last date must not be relabelled as current.
    if at == "2026-11-27T13:15-05:00":
        assert str(actual.index[-1].date()) == "2026-11-26"
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert frame.attrs == original.attrs
