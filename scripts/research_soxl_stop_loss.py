"""Offline attribution of frozen stop trades; never changes application gates."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.research_soxl_hours import _exchange_schedule, execution_grid, completed_hour_grid


def decompose(trade, soxx, soxl, grid, full_grid):
    entry, exit_at = pd.Timestamp(trade['entry_time']), pd.Timestamp(trade['exit_time'])
    stop = float(trade['stop'])
    expected = grid[(grid >= entry) & (grid < exit_at)]
    x, l = soxx.reindex(expected), soxl.reindex(expected)
    cols = ['Open', 'High', 'Low', 'Close']
    if not len(expected) or any(f[cols].isna().any().any() for f in [x, l]):
        return {'status': 'path_missing'}
    if any(not np.isfinite(f[cols].to_numpy()).all() or (f[cols] <= 0).any().any() for f in [x, l]):
        return {'status': 'path_invalid'}
    confirmations = x.loc[x.index.isin(full_grid) & (x.Close < stop)]
    touches = x.loc[x.Low < stop]
    if confirmations.empty or touches.empty:
        return {'status': 'no_confirmed_stop'}
    confirmed, touch = confirmations.index[0], touches.index[0]
    if confirmed + pd.Timedelta(hours=1) != exit_at:
        return {'status': 'unexpected_exit_clock'}
    e, z = float(trade['soxl_entry']), float(trade['soxl_exit'])
    if not np.isclose(l.Open.iloc[0], e):
        return {'status': 'entry_mismatch'}
    l = l.loc[:confirmed]
    scale = 100 / e
    overnight, intraday = 0., 0.
    for i in range(1, len(l)):
        delta = (l.Open.iloc[i] - l.Close.iloc[i-1]) * scale
        if l.index[i].tz_convert('America/New_York').date() != l.index[i-1].tz_convert('America/New_York').date():
            overnight += delta
        else:
            intraday += delta
    within = float((l.Close-l.Open).sum()*scale)
    post = float((z-l.Close.iloc[-1])*scale)
    gross = (z/e-1)*100
    before = float((l.at[touch,'Open']-e)*scale)
    touch_bar = float((l.at[touch,'Close']-l.at[touch,'Open'])*scale)
    waiting = float((l.Close.iloc[-1]-l.at[touch,'Close'])*scale)
    assert abs(overnight+intraday+within+post-gross)<1e-9
    assert abs(before+touch_bar+waiting+post-gross)<1e-9
    planned = 100*(1-stop/float(trade['soxx_entry']))
    return dict(status='ok', signal_time=str(trade['signal_time']),entry_time=str(entry),
        exit_time=str(exit_at),first_touch_bar=str(touch),confirmation_bar=str(confirmed),
        net_pct=float(trade['net_pct']),gross_pct=gross,cost_pp=float(trade['net_pct'])-gross,
        planned_soxx_stop_pct=planned,actual_soxx_pct=float(trade['soxx_return']),
        heuristic_3x_stop_pct=3*planned,
        loss_to_heuristic_ratio=-float(trade['net_pct'])/(3*planned),
        overnight_gap_pp=overnight,intraday_boundary_pp=intraday,within_bar_pp=within,
        post_confirmation_fill_pp=post,before_touch_bar_pp=before,touch_bar_pp=touch_bar,
        after_touch_close_to_confirmation_pp=waiting,
        touch_to_confirmation_wall_hours=(confirmed-touch).total_seconds()/3600,
        bars_after_touch=int((l.index>touch).sum()),overnight=bool(trade['overnight']))


def main():
    source=ROOT/'cache/soxl_hour_research'
    out=ROOT/'cache/soxl_stop_loss'
    out.mkdir(parents=True,exist_ok=True)
    meta=json.loads((source/'summary.json').read_text(encoding='utf-8'))
    hashes={s:hashlib.sha256((source/(s+'.parquet')).read_bytes()).hexdigest() for s in meta['hashes']}
    assert hashes==meta['hashes']
    raw={s:pd.read_parquet(source/(s+'.parquet')) for s in ['SOXX','SOXL']}
    now=pd.Timestamp(meta['captured_at'])
    schedule=_exchange_schedule('US',raw['SOXX'].index.min().date().isoformat(),now.date().isoformat())
    grid,full=execution_grid(schedule,now),completed_hour_grid(schedule,now)
    ledger=pd.read_csv(source/'support_one_r.csv')
    rows=[decompose(t,raw['SOXX'],raw['SOXL'],grid,full)
          for t in ledger.loc[ledger.reason.eq('stop_close')].to_dict('records')]
    df=pd.DataFrame(rows)
    df.to_csv(out/'stop_attribution.csv',index=False)
    good=df.loc[df.status.eq('ok')]
    metrics=['net_pct','planned_soxx_stop_pct','heuristic_3x_stop_pct','loss_to_heuristic_ratio',
             'overnight_gap_pp','within_bar_pp','intraday_boundary_pp','post_confirmation_fill_pp',
             'after_touch_close_to_confirmation_pp','bars_after_touch']
    summary=dict(captured_at=meta['captured_at'],hashes=hashes,
        ledger_sha256=hashlib.sha256((source/'support_one_r.csv').read_bytes()).hexdigest(),
        statuses=df.status.value_counts().to_dict(),metrics=good[metrics].describe().to_dict(),
        delayed_confirmation_n=int((good.bars_after_touch>0).sum()),
        overnight_n=int(good.overnight.sum()),negative_overnight_gap_n=int((good.overnight_gap_pp<0).sum()),
        worse_than_heuristic_n=int((-good.net_pct>good.heuristic_3x_stop_pct).sum()),
        worst=good.sort_values('net_pct').head(6).to_dict('records'))
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
