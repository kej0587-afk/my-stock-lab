"""Paired exit-only audit on observed 5m bars, not a production trading rule."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.research_soxl_hours import _exchange_schedule

COLS=['Open','High','Low','Close']


def minute_grid(schedule, now):
    values=[]
    for row in schedule.itertuples():
        values.extend(pd.date_range(row.market_open,row.market_close,freq='5min',inclusive='left'))
    result=pd.DatetimeIndex(values).tz_convert('UTC')
    return result[result+pd.Timedelta(minutes=5)<=now]


def valid_path(frame, index):
    path=frame.reindex(index)[COLS]
    a=path.to_numpy(dtype=float)
    return len(path)>0 and np.isfinite(a).all() and (a>0).all()


def aggregate(frame):
    return np.array([frame.Open.iloc[0],frame.High.max(),frame.Low.min(),frame.Close.iloc[-1]],dtype=float)


def reconcile(trade, fine, coarse, grid, schedule):
    entry,exit_at=pd.Timestamp(trade['entry_time']),pd.Timestamp(trade['exit_time'])
    wanted=grid[(grid>=entry)&(grid<=exit_at)]
    if not len(wanted) or wanted[0]!=entry or wanted[-1]!=exit_at:
        return 'outside_available_grid'
    for symbol in ['SOXX','SOXL']:
        f,c=fine[symbol],coarse[symbol]
        if not valid_path(f,wanted):
            return symbol+'_missing_5m'
        if not np.isclose(f.at[exit_at,'Open'],c.at[exit_at,'Open'],rtol=1e-6,atol=1e-5):
            return symbol+'_exit_open_mismatch'
        for at in c.index[(c.index>=entry)&(c.index<exit_at)]:
            session=schedule.loc[(schedule.market_open<=at)&(at<schedule.market_close)]
            if len(session)!=1:
                return 'session_missing'
            end=min(at+pd.Timedelta(hours=1),session.market_close.iloc[0])
            bars=f.reindex(grid[(grid>=at)&(grid<end)])
            if not np.allclose(aggregate(bars),c.loc[at,COLS].to_numpy(dtype=float),rtol=1e-6,atol=1e-5):
                return symbol+'_hourly_aggregation_mismatch'
    return 'ok'


def exit_variant(trade, x, l, grid, *, minutes=5, use_low=False, extra_delay_bars=0):
    """A bar-low trigger is only known at its end, never at its hindsight low."""
    entry,original=pd.Timestamp(trade['entry_time']),pd.Timestamp(trade['exit_time'])
    stop=float(trade['stop'])
    wanted=grid[(grid>=entry)&(grid<=original)]
    if not valid_path(x,wanted) or not valid_path(l,wanted):
        return {'status':'missing_path'}
    trigger=None
    for at in wanted:
        if at>=original:
            break
        end=at+pd.Timedelta(minutes=minutes)
        if end>original:
            break
        # US session opens at :30; 15m windows also start at :00/:15/:30/:45.
        if minutes==15 and at.minute%15:
            continue
        times=pd.date_range(at,end,freq='5min',inclusive='left')
        if not times.isin(grid).all():
            continue
        values=x.reindex(times)
        breach=values.Low.min()<stop if use_low else values.Close.iloc[-1]<stop
        if breach:
            trigger=end
            break
    fill=original
    if trigger is not None and trigger<original:
        pos=grid.searchsorted(trigger)+extra_delay_bars
        # Keep the original exit if it arrives before the hypothetical delayed order.
        fill=min(grid[pos],original) if pos<len(grid) else original
    if fill not in l.index or not np.isfinite(l.at[fill,'Open']) or l.at[fill,'Open']<=0:
        return {'status':'missing_fill'}
    e,z=float(trade['soxl_entry']),float(l.at[fill,'Open'])
    net=(z*.999/(e*1.001)-1)*100
    touches=x.loc[wanted[wanted<original]]
    touches=touches.loc[touches.Low<stop]
    first=None if touches.empty else touches.index[0]
    return dict(status='ok',signal_time=str(trade['signal_time']),entry_time=str(entry),
        original_exit=str(original),original_reason=trade['reason'],original_net_pct=float(trade['net_pct']),
        first_low_bar=None if first is None else str(first),
        trigger_end=None if trigger is None else str(trigger),exit_time=str(fill),exit_price=z,
        net_pct=net,difference_pp=net-float(trade['net_pct']),
        original_wait_from_first_low_bar_end_min=None if first is None else (original-(first+pd.Timedelta(minutes=5))).total_seconds()/60)


def budget_weight(budget_pct, loss_scenario_pct):
    """Percent of account; a scenario calculation, not a guaranteed loss cap."""
    try:
        budget_pct,loss_scenario_pct=float(budget_pct),float(loss_scenario_pct)
    except (TypeError,ValueError):
        return None
    if not np.isfinite([budget_pct,loss_scenario_pct]).all() or budget_pct<0 or loss_scenario_pct<=0:
        return None
    return min(100.,100*budget_pct/loss_scenario_pct)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fetch',action='store_true')
    args=parser.parse_args()
    root=ROOT/'cache/soxl_five_minute'
    root.mkdir(parents=True,exist_ok=True)
    if args.fetch:
        import yfinance as yf
        from stock_lab_core.yahoo_transport import yahoo_session_kwargs
        from stock_lab_core.price_batch_selection import DownloadFrameSelector
        now=pd.Timestamp.now(tz='UTC')
        start=(now-pd.Timedelta(days=59)).date().isoformat()
        downloaded=yf.download(['SOXX','SOXL'],start=start,interval='5m',prepost=False,
            auto_adjust=True,actions=True,ignore_tz=False,group_by='ticker',threads=2,progress=False,
            timeout=12,**yahoo_session_kwargs())
        selector=DownloadFrameSelector(downloaded)
        meta=dict(captured_at=str(now),requested_start=start,interval='5m',auto_adjust=True,
                  prepost=False,source='Yahoo/yfinance',symbols={})
        for symbol in ['SOXX','SOXL']:
            f=selector.select(symbol).dropna(how='all')
            if f.empty:
                raise RuntimeError(symbol+' five-minute data unavailable')
            f.to_parquet(root/(symbol+'.parquet'))
            meta['symbols'][symbol]=dict(first=str(f.index.min()),last=str(f.index.max()),rows=len(f))
        (root/'fetch.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    meta=json.loads((root/'fetch.json').read_text(encoding='utf-8'))
    previous=ROOT/'cache/soxl_hour_research'
    old=json.loads((previous/'summary.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((previous/(s+'.parquet')).read_bytes()).hexdigest()==h for s,h in old['hashes'].items())
    fine={s:pd.read_parquet(root/(s+'.parquet')) for s in ['SOXX','SOXL']}
    coarse={s:pd.read_parquet(previous/(s+'.parquet')) for s in fine}
    now=min(pd.Timestamp(meta['captured_at']),pd.Timestamp(old['captured_at']))
    first=max(f.index.min() for f in fine.values())
    schedule=_exchange_schedule('US',first.date().isoformat(),now.date().isoformat())
    grid=minute_grid(schedule,now)
    ledger=pd.read_csv(previous/'support_one_r.csv')
    coverage,records=[],[]
    policies={'low_5m':dict(use_low=True),'close_5m':{},'close_15m':dict(minutes=15),
              'close_5m_plus_5m_delay':dict(extra_delay_bars=1)}
    for trade in ledger.to_dict('records'):
        entry,exit_at=pd.Timestamp(trade['entry_time']),pd.Timestamp(trade['exit_time'])
        status='outside_provider_window' if entry<first else reconcile(trade,fine,coarse,grid,schedule)
        coverage.append(dict(entry_time=str(entry),exit_time=str(exit_at),reason=trade['reason'],status=status))
        if status!='ok':
            continue
        for name,options in policies.items():
            records.append(dict(policy=name,**exit_variant(trade,fine['SOXX'],fine['SOXL'],grid,**options)))
    df=pd.DataFrame(records)
    if df.empty:
        df=pd.DataFrame(columns=['policy','status','net_pct','difference_pp'])
    df.to_csv(root/'paired_exits.csv',index=False)
    pd.DataFrame(coverage).to_csv(root/'coverage.csv',index=False)
    result=dict(fetch=meta,price_hashes={s:hashlib.sha256((root/(s+'.parquet')).read_bytes()).hexdigest() for s in fine},
                ledger_sha256=hashlib.sha256((previous/'support_one_r.csv').read_bytes()).hexdigest(),
                coverage=coverage,policies={},risk_scenarios=[dict(budget_pct=b,loss_scenario_pct=l,
                weight_pct=budget_weight(b,l)) for b in [.25,.5,1.] for l in [5.,10.,15.,20.]])
    for name in policies:
        sample=df.loc[(df.policy==name)&(df.status=='ok')]
        result['policies'][name]=dict(n=len(sample),mean_net_pct=float(sample.net_pct.mean()) if len(sample) else None,
            worst_net_pct=float(sample.net_pct.min()) if len(sample) else None,improved_n=int((sample.difference_pp>1e-8).sum()),
            worsened_n=int((sample.difference_pp<-1e-8).sum()),
            actual_quote_execution='Unavailable; next bar Open proxy, not bid/ask or fills')
    (root/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(df.to_string(index=False))
    print(json.dumps(result['policies'],indent=2))


if __name__=='__main__':
    main()
