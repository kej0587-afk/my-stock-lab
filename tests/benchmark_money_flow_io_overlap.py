"""Measure bounded KR history / overseas batch overlap on identical inputs.

Live recording is opt-in. Replay uses saved public market frames, never accounts.
Run from the repository root with python -m tests.benchmark_money_flow_io_overlap.
"""

import argparse
import ast
import json
import logging
from pathlib import Path
import pickle
from statistics import median
import subprocess
from threading import Lock
from time import perf_counter, sleep
from unittest.mock import patch

import pandas as pd

from stock_lab_core import money_flow as flow
from stock_lab_core.performance import PerformanceTrace, measure


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "e0cb0462"
FUNCTIONS = {"_load_universe_metrics", "calculate_money_flow_df", "calculate_image_theme_flow_df"}
PREFIX = ROOT / "cache/flow_io_overlap_20261101"


def implementation(source, label):
    scope = dict(vars(flow))
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert {node.name for node in nodes} == FUNCTIONS
    for node in nodes:
        node.decorator_list = []  # Force identical full calculation, not a result-cache hit.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), f"<{label}>", "exec"), scope)
    return scope


def run(scope):
    with PerformanceTrace() as trace:
        with measure("phase", "etf_table"):
            etf = scope["calculate_money_flow_df"]()
        with measure("phase", "theme_table"):
            theme = scope["calculate_image_theme_flow_df"]("")
    return (etf, theme), trace.report()


def record_live(label):
    bundle = {"batches": {}, "histories": {}}
    lock = Lock()
    download = flow.download_money_flow_prices
    history = flow.get_money_flow_ohlc
    universe = flow.build_money_flow_universe_with_naver_rankings()
    bundle["universe"] = universe

    def get_batch(tickers):
        started = perf_counter()
        data = download(tickers)
        bundle["batches"][tuple(tickers)] = (data, perf_counter() - started)
        return data

    def get_history(data, ticker):
        started = perf_counter()
        frame = history(data, ticker)
        with lock:
            bundle["histories"][ticker] = (frame, perf_counter() - started)
        return frame

    scope = implementation((ROOT / "stock_lab_core/money_flow.py").read_text(encoding="utf-8"), label)
    scope.update(download_money_flow_prices=get_batch, get_money_flow_ohlc=get_history,
                 build_money_flow_universe_with_naver_rankings=lambda: universe)
    tables, report = run(scope)
    bundle["tables"] = tables
    PREFIX.parent.mkdir(exist_ok=True)
    PREFIX.with_name(PREFIX.name + f"_{label}_sources.pkl").write_bytes(pickle.dumps(bundle))
    PREFIX.with_name(PREFIX.name + f"_{label}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"label": label, "elapsed_seconds": report["elapsed_seconds"],
                      "phases": {row["name"]: row["total_seconds"] for row in report["functions"]
                                 if row["category"] == "phase"},
                      "rows": [len(table) for table in tables],
                      "batch_requests": len(bundle["batches"]),
                      "unique_histories": len(bundle["histories"])}, indent=2))


def replay(*, wait_scale=1.0, runs=3):
    bundle = pickle.loads(PREFIX.with_name(PREFIX.name + "_before_sources.pkl").read_bytes())
    before = subprocess.check_output(["git", "show", f"{BASELINE}:stock_lab_core/money_flow.py"],
                                     cwd=ROOT, encoding="utf-8")
    after = (ROOT / "stock_lab_core/money_flow.py").read_text(encoding="utf-8")
    results = {"before": [], "after": []}
    counts = {"before": [], "after": []}
    for run_index in range(runs):
        for label in (("before", "after") if run_index % 2 == 0 else ("after", "before")):
            counter = {"batch_requests": 0, "histories": 0}
            lock = Lock()

            def download(tickers):
                data, elapsed = bundle["batches"][tuple(tickers)]
                counter["batch_requests"] += 1
                sleep(elapsed * wait_scale)
                return data

            def history(data, ticker):
                frame, elapsed = bundle["histories"][ticker]
                with lock:
                    counter["histories"] += 1
                sleep(elapsed * wait_scale)
                return frame

            scope = implementation(before if label == "before" else after, label)
            scope.update(download_money_flow_prices=download, get_money_flow_ohlc=history,
                         build_money_flow_universe_with_naver_rankings=lambda: bundle["universe"])
            tables, report = run(scope)
            for expected, actual in zip(bundle["tables"], tables):
                pd.testing.assert_frame_equal(actual, expected, check_exact=True)
                assert actual.attrs == expected.attrs
            results[label].append(report["elapsed_seconds"])
            counts[label].append(counter)
    assert counts["before"] == counts["after"]
    summary = {"seconds": results, "median_seconds": {key: median(value) for key, value in results.items()},
               "provider_counts": counts, "exact_equal": True,
               "wait_scale": wait_scale, "runs_per_version": runs,
               "scope": "same saved public frames and recorded provider waits, not Cloud latency"}
    PREFIX.with_name(PREFIX.name + "_replay.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-live", choices=["before", "after"])
    parser.add_argument("--wait-scale", type=float, default=1.0)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.wait_scale < 0 or args.runs < 1:
        parser.error("wait scale must be nonnegative and runs must be positive")
    # Keep dependency auto-login out of this public-market-only benchmark.
    with patch.object(flow, "_AV_API_KEY", ""):
        if args.record_live:
            record_live(args.record_live)
        else:
            replay(wait_scale=args.wait_scale, runs=args.runs)


if __name__ == "__main__":
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
    main()
