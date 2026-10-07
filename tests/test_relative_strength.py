import pandas as pd

from stock_lab_core.relative_strength import compute_relative_strength


def _prices(dates, values):
    return pd.DataFrame({"Close": values}, index=pd.to_datetime(dates))


def test_rs_compares_identical_sessions_despite_different_holidays():
    stock = _prices(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"], [100, 200, 102, 110])
    base = _prices(["2026-09-01", "2026-09-03", "2026-09-04"], [100, 101, 102])
    result = compute_relative_strength(stock, base, 2)
    assert result["label"] == "🚀강함"
    assert round(result["change_pct"], 2) == 7.84
    assert result["asof"] == "2026-09-04"


def test_missing_short_or_stale_history_is_not_reported_as_neutral():
    valid = _prices(["2026-09-01", "2026-09-02"], [100, 110])
    missing = compute_relative_strength(valid, pd.DataFrame(), 1)
    short = compute_relative_strength(valid, valid, 3)
    assert missing["label"] == "가격없음"
    assert missing["score"] == 0
    assert short["label"] == "이력부족"
    assert short["score"] == 0
    newer = _prices(["2026-09-01", "2026-09-02", "2026-09-20"], [100, 110, 115])
    stale = compute_relative_strength(newer, valid, 1)
    assert stale["label"] == "기준일차이"
    assert stale["score"] == 0
