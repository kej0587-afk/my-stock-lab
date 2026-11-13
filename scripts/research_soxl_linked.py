"""Reproduce the production research engine offline from exact frozen inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.soxl_trade_research import replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="cache/soxl_hour_research")
    parser.add_argument("--out", default="cache/soxl_linked_research")
    args = parser.parse_args()
    source, out = ROOT / args.source, ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((source / "fetch.json").read_text(encoding="utf-8"))
    frames = {t: pd.read_parquet(source / (t + ".parquet")) for t in ("SOXX", "SOXL")}
    now = pd.Timestamp(meta["captured_at"])
    schedule = _exchange_schedule("US", min(f.index.min() for f in frames.values()).date().isoformat(), now.date().isoformat())
    start = perf_counter()
    result = replay(frames, schedule, now)
    result["elapsed_seconds"] = perf_counter() - start
    result["captured_at"] = meta["captured_at"]
    result["hashes"] = {t: hashlib.sha256((source / (t + ".parquet")).read_bytes()).hexdigest() for t in frames}
    for policy in result["policies"]:
        pd.DataFrame(result["policies"][policy].pop("trades")).to_csv(out / (policy + ".csv"), index=False)
    (out / "summary.json").write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, default=str, ensure_ascii=True))


if __name__ == "__main__":
    main()
