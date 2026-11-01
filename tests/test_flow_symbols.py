from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core import flow_symbols as symbols
from stock_lab_core.report_build import _LOADED


EXPECTED_EVENT = {
    "status": "inactive",
    "last_trading_date": "2026-10-02",
    "effective_date": "2026-10-05",
    "reason": "합병으로 독립 거래 종료; SWKS 주가로 대체하지 않음",
    "source_url": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-702",
    "successor_symbol": "SWKS",
}


@pytest.mark.parametrize("asof,expected", [
    ("2025-01-17", "SQ"),
    (date(2025, 1, 20), "SQ"),
    ("2025-01-21", "XYZ"),
    (date(2025, 1, 22), "XYZ"),
])
def test_sq_rename_starts_on_nyse_effective_date(asof, expected):
    assert symbols.resolve_flow_symbol("SQ", asof=asof) == expected


@pytest.mark.parametrize("asof,inactive", [
    ("2026-10-01", False),
    (date(2026, 10, 2), False),
    ("2026-10-03", False),
    ("2026-10-04", False),
    (date(2026, 10, 5), True),
    ("2026-10-06", True),
])
def test_qrvo_listing_event_starts_after_last_trading_day(asof, inactive):
    assert symbols.flow_listing_event("QRVO", asof=asof) == (EXPECTED_EVENT if inactive else {})


@pytest.mark.parametrize("asof", ["2025-01-20", "2026-10-02", "2026-10-05", "2027-01-01"])
def test_merger_never_substitutes_swks_for_qrvo(asof):
    assert symbols.resolve_flow_symbol("QRVO", asof=asof) == "QRVO"
    assert symbols.resolve_flow_symbol("SWKS", asof=asof) == "SWKS"
    assert symbols.flow_listing_event("SWKS", asof=asof) == {}


@pytest.mark.parametrize("ticker,expected", [
    (" sq ", "XYZ"),
    ("\tSq\n", "XYZ"),
    (" xyz ", "XYZ"),
    (" qrVo ", "QRVO"),
    (" swks ", "SWKS"),
    (" aapl ", "AAPL"),
    ("  ", ""),
])
def test_normalizes_case_and_outer_whitespace(ticker, expected):
    assert symbols.resolve_flow_symbol(ticker, asof="2026-10-05") == expected
    event = symbols.flow_listing_event(ticker, asof="2026-10-05")
    assert event == (EXPECTED_EVENT if expected == "QRVO" else {})


@pytest.mark.parametrize("ticker", [" sq.ax ", "SQ.TO", "SQ.L", " qrvo.ax ", "QRVO.TO"])
def test_foreign_symbols_do_not_inherit_us_actions(ticker):
    assert symbols.resolve_flow_symbol(ticker, asof="2027-01-01") == ticker.strip().upper()
    assert symbols.flow_listing_event(ticker, asof="2027-01-01") == {}


@pytest.mark.parametrize("convert", [str, datetime.fromisoformat, pd.Timestamp])
@pytest.mark.parametrize("ticker,instant,resolved,inactive", [
    ("SQ", "2025-01-21T04:59:59+00:00", "SQ", False),
    ("SQ", "2025-01-21T05:00:00+00:00", "XYZ", False),
    ("SQ", "2025-01-21T13:59:59+09:00", "SQ", False),
    ("SQ", "2025-01-21T14:00:00+09:00", "XYZ", False),
    ("QRVO", "2026-10-05T03:59:59+00:00", "QRVO", False),
    ("QRVO", "2026-10-05T04:00:00+00:00", "QRVO", True),
    ("QRVO", "2026-10-05T12:59:59+09:00", "QRVO", False),
    ("QRVO", "2026-10-05T13:00:00+09:00", "QRVO", True),
])
def test_aware_timestamps_use_new_york_day_in_winter_and_summer(
    convert, ticker, instant, resolved, inactive,
):
    asof = convert(instant)
    assert symbols.resolve_flow_symbol(ticker, asof=asof) == resolved
    assert symbols.flow_listing_event(ticker, asof=asof) == (EXPECTED_EVENT if inactive else {})


@pytest.mark.parametrize("instant,resolved,inactive", [
    (datetime(2025, 1, 21, 4, 59, 59, tzinfo=timezone.utc), "SQ", False),
    (datetime(2025, 1, 21, 5, tzinfo=timezone.utc), "XYZ", False),
    (datetime(2026, 10, 5, 3, 59, 59, tzinfo=timezone.utc), "XYZ", False),
    (datetime(2026, 10, 5, 4, tzinfo=timezone.utc), "XYZ", True),
])
def test_default_is_today_in_new_york(monkeypatch, instant, resolved, inactive):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is not None
            return instant.astimezone(tz)

    monkeypatch.setattr(symbols, "datetime", FrozenDatetime)
    assert symbols.resolve_flow_symbol("SQ") == resolved
    assert symbols.resolve_flow_symbol("SQ", asof=None) == resolved
    assert symbols.flow_listing_event("QRVO") == (EXPECTED_EVENT if inactive else {})


@pytest.mark.parametrize("asof", [
    "", "today", "not-a-date", "2026-02-30", "2026-10", "20261005", "2026-W41-1",
    "2026-10-05T12:00:00", "2026-10-05T25:00:00+00:00",
    datetime(2026, 10, 5), pd.Timestamp("2026-10-05"), pd.NaT, pd.NA,
    0, 20261005, True, float("nan"), float("inf"), [], {}, object(),
])
@pytest.mark.parametrize("ticker", ["SQ", "QRVO", "AAPL"])
def test_invalid_or_unknown_asof_never_applies_actions_silently(asof, ticker):
    with pytest.raises(ValueError, match="asof must be"):
        symbols.resolve_flow_symbol(ticker, asof=asof)
    with pytest.raises(ValueError, match="asof must be"):
        symbols.flow_listing_event(ticker, asof=asof)


def test_returned_event_mutations_cannot_change_later_results():
    event = symbols.flow_listing_event("QRVO", asof="2026-10-05")
    second = symbols.flow_listing_event("QRVO", asof="2026-10-05")
    assert event is not second
    event["status"] = "active"
    event["successor_symbol"] = "XYZ"
    event.pop("source_url")
    assert second == EXPECTED_EVENT
    assert symbols.flow_listing_event("QRVO", asof="2026-10-06") == EXPECTED_EVENT
    assert symbols.resolve_flow_symbol("QRVO", asof="2026-10-06") == "QRVO"
    empty = symbols.flow_listing_event("QRVO", asof="2026-10-04")
    empty.update(EXPECTED_EVENT)
    assert symbols.flow_listing_event("QRVO", asof="2026-10-04") == {}
    assert symbols.flow_listing_event("SQ", asof="2026-10-05") == {}


def test_official_source_constant_and_loaded_source_registration():
    assert symbols.BLOCK_TICKER_CHANGE_SOURCE_URL == (
        "https://investors.block.xyz/investor-news/news-details/2025/"
        "Block-Announces-Ticker-Symbol-Change-to-XYZ-To-Report-Fourth-Quarter-Results/default.aspx"
    )
    assert _LOADED[symbols.__name__]["path"] == str(Path(symbols.__file__).resolve())
    assert len(_LOADED[symbols.__name__]["sha256"]) == 64
