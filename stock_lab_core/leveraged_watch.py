"""Build leveraged-product proxy rows with bounded, context-aware overlap."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import chain
from threading import BoundedSemaphore, RLock

import numpy as np
import pandas as pd

from stock_lab_core.formatters import (
    clean_float,
    finite_num,
    format_currency,
    sanitize_ticker_value,
)
from stock_lab_core.performance import count_event, measure, submit_with_context, timed_call
from stock_lab_core.report_build import register_loaded_source


_PARALLEL_ROW_SLOTS = BoundedSemaphore(2)
_BATCH_HISTORY = ContextVar("leveraged_watch_batch_history", default=None)
SESSION_COMPARISON_VERSION = "completed-session-v1"


@contextmanager
def leveraged_watch_history_scope():
    """Share successful exact-period frames only across this summary's profiles."""
    token = _BATCH_HISTORY.set((RLock(), {}, {}))
    try:
        yield
    finally:
        _BATCH_HISTORY.reset(token)


@timed_call("external_data")
def _build_watch_row(entry, *, load_quote, load_history, pct_text, judge, comparison=None):
    if comparison is not None:
        from stock_lab_core.leveraged_comparison import completed_comparison_row
        try:
            with measure("prices", "leveraged_watch_history_6mo"):
                history = load_history(sanitize_ticker_value(entry[0]), "6mo")
        except Exception:
            history = None
        return completed_comparison_row(entry, history, context=comparison,
                                        pct_text=pct_text, judge=judge)
    t, role, label = entry
    ticker = sanitize_ticker_value(t)
    with measure("prices", "leveraged_watch_quote"):
        px = clean_float(load_quote(ticker), 0.0)
    try:
        with measure("prices", "leveraged_watch_history_6mo"):
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
def build_leveraged_watch_rows(watch, *, load_quote, load_history, pct_text, judge, parallel=True,
                               comparison_profile="", comparison_ticker=""):
    """Keep provider/cache policy in the callbacks; serial calls stay on the caller."""
    callbacks = dict(load_quote=load_quote, load_history=load_history,
                     pct_text=pct_text, judge=judge)
    if comparison_profile:
        from stock_lab_core.leveraged_comparison import comparison_context, comparison_entries, exact_profile
        profile = exact_profile(comparison_profile, comparison_ticker)
        watch = comparison_entries(watch, profile)
        callbacks["comparison"] = comparison_context(profile)
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


@timed_call("external_data")
def build_leveraged_watch_rows_batched(watch, *, load_quote, load_history, load_batch, pct_text, judge,
                                      comparison_profile="", comparison_ticker=""):
    """Batch exact 6mo histories only inside a non-forced summary scope.

    The existing batch provider excludes KR symbols. Failed/missing symbols use
    the original loader. Frames never seed the general price cache: only Close
    is consumed here, and Yahoo batch Adj Close may differ from single requests.
    Forced refresh must continue through build_leveraged_watch_rows on its caller.
    """
    state = _BATCH_HISTORY.get()
    if state is None:
        return build_leveraged_watch_rows(watch, load_quote=load_quote, load_history=load_history,
                                          pct_text=pct_text, judge=judge, comparison_profile=comparison_profile,
                                          comparison_ticker=comparison_ticker)
    entries = list(watch)
    if comparison_profile:
        from stock_lab_core.leveraged_comparison import comparison_entries, exact_profile
        entries = comparison_entries(entries, exact_profile(comparison_profile, comparison_ticker))
    symbols = tuple(sorted({sanitize_ticker_value(entry[0]) for entry in entries
                            if sanitize_ticker_value(entry[0])}))
    frames = {}
    if len(symbols) > 1:
        lock, memo, providers = state
        # Avoid duplicate concurrent profile misses. The provider already uses
        # one global Yahoo lock; row workers retain their existing two slots.
        with measure("prices", "leveraged_watch_batch_wait"), lock:
            provider_id = id(load_batch)
            providers[provider_id] = load_batch
            missing = tuple(t for t in symbols if (provider_id, t) not in memo)
            count_event("leveraged_watch.shared_frame_hit", len(symbols) - len(missing))
            if missing:
                try:
                    with measure("prices", "leveraged_watch_batch_6mo"):
                        count_event("leveraged_watch.batch_lookup")
                        fetched = load_batch(missing, "6mo")
                    if isinstance(fetched, dict):
                        for ticker in missing:
                            frame = fetched.get(ticker)
                            if isinstance(frame, pd.DataFrame) and not frame.empty and "Close" in frame:
                                memo[provider_id, ticker] = frame.copy(deep=True)
                except Exception:
                    count_event("leveraged_watch.batch_exception")
            frames = {t: memo[provider_id, t] for t in symbols if (provider_id, t) in memo}

    def exact_history(ticker, period):
        frame = frames.get(ticker) if period == "6mo" else None
        if isinstance(frame, pd.DataFrame) and not frame.empty and "Close" in frame:
            count_event("leveraged_watch.batch_frame_hit")
            return frame.copy(deep=True)
        count_event("leveraged_watch.original_history_fallback")
        return load_history(ticker, period)

    return build_leveraged_watch_rows(
        entries, load_quote=load_quote, load_history=exact_history,
        pct_text=pct_text, judge=judge, parallel=True,
        comparison_profile=comparison_profile,
        comparison_ticker=comparison_ticker,
    )


register_loaded_source(__name__, __file__)
