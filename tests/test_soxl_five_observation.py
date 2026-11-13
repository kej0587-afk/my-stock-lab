from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.soxl_five_observation import (
    budget_weight, build_five_observation, completed_five_grid,
)
from tests.test_soxl_short_observation import schedule, UI


def sample():
    sched = schedule(days=1)
    base = sched.market_open.iloc[0] + pd.Timedelta(hours=1)
    now = base + pd.Timedelta(minutes=17)
    frame = pd.DataFrame({"Open": [101., 99., 99.], "High": [102., 101., 102.],
                          "Low": [99., 98., 98.], "Close": [101., 99., 101.]},
                         index=pd.date_range(base, periods=3, freq="5min"))
    hourly = {"as_of": base, "expected_end": base, "plan": {"stop": 100.}}
    return sched, base, now, frame, hourly


def test_distinguishes_first_low_close_and_recovery_without_mutation():
    sched, base, now, frame, hourly = sample()
    original, before = frame.copy(deep=True), deepcopy(hourly)
    result = build_five_observation(frame, hourly, sched, now)
    assert result["first_low_end"] == base + pd.Timedelta(minutes=5)
    assert result["first_close_end"] == base + pd.Timedelta(minutes=10)
    assert "복귀" in result["status"] and result["bars"] == 3
    pd.testing.assert_frame_equal(frame, original)
    assert hourly == before
    assert not {"buy_amt", "allow_current", "decision"}.intersection(result)


@pytest.mark.parametrize("fault", ["empty", "gap", "leading_gap", "stale", "nan", "infinity", "bad_ohlc", "naive", "duplicate"])
def test_missing_or_corrupt_never_counts_as_recovery(fault):
    sched, _, now, frame, hourly = sample()
    if fault == "empty": frame = pd.DataFrame()
    if fault == "gap": frame = frame.drop(frame.index[1])
    if fault == "leading_gap": frame = frame.iloc[1:]
    if fault == "stale": frame = frame.iloc[:-1]
    if fault == "nan": frame.iloc[-1, 3] = np.nan
    if fault == "infinity": frame.iloc[-1, 3] = np.inf
    if fault == "bad_ohlc": frame.iloc[-1, 1] = 1
    if fault == "naive": frame.index = frame.index.tz_localize(None)
    if fault == "duplicate": frame = pd.concat([frame, frame.iloc[-1:]])
    result = build_five_observation(frame, hourly, sched, now)
    assert result["status"] == "미연결" and result["close"] is None


@pytest.mark.parametrize("fault", ["missing_plan", "stale_hour", "future", "invalid_stop"])
def test_requires_valid_hourly_reference(fault):
    sched, base, now, frame, hourly = sample()
    if fault == "missing_plan": hourly["plan"] = {}
    if fault == "stale_hour": hourly["expected_end"] = base + pd.Timedelta(hours=1)
    if fault == "future": hourly.update(as_of=now + pd.Timedelta(hours=1), expected_end=now + pd.Timedelta(hours=1))
    if fault == "invalid_stop": hourly["plan"]["stop"] = np.nan
    assert build_five_observation(frame, hourly, sched, now)["status"] == "미연결"


def test_no_back_projection_or_incomplete_or_extended_hours():
    sched, base, now, frame, hourly = sample()
    baseline = build_five_observation(frame, hourly, sched, now)
    extra = frame.iloc[:1].copy() * .1
    extras = []
    for stamp in (base - pd.Timedelta(minutes=5), base + pd.Timedelta(minutes=15), sched.market_close.iloc[0]):
        item = extra.copy()
        item.index = pd.DatetimeIndex([stamp])
        extras.append(item)
    result = build_five_observation(pd.concat([frame, *extras]), hourly, sched, now)
    assert result == baseline
    assert build_five_observation(frame, hourly, sched, base)["status"] == "관찰 대기"


def test_new_session_needs_new_hour_reference():
    sched, _, _, frame, hourly = sample()
    sched = schedule(days=2)
    now = sched.market_open.iloc[-1] + pd.Timedelta(minutes=10)
    result = build_five_observation(frame, hourly, sched, now)
    assert result["status"] == "미연결" and "다른 거래일" in result["issue"]


def test_low_only_close_breach_and_equal_not_breach():
    sched, _, now, frame, hourly = sample()
    frame.Close = 100.
    assert "저가 이탈만" in build_five_observation(frame, hourly, sched, now)["status"]
    frame.Low = 100.
    frame.Open = 100.
    assert build_five_observation(frame, hourly, sched, now)["status"] == "조회 구간 이탈 미관찰"
    frame.iloc[-1, 2:] = [98., 99.]
    assert build_five_observation(frame, hourly, sched, now)["status"] == "5분 종가 이탈 관찰"


def test_regular_calendar_and_early_close():
    sched = schedule(days=1, early=True)
    grid = completed_five_grid(sched, sched.market_close.iloc[0] + pd.Timedelta(hours=4))
    assert len(grid) == 42 and grid[-1] + pd.Timedelta(minutes=5) == sched.market_close.iloc[0]
    with pytest.raises(ValueError): completed_five_grid(sched, "2026-11-02")


@pytest.mark.parametrize("budget,loss,expected", [(.25, 10, 2.5), (.5, 20, 2.5), (1, 15, 100/15),
                                               (0, 10, 0), (2, 1, 100)])
def test_budget_formula(budget, loss, expected):
    assert budget_weight(budget, loss) == pytest.approx(expected)


@pytest.mark.parametrize("budget,loss", [(np.nan, 10), (.5, 0), (.5, -1), (-1, 10), (101, 10),
                                       (.5, 101), (None, 10), (.5, np.inf)])
def test_invalid_budget_or_loss_not_zero(budget, loss):
    assert budget_weight(budget, loss) is None


def test_loader_only_soxx_regular_five_and_explicit_failure(monkeypatch):
    import yfinance
    from stock_lab_core.soxl_short_data import load_short_five
    _, _, _, frame, _ = sample()
    def download(tickers, **kwargs):
        assert tickers == ["SOXX"] and kwargs["interval"] == "5m"
        assert kwargs["period"] == "5d" and kwargs["auto_adjust"] and not kwargs["prepost"]
        assert kwargs["timeout"] == 6 and not kwargs["threads"]
        return pd.concat({"SOXX": frame}, axis=1)
    monkeypatch.setattr(yfinance, "download", download)
    assert load_short_five.__wrapped__()["ok"]
    def fail(*args, **kwargs): raise TimeoutError()
    monkeypatch.setattr(yfinance, "download", fail)
    result = load_short_five.__wrapped__()
    assert not result["ok"] and result["frame"].empty and "TimeoutError" in result["issue"]


def test_view_missing_does_not_display_zero_or_approval():
    from stock_lab_core.soxl_five_view import render_five_observation, render_budget_table
    from stock_lab_core.soxl_short_view import _time
    sched, _, now, _, hourly = sample()
    ui = UI()
    render_five_observation(ui, {}, hourly, sched, now, _time)
    assert "미연결" in " ".join(ui.text) and not ui.tables
    render_budget_table(ui)
    assert len(ui.tables[-1]) == 4 and "2.50%" in ui.tables[-1][1].values()
