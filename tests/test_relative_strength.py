import pandas as pd
import pytest

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
    assert result["start_asof"] == "2026-09-01"


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


def test_rs_prefers_adjusted_close_when_available():
    stock = pd.DataFrame(
        {
            "Close": [100, 100],
            "Adj Close": [100, 110],
        },
        index=pd.to_datetime(["2026-09-01", "2026-09-02"]),
    )
    base = pd.DataFrame(
        {
            "Close": [100, 100],
            "Adj Close": [100, 100],
        },
        index=pd.to_datetime(["2026-09-01", "2026-09-02"]),
    )

    result = compute_relative_strength(stock, base, 1)

    assert result["label"] == "🚀강함"
    assert result["price_basis"] == "Adj Close / Adj Close"


def test_rs_can_use_close_when_adjusted_close_is_disabled():
    stock = pd.DataFrame(
        {
            "Close": [100, 100],
            "Adj Close": [100, 110],
        },
        index=pd.to_datetime(["2026-09-01", "2026-09-02"]),
    )
    base = pd.DataFrame(
        {
            "Close": [100, 100],
            "Adj Close": [100, 100],
        },
        index=pd.to_datetime(["2026-09-01", "2026-09-02"]),
    )

    result = compute_relative_strength(stock, base, 1, prefer_adjusted=False)

    assert result["label"] == "➖보통"
    assert result["price_basis"] == "Close / Close"


def test_rs_reports_no_common_sessions_separately():
    stock = _prices(["2026-09-01", "2026-09-03"], [100, 105])
    base = _prices(["2026-09-02", "2026-09-04"], [100, 101])

    result = compute_relative_strength(stock, base, 1)

    assert result["label"] == "공통거래일없음"
    assert result["score"] == 0
    assert result["sessions"] == 0


def test_rs_keeps_latest_duplicate_daily_close():
    stock = pd.DataFrame(
        {"Close": [100, 120, 130]},
        index=pd.to_datetime(["2026-09-01 09:30", "2026-09-02 09:30", "2026-09-02 16:00"]),
    )
    base = pd.DataFrame(
        {"Close": [100, 100]},
        index=pd.to_datetime(["2026-09-01", "2026-09-02"]),
    )

    result = compute_relative_strength(stock, base, 1)

    assert result["label"] == "🚀강함"
    assert result["change_pct"] == pytest.approx(30.0)
