"""Research-only full candidate cohort selection and anonymous bias comparison.

Uses a dated private review export, not a retrospectively invented watchlist.
Operational scores, portfolio balances and policies are never modified.
"""
from __future__ import annotations

import pandas as pd

from scripts.core_first_buy_next_open import anonymous_summary


def canonical(ticker):
    text=str(ticker).strip().upper()
    if text.endswith((".KS", ".KQ")):
        text=text[:-3]
    return "BRK.B" if text=="BRK-B" else text


def _held(value):
    if value is True or str(value).strip().lower() in ("true", "1"):
        return True
    if value is False or str(value).strip().lower() in ("false", "0"):
        return False
    raise ValueError("Unknown holding state: do not silently include as unheld")


def select_candidates(master, holdings):
    """Freeze all explicitly unheld core rows; confirm against positive holdings."""
    quantity=pd.to_numeric(holdings["보유량"].astype(str).str.replace(",", "", regex=False),errors="coerce")
    if quantity.isna().any() or (quantity<0).any():
        raise ValueError("Invalid holdings quantity")
    held=set(holdings.loc[quantity.gt(0),"티커"].map(canonical))
    kinds,markets,seen={},{},set()
    excluded={"noncore":0,"held":0,"duplicate":0}
    for row in master.to_dict("records"):
        if row["bucket"] != "core":
            excluded["noncore"]+=1
            continue
        if _held(row["has_pos"]) or canonical(row["티커"]) in held:
            excluded["held"]+=1
            continue
        ticker=str(row["티커"]).strip()
        kind={"개별주":"stock","ETF":"ETF"}.get(row["유형"])
        market={"한국":"KR","미국":"US"}.get(row["시장"])
        if not ticker or ticker.lower()=="nan" or not kind or not market:
            raise ValueError("Incomplete candidate identity/type/market")
        key=canonical(ticker)
        if key in seen:
            prior=next(t for t in kinds if canonical(t)==key)
            if (kinds[prior],markets[prior]) != (kind,market):
                raise ValueError("Conflicting duplicate candidate")
            excluded["duplicate"]+=1
            continue
        seen.add(key);kinds[ticker]=kind;markets[ticker]=market
    return kinds,markets,excluded


def selection_summary(snapshot, details, original):
    """Separate event-conditioned performance from no-signal/missing candidates.

    No-event candidates are counted, not assigned fictitious zero-return trades.
    Every cohort exists before reading outcomes. No ticker identities in output.
    """
    full=set(snapshot["kinds"])
    if not set(original)<=full:
        raise ValueError("Expanded cohort must include the original cohort")
    groups={"original":set(original), "additional":full-set(original), "full":full}
    result={}
    for version,rows in details.items():
        result[version]={}
        for group,tickers in groups.items():
            records=[r for r in rows if r["ticker"] in tickers and r["cost_bps"]==10]
            event_tickers={r["ticker"] for r in records}
            missing={t for t in tickers if t not in snapshot["frames"] or
                     len(snapshot["frames"][t].loc[:snapshot["cutoff"]].Close.dropna())<120}
            no_signal=tickers-event_tickers-missing
            counts={"candidates":len(tickers),"event_candidates":len(event_tickers),
                "no_signal":len(no_signal),"insufficient":len(missing)}
            assert counts["candidates"]==sum(counts[k] for k in ("event_candidates","no_signal","insufficient"))
            result[version][group]={**counts,"event_results":anonymous_summary(records)}
    return result


def assert_frozen_extension(snapshot, base):
    """An extension may add candidate frames, never replace gate/source inputs."""
    for key in ("cutoff", "flow_tickers"):
        if snapshot[key] != base[key]:
            raise ValueError(f"Changed fixed input: {key}")
    if not set(base["kinds"])<=set(snapshot["kinds"]):
        raise ValueError("Original candidates were removed")
    for ticker in base["kinds"]:
        if (base["kinds"][ticker],base["markets"][ticker]) != (snapshot["kinds"][ticker],snapshot["markets"][ticker]):
            raise ValueError("Original candidate classification changed")
    for ticker,frame in base["frames"].items():
        pd.testing.assert_frame_equal(frame,snapshot["frames"][ticker],check_exact=True)
    for region,sessions in base["sessions"].items():
        pd.testing.assert_index_equal(sessions,snapshot["sessions"][region],exact=True)


def main():
    import argparse
    import hashlib
    import json
    from pathlib import Path
    from scripts.core_gate_event_comparison import run_study

    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expanded",type=Path)
    parser.add_argument("base",type=Path)
    parser.add_argument("private_out",type=Path)
    args=parser.parse_args()
    # Trusted local research snapshots only; pickle is not an upload format.
    snapshot,base=pd.read_pickle(args.expanded),pd.read_pickle(args.base)
    assert_frozen_extension(snapshot,base)
    summary,details,gates=run_study(snapshot)
    summary["selection"]=selection_summary(snapshot,details,base["kinds"])
    summary["snapshot_sha256"]=hashlib.sha256(args.expanded.read_bytes()).hexdigest()
    args.private_out.mkdir(parents=True,exist_ok=True)
    for version,rows in details.items():
        pd.DataFrame(rows).to_csv(args.private_out/f"{version}_events.csv",index=False,encoding="utf-8-sig")
        for region,frame in gates[version].items():
            frame.to_csv(args.private_out/f"{version}_gate_{region}.csv")
    (args.private_out/"anonymous_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"coverage":summary["coverage"],"selection":summary["selection"],"paired":summary["paired"]["10"]},ensure_ascii=False))


if __name__=="__main__":
    main()
