"""Research replay: first buy of an unheld long-term candidate that recovers before the market.

Not an operating rule. Compares, with the same amount, buying at the stock's own recovery signal
while the replayed market gate is closed (A) versus buying at the first day the replayed gate opens (B).

Replayed gate ("가격·돈흐름 재현 게이트") = the app's regional benchmark score (build_today_market_guard
benchmarks, same thresholds) + its money-flow breadth/acceleration score. Macro, event and portfolio
parts are not replayable from price history and are treated as 0 (미확인), so the real gate may have
been closed on more days than this replay shows.

Usage: python scripts/sim_core_first_buy.py UNIVERSE_FILE OUT_DIR
UNIVERSE_FILE: one line "TICKER:KR|US:S|E:R|A,..." (kept outside Git: it is the user's watchlist).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BENCH = [("^KS11", "KR"), ("^KQ11", "KR"), ("069500.KS", "KR"), ("229200.KS", "KR"),
         ("^GSPC", "US"), ("^IXIC", "US"), ("^DJI", "US"), ("SPY", "US"), ("QQQ", "US"), ("IWM", "US")]
START = "2018-06-01"
HOLD_AFTER_OPEN = 60          # same end date for A and B: gate-open day + 60 trading days
BELOW_MA50_DAYS = 20          # stock was below MA50 at least this many of the prior days
FAIL_WINDOW = 10              # back below MA50 within N days = failed rebound


def download(tickers):
    import yfinance as yf
    frames = {}
    for i in range(0, len(tickers), 40):
        chunk = tickers[i:i + 40]
        raw = yf.download(chunk, start=START, interval="1d", auto_adjust=False, group_by="ticker",
                          progress=False, threads=True)
        for t in chunk:
            try:
                f = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                f = f.dropna(subset=["Close"])
                f.index = pd.DatetimeIndex(f.index).tz_localize(None).normalize()
                if len(f):
                    frames[t] = f
            except KeyError:
                pass
    return frames


def bench_row(close: pd.Series) -> dict | None:
    """Same per-benchmark fields as _calc_today_benchmark_guard_row (close ends at the as-of day)."""
    if len(close) < 25:
        return None
    last = float(close.iloc[-1])
    d1 = last / float(close.iloc[-2]) - 1
    d5 = last / float(close.iloc[-6]) - 1
    diffs = close.diff().tail(8).dropna().tolist()
    streak = 0
    for v in reversed(diffs):
        if v < 0:
            streak += 1
        else:
            break
    return {"d1": d1, "d5": d5, "below20": last < float(close.tail(20).mean()),
            "below50": len(close) >= 50 and last < float(close.tail(50).mean()), "streak": streak}


def region_stats(rows: list[dict]) -> dict:
    """Same thresholds as _today_benchmark_guard_stats."""
    if not rows:
        return {"score": 0, "mode": "데이터부족", "circuit": 0, "panic": 0, "strong": 0, "max_gain": np.nan}
    below20 = sum(r["below20"] for r in rows)
    below50 = sum(r["below50"] for r in rows)
    down3 = sum(r["streak"] >= 3 for r in rows)
    weak5 = sum(r["d5"] <= -0.03 for r in rows)
    sharp = sum(r["d1"] <= -0.015 for r in rows)
    panic = sum(r["d1"] <= -0.05 for r in rows)
    circuit = sum(r["d1"] <= -0.08 for r in rows)
    score = 0
    if circuit >= 1:
        score += 5
    elif panic >= 1:
        score += 3
    score += 2 if below20 >= 3 else 1 if below20 >= 2 else 0
    score += 2 if below50 >= 2 else 0
    score += 2 if down3 >= 2 else 0
    score += 2 if weak5 >= 2 else 0
    score += 1 if sharp >= 2 else 0
    if circuit >= 1 or panic >= 2:
        mode = "비상"
    elif score >= 8:
        mode = "위험"
    elif score >= 5:
        mode = "방어"
    elif score >= 2:
        mode = "주의"
    else:
        mode = "정상"
    return {"score": score, "mode": mode, "circuit": circuit, "panic": panic,
            "strong": sum(r["d1"] >= 0.03 for r in rows), "max_gain": max(r["d1"] for r in rows)}


def flow_score_series(flow_frames: dict, days: pd.DatetimeIndex, *, view: str = "US") -> pd.DataFrame:
    """Align each listing market BEFORE computing cross-market breadth.

    Inputs use unique, ordered, naive daily session dates (download() contract).
    KR view sees domestic closes <= d but US closes strictly < d. US view sees
    both <= d. A Korean-listed US-asset ETF is domestic by listing, not exposure.
    Select the latest preceding source date, not a shift over available rows:
    on a US holiday yesterday's observed bar is already available in Korea.
    Preserve a selected NaN; do not backfill a missing metric with older data.
    This daily-session approximation does not model historical publication delays.
    """
    if view not in ("KR", "US"):
        raise ValueError("view must be KR or US")
    r3, acc = {}, {}
    for t, f in flow_frames.items():
        target = days
        if view == "KR" and not t.endswith((".KS", ".KQ")):
            if re.fullmatch(r"[A-Z][A-Z0-9]*", t) is None:
                raise ValueError(f"Unknown flow listing market: {t}")
            target = days - pd.Timedelta(nanoseconds=1)
        c = f["Close"]
        ret3 = c / c.shift(63) - 1
        prev3 = c.shift(63) / c.shift(126) - 1
        r3[t] = ret3.reindex(target, method="ffill").set_axis(days)
        acc[t] = (ret3 - prev3).reindex(target, method="ffill").set_axis(days)
    r3, acc = pd.DataFrame(r3), pd.DataFrame(acc)
    breadth = r3.gt(0).where(r3.notna()).mean(axis=1)
    accel = acc.gt(0).where(acc.notna()).mean(axis=1)
    score = np.where(breadth < .35, 2, np.where(breadth < .50, 1, 0)) + np.where(accel < .35, 1, 0)
    return pd.DataFrame({"breadth": breadth, "accel": accel, "flow": score}, index=days)


def replay_gate(bench_frames: dict, flow_frames: dict, view: str) -> pd.DataFrame:
    """Per day, as seen from a `view` (KR or US) session: a KR session on date d closes before the US
    session of d, so the KR view sees US closes before d; the US view sees KR closes up to d."""
    days = pd.DatetimeIndex(sorted(set().union(*[f.index for f in bench_frames.values()])))
    days = days[days >= pd.Timestamp(START) + pd.Timedelta(days=200)]
    flow = flow_score_series(flow_frames, days, view=view)
    out = []
    closes = {t: f["Close"] for t, f in bench_frames.items()}
    for day in days:
        rows = {"KR": [], "US": []}
        for t, region in BENCH:
            c = closes.get(t)
            if c is None:
                continue
            c = c[c.index < day] if (view == "KR" and region == "US") else c[c.index <= day]
            if region == "US" and t == "SPY" and "^GSPC" in closes:
                continue   # unique_guard_benchmarks: ^GSPC and SPY are one observation
            row = bench_row(c.tail(80))
            if row:
                rows[region].append(row)
        kr, us = region_stats(rows["KR"]), region_stats(rows["US"])
        all_rows = rows["KR"] + rows["US"]
        regional = max(kr["score"], us["score"])
        fl = int(flow.at[day, "flow"]) if np.isfinite(flow.at[day, "breadth"]) else None
        whole = regional + (fl or 0)
        recovery_ok = (flow.at[day, "breadth"] >= .55) or (flow.at[day, "accel"] >= .50)
        any_circuit = sum(r["d1"] <= -0.08 for r in all_rows)
        any_panic = sum(r["d1"] <= -0.05 for r in all_rows)
        strong = sum(r["d1"] >= 0.03 for r in all_rows)
        max_gain = max((r["d1"] for r in all_rows), default=np.nan)
        tactical = (whole >= 8 and any_circuit == 0 and any_panic == 0 and bool(recovery_ok)
                    and (strong >= 2 or (np.isfinite(max_gain) and max_gain >= 0.05)))
        emergency = kr["mode"] == "비상" or us["mode"] == "비상"
        stop_all = (not emergency) and whole >= 8 and not tactical
        closed = {}
        for region, stats in (("KR", kr), ("US", us)):
            local_stop = stats["mode"] in {"비상", "위험"}
            whole_stop = emergency and kr["mode"] == "비상" and us["mode"] == "비상"
            closed[region] = bool(stop_all or local_stop or whole_stop)
        out.append({"day": day, "kr_score": kr["score"], "us_score": us["score"], "kr_mode": kr["mode"],
                    "us_mode": us["mode"], "flow": fl, "breadth": flow.at[day, "breadth"],
                    "accel": flow.at[day, "accel"], "whole": whole, "tactical": tactical,
                    "closed_KR": closed["KR"], "closed_US": closed["US"]})
    return pd.DataFrame(out).set_index("day")


def gate_closed_on(gates: dict, region: str, day: pd.Timestamp) -> bool | None:
    gate = gates[region]
    part = gate[gate.index <= day]
    return None if part.empty else bool(part[f"closed_{region}"].iloc[-1])


def events_for(ticker: str, region: str, frame: pd.DataFrame, gates: dict, bench_close: pd.Series):
    c, low = frame["Close"], frame.get("Low", frame["Close"])
    ma50, ma20 = c.rolling(50).mean(), c.rolling(20).mean()
    below = (c < ma50).astype(float).rolling(BELOW_MA50_DAYS).sum().shift(1)
    bench = bench_close.reindex(c.index, method="ffill")
    rs20 = (c / c.shift(20) - 1) - (bench / bench.shift(20) - 1)
    closed = pd.Series([gate_closed_on(gates, region, d) for d in c.index], index=c.index)
    signal = (c > ma50) & (c.shift(1) <= ma50.shift(1)) & (below >= BELOW_MA50_DAYS) & (c > ma20) & (rs20 > 0)
    rows, last_episode_end = [], None
    idx = list(c.index)
    for s in c.index[signal.fillna(False)]:
        if closed.get(s) is not True:
            continue
        if last_episode_end is not None and s <= last_episode_end:
            continue   # one event per closed-gate episode
        i = idx.index(s)
        later = closed.iloc[i + 1:]
        opened = later[later == False]  # noqa: E712
        fail = bool((c.iloc[i + 1:i + 1 + FAIL_WINDOW] < ma50.iloc[i + 1:i + 1 + FAIL_WINDOW]).any())
        row = {"티커": ticker, "시장": region, "신호일": s.date().isoformat(), "신호가": float(c.iloc[i]),
               "실패반등": "예" if fail else "아니오"}
        if opened.empty:
            row.update({"게이트 열림일": "미개방(자료 끝까지)", "기다린 거래일": None, "진입가 차이": None,
                        "먼저 산 뒤 최대 추가하락": float(low.iloc[i + 1:].min() / c.iloc[i] - 1) if i + 1 < len(c) else None,
                        "같은 종료일 평가액 차이": None, "종료일": "미확인"})
            last_episode_end = c.index[-1]
            rows.append(row)
            continue
        g = opened.index[0]
        j = idx.index(g)
        last_episode_end = g
        row.update({"게이트 열림일": g.date().isoformat(), "기다린 거래일": j - i,
                    "진입가 차이": float(c.iloc[j] / c.iloc[i] - 1),
                    "먼저 산 뒤 최대 추가하락": float(low.iloc[i + 1:j + 1].min() / c.iloc[i] - 1) if j > i else 0.0})
        k = j + HOLD_AFTER_OPEN
        if k >= len(c):
            row.update({"같은 종료일 평가액 차이": None, "종료일": "미확인(자료 부족)"})
        else:
            a_value = c.iloc[k] / c.iloc[i]
            b_value = c.iloc[k] / c.iloc[j]
            row.update({"같은 종료일 평가액 차이": float(a_value - b_value), "종료일": c.index[k].date().isoformat(),
                        "A 평가액": float(a_value), "B 평가액": float(b_value)})
        rows.append(row)
    return rows


def main(universe_file: str, out_dir: str):
    from stock_lab_core.money_flow import MONEY_FLOW_UNIVERSE
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    items = [x.split(":") for x in Path(universe_file).read_text().strip().split(",") if x]
    flow_tickers = sorted({u["ticker"] for u in MONEY_FLOW_UNIVERSE if u.get("구분") != "매크로"})
    bench_tickers = [t for t, _ in BENCH]
    frames = download(sorted(set(bench_tickers + flow_tickers + [i[0] for i in items])))
    bench = {t: frames[t] for t in bench_tickers if t in frames}
    flow = {t: frames[t] for t in flow_tickers if t in frames}
    gates = {view: replay_gate(bench, flow, view) for view in ("KR", "US")}
    for view, g in gates.items():
        g.to_csv(out / f"gate_replay_{view}.csv")
    events, missing = [], []
    for ticker, region, kind, source in items:
        f = frames.get(ticker)
        if f is None or len(f) < 120:
            missing.append({"티커": ticker, "시장": region, "사유": "가격 이력 없음 또는 120거래일 미만",
                            "이력": 0 if f is None else len(f)})
            continue
        ref = bench["^KS11" if region == "KR" else "^GSPC"]["Close"]
        events += events_for(ticker, region, f, gates, ref)
    pd.DataFrame(events).to_csv(out / "events.csv", index=False)
    pd.DataFrame(missing).to_csv(out / "missing.csv", index=False)
    def plain(row):
        return {k: (v.item() if isinstance(v, (np.floating, np.bool_, np.integer)) else v) for k, v in row.items()}
    meta = {"flow_alignment": {"KR": "KR <= session date; US < session date", "US": "all <= session date"},
            "flow_universe": len(flow), "flow_requested": len(flow_tickers), "bench": sorted(bench),
            "gate_first": str(gates["US"].index[0].date()), "gate_last": str(gates["US"].index[-1].date()),
            "closed_KR_days": int(gates["KR"]["closed_KR"].sum()), "KR_days": len(gates["KR"]),
            "closed_US_days": int(gates["US"]["closed_US"].sum()), "US_days": len(gates["US"]),
            "last_KR": plain(gates["KR"].iloc[-1].to_dict()), "last_US": plain(gates["US"].iloc[-1].to_dict())}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(meta, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main(*sys.argv[1:3])
