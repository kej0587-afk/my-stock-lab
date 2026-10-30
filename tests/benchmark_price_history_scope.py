"""Network-free replay: python -m tests.benchmark_price_history_scope.

Uses real Streamlit cache layers and deterministic, injected provider frames.
The 729-call workload is synthetic, NOT the Cloud request sequence: the exported
trace has aggregate counts but no ticker/period keys or provider cache hits.
"""

import argparse
import ast
from collections import Counter
from contextlib import ExitStack
from contextvars import ContextVar
from functools import wraps
import json
from pathlib import Path
import statistics
import subprocess
from time import perf_counter

import pandas as pd

from stock_lab_core import prices
from stock_lab_core.performance import PerformanceTrace


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "9cdfe682e1c511b9621d5fa17a7085e562937f2b"
FUNCTIONS = {"price_frame_scope", "_reuse_prefetched_history", "load_price_df"}


def workload():
    symbols = [f"REPLAY{i:03d}" for i in range(95)]
    requests = []
    for symbol in symbols:
        requests.extend([(symbol, "3mo"), ("SPY", "3mo"), (symbol, "3mo"),
                         ("XLK", "3mo"), (symbol, "6mo"), ("SPY", "6mo"), ("XLK", "6mo")])
    requests.extend((symbol, "1y") for symbol in symbols[:64])
    return symbols, requests


def fixture_frame(ticker, period):
    rows = {"3mo": 64, "6mo": 130, "1y": 260}[period]
    base = float(sum(map(ord, ticker)))
    index = pd.bdate_range(end="2026-10-29", periods=rows, name="Date")
    close = pd.Series([base + i / 10 for i in range(rows)], index=index)
    frame = pd.DataFrame({"Open": close - 1, "High": close + 2, "Low": close - 2,
                          "Close": close, "Adj Close": close * .99, "Volume": 1000000}, index=index)
    frame.attrs = {"source": "injected", "ticker": ticker, "period": period}
    return frame


def implementation(source, label, counts, fixtures):
    namespace = dict(vars(prices))
    namespace["_PREFETCHED_HISTORY"] = ContextVar(label + "_prefetched", default=None)
    namespace["_HISTORY_REQUEST_MEMO"] = ContextVar(label + "_memo", default=None)

    def counted_cache(**options):
        def decorate(fn):
            cached = prices.cache_result(**options)(fn)

            @wraps(cached)
            def lookup(*args, **kwargs):
                counts["cache_boundary_calls"] += 1
                return cached(*args, **kwargs)

            return lookup
        return decorate

    def provider(ticker, period):
        counts["provider_calls"] += 1
        return fixtures[ticker, period].copy(deep=True)

    namespace["cache_result"] = counted_cache
    namespace["_fetch_yfinance_ohlcv"] = provider
    namespace["_fetch_pykrx_ohlcv"] = provider
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert {node.name for node in nodes} == FUNCTIONS
    exec(compile(ast.Module(body=nodes, type_ignores=[]), f"<{label}>", "exec"), namespace)
    return namespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("before", "after", "both"), default="both")
    args = parser.parse_args()
    sources = {
        "before": subprocess.check_output(
            ["git", "show", f"{BASELINE}:stock_lab_core/prices.py"], cwd=ROOT, encoding="utf-8"),
        "after": Path(prices.__file__).read_text(encoding="utf-8-sig"),
    }
    labels = ("before", "after") if args.version == "both" else (args.version,)
    symbols, requests = workload()
    fixtures = {key: fixture_frame(*key) for key in dict.fromkeys(requests)}
    counters = {label: Counter() for label in labels}
    scopes = {label: implementation(sources[label], label, counters[label], fixtures) for label in labels}
    results = []
    try:
        for seeded in (True, False):
            for warm in (False, True):
                samples = {label: [] for label in labels}
                for run in range(3):
                    for label in (labels if run % 2 == 0 else labels[::-1]):
                        scope, counts = scopes[label], counters[label]
                        loader = scope["load_price_df"]
                        loader.clear()
                        if warm:
                            for ticker, period in fixtures:
                                loader(ticker, period)
                        counts.clear()
                        with PerformanceTrace(), ExitStack() as stack:
                            if seeded:
                                for period in ("1y", "3mo"):
                                    frames = {ticker: frame for (ticker, p), frame in fixtures.items() if p == period}
                                    stack.enter_context(scope["price_frame_scope"](frames, period))
                            else:
                                stack.enter_context(scope["price_frame_scope"]({}, "1y"))
                            started = perf_counter()
                            actual = [loader(ticker, period) for ticker, period in requests]
                            seconds = perf_counter() - started
                        for key, frame in zip(requests, actual):
                            pd.testing.assert_frame_equal(frame, fixtures[key], check_exact=True)
                            assert frame.attrs == fixtures[key].attrs
                        expected_providers = 0 if warm else sum(not seeded or period == "6mo" for _, period in fixtures)
                        assert counts["provider_calls"] == expected_providers
                        samples[label].append({"seconds": round(seconds, 6),
                                               "cache_boundary_calls": counts["cache_boundary_calls"],
                                               "provider_calls": counts["provider_calls"]})
                results.append({"seeded_existing_scope": seeded, "warm_streamlit_cache": warm,
                                "samples": samples,
                                "mean_seconds": {label: statistics.mean(s["seconds"] for s in runs)
                                                 for label, runs in samples.items()},
                                "median_seconds": {label: statistics.median(s["seconds"] for s in runs)
                                                   for label, runs in samples.items()}})
    finally:
        for scope in scopes.values():
            scope["load_price_df"].clear()
    print(json.dumps({"scope": "synthetic local replay; no network, secrets, or Cloud speedup claim",
                      "baseline": BASELINE, "requests": len(requests), "unique_requests": len(fixtures),
                      "symbols": len(symbols), "runs_per_condition": 3,
                      "injected_latency_seconds": 0, "exact_frames_and_attrs": True,
                      "results": results}, indent=2))


if __name__ == "__main__":
    main()
