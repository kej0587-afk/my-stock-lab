"""Run with python -m tests.benchmark_money_flow_cache_replay.

Compare e6a1ccff and the working tree on the same network-free workload.
UI replay failures are covered separately by test_money_flow_cache_replay.
This measures local calculation overhead, not Cloud/API speed improvement.
"""

import ast
import json
from pathlib import Path
import subprocess
from time import perf_counter

import pandas as pd
import pytest

from stock_lab_core import money_flow as flow
from stock_lab_core.performance import PerformanceTrace
from tests.test_money_flow_cache_replay import injected_payload, injected_provider


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {"_fetch_fdr_ohlc", "get_money_flow_ohlc", "_load_universe_metrics",
             "calculate_money_flow_df", "calculate_image_theme_flow_df"}


def implementation(source, label):
    scope = dict(vars(flow))
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert {node.name for node in nodes} == FUNCTIONS
    exec(compile(ast.Module(body=nodes, type_ignores=[]), f"<{label}>", "exec"), scope)
    return scope


def main():
    before_source = subprocess.check_output(
        ["git", "show", "e6a1ccff:stock_lab_core/money_flow.py"], cwd=ROOT, encoding="utf-8")
    after_source = (ROOT / "stock_lab_core/money_flow.py").read_text(encoding="utf-8")
    timings = {"before": [], "after": []}
    outputs = {"before": [], "after": []}
    provider_counts = {"before": [], "after": []}
    with pytest.MonkeyPatch.context() as patch, injected_provider(patch) as (calls, _):
        implementations = {"before": implementation(before_source, "baseline"),
                           "after": implementation(after_source, "working-tree")}
        quote = injected_payload()["chart"]["result"][0]
        frame = pd.DataFrame(quote["indicators"]["quote"][0],
                             index=pd.to_datetime(quote["timestamp"], unit="s"))
        frame.columns = frame.columns.str.capitalize()
        tickers = [f"{i:06d}.KS" for i in range(10)] + [f"{4000+i}.T" for i in range(10)]
        universe = [{"ticker": ticker, "name": f"member-{i}", "테마": str(i % 3),
                     "하위테마": str(i % 5), "구분": "test", "섹터": str(i % 4),
                     "랭킹보조점수": float(i % 2)} for i, ticker in enumerate(tickers * 2)]
        for scope in implementations.values():
            scope["IMAGE_THEME_UNIVERSE"] = universe
            scope["build_money_flow_universe_with_naver_rankings"] = lambda: universe
            scope["load_kr_flow_history"] = lambda ticker: frame.copy(deep=True)
        for run in range(3):
            for label in (("before", "after") if run % 2 == 0 else ("after", "before")):
                scope = implementations[label]
                for name in ("_fetch_fdr_ohlc", "calculate_money_flow_df", "calculate_image_theme_flow_df"):
                    scope[name].clear()
                calls.clear()
                with PerformanceTrace():  # No UI observer: the baseline can complete.
                    start = perf_counter()
                    tables = (scope["calculate_money_flow_df"](),
                              scope["calculate_image_theme_flow_df"](""),
                              scope["calculate_image_theme_flow_df"]("1"))
                    timings[label].append(round(perf_counter() - start, 6))
                outputs[label].append(tables)
                provider_counts[label].append(len(calls))
        for before, after in zip(outputs["before"], outputs["after"]):
            for expected, actual in zip(before, after):
                pd.testing.assert_frame_equal(actual, expected, check_exact=True)
                assert actual.attrs == expected.attrs
        assert provider_counts["before"] == provider_counts["after"] == [10, 10, 10]
        for scope in implementations.values():
            for name in ("_fetch_fdr_ohlc", "calculate_money_flow_df", "calculate_image_theme_flow_df"):
                scope[name].clear()
    print(json.dumps({"seconds": timings, "provider_calls": provider_counts,
                      "exact_equal": True, "runs_per_version": 3,
                      "scope": "injected local workload; no Cloud speedup claim"}, indent=2))


if __name__ == "__main__":
    main()
