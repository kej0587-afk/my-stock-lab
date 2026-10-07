"""Date-aligned relative strength and sector-classification provenance."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import pandas as pd

from stock_lab_core.formatters import normalize_ticker


def _dated_closes(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "Close" not in frame:
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame["Close"], errors="coerce").copy()
    dates = pd.to_datetime(frame.index, errors="coerce")
    close.index = dates.tz_localize(None).normalize()
    close = close[close.index.notna() & close.gt(0)]
    return close.groupby(level=0).last().sort_index()


def compute_relative_strength(stock: pd.DataFrame, benchmark: pd.DataFrame, lookback: int) -> dict:
    """Compare returns on the same sessions without treating missing data as neutral."""
    result = {"score": 0, "label": "가격없음", "change_pct": None, "asof": "", "sessions": 0}
    asset = _dated_closes(stock)
    base = _dated_closes(benchmark)
    if asset.empty or base.empty:
        return result
    paired = pd.concat([asset.rename("asset"), base.rename("base")], axis=1, join="inner").dropna()
    result["sessions"] = len(paired)
    if len(paired) < lookback + 1:
        result["label"] = "이력부족"
        return result
    result["asof"] = paired.index[-1].strftime("%Y-%m-%d")
    if abs((asset.index[-1] - base.index[-1]).days) > 7:
        result["label"] = "기준일차이"
        return result
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
