"""Offline A/B benchmark of the two print-plan summaries, not today's full queue.

Run with: python scripts/benchmark_print_report.py --rows 85 --repeat 5
Both paths use identical synthetic inputs and the retained production multiplier.
No quote requests, persistent caches, account writes, or orders are involved.
"""

import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.asset_classifier import resolve_effective_investment_bucket
from stock_lab_core.formatters import clean_bool, is_kr_listed, normalize_bucket, report_num, sanitize_ticker_value
from stock_lab_core.print_report_data import active_plan_rows, build_monthly_plan_report, build_total_needed_shares_report


BASE = "455fc34c3ecf44faffdd9ef1313423ccc14f5c73"


def benchmark(rows=85, repeat=5, iterations=50):
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    tree = ast.parse(source)
    report = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_print_report_v2")
    names = {"_active_plan_rows", "_build_monthly_plan_report", "_build_total_needed_shares_report"}
    nodes = [deepcopy(n) for n in report.body if isinstance(n, ast.FunctionDef) and n.name in names]
    nodes += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_rebcalc_signal_multiplier"]
    frame = pd.DataFrame([{"자산명": f"Fixture {i}", "티커": f"{i + 1:06}.KS", "bucket": "core",
        "asset_class": "kr_stock", "운용대상": True, "현재가": 10000. + i * 100,
        "매입가": 11000., "보유량": float(i % 3), "목표비중": 100. / rows,
        "기술적타점": "분할 매수"} for i in range(rows)])
    state = {"rebcalc_monthly": 750000., "rebcalc_carryover": 10000.,
        "rebcalc_accum": {}, "rebcalc_redistribute": True, "_ticker_signal_cache": {}}
    summary = {"current_asset": 10000000.}
    namespace = dict(globals(), _num=report_num, holdings_table=frame, portfolio_summary=summary,
        st=SimpleNamespace(session_state=state), usdkrw=1400., sanitize_asset_name=lambda name, ticker: name)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<baseline-plan>", "exec"), namespace)

    def before():
        return namespace["_build_monthly_plan_report"](), namespace["_build_total_needed_shares_report"]()

    def after():
        active = active_plan_rows(frame)
        callbacks = dict(sanitize_asset_name=namespace["sanitize_asset_name"],
            signal_multiplier=namespace["_rebcalc_signal_multiplier"])
        return (build_monthly_plan_report(active, state, 1400., **callbacks),
            build_total_needed_shares_report(active, state, 1400., summary, **callbacks))

    original = before()
    updated = after()
    pd.testing.assert_frame_equal(original[0][0], updated[0][0], check_exact=True)
    assert original[0][1] == updated[0][1]
    pd.testing.assert_frame_equal(original[1], updated[1], check_exact=True)
    before_samples, after_samples = [], []
    for repetition in range(repeat):
        # Alternate order to reduce warm-up/order bias; initialization is outside timing.
        pairs = [(before, before_samples), (after, after_samples)]
        for fn, samples in pairs if repetition % 2 == 0 else reversed(pairs):
            started = perf_counter()
            for _ in range(iterations):
                fn()
            samples.append((perf_counter() - started) * 1000 / iterations)
    old_mean, new_mean = statistics.mean(before_samples), statistics.mean(after_samples)
    return {"baseline": BASE, "scope": "offline two-table calculation only", "rows": rows,
        "repeat": repeat, "iterations_per_repeat": iterations, "outputs_exact": True,
        "preparations_per_render": {"before": 2, "after": 1},
        "before_ms": before_samples, "after_ms": after_samples,
        "before_mean_ms": old_mean, "after_mean_ms": new_mean,
        "reduction_pct": (old_mean - new_mean) / old_mean * 100}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=85)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=50)
    args = parser.parse_args()
    if min(args.rows, args.repeat, args.iterations) <= 0:
        parser.error("rows, repeat and iterations must be positive")
    print(json.dumps(benchmark(args.rows, args.repeat, args.iterations), indent=2))
