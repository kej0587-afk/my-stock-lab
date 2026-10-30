"""Short-lived quote reuse during an explicitly refreshed calculation."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging
import math
import time


_QUOTES = ContextVar("stock_lab_fresh_quote_batch", default=None)
_GENERATION = object()


def invalidate_prefetched_quotes():
    global _GENERATION
    _GENERATION = object()


def prefetched_quote(ticker):
    snapshot = _QUOTES.get()
    if snapshot is None or snapshot[0] is not _GENERATION:
        return None
    entry = snapshot[1].get(ticker)
    if entry is None or time.monotonic() >= entry[1]:
        return None
    return entry[0]


@contextmanager
def fresh_quote_scope(tickers, fetch_prices, *, ttl):
    """Use each batch only until its original deadline, never recache its hits.

    The caller supplies normalized domestic tickers and the existing primary
    provider. Missing/expired values continue through the original fallback.
    Context propagation is handled by submit_with_context, not global prices.
    """
    keys = list(dict.fromkeys(tickers))
    generation = _GENERATION
    entries = {}
    for start in range(0, len(keys), 50):
        batch = keys[start:start + 50]
        deadline = time.monotonic() + ttl
        try:
            values = fetch_prices(batch)
        except Exception as exc:
            logging.warning("Quote prefetch unavailable: %s", type(exc).__name__)
            continue
        if not isinstance(values, dict):
            continue
        for key in batch:
            value = values.get(key)
            if isinstance(value, bool):
                continue
            try:
                value = float(value)
            except (ValueError, TypeError):
                continue
            if math.isfinite(value) and value > 0:
                entries[key] = (value, deadline)
    token = _QUOTES.set((generation, entries))
    try:
        yield
    finally:
        _QUOTES.reset(token)
