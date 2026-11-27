"""Offline paired daily-OHLC research. Not imported by the application."""

from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Protocol:
    drop: float = .20
    stop: float = .10
    hold_sessions: int = 10
    commission: float = .0005
    slippage: float = .001
    capital: float = 100_000.
    cash_per_trade: float = 10_000.


DEFAULT = Protocol()
REFERENCES = ("previous_close", "previous_20_highest_close")
MODES = ("close_confirmed", "intraday_touch")
TARGETS = (.10, .20)
PRICE_COLUMNS = ["Open", "High", "Low", "Close"]


def validate_prices(frame, sessions=None):
    """Reject holes and ambiguous identities instead of filling observations."""
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("empty data or non-date index")
    if frame.index.tz is not None or not frame.index.equals(frame.index.normalize()):
        raise ValueError("index must be exchange-local session dates without timezone")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("unsorted or duplicate sessions")
    columns = PRICE_COLUMNS + ["Dividends", "Stock Splits"]
    if any(c not in frame for c in columns):
        raise ValueError("missing OHLC or corporate actions")
    values = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (frame[PRICE_COLUMNS] <= 0).any().any():
        raise ValueError("missing, infinite or non-positive OHLC")
    if (frame[["Dividends", "Stock Splits"]] < 0).any().any():
        raise ValueError("negative corporate action")
    if ((frame.High < frame[["Open", "Close", "Low"]].max(axis=1)) |
            (frame.Low > frame[["Open", "Close", "High"]].min(axis=1))).any():
        raise ValueError("inconsistent OHLC bounds")
    if sessions is not None and not frame.index.equals(pd.DatetimeIndex(sessions)):
        raise ValueError("missing or unexpected exchange session")
    # Yahoo's split-adjusted OHLC must not still contain the mechanical split gap.
    for i in range(1, len(frame)):
        ratio = float(frame.iloc[i]["Stock Splits"])
        gap = float(frame.iloc[i].Open / frame.iloc[i - 1].Close)
        if ratio and abs(math.log(gap * ratio)) < .15 and abs(math.log(gap)) > .35:
            raise ValueError(f"possible unadjusted split at {frame.index[i].date()}")


def entry_ledger(frame, reference, mode, p=DEFAULT):
    """Generate once, without consulting either target arm or any later price."""
    if reference not in REFERENCES or mode not in MODES:
        raise ValueError("unknown hypothesis")
    ref = frame.Close.shift(1)
    if reference == REFERENCES[1]:
        ref = ref.rolling(20, min_periods=20).max()
    entries, signals = [], []
    next_entry = 0
    for i, (date, row) in enumerate(frame.iterrows()):
        if pd.isna(ref.iloc[i]):
            continue
        trigger = float(ref.iloc[i]) * (1 - p.drop)
        hit = row.Close <= trigger if mode == MODES[0] else row.Low <= trigger
        if not hit:
            continue
        j = i + 1 if mode == MODES[0] else i
        signal = dict(reference=reference, mode=mode, signal_date=str(date.date()),
                      reference_price=float(ref.iloc[i]), trigger=trigger,
                      signal_time="session_close" if mode == MODES[0] else
                      ("session_open" if row.Open <= trigger else "intraday_unknown"))
        if j < next_entry:
            signals.append(dict(signal, status="common_lockout"))
            continue
        if j >= len(frame):
            signals.append(dict(signal, status="unfilled_no_next_open"))
            continue
        at_open = mode == MODES[0] or row.Open <= trigger
        raw_fill = float(frame.iloc[j].Open) if at_open else trigger
        fill = raw_fill * (1 + p.slippage)
        entry = dict(signal, trade_id=len(entries) + 1, entry_index=j,
                     entry_date=str(frame.index[j].date()), entry_at_open=bool(at_open),
                     entry_raw=raw_fill, entry_fill=fill,
                     cash_amount=p.cash_per_trade,
                     units=p.cash_per_trade / (fill * (1 + p.commission)))
        entries.append(entry)
        signals.append(dict(signal, status="entered", trade_id=entry["trade_id"]))
        next_entry = j + p.hold_sessions
    return entries, signals


def simulate_trade(frame, entry, target, p=DEFAULT):
    start = entry["entry_index"]
    last = min(start + p.hold_sessions - 1, len(frame) - 1)
    stop_price = entry["entry_fill"] * (1 - p.stop)
    target_price = entry["entry_fill"] * (1 + target)
    uncertain_high, both_hit, dividends = 0, 0, 0.
    reason = None
    for i in range(start, last + 1):
        row = frame.iloc[i]
        if i > start:
            dividends += entry["units"] * float(row.Dividends)
        touch_entry_day = i == start and not entry["entry_at_open"]
        if touch_entry_day:
            # High could precede the buy; a subsequent stop can never be ignored.
            uncertain_high += int(row.High >= target_price)
            if row.Low <= stop_price:
                raw, reason = stop_price, "stop"
        elif i > start and row.Open <= stop_price:
            raw, reason = float(row.Open), "stop_gap"
        elif i > start and row.Open >= target_price:
            raw, reason = target_price, "target_gap"
        else:
            stop_hit, target_hit = row.Low <= stop_price, row.High >= target_price
            both_hit += int(stop_hit and target_hit)
            if stop_hit:
                raw, reason = stop_price, "stop_both" if target_hit else "stop"
            elif target_hit:
                raw, reason = target_price, "target"
        if reason is not None:
            break
    else:
        i, raw = last, float(frame.iloc[last].Close)
        reason = "horizon" if start + p.hold_sessions <= len(frame) else "data_end"
    fill = raw * (1 - p.slippage)
    proceeds = entry["units"] * fill * (1 - p.commission)
    pnl = proceeds + dividends - p.cash_per_trade
    return dict(entry, target=target, stop_price=stop_price, target_price=target_price,
                exit_index=i, exit_date=str(frame.index[i].date()), exit_raw=raw,
                exit_fill=fill, exit_proceeds=proceeds, dividends=dividends,
                exit_reason=reason, holding_sessions=i - start + 1,
                target_hit=reason in ("target", "target_gap"),
                net_pnl=pnl, net_return=pnl / p.cash_per_trade,
                both_hit_sessions=both_hit, uncertain_entry_high=uncertain_high)


def equity_curve(frame, trades, p=DEFAULT):
    cash, active = p.capital, None
    entries = {t["entry_index"]: t for t in trades}
    rows = []
    for i, (date, row) in enumerate(frame.iterrows()):
        if i in entries:
            if active is not None or cash < p.cash_per_trade:
                raise ValueError("overlap or insufficient cash")
            active = entries[i]
            cash -= p.cash_per_trade
        if active and i > active["entry_index"]:
            cash += active["units"] * float(row.Dividends)
        if active and i == active["exit_index"]:
            cash += active["exit_proceeds"]
            active = None
        holding = active["units"] * float(row.Close) if active else 0.
        rows.append(dict(date=str(date.date()), cash=cash, position_value=holding,
                         equity=cash + holding))
    result = pd.DataFrame(rows)
    peak = result.equity.cummax().clip(lower=p.capital)
    result["drawdown"] = result.equity / peak - 1
    return result


def summarize(reference, mode, target, trades, equity):
    count = len(trades)
    returns = [t["net_return"] for t in trades]
    return dict(reference=reference, mode=mode, target=target, entries=count,
                target_hit_rate=sum(t["target_hit"] for t in trades) / count if count else None,
                net_win_rate=sum(r > 0 for r in returns) / count if count else None,
                mean_net_return=float(np.mean(returns)) if count else None,
                worst_trade=min(returns) if count else None,
                strategy_mdd=float(equity.drawdown.min()) if count else None,
                median_holding_sessions=float(np.median([t["holding_sessions"] for t in trades])) if count else None,
                both_hit_sessions=sum(t["both_hit_sessions"] for t in trades),
                uncertain_entry_high=sum(t["uncertain_entry_high"] for t in trades),
                horizon_exits=sum(t["exit_reason"] == "horizon" for t in trades),
                data_end_exits=sum(t["exit_reason"] == "data_end" for t in trades),
                non_target_wins=sum(not t["target_hit"] and t["net_return"] > 0 for t in trades),
                terminal_equity=float(equity.equity.iloc[-1]))


def run_study(frame, p=DEFAULT):
    validate_prices(frame)
    summaries, all_trades, all_equity, all_signals, all_entries = [], [], [], [], []
    for reference in REFERENCES:
        for mode in MODES:
            entries, signals = entry_ledger(frame, reference, mode, p)
            all_entries.extend(entries)
            all_signals.extend(signals)
            for target in TARGETS:
                trades = [simulate_trade(frame, e, target, p) for e in entries]
                curve = equity_curve(frame, trades, p)
                if not np.isclose(curve.equity.iloc[-1], p.capital + sum(t["net_pnl"] for t in trades)):
                    raise ValueError("equity and trade P/L do not reconcile")
                summaries.append(summarize(reference, mode, target, trades, curve))
                all_trades.extend(trades)
                all_equity.append(curve.assign(reference=reference, mode=mode, target=target))
    return dict(summary=pd.DataFrame(summaries), trades=pd.DataFrame(all_trades),
                equity=pd.concat(all_equity, ignore_index=True),
                signals=pd.DataFrame(all_signals), entries=pd.DataFrame(all_entries),
                protocol=asdict(p))
