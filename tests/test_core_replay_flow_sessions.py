"""Research-only session alignment, no live requests or private inputs."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sim_core_first_buy as research


def fixture():
    days = pd.bdate_range("2019-01-02", periods=150)
    base = pd.DataFrame({"Close": np.full(len(days), 100.)}, index=days)
    us = base.copy()
    us.iloc[-1, 0] = 200.
    flow = {"069500.KS": base, "QQQ": us}
    benchmark = base.copy()
    benchmark.iloc[-20:, 0] = np.linspace(99.8, 95., 20)
    bench = {t: benchmark.copy() for t, _ in research.BENCH}
    return days, flow, bench


def legacy_flow(flow, days):
    r3, acc = {}, {}
    for ticker, frame in flow.items():
        close = frame.Close
        current = close / close.shift(63) - 1
        prior = close.shift(63) / close.shift(126) - 1
        r3[ticker] = current.reindex(days, method="ffill")
        acc[ticker] = (current-prior).reindex(days, method="ffill")
    r3, acc = pd.DataFrame(r3), pd.DataFrame(acc)
    breadth = r3.gt(0).where(r3.notna()).mean(axis=1)
    accel = acc.gt(0).where(acc.notna()).mean(axis=1)
    score = np.where(breadth < .35, 2, np.where(breadth < .50, 1, 0)) + np.where(accel < .35, 1, 0)
    return pd.DataFrame({"breadth":breadth, "accel":accel, "flow":score}, index=days)


def test_kr_gate_ignores_us_same_day_shock():
    days, flow, bench = fixture()
    before = research.replay_gate(bench, flow, "KR")
    altered = {k:v.copy() for k,v in flow.items()}
    altered["QQQ"].iloc[-1, 0] = 1.
    after = research.replay_gate(bench, altered, "KR")
    pd.testing.assert_frame_equal(before, after)
    assert before.iloc[-1]["flow"] == 3
    assert before.iloc[-1]["whole"] == 9
    assert bool(before.iloc[-1]["closed_KR"])


def test_us_replay_keeps_all_legacy_values(monkeypatch):
    days, flow, bench = fixture()
    current = research.replay_gate(bench, flow, "US")
    monkeypatch.setattr(research, "flow_score_series", lambda f,d,**kw:legacy_flow(f,d))
    legacy = research.replay_gate(bench, flow, "US")
    pd.testing.assert_frame_equal(current, legacy)
    assert current.iloc[-1]["flow"] == 0
    assert not bool(current.iloc[-1]["closed_US"])


@pytest.mark.parametrize("local_ticker", ["069500.KS", "379810.KS", "999999.KQ"])
def test_local_same_day_remains_visible_and_us_seen_next_day(local_ticker):
    days, flow, _ = fixture()
    flow[local_ticker] = flow.pop("069500.KS")
    target = pd.DatetimeIndex([days[-1], days[-1] + pd.Timedelta(days=1)])
    initial = research.flow_score_series(flow, target, view="KR")
    assert list(initial.breadth) == [0., .5]
    flow[local_ticker].iloc[-1, 0] = 200.
    changed = research.flow_score_series(flow, target, view="KR")
    assert list(changed.breadth) == [.5, 1.]


def test_us_holiday_does_not_delay_last_available_bar_again():
    days, flow, _ = fixture()
    # d has no US row: d-1's large gain must already be visible on KR day d.
    us = flow["QQQ"].iloc[:-1].copy()
    us.iloc[-1, 0] = 200.
    flow["QQQ"] = us
    result = research.flow_score_series(flow, days[-1:], view="KR")
    assert result.breadth.iloc[0] == .5


def test_missing_latest_metric_not_filled_with_older_valid_metric():
    days, flow, _ = fixture()
    flow["QQQ"].iloc[-2, 0] = np.nan
    flow["069500.KS"].iloc[-1, 0] = 200.
    result = research.flow_score_series(flow, days[-1:], view="KR")
    assert result.breadth.iloc[0] == 1.  # US missing excluded from denominator


def test_warmup_has_no_future_value():
    days, flow, _ = fixture()
    result = research.flow_score_series({"QQQ": flow["QQQ"]}, days[[0,63,64]], view="KR")
    assert result.breadth.iloc[:2].isna().all()
    assert result.breadth.iloc[2] == 0


@pytest.mark.parametrize("view", ["", "JP", None])
def test_invalid_view_rejected(view):
    days, flow, _ = fixture()
    with pytest.raises(ValueError):
        research.flow_score_series(flow, days, view=view)


def test_unknown_listing_market_not_silently_us():
    days, flow, _ = fixture()
    with pytest.raises(ValueError):
        research.flow_score_series({"UNKNOWN.TO":flow["QQQ"]}, days, view="KR")
