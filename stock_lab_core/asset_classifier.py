"""Pure asset classification helpers for Stock Lab.

These helpers decide whether a ticker should be treated as an ETF/fund or an
individual stock. They intentionally avoid Streamlit and database imports so
portfolio rows, watchlist rows, and Today Queue can share the same rules.
"""

from __future__ import annotations

from stock_lab_core.constants import (
    FIN_SCORE_EXEMPT_ASSET_CLASS_KEYWORDS,
    KNOWN_INDIVIDUAL_STOCK_SYMBOLS,
    KNOWN_KR_ETF_SYMBOLS,
    KNOWN_US_NASDAQ_ETFS,
    KNOWN_US_OTHER_ETFS,
    KNOWN_US_SP_ETFS,
    KR_ETF_NAME_KEYWORDS,
)
from stock_lab_core.formatters import clean_bool, clean_symbol, is_kr_listed, sanitize_ticker_value


def is_known_individual_stock_ticker(ticker) -> bool:
    """Return True for symbols that must be treated as individual stocks."""
    return clean_symbol(ticker) in KNOWN_INDIVIDUAL_STOCK_SYMBOLS


def normalize_individual_stock_asset_class(ticker, current_asset_class="") -> str:
    """Return a stock asset class even if saved ETF metadata is stale."""
    current = str(current_asset_class or "").strip()
    if current and not asset_class_marks_fin_score_exempt(current):
        return current
    return "kr_stock" if is_kr_listed(ticker) else "us_stock"


def is_known_etf_ticker(ticker) -> bool:
    """Return True when the ticker is explicitly known as an ETF/ETN/fund."""
    raw = sanitize_ticker_value(ticker)
    symbol = clean_symbol(raw)
    if is_known_individual_stock_ticker(raw):
        return False
    return (
        symbol in KNOWN_US_SP_ETFS
        or symbol in KNOWN_US_NASDAQ_ETFS
        or symbol in KNOWN_US_OTHER_ETFS
        or symbol in KNOWN_KR_ETF_SYMBOLS
        or raw.endswith("ETF")
    )


def asset_class_marks_fin_score_exempt(asset_class) -> bool:
    """Return True when an asset class indicates ETF/fund-like treatment."""
    text = str(asset_class or "").strip().lower()
    return any(keyword in text for keyword in FIN_SCORE_EXEMPT_ASSET_CLASS_KEYWORDS)


def is_fin_score_exempt_asset(ticker, is_etf=False, asset_class="", name="") -> bool:
    """Return True when the asset should skip individual-company financial scoring."""
    if is_known_individual_stock_ticker(ticker):
        return False
    if clean_bool(is_etf) or is_known_etf_ticker(ticker) or asset_class_marks_fin_score_exempt(asset_class):
        return True

    name_upper = str(name or "").strip().upper()
    if is_kr_listed(ticker) and any(keyword in name_upper for keyword in KR_ETF_NAME_KEYWORDS):
        return True

    return False


def infer_asset_class_for_ticker(ticker, current_asset_class="") -> str:
    """Normalize the broad asset class using the shared ticker classifier."""
    current = str(current_asset_class or "").strip()
    if is_known_individual_stock_ticker(ticker):
        return normalize_individual_stock_asset_class(ticker, current)
    if not is_known_etf_ticker(ticker) and not asset_class_marks_fin_score_exempt(current):
        return current

    symbol = clean_symbol(ticker)
    if is_kr_listed(ticker):
        if symbol == "379810":
            return "us_etf_nasdaq"
        if symbol in {"379800", "458730"}:
            return "us_etf_sp"
        return current if asset_class_marks_fin_score_exempt(current) else "kr_etf"

    if symbol in KNOWN_US_SP_ETFS:
        return "us_etf_sp"
    if asset_class_marks_fin_score_exempt(current):
        return current
    return "us_etf_nasdaq"
