"""Pure holdings display metrics, separate from valuation and trading policy."""

from math import nan
from stock_lab_core.formatters import finite_num


def breakeven_recovery_pct(current_price, breakeven_price):
    """Required rise from the current price; zero when already at breakeven."""
    if not finite_num(current_price) or not finite_num(breakeven_price):
        return nan
    current, breakeven = float(current_price), float(breakeven_price)
    if current <= 0 or breakeven <= 0:
        return nan
    return round(max(0.0, (breakeven / current - 1.0) * 100.0), 2)
