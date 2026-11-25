"""Benchmark market regime used by regime-limited decision policies (C-1 step 2, 2026-11-25).

Same definition as the C-1/C-1b comparison: benchmark close vs its 200-day average and the
20-day change of that average. US stocks use SPY, Korean stocks use KOSPI (^KS11).
  상승: close > MA200 and MA200 rising over 20 trading days
  하락: close < MA200 and MA200 falling over 20 trading days
  횡보: anything else with enough history
  미확인: fewer than 220 closes (never treated as 상승)
"""

from __future__ import annotations

import math
from typing import Callable

import pandas as pd

from stock_lab_core.formatters import is_kr_listed

REGIME_UP, REGIME_SIDEWAYS, REGIME_DOWN, REGIME_UNKNOWN = "상승", "횡보", "하락", "미확인"
MIN_CLOSES = 220
MA_DAYS, SLOPE_DAYS = 200, 20


def regime_benchmark(ticker: str) -> str:
    return "^KS11" if is_kr_listed(str(ticker or "")) else "SPY"


def classify_regime(close) -> str:
    if close is None:
        return REGIME_UNKNOWN
    series = pd.to_numeric(pd.Series(close), errors="coerce").dropna()
    series = series[series > 0]
    if len(series) < MIN_CLOSES:
        return REGIME_UNKNOWN
    ma = series.rolling(MA_DAYS).mean()
    last, ma_now, ma_prev = float(series.iloc[-1]), float(ma.iloc[-1]), float(ma.iloc[-1 - SLOPE_DAYS])
    if not all(math.isfinite(v) for v in (last, ma_now, ma_prev)):
        return REGIME_UNKNOWN
    slope = ma_now - ma_prev
    if last > ma_now and slope > 0:
        return REGIME_UP
    if last < ma_now and slope < 0:
        return REGIME_DOWN
    return REGIME_SIDEWAYS


_PROVIDER: dict[str, Callable[[str], str] | None] = {"fn": None}


def register_regime_provider(fn: Callable[[str], str] | None) -> None:
    """The app registers a ticker -> regime lookup that reads benchmark prices."""
    _PROVIDER["fn"] = fn


def regime_for(ticker: str, decision: dict | None = None) -> str:
    """Regime attached to the decision when present, else from the registered provider."""
    attached = str((decision or {}).get("market_regime", "") or "").strip()
    if attached:
        return attached
    fn = _PROVIDER["fn"]
    if fn is None:
        return REGIME_UNKNOWN
    try:
        return str(fn(ticker) or REGIME_UNKNOWN)
    except Exception:
        return REGIME_UNKNOWN
