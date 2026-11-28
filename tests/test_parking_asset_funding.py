"""Synthetic accounting contracts: held reserves are assets, not deposit cash."""

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.parking_assets import is_parking_asset, parking_asset_rows
from stock_lab_core.portfolio import (
    append_cash_rows,
    apply_holdings_weight_columns,
    calc_portfolio_summary,
    calc_reserve_summary,
    get_active_portfolio_rows,
)


@pytest.mark.parametrize("row, expected", [
    ({"티커": "SGOV", "bucket": "reserve"}, True),
    ({"티커": "SGOV", "bucket": "core"}, False),
    ({"티커": "SGOV"}, False),
    ({"티커": "OTHER", "bucket": " Reserve "}, True),
    ({"티커": "OTHER", "버킷": "reserve"}, True),
    ({"bucket": "core", "버킷": "reserve"}, False),
    ({"bucket": "cash"}, False),
    ({"bucket": "swing"}, False),
    ({"bucket": "leverage"}, False),
    ({"bucket": None}, False),
    ({"bucket": np.nan}, False),
    ({"bucket": pd.NA}, False),
    ({"자산명": "SGOV 파킹 대기자금"}, False),
])
def test_only_explicit_reserve_designation_is_parking(row, expected):
    assert is_parking_asset(row) is expected
    assert is_parking_asset(pd.Series(row)) is expected


def _holdings(bucket="reserve"):
    # Same valuation/display fields as app.build_holdings_table; no live prices.
    return pd.DataFrame([
        {"티커": "SGOV", "자산명": "USD reserve", "보유량": 10.,
         "현재가": 100., "평가금액": 1000., "원화환산": 1_400_000.,
         "목표비중": 10., "bucket": bucket},
        {"티커": "TEST", "자산명": "Active holding", "보유량": 20.,
         "현재가": 100., "평가금액": 2000., "원화환산": 2_800_000.,
         "목표비중": 70., "bucket": "core"},
        {"티커": "357870.KS", "자산명": "KRW reserve", "보유량": 2.,
         "현재가": 50_000., "평가금액": 100_000., "원화환산": 100_000.,
         "목표비중": 0., "bucket": "reserve"},
    ])


@pytest.mark.parametrize("krw_cash,usd_cash", [(140_000., 100.), (0., 0.)])
def test_nav_counts_held_reserve_once_and_cash_excludes_it(krw_cash, usd_cash):
    holdings = _holdings()
    original = holdings.copy(deep=True)
    cash = krw_cash + usd_cash * 1400.
    expected_nav = 4_300_000. + cash
    weighted = apply_holdings_weight_columns(holdings, krw_cash, usd_cash, 1400.)
    summary = calc_portfolio_summary(weighted, 4_000_000., krw_cash, usd_cash,
                                     1400., pd.DataFrame())
    full = append_cash_rows(weighted, krw_cash, usd_cash, 1400., expected_nav)
    reserve = calc_reserve_summary(full, 10.)

    assert summary["current_asset"] == expected_nav
    assert summary["stock_value"] == 4_300_000.
    assert summary["cash_value"] == cash
    assert reserve["total"] == expected_nav
    assert reserve["reserve_value"] == 1_500_000.
    assert reserve["cash_value"] == cash
    assert reserve["waiting_value"] == 1_500_000. + cash
    assert reserve["invest_value"] == 2_800_000.
    assert reserve["total"] == reserve["invest_value"] + reserve["waiting_value"]
    assert full["현재비중"].sum() == pytest.approx(100.)
    assert get_active_portfolio_rows(weighted)["티커"].tolist() == ["TEST"]

    parking = parking_asset_rows(weighted)
    sgov = parking.set_index("티커").loc["SGOV"]
    assert sgov["보유량"] == 10.
    assert sgov["평가금액"] == 1000.
    assert sgov["원화환산"] == 1_400_000.
    assert sgov["현재비중"] == pytest.approx(1_400_000. / expected_nav * 100)
    assert not sgov["운용대상"]
    pd.testing.assert_frame_equal(holdings, original)


def test_sgov_without_designation_remains_an_active_asset():
    weighted = apply_holdings_weight_columns(_holdings("core"), 0., 0., 1400.)
    assert "SGOV" in get_active_portfolio_rows(weighted)["티커"].tolist()
    assert parking_asset_rows(weighted)["티커"].tolist() == ["357870.KS"]
    assert calc_portfolio_summary(weighted, 0., 0., 0., 1400., None)["current_asset"] == 4_300_000.


def test_parking_rows_preserve_schema_index_values_and_do_not_mutate_input():
    holdings = _holdings()
    holdings.index = [8, 3, 1]
    original = holdings.copy(deep=True)
    selected = parking_asset_rows(holdings)
    pd.testing.assert_frame_equal(selected, holdings.loc[[8, 1]])
    selected.loc[8, "보유량"] = 999.
    pd.testing.assert_frame_equal(holdings, original)
    pd.testing.assert_frame_equal(parking_asset_rows(holdings.iloc[:0]), holdings.iloc[:0])
    assert parking_asset_rows(pd.DataFrame([{"티커": "SGOV"}])).empty
    assert parking_asset_rows(None).empty


def test_all_cash_and_empty_portfolio_have_no_held_reserve():
    summary = calc_portfolio_summary(pd.DataFrame(), 0., 100., 1., 1400., None)
    full = append_cash_rows(pd.DataFrame(), 100., 1., 1400., summary["current_asset"])
    reserve = calc_reserve_summary(full, 10.)
    assert summary["current_asset"] == reserve["total"] == 1500.
    assert reserve["cash_value"] == reserve["waiting_value"] == 1500.
    assert reserve["reserve_value"] == 0.
    assert parking_asset_rows(full).empty
    assert calc_reserve_summary(pd.DataFrame(), 10.)["total"] == 0.
