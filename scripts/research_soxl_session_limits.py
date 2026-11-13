"""Paired late-entry/overnight research on the frozen previous hourly dataset."""

import hashlib
import json
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.research_soxl_hours import (
    _exchange_schedule, completed_hour_grid, completed_hour_frame,
    execution_grid, signals, simulate, summarize, session_close,
)

POLICIES = {
    'allow_all': {},
    'no_late_entry': {'no_late_entry': True},
    'flat_at_close': {'flat_at_close': True},
    'both_limits': {'no_late_entry': True, 'flat_at_close': True},
}


def paired_opportunities(baseline, alternatives, *, blocked_times=()):
    """Per-trade percentage-point differences, NOT additive account returns."""
    observed = {str(t['signal_time']): t for t in alternatives}
    missing, paired, details, unknown = [], [], [], 0
    blocked_times = {str(t) for t in blocked_times}
    for base in baseline:
        alt = observed.get(str(base['signal_time']))
        if alt is None:
            blocked = str(base['signal_time']) in blocked_times
            if blocked:
                missing.append(base)
            else:
                unknown += 1
            details.append(dict(signal_time=str(base['signal_time']),kind='not_entered' if blocked else 'unavailable',
                                base_net_pct=base['net_pct'],alternative_net_pct=None,
                                difference_pp=None))
        else:
            difference = alt['net_pct'] - base['net_pct']
            paired.append(difference)
            details.append(dict(signal_time=str(base['signal_time']),kind='paired',
                                base_net_pct=base['net_pct'],alternative_net_pct=alt['net_pct'],
                                difference_pp=difference))
    wins = [t['net_pct'] for t in missing if t['net_pct']>0]
    losses = [t['net_pct'] for t in missing if t['net_pct']<0]
    changed = [r for r in details if r['kind']=='paired' and abs(r['difference_pp'])>1e-10]
    return dict(not_entered_n=len(missing),unavailable_n=unknown, missed_winners=len(wins), avoided_losers=len(losses),
                best_missed_pct=max(wins,default=None), worst_avoided_pct=min(losses,default=None),
                mean_missed_winner_pct=sum(wins)/len(wins) if wins else None,
                mean_avoided_loser_pct=sum(losses)/len(losses) if losses else None,
                matched_n=len(paired), changed_exit_n=len(changed),
                improved_n=sum(r['difference_pp']>0 for r in changed),
                worsened_n=sum(r['difference_pp']<0 for r in changed),
                mean_changed_difference_pp=sum(r['difference_pp'] for r in changed)/len(changed) if changed else None,
                largest_improvement_pp=max(paired,default=None),
                largest_foregone_gain_pp=max(0.,-min(paired,default=0))), details


def main():
    source = ROOT/'cache/soxl_hour_research'
    out = ROOT/'cache/soxl_session_limits'
    out.mkdir(parents=True,exist_ok=True)
    previous = json.loads((source/'summary.json').read_text(encoding='utf-8'))
    hashes = {s:hashlib.sha256((source/(s+'.parquet')).read_bytes()).hexdigest()
              for s in previous['hashes']}
    assert hashes == previous['hashes'], 'Prior price dataset changed'
    now = pd.Timestamp(previous['captured_at'])
    raw = {s:pd.read_parquet(source/(s+'.parquet')) for s in ['SOXX','SOXL']}
    schedule = _exchange_schedule('US',raw['SOXX'].index.min().date().isoformat(),now.date().isoformat())
    frame,issue = completed_hour_frame(raw['SOXX'],completed_hour_grid(schedule,now))
    assert not issue
    grid = execution_grid(schedule,now)
    observations = signals(frame)
    result = dict(source_capture=previous['captured_at'],hashes=hashes,
                  assumption='No historical market gate reconstructed; app rules unchanged',studies={})
    for objective in ['one_r','upper']:
        baseline,rejected=simulate(frame,raw['SOXX'],raw['SOXL'],grid,observations,
                                    support_only=True,objective=objective)
        old = pd.read_csv(source/('support_'+objective+'.csv'))
        assert len(old)==len(baseline)
        for prior,current in zip(old.to_dict('records'),baseline):
            assert pd.Timestamp(prior['entry_time'])==current['entry_time']
            assert pd.Timestamp(prior['exit_time'])==current['exit_time']
            assert abs(prior['net_pct']-current['net_pct'])<1e-10
        selected={t['signal_time'] for t in baseline}
        fixed_signals=[r for r in observations if r['time'] in selected]
        study={}
        for name,options in POLICIES.items():
            trades,rejected=simulate(frame,raw['SOXX'],raw['SOXL'],grid,observations,
                                      support_only=True,objective=objective,schedule=schedule,**options)
            # Isolate exit/rejection effects on EXACT same baseline entry events.
            paired,paired_rejected=simulate(frame,raw['SOXX'],raw['SOXL'],grid,fixed_signals,
                                            support_only=True,objective=objective,schedule=schedule,**options)
            blocked_times = [t['signal_time'] for t in baseline if options.get('no_late_entry')
                             and t['entry_time'] >= session_close(schedule,t['entry_time'])-pd.Timedelta(hours=1)]
            opportunities,details=paired_opportunities(baseline,paired,blocked_times=blocked_times)
            stressed,_=simulate(frame,raw['SOXX'],raw['SOXL'],grid,observations,
                                 support_only=True,objective=objective,schedule=schedule,cost_bps=20,**options)
            midpoint=frame.index[139]+(frame.index[-1]-frame.index[139])/2
            study[name]=dict(summary=summarize(trades),rejected=rejected,
                cost_40bp=summarize(stressed),same_signals=summarize(paired),
                paired_rejected=paired_rejected,opportunities=opportunities,
                earlier=summarize([t for t in trades if t['entry_time']<midpoint]),
                later=summarize([t for t in trades if t['entry_time']>=midpoint]),
                new_entry_events=sum(t['signal_time'] not in selected for t in trades))
            pd.DataFrame(trades).to_csv(out/(objective+'_'+name+'.csv'),index=False)
            pd.DataFrame(details).to_csv(out/(objective+'_'+name+'_pairs.csv'),index=False)
        result['studies'][objective]=study
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))


if __name__=='__main__':
    main()
