"""Offline A/B for Today Queue display labels, including private frame copies.

Excludes provider calls, investment calculations, enrichment and UI rendering.
Run: python scripts/benchmark_today_queue_display.py --rows 85 --repeat 5
"""

import argparse
import ast
import json
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.asset_classifier import is_leveraged_or_inverse_product
from stock_lab_core.decision_engine import classify_decision_signal
from stock_lab_core.formatters import is_kr_listed, sanitize_ticker_value
from stock_lab_core.today_queue import (
    leveraged_market_defense_mask as _leveraged_market_defense_mask,
    leveraged_recovery_tracking_mask as _leveraged_recovery_tracking_mask,
    leveraged_scout_execution_mask as _leveraged_scout_execution_mask,
    today_queue_reason_bucket as _today_queue_reason_bucket,
)


BASE = "57ba39a96d45197bd3a04a6a6dd14fb001feab9b"


def compile_policy(source):
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
              and n.name == "_render_today_queue_tab")

    def assignment(name):
        return next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))

    body = fn.body[assignment("portfolio_signal_attrs"):assignment("risk_df")]
    return compile(ast.Module(body=body, type_ignores=[]), "<queue-display-benchmark>", "exec")


def benchmark(rows=85, repeat=5, iterations=20):
    baseline = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    codes = [compile_policy(baseline), compile_policy((ROOT / "app.py").read_text(encoding="utf-8-sig"))]
    frame = pd.DataFrame([{
        "티커": ["RAM", "SOXL", "418660.KS", "MSFT", "379810.KS"][i % 5],
        "종목명": "Fixture", "유형": "ETF", "asset_class": "us_etf_nasdaq",
        "판정코드": "LEVERAGED_RECOVERY_DCA_CONDITIONAL" if i % 5 < 3 else "HARD_BLOCK_OVERWEIGHT",
        "🔥기술적 타점": "레버리지 시장위험: DCA 대기" if i % 5 < 3 else "하드차단: 비중 초과",
        "최종읽기": "관망", "📌후보등급": "A급", "판정분류": "buyish",
        "실행메모": "R/R 회복 대기", "매크로상태": "CAUTION", "데이터상태": "OK",
        "핵심근거": "회복 4/6(부분 회복) · 기초축 1W +6.0%",
        "R/R": 1.15, "Adj점수": 4.2, "현재비중": .5, "목표비중": 2.,
        "RSI": 64., "MFI": 72., "볼린저 %B": .82,
    } for i in range(rows)])
    original = frame.copy(deep=True)
    market = {"mode": "주의", "kr_stats": {"mode": "정상"}, "us_stats": {"mode": "정상"}, "macro_risk": 0.}

    def run(code):
        env = dict(globals(), summary_df=frame, get_cached_today_market_flow_snapshot=lambda: {},
                   build_today_market_guard=lambda *a: market)
        exec(code, env)
        return {k: env[k] for k in ("summary_df", "reason_bucket", "hard_block_mask", "buyish_mask", "caution_mask")}

    old, new = map(run, codes)
    for key in old:
        check = pd.testing.assert_frame_equal if isinstance(old[key], pd.DataFrame) else pd.testing.assert_series_equal
        check(old[key], new[key], check_exact=True)
    samples = [[], []]
    for repetition in range(repeat):
        for i in (0, 1) if repetition % 2 == 0 else (1, 0):
            start = perf_counter()
            for _ in range(iterations):
                run(codes[i])
            samples[i].append((perf_counter() - start) * 1000 / iterations)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    means = list(map(statistics.mean, samples))
    return {"baseline": BASE, "scope": "offline display policy only", "rows": rows,
        "repeat": repeat, "iterations_per_repeat": iterations, "outputs_exact": True,
        "before_ms": samples[0], "after_ms": samples[1],
        "before_mean_ms": means[0], "after_mean_ms": means[1],
        "reduction_pct": (means[0] - means[1]) / means[0] * 100}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=85)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    if min(args.rows, args.repeat, args.iterations) <= 0:
        parser.error("rows, repeat and iterations must be positive")
    print(json.dumps(benchmark(args.rows, args.repeat, args.iterations), indent=2))
