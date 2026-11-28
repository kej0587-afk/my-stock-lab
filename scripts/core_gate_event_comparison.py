"""Offline research: regenerate events under two alignments of one frozen snapshot.

No production policy changes, live queries, or private identifiers in the public
summary. CLI input pickle must be a trusted locally produced research snapshot.
Signal rules match sim_core_first_buy; execution uses core_first_buy_next_open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

try:
    from . import sim_core_first_buy as replay
    from .core_first_buy_next_open import evaluate_event, anonymous_summary
except ImportError:
    import sim_core_first_buy as replay
    from core_first_buy_next_open import evaluate_event, anonymous_summary


def recovery_events(frame, gate, bench_close, sessions, region):
    """Same MA/RS predicate, first signal per closed episode; no bool identity test.

    Use explicit exchange sessions for the first opening, even when the asset has
    a missing price row. Never extend the gate-observation cutoff by forward-fill.
    Close-only observation rows match the legacy research's rolling-bar contract.
    """
    c = frame.Close.dropna()
    ma50, ma20 = c.rolling(50).mean(), c.rolling(20).mean()
    below = (c < ma50).astype(float).rolling(replay.BELOW_MA50_DAYS).sum().shift(1)
    bench = bench_close.reindex(c.index, method="ffill")
    rs = c / c.shift(20) - bench / bench.shift(20)
    signal = (c > ma50) & (c.shift(1) <= ma50.shift(1)) & (below >= replay.BELOW_MA50_DAYS) & (c > ma20) & (rs > 0)
    observed = pd.DatetimeIndex(sessions)
    observed = observed[(observed >= gate.index.min()) & (observed <= gate.index.max())]
    closed = gate[f"closed_{region}"].reindex(observed, method="ffill")
    rows, end = [], None
    for day in c.index[signal.fillna(False)]:
        if day not in closed.index or pd.isna(closed.loc[day]) or not bool(closed.loc[day]):
            continue
        if end is not None and day <= end:
            continue
        opened = closed.loc[closed.index > day].eq(False)
        opening = opened.index[opened][0] if opened.any() else None
        end = opening if opening is not None else observed[-1]
        rows.append({"signal":day, "gate":opening})
    return rows


def generate_gates(bench, flow, *, legacy):
    if not legacy:
        return {v:replay.replay_gate(bench, flow, v) for v in ("KR", "US")}
    aligned = replay.flow_score_series
    # Only baseline alignment changes: same formulas, benchmarks and thresholds.
    with patch.object(replay, "flow_score_series", lambda f,d,**kw:aligned(f,d,view="US")):
        return {v:replay.replay_gate(bench, flow, v) for v in ("KR", "US")}


def paired_summary(before, after):
    key = lambda r:(r["ticker"], r["signal"])
    old, new = {key(r):r for r in before}, {key(r):r for r in after}
    common = old.keys() & new.keys()
    result = {"common":len(common), "added":len(new.keys()-old.keys()), "removed":len(old.keys()-new.keys()),
              "gate_date_changed":sum(old[k]["gate"] != new[k]["gate"] for k in common), "groups":{}}
    for kind in ("stock", "ETF"):
        keys = [k for k in common if old[k]["kind"]==kind and old[k]["status"]==new[k]["status"]=="ok"]
        changes = [new[k]["difference"]-old[k]["difference"] for k in keys]
        # A's date/price/end must be identical for a shared signal.
        for k in keys:
            assert old[k]["end"] == new[k]["end"] and old[k]["A_return"] == new[k]["A_return"]
        result["groups"][kind] = {"paired_valid":len(keys),
            "difference_change_mean":float(np.mean(changes)) if changes else None,
            "difference_change_median":float(np.median(changes)) if changes else None,
            "return_changed":sum(abs(x)>1e-12 for x in changes)}
    return result


def run_study(snapshot):
    cutoff = pd.Timestamp(snapshot["cutoff"])
    frames = {t:f.loc[:cutoff].copy() for t,f in snapshot["frames"].items()}
    closes = {t:f.dropna(subset=["Close"]) for t,f in frames.items()}
    bench = {t:closes[t] for t,_ in replay.BENCH}
    if any(f.empty for f in bench.values()):
        raise ValueError("Missing benchmark: a comparable gate cannot be built")
    requested = snapshot["flow_tickers"]
    flow = {t:closes[t] for t in requested if t in closes and not closes[t].empty}
    if not flow:
        raise ValueError("No flow observations")
    sessions = {r:ds[ds<=cutoff] for r,ds in snapshot["sessions"].items()}
    gates, detailed, summary = {}, {}, {"source":snapshot.get("source", {}),
        "coverage":{"candidates":len(snapshot["kinds"]), "flow_requested":len(requested),
                    "flow_available":len(flow), "benchmarks":len(bench)}, "versions":{}, "paired":{}}
    for version in ("before", "after"):
        gates[version] = generate_gates(bench, flow, legacy=version=="before")
        records, missing = [], 0
        for ticker,kind in snapshot["kinds"].items():
            region = snapshot["markets"][ticker]
            f = closes.get(ticker)
            if f is None or len(f)<120:
                missing += 1
                continue
            gate = gates[version][region]
            ref = bench["^KS11" if region=="KR" else "^GSPC"].Close
            for event in recovery_events(f, gate, ref, sessions[region], region):
                for cost in (0,10,30):
                    records.append({"ticker":ticker,"market":region,"kind":kind,"cost_bps":cost,**event,
                        **evaluate_event(frames[ticker],sessions[region],event["signal"],event["gate"],
                            completed_through=cutoff,gate_observed_through=gate.index.max(),cost_bps=cost)})
        detailed[version] = records
        summary["versions"][version] = {"insufficient_candidates":missing, "costs":{
            str(cost):anonymous_summary([r for r in records if r["cost_bps"]==cost]) for cost in (0,10,30)}}
    for cost in (0,10,30):
        summary["paired"][str(cost)] = paired_summary(
            [r for r in detailed["before"] if r["cost_bps"]==cost],
            [r for r in detailed["after"] if r["cost_bps"]==cost])
    pd.testing.assert_frame_equal(gates["before"]["US"],gates["after"]["US"])
    old,new=gates["before"]["KR"],gates["after"]["KR"]
    changed=old.ne(new)&~(old.isna()&new.isna())
    summary["gate_comparison"]={"rows":len(old),"KR_changed_rows":int(changed.any(axis=1).sum()),
        "KR_closed_changed":int(changed.closed_KR.sum()),"US_changed_rows":0,
        "first":str(old.index.min().date()),"last":str(old.index.max().date())}
    us_old=[r for r in detailed["before"] if r["market"]=="US"]
    us_new=[r for r in detailed["after"] if r["market"]=="US"]
    assert us_old == us_new
    return summary,detailed,gates


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot",type=Path)
    parser.add_argument("private_out",type=Path)
    args=parser.parse_args()
    summary,details,gates=run_study(pd.read_pickle(args.snapshot))
    summary["snapshot_sha256"]=hashlib.sha256(args.snapshot.read_bytes()).hexdigest()
    args.private_out.mkdir(parents=True,exist_ok=True)
    for version,rows in details.items():
        pd.DataFrame(rows).to_csv(args.private_out/f"{version}_events.csv",index=False,encoding="utf-8-sig")
        for region,g in gates[version].items():
            g.to_csv(args.private_out/f"{version}_gate_{region}.csv")
    (args.private_out/"anonymous_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__":
    main()
