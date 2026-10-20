"""Compare old/corrected public Naver batch queries without importing the app."""

import argparse
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stock_lab_core import prices
from stock_lab_core.performance import PerformanceTrace


def legacy_bulk(tickers):
    query = "|".join("SERVICE_ITEM:" + prices._kr_code(t) for t in tickers)
    req = urllib.request.Request(
        "https://polling.finance.naver.com/api/realtime?query=" + urllib.parse.quote(query),
        headers=prices._NAVER_HEADERS,
    )
    prices._quote_transport_event("naver_bulk", "request")
    with urllib.request.urlopen(req, timeout=6) as response:
        result = prices._parse_naver_realtime_quotes(response.read().decode("utf-8", errors="ignore"), tickers)
    prices._quote_transport_event("naver_bulk", "response")
    return result


def run(tickers, bulk):
    prices.clear_latest_price_cache()
    with patch.object(prices, "_fetch_naver_quotes_bulk", bulk), PerformanceTrace() as trace:
        quotes = prices._load_latest_kr_quotes_batch_cached.__wrapped__(tuple(tickers))
    report = trace.report()
    return quotes, {"elapsed_seconds": report["elapsed_seconds"],
                    "transport_events": report["transport_events"],
                    "quotes_returned": len(quotes), "functions": report["functions"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tickers = ["005930.KS", "000660.KS", "379810.KS", "379800.KS",
               "418660.KS", "0167A0.KS", "003160.KS", "096530.KQ"]
    before, old_trace = run(tickers, legacy_bulk)
    after, new_trace = run(tickers, prices._fetch_naver_quotes_bulk)
    result = {
        "scope": "public_8_ticker_quote_batch_only_not_full_today_queue",
        "observed_at": prices.pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
        "tickers": tickers, "before": old_trace, "after": new_trace,
        "same_quotes": before == after,
        "note": "Live prices can move between probes. This does not measure Cloud end-to-end elapsed.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in ("before", "after")}, ensure_ascii=False))
    for name, trace in [("before", old_trace), ("after", new_trace)]:
        print(name, round(trace["elapsed_seconds"], 3), trace["transport_events"], trace["quotes_returned"])


if __name__ == "__main__":
    main()
