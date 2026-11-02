from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.report_fx import fx_interval_note
from stock_lab_core.report_scenario import nearest_fx_interval
from stock_lab_core.report_holdings import cumulative_holding_comparison


START = pd.Timestamp("2026-10-30T15:30:00+09:00")
END = pd.Timestamp("2026-11-02T15:30:00+09:00")
NOW = datetime.fromisoformat("2026-11-02T15:36:00+09:00")


def bars(start, end, values=(1300, 1313)):
    return pd.DataFrame({"Close": values}, index=pd.DatetimeIndex([start, end]) - pd.Timedelta(minutes=5))


def test_nearest_fx_labels_actual_endpoints_and_does_not_change_future_alignment():
    fx = bars(START - pd.Timedelta(minutes=5), END + pd.Timedelta(minutes=5))
    frames = {"379810.KS": pd.DataFrame({"Close": [100, 102]}, index=pd.to_datetime(["2026-10-30", "2026-11-02"]))}
    result = cumulative_holding_comparison({"티커": "379810.KS"}, {"379810.KS": {"date": "2026-11-02"}},
        {"KR": "2026-11-02", "US": "2026-10-30"}, NOW, frames,
        scenario_frames={"NQ=F": bars(START, END, (100, 101)), "USDKRW=X": fx})
    assert result["actual"] == pytest.approx(.02)
    assert result["reference"] == pytest.approx(.01)
    assert result["fx_return"] == pytest.approx(.01)
    assert "시작 -5분 / 끝 +5분" in fx_interval_note(result)
    assert result["fx_observation"]["approximate"]


def test_no_incomplete_future_or_stale_fx_and_exact_value_unchanged():
    assert not nearest_fx_interval(bars(START, END + pd.Timedelta(minutes=10)), START, END, NOW)
    assert not nearest_fx_interval(bars(START - pd.Timedelta(minutes=15), END), START, END, NOW)
    exact = nearest_fx_interval(bars(START, END), START, END, NOW)
    assert exact["return"] == pytest.approx(.01) and not exact["approximate"]
    assert fx_interval_note({"fx_observation": exact}) == ""


def test_equal_distance_prefers_earlier_bar_and_input_is_unchanged():
    frame = pd.DataFrame({"Close": [1300, 9999, 1313]},
        index=pd.DatetimeIndex([START - pd.Timedelta(minutes=10), START, END - pd.Timedelta(minutes=5)]))
    before = frame.copy(deep=True)
    result = nearest_fx_interval(frame, START, END, NOW)
    assert result["base_offset_minutes"] == -5 and result["return"] == pytest.approx(.01)
    pd.testing.assert_frame_equal(frame, before)
