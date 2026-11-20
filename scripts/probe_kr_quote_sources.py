"""Read-only polling/basic comparison. Never changes production routing or caches.

Run explicitly with --live. Each round uses one polling batch and N basic calls,
without retries; request timestamps describe the probe, not the quoted trade.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from time import perf_counter
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stock_lab_core import prices
from stock_lab_core.quote_observation import quote_provenance


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", ""))
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def compare_pair(ticker, polling_payload, basic_payload):
    """Compare observations, never merge another endpoint's time into a price."""
    key = prices.normalize_price_lookup_key(ticker)
    code = prices._kr_code(key)
    polling_quote = prices._parse_naver_realtime_quotes(json.dumps(polling_payload), [key]).get(key, {})
    basic_quote = prices._extract_naver_quote_from_obj(basic_payload, ticker=key, source="naver_basic")
    polling_info = quote_provenance(polling_quote.get("price"), key)
    basic_info = quote_provenance(basic_quote.get("price"), key)
    raw = next((obj for symbol, obj in prices._walk_naver_quote_objects(polling_payload)
                if symbol == code), {})
    basic = basic_payload if isinstance(basic_payload, dict) else {}
    pp = positive(polling_quote.get("price")) if polling_info else None
    bp = positive(basic_quote.get("price")) if basic_info else None
    equal = pp == bp if pp is not None and bp is not None else None
    delta = bp - pp if equal is not None else None
    nxt = raw.get("nxtOverMarketPriceInfo") or {}
    over = basic.get("overMarketPriceInfo") or {}
    nxt = nxt if isinstance(nxt, dict) else {}
    over = over if isinstance(over, dict) else {}
    return {
        "ticker": key, "polling_price": pp, "basic_price": bp,
        "same_numeric_price": equal, "basic_minus_polling": delta,
        "basic_minus_polling_pct": delta / pp * 100 if delta is not None else None,
        "polling_state": raw.get("ms"), "basic_state": basic.get("marketStatus"),
        "basic_session_label": basic.get("marketSessionType"),
        "polling_observed_at": polling_info.get("observed_at"),
        "basic_observed_at": basic_info.get("observed_at"),
        "basic_timestamp_meaning": "supplier_field_not_verified_execution_time",
        "separate_polling_nxt": {"price": positive(nxt.get("overPrice")), "time": nxt.get("localTradedAt")},
        "separate_basic_overmarket": {"price": positive(over.get("overPrice")), "time": over.get("localTradedAt")},
        "assessment": ("missing_or_unproven_quote" if equal is None else
                       "different_prices_do_not_substitute" if not equal else
                       "equal_numbers_not_proof_of_same_session"),
    }


def fetch_capture(url, *, timeout):
    """Exactly one HTTP attempt, retaining public payload and request cost."""
    start = perf_counter()
    result = {"requested_at": datetime.now(timezone.utc).isoformat(), "request_count": 1,
              "http_status": None, "response_bytes": 0, "error_type": None, "payload": {}}
    try:
        req = urllib.request.Request(url, headers=prices._NAVER_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result["http_status"] = response.status
            raw = response.read()
        result["response_bytes"] = len(raw)
        result["response_sha256"] = hashlib.sha256(raw).hexdigest()
        # Same decoding as the current application; quote digits remain intact.
        result["payload"] = json.loads(raw.decode("utf-8", errors="ignore"))
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["http_status"] = getattr(exc, "code", result["http_status"])
    result["received_at"] = datetime.now(timezone.utc).isoformat()
    result["elapsed_seconds"] = round(perf_counter() - start, 6)
    return result


def collect_round(tickers, *, basic_first=False, fetch=fetch_capture):
    keys = list(dict.fromkeys(prices.normalize_price_lookup_key(t) for t in tickers))
    if not keys or len(keys) > 12 or any(not re.fullmatch(r"[0-9][A-Z0-9]{5}\.(KS|KQ)", t) for t in keys):
        raise ValueError("Provide 1–12 explicit domestic .KS/.KQ symbols")
    if len({prices._kr_code(t) for t in keys}) != len(keys):
        raise ValueError("Conflicting exchange suffixes for the same instrument")
    captures = {}
    clock = perf_counter()
    for group in (["basic", "polling"] if basic_first else ["polling", "basic"]):
        if group == "polling":
            query = "SERVICE_ITEM:" + ",".join(prices._kr_code(t) for t in keys)
            captures["polling"] = fetch("https://polling.finance.naver.com/api/realtime?query=" +
                                        urllib.parse.quote(query), timeout=6)
        else:
            captures["basic"] = {t: fetch(f"https://m.stock.naver.com/api/stock/{prices._kr_code(t)}/basic", timeout=5)
                                 for t in keys}
    bulk, singles = captures["polling"], list(captures["basic"].values())
    return {
        "order": "basic_then_polling" if basic_first else "polling_then_basic",
        "elapsed_seconds": round(perf_counter() - clock, 6),
        "cost": {"polling_requests": bulk["request_count"],
                 "basic_requests": sum(c["request_count"] for c in singles),
                 "polling_seconds": bulk["elapsed_seconds"],
                 "basic_sequential_seconds": round(sum(c["elapsed_seconds"] for c in singles), 6)},
        "rows": [compare_pair(t, bulk["payload"], captures["basic"][t]["payload"]) for t in keys],
        "captures": captures,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make bounded public-data requests")
    parser.add_argument("--rounds", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--tickers", nargs="+", default=["005930.KS", "000660.KS", "379810.KS"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("No network work without --live")
    if args.output.exists():
        parser.error("Output already exists; preserve the earlier capture")
    runs = [collect_round(args.tickers, basic_first=bool(i % 2)) for i in range(args.rounds)]
    report = {"scope": "public_local_probe_not_cloud_or_simultaneous_market_snapshot",
              "production_routing_changed": False, "replacement_supported": False,
              "limits": ["Price equality alone does not prove quote-session equivalence",
                         "Polling has no per-item timestamp; basic still requires one request per symbol",
                         "Supplier time is not verified execution time; request time is separate",
                         "Sequential diagnostic timing is not a Cloud performance benchmark"],
              "runs": runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    for i, run in enumerate(runs, 1):
        print(json.dumps({"round": i, "cost": run["cost"], "rows": run["rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
