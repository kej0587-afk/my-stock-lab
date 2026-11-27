"""Read-only Yahoo snapshot and reproducible 120-minute aggregation audit."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stock_lab_core.intraday_chart import fetch_yahoo, pair_sixty_minute_bars
from stock_lab_core.intraday_chart_view import _labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "cache/unified_chart_audit")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "SOXL_60m.csv"
    if args.offline:
        frame = pd.read_csv(path, index_col=0)
        frame.index = pd.to_datetime(frame.index, utc=True).tz_convert("America/New_York")
    else:
        frame = fetch_yahoo("SOXL", "60m", "730d")
        frame.to_csv(path)
    paired = pair_sixty_minute_bars(frame)
    paired.to_csv(args.output / "SOXL_120m.csv")
    sessions = []
    for day in ("2026-11-25", "2025-11-28", "2026-07-02"):
        source = frame.loc[frame.index.strftime("%Y-%m-%d") == day]
        result = paired.loc[paired.index.strftime("%Y-%m-%d") == day]
        sessions.append({"date": day, "source_60": len(source), "result_120": len(result),
                         "starts": result.index.strftime("%H:%M").tolist(),
                         "source_volume": float(source.Volume.sum(min_count=1)),
                         "result_volume": float(result.Volume.sum(min_count=1))})
    old_x = paired.tail(1500).index.strftime("%m-%d %H:%M")
    result = {"source": "Yahoo Finance yfinance auto_adjust=True prepost=False", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "first": str(frame.index[0]), "last": str(frame.index[-1]), **paired.attrs["aggregation"],
              "sent_to_browser": min(1500, len(paired)), "old_unique_categories": len(set(old_x)),
              "new_unique_categories": len(set(_labels(paired.tail(1500).index, "120분", "US"))),
              "old_axis_range": [1259.5, 1499.5], "sessions": sessions}
    (args.output / "audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
