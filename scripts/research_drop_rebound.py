"""Offline replay: buy after a −X% drop, sell at +10% / +20% over own cost.

Research only (short-term criteria follow-up ③, 2026-11-27). Never imported by the
app and never changes scores, weights, gates or buy conditions.

Data: Yahoo chart API daily bars (split-adjusted, not dividend-adjusted). Pass a
saved JSON with --json, or --fetch to download. Missing bars are dropped and
counted; nothing is interpolated.

Rules fixed before looking at results:
- Signal at a completed daily close; entry at the NEXT regular open (no look-ahead).
  A close-entry sensitivity is reported separately.
- Take profit: limit at entry*(1+tp). If the day's open is already above, fill at
  the open; otherwise fill at the limit when High reaches it.
- Optional stop at entry*(1-stop): gap below fills at the open; if stop and target
  are both inside the same bar, the stop is counted first (conservative).
- Max holding N trading days: exit at that day's close. "none" = hold until hit;
  a still-open trade at the end of data is reported as open, never as a win.
- Cost: per-side percent (commission + spread + FX), deducted on both sides.
- Event-matched comparison: each drop *episode* gives one entry; every exit rule is
  replayed on the same entries (overlap allowed). Sequential one-position replay
  is reported separately for strategy MDD and trade count.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

YAHOO = "https://query2.finance.yahoo.com/v8/finance/chart/{t}?period1=0&period2=4102444800&interval=1d&events=div,splits"


def load_yahoo(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = path.read_bytes()
    r = json.loads(raw)["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    idx = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert(r["meta"].get("exchangeTimezoneName", "UTC")).normalize().tz_localize(None)
    f = pd.DataFrame({k.capitalize(): q[k] for k in ("open", "high", "low", "close", "volume")}, index=idx)
    before = len(f)
    f = f.dropna(subset=["Open", "High", "Low", "Close"])
    f = f[(f[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    f = f[~f.index.duplicated(keep="last")]
    meta = {"sha256": hashlib.sha256(raw).hexdigest()[:16], "rows": len(f), "dropped": before - len(f),
            "first": str(f.index[0].date()), "last": str(f.index[-1].date())}
    return f, meta


# ---- "−20%" reference definitions -------------------------------------------------

def signal_series(f: pd.DataFrame, basis: str, drop: float) -> pd.Series:
    c = f.Close
    if basis.startswith("peak"):              # close vs highest close of last N days (incl. today)
        n = int(basis[4:])
        ref = c.rolling(n, min_periods=n).max()
    elif basis.startswith("ret"):             # close vs close N days ago
        n = int(basis[3:])
        ref = c.shift(n)
    else:
        raise ValueError(basis)
    return (c / ref - 1) <= -drop


def episodes(sig: pd.Series, f: pd.DataFrame, basis: str, drop: float, rearm: float) -> list[int]:
    """First signal day of each episode. Re-arm once the same measure recovers above −rearm."""
    c = f.Close
    if basis.startswith("peak"):
        n = int(basis[4:]); dd = c / c.rolling(n, min_periods=n).max() - 1
    else:
        n = int(basis[3:]); dd = c / c.shift(n) - 1
    out, armed = [], True
    for i, (s, d) in enumerate(zip(sig.to_numpy(), dd.to_numpy())):
        if armed and s:
            out.append(i); armed = False
        elif not armed and not math.isnan(d) and d > -rearm:
            armed = True
    return out


# ---- one trade ------------------------------------------------------------------

def run_trade(f, sig_i, tp, stop, max_hold, cost, entry="open"):
    o, h, l, c = (f[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    if entry == "open":
        e_i = sig_i + 1
        if e_i >= len(f):
            return None
        px = o[e_i]; first = e_i
    else:
        e_i = sig_i; px = c[e_i]; first = e_i + 1
    target = px * (1 + tp)
    stop_px = px * (1 - stop) if stop else None
    mae = 0.0
    last = len(f) - 1 if max_hold is None else min(len(f) - 1, e_i + max_hold - 1)
    j = e_i
    for j in range(first, last + 1):
        if entry == "open" and j == e_i:
            bar_o = None                       # entered at this open; only H/L/C after
        else:
            bar_o = o[j]
        if stop_px is not None and bar_o is not None and bar_o <= stop_px:
            return _done(px, bar_o, e_i, j, "gap_stop", mae, cost, f)
        if bar_o is not None and bar_o >= target:
            return _done(px, bar_o, e_i, j, "target_gap", min(mae, l[j] / px - 1), cost, f)
        mae = min(mae, l[j] / px - 1)
        if stop_px is not None and l[j] <= stop_px:
            return _done(px, stop_px, e_i, j, "stop", mae, cost, f)
        if h[j] >= target:
            return _done(px, target, e_i, j, "target", mae, cost, f)
    if max_hold is not None and last == e_i + max_hold - 1:
        return _done(px, c[last], e_i, last, "time", mae, cost, f)
    t = _done(px, c[len(f) - 1], e_i, len(f) - 1, "open_end", mae, cost, f)
    return t


def _done(px, out, e_i, x_i, why, mae, cost, f):
    gross = out / px - 1
    net = (out * (1 - cost)) / (px * (1 + cost)) - 1
    return dict(entry_date=str(f.index[e_i].date()), exit_date=str(f.index[x_i].date()), entry=px, exit=out,
                reason=why, hold_days=x_i - e_i + 1, gross=gross, net=net, mae=mae, e_i=e_i, x_i=x_i)


def summarize(trades):
    closed = [t for t in trades if t["reason"] != "open_end"]
    opened = [t for t in trades if t["reason"] == "open_end"]
    if not closed:
        return dict(n=0, open=len(opened))
    net = np.array([t["net"] for t in closed])
    hold = np.array([t["hold_days"] for t in closed])
    return dict(n=len(closed), open=len(opened), win=float((net > 0).mean()), hit=float(np.mean([t["reason"].startswith("target") for t in closed])),
                mean=float(net.mean()), median=float(np.median(net)), worst=float(net.min()),
                mae=float(min(t["mae"] for t in closed)), hold_mean=float(hold.mean()), hold_median=float(np.median(hold)),
                hold_max=int(hold.max()), open_mark=[round(t["net"], 4) for t in opened])


def sequential(f, sig, tp, stop, max_hold, cost):
    """One position at a time, full capital, next signal day after exit."""
    trades, i, s = [], 0, sig.to_numpy()
    eq, peak, mdd = 1.0, 1.0, 0.0
    while i < len(f) - 1:
        if not s[i]:
            i += 1; continue
        t = run_trade(f, i, tp, stop, max_hold, cost)
        if t is None:
            break
        # mark-to-market MDD inside the trade on closes, then realize
        closes = f.Close.to_numpy()[t["e_i"]:t["x_i"] + 1]
        for cpx in closes:
            v = eq * cpx / t["entry"]
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)
        eq *= 1 + t["net"]; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        trades.append(t)
        i = t["x_i"] + 1
    return trades, eq, mdd


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    f, meta = load_yahoo(a.json)
    if a.start:
        f = f[f.index >= a.start]
    bases = ["peak20", "peak60", "peak252", "ret5", "ret1"]
    tps = [0.10, 0.20]
    holds = [10, 20, 60, None]
    stops = [None, 0.10, 0.20]
    costs = [0.001, 0.0025, 0.005]
    rows, trade_rows = [], []
    for basis in bases:
        sig = signal_series(f, basis, 0.20)
        ep = episodes(sig, f, basis, 0.20, 0.10)
        for hold in holds:
            for stop in stops:
                for cost in costs:
                    for tp in tps:
                        tr = [t for t in (run_trade(f, i, tp, stop, hold, cost) for i in ep) if t]
                        s = summarize(tr)
                        seq, eq, mdd = sequential(f, sig, tp, stop, hold, cost)
                        s.update(basis=basis, tp=tp, hold=hold or "none", stop=stop or "none", cost=cost,
                                 signal_days=int(sig.sum()), episodes=len(ep),
                                 seq_n=len(seq), seq_final=eq, seq_mdd=mdd)
                        rows.append(s)
                        if cost == 0.0025 and stop is None and hold == 60:
                            for t in tr:
                                trade_rows.append(dict(basis=basis, tp=tp, **{k: v for k, v in t.items() if k not in ("e_i", "x_i")}))
    # close-entry sensitivity for the base case
    sens = []
    for basis in bases:
        sig = signal_series(f, basis, 0.20)
        ep = episodes(sig, f, basis, 0.20, 0.10)
        for tp in tps:
            tr = [t for t in (run_trade(f, i, tp, None, 60, 0.0025, entry="close") for i in ep) if t]
            s = summarize(tr); s.update(basis=basis, tp=tp, entry="close"); sens.append(s)
    out = dict(meta=meta, start=a.start, rows=rows, close_entry=sens, trades=trade_rows)
    text = json.dumps(out, ensure_ascii=False, indent=1, default=float)
    if a.out:
        a.out.write_text(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
