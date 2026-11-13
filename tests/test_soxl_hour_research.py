"""Synthetic execution audit tests; no API calls and no app decision changes."""
import numpy as np
import pandas as pd
import pytest
from scripts import research_soxl_hours as study


def fixture():
    idx = pd.date_range('2026-01-05 14:30', periods=7, freq='1h', tz='UTC')
    frame = pd.DataFrame({'Open':[100,101,104,105,106,107,108],
                          'High':[102,104,106,107,108,109,110],
                          'Low':[99,100,103,104,105,106,107],
                          'Close':[101,103,105,106,107,108,109]},index=idx,dtype=float)
    signals = [dict(i=0,time=idx[0]+pd.Timedelta(hours=1),formation='a',inside=True,
                    support=True,lower=99.,upper=110.)]
    return frame, signals


def test_next_open_entry_and_actual_entry_one_r():
    frame, signals = fixture()
    trades,_ = study.simulate(frame,frame,frame*2,frame.index,signals,support_only=True,objective='one_r')
    row = trades[0]
    assert row['entry_time']==frame.index[1]
    assert row['soxx_entry']==101
    assert row['target']==103
    assert row['exit_time']==frame.index[2]
    assert row['soxl_entry']==202 and row['soxl_exit']==208
    assert row['net_pct'] < row['gross_pct']


def test_no_exit_bar_low_in_mae():
    frame, signals = fixture()
    etf=frame*2
    etf.loc[frame.index[2],'Low']=1
    trades,_=study.simulate(frame,frame,etf,frame.index,signals,support_only=True,objective='one_r')
    assert trades[0]['soxl_mae_pct']==pytest.approx((200/202-1)*100)


def test_missing_exact_execution_open_is_not_forward_filled():
    frame, signals=fixture()
    raw=frame.drop(index=frame.index[1])
    trades, rejected=study.simulate(frame,frame,raw,frame.index,signals,support_only=True)
    assert not trades and rejected['entry_quote_missing']==1


def test_missing_soxl_intratrade_low_does_not_discard_known_return():
    frame, signals=fixture()
    raw=frame.copy()
    raw.loc[frame.index[1],'Low']=np.nan
    trades,_=study.simulate(frame,frame,raw,frame.index,signals,support_only=True,objective='one_r')
    assert len(trades)==1 and trades[0]['soxl_mae_pct'] is None
    assert np.isfinite(trades[0]['net_pct'])


def test_unknown_and_blocked_gate_never_pass():
    frame, signals=fixture()
    for gates in ({},{signals[0]['time']:False}):
        trades,rejected=study.simulate(frame,frame,frame,frame.index,signals,support_only=True,gates=gates)
        assert not trades and rejected['gate_blocked_or_unknown']==1
    trades,_=study.simulate(frame,frame,frame,frame.index,signals,support_only=True,
                            objective='one_r',gates={signals[0]['time']:True})
    assert len(trades)==1


def test_close_stop_fills_at_next_open_not_stop_price():
    frame, signals=fixture()
    frame.loc[frame.index[1],['Low','Close']]=[97,98]
    frame.loc[frame.index[2],['Open','Low']]=[90,89]
    trades,_=study.simulate(frame,frame,frame,frame.index,signals,support_only=True)
    assert trades[0]['reason']=='stop_close'
    assert trades[0]['soxl_exit']==90
    assert trades[0]['gross_pct']==pytest.approx((90/101-1)*100)


def test_next_open_gap_outside_and_unfinished_trade_excluded():
    frame,signals=fixture()
    raw=frame.copy()
    raw.loc[frame.index[1],'Open']=112
    trades,rejected=study.simulate(frame,raw,frame,frame.index,signals,support_only=True)
    assert not trades and rejected['next_open_outside_channel']==1
    trades,rejected=study.simulate(frame,frame,frame,frame.index,signals,support_only=True,horizon=18)
    assert not trades and rejected['right_censored']==1


def test_repeated_formation_and_overlapping_positions_not_reentered():
    frame,signals=fixture()
    second=dict(signals[0],i=2,time=frame.index[3])
    trades,_=study.simulate(frame,frame,frame,frame.index,signals+[second],support_only=True,objective='one_r')
    assert len(trades)==1


def test_completed_signal_prefix_does_not_change_with_future_prices():
    rng=np.random.default_rng(71)
    idx=pd.date_range('2025-01-01',periods=240,freq='1h',tz='UTC')
    close=100+np.cumsum(rng.normal(0,1,len(idx)))
    frame=pd.DataFrame(dict(Open=close,High=close+1,Low=close-1,Close=close,Volume=1000),index=idx)
    prefix=study.signals(frame.iloc[:200])
    assert prefix
    changed=frame.copy()
    changed.iloc[200:,:4]*=4
    actual=[r for r in study.signals(changed) if r['i']<200]
    assert prefix==actual


def test_final_partial_bar_only_execution_not_completed_signal():
    schedule=pd.DataFrame({'market_open':[pd.Timestamp('2026-01-05 14:30Z')],
                           'market_close':[pd.Timestamp('2026-01-05 21:00Z')]})
    now=pd.Timestamp('2026-01-05 22:00Z')
    assert len(study.execution_grid(schedule,now))==7
    assert len(study.completed_hour_grid(schedule,now))==6
