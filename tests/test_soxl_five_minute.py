import pandas as pd
import pytest

from scripts.research_soxl_five_minute import budget_weight, exit_variant, reconcile


def example():
    grid=pd.date_range('2026-11-12 14:30Z',periods=13,freq='5min')
    x=pd.DataFrame(dict(Open=101.,High=102.,Low=100.,Close=101.),index=grid)
    l=pd.DataFrame(dict(Open=100.,High=102.,Low=98.,Close=100.),index=grid)
    trade=dict(entry_time=grid[0],exit_time=grid[-1],signal_time=grid[0],
               stop=99.,soxl_entry=100.,net_pct=-.1998001998002,reason='target_close')
    return trade,x,l,grid


def test_intrabar_low_is_only_known_at_bar_end_and_never_gets_low_fill():
    t,x,l,g=example()
    x.loc[g[0],'Low']=98.
    l.loc[g[0],'Low']=50.
    l.loc[g[1],'Open']=97.
    r=exit_variant(t,x,l,g,use_low=True)
    assert r['trigger_end']==str(g[1]) and r['exit_price']==97.
    assert r['exit_time']==str(g[1])


def test_wick_does_not_trigger_close_rule():
    t,x,l,g=example()
    x.loc[g[0],'Low']=98.
    r=exit_variant(t,x,l,g)
    assert r['trigger_end'] is None and r['exit_time']==str(g[-1])


def test_first_five_minute_close_and_predeclared_delay():
    t,x,l,g=example()
    x.loc[g[1],['Low','Close']]=[97.,98.]
    l.loc[g[2],'Open']=96.
    l.loc[g[3],'Open']=94.
    assert exit_variant(t,x,l,g)['exit_price']==96.
    assert exit_variant(t,x,l,g,extra_delay_bars=1)['exit_price']==94.


def test_fifteen_minute_close_does_not_use_unfinished_window():
    t,x,l,g=example()
    x.loc[g[0],['Low','Close']]=[97.,98.]
    assert exit_variant(t,x,l,g,minutes=15)['trigger_end'] is None
    x.loc[g[2],['Low','Close']]=[97.,98.]
    assert exit_variant(t,x,l,g,minutes=15)['trigger_end']==str(g[3])


def test_future_prices_cannot_change_prior_trigger_or_fill():
    t,x,l,g=example()
    x.loc[g[0],['Low','Close']]=[97.,98.]
    original=exit_variant(t,x,l,g)
    x.loc[g[2]:]*=.1
    l.loc[g[2]:]*=4
    assert exit_variant(t,x,l,g)==original


def test_missing_five_minute_bar_is_not_interpolated():
    t,x,l,g=example()
    assert exit_variant(t,x,l.drop(g[2]),g)=={'status':'missing_path'}


def test_original_exit_has_priority_over_delayed_fill():
    t,x,l,g=example()
    x.loc[g[-2],['Low','Close']]=[97.,98.]
    assert exit_variant(t,x,l,g,extra_delay_bars=1)['exit_time']==str(g[-1])


def test_reconciliation_rejects_different_adjustment_scale():
    t,x,l,g=example()
    schedule=pd.DataFrame(dict(market_open=[g[0]],market_close=[g[0]+pd.Timedelta(hours=6.5)]))
    coarse={s:f.loc[[g[0],g[-1]]].copy() for s,f in [('SOXX',x),('SOXL',l)]}
    fine={'SOXX':x,'SOXL':l}
    assert reconcile(t,fine,coarse,g,schedule)=='ok'
    fine['SOXX']=x*3
    assert reconcile(t,fine,coarse,g,schedule)=='SOXX_exit_open_mismatch'


@pytest.mark.parametrize('budget,loss,expected',[(.25,10,2.5),(.5,20,2.5),(0,10,0),(.5,0,None),
                                               (None,10,None),(.25,float('nan'),None),(-.5,10,None)])
def test_loss_budget_is_scenario_not_missing_to_zero(budget,loss,expected):
    assert budget_weight(budget,loss)==expected
