"""Research-only revaluation of saved events; no production policy imports.

Saved signal/gate dates are conditional inputs, NOT a replay of the complete
historical market gate. Prices and authoritative sessions must be provided.
Both arms confirm on Close and enter at the next session Open. The common end
is signal session + horizon (60 by default), independent of the gate-open date.
No dividends, interest, FX, taxes or portfolio allocation are modeled.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def read_saved_events(path):
    """Read the private legacy Markdown export without committing its contents."""
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        cells = [x.strip() for x in line.split("|")[1:-1]]
        if len(cells) != 10 or cells[1] not in ("KR", "US"):
            continue
        gate = None if cells[3] == "미개방(자료 끝까지)" else pd.Timestamp(cells[3])
        if gate is not None and pd.isna(gate):
            raise ValueError("Missing gate date is not a confirmed never-open event")
        rows.append(dict(ticker=cells[0], market=cells[1],
                         signal=pd.Timestamp(cells[2]), gate=gate))
    return rows


def evaluate_event(frame, sessions, signal, gate, *, completed_through, gate_observed_through=None,
                   horizon=60, cost_bps=0):
    """Return one equal-initial-capital comparison, including a cash-only B.

Missing values never advance execution to a later available candle. A gate
opening on/after the evaluation Close leaves B in cash. Gate=None means no
observed opening through completed_through (caller must attest coverage).
Costs are an illustrative per-side proportional execution charge, not a fee
schedule; one unit buys 1/(open*(1+cost)) shares and liquidates at close*(1-cost).
"""
    if horizon < 1 or not 0 <= cost_bps < 10000:
        raise ValueError("Invalid horizon/cost")
    sessions = pd.DatetimeIndex(sessions)
    if sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("Sessions must be unique and ordered")
    if frame.index.has_duplicates:
        raise ValueError("Duplicate price dates")
    signal = pd.Timestamp(signal)
    gate = None if gate is None else pd.Timestamp(gate)
    if signal not in sessions or (gate is not None and (gate not in sessions or gate <= signal)):
        return {"status": "invalid_event_date"}
    i = sessions.get_loc(signal)
    k = i + horizon
    if k >= len(sessions) or sessions[k] > pd.Timestamp(completed_through):
        return {"status": "incomplete_horizon"}
    end = sessions[k]
    b_pos = None if gate is None else sessions.get_loc(gate) + 1
    b_cash = b_pos is None or b_pos > k
    if gate is None and (gate_observed_through is None or pd.Timestamp(gate_observed_through) < end):
        return {"status": "unknown_gate_coverage"}
    result = {"status": "ok", "end": end.date().isoformat(), "B_cash": b_cash}
    prices = frame.reindex(sessions)
    fee = cost_bps / 10000
    for arm, pos in (("A", i + 1), ("B", None if b_cash else b_pos)):
        if pos is None:
            result.update(B_return=0.0, B_mdd=0.0, B_max_loss=0.0, B_holding_sessions=0, B_path="cash")
            continue
        if "Open" not in prices or not np.isfinite(prices["Open"].iloc[pos]) or prices["Open"].iloc[pos] <= 0:
            return {**result, "status": "missing_entry_open", "missing_arm": arm}
        if "Close" not in prices or not np.isfinite(prices["Close"].iloc[k]) or prices["Close"].iloc[k] <= 0:
            return {**result, "status": "missing_end_close"}
        path = prices.reindex(columns=["Close", "Low"]).iloc[pos:k + 1]
        complete_path = np.isfinite(path.to_numpy(dtype=float)).all() and not (path <= 0).any().any()
        entry = prices["Open"].iloc[pos]
        shares = 1 / (entry * (1 + fee))
        marks = path["Close"].to_numpy() * shares
        marks[-1] *= 1 - fee
        curve = np.r_[1.0, marks]
        result.update({f"{arm}_entry": sessions[pos].date().isoformat(),
                       f"{arm}_return": float(marks[-1] - 1),
                       f"{arm}_path": "complete" if complete_path else "missing",
                       f"{arm}_mdd": float(np.min(curve / np.maximum.accumulate(curve) - 1)) if complete_path else None,
                       f"{arm}_max_loss": float(min(0, path["Low"].min() * shares * (1-fee) - 1)) if complete_path else None,
                       f"{arm}_holding_sessions": k - pos + 1})
    result["difference"] = result["A_return"] - result["B_return"]
    return result


def anonymous_summary(rows):
    """Only publish non-identifying aggregates; missing cases keep their counts."""
    result = {"events": len(rows), "groups": {}}
    for kind in ("stock", "ETF"):
        group = [r for r in rows if r["kind"] == kind]
        valid = [r for r in group if r["status"] == "ok"]
        risk_pairs = [r for r in valid if r["A_mdd"] is not None and r["B_mdd"] is not None]
        stats = {"events": len(group), "endpoint_valid": len(valid), "risk_pairs": len(risk_pairs),
                 "statuses": dict(pd.Series([r["status"] for r in group], dtype=str).value_counts().items()),
                 "cash_B": sum(r["B_cash"] for r in valid)}
        if valid:
            for field in ("A_return", "B_return", "difference", "A_mdd", "B_mdd", "A_max_loss", "B_max_loss"):
                cohort = risk_pairs if field.endswith(("_mdd", "_max_loss")) else valid
                values = [r[field] for r in cohort]
                stats[field] = {"count": len(values), "mean": float(np.mean(values)) if values else None,
                                "median": float(np.median(values)) if values else None}
            stats["A_wins"] = sum(r["difference"] > 0 for r in valid)
        result["groups"][kind] = stats
    return result


def paired_conventions(rows, frames, schedules, completed_through, horizon=60):
    """Isolate execution and endpoint changes using the SAME zero-cost cohort."""
    pairs = []
    for row in rows:
        if row["status"] != "ok" or row["gate"] is None:
            continue
        days = schedules[row["market"]]
        a, b = days.get_loc(row["signal"]), days.get_loc(row["gate"])
        k = b + horizon
        if k >= len(days) or days[k] > pd.Timestamp(completed_through):
            continue
        frame = frames[row["ticker"]].reindex(days)
        ca, cb, ck = frame.Close.iloc[[a, b, k]]
        oa, ob = frame.Open.iloc[[a+1, b+1]]
        if not all(np.isfinite(v) and v > 0 for v in (ca, cb, ck, oa, ob)):
            continue
        pairs.append(dict(kind=row["kind"], old=ck/ca-ck/cb,
                          open_same_end=ck/oa-ck/ob, new=row["difference"]))
    return {kind: {"count": len(g), "median_pp": {
        key: float(np.median([r[key] for r in g]) * 100) for key in ("old", "open_same_end", "new")}}
        for kind in ("stock", "ETF") if (g := [r for r in pairs if r["kind"] == kind])}


def main():
    """CLI stores all detailed inputs/results in an explicit PRIVATE directory."""
    import argparse
    import hashlib
    import json
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("kinds", type=Path, help='Private JSON mapping ticker to stock or ETF')
    parser.add_argument("out", type=Path, help="Private directory, never commit")
    parser.add_argument("--completed-through", required=True)
    parser.add_argument("--gate-observed-through", required=True,
                        help="Last date covered by saved gate observations, NOT price fetch date")
    parser.add_argument("--refresh", action="store_true", help="Replace research snapshot explicitly")
    args = parser.parse_args()
    events = read_saved_events(args.events)
    kinds = json.loads(args.kinds.read_text(encoding="utf-8"))
    if not events or any(kinds.get(e["ticker"]) not in ("stock", "ETF") for e in events):
        raise ValueError("Require events and an explicit asset class for every ticker")
    args.out.mkdir(parents=True, exist_ok=True)
    price_path, schedule_path = args.out / "prices.pkl", args.out / "sessions.pkl"
    cutoff = pd.Timestamp(args.completed_through)
    if args.refresh or not price_path.exists() or not schedule_path.exists():
        import exchange_calendars as calendars
        import yfinance as yf
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from stock_lab_core.yahoo_transport import yahoo_session_kwargs

        tickers = sorted({e["ticker"] for e in events})
        start = min(e["signal"] for e in events).date().isoformat()
        raw = yf.download(tickers, start=start, end=(cutoff + pd.Timedelta(days=1)).date().isoformat(),
                          interval="1d", auto_adjust=False, group_by="ticker", progress=False,
                          threads=4, timeout=20, **yahoo_session_kwargs())
        frames = {}
        for ticker in tickers:
            frame = raw[ticker].copy() if isinstance(raw.columns, pd.MultiIndex) else raw.copy()
            frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
            frames[ticker] = frame  # retain missing rows; no forward-fill or dropna
        schedules = {region: calendars.get_calendar(code, start=start, end=cutoff).sessions.tz_localize(None)
                     for region, code in (("KR", "XKRX"), ("US", "XNYS"))}
        pd.to_pickle(frames, price_path)
        pd.to_pickle(schedules, schedule_path)
        (args.out / "source.json").write_text(json.dumps(dict(
            fetched_at=datetime.now(timezone.utc).isoformat(), completed_through=str(cutoff.date()),
            source="Yahoo daily OHLC auto_adjust=False", yfinance=yf.__version__,
            calendar_version=calendars.__version__, start=start, requested=len(tickers)), indent=2), encoding="utf-8")
    # Only load snapshots produced locally by this CLI, never untrusted pickles.
    source = json.loads((args.out / "source.json").read_text(encoding="utf-8"))
    if pd.Timestamp(source["completed_through"]) < cutoff or pd.Timestamp(source["start"]) > min(e["signal"] for e in events):
        raise ValueError("Snapshot does not cover requested dates; use --refresh")
    frames, schedules = pd.read_pickle(price_path), pd.read_pickle(schedule_path)
    if any(e["ticker"] not in frames for e in events):
        raise ValueError("Snapshot does not cover requested tickers; use --refresh")
    summary = {"method": "saved_events_next_open_signal_plus_60", "completed_through": str(cutoff.date()),
               "gate_observed_through": args.gate_observed_through, "source": source, "costs": {}}
    detailed = []
    for cost in (0, 10, 30):
        rows = []
        for event in events:
            row = {**event, "kind": kinds[event["ticker"]], "cost_bps": cost,
                   **evaluate_event(frames[event["ticker"]], schedules[event["market"]],
                       event["signal"], event["gate"], completed_through=cutoff,
                       gate_observed_through=args.gate_observed_through, cost_bps=cost)}
            rows.append(row)
        summary["costs"][str(cost)] = anonymous_summary(rows)
        if cost == 0:
            summary["paired_conventions"] = paired_conventions(rows, frames, schedules, cutoff)
        detailed.extend(rows)
    pd.DataFrame(detailed).to_csv(args.out / "events_next_open.csv", index=False, encoding="utf-8-sig")
    summary["input_hashes"] = {key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in (("events", args.events), ("kinds", args.kinds), ("prices", price_path), ("sessions", schedule_path))}
    (args.out / "anonymous_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
