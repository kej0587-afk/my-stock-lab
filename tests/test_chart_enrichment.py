import copy

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from stock_lab_core.chart_enrichment import (
    build_financial_snapshot_rows,
    build_volume_at_price_profile,
    build_volume_signal_series,
    build_volume_signal_tail,
)


def _ohlcv(volumes, *, up=False):
    count = len(volumes)
    close = 1000.0 + np.arange(count) * (1 if up else -1)
    return pd.DataFrame({
        "Open": close + (2 if up else -2), "High": close + 3,
        "Low": close - 3, "Close": close, "Volume": volumes,
    }, index=pd.date_range("2025-01-01", periods=count))


@pytest.mark.parametrize("volumes,up,expected", [
    ([100] * 70 + [200], True, "HVE"),
    ([1000] + [100] * 252 + [200], True, "HVY"),
    ([1000] + [100] * 70 + [200], True, "HVQ"),
    ([1000] + [100] * 19 + [150], True, "POCKET_PIVOT"),
    ([1000] + [100] * 19 + [300], False, "POWER"),
    ([1000] + [100] * 19 + [200], False, "HIGH"),
    ([1000] + [100] * 58 + [10], False, "DRY60"),
    ([1000, 5] + [100] * 38 + [10], False, "DRY20"),
    ([1000] + [100] * 19 + [90], False, "BASE"),
])
def test_signal_priority(volumes, up, expected):
    row = build_volume_signal_series(_ohlcv(volumes, up=up), ma_length=5).iloc[-1]
    assert row.signal == expected
    assert isinstance(row.color, str) and row.color.startswith("#")


def test_overlapping_conditions_use_pine_priority():
    result = build_volume_signal_series(_ohlcv([100] * 60 + [1000], up=True))
    last = result.iloc[-1]
    assert all(last[key] for key in ["is_hve", "is_hvy", "is_hvq", "is_pocket_pivot", "is_power", "is_high"])
    assert last.signal == "HVE"
    assert build_volume_signal_series(_ohlcv([20, 20])).signal.tolist() == ["HVE", "HVE"]


def test_previous_close_direction_ignores_candle_body_and_flat_excluded_from_ud():
    frame = _ohlcv([10, 20, 30, 40])
    frame["Close"] = [100, 101, 100, 100]
    frame["Open"] = [100, 110, 90, 80]
    result = build_volume_signal_series(frame, ma_length=2, ud_length=3)
    assert result.direction.tolist() == ["unknown", "up", "down", "flat"]
    assert result.up_volume.tolist() == [0, 20, 0, 0]
    assert result.down_volume.tolist() == [0, 0, 30, 0]
    assert result.iloc[-1].up_down_ratio == pytest.approx(20 / 30)
    assert result.iloc[-1].rvol == pytest.approx(40 / 35)
    assert result.iloc[-1].buzz_pct == pytest.approx((40 / 35 - 1) * 100)


def test_pocket_pivot_uses_prior_down_bars_and_strict_volume_comparison():
    frame = _ohlcv([1000, 150, 80, 150, 151])
    frame["Close"] = [100, 99, 100, 101, 101]
    result = build_volume_signal_series(frame, pocket_lookback=3, ma_length=2)
    assert not result.iloc[3].is_pocket_pivot
    assert result.iloc[4].is_pocket_pivot
    assert result.iloc[4].signal == "POCKET_PIVOT"


def test_prefix_invariance_and_tail_keep_full_history_without_mutation():
    rng = np.random.default_rng(73)
    frame = _ohlcv(rng.integers(10, 300, 320))
    frame["Close"] = 100 + rng.normal(size=len(frame)).cumsum()
    original = frame.copy(deep=True)
    full = build_volume_signal_series(frame)
    for cutoff in [1, 9, 50, 63, 252, 301]:
        assert_frame_equal(build_volume_signal_series(frame.iloc[:cutoff]), full.iloc[:cutoff])
    assert_frame_equal(build_volume_signal_tail(frame, bars=3), full.tail(3))
    assert_frame_equal(frame, original)


@pytest.mark.parametrize("timeframe,ma,year,quarter", [
    ("daily", 50, 252, 63), ("weekly", 10, 52, 13), ("monthly", 50, 12, 3),
])
def test_timeframe_windows(timeframe, ma, year, quarter):
    result = build_volume_signal_series(_ohlcv([1000] + [100] * year + [200]), timeframe=timeframe)
    assert result.attrs["ma_length"] == ma
    assert result.attrs["year_length"] == year
    assert result.attrs["quarter_length"] == quarter
    assert result.iloc[-1].signal == "HVY"


def test_missing_and_zero_volume_do_not_fabricate_ratios_or_record_signals():
    frame = _ohlcv([0, 0, -1, np.nan, np.inf, 20], up=True)
    result = build_volume_signal_series(frame, ma_length=2, ud_length=2)
    assert result.signal.tolist() == ["BASE", "BASE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "HVE"]
    assert result.rvol.isna().all()
    assert result.up_down_ratio.isna().all()
    assert not result.iloc[2:5].is_hve.any()
    missing_volume = build_volume_signal_series(frame.drop(columns="Volume"))
    assert missing_volume.signal.eq("UNAVAILABLE").all()
    assert build_volume_signal_series(None).empty
    assert build_volume_signal_tail(None).empty


def test_missing_close_does_not_reuse_a_stale_direction():
    frame = _ohlcv([100, 50, 60, 70])
    frame["Close"] = [100, np.nan, 101, 102]
    result = build_volume_signal_series(frame, ma_length=2)
    assert result.iloc[1].signal == "UNAVAILABLE"
    assert result.direction.tolist() == ["unknown", "unknown", "unknown", "up"]


@pytest.mark.parametrize("kwargs", [
    {"ma_length": 0}, {"ud_length": 1.5}, {"pocket_lookback": True},
    {"timeframe": "intraday"}, {"dry_mult": 0}, {"high_mult": 3, "power_mult": 2},
])
def test_invalid_signal_options(kwargs):
    with pytest.raises(ValueError):
        build_volume_signal_series(_ohlcv([10, 20]), **kwargs)


def _profile_frame(lows, highs, volumes, closes=None):
    return pd.DataFrame({"Low": lows, "High": highs,
                         "Close": lows if closes is None else closes, "Volume": volumes})


def test_profile_overlap_conserves_volume_and_value_area_includes_poc():
    frame = _profile_frame([10, 10, 15], [20, 15, 20], [100, 200, 300])
    original = frame.copy(deep=True)
    result = build_volume_at_price_profile(frame, bins=2)
    assert result["ok"]
    assert [row["volume"] for row in result["rows"]] == pytest.approx([250, 350])
    assert result["total_volume"] == pytest.approx(600)
    assert sum(row["fraction"] for row in result["rows"]) == pytest.approx(1)
    assert result["poc"]["mid"] == pytest.approx(17.5)
    assert result["value_area_low"] <= result["poc"]["mid"] <= result["value_area_high"]
    assert result["value_area_fraction"] >= 0.7
    assert result["estimated"] and "order book" in result["note"]
    assert_frame_equal(frame, original)


def test_point_bars_on_edges_only_enter_one_bin():
    frame = _profile_frame([10, 15, 20], [10, 15, 20], [10, 20, 30])
    result = build_volume_at_price_profile(frame, bins=2)
    assert [row["volume"] for row in result["rows"]] == [10, 50]
    assert result["total_volume"] == 60


def test_constant_price_is_a_single_node_without_invented_range():
    result = build_volume_at_price_profile(_profile_frame([10, 10], [10, 10], [10, 20]))
    assert result["ok"] and len(result["rows"]) == 1
    assert result["poc"]["mid"] == result["value_area_low"] == result["value_area_high"] == 10
    assert result["value_area_fraction"] == 1
    assert result["total_volume"] == 30
    assert len(result["hvn_levels"]) == 1


def test_poc_and_value_area_ties_are_deterministic():
    result = build_volume_at_price_profile(
        _profile_frame([10, 12, 14, 16], [10, 12, 14, 16], [40, 100, 40, 1]),
        bins=4, value_area=0.7,
    )
    assert result["poc"]["mid"] == 12.25
    assert result["value_area_low"] == 10
    assert result["value_area_high"] == 13
    tied = build_volume_at_price_profile(_profile_frame([10], [20], [100]), bins=4)
    assert tied["poc"]["mid"] == 11.25
    assert len(tied["hvn_levels"]) == 1


def test_hvn_are_distinct_local_maxima_sorted_by_volume():
    result = build_volume_at_price_profile(
        _profile_frame([10, 11, 12, 13, 14, 15, 16], [10, 11, 12, 13, 14, 15, 16],
                       [10, 100, 5, 80, 5, 60, 1]), bins=7,
    )
    assert [row["volume"] for row in result["hvn_levels"]] == [100, 80, 60]


def test_profile_excludes_missing_invalid_and_zero_volume_without_synthetic_weights():
    frame = _profile_frame([10] * 6, [20, 20, 9, 20, 20, 20], [100, np.nan, 100, -1, 0, np.inf])
    result = build_volume_at_price_profile(frame, bins=2)
    assert result["bars_used"] == 1 and result["bars_excluded"] == 5
    assert result["total_volume"] == 100
    assert not build_volume_at_price_profile(frame.drop(columns="Volume"))["ok"]
    assert not build_volume_at_price_profile(frame.iloc[1:])["ok"]
    assert not build_volume_at_price_profile(None)["ok"]
    outside = _profile_frame([10], [20], [100], closes=[21])
    assert not build_volume_at_price_profile(outside)["ok"]


def test_profile_lookback_is_applied_before_filtering_bad_bars():
    frame = _profile_frame([10, 15, 15], [20, 15, 15], [1000, 10, np.nan])
    result = build_volume_at_price_profile(frame, lookback=2)
    assert result["total_volume"] == 10
    assert result["bars_excluded"] == 1


def test_profile_conserves_randomized_volumes_and_full_value_area():
    rng = np.random.default_rng(14)
    lows = rng.uniform(5, 100, 100)
    highs = lows + rng.uniform(0.1, 20, 100)
    volumes = rng.uniform(1, 1e7, 100)
    frame = _profile_frame(lows, highs, volumes)
    result = build_volume_at_price_profile(frame, bins=31, value_area=1)
    assert sum(row["volume"] for row in result["rows"]) == pytest.approx(volumes.sum())
    assert result["value_area_fraction"] == pytest.approx(1)


@pytest.mark.parametrize("kwargs", [
    {"bins": 0}, {"bins": 501}, {"lookback": -2}, {"value_area": 1.1},
    {"value_area": np.nan}, {"hvn_count": 0}, {"hvn_min_ratio": -1},
])
def test_invalid_profile_options(kwargs):
    with pytest.raises(ValueError):
        build_volume_at_price_profile(None, **kwargs)


@pytest.mark.parametrize("builder", [build_volume_signal_series, build_volume_at_price_profile])
def test_out_of_order_or_duplicate_indexes_rejected_without_realigning(builder):
    frame = _ohlcv([10, 20, 30])
    with pytest.raises(ValueError, match="chronological"):
        builder(frame.iloc[::-1])
    frame.index = [0, 0, 1]
    with pytest.raises(ValueError, match="unique"):
        builder(frame)


def test_financial_rows_exclude_missing_preserve_zero_negative_and_currency():
    info = {"trailingPE": None, "forwardPE": np.inf, "priceToBook": "-",
            "returnOnEquity": -0.1, "operatingMargins": 0, "revenueGrowth": "0.25",
            "currentRatio": True, "currency": "USD", "financialCurrency": "KRW",
            "currentPrice": 100, "operatingCashflow": -1000}
    original = copy.deepcopy(info)
    rows = build_financial_snapshot_rows(info)
    by_key = {row["key"]: row for row in rows}
    assert set(by_key) == {"currentPrice", "returnOnEquity", "operatingMargins", "revenueGrowth", "operatingCashflow"}
    assert by_key["returnOnEquity"]["value"] == -10
    assert by_key["operatingMargins"]["value"] == 0
    assert by_key["revenueGrowth"]["value"] == 25
    assert by_key["currentPrice"]["currency"] == "USD"
    assert by_key["operatingCashflow"]["currency"] == "KRW"
    assert all("score" not in row for row in rows)
    assert info == original


@pytest.mark.parametrize("quote_type", ["ETF", "ETN", "MUTUALFUND", "mutual_fund"])
def test_funds_never_receive_corporate_metrics_or_scores(quote_type):
    info = {"quoteType": quote_type, "returnOnEquity": 0.2, "trailingPE": 20,
            "marketCap": 1000, "freeCashflow": 100, "totalAssets": 500,
            "navPrice": 12, "annualReportExpenseRatio": 0.005, "currency": "USD"}
    rows = build_financial_snapshot_rows(info)
    assert {row["key"] for row in rows} == {"totalAssets", "navPrice", "annualReportExpenseRatio"}
    assert next(row for row in rows if row["key"] == "annualReportExpenseRatio")["value"] == 0.5
    assert all(row["group"] == "fund" and "score" not in row for row in rows)


def test_explicit_etf_flag_overrides_equity_metadata_and_wrapped_info_is_supported():
    info = {"data": {"quoteType": "EQUITY", "trailingPE": 10, "currentPrice": None,
                     "regularMarketPrice": "1,200", "navPrice": 1199}}
    rows = build_financial_snapshot_rows(info, is_etf=True)
    assert {row["key"] for row in rows} == {"regularMarketPrice", "navPrice"}
    assert rows[0]["value"] == 1200
    assert build_financial_snapshot_rows(None) == []
    assert build_financial_snapshot_rows({"trailingPE": np.nan, "profitMargins": "N/A"}) == []


def test_financial_rows_do_not_guess_ambiguous_provider_units_or_derive_valuations():
    info = {"dividendYield": 2, "debtToEquity": 1.5, "marketCap": 200,
            "netIncomeToCommon": 10, "trailingAnnualDividendYield": 0.02}
    rows = build_financial_snapshot_rows(info)
    assert {row["key"] for row in rows} == {"marketCap", "trailingAnnualDividendYield"}
    assert next(row for row in rows if row["unit"] == "%")["value"] == 2


def test_explicit_percent_strings_are_not_multiplied_again_or_used_as_prices():
    rows = build_financial_snapshot_rows({
        "returnOnEquity": "-10%", "operatingMargins": "0%",
        "trailingAnnualDividendYield": "2.5%", "currentPrice": "100%",
    })
    assert {row["key"]: row["value"] for row in rows} == {
        "returnOnEquity": -10, "operatingMargins": 0, "trailingAnnualDividendYield": 2.5,
    }
