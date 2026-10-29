from datetime import datetime

from stock_lab_core.report_session import display_market_status


def test_overview_shows_both_markets_and_overnight_not_only_us_closed():
    now = datetime.fromisoformat("2026-10-29T10:32:00+09:00")
    result = display_market_status(now)
    assert "한국 장중" in result
    assert "미국 데이마켓" in result
    assert result.endswith("시간대")


def test_ticker_view_uses_market_specific_clock_and_aftermarket():
    now = datetime.fromisoformat("2026-10-29T07:00:00+09:00")
    assert display_market_status(now, market="KR") == "한국 개장 전 시간대"
    assert display_market_status(now, market="US") == "미국 애프터마켓 시간대"
