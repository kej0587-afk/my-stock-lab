"""Offline synthetic comparison: python -m tests.benchmark_resample."""

import argparse
import json
from statistics import median
from time import perf_counter

import numpy as np
import pandas as pd

from tests.test_resample_refactor_parity import assert_exact_frame, implementations, make_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--frames", type=int, default=12)
    args = parser.parse_args()
    if args.repeats < 1 or args.frames < 1:
        parser.error("repeats and frames must be positive")
    old, new = implementations()
    rng = np.random.default_rng(102631)
    index = pd.bdate_range("2015-01-01", periods=2600, name="Date", tz="Asia/Seoul")
    reports = []
    for case in ("int64", "float64_missing", "fractional_fallback"):
        frames = []
        for _ in range(args.frames):
            volume = rng.integers(0, 10_000_000, len(index))
            if case != "int64":
                volume = volume.astype(float)
                volume[rng.random(len(index)) < .1] = np.nan
                if case == "fractional_fallback":
                    volume += .25
            frames.append(make_frame(volume, index=index))
        requests = [(frame, rule) for frame in frames for rule in ("W-FRI", pd.offsets.MonthEnd())]

        def run(function):
            return [function(frame, rule) for frame, rule in requests]

        for expected, actual in zip(run(old), run(new)):
            assert_exact_frame(actual, expected)
        times = {"old": [], "current": []}
        for iteration in range(args.repeats):
            functions = (("old", old), ("current", new))
            for label, function in (functions if iteration % 2 == 0 else functions[::-1]):
                started = perf_counter()
                outputs = run(function)
                times[label].append(perf_counter() - started)
                if label == "old":
                    old_outputs = outputs
                else:
                    current_outputs = outputs
            for expected, actual in zip(old_outputs, current_outputs):
                assert_exact_frame(actual, expected)
        old_median, current_median = median(times["old"]), median(times["current"])
        reports.append({"volume": case, "exact_equal": True, "old_median_seconds": old_median,
                        "current_median_seconds": current_median,
                        "old_over_current": old_median / current_median})
    print(json.dumps({"scope": "local synthetic resampling only; not a Cloud benchmark",
                      "pandas": pd.__version__, "numpy": np.__version__, "rows_per_frame": len(index),
                      "frames_per_case": args.frames, "resamples_per_case": len(requests),
                      "repeats": args.repeats, "results": reports}, indent=2))


if __name__ == "__main__":
    main()
