"""Regression: inverse ticker tokens must not match issuer/company substrings."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.portfolio import calc_asset_shock_table, infer_scenario_shock_multiplier


@pytest.mark.parametrize("ticker,name,expected", [
    ("SOXX", "iShares Semiconductor ETF", 1.0),
    ("IBB", "iShares Biotechnology ETF", 1.0),
    ("SHLD", "Global X Defense Tech ETF", 1.0),
    ("SHOP", "Shopify", 1.0),
    ("SH", "ProShares Short S&P500", -1.0),
    ("PSQ", "ProShares Short QQQ", -1.0),
    ("SDS", "ProShares UltraShort S&P500", -2.0),
    ("SH", "", -1.0),
    ("PSQ", "", -1.0),
    ("SDS", "", -2.0),
    (" sh ", "", -1.0),
    ("SPXU", "ProShares UltraPro Short S&P500", -3.0),
    ("SQQQ", "ProShares UltraPro Short QQQ", -3.0),
    ("SOXS", "Direxion Semiconductor Bear 3X Shares", -3.0),
    ("SSO", "ProShares Ultra S&P500", 2.0),
    ("UPRO", "ProShares UltraPro S&P500", 3.0),
    ("SPXL", "Direxion S&P500 Bull 3X Shares", 3.0),
    ("SOXL", "Direxion Semiconductor Bull 3X Shares", 3.0),
    ("QLD", "ProShares Ultra QQQ", 2.0),
    ("TQQQ", "ProShares UltraPro QQQ", 3.0),
    ("418660.KS", "NASDAQ 100 2X", 2.0),
    ("RAM", "Roundhill T-REX 2X Long DRAM", 2.0),
    ("BITX", "2X Bitcoin ETF", 2.0),
    ("BITU", "2X Bitcoin ETF", 2.0),
])
def test_inverse_and_long_products_keep_their_direction_and_magnitude(ticker, name, expected):
    row = {"티커": ticker, "자산명": name}
    original = deepcopy(row)
    assert infer_scenario_shock_multiplier(row) == expected
    assert row == original


@pytest.mark.parametrize("name,asset_class,expected", [
    ("Index Inverse ETF", "", -1.0),
    ("Index Short ETF", "", -1.0),
    ("ProShares UltraShort 2X", "", -2.0),
    ("Daily Semiconductor Bear 3X Shares", "", -3.0),
    ("지수 인버스", "", -1.0),
    ("지수 곱버스 2X", "", -2.0),
    ("", "us_inverse_etf", -1.0),
    ("ETF (SH)", "", -1.0),
    ("ETF / PSQ", "", -1.0),
    ("ETF: SDS", "", -2.0),
])
def test_legitimate_inverse_names_and_delimited_codes_still_work(name, asset_class, expected):
    assert infer_scenario_shock_multiplier({"ticker": "TEST", "name": name, "asset_class": asset_class}) == expected


def test_market_drop_is_loss_for_plain_ishares_and_gain_only_for_inverse_products():
    frame = pd.DataFrame([
        {"티커": ticker, "자산명": name, "원화환산": 1_000_000}
        for ticker, name in (("SOXX", "iShares Semiconductor ETF"), ("SH", "ProShares Short S&P500"),
                             ("PSQ", "ProShares Short QQQ"), ("SDS", "ProShares UltraShort S&P500"),
                             ("SSO", "ProShares Ultra S&P500"))
    ])
    original = frame.copy(deep=True)
    result = calc_asset_shock_table(frame, 5_000_000, -10).set_index("티커")
    assert result["예상손익"].to_dict() == {
        "SOXX": -100_000, "SH": 100_000, "PSQ": 100_000, "SDS": 200_000, "SSO": -200_000,
    }
    assert result.loc["SOXX", "충격후금액"] == 900_000
    pd.testing.assert_frame_equal(frame, original)
    unscaled = calc_asset_shock_table(frame, 5_000_000, -10, use_multiplier=False)
    assert unscaled["예상손익"].eq(-100_000).all()
