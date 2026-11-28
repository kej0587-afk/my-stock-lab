"""Timing/missingness checks for the isolated research, no network."""
import numpy as np
import pandas as pd
import pytest

from scripts.short_options_information_probe import BASE, compare, make_panel


def prices():
    idx = pd.bdate_range("2012-01-02", "2013-03-01")
    p = np.arange(len(idx), dtype=float) + 100
    return pd.DataFrame({"Open": p, "High": p + 2, "Low": p - 2,
                         "Close": p + 1, "Volume": p * 100}, index=idx)


def test_next_open_outcome_and_lag_missingness():
    px = prices()
    ratio = pd.Series(np.arange(len(px), dtype=float), index=px.index)
    missing = pd.Timestamp("2013-01-07")
    ratio = ratio.drop(missing)
    panel = make_panel(px, {"pc": ratio}, sessions=px.index)
    d = pd.Timestamp("2013-01-08")
    assert pd.isna(panel.at[d, "pc"])
    d = pd.Timestamp("2013-01-09")
    assert panel.at[d, "pc"] == ratio.loc["2013-01-08"]
    assert panel.at[d, "target"] == px.at[pd.Timestamp("2013-01-11"), "Open"] / px.at[pd.Timestamp("2013-01-10"), "Open"] - 1


def test_future_prices_do_not_change_features():
    px = prices()
    ratio = pd.Series(0.8, index=px.index)
    before = make_panel(px, {"pc": ratio}, sessions=px.index)
    px.loc[px.index > "2013-02-01", ["Open", "High", "Low", "Close"]] *= 2
    after = make_panel(px, {"pc": ratio}, sessions=px.index)
    pd.testing.assert_frame_equal(before.loc[:"2013-02-01", BASE + ["pc"]], after.loc[:"2013-02-01", BASE + ["pc"]])


def test_training_labels_cannot_cross_test_boundary():
    idx = pd.bdate_range("2016-11-01", "2017-01-31")
    rng = np.random.default_rng(42)
    panel = pd.DataFrame(rng.normal(size=(len(idx), len(BASE))), index=idx, columns=BASE)
    panel["pc"] = rng.normal(size=len(idx))
    panel["target"] = rng.normal(size=len(idx)) * .01
    panel["exit_date"] = pd.Series(idx, index=idx).shift(-2)
    result = compare(panel, "pc")
    expected = ((idx < "2017-01-01") & (panel.exit_date < "2017-01-01")).sum()
    assert result["train_n"] == expected
    assert result["train_range"][1] == "2016-12-28"


def test_absent_price_row_does_not_move_next_open_or_ratio_lag():
    px = prices()
    sessions = px.index
    ratio = pd.Series(np.arange(len(px), dtype=float), index=px.index)
    missing = pd.Timestamp("2013-01-10")
    panel = make_panel(px.drop(missing), {"pc": ratio}, sessions=sessions)
    signal = pd.Timestamp("2013-01-09")
    assert pd.isna(panel.at[signal, "target"])
    assert panel.at[signal, "exit_date"] == pd.Timestamp("2013-01-11")
    assert panel.at[signal, "pc"] == ratio.loc["2013-01-08"]
    assert pd.Timestamp("2013-01-11") not in panel.index  # incomplete feature window is withheld


@pytest.mark.parametrize("lag", [0, -1])
def test_future_or_same_day_ratio_not_allowed(lag):
    px = prices()
    with pytest.raises(ValueError):
        make_panel(px, {"pc":pd.Series(.8,index=px.index)}, lag=lag, sessions=px.index)
