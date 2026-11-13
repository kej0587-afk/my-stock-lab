import pandas as pd
import pytest

from scripts.research_soxl_stop_loss import decompose
from scripts.research_leverage_daily_risk import summarize_daily


def example():
    grid=pd.to_datetime(['2026-11-10 20:30Z','2026-11-11 14:30Z','2026-11-11 15:30Z'])
    x=pd.DataFrame(dict(Open=[101.,97.,94.],High=[102.,100.,95.],Low=[100.,94.,93.],Close=[101.,94.,94.]),index=grid)
    l=pd.DataFrame(dict(Open=[100.,90.,84.],High=[101.,92.,85.],Low=[99.,83.,82.],Close=[100.,85.,83.]),index=grid)
    trade=dict(entry_time=grid[0],exit_time=grid[-1],signal_time=grid[0],
        stop=98.,soxx_entry=101.,soxx_return=(94/101-1)*100,soxl_entry=100.,soxl_exit=84.,
        net_pct=-16.2,overnight=True)
    return trade,x,l,grid,grid[1:]


def test_gap_and_post_confirmation_are_separate_and_add_up():
    r=decompose(*example())
    assert r['status']=='ok'
    assert r['overnight_gap_pp']==-10
    assert r['within_bar_pp']==-5
    assert r['post_confirmation_fill_pp']==-1
    assert r['cost_pp']==pytest.approx(-.2)
    assert r['bars_after_touch']==0


def test_missing_partial_bar_is_not_filled_or_zero_loss():
    args=list(example())
    args[2]=args[2].drop(args[3][0])
    assert decompose(*args)=={'status':'path_missing'}


def test_exit_bar_future_low_does_not_affect_attribution():
    args=list(example())
    baseline=decompose(*args)
    args[1].loc[args[3][-1],['Low','Close']]=[1.,2.]
    args[2].loc[args[3][-1],['Low','Close']]=[1.,2.]
    assert decompose(*args)==baseline


def test_partial_bar_touch_waits_for_next_full_bar_confirmation():
    args=list(example())
    args[1].loc[args[3][0],'Low']=97.
    r=decompose(*args)
    assert r['bars_after_touch']==1
    assert r['touch_to_confirmation_wall_hours']==18
    assert r['after_touch_close_to_confirmation_pp']==-15


def test_intraday_boundary_not_labeled_overnight():
    args=list(example())
    grid=pd.to_datetime(['2026-11-11 14:30Z','2026-11-11 15:30Z','2026-11-11 16:30Z'])
    args[1].index=args[2].index=grid
    args[3],args[4]=grid,grid
    args[0].update(entry_time=grid[0],exit_time=grid[-1])
    r=decompose(*args)
    assert r['overnight_gap_pp']==0 and r['intraday_boundary_pp']==-10


def test_missing_last_day_not_reported_as_old_valid_daily_return():
    index=pd.to_datetime(['2026-11-10 05:00Z','2026-11-11 05:00Z','2026-11-13 05:00Z'])
    frame=pd.DataFrame({k:[100.,99.,95.] for k in ['Open','High','Low','Close']},index=index)
    r=summarize_daily(frame,['2026-11-10','2026-11-11','2026-11-12'],'America/New_York')
    assert r['latest_expected_change_pct'] is None
    assert r['missing_expected_dates']==['2026-11-12']
    assert not r['latest_bar_is_complete']
    assert r['last_close']==99.


def test_korean_daily_midnight_utc_previous_date_converts_to_korean_date():
    index=pd.to_datetime(['2026-11-11 15:00Z','2026-11-12 15:00Z'])
    frame=pd.DataFrame({k:[100.,105.] for k in ['Open','High','Low','Close']},index=index)
    r=summarize_daily(frame,['2026-11-12'],'Asia/Seoul')
    assert r['closed_last_date']=='2026-11-12' and r['last_close']==100.
    assert r['latest_bar_close']==105. and not r['latest_bar_is_complete']
