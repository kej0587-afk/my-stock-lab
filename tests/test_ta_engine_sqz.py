import pandas as pd

from stock_lab_core.ta_engine import (
    build_smc_overlay_features,
    detect_equal_highs_lows,
    detect_order_block_zones,
    detect_smc_features,
    get_sqz_status,
)


def test_sqz_status_distinguishes_no_recent_squeeze():
    assert get_sqz_status(False, False, [False] * 10) == "➖비압축"


def test_sqz_status_keeps_release_only_after_recent_squeeze():
    assert get_sqz_status(False, False, [False, False, True, True, False, False]) == "➡️해제유지"


def test_sqz_status_core_transitions():
    assert get_sqz_status(True, False, [False, False, True]) == "⏳재압축"
    assert get_sqz_status(True, True, [True, True, True]) == "⏳압축중"
    assert get_sqz_status(False, True, [True, True, False]) == "🚀해제직후"


def test_detect_smc_features_reports_bullish_fvg_and_support_zone():
    df = pd.DataFrame(
        {
            "High": [10, 11, 12, 15, 16],
            "Low": [8, 9, 13, 14, 15],
            "Close": [9, 10, 14, 15, 15.5],
        }
    )

    result = detect_smc_features(df)

    assert "지지 갭(FVG)" in result["fvg_label"]
    assert "단기 지지선" in result["ob_label"]


def test_smc_overlay_features_include_fvg_and_equal_level_candidates():
    df = pd.DataFrame(
        {
            "Open": [10, 11, 12, 13, 12, 13, 14, 14, 15, 16, 16, 17, 18, 18, 19, 20, 19, 20, 21, 21],
            "High": [11, 12, 13, 15, 13, 14, 15, 16, 17, 19, 17, 18, 19, 21, 19, 20, 21, 22, 21, 22],
            "Low": [9, 10, 11, 12, 11, 12, 13, 14, 15, 16, 15, 16, 17, 18, 17, 18, 19, 20, 19, 20],
            "Close": [10.5, 11.5, 12.5, 14, 12.5, 13.5, 14.5, 15, 16, 18, 16.5, 17.5, 18.5, 20, 18.5, 19.5, 20.5, 21, 20.5, 21.5],
        }
    )

    features = build_smc_overlay_features(df)

    assert set(features) == {"fvg", "order_blocks", "equal_levels"}
    assert features["fvg"]["type"] in {"Bullish FVG", "Bearish FVG", "없음"}
    assert isinstance(detect_equal_highs_lows(df), list)
    assert isinstance(detect_order_block_zones(df), list)
