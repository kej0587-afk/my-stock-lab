"""Offline A/B timing for the monthly calculator, excluding UI, DB and price IO.

Run: python scripts/benchmark_monthly_rebalance.py --rows 85 --repeat 5
The retained baseline supplies the original calculation and signal multiplier.
"""

import argparse
import ast
from copy import deepcopy
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.asset_classifier import is_known_etf_ticker, resolve_effective_investment_bucket
from stock_lab_core.formatters import clean_bool, clean_float, is_kr_listed, normalize_bucket
from stock_lab_core.monthly_rebalance import prepare_rebalance_holdings, build_rebalance_plan


BASE = "8d6ee440f4fe2386fc8c218ccbabf165b944b795"


def benchmark(rows=85, repeat=5, iterations=50):
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    tree = ast.parse(source)
    original = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "render_monthly_rebalancing_calculator")
    body = next(n for n in original.body if isinstance(n, ast.With)).body
    statements = [deepcopy(n) for n in body if 69 <= n.lineno - original.lineno <= 74
                  or n.lineno - original.lineno == 80 or 103 <= n.lineno - original.lineno <= 265]
    baseline = ast.parse("def baseline():\n    pass").body[0]
    baseline.body = statements + [ast.parse("return calc_rows").body[0]]
    multiplier = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_rebcalc_signal_multiplier")
    frame = pd.DataFrame([{"자산명": f"Fixture {i}", "티커": f"{i + 1:06}.KS", "bucket": "core",
        "asset_class": "kr_stock", "운용대상": True, "현재가": 10000. + i * 100.,
        "매입가": 11000., "보유량": float(i % 3), "목표비중": 100. / rows,
        "기술적타점": "분할 매수"} for i in range(rows)])
    original_frame = frame.copy(deep=True)
    namespace = dict(globals(), holdings_table=frame, total_invest=750000., usdkrw=1400.,
        _signal_cache={}, always_invest_set=set(), redistribute_mode=True,
        st=SimpleNamespace(session_state={"rebcalc_accum": {}}))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[multiplier, baseline], type_ignores=[])),
                 "<baseline-calculation>", "exec"), namespace)
    before = namespace["baseline"]

    def after():
        eligible = prepare_rebalance_holdings(frame)
        return build_rebalance_plan(eligible, float(eligible["목표비중"].sum()), 750000., 1400.,
            {}, set(), True, {}, namespace["_rebcalc_signal_multiplier"])

    assert before() == after()
    before_samples, after_samples = [], []
    for repetition in range(repeat):
        pairs = [(before, before_samples), (after, after_samples)]
        for fn, samples in pairs if repetition % 2 == 0 else reversed(pairs):
            started = perf_counter()
            for _ in range(iterations):
                fn()
            samples.append((perf_counter() - started) * 1000 / iterations)
    pd.testing.assert_frame_equal(frame, original_frame, check_exact=True)
    old_mean, new_mean = statistics.mean(before_samples), statistics.mean(after_samples)
    return {"baseline": BASE, "scope": "offline allocation and share calculation only", "rows": rows,
        "repeat": repeat, "iterations_per_repeat": iterations, "outputs_exact": True,
        "target_conversions_for_eligible_rows": {"before": rows * 3, "after": rows},
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
