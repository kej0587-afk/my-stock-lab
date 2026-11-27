"""Collect a bounded public snapshot once, replay phase-1 entries offline."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_soxl_drawdown import ROOT, sha, dump
from soxl_drawdown_engine import DEFAULT, REFERENCES, MODES, TARGETS, entry_ledger
from soxl_intraday_engine import audit_window, simulate, equity, guard_at, summary, expected_bars

PHASE1 = ROOT / "docs/research/soxl_drawdown_20261127"
DIRECTORY = ROOT / "docs/research/soxl_intraday_20261127"
PROTOCOL = ROOT / "docs/maintenance/20261127_soxl_phase2_protocol.md"


def verified_protocol(directory, manifest):
    """A replay belongs to its captured protocol, not the mutable work log."""
    path = directory / "protocol.md"
    if not path.is_file() or sha(path) != manifest["protocol_sha256"]:
        raise ValueError("snapshot protocol missing or hash changed")
    return path


def fetch(directory):
    import yfinance as yf
    if (directory / "manifest.json").exists():
        raise ValueError("immutable snapshot exists; select another directory")
    directory.mkdir(parents=True, exist_ok=True)
    frozen_protocol = directory / "protocol.md"
    if frozen_protocol.exists():
        raise ValueError("snapshot protocol exists; select another directory")
    frozen_protocol.write_bytes(PROTOCOL.read_bytes())
    records = []
    for interval, period in (("1m", "8d"), ("5m", "60d"), ("60m", "730d")):
        record = dict(interval=interval, requested_period=period)
        try:
            frame = yf.Ticker("SOXL").history(period=period, interval=interval,
                auto_adjust=False, back_adjust=False, repair=False, actions=True,
                prepost=False, keepna=True, timeout=30)
            if frame.empty:
                raise ValueError("empty provider response")
            frame.index = frame.index.tz_convert("UTC")
            path = directory / f"SOXL_{interval}.csv"
            frame.to_csv(path, index_label="Time", float_format="%.12g", lineterminator="\n")
            record.update(rows=len(frame), start=frame.index[0].isoformat(),
                          end=frame.index[-1].isoformat(), sha256=sha(path))
        except Exception as exc:
            record.update(rows=0, error=f"{type(exc).__name__}: {exc}")
        records.append(record)
    dump(directory / "manifest.json", dict(symbol="SOXL", source="Yahoo Finance via yfinance",
        source_url="https://finance.yahoo.com/quote/SOXL/history/", datasets=records,
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        price_basis="split-adjusted OHLC; NOT dividend-adjusted; auto_adjust=False",
        protocol_sha256=sha(frozen_protocol), phase1_price_sha256=sha(PHASE1 / "prices.csv")))


def replay(directory, output, archive_path=None):
    import exchange_calendars as xc
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    frozen_protocol = verified_protocol(directory, manifest)
    if sha(PHASE1 / "prices.csv") != manifest["phase1_price_sha256"]:
        raise ValueError("frozen protocol or phase-1 snapshot changed")
    five = next(r for r in manifest["datasets"] if r["interval"] == "5m")
    if five["rows"] == 0 or sha(directory / "SOXL_5m.csv") != five["sha256"]:
        raise ValueError("missing or changed 5m snapshot")
    bars = pd.read_csv(directory / "SOXL_5m.csv", index_col="Time")
    bars.index = pd.to_datetime(bars.index, utc=True)
    if not bars.index.is_monotonic_increasing:
        raise ValueError("unsorted snapshot")
    daily = pd.read_csv(PHASE1 / "prices.csv", index_col="Date", parse_dates=True)
    schedule = xc.get_calendar("XNYS", start=str(daily.index[0].date()), end=str(daily.index[-1].date())).schedule
    regular = bars.loc[(bars.index >= schedule.open.iloc[0]) & (bars.index < schedule.close.iloc[-1])]
    archive = pd.read_csv(archive_path) if archive_path else None
    audits, trades, summaries, curves, quality = [], [], [], [], []
    for date, session in schedule.iterrows():
        part = regular.loc[(regular.index >= session.open) & (regular.index < session.close)]
        if part.empty:
            continue
        missing = len(expected_bars(schedule.loc[[date]]).difference(part.index))
        invalid = int(part[["Open", "High", "Low", "Close"]].isna().any(axis=1).sum())
        aggregate = [part.Open.iloc[0], part.High.max(), part.Low.min(), part.Close.iloc[-1]]
        for field, observed in zip(("Open", "High", "Low", "Close"), aggregate):
            frozen = float(daily.loc[date, field])
            tolerance = max(.03, .001 * frozen)
            quality.append(dict(date=str(date.date()), field=field, daily=frozen, intraday=observed,
                                difference=observed-frozen, tolerance=tolerance,
                                within_tolerance=bool(abs(observed-frozen) <= tolerance),
                                missing_bars=missing, nan_bars=invalid))
    for reference in REFERENCES:
        for mode in MODES:
            entries, _ = entry_ledger(daily, reference, mode)
            verified = []
            for entry in entries:
                window, status, missing = audit_window(daily, regular, schedule, entry)
                guard = guard_at(window.index[0], archive) if window is not None else "unknown"
                audits.append(dict(entry, coverage=status, missing_bars=missing, historical_guard=guard))
                if window is not None:
                    verified.extend(dict(simulate(window, daily, entry, target), historical_guard=guard)
                                    for target in TARGETS)
            trades.extend(verified)
            for target in TARGETS:
                for cohort in ("no_guard", "guard_verified_allowed"):
                    chosen = [t for t in verified if t["target"] == target and
                              (cohort == "no_guard" or t["historical_guard"] == "allowed")]
                    curve = equity(regular, daily, chosen)
                    summaries.append(dict(reference=reference, mode=mode, target=target, cohort=cohort,
                                          **summary(chosen, curve)))
                    if chosen:
                        curves.append(curve.assign(reference=reference, mode=mode, target=target, cohort=cohort))
    output.mkdir(parents=True, exist_ok=True)
    tables = dict(coverage=pd.DataFrame(audits), trades=pd.DataFrame(trades, columns=list(trades[0]) if trades else
                  ["reference", "mode", "trade_id", "target", "entry_time", "exit_time", "net_return"]),
                  summary=pd.DataFrame(summaries), quality=pd.DataFrame(quality),
                  equity=pd.concat(curves, ignore_index=True) if curves else pd.DataFrame(columns=["time", "equity", "drawdown"]))
    for key, frame in tables.items():
        frame.to_csv(output / f"{key}.csv", index=False, float_format="%.12g", lineterminator="\n")
    dump(output / "replay.json", dict(protocol_sha256=sha(frozen_protocol),
        engine_sha256=sha(Path(__file__).with_name("soxl_intraday_engine.py")),
        runner_sha256=sha(Path(__file__)), source_sha256=five["sha256"],
        historical_guard_source=str(archive_path) if archive_path else None,
        historical_guard_note="No timestamped interval-valid archive supplied; unknown, not allowed",
        output_sha256={f"{name}.csv": sha(output / f"{name}.csv") for name in tables}))
    print(tables["coverage"].groupby(["reference", "mode", "coverage"]).size().to_string())
    print(tables["summary"].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--guard-archive", type=Path)
    args = parser.parse_args()
    if args.fetch:
        fetch(args.directory)
    replay(args.directory, args.output or args.directory, args.guard_archive)
