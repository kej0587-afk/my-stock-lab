import pandas as pd
import pytest

from scripts import research_soxl_hours as study
from scripts.research_soxl_session_limits import paired_opportunities


def setup_session(early=False):
    opening=pd.Timestamp('2026-11-27 14:30Z')
    closing=pd.Timestamp('2026-11-27 18:00Z' if early else '2026-11-27 21:00Z')
    next_open=pd.Timestamp('2026-11-30 14:30Z')
    schedule=pd.DataFrame(dict(market_open=[opening,next_open],
                               market_close=[closing,next_open+pd.Timedelta(hours=6.5)]))
    grid=study.execution_grid(schedule,next_open+pd.Timedelta(hours=7))
    raw=pd.DataFrame(dict(Open=101.,High=103.,Low=100.,Close=102.),index=grid)
    full=study.completed_hour_grid(schedule,next_open+pd.Timedelta(hours=7))
    frame=raw.reindex(full)
    signal_time=closing-pd.Timedelta(minutes=30)
    i=frame.index.get_loc(signal_time-pd.Timedelta(hours=1))
    signal=dict(i=i,time=signal_time,formation='a',inside=True,support=True,lower=95.,upper=120.)
    return schedule,grid,frame,raw,signal


@pytest.mark.parametrize('early',[False,True])
def test_last_partial_bar_entry_blocked_on_regular_and_short_sessions(early):
    schedule,grid,frame,raw,signal=setup_session(early)
    trades,rejected=study.simulate(frame,raw,raw,grid,[signal],support_only=True,
                                   schedule=schedule,no_late_entry=True)
    assert not trades and rejected['late_entry']==1


@pytest.mark.parametrize('early',[False,True])
def test_flatten_uses_known_calendar_close_and_last_partial_close(early):
    schedule,grid,frame,raw,signal=setup_session(early)
    trades,_=study.simulate(frame,raw,raw,grid,[signal],support_only=True,
                             schedule=schedule,flat_at_close=True)
    assert len(trades)==1
    trade=trades[0]
    assert trade['entry_time']==signal['time']
    assert trade['exit_time']==schedule.market_close.iloc[0]
    assert trade['reason']=='session_close' and trade['soxl_exit']==102
    assert not trade['overnight']


def test_missing_last_bar_close_never_replaced_with_earlier_or_next_day():
    schedule,grid,frame,raw,signal=setup_session()
    raw.loc[signal['time'],'Close']=float('nan')
    trades,rejected=study.simulate(frame,raw,raw,grid,[signal],support_only=True,
                                   schedule=schedule,flat_at_close=True)
    assert not trades and rejected['exit_quote_missing']==1


def test_next_session_cannot_change_flattened_result():
    schedule,grid,frame,raw,signal=setup_session()
    a,_=study.simulate(frame,raw,raw,grid,[signal],support_only=True,
                        schedule=schedule,flat_at_close=True)
    changed=raw.copy()
    changed.loc[changed.index>=schedule.market_open.iloc[1]]*=.1
    b,_=study.simulate(changed.reindex(frame.index),changed,changed,grid,[signal],support_only=True,
                        schedule=schedule,flat_at_close=True)
    assert a==b


def test_same_day_stop_has_priority_over_forced_close():
    schedule,grid,frame,raw,signal=setup_session()
    signal.update(i=0,time=frame.index[1])
    frame.loc[frame.index[1],['Low','Close']]=[93.,94.]
    raw.loc[frame.index[2],'Open']=92.
    trades,_=study.simulate(frame,raw,raw,grid,[signal],support_only=True,
                             schedule=schedule,flat_at_close=True)
    assert trades[0]['reason']=='stop_close'
    assert trades[0]['exit_time']==frame.index[2] and trades[0]['soxl_exit']==92


def test_missing_counterfactual_not_counted_as_avoided_loss():
    base=[dict(signal_time='a',net_pct=-5),dict(signal_time='b',net_pct=8)]
    result,_=paired_opportunities(base,[],blocked_times=['b'])
    assert result['unavailable_n']==1
    assert result['missed_winners']==1 and result['avoided_losers']==0


def test_paired_improvement_and_opportunity_counts():
    base=[dict(signal_time='a',net_pct=-5),dict(signal_time='b',net_pct=8),dict(signal_time='c',net_pct=-3)]
    alt=[dict(signal_time='a',net_pct=1),dict(signal_time='b',net_pct=2)]
    result,_=paired_opportunities(base,alt,blocked_times=['c'])
    assert result['improved_n']==1 and result['worsened_n']==1
    assert result['largest_improvement_pp']==6 and result['largest_foregone_gain_pp']==6
    assert result['avoided_losers']==1
