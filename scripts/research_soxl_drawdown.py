"""Fetch once explicitly, then replay a hashed public daily snapshot offline."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from soxl_drawdown_engine import run_study, validate_prices

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "docs/research/soxl_drawdown_20261127"
CUTOFF = "2026-11-27T05:00:00Z"
PROTOCOL = ROOT / "docs/maintenance/20261127_soxl_drawdown_protocol.md"


def sha(path):
    # Text artifacts remain reproducible with Git's Windows CRLF checkout.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def sessions():
    import exchange_calendars as xc
    schedule = xc.get_calendar("XNYS", start="2010-01-01", end="2026-11-30").schedule
    return schedule.loc[schedule["close"] <= pd.Timestamp(CUTOFF)]


def fetch(directory):
    import yfinance as yf
    path = directory / "prices.csv"
    if path.exists():
        raise ValueError("snapshot already exists; choose a new --directory, never overwrite")
    schedule = sessions()
    end = schedule.index[-1] + pd.Timedelta(days=1)
    data = yf.Ticker("SOXL").history(start="2010-01-01", end=str(end.date()),
                                    interval="1d", auto_adjust=False, back_adjust=False,
                                    repair=False, actions=True, prepost=False,
                                    keepna=True, timeout=30)
    if data.empty:
        raise ValueError("Yahoo returned no data")
    data.index = data.index.tz_convert("America/New_York").tz_localize(None).normalize()
    validate_prices(data, schedule.loc[data.index[0]:].index)
    directory.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index_label="Date", float_format="%.12g", lineterminator="\n")
    audit = []
    for i in range(1, len(data)):
        row, prev = data.iloc[i], data.iloc[i - 1]
        ret = float(row.Close / prev.Close - 1)
        if row["Stock Splits"] or abs(ret) > .40:
            audit.append(dict(date=str(data.index[i].date()), split=float(row["Stock Splits"]),
                              previous_close=float(prev.Close), open=float(row.Open),
                              close=float(row.Close), daily_return=ret))
    dump(directory / "data_manifest.json", dict(
        symbol="SOXL", interval="1d", session="regular", cutoff_utc=CUTOFF,
        fetched_at_utc=datetime.now(timezone.utc).isoformat(), source="Yahoo Finance via yfinance",
        source_url="https://finance.yahoo.com/quote/SOXL/history/", start=str(data.index[0].date()),
        end=str(data.index[-1].date()), rows=len(data), sha256=sha(path),
        price_basis="Yahoo split-adjusted OHLC; not dividend-back-adjusted; no second split adjustment",
        parameters=dict(auto_adjust=False, back_adjust=False, repair=False, actions=True, prepost=False),
        python=platform.python_version(), versions={name: importlib.metadata.version(name)
                                                   for name in ("pandas", "numpy", "yfinance", "exchange-calendars")},
        split_and_large_return_audit=audit, protocol_sha256=sha(PROTOCOL)))


def replay(directory, output=None):
    manifest = json.loads((directory / "data_manifest.json").read_text(encoding="utf-8"))
    if sha(directory / "prices.csv") != manifest["sha256"]:
        raise ValueError("snapshot hash mismatch")
    if sha(PROTOCOL) != manifest["protocol_sha256"]:
        raise ValueError("frozen protocol changed")
    frame = pd.read_csv(directory / "prices.csv", index_col="Date", parse_dates=True)
    schedule = sessions()
    validate_prices(frame, schedule.loc[frame.index[0]:].index)
    result = run_study(frame)
    output = output or directory
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    trades = result["trades"]
    keys = ["reference", "mode", "trade_id"]
    left = trades.loc[trades.target == .10].set_index(keys)
    right = trades.loc[trades.target == .20].set_index(keys)
    paired_fields = ["signal_date", "entry_date", "entry_raw", "entry_fill", "cash_amount", "units"]
    pd.testing.assert_frame_equal(left[paired_fields], right[paired_fields])
    paired = left[paired_fields].copy()
    paired["net_return_10"] = left.net_return
    paired["net_return_20"] = right.net_return
    paired["difference_20_minus_10"] = right.net_return - left.net_return
    result["paired"] = paired.reset_index()
    result["yearly"] = trades.assign(entry_year=trades.entry_date.str[:4]).groupby(
        ["reference", "mode", "target", "entry_year"], as_index=False).agg(
            entries=("net_return", "size"), mean_net_return=("net_return", "mean"),
            net_pnl=("net_pnl", "sum"), target_hit_rate=("target_hit", "mean"))
    for name in ("summary", "trades", "equity", "signals", "entries", "paired", "yearly"):
        path = output / f"{name}.csv"
        result[name].to_csv(path, index=False, float_format="%.12g", lineterminator="\n")
        hashes[path.name] = sha(path)
    dump(output / "replay_manifest.json", dict(
        protocol=result["protocol"], price_sha256=manifest["sha256"],
        hash_convention="SHA-256 of UTF-8 text with CRLF normalized to LF",
        engine_sha256=sha(Path(__file__).with_name("soxl_drawdown_engine.py")),
        runner_sha256=sha(Path(__file__)), output_sha256=hashes))
    print(result["summary"].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--output", type=Path, help="offline replay output; does not overwrite input snapshot")
    parser.add_argument("--fetch", action="store_true", help="explicit network snapshot creation")
    args = parser.parse_args()
    if args.fetch:
        fetch(args.directory)
    replay(args.directory, args.output)
