"""Offline exploratory study. Never imported by the app or used as a trade gate."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd

from stock_lab_core.chart_structure import build_parallel_channel
from stock_lab_core.price_batch_selection import DownloadFrameSelector
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.soxl_short_observation import completed_hour_grid, completed_hour_frame, channel_plan
from stock_lab_core.yahoo_transport import yahoo_session_kwargs


def signals(frame, warmup=140):
    """Rebuild each channel from its prefix; no final chart projected backwards."""
    rows = []
    for i in range(warmup - 1, len(frame)):
        view = frame.iloc[max(0, i - 139):i + 1]
        if view[['Open', 'High', 'Low', 'Close']].isna().any().any():
            continue
        channel = build_parallel_channel(view)
        if not channel:
            continue
        assert pd.Timestamp(channel['known_at']) <= frame.index[i]
        plan, _ = channel_plan(view, channel)
        rows.append(dict(i=i, time=frame.index[i] + pd.Timedelta(hours=1),
                         formation=str(channel['formation_id']), state=channel['state'],
                         lower=channel['lower'][-1], upper=channel['upper'][-1],
                         slope=channel['slope'], close=float(frame.Close.iloc[i]),
                         support=bool(plan.get('support_reaction')), inside=bool(plan),
                         known_at=str(channel['known_at'])))
    return rows


def execution_grid(schedule, now):
    # Last partial bar is an execution quote only, never a signal candle.
    rows = []
    for row in schedule.itertuples():
        rows.extend(pd.date_range(row.market_open, row.market_close, freq='1h', inclusive='left'))
    grid = pd.DatetimeIndex(rows).tz_convert('UTC')
    return grid[grid <= now]


def next_fill(clock, grid, raw):
    pos = grid.searchsorted(clock)
    if pos == len(grid):
        return None
    at = grid[pos]
    if at not in raw.index:
        return None
    price = raw.at[at, 'Open']
    return (at, float(price)) if pd.notna(price) and np.isfinite(price) and price > 0 else None


def session_close(schedule, at):
    sessions = schedule.loc[(schedule.market_open <= at) & (schedule.market_close > at)]
    if len(sessions) != 1:
        return None
    return pd.Timestamp(sessions.market_close.iloc[0])


def close_fill(closing, schedule, grid, raw):
    """Predetermined closing fill proxy, not an observed auction execution."""
    sessions = schedule.loc[schedule.market_close.eq(closing)]
    if len(sessions) != 1:
        return None
    opening = sessions.market_open.iloc[0]
    expected = grid[(grid >= opening) & (grid < closing)]
    if not len(expected) or expected[-1] not in raw.index:
        return None
    price = raw.at[expected[-1], 'Close']
    return (closing, float(price)) if pd.notna(price) and np.isfinite(price) and price > 0 else None


def simulate(frame, raw_soxx, raw_soxl, grid, observations, *, support_only,
             objective='upper', horizon=18, cost_bps=10, gates=None,
             schedule=None, no_late_entry=False, flat_at_close=False):
    """Close-confirmed exits, next scheduled open; one position/formation at a time.

    gates must be exact decision-time boolean observations. Unknown never passes.
    This is an event execution audit, not an optimized production strategy.
    """
    trades, used, rejected = [], set(), Counter()
    if (no_late_entry or flat_at_close) and schedule is None:
        raise ValueError('Session calendar required for session restrictions')
    busy_until = pd.Timestamp.min.tz_localize('UTC')
    for signal in observations:
        if not signal['inside'] or (support_only and not signal['support']):
            continue
        if signal['time'] <= busy_until or signal['formation'] in used:
            continue
        if gates is not None and gates.get(signal['time']) is not True:
            rejected['gate_blocked_or_unknown'] += 1
            continue
        fills = [next_fill(signal['time'], grid, raw) for raw in (raw_soxx, raw_soxl)]
        if any(fill is None for fill in fills):
            rejected['entry_quote_missing'] += 1
            continue
        (entry_at, entry), (_, etf_entry) = fills
        closing = session_close(schedule, entry_at) if schedule is not None else None
        if (no_late_entry or flat_at_close) and closing is None:
            rejected['session_unavailable'] += 1
            continue
        if no_late_entry and entry_at >= closing - pd.Timedelta(hours=1):
            rejected['late_entry'] += 1
            continue
        stop, upper = signal['lower'], signal['upper']
        if not stop < entry < upper:
            rejected['next_open_outside_channel'] += 1
            continue
        # Rebase 1R to actual next-open entry; do not silently retain signal-close R.
        target = upper if objective == 'upper' else entry + (entry - stop)
        if target > upper:
            rejected['one_r_beyond_upper'] += 1
            continue
        used.add(signal['formation'])
        forward = frame.iloc[signal['i'] + 1:signal['i'] + 1 + horizon]
        exit_row, reason, invalid = None, None, False
        for at, bar in forward.iterrows():
            if flat_at_close and at + pd.Timedelta(hours=1) > closing:
                break
            if at < entry_at:
                continue
            if not np.isfinite(bar[['Open', 'High', 'Low', 'Close']].to_numpy(dtype=float)).all():
                invalid = True
                break
            if bar.Close < stop:
                exit_row, reason = at, 'stop_close'
                break
            if bar.Close >= target:
                exit_row, reason = at, 'target_close'
                break
        if invalid:
            rejected['path_missing'] += 1
            busy_until = forward.index[-1] + pd.Timedelta(hours=1)
            continue
        if exit_row is None:
            if flat_at_close:
                reason = 'session_close'
            elif len(forward) < horizon:
                rejected['right_censored'] += 1
                break
            else:
                exit_row, reason = forward.index[-1], 'time_exit'
        exit_clock = closing if reason == 'session_close' else exit_row + pd.Timedelta(hours=1)
        out = [(close_fill(exit_clock, schedule, grid, raw) if reason == 'session_close'
                else next_fill(exit_clock, grid, raw)) for raw in (raw_soxx, raw_soxl)]
        busy_until = out[0][0] if out[0] else exit_clock
        if any(fill is None for fill in out):
            rejected['exit_quote_missing'] += 1
            continue
        (exit_at, exit_price), (_, etf_exit) = out
        if abs(exit_price / entry - 1) > .40:
            rejected['soxx_extreme_requires_action_audit'] += 1
            continue
        path = frame.loc[entry_at:exit_row] if reason != 'session_close' else raw_soxx.loc[(raw_soxx.index>=entry_at)&(raw_soxx.index<exit_at)]
        # The exit bar's high/low occur AFTER our open fill and cannot enter MAE.
        etf_path = raw_soxl.reindex(grid[(grid >= entry_at) & (grid < exit_at)])
        path_missing = etf_path[['Open','High','Low','Close']].isna().any().any()
        gross = etf_exit / etf_entry - 1
        cost = cost_bps / 10000
        net = etf_exit * (1 - cost) / (etf_entry * (1 + cost)) - 1
        trades.append(dict(signal_time=signal['time'], entry_time=entry_at,
                           exit_time=exit_at, formation=signal['formation'], reason=reason,
                           soxx_entry=entry, stop=stop, target=target,
                           planned_rr=(target-entry)/(entry-stop), soxx_return=(exit_price/entry-1)*100,
                           soxl_entry=etf_entry, soxl_exit=etf_exit, gross_pct=gross*100,
                           net_pct=net*100, r_multiple=(exit_price-entry)/(entry-stop),
                           soxx_mae_pct=(min([entry,exit_price]+path.Low.dropna().tolist())/entry-1)*100,
                           overnight=entry_at.tz_convert('America/New_York').date()!=exit_at.tz_convert('America/New_York').date(),
                           soxl_mae_pct=None if path_missing else (min(etf_path.Low.min(),etf_exit)/etf_entry-1)*100))
    return trades, dict(rejected)


def summarize(trades):
    if not trades:
        return {'n': 0, 'mean_net_pct': None, 'win_pct': None}
    frame = pd.DataFrame(trades)
    pnl = frame.net_pct.to_numpy() / 100
    equity = np.r_[1., np.cumprod(1+pnl)]
    return dict(n=len(frame), win_pct=float((pnl > 0).mean()*100),
                mean_net_pct=float(frame.net_pct.mean()), median_net_pct=float(frame.net_pct.median()),
                mean_excluding_best_three_pct=float(frame.net_pct.sort_values().iloc[:-3].mean()) if len(frame)>3 else None,
                worst_trade_pct=float(frame.net_pct.min()),
                worst_intratrade_mae_pct=float(frame.soxl_mae_pct.min()),
                mae_unavailable=int(frame.soxl_mae_pct.isna().sum()),
                overnight_n=int(frame.overnight.sum()),
                trade_close_mdd_pct=float((equity/np.maximum.accumulate(equity)-1).min()*100),
                compounded_full_sleeve_pct=float((equity[-1]-1)*100),
                exits=dict(Counter(frame.reason)))


def breakout_study(frame, observations):
    events, seen, busy = [], set(), {}
    for row in observations:
        if row['state'] not in ('하단 이탈', '상단 돌파'):
            continue
        key = row['formation'], row['state']
        if key in seen or row['i'] <= busy.get(row['state'], -1):
            continue
        future = frame.iloc[row['i']+1:row['i']+19]
        if len(future) < 18 or future[['Open','High','Low','Close']].isna().any().any():
            continue
        seen.add(key)
        busy[row['state']] = row['i'] + 18
        lower = row['lower'] + row['slope'] * np.arange(1,19)
        upper = row['upper'] + row['slope'] * np.arange(1,19)
        events.append(dict(time=row['time'], state=row['state'],
                           forward_6_pct=(future.Close.iloc[5]/row['close']-1)*100,
                           forward_18_pct=(future.Close.iloc[17]/row['close']-1)*100,
                           mae_pct=min(0.,(future.Low.min()/row['close']-1)*100),
                           reclaimed_original_channel=bool(((future.Close>lower)&(future.Close<upper)).any())))
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='cache/soxl_hour_research')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        import yfinance as yf
        now = pd.Timestamp(datetime.now(timezone.utc))
        symbols = ['SOXX', 'SOXL', '^SOX', 'SMH', 'QQQ']
        data = yf.download(symbols, start=(now-pd.Timedelta(days=729)).date().isoformat(),
                           interval='60m', prepost=False, auto_adjust=True, actions=True,
                           ignore_tz=False, group_by='ticker', threads=4, progress=False,
                           timeout=12, **yahoo_session_kwargs())
        if not isinstance(data.columns, pd.MultiIndex) or data.empty:
            raise RuntimeError('No exact-symbol historical data; no simulated prices substituted')
        selector = DownloadFrameSelector(data)
        for symbol in symbols:
            selector.select(symbol).to_parquet(out / (symbol.replace('^','')+'.parquet'))
        (out/'fetch.json').write_text(json.dumps(dict(captured_at=now.isoformat(),
            source='Yahoo/yfinance adjusted regular 60m',requested_days=729)),encoding='utf-8')
    meta = json.loads((out/'fetch.json').read_text(encoding='utf-8'))
    now = pd.Timestamp(meta['captured_at'])
    raw = {s:pd.read_parquet(out/(s+'.parquet')) for s in ['SOXX','SOXL','SOX','SMH','QQQ']}
    start = min(f.index.min() for f in raw.values()).date().isoformat()
    schedule = _exchange_schedule('US', start, now.date().isoformat())
    grid = completed_hour_grid(schedule, now)
    frame, issue = completed_hour_frame(raw['SOXX'], grid)
    if frame.empty or issue:
        raise RuntimeError('No usable SOXX hourly history')
    fills = execution_grid(schedule, now)
    observations = signals(frame)
    pd.DataFrame(observations).to_csv(out/'observations.csv', index=False)
    summary = dict(meta, first=str(frame.index.min()), last=str(frame.index.max()),
                   retained_bars=len(frame), valid_bars=int(frame.Close.notna().sum()),
                   signal_rows=len(observations), state_counts=dict(Counter(r['state'] for r in observations)),
                   hypotheses={}, gate_comparison='Historical complete gate inputs unavailable; not reconstructed',
                   hashes={s:hashlib.sha256((out/(s+'.parquet')).read_bytes()).hexdigest() for s in raw})
    summary['price_audit'] = {s:dict(max_abs_hour_move_pct=float((f.Close.pct_change(fill_method=None)*100).abs().max()),
        splits={str(k):float(v) for k,v in f.get('Stock Splits',pd.Series(dtype=float)).items() if pd.notna(v) and v})
        for s,f in raw.items() if s in ['SOXX','SOXL']}
    summary['constant_defense_scenario'] = {'assumption':'Block every new entry, not a reconstruction of historical gates',
        'new_trades':0,'new_sleeve_price_pnl_pct':0,'interest_fees_existing_holdings':'not modeled'}
    for support in [False, True]:
        for objective in ['upper','one_r']:
            key = ('support' if support else 'inside')+'_'+objective
            trades, rejected = simulate(frame, raw['SOXX'], raw['SOXL'], fills, observations,
                                         support_only=support, objective=objective)
            pd.DataFrame(trades).to_csv(out/(key+'.csv'),index=False)
            # Chronological descriptive halves, never threshold optimization.
            midpoint = frame.index[139] + (frame.index[-1]-frame.index[139])/2
            early = [t for t in trades if t['entry_time'] < midpoint]
            late = [t for t in trades if t['entry_time'] >= midpoint]
            stressed,_ = simulate(frame, raw['SOXX'], raw['SOXL'], fills, observations,
                                   support_only=support, objective=objective,cost_bps=20)
            summary['hypotheses'][key] = dict(summary=summarize(trades),rejected=rejected,
                                               earlier=summarize(early),later=summarize(late),
                                               cost_40bp=summarize(stressed))
    events = breakout_study(frame, observations)
    pd.DataFrame(events).to_csv(out/'breakouts.csv',index=False)
    summary['breakouts'] = {}
    for state in ['하단 이탈','상단 돌파']:
        subset = pd.DataFrame([e for e in events if e['state']==state])
        summary['breakouts'][state] = {'n':len(subset)}
        if not subset.empty:
            summary['breakouts'][state].update(subset.select_dtypes(include='number').mean().to_dict())
            summary['breakouts'][state]['reclaim_pct'] = subset.reclaimed_original_channel.mean()*100
    summary['support_one_r_hold_sensitivity'] = {}
    for horizon in (6,36):
        trades,rejected=simulate(frame,raw['SOXX'],raw['SOXL'],fills,observations,
                                  support_only=True,objective='one_r',horizon=horizon)
        summary['support_one_r_hold_sensitivity'][str(horizon)] = dict(summary=summarize(trades),rejected=rejected)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))


if __name__ == '__main__':
    main()
