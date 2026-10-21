"""Opt-in live A/B: same symbols/date/feed/4 workers, no result caches.

Run: py -3.11 -X utf8 -m tests.benchmark_kr_history_connections
This is a provider-stage comparison, not a full-account Cloud timing claim.
"""

import json
from statistics import mean
from time import perf_counter
from unittest.mock import patch

import pandas as pd
import requests

from stock_lab_core import kr_flow_history as history
from stock_lab_core import money_flow as flow


def main():
    tickers = list(dict.fromkeys(
        flow.normalize_money_flow_ticker(item["ticker"])
        for item in flow.IMAGE_THEME_UNIVERSE
        if flow._is_krx_money_flow_ticker(item["ticker"])
    ))[:32]
    universe = [{"ticker": t} for t in tickers]
    now = pd.Timestamp.now(tz="Asia/Seoul").normalize()
    measurements = {"before": [], "after": []}
    reference = None
    for repeat in range(3):
        for mode in (("before", "after") if repeat % 2 == 0 else ("after", "before")):
            reader = history.KrFlowHistoryReader(request=requests.get if mode == "before" else None)
            frames = {}

            def load(ticker):
                result = reader.read(ticker, now=now)
                if result.empty or result.attrs.get("transport_error"):
                    raise AssertionError(f"Incomplete provider response: {ticker} {result.attrs}")
                frames[ticker] = result
                return result

            started = perf_counter()
            with patch.object(flow, "load_kr_flow_history", load):
                metrics = flow._load_universe_metrics(pd.DataFrame(), universe)
            elapsed = perf_counter() - started
            if reference is None:
                reference = frames, metrics
            for ticker in tickers:
                pd.testing.assert_frame_equal(reference[0][ticker], frames[ticker], check_exact=True)
                assert reference[0][ticker].attrs == frames[ticker].attrs
            pd.testing.assert_frame_equal(pd.DataFrame(reference[1]), pd.DataFrame(metrics), check_exact=True)
            measurements[mode].append(elapsed)
            print(json.dumps({"repeat": repeat + 1, "mode": mode, "seconds": elapsed,
                              "rows_and_metrics_identical": True}), flush=True)
    print(json.dumps({"scope": "KR theme history and metrics; cold result caches",
                      "symbols": len(tickers), "requests_each_run": len(tickers), "workers": 4,
                      "date": str(now.date()), "runs": measurements,
                      "means": {key: mean(values) for key, values in measurements.items()}}), flush=True)


if __name__ == "__main__":
    main()
