"""2026-11-27: 240/1000 trading-day lines on 일/주/월봉, checked against the raw daily closes."""

import numpy as np
import pandas as pd

from stock_lab_core import intraday_chart as ic
from stock_lab_core.intraday_chart_view import BASIS_BAR, BASIS_DAILY, daily_basis_view


def daily(n=1300, end="2026-11-25"):
    idx = pd.bdate_range(end=end, periods=n)
    close = pd.Series(np.linspace(10, 60, n) + np.sin(np.arange(n) / 7.0), index=idx)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000.0})


def weekly(frame):
    return frame.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})


def monthly(frame):
    return frame.resample(pd.offsets.MonthEnd()).agg({"Open": "first", "High": "max", "Low": "min",
                                                     "Close": "last", "Volume": "sum"})


def test_weekly_and_monthly_lines_equal_the_daily_sma_at_each_bar_end():
    d = daily()
    for frame, label in ((weekly(d), "주봉"), (monthly(d), "월봉")):
        lines, status = ic.daily_basis_lines(d, frame, [240, 1000], label=label)
        for period in (240, 1000):
            assert status[period]["ok"]
            # last bar: the in-progress week/month uses the latest daily close (2026-11-25)
            assert status[period]["last_date"] == "2026-11-25"
            assert np.isclose(lines[period].iloc[-1], d["Close"].tail(period).mean())
            assert np.isclose(status[period]["last_value"], d["Close"].tail(period).mean())
            # a completed earlier bar: SMA through the last trading day on/before its label date
            label_date = frame.index[-5]
            through = d["Close"][d.index <= label_date]
            assert np.isclose(lines[period].iloc[-5], through.tail(period).mean())


def test_daily_chart_line_uses_long_history_even_when_the_chart_frame_is_one_year():
    d = daily()
    chart = d.tail(250).copy()
    chart.iloc[-1, chart.columns.get_loc("Close")] = 99.0  # live-applied last bar is kept
    lines, status = ic.daily_basis_lines(d, chart, [1000], label="일봉")
    expected = pd.concat([d["Close"].iloc[:-1], pd.Series([99.0], index=d.index[-1:])]).tail(1000).mean()
    assert status[1000]["ok"] and lines[1000].notna().all()
    assert np.isclose(lines[1000].iloc[-1], expected)


def test_shortage_reports_have_and_need_in_trading_days():
    d = daily(n=600)
    lines, status = ic.daily_basis_lines(d, weekly(d), [240, 1000], label="주봉")
    assert 240 in lines and 1000 not in lines
    assert status[1000] == {"ok": False, "have": 600, "need": 1000}
    _, _, notes = daily_basis_view(d, weekly(d), "주봉", [1000], BASIS_DAILY)
    assert notes == ["일봉 1000일선: 계산 불가 (확보 600거래일 < 필요 1,000거래일)"]


def test_bar_unit_mode_names_its_unit():
    d = daily()
    ma, overlay, notes = daily_basis_view(d, weekly(d), "주봉", [20, 1000], BASIS_BAR)
    assert set(ma) == {"20주선"} and overlay == {}
    assert notes and notes[0].startswith("1000주선: 계산 불가")
    ma, overlay, _ = daily_basis_view(d, monthly(d), "월봉", [20], BASIS_BAR)
    assert set(ma) == {"20개월선"}


def test_daily_label_names_lines_in_days():
    d = daily()
    ma, overlay, notes = daily_basis_view(d, d.tail(250), "일봉", [240, 1000], BASIS_DAILY)
    assert set(ma) == {"240일선", "1000일선"} and overlay == {}
    assert notes[0].startswith("240일선 마지막 값")
