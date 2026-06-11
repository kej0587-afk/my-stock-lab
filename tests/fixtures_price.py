"""Deterministic synthetic OHLCV price data for golden-snapshot tests.

Uses a seeded RNG so the same scenario always produces byte-identical
DataFrames across runs/machines.
"""
import numpy as np
import pandas as pd

from stock_lab_core.ta_engine import build_indicators


def make_price_df(
    days: int = 260,
    start_price: float = 100.0,
    daily_drift: float = 0.0005,
    daily_vol: float = 0.012,
    seed: int = 0,
    tail_shock: float | None = None,
    tail_shock_days: int = 10,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame with technical indicator columns.

    Args:
        days: number of trading days (>=252 needed for 52w-high logic).
        daily_drift / daily_vol: mean/std of daily log-ish returns.
        seed: RNG seed -> fully reproducible output.
        tail_shock: optional total return applied across the last
            `tail_shock_days` days (e.g. -0.35 for a -35% crash tail),
            on top of the base drift/vol.
    """
    rng = np.random.default_rng(seed)
    rets = rng.normal(daily_drift, daily_vol, days)
    if tail_shock is not None:
        rets[-tail_shock_days:] += tail_shock / tail_shock_days

    close = start_price * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0.0, 0.01, days))
    low = close * (1 - rng.uniform(0.0, 0.01, days))
    open_ = close * (1 + rng.normal(0.0, 0.003, days))
    volume = rng.uniform(1_000_000, 2_000_000, days)

    idx = pd.bdate_range(end="2026-06-10", periods=days)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )
    return build_indicators(df)
