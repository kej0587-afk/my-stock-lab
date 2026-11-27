"""Conservative paired replay of frozen daily entries. Never imported by app."""

import math
import numpy as np
import pandas as pd

from soxl_drawdown_engine import DEFAULT, PRICE_COLUMNS


def expected_bars(schedule):
    parts = [pd.date_range(r.open, r.close, freq="5min", inclusive="left")
             for r in schedule.itertuples()]
    return parts[0].append(parts[1:]) if parts else pd.DatetimeIndex([], tz="UTC")


def audit_window(daily, bars, schedule, entry, p=DEFAULT):
    start = int(entry["entry_index"])
    days = daily.iloc[start:start + p.hold_sessions]
    wanted = expected_bars(schedule.loc[days.index])
    if len(wanted) == 0 or bars.empty or wanted[0] < bars.index.min() or wanted[-1] > bars.index.max():
        return None, "outside_available_5m", 0
    missing = wanted.difference(bars.index)
    if len(missing):
        return None, "missing_regular_5m", len(missing)
    selected = bars.loc[wanted]
    if selected.index.has_duplicates:
        return None, "duplicate_timestamp", 0
    values = selected[PRICE_COLUMNS].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        return None, "invalid_ohlc", 0
    if ((selected.High < selected[["Open", "Close", "Low"]].max(axis=1)) |
            (selected.Low > selected[["Open", "Close", "High"]].min(axis=1))).any():
        return None, "invalid_ohlc", 0
    for date, row in days.iterrows():
        session = schedule.loc[date]
        part = selected.loc[(selected.index >= session.open) & (selected.index < session.close)]
        aggregate = [part.Open.iloc[0], part.High.max(), part.Low.min(), part.Close.iloc[-1]]
        if any(abs(float(a) - float(row[c])) > max(.03, .001 * float(row[c]))
               for a, c in zip(aggregate, PRICE_COLUMNS)):
            return None, "daily_intraday_basis_mismatch", 0
    first_day = schedule.loc[days.index[0]]
    entry_bars = selected.loc[selected.index < first_day.close]
    if entry["entry_at_open"]:
        if abs(float(entry_bars.Open.iloc[0]) - entry["entry_raw"]) > max(.03, .001 * entry["entry_raw"]):
            return None, "entry_open_mismatch", 0
        entry_time = entry_bars.index[0]
    else:
        touched = entry_bars.loc[entry_bars.Low <= entry["trigger"]]
        if touched.empty or touched.Open.iloc[0] < entry["trigger"]:
            return None, "touch_fill_unreproducible", 0
        entry_time = touched.index[0]
    return selected.loc[entry_time:], "verified", 0


def simulate(bars, daily, entry, target, p=DEFAULT):
    stop, goal = entry["entry_fill"] * (1 - p.stop), entry["entry_fill"] * (1 + target)
    both, entry_high, reason = 0, 0, None
    for j, (stamp, row) in enumerate(bars.iterrows()):
        if j == 0 and not entry["entry_at_open"]:
            entry_high += int(row.High >= goal)
            if row.Low <= stop:
                raw, reason = stop, "stop"
        elif j > 0 and row.Open <= stop:
            raw, reason = float(row.Open), "stop_gap"
        elif j > 0 and row.Open >= goal:
            raw, reason = goal, "target_gap"
        else:
            sh, th = row.Low <= stop, row.High >= goal
            both += int(sh and th)
            if sh:
                raw, reason = stop, "stop_both"
            elif th:
                raw, reason = goal, "target"
        if reason:
            break
    else:
        stamp, raw = bars.index[-1], float(bars.Close.iloc[-1])
        reason = "horizon" if entry["entry_index"] + p.hold_sessions <= len(daily) else "data_end"
    exit_day = stamp.tz_convert("America/New_York").tz_localize(None).normalize()
    exit_index = daily.index.get_loc(exit_day)
    dividends = float(daily.iloc[int(entry["entry_index"]) + 1:exit_index + 1].Dividends.sum()) * entry["units"]
    proceeds = entry["units"] * raw * (1 - p.slippage) * (1 - p.commission)
    pnl = proceeds + dividends - entry["cash_amount"]
    return dict(entry, target=target, entry_time=bars.index[0].isoformat(), exit_time=stamp.isoformat(),
                exit_date=str(exit_day.date()), exit_raw=raw, exit_reason=reason,
                exit_proceeds=proceeds, dividends=dividends, net_pnl=pnl,
                net_return=pnl / entry["cash_amount"], target_hit=reason.startswith("target"),
                both_hit_bars=both, uncertain_entry_high=entry_high,
                holding_sessions=int(exit_index - entry["entry_index"] + 1))


def guard_at(entry_time, archive):
    """An explicit validity interval and known-at timestamp are mandatory."""
    if archive is None or archive.empty:
        return "unknown"
    t = pd.Timestamp(entry_time)
    matches = archive.loc[(pd.to_datetime(archive.known_at, utc=True) <= t) &
                          (pd.to_datetime(archive.valid_from, utc=True) <= t) &
                          (pd.to_datetime(archive.valid_until, utc=True) > t)]
    if matches.empty or matches.allowed.nunique() != 1:
        return "unknown"
    value = str(matches.allowed.iloc[-1]).lower()
    return "allowed" if value == "true" else "blocked" if value == "false" else "unknown"


def equity(bars, daily, trades, p=DEFAULT):
    cash, active, prev_day = p.capital, None, None
    entries = {pd.Timestamp(t["entry_time"]): t for t in trades}
    rows = []
    for stamp, row in bars.iterrows():
        day = stamp.tz_convert("America/New_York").tz_localize(None).normalize()
        if active and day != prev_day and day in daily.index:
            cash += active["units"] * float(daily.loc[day].Dividends)
        if stamp in entries:
            if active is not None or cash < entries[stamp]["cash_amount"]:
                raise ValueError("overlap or insufficient cash")
            active = entries[stamp]
            cash -= active["cash_amount"]
        if active and stamp == pd.Timestamp(active["exit_time"]):
            cash += active["exit_proceeds"]
            active = None
        value = cash + (active["units"] * float(row.Close) if active else 0)
        rows.append(dict(time=stamp.isoformat(), equity=value))
        prev_day = day
    if active:
        raise ValueError("open position at end")
    if not math.isclose(cash, p.capital + sum(t["net_pnl"] for t in trades), abs_tol=1e-6):
        raise ValueError("equity/trade P&L mismatch")
    result = pd.DataFrame(rows)
    result["drawdown"] = result.equity / result.equity.cummax().clip(lower=p.capital) - 1
    return result


def summary(trades, curve):
    if not trades:
        return dict(entries=0, target_hit_rate=None, net_win_rate=None, mean_net_return=None,
                    worst_trade=None, strategy_mdd=None, median_holding_sessions=None,
                    both_hit_bars=0, uncertain_entry_high=0)
    return dict(entries=len(trades), target_hit_rate=np.mean([t["target_hit"] for t in trades]),
                net_win_rate=np.mean([t["net_return"] > 0 for t in trades]),
                mean_net_return=np.mean([t["net_return"] for t in trades]),
                worst_trade=min(t["net_return"] for t in trades),
                strategy_mdd=float(curve.drawdown.min()),
                median_holding_sessions=np.median([t["holding_sessions"] for t in trades]),
                both_hit_bars=sum(t["both_hit_bars"] for t in trades),
                uncertain_entry_high=sum(t["uncertain_entry_high"] for t in trades))
