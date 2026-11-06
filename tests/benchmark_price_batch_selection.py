"""Three paired CPU-only runs, fixed inputs; not a network/Cloud benchmark."""

import json
from statistics import mean
from time import perf_counter

import pandas as pd

from stock_lab_core.price_batch_selection import DownloadFrameSelector
from tests.test_price_batch_selection import batch, legacy_select


def main():
    symbols = tuple(f"S{i}" for i in range(95))
    frames = [batch(symbols, rows) for rows in (64, 260, 2600)]
    times = {"before": [], "after": []}
    for repeat in range(3):
        outputs = {}
        for mode in (("before", "after") if repeat % 2 == 0 else ("after", "before")):
            started = perf_counter()
            result = []
            for frame in frames:
                selector = DownloadFrameSelector(frame) if mode == "after" else None
                result.extend(selector.select(t) if selector else legacy_select(frame, t) for t in symbols)
            times[mode].append(perf_counter() - started)
            outputs[mode] = result
        for old, new in zip(outputs["before"], outputs["after"]):
            pd.testing.assert_frame_equal(new, old, check_exact=True)
            assert new.attrs == old.attrs
    print(json.dumps({"scope": "CPU batch column selection only; no network or app timing",
                      "baseline": "f2ad9174", "symbols": len(symbols), "rows": [64, 260, 2600],
                      "equal_frames_per_pair": 285, "provider_requests_both": 0,
                      "samples_seconds": times,
                      "mean_seconds": {key: mean(value) for key, value in times.items()}}, indent=2))


if __name__ == "__main__":
    main()
