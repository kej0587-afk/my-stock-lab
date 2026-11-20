"""Quote-only placeholders must not contribute an invented trading range."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.decision_engine import calc_atr_for_decision, build_rr_context
from stock_lab_core.signal_basis import build_signal_basis, render_signal_basis


def price_bars(count=25):
    close = np.arange(count, dtype=float) + 100
    return pd.DataFrame({"Open": close - 1, "High": close + 3, "Low": close - 4,
                         "Close": close, "Volume": 1000.},
                        index=pd.bdate_range("2026-10-01", periods=count))


def old_atr(frame, period=14):
    tr = pd.concat([frame.High - frame.Low, (frame.High - frame.Close.shift()).abs(),
                    (frame.Low - frame.Close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


@pytest.mark.parametrize("price", [90., 119., 160.])
@pytest.mark.parametrize("append", [True, False])
def test_quote_only_gap_is_not_an_observed_range(price, append):
    source = price_bars()
    overlay = source.copy(deep=True)
    if append:
        day = overlay.index[-1] + pd.offsets.BDay()
    else:
        day = overlay.index[-1]
        source = source.iloc[:-1].copy()
    overlay["LiveQuoteOnly"] = False
    overlay.loc[day, ["Open", "High", "Low", "Close"]] = price
    overlay.loc[day, "Volume"] = np.nan
    overlay.loc[day, "LiveQuoteOnly"] = True
    before = overlay.copy(deep=True)
    levels = {"int_high": 200, "ext_high": 220}
    result = build_rr_context(overlay, price, levels)
    assert result == build_rr_context(source, price, levels)
    assert result["_atr"] == pytest.approx(old_atr(source))
    assert result["rr_stop_atr"] == round(price - 2 * old_atr(source), 4)
    assert old_atr(overlay) != result["_atr"]
    pd.testing.assert_frame_equal(overlay, before)


@pytest.mark.parametrize("flag", [None, False, np.nan])
def test_unmarked_history_preserves_original_atr_exactly(flag):
    source = price_bars()
    if flag is not None:
        source["LiveQuoteOnly"] = flag
    assert calc_atr_for_decision(source) == old_atr(source)


def test_placeholders_cannot_fill_missing_history():
    frame = price_bars(15)
    frame["LiveQuoteOnly"] = False
    frame.loc[frame.index[-1], "LiveQuoteOnly"] = True
    assert calc_atr_for_decision(frame) == 0
    assert build_rr_context(frame, 110, {"int_high": 120, "ext_high": 130})["rr_ratio"] is None


def test_quote_only_exclusion_is_applied_before_previous_close_shift():
    source = price_bars(30)
    overlay = source.copy()
    overlay["LiveQuoteOnly"] = False
    middle = overlay.index[-3]
    overlay.loc[middle, ["High", "Low", "Close"]] = 900
    overlay.loc[middle, "LiveQuoteOnly"] = True
    assert calc_atr_for_decision(overlay) == old_atr(source.drop(middle))


def test_provenance_separates_price_momentum_atr_and_volume_dates():
    source = price_bars()
    overlay = pd.concat([source, pd.DataFrame({"Close": [90], "LiveQuoteOnly": [True]},
                                            index=[source.index[-1] + pd.offsets.BDay()])])
    overlay.attrs["live_quote"] = {"mfi_asof": str(source.index[-1])}
    basis = build_signal_basis(source, (overlay, True, ""), calculated_at="captured")
    before = deepcopy(basis)
    frames, captions = [], []
    class UI:
        def dataframe(self, frame, **kw):
            frames.append(frame)
        def caption(self, text):
            captions.append(text)
    render_signal_basis(UI(), basis)
    assert basis["ATR기준일"] == source.index[-1].strftime("%Y-%m-%d")
    assert basis["ATR가격봉수"] == len(source)
    assert basis["ATR기준일"] != basis["지표마지막봉"]
    rows = frames[0].to_dict("records")
    assert "임시값" in rows[0]["가격 기준"]
    assert "현재가 보정 제외" in rows[1]["가격 기준"]
    assert "임시 봉 제외" in rows[2]["가격 기준"]
    assert "MFI" in rows[3]["가격 기준"]
    assert basis == before
