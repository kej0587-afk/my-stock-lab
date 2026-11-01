"""Offline fake-provider waits: python -m tests.benchmark_leveraged_watch."""

import argparse
import json
import math
from statistics import median
from threading import Lock
from time import perf_counter, sleep

import pandas as pd

from stock_lab_core.leveraged_watch import build_leveraged_watch_rows
from tests.test_leveraged_watch import BASELINE, BASELINE_FUNCTION, assert_exact_rows, baseline_scope


class FakeProviders:
    def __init__(self, frame, delay):
        self.frame = frame
        self.delay = delay
        self.calls = {"quote": 0, "history": 0}
        self.active = self.peak = 0
        self.lock = Lock()

    def wait(self, kind):
        with self.lock:
            self.calls[kind] += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            sleep(self.delay)
        finally:
            with self.lock:
                self.active -= 1

    def quote(self, ticker):
        self.wait("quote")
        return 150.25

    def history(self, ticker, period):
        assert period == "6mo"
        self.wait("history")
        return self.frame


def benchmark(*, rows=8, repeats=3, delay=0.02):
    watch = [(f"SYN{index}", "proxy", f"synthetic {index}") for index in range(rows)]
    frame = pd.DataFrame({"Close": [100 + index for index in range(30)]})
    scope = baseline_scope()
    scope["LEVERAGED_ETF_PRECISION_PROFILES"] = {"benchmark": {"watch": watch}}
    callbacks = dict(pct_text=scope["_leveraged_precision_pct_text"],
                     judge=scope["_leveraged_precision_proxy_judgement"])
    times = {"old_sequential": [], "new_two_slots": []}
    counts = {key: [] for key in times}
    peaks = {key: [] for key in times}
    for iteration in range(repeats):
        outputs = {}
        labels = tuple(times)
        for label in (labels if iteration % 2 == 0 else labels[::-1]):
            providers = FakeProviders(frame, delay)
            if label == "old_sequential":
                scope.update(load_display_live_price=providers.quote, load_price_df=providers.history)
                run = lambda: scope[BASELINE_FUNCTION]("benchmark")
            else:
                run = lambda: build_leveraged_watch_rows(
                    watch, load_quote=providers.quote, load_history=providers.history, **callbacks,
                )
            started = perf_counter()
            outputs[label] = run()
            times[label].append(perf_counter() - started)
            counts[label].append(dict(providers.calls))
            peaks[label].append(providers.peak)
            assert providers.active == 0
            assert providers.calls == {"quote": rows, "history": rows}
            assert providers.peak <= (1 if label == "old_sequential" else 2)
        assert_exact_rows(outputs["new_two_slots"], outputs["old_sequential"])
    assert counts["old_sequential"] == counts["new_two_slots"]
    return {
        "scope": "offline synthetic delayed fake providers; not Cloud latency",
        "baseline": BASELINE, "rows": rows, "repeats": repeats,
        "delay_seconds_per_fake_call": delay, "exact_equal": True,
        "median_seconds": {key: median(values) for key, values in times.items()},
        "seconds": times, "fake_provider_calls": counts, "peak_fake_provider_overlap": peaks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.02)
    args = parser.parse_args()
    if args.rows < 1 or args.repeats < 1 or not math.isfinite(args.delay) or args.delay < 0:
        parser.error("rows/repeats must be positive; delay must be finite and nonnegative")
    print(json.dumps(benchmark(rows=args.rows, repeats=args.repeats, delay=args.delay), indent=2))


if __name__ == "__main__":
    main()
