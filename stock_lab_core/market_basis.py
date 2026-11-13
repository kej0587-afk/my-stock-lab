"""Comparable daily-bar inputs for the market guard, without quote-time guesses."""

import numpy as np
import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def unique_guard_benchmarks(frame):
    """A valid S&P 500 index and its SPY proxy are one risk observation."""
    result = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    excluded = []
    if "티커" in result:
        tickers = result["티커"].astype(str).str.upper()
        if "^GSPC" in set(tickers) and "SPY" in set(tickers):
            excluded = ["SPY"]
            result = result.loc[tickers.ne("SPY")].copy()
    return result, excluded


def guard_macro_input(macro_data, legacy_risk):
    """Use the base captured with the macro snapshot, not today's event value.

    Older snapshots have no decomposition. Retain their score explicitly until
    refreshed rather than subtracting a possibly unrelated event observation.
    """
    values = list(macro_data.values()) if isinstance(macro_data, dict) else []
    pairs = []
    for value in values:
        if not isinstance(value, dict):
            break
        base, event = value.get("guard_macro_base"), value.get("guard_event_risk")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and np.isfinite(x)
                   for x in (base, event)):
            break
        pairs.append((float(base), float(event)))
    if values and len(pairs) == len(values) and len(set(pairs)) == 1:
        base, event = pairs[0]
        return {"risk": base, "event_included": event, "legacy_risk": legacy_risk,
                "status": "event_separated"}
    return {"risk": legacy_risk, "event_included": None, "legacy_risk": legacy_risk,
            "status": "legacy_unverified"}


def guard_input_dates(flow_frame, macro_data):
    """Show observed input dates only; do not substitute report generation time."""
    flow = []
    if isinstance(flow_frame, pd.DataFrame) and "기준일" in flow_frame:
        flow = sorted({str(x)[:10] for x in flow_frame["기준일"].dropna() if str(x).strip()})
    macro = {str(key): str(value.get("as_of") or "미확인")
             for key, value in (macro_data or {}).items() if isinstance(value, dict)}
    return {"flow": flow, "macro": macro}


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
