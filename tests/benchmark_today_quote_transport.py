"""python -m tests.benchmark_today_quote_transport

Three paired offline transport replays against the pre-change commit.
The supplied diagnostics contain counts, not symbols or response bodies.
Inputs are therefore synthetic: 69 US quotes (8 held, 12 rotation, 49 watch),
10 KR clusters, 6 workers, empty quote caches, fixed provider timestamps,
generated gzip HTML/JSON, no network and no simulated network delay.
This measures local replay overhead, NOT live end-to-end latency.
"""

import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
from statistics import mean
from time import perf_counter

import pandas as pd
import pytest

from stock_lab_core import kr_sector_snapshot as kr, prices
from stock_lab_core.performance import PerformanceTrace, submit_with_context
from tests.test_today_quote_performance import (
    BASELINE, app_context, cluster_fixture, offline, source,
)


def baseline_prices():
    names = {"_fetch_yahoo_overnight_page_price", "_load_latest_price_cached", "load_latest_price"}
    nodes = [node for node in ast.parse(source("stock_lab_core/prices.py", True)).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    env = dict(vars(prices))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<baseline-prices>", "exec"), env)
    return env


def main():
    results = {"us_quotes": [], "kr_render": []}
    old = baseline_prices()
    current_overnight = prices._fetch_yahoo_overnight_page_price
    env = app_context()
    held = ["H" + chr(65 + i) for i in range(8)]
    rotation = list(dict.fromkeys(t for members in env["SECTOR_CLUSTERS_US"].values() for t in members))[:12]
    watch = ["W" + chr(65 + i // 26) + chr(65 + i % 26) for i in range(49)]
    tickers = held + rotation + watch
    env["holdings_table"] = pd.DataFrame({"티커": held, "보유량": 1.0})
    allowed = env["_today_queue_overnight_tickers"]()
    with pytest.MonkeyPatch.context() as patch:
        generator = offline.__wrapped__(patch)
        transport = next(generator)
        # Approximate the supplied 66,821,089 decoded bytes / 69 HTML responses.
        # Encoding is prepared outside the timer. Padding is synthetic/compressible.
        transport.html_bytes = 968422
        transport.prepare_html(tickers)
        names, snapshot = cluster_fixture(patch)
        try:
            for repeat in range(1, 4):
                us_run, kr_run = {"run": repeat}, {"run": repeat}
                outputs, snapshots = {}, {}
                for label in (("before", "after") if repeat % 2 else ("after", "before")):
                    before = label == "before"
                    prices.clear_latest_price_cache()
                    old["_load_latest_price_cached"].clear()
                    transport.calls.clear()
                    patch.setattr(prices, "_fetch_yahoo_overnight_page_price",
                                  old["_fetch_yahoo_overnight_page_price"] if before else current_overnight)
                    loader = old["load_latest_price"] if before else prices.load_latest_price
                    with PerformanceTrace() as trace:
                        start = perf_counter()
                        with (nullcontext() if before else prices.overnight_quote_scope(allowed)):
                            with ThreadPoolExecutor(max_workers=6) as pool:
                                futures = [submit_with_context(pool, loader, ticker) for ticker in tickers]
                                outputs[label] = [future.result() for future in futures]
                        elapsed = perf_counter() - start
                    events = trace.report()["transport_events"]
                    us_run[label] = {"seconds": round(elapsed, 6), "transport_events": events}
                    assert events.get("yahoo_overnight.request", 0) == (69 if before else 20)
                    assert events.get("yahoo_chart.request", 0) == (0 if before else 49)

                    prices.clear_latest_price_cache()
                    transport.calls.clear()
                    render = app_context(before)
                    with PerformanceTrace() as trace:
                        start = perf_counter()
                        with kr.kr_cluster_snapshot_scope(owner_scope="benchmark"):
                            if not before:
                                render["_preload_today_queue_kr_context"](snapshot)
                            snapshots[label] = [render["_get_market_cluster_snapshot_cached"]("KOSPI", n, n) for n in names]
                        elapsed = perf_counter() - start
                    events = trace.report()["transport_events"]
                    kr_run[label] = {"seconds": round(elapsed, 6), "transport_events": events}
                    assert events["naver_bulk.request"] == (10 if before else 1)
                assert outputs["before"] == outputs["after"] == [123.45] * 69
                assert snapshots["before"] == snapshots["after"]
                results["us_quotes"].append(us_run)
                results["kr_render"].append(kr_run)
        finally:
            next(generator, None)
            old["_load_latest_price_cached"].clear()
    print(json.dumps({
        "baseline": BASELINE, "offline": True, "synthetic_provider_payloads": True,
        "live_latency_claim": False, "runs_per_version": 3, "workers_us": 6,
        "cache_condition": "empty quote caches before each variant; same preloaded local frames",
        "network_delay_ms": 0, "decoded_html_bytes_per_response": transport.html_bytes,
        "equal_fixture_prices_and_kr_snapshots": True, "runs": results,
        "mean_seconds": {scenario: {label: mean(run[label]["seconds"] for run in runs)
                                   for label in ("before", "after")}
                         for scenario, runs in results.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
