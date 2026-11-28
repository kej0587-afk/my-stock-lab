"""Explicit parking designations, independent of technical/investment policy."""

import pandas as pd

from stock_lab_core.formatters import normalize_bucket


def is_parking_asset(row):
    """True only for an explicitly designated reserve row (dict or Series).

    The canonical holdings field is ``bucket``. ``버킷`` is the existing
    portfolio display alias, used only when ``bucket`` is absent. Case and
    surrounding whitespace follow normalize_bucket. No ticker/name inference
    or global configuration is applied. Cash balances are not parking assets.
    """
    bucket = row.get("bucket", row.get("버킷", ""))
    return False if pd.isna(bucket) else normalize_bucket(bucket) == "reserve"


def parking_asset_rows(holdings):
    """Copy designated rows without dropping columns or recalculating values.

    build_holdings_table supplies 자산명, 티커, 보유량, 평가금액 (USD for US
    securities, KRW for Korean listings), 원화환산, 현재비중 and bucket.
    Preserve that schema: 평가금액 is not universally a USD amount. Include
    zero-quantity rows if present; this helper selects designation, not trades.
    """
    if holdings is None:
        return pd.DataFrame()
    if holdings.empty:
        return holdings.copy()
    return holdings.loc[holdings.apply(is_parking_asset, axis=1)].copy()
