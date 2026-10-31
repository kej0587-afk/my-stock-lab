"""Comparable daily-bar inputs for the market guard, without quote-time guesses."""

import numpy as np
import pandas as pd


def positive_observation_fraction(values):
    """Exclude missing/non-finite observations, retaining genuine zero returns."""
    raw = pd.Series(values)
    numeric = pd.to_numeric(raw, errors="coerce")
    valid = np.isfinite(numeric).fillna(False) & ~raw.map(lambda value: isinstance(value, (bool, np.bool_)))
    observed = numeric.loc[valid]
    return {
        "fraction": float(observed.gt(0).mean()) if not observed.empty else np.nan,
        "valid": int(valid.sum()), "missing": int((~valid).sum()),
    }


def daily_close(frame):
    """Keep provider trading dates; a daily index is not a live quote timestamp."""
    if not isinstance(frame, pd.DataFrame) or "Close" not in frame:
        return pd.Series(dtype=float)
    if not isinstance(frame.index, pd.DatetimeIndex):
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame["Close"], errors="coerce").copy()
    close.index = close.index.tz_localize(None).normalize()
    close = close.loc[close.index.notna() & np.isfinite(close) & close.gt(0)]
    return close[~close.index.duplicated(keep="last")].sort_index()


def align_market_closes(closes, regions, *, minimum_bars=25):
    """Truncate each region to its latest common trading date, never forward-fill.

    KR and US are independent sessions. Missing/short histories are not allowed
    to pull an otherwise usable region back to a new instrument's listing date.
    """
    aligned = {key: value.copy() for key, value in closes.items()}
    notes = {}
    for region in set(regions.values()):
        keys = [key for key, value in closes.items()
                if regions.get(key) == region and len(value) >= minimum_bars]
        if not keys:
            continue
        common = closes[keys[0]].index
        for key in keys[1:]:
            common = common.intersection(closes[key].index)
        if common.empty:
            for key in keys:
                aligned[key] = closes[key].iloc[:0]
                notes[key] = "공통 거래일 없음"
            continue
        common = common.sort_values()
        asof = common.max()
        latest = max(closes[key].index.max() for key in keys)
        for key in keys:
            # Use the same denominator date as well as the same final date.
            aligned[key] = closes[key].reindex(common)
            notes[key] = (
                f"공통일 {asof:%Y-%m-%d} · 시장 내 최신봉 {latest:%Y-%m-%d}"
                if asof < latest else "동일 거래일"
            )
    return aligned, notes
