"""Date-aligned relative strength and sector-classification provenance."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import pandas as pd

from stock_lab_core.formatters import normalize_ticker


def _normalize_daily_index(index) -> pd.DatetimeIndex:
    """Return a timezone-naive daily index, preserving normal daily market dates."""
    try:
        dates = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
        if dates.tz is not None:
            dates = dates.tz_localize(None)
    except Exception:
        # Mixed timezone indexes need UTC coercion; this is a fallback for rare messy inputs.
        values = pd.to_datetime(pd.Series(index), errors="coerce", utc=True)
        dates = pd.DatetimeIndex(values.dt.tz_convert(None))
    return dates.normalize()


def _select_price_column(frame: pd.DataFrame, prefer_adjusted: bool) -> str:
    columns = ("Adj Close", "Close") if prefer_adjusted else ("Close", "Adj Close")
    for column in columns:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.gt(0).any():
            return column
    return ""


def _dated_closes(frame: pd.DataFrame, *, prefer_adjusted: bool = True) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    price_column = _select_price_column(frame, prefer_adjusted)
    if not price_column:
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame[price_column], errors="coerce").copy()
    close.index = _normalize_daily_index(frame.index)
    close = close[close.index.notna() & close.gt(0)]
    close = close.groupby(level=0).last().sort_index()
    close.attrs["price_column"] = price_column
    return close


def compute_relative_strength(
    stock: pd.DataFrame,
    benchmark: pd.DataFrame,
    lookback: int,
    *,
    stale_days: int = 7,
    prefer_adjusted: bool = True,
) -> dict:
    """Compare returns on the same sessions without treating missing data as neutral."""
    try:
        lookback = int(lookback)
    except (TypeError, ValueError):
        lookback = 0
    stale_days = max(int(stale_days), 0)
    result = {
        "score": 0,
        "label": "가격없음",
        "change_pct": None,
        "asof": "",
        "start_asof": "",
        "asset_asof": "",
        "benchmark_asof": "",
        "sessions": 0,
        "lookback": lookback,
        "price_basis": "",
    }
    if lookback < 1:
        result["label"] = "이력부족"
        return result

    asset = _dated_closes(stock, prefer_adjusted=prefer_adjusted)
    base = _dated_closes(benchmark, prefer_adjusted=prefer_adjusted)
    if asset.empty or base.empty:
        return result
    result["asset_asof"] = asset.index[-1].strftime("%Y-%m-%d")
    result["benchmark_asof"] = base.index[-1].strftime("%Y-%m-%d")
    result["price_basis"] = f"{asset.attrs.get('price_column', 'Close')} / {base.attrs.get('price_column', 'Close')}"

    paired = pd.concat([asset.rename("asset"), base.rename("base")], axis=1, join="inner").dropna()
    result["sessions"] = len(paired)
    if paired.empty:
        result["label"] = "공통거래일없음"
        return result

    result["asof"] = paired.index[-1].strftime("%Y-%m-%d")
    if (
        abs((asset.index[-1] - base.index[-1]).days) > stale_days
        or abs((asset.index[-1] - paired.index[-1]).days) > stale_days
        or abs((base.index[-1] - paired.index[-1]).days) > stale_days
    ):
        result["label"] = "기준일차이"
        return result

    if len(paired) < lookback + 1:
        result["label"] = "이력부족"
        return result
    result["start_asof"] = paired.index[-lookback - 1].strftime("%Y-%m-%d")

    relative = paired["asset"] / paired["base"]
    change = (relative.iloc[-1] / relative.iloc[-lookback - 1] - 1) * 100
    result["change_pct"] = float(change)
    if change > 3:
        result.update(score=2, label="🚀강함")
    elif change < -3:
        result.update(score=0, label="🐢약함")
    else:
        result["label"] = "➖보통"
    return result


@lru_cache(maxsize=1)
def _sector_sources() -> dict:
    path = Path(__file__).parent / "data" / "sector_benchmark_sources.json"
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return {normalize_ticker(k): v for k, v in data.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def get_sector_provenance(ticker: str, benchmark: str) -> dict:
    entry = _sector_sources().get(normalize_ticker(ticker), {})
    if normalize_ticker(entry.get("benchmark", "")) != normalize_ticker(benchmark):
        return {}
    return {
        "섹터분류근거": entry.get("proxy_note", "") or entry.get("sector", ""),
        "섹터분류출처": entry.get("source_url", ""),
        "섹터검증일": entry.get("verified_on", ""),
    }
