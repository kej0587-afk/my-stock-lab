from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.sector_candidate_association import sector_market_from_row


@pytest.mark.parametrize("ticker", ["BRK-B", "BRK.B"])
def test_berkshire_theme_ownership_is_us_and_input_is_unchanged(ticker):
    row = {"테마": "미국 금융·핀테크", "대표주": f"버크셔해서웨이 ({ticker})",
           "테마돈흐름점수": 17.5, "1개월수익률": .03, "테마판정": "관망"}
    original = deepcopy(row)
    assert sector_market_from_row(row) == "미국"
    assert row == original


@pytest.mark.parametrize("row,expected", [
    ({"테마": "한국 금융", "대표주": "카카오뱅크 (323410.KS)"}, "한국"),
    ({"테마": "미국 금융·핀테크", "대표주": "버크셔해서웨이"}, "미국"),
    ({"테마": "금융·핀테크", "대표주": "버크셔해서웨이 (BRK-B)"}, "미국"),
    ({"Ticker": "BRK.B"}, "미국"),
    ({"Ticker": "0117V0.KS"}, "한국"),
    ({"Ticker": "035720.KQ"}, "한국"),
    ({"Ticker": "0117V0"}, "한국"),
    ({"Ticker": "VOD.L"}, "혼합"),
    ({"Ticker": "BTC-USD"}, "혼합"),
    ({"테마": "K-뷰티·소비재"}, "한국"),
    ({"테마": "BRK-B"}, "혼합"),
    ({"대표주": "ASUS", "시장": "AUS"}, "혼합"),
    ({"시장축": "미국", "테마": "한국 노출"}, "미국"),
    ({"시장축": "-", "시장": "KR"}, "한국"),
    ({"구분": "미국 섹터"}, "미국"),
    ({"테마": "한국·미국 금융"}, "혼합"),
    ({}, "혼합"),
])
def test_market_ownership_uses_exact_identity(row, expected):
    assert sector_market_from_row(pd.Series(row, dtype=object)) == expected


@pytest.mark.parametrize("symbol", ["BRK-B", "BRK.B"])
def test_sector_cards_keep_berkshire_only_in_us_after_adapter_integration(app_module, symbol):
    themes = pd.DataFrame([
        {"테마": "미국 금융·핀테크", "대표주": f"버크셔해서웨이 ({symbol})", "테마돈흐름점수": 17.5},
        {"테마": "한국 금융", "대표주": "카카오뱅크 (323410.KS)", "테마돈흐름점수": 15},
    ])
    original = themes.copy(deep=True)
    cards = app_module._flow_sector_ability_cards(pd.DataFrame(), pd.DataFrame(), themes)
    by_market = {card["market"]: card for card in cards}
    assert by_market["미국"]["representatives"] == "버크셔해서웨이"
    assert by_market["한국"]["representatives"] == "카카오뱅크"
    pd.testing.assert_frame_equal(themes, original)
