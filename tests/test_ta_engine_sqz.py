import pandas as pd

from stock_lab_core.ta_engine import detect_smc_features, get_sqz_status


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
