from stock_lab_core.ta_engine import get_sqz_status


def test_sqz_status_distinguishes_no_recent_squeeze():
    assert get_sqz_status(False, False, [False] * 10) == "➖비압축"


def test_sqz_status_keeps_release_only_after_recent_squeeze():
    assert get_sqz_status(False, False, [False, False, True, True, False, False]) == "➡️해제유지"


def test_sqz_status_core_transitions():
    assert get_sqz_status(True, False, [False, False, True]) == "⏳재압축"
    assert get_sqz_status(True, True, [True, True, True]) == "⏳압축중"
    assert get_sqz_status(False, True, [True, True, False]) == "🚀해제직후"
