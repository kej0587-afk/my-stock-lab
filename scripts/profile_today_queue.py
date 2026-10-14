"""Profile public/synthetic Today Queue inputs, without private portfolio data."""

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
from threading import Lock
from time import sleep
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["STOCK_LAB_FORCE_AUTH_MODE"] = "public_demo"
logging.disable(logging.CRITICAL)

from stock_lab_core.performance import PerformanceTrace, measure, timed_call


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-live", action="store_true")
    parser.add_argument("--count", type=int, default=77)
    parser.add_argument("--provider-delay", type=float, default=0.0)
    args = parser.parse_args()
    if args.count < 1 or args.provider_delay < 0:
        parser.error("count must be positive and provider-delay nonnegative")

    with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
        import app
        import pandas as pd
        from stock_lab_core import prices
        from tests.fixtures_price import make_price_df

    symbols = ["SPY", "MSFT", "NVDA"] if args.public_live else [f"PERF{i:03d}" for i in range(args.count)]
    items = tuple(dict(ticker=symbol, name=f"Profile company {i}", is_etf=symbol == "SPY", asset_class="us_etf_sp" if symbol == "SPY" else "us_stock") for i, symbol in enumerate(symbols))
    provider_calls = {"batch": 0, "single": 0}
    lock = Lock()
    frames = {period: make_price_df(days=days)[["Open", "High", "Low", "Close", "Volume"]] for period, days in [("1y", 260), ("10y", 2600), ("3mo", 64)]}

    def download(tickers, *, period="1y", **kwargs):
        is_batch = isinstance(tickers, (list, tuple))
        with lock:
            provider_calls["batch" if is_batch else "single"] += 1
        sleep(args.provider_delay * (len(tickers) / 4 if is_batch else 1))
        frame = frames.get(period, frames["10y"])
        return pd.concat({symbol: frame for symbol in tickers}, axis=1) if is_batch else frame.copy()

    with ExitStack() as stack:
        stack.enter_context(patch.object(app, "holdings_table", pd.DataFrame()))
        stack.enter_context(patch.object(app, "get_my_price", return_value=0.0))
        stack.enter_context(patch.object(app, "has_position", return_value=False))
        stack.enter_context(patch.object(app, "load_display_live_price", timed_call("prices", "load_display_live_price")(lambda _: 0.0)))
        stack.enter_context(patch.object(app, "load_fin_score_meta_fast", timed_call("external_data", "load_fin_score_meta_fast")(lambda *a: (4, {}))))
        if not args.public_live:
            stack.enter_context(patch.object(prices.yf, "download", download))
            stack.enter_context(patch.object(prices, "_maybe_align_ohlcv_to_live_price", lambda ticker, frame: frame))
            stack.enter_context(patch.object(app, "get_sector_benchmark_info", return_value=("XLK", "US technology")))
            stack.enter_context(patch.object(app, "get_sector_provenance", return_value={}))
        app.st.session_state.fin_score_map = {}
        app.get_auto_benchmark_info.clear()
        prices.load_price_df.clear()
        prices.load_price_frames_batch.clear()
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()), PerformanceTrace() as trace:
            result = app.get_all_summary((), "개인모드", items)
            with measure("phase", "analyst_enrichment"):
                result = app.attach_today_analyst_context(
                    result,
                    get_analyst_snapshot=app.get_analyst_snapshot if args.public_live else timed_call("external_data", "get_analyst_snapshot")(lambda _: {"ok": True, "data": {"targetMeanPrice": 150, "numberOfAnalystOpinions": 10}, "fetched_at": "2026-10-14T00:00:00+00:00", "source": "synthetic"}),
                    load_latest_price=lambda _: 0.0,
                )
        report = trace.report()
        # Target fallback timestamps and provenance aren't timing invariants.
        stable = result.drop(columns=[c for c in result if c.endswith("조회시각")], errors="ignore")
        payload = stable.to_json(orient="split", date_format="iso", double_precision=10)
        report.update({
            "scope": "public_live_summary_and_analysts" if args.public_live else "synthetic_summary_and_analysts",
            "rows": len(result), "expected_rows": len(items),
            "provider_calls": provider_calls if not args.public_live else "not mocked",
            "result_digest": hashlib.sha256(payload.encode()).hexdigest(),
            "data_status_counts": result.get("데이터상태", pd.Series(dtype=str)).value_counts().to_dict(),
            "analyst_status_counts": result.get("애널목표상태", pd.Series(dtype=str)).value_counts().to_dict(),
            "live_display_quotes_mocked": True,
            "financial_scores_mocked": True,
            "flow_and_ui_included": False,
        })
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
