"""Date-bounded symbol continuity and listing events for flow callers."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

BLOCK_TICKER_CHANGE_SOURCE_URL = (
    "https://investors.block.xyz/investor-news/news-details/2025/"
    "Block-Announces-Ticker-Symbol-Change-to-XYZ-To-Report-Fourth-Quarter-Results/default.aspx"
)
SQ_TO_XYZ_EFFECTIVE_DATE = date(2025, 1, 21)
QRVO_LAST_TRADING_DATE = date(2026, 10, 2)
QRVO_INACTIVE_EFFECTIVE_DATE = date(2026, 10, 5)
QRVO_MERGER_SOURCE_URL = "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-702"

_NEW_YORK = ZoneInfo("America/New_York")
_ASOF_ERROR = "asof must be a date, an ISO YYYY-MM-DD string, or a timezone-aware timestamp"
_QRVO_LISTING_EVENT = {
    "status": "inactive",
    "last_trading_date": QRVO_LAST_TRADING_DATE.isoformat(),
    "effective_date": QRVO_INACTIVE_EFFECTIVE_DATE.isoformat(),
    "reason": "합병으로 독립 거래 종료; SWKS 주가로 대체하지 않음",
    "source_url": QRVO_MERGER_SOURCE_URL,
    "successor_symbol": "SWKS",
}


def _exchange_date(asof):
    if asof is None:
        return datetime.now(_NEW_YORK).date()
    try:
        if isinstance(asof, str):
            value = asof.strip()
            if len(value) == 10:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() == value:
                    return parsed
            elif len(value) > 10 and value[10] in ("T", " "):
                asof = datetime.fromisoformat(value)
        if isinstance(asof, datetime):
            if asof.utcoffset() is not None:
                return asof.astimezone(_NEW_YORK).date()
        elif isinstance(asof, date):
            return asof
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(_ASOF_ERROR) from exc
    raise ValueError(_ASOF_ERROR)


def resolve_flow_symbol(ticker: str, *, asof=None) -> str:
    """Normalize a symbol; only SQ's same-security rename can change it.

    Dates are exchange-day labels; aware timestamps use their New York date.
    None uses today's New York date. Invalid or naive timestamps raise ValueError.
    """
    day = _exchange_date(asof)
    symbol = ticker.strip().upper()
    if symbol == "SQ" and day >= SQ_TO_XYZ_EFFECTIVE_DATE:
        return "XYZ"
    return symbol


def flow_listing_event(ticker: str, *, asof=None) -> dict:
    """Return a fresh listing-event dict under the same asof rules as resolution.

    Successor metadata never authorizes substituting a successor's price history.
    """
    day = _exchange_date(asof)
    if ticker.strip().upper() == "QRVO" and day >= QRVO_INACTIVE_EFFECTIVE_DATE:
        return dict(_QRVO_LISTING_EVENT)
    return {}
