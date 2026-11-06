"""Exact parity with ta's existing MFI, including warmup and missing volume."""

import numpy as np
import pandas as pd
import pytest
import ta

from stock_lab_core.ta_engine import build_indicators
from tests.fixtures_price import make_price_df


@pytest.mark.parametrize("days", [3, 13, 14, 15, 20, 63, 260, 2600])
@pytest.mark.parametrize("case", ["mixed", "up", "down", "flat", "zero_volume",
                                 "missing_volume", "missing_price", "infinity", "float32"])
def test_mfi_exactly_matches_reference(days, case):
    frame = make_price_df(days=max(days, 20)).iloc[-days:][
        ["Open", "High", "Low", "Close", "Volume"]
    ].copy()
    if case in {"up", "down", "flat"}:
        close = np.arange(days, dtype=float) + 100
        if case == "down":
            close = close[::-1]
        elif case == "flat":
            close[:] = 100
        for col in ("Open", "High", "Low", "Close"):
            frame[col] = close
    elif case == "zero_volume":
        frame["Volume"] = 0.0
    elif case == "missing_volume":
        frame.iloc[::17, frame.columns.get_loc("Volume")] = np.nan
        frame.iloc[-1, frame.columns.get_loc("Volume")] = np.nan
    elif case == "missing_price":
        frame.iloc[::19, frame.columns.get_loc("High")] = np.nan
    elif case == "infinity":
        frame.iloc[::23, frame.columns.get_loc("Volume")] = np.inf
    elif case == "float32":
        frame = frame.astype("float32")
    # Non-default labels must survive; values must not be aligned by row number.
    frame.index = frame.index.tz_localize("Asia/Seoul")
    frame.attrs["source"] = "fixed parity input"
    original = frame.copy(deep=True)
    expected = ta.volume.MFIIndicator(
        frame.High, frame.Low, frame.Close, frame.Volume
    ).money_flow_index().rename("MFI")
    actual = build_indicators(frame)
    pd.testing.assert_series_equal(actual.MFI, expected, check_exact=True)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert actual.attrs == original.attrs


def test_mfi_preserves_duplicate_dates():
    frame = make_price_df(days=63)
    frame.index = pd.DatetimeIndex([pd.Timestamp("2026-01-02")] * len(frame))
    expected = ta.volume.MFIIndicator(frame.High, frame.Low, frame.Close, frame.Volume).money_flow_index()
    pd.testing.assert_series_equal(build_indicators(frame).MFI, expected.rename("MFI"), check_exact=True)


def test_mfi_long_history_chunk_boundaries():
    from stock_lab_core.ta_engine import _money_flow_index

    frame = make_price_df(days=8300)
    frame.loc[frame.index[[4095, 4108, 8204]], "Volume"] = np.nan
    expected = ta.volume.MFIIndicator(frame.High, frame.Low, frame.Close, frame.Volume).money_flow_index()
    actual = _money_flow_index(frame.High, frame.Low, frame.Close, frame.Volume)
    pd.testing.assert_series_equal(actual, expected, check_exact=True)
