"""Opt-in live comparison of the cold domestic quote stage, not the full app.

Run: py -3.11 -X utf8 -m tests.benchmark_fresh_quotes
Same public symbols/provider/6 workers/empty result cache, three paired runs.
Quote changes between requests are reported, never silently treated as equal.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
from statistics import mean
from time import perf_counter

from stock_lab_core import prices
from stock_lab_core.performance import submit_with_context


TICKERS = [
    "005930.KS", "000660.KS", "035420.KS", "005380.KS",
    "051910.KS", "006400.KS", "000270.KS", "012330.KS",
    "069500.KS", "379810.KS", "379800.KS", "396500.KS",
]


def main():
    measurements = {"before": [], "after": []}
    comparisons = []
    for repeat in range(3):
        results = {}
        for mode in (("before", "after") if repeat % 2 == 0 else ("after", "before")):
            prices.clear_latest_price_cache()
            started = perf_counter()
            scope = prices.fresh_kr_quote_scope(TICKERS) if mode == "after" else nullcontext()
            with scope, ThreadPoolExecutor(max_workers=6) as pool:
                futures = {t: submit_with_context(pool, prices.load_latest_price, t) for t in TICKERS}
                results[mode] = {t: f.result() for t, f in futures.items()}
            elapsed = perf_counter() - started
            measurements[mode].append(elapsed)
            print(json.dumps({"repeat": repeat + 1, "mode": mode, "elapsed": elapsed,
                              "valid_quotes": sum(v > 0 for v in results[mode].values())}), flush=True)
        comparisons.append([t for t in TICKERS if results["before"][t] != results["after"][t]])
    print(json.dumps({"scope": "cold domestic latest-price stage only", "symbols": len(TICKERS),
                      "runs": measurements, "mean_seconds": {m: mean(v) for m, v in measurements.items()},
                      "changed_quotes_per_pair": comparisons}), flush=True)


if __name__ == "__main__":
    main()
