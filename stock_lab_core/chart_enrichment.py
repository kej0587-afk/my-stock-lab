# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# Volume classification adapted from Volume Signal, modified by mossst,
# based on "MarketSmith Volumes" (c) Fred6724:
# https://www.tradingview.com/script/DRT8QZSp/
"""Pure chart annotations; no fetching, Streamlit, or decision-score changes.

Volume signals use only the current and earlier bars. Profiles describe the
supplied window, so slice OHLCV to the historical cutoff before backtesting.
Financial rows are independently implemented from existing metadata, without
the unlicensed reference dashboard's scoring formulas or presentation code.
"""

from __future__ import annotations

from collections.abc import Mapping
from operator import index as integer_index

import numpy as np
import pandas as pd

from stock_lab_core.financial_score import optional_float, unwrap_snapshot_data


__all__ = [
    "build_volume_signal_series",
    "build_volume_signal_tail",
    "build_volume_at_price_profile",
    "build_financial_snapshot_rows",
]

_TIMEFRAMES = {"daily": (50, 252, 63), "weekly": (10, 52, 13), "monthly": (50, 12, 3)}
_COLORS = {
    "HVE": "#5B21B6", "HVY": "#7D3CFF", "HVQ": "#A47CFF",
    "POCKET_PIVOT": "#FF4D9D", "DRY60": "#222222", "DRY20": "#3B4A8C",
    "BASE": "#D9D9DE", "UNAVAILABLE": "#94A3B8",
}
PROFILE_ESTIMATION_NOTE = (
    "Estimated volume at price from daily OHLCV: each bar's volume is spread "
    "uniformly over its low-high range. This is not actual traded volume at "
    "each price, an order book, or evidence of resting buy/sell orders."
)


def _positive_int(value, name: str) -> int:
    try:
        result = integer_index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if isinstance(value, (bool, np.bool_)) or result < 1:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _source_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        raise TypeError("OHLCV must be a pandas DataFrame")
    if not df.index.is_monotonic_increasing or not df.index.is_unique:
        raise ValueError("OHLCV index must be chronological and unique")
    if not df.columns.is_unique:
        raise ValueError("OHLCV columns must be unique")
    return df


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce").astype(float).replace([np.inf, -np.inf], np.nan)


def build_volume_signal_series(
    df: pd.DataFrame | None,
    *,
    timeframe: str = "daily",
    ma_length: int | None = None,
    ud_length: int = 50,
    pocket_lookback: int = 10,
    power_mult: float = 2.0,
    high_mult: float = 1.5,
    dry_mult: float = 0.5,
    dry_short: int = 20,
    dry_long: int = 60,
) -> pd.DataFrame:
    """Return index-aligned volume, signal, color, RVOL and U/D columns.

    Priority: HVE > HVY > HVQ > POCKET_PIVOT > POWER > HIGH > DRY60 >
    DRY20 > BASE. HVE means a record in *loaded* history, through that bar;
    equal records count. Rolling extrema use available history. MA and U/D
    require complete windows; missing/negative volume is never replaced by 0.
    RVOL = volume / current-inclusive SMA, buzz_pct = (RVOL - 1) * 100.

    Direction compares the previous close, never the open. Like the source,
    a flat close can qualify as a pocket pivot, but contributes to neither
    side of the strictly-up/strictly-down U/D ratio. Zero down volume yields
    a missing ratio, not infinity. DRY60/20 names denote long/short windows
    (defaults 60/20); these bar-count windows are not rescaled by timeframe.
    """
    if timeframe not in _TIMEFRAMES:
        raise ValueError("timeframe must be daily, weekly, or monthly")
    default_ma, year_length, quarter_length = _TIMEFRAMES[timeframe]
    ma_length = _positive_int(default_ma if ma_length is None else ma_length, "ma_length")
    ud_length = _positive_int(ud_length, "ud_length")
    pocket_lookback = _positive_int(pocket_lookback, "pocket_lookback")
    dry_short = _positive_int(dry_short, "dry_short")
    dry_long = max(dry_short, _positive_int(dry_long, "dry_long"))
    if not (np.isfinite(high_mult) and np.isfinite(power_mult) and 1 <= high_mult <= power_mult):
        raise ValueError("require 1 <= high_mult <= power_mult, both finite")
    if not np.isfinite(dry_mult) or not 0 < dry_mult <= 1:
        raise ValueError("dry_mult must be finite and in (0, 1]")

    source = _source_frame(df)
    close = _column(source, "Close").where(lambda s: s > 0)
    volume = _column(source, "Volume").where(lambda s: s >= 0)
    previous = close.shift(1)
    known_direction = close.notna() & previous.notna()
    up = known_direction & (close > previous)
    down = known_direction & (close < previous)
    flat = known_direction & (close == previous)
    valid = volume.notna() & close.notna()
    ma = volume.rolling(ma_length, min_periods=ma_length).mean()
    rvol = volume / ma.where(ma > 0)
    up_volume = volume.where(up, 0.0).where(valid)
    down_volume = volume.where(down, 0.0).where(valid)
    up_sum = up_volume.rolling(ud_length, min_periods=ud_length).sum()
    down_sum = down_volume.rolling(ud_length, min_periods=ud_length).sum()
    prior_down_max = down_volume.shift(1).rolling(pocket_lookback, min_periods=1).max()
    positive = valid & (volume > 0)
    dry = valid & (ma > 0) & (volume <= ma * dry_mult)
    conditions = {
        "HVE": positive & volume.eq(volume.cummax()),
        "HVY": positive & volume.eq(volume.rolling(year_length, min_periods=1).max()),
        "HVQ": positive & volume.eq(volume.rolling(quarter_length, min_periods=1).max()),
        "POCKET_PIVOT": positive & (up | flat) & (volume > prior_down_max),
        "POWER": valid & (ma > 0) & (volume >= ma * power_mult),
        "HIGH": valid & (ma > 0) & (volume >= ma * high_mult),
        "DRY60": dry & volume.eq(volume.rolling(dry_long, min_periods=1).min()),
        "DRY20": dry & volume.eq(volume.rolling(dry_short, min_periods=1).min()),
    }
    result = pd.DataFrame({
        "volume": volume, "volume_ma": ma, "rvol": rvol,
        "buzz_pct": (rvol - 1.0) * 100.0,
        "direction": np.select([up, down, flat], ["up", "down", "flat"], default="unknown"),
        "up_volume": up_volume, "down_volume": down_volume,
        "up_volume_sum": up_sum, "down_volume_sum": down_sum,
        "up_down_ratio": up_sum / down_sum.where(down_sum > 0),
    }, index=source.index)
    for name, condition in conditions.items():
        result[f"is_{name.lower()}"] = condition
    result["signal"] = np.select(
        [~valid, *conditions.values()], ["UNAVAILABLE", *conditions.keys()], default="BASE",
    )
    result["color"] = result["signal"].map(_COLORS)
    for name, up_color, down_color in [
        ("POWER", "#7CC4BF", "#FFB08A"), ("HIGH", "#B5E2DF", "#FFD2BD"),
    ]:
        mask = result["signal"].eq(name)
        result.loc[mask, "color"] = np.where((up | flat)[mask], up_color, down_color)
    result.attrs.update(timeframe=timeframe, ma_length=ma_length, year_length=year_length,
                        quarter_length=quarter_length, dry_short=dry_short, dry_long=dry_long)
    return result


def build_volume_signal_tail(df: pd.DataFrame | None, *, bars: int = 20, **kwargs) -> pd.DataFrame:
    """Compute on full history, then select the final bars for chart labels/UI."""
    bars = _positive_int(bars, "bars")
    return build_volume_signal_series(df, **kwargs).tail(bars).copy()


def _hvn_indices(volumes: np.ndarray, limit: int, min_ratio: float) -> list[int]:
    peaks = []
    start = 0
    while start < len(volumes):
        stop = start + 1
        while stop < len(volumes) and volumes[stop] == volumes[start]:
            stop += 1
        left = volumes[start - 1] if start else -1.0
        right = volumes[stop] if stop < len(volumes) else -1.0
        if volumes[start] > 0 and volumes[start] > left and volumes[start] > right:
            if volumes[start] >= volumes.max() * min_ratio:
                peaks.append((start + stop - 1) // 2)
        start = stop
    return sorted(peaks, key=lambda i: (-volumes[i], i))[:limit]


def build_volume_at_price_profile(
    df: pd.DataFrame | None,
    *,
    lookback: int = 300,
    bins: int = 31,
    value_area: float = 0.70,
    hvn_count: int = 3,
    hvn_min_ratio: float = 0.5,
) -> dict:
    """Estimate daily volume at price while conserving every usable bar's volume.

    Allocate volume by each bin's overlap with [Low, High]. A zero-range bar
    goes to one bin. POC ties choose the lower bin. Value area grows from POC
    toward the larger adjacent volume (lower on ties), until the target share
    is covered. HVNs are local maxima; a plateau is one node at its midpoint.
    Missing/invalid OHLCV and zero volume are excluded, never unit-weighted.
    """
    lookback = _positive_int(lookback, "lookback")
    bins = _positive_int(bins, "bins")
    hvn_count = _positive_int(hvn_count, "hvn_count")
    if bins > 500:
        raise ValueError("bins must be <= 500")
    if not np.isfinite(value_area) or not 0 < value_area <= 1:
        raise ValueError("value_area must be in (0, 1]")
    if not np.isfinite(hvn_min_ratio) or not 0 <= hvn_min_ratio <= 1:
        raise ValueError("hvn_min_ratio must be in [0, 1]")
    source = _source_frame(df).tail(lookback)
    data = pd.DataFrame({name: _column(source, name) for name in ["Low", "High", "Close", "Volume"]})
    mask = (data.notna().all(axis=1) & (data.Low > 0) & (data.High >= data.Low)
            & (data.Close >= data.Low) & (data.Close <= data.High) & (data.Volume > 0))
    usable = data.loc[mask]
    result = {
        "ok": False, "reason": "No usable positive-volume OHLCV bars", "rows": [],
        "poc": None, "value_area_low": None, "value_area_high": None,
        "value_area_fraction": None, "value_area_target": value_area, "hvn_levels": [],
        "total_volume": 0.0, "bars_used": len(usable), "bars_excluded": len(source) - len(usable),
        "estimated": True, "method": "uniform_low_high_overlap",
        "note": PROFILE_ESTIMATION_NOTE,
    }
    if usable.empty:
        return result
    low, high = float(usable.Low.min()), float(usable.High.max())
    if low == high:
        edges = np.array([low, high])
    else:
        edges = np.linspace(low, high, bins + 1)
    volumes = np.zeros(len(edges) - 1, dtype=float)
    for bar in usable.itertuples(index=False):
        if bar.Low == bar.High:
            pos = int(np.clip(np.searchsorted(edges, bar.Close, side="right") - 1, 0, len(volumes) - 1))
            volumes[pos] += bar.Volume
        else:
            overlap = np.maximum(0.0, np.minimum(edges[1:], bar.High) - np.maximum(edges[:-1], bar.Low))
            volumes += bar.Volume * (overlap / overlap.sum())
    total = float(volumes.sum())
    if not np.isfinite(total) or total <= 0:
        result["reason"] = "Profile volume is not finite and positive"
        return result
    poc_pos = int(np.argmax(volumes))
    va_low = va_high = poc_pos
    covered = volumes[poc_pos]
    while covered < total * value_area and (va_low > 0 or va_high < len(volumes) - 1):
        left = volumes[va_low - 1] if va_low > 0 else -1.0
        right = volumes[va_high + 1] if va_high < len(volumes) - 1 else -1.0
        if left >= right:
            va_low -= 1
            covered += volumes[va_low]
        else:
            va_high += 1
            covered += volumes[va_high]
    rows = [{
        "low": float(edges[i]), "high": float(edges[i + 1]),
        "mid": float(edges[i] + (edges[i + 1] - edges[i]) / 2),
        "volume": float(volume), "fraction": float(volume / total),
        "intensity": float(volume / volumes[poc_pos]), "in_value_area": va_low <= i <= va_high,
    } for i, volume in enumerate(volumes)]
    result.update(
        ok=True, reason="", rows=rows, poc=dict(rows[poc_pos]),
        value_area_low=float(edges[va_low]), value_area_high=float(edges[va_high + 1]),
        value_area_fraction=float(covered / total), total_volume=total,
        hvn_levels=[dict(rows[i]) for i in _hvn_indices(volumes, hvn_count, hvn_min_ratio)],
    )
    return result


def build_financial_snapshot_rows(info: Mapping | None, *, is_etf: bool = False) -> list[dict]:
    """Return available metadata rows only; no network, score, or missing-as-zero.

    Accept raw info or the existing {'data': info} snapshot wrapper. Values
    retain provider meaning; explicit fractional ratio keys are converted to
    percentage points; explicit percent strings already use those units.
    Monetary rows carry quote or financial currency. ETF,
    ETN and mutual-fund metadata automatically suppress corporate rows.
    Provider-specific dividendYield/debtToEquity units are deliberately not
    guessed. Pass already normalized info from the existing valuation path.
    """
    data = unwrap_snapshot_data(dict(info)) if isinstance(info, Mapping) else {}
    quote_type = str(data.get("quoteType") or "").upper().replace("_", "").replace(" ", "")
    fund = is_etf or quote_type in {"ETF", "ETN", "MUTUALFUND"}
    currency = str(data.get("currency") or "")
    financial_currency = str(data.get("financialCurrency") or currency)
    # Specs describe existing metadata, not a new financial scoring model.
    specs = [
        ("snapshot", "Price", ("currentPrice", "regularMarketPrice"), "currency", 1.0, currency),
        ("income", "Trailing dividend yield", ("trailingAnnualDividendYield",), "%", 100.0, ""),
    ]
    if fund:
        specs += [
            ("fund", "Total assets", ("totalAssets",), "currency", 1.0, currency),
            ("fund", "NAV", ("navPrice",), "currency", 1.0, currency),
            ("fund", "Annual expense ratio", ("annualReportExpenseRatio",), "%", 100.0, ""),
        ]
    else:
        specs += [
            ("snapshot", "Market cap", ("marketCap",), "currency", 1.0, currency),
            ("valuation", "Trailing P/E", ("trailingPE",), "x", 1.0, ""),
            ("valuation", "Forward P/E", ("forwardPE",), "x", 1.0, ""),
            ("valuation", "Price / book", ("priceToBook",), "x", 1.0, ""),
            ("valuation", "Price / sales", ("priceToSalesTrailing12Months",), "x", 1.0, ""),
            ("valuation", "EV / EBITDA", ("enterpriseToEbitda",), "x", 1.0, ""),
            ("quality", "ROE", ("returnOnEquity",), "%", 100.0, ""),
            ("quality", "ROA", ("returnOnAssets",), "%", 100.0, ""),
            ("quality", "Operating margin", ("operatingMargins",), "%", 100.0, ""),
            ("quality", "Net margin", ("profitMargins",), "%", 100.0, ""),
            ("growth", "Revenue growth", ("revenueGrowth",), "%", 100.0, ""),
            ("growth", "Earnings growth", ("earningsGrowth",), "%", 100.0, ""),
            ("health", "Current ratio", ("currentRatio",), "x", 1.0, ""),
            ("health", "Quick ratio", ("quickRatio",), "x", 1.0, ""),
            ("cashflow", "Operating cash flow", ("operatingCashflow",), "currency", 1.0, financial_currency),
            ("cashflow", "Free cash flow", ("freeCashflow",), "currency", 1.0, financial_currency),
            ("income", "Payout ratio", ("payoutRatio",), "%", 100.0, ""),
        ]
    rows = []
    for group, label, keys, unit, scale, row_currency in specs:
        for key in keys:
            raw = data.get(key)
            if isinstance(raw, (bool, np.bool_)):
                continue
            percent_text = isinstance(raw, str) and "%" in raw
            if percent_text and unit != "%":
                continue
            multiplier = 1.0 if percent_text else scale
            value = optional_float(raw)
            if value is None or not np.isfinite(value * multiplier):
                continue
            rows.append({"key": key, "group": group, "label": label,
                         "value": value * multiplier, "unit": unit, "currency": row_currency})
            break
    return rows
