"""Offline A/B: guidance and sorting for ten detail groups plus the full table.

Excludes Streamlit rendering, prices, external data and decision calculations.
Run: python scripts/benchmark_today_queue_view.py --rows 85 --repeat 5
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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.today_queue import sort_today_queue_detail_table
from stock_lab_core.today_queue_view import prepare_detail_view


BASE = "26da1c00a97afc6d53f52d551e9a069216d25c8d"


def benchmark(rows=85, repeat=5, iterations=10):
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
              and n.name == "_render_today_queue_tab")
    table = deepcopy(next(n for n in fn.body if isinstance(n, ast.FunctionDef)
                           and n.name == "_render_today_queue_table"))
    end = next(i for i, n in enumerate(table.body) if isinstance(n, ast.Assign)
               and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
               and n.value.func.id == "sort_today_queue_detail_table")
    table.body = table.body[:end + 1] + [ast.parse("return view_df").body[0]]
    env = dict(globals(), st=SimpleNamespace(info=lambda *a: None))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[table], type_ignores=[])),
                 "<baseline-detail-preparation>", "exec"), env)
    frame = pd.DataFrame({"티커": [f"T{i}" for i in range(rows)], "종목명": "Fixture",
        "게이트상태": ["실행가능" if i % 2 else "방어우선" for i in range(rows)],
        "게이트근거": "Existing reason", "Adj점수": np.arange(rows) % 4,
        "R/R": np.arange(rows) % 3, "안전상태": "GREEN", "최종읽기": "관망"})
    original = frame.copy(deep=True)
    selections = [(np.arange(rows) % 10 == i, i >= 2) for i in range(10)
                  if (np.arange(rows) % 10 == i).any()]
    selections.append((np.ones(rows, dtype=bool), False))

    def before():
        return [env["_render_today_queue_table"](frame.loc[mask], "empty", risk)
                for mask, risk in selections]

    def after():
        detail = prepare_detail_view(frame)
        return [sort_today_queue_detail_table(detail.loc[mask].copy(), risk_first=risk)
                for mask, risk in selections]

    for old, new in zip(before(), after()):
        pd.testing.assert_frame_equal(old, new, check_exact=True)
    before_samples, after_samples = [], []
    for repetition in range(repeat):
        pairs = [(before, before_samples), (after, after_samples)]
        for fn, samples in pairs if repetition % 2 == 0 else reversed(pairs):
            started = perf_counter()
            for _ in range(iterations):
                fn()
            samples.append((perf_counter() - started) * 1000 / iterations)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    old_mean, new_mean = statistics.mean(before_samples), statistics.mean(after_samples)
    return {"baseline": BASE, "scope": "offline guidance and sorting only", "rows": rows,
        "repeat": repeat, "iterations_per_repeat": iterations, "outputs_exact": True,
        "guidance_calls": {"before": 2 * rows, "after": rows},
        "before_ms": before_samples, "after_ms": after_samples,
        "before_mean_ms": old_mean, "after_mean_ms": new_mean,
        "reduction_pct": (old_mean - new_mean) / old_mean * 100}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=85)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    if min(args.rows, args.repeat, args.iterations) <= 0:
        parser.error("rows, repeat and iterations must be positive")
    print(json.dumps(benchmark(args.rows, args.repeat, args.iterations), indent=2))
