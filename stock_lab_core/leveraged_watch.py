"""Build leveraged-product proxy rows with bounded, context-aware overlap."""

from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from threading import BoundedSemaphore

import numpy as np
import pandas as pd

from stock_lab_core.formatters import (
    clean_float,
    finite_num,
    format_currency,
    sanitize_ticker_value,
)
from stock_lab_core.performance import submit_with_context, timed_call
from stock_lab_core.report_build import register_loaded_source


_PARALLEL_ROW_SLOTS = BoundedSemaphore(2)


@timed_call("external_data")
def _build_watch_row(entry, *, load_quote, load_history, pct_text, judge):
    t, role, label = entry
    ticker = sanitize_ticker_value(t)
    px = clean_float(load_quote(ticker), 0.0)
    try:
        hist = load_history(ticker, "6mo")
        close = pd.to_numeric(hist["Close"], errors="coerce").dropna() if hist is not None and not hist.empty and "Close" in hist.columns else pd.Series(dtype=float)
    except Exception:
        close = pd.Series(dtype=float)

    def _ret_from_close(bars):
        if len(close) < 2:
            return np.nan
        end = px if px > 0 else clean_float(close.iloc[-1], np.nan)
        base_idx = -bars - 1 if len(close) > bars else 0
        base = clean_float(close.iloc[base_idx], np.nan)
        if not finite_num(end) or not finite_num(base) or end <= 0 or base <= 0:
            return np.nan
        return (end / base - 1) * 100

    day_ret = _ret_from_close(1)
    week_ret = _ret_from_close(5)
    month_ret = _ret_from_close(21)
    return {
        "구분": role,
        "확인축": label,
        "Ticker": ticker,
        "현재가": format_currency(px, ticker) if px > 0 else "-",
        "1D": pct_text(day_ret),
        "1W": pct_text(week_ret),
        "1M": pct_text(month_ret),
        "판정": judge(day_ret, week_ret, month_ret),
        "_1d": clean_float(day_ret, np.nan),
        "_1w": clean_float(week_ret, np.nan),
        "_1m": clean_float(month_ret, np.nan),
    }


@timed_call("external_data")
def build_leveraged_watch_rows(watch, *, load_quote, load_history, pct_text, judge, parallel=True):
    """Keep provider/cache policy in the callbacks; serial calls stay on the caller."""
    callbacks = dict(load_quote=load_quote, load_history=load_history,
                     pct_text=pct_text, judge=judge)
    if not parallel:
        return [_build_watch_row(entry, **callbacks) for entry in watch]

    entries = iter(watch)
    missing = object()
    first = next(entries, missing)
    if first is missing:
        return []
    second = next(entries, missing)
    if second is missing:
        return [_build_watch_row(first, **callbacks)]

    def parallel_row(entry):
        # All concurrent profile builds share these slots; serial mode bypasses them.
        with _PARALLEL_ROW_SLOTS:
            return _build_watch_row(entry, **callbacks)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [submit_with_context(executor, parallel_row, entry)
                   for entry in chain((first, second), entries)]
        return [future.result() for future in futures]


register_loaded_source(__name__, __file__)
