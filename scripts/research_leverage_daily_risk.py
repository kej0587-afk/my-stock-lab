"""Describe cached daily prices; separate incomplete sessions and missing days."""

import json
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stock_lab_core.report_eventstudy import _exchange_schedule


def summarize_daily(frame, expected_dates, zone):
    f=frame.dropna(subset=['Open','High','Low','Close']).copy()
    f.index=f.index.tz_convert(zone)
    dates=f.index.strftime('%Y-%m-%d')
    valid=dates.isin(expected_dates)
    closed=f.loc[valid].copy()
    closed.index=dates[valid]
    aligned=closed.reindex(expected_dates)
    # No forward-fill across absent source dates; never relabel a multi-day move as daily.
    close_ret=(aligned.Close/aligned.Close.shift(1)-1)*100
    gap=(aligned.Open/aligned.Close.shift(1)-1)*100
    last_date=expected_dates[-1]
    current_return=close_ret.loc[last_date]
    return dict(expected_last_date=last_date,closed_last_date=closed.index[-1] if len(closed) else None,
        closed_rows=len(closed),missing_expected_dates=aligned.index[aligned.Close.isna()].tolist(),
        worst_close_day_pct=float(close_ret.min()),worst_open_gap_pct=float(gap.min()),
        gap_5th_percentile_pct=float(gap.quantile(.05)),
        last_close=float(closed.Close.iloc[-1]) if len(closed) else None,
        latest_expected_change_pct=float(current_return) if pd.notna(current_return) else None,
        last_5=closed.tail(5).reset_index().to_dict('records'),
        latest_available_bar=str(f.index[-1]),latest_bar_close=float(f.Close.iloc[-1]),
        latest_bar_is_complete=bool(valid[-1]))


def main():
    root=ROOT/'cache/soxl_stop_loss'
    meta=json.loads((root/'daily_risk_snapshot.json').read_text(encoding='utf-8'))
    now=pd.Timestamp(meta['captured_at'])
    result={}
    for symbol in ['SOXL','SOXX','BITX','BTC-USD','QQQ','418660.KS']:
        frame=pd.read_parquet(root/(symbol+'_daily.parquet'))
        zone='Asia/Seoul' if symbol.endswith('.KS') else ('UTC' if symbol=='BTC-USD' else 'America/New_York')
        start=frame.index.tz_convert(zone).min().date().isoformat()
        if symbol=='BTC-USD':
            expected=pd.date_range(start,now.date(),inclusive='left',freq='D').strftime('%Y-%m-%d').tolist()
        else:
            schedule=_exchange_schedule('KR' if symbol.endswith('.KS') else 'US',start,now.date().isoformat())
            expected=schedule.loc[schedule.market_close<=now,'market_open'].dt.tz_convert(zone).dt.strftime('%Y-%m-%d').tolist()
        result[symbol]=summarize_daily(frame,expected,zone)
        if symbol=='BTC-USD':
            # A UTC midnight boundary is not an ETF's non-trading overnight gap.
            result[symbol]['worst_open_gap_pct']=None
            result[symbol]['gap_5th_percentile_pct']=None
    meta['data']=result
    (root/'daily_risk_snapshot.json').write_text(json.dumps(meta,indent=2,default=str),encoding='utf-8')
    print(json.dumps(meta,indent=2,default=str))


if __name__=='__main__':
    main()
