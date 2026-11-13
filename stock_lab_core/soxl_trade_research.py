"""Prefix-only SOXX signals and SOXL execution proxies; isolated research, not a gate."""

from collections import Counter
import math

import numpy as np
import pandas as pd

from stock_lab_core.chart_structure import build_parallel_channel
from stock_lab_core.soxl_short_observation import completed_hour_grid, completed_hour_frame, HOUR
from stock_lab_core.soxl_trade_plan import OHLC, RULE, price_plan, setup_from_channel
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def signal_rows(frame):
    rows = []
    for i in range(139, len(frame)):
        prefix = frame.iloc[i - 139:i + 1]
        if prefix[OHLC].isna().any().any():
            continue
        channel = build_parallel_channel(prefix)
        if not channel or pd.Timestamp(channel["known_at"]) > prefix.index[-1]:
            continue
        plan, _ = setup_from_channel(prefix, channel)
        if plan:
            rows.append(dict(time=prefix.index[-1] + HOUR, formation=str(channel["formation_id"]),
                             soxx_stop=plan["stop"], soxx_upper=plan["target"]))
    return rows


def execution_grid(schedule, now):
    rows = []
    for day in schedule.itertuples():
        for start in pd.date_range(day.market_open, day.market_close, freq="1h", inclusive="left"):
            end = min(start + HOUR, day.market_close)
            if end <= now:
                rows.append((start, end, day.market_close))
    return pd.DataFrame(rows, columns=["start", "end", "session_close"])


def protective_exit(bar, plan):
    """Conservative OHLC ordering; stop first if both touched, gap stop at Open."""
    if bar.Open <= plan["stop"]:
        return float(bar.Open), "gap_stop", False
    if bar.Open >= plan["target"]:
        return plan["target"], "target", False
    stop_hit, target_hit = bar.Low <= plan["stop"], bar.High >= plan["target"]
    if stop_hit:
        return plan["stop"], "price_stop", bool(target_hit)
    if target_hit:
        return plan["target"], "target", False
    return None, None, False


def simulate(observations, soxx, soxl, slots, *, same_day=True, cost_bps=10, gates=None):
    """Both replay policies share entry/stop/target; exact historical gates optional."""
    trades, rejected, used = [], Counter(), set()
    busy = pd.Timestamp.min.tz_localize("UTC")
    if slots.empty:
        return trades, {"execution_bars_missing": 1}
    starts = pd.DatetimeIndex(slots.start)
    for signal in observations:
        at = signal["time"]
        if at <= busy or signal["formation"] in used:
            continue
        if gates is not None and gates.get(at) is not True:
            rejected["gate_blocked_or_unknown"] += 1
            continue
        if at not in starts or at not in soxx.index or at not in soxl.index or at - HOUR not in soxl.index:
            rejected["entry_missing"] += 1
            continue
        ix = starts.get_loc(at)
        values = [soxx.at[at, "Open"], soxl.at[at, "Open"], soxl.at[at - HOUR, "Low"]]
        if not np.isfinite(values).all():
            rejected["entry_missing"] += 1
            continue
        xentry, entry, stop = map(float, values)
        if not signal["soxx_stop"] < xentry < signal["soxx_upper"] or 2 * xentry - signal["soxx_stop"] > signal["soxx_upper"]:
            rejected["entry_outside_soxx_plan"] += 1
            continue
        plan = price_plan(entry, stop)
        if not plan:
            rejected["invalid_soxl_stop"] += 1
            continue
        used.add(signal["formation"])
        close = slots.iloc[ix].session_close
        pending, exit_price, reason, ambiguous, hours, low = False, None, None, False, 0, entry
        exit_at, end = at, at
        for slot in slots.iloc[ix:].itertuples():
            start, end = slot.start, slot.end
            if same_day and start >= close:
                break
            if start not in soxx.index or start not in soxl.index:
                reason = "path_missing"
                break
            xb, lb = soxx.loc[start], soxl.loc[start]
            if not np.isfinite(xb[OHLC].to_numpy(dtype=float)).all() or not np.isfinite(lb[OHLC].to_numpy(dtype=float)).all():
                reason = "path_missing"
                break
            if pending:
                exit_price, reason, exit_at = float(lb.Open), "soxx_stop_next_open", start
                low = min(low, exit_price)
                break
            exit_price, reason, ambiguous = protective_exit(lb, plan)
            if exit_price is not None:
                # Intrabar path after exit is unknown; MAE is a conservative whole-bar bound.
                low = min(low, float(lb.Low), exit_price)
                exit_at = end
                break
            low = min(low, float(lb.Low))
            if same_day and end == close:
                exit_price, reason, exit_at = float(lb.Close), "session_close_proxy", end
                break
            if end - start == HOUR:
                hours += 1
                if xb.Close < signal["soxx_stop"]:
                    pending = True
                if hours >= 18:
                    exit_price, reason, exit_at = float(lb.Close), "18h_close_proxy", end
                    break
        busy = exit_at if exit_price is not None else end
        if exit_price is None:
            rejected[reason or "right_censored"] += 1
            continue
        cost = cost_bps / 10000
        trades.append(dict(signal_time=at, entry_time=at, exit_time=exit_at, entry=entry,
                           stop=stop, target=plan["target"], exit=exit_price, reason=reason,
                           net_pct=(exit_price * (1 - cost) / (entry * (1 + cost)) - 1) * 100,
                           mae_bound_pct=(low / entry - 1) * 100, ambiguous=ambiguous,
                           overnight=at.tz_convert("America/New_York").date() != exit_at.tz_convert("America/New_York").date()))
    return trades, dict(rejected)


def summarize(trades):
    if not trades:
        return dict(n=0, wins=0, win_pct=None, interval=None, mean_pct=None, worst_pct=None, mdd_pct=None, mae_pct=None)
    pnl = np.array([t["net_pct"] for t in trades], dtype=float)
    n, wins = len(pnl), int((pnl > 0).sum())
    p, z = wins / n, 1.96
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    radius = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    equity = np.r_[1., np.cumprod(1 + pnl / 100)]
    return dict(n=n, wins=wins, win_pct=p * 100, interval=((center-radius)*100, (center+radius)*100),
                mean_pct=float(pnl.mean()), worst_pct=float(pnl.min()),
                mdd_pct=float((equity / np.maximum.accumulate(equity) - 1).min()*100),
                mae_pct=min(t["mae_bound_pct"] for t in trades))


def compare_policies(day, overnight):
    left = {t["entry_time"]: t["net_pct"] for t in day}
    right = {t["entry_time"]: t["net_pct"] for t in overnight}
    keys = left.keys() & right.keys()
    delta = [left[k] - right[k] for k in keys]
    return dict(paired=len(keys), day_better=sum(d > 1e-8 for d in delta),
                day_worse=sum(d < -1e-8 for d in delta),
                max_saved_pp=max([0., *delta]), max_forgone_pp=max([0., *[-d for d in delta]]),
                unpaired=len(left.keys() ^ right.keys()))


def replay(frames, schedule, now):
    slots = execution_grid(schedule, pd.Timestamp(now))
    if slots.empty:
        return {"rule": RULE, "issue": "완료 정규장 자료 없음", "policies": {}}
    grid = pd.DatetimeIndex(slots.start)
    clean = {ticker: completed_hour_frame(frames.get(ticker), grid)[0].reindex(grid) for ticker in ("SOXX", "SOXL")}
    if any(not set(OHLC).issubset(f.columns) for f in clean.values()):
        return {"rule": RULE, "issue": "SOXX/SOXL 동시각 OHLC 미확보", "policies": {}}
    hourly = clean["SOXX"].reindex(completed_hour_grid(schedule, now))
    observations = signal_rows(hourly)
    policies = {}
    midpoint = grid[0] + (grid[-1] - grid[0]) / 2
    for same_day in (True, False):
        trades, rejected = simulate(observations, clean["SOXX"], clean["SOXL"], slots, same_day=same_day)
        costly, _ = simulate(observations, clean["SOXX"], clean["SOXL"], slots, same_day=same_day, cost_bps=20)
        policies["day" if same_day else "overnight"] = dict(stats=summarize(trades), trades=trades, rejected=rejected,
            early=summarize([t for t in trades if t["entry_time"] < midpoint]),
            late=summarize([t for t in trades if t["entry_time"] >= midpoint]), cost20=summarize(costly))
    return dict(rule=RULE, issue="", policies=policies, first=grid[0], last=slots.end.iloc[-1],
                bars=len(grid), missing={t: int(f[OHLC].isna().any(axis=1).sum()) for t,f in clean.items()},
                gate_history="미확보 · 시장방어 적용 승률 아님", signals=len(observations),
                comparison=compare_policies(policies["day"]["trades"], policies["overnight"]["trades"]))
