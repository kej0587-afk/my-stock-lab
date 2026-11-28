import numpy as np
import pandas as pd

from scripts.core_gate_event_comparison import recovery_events, paired_summary, run_study
from scripts import sim_core_first_buy as legacy


def fixture():
    days=pd.bdate_range("2018-06-01",periods=330)
    values=np.full(330,100.)
    values[180:260]=np.linspace(99,65,80)
    values[260:]=120.
    frame=pd.DataFrame({"Open":values,"Close":values,"Low":values*.98},index=days)
    gate=pd.DataFrame({"closed_KR":True,"closed_US":True},index=days[200:])
    gate.loc[days[264]:]=False
    bench=pd.Series(100.,index=days)
    return days,frame,gate,bench


def test_same_recovery_and_gate_as_legacy_when_history_is_complete():
    days,frame,gate,bench=fixture()
    old=legacy.events_for("TEST","KR",frame,{"KR":gate},bench)
    new=recovery_events(frame,gate,bench,days,"KR")
    assert len(old)==len(new)==1
    assert new[0]=={"signal":pd.Timestamp(old[0]["신호일"]),"gate":pd.Timestamp(old[0]["게이트 열림일"])}


def test_boolean_series_without_initial_none_still_generates_event():
    days,frame,gate,bench=fixture()
    # Legacy identity `is True` rejects numpy bools when no early None exists.
    gate=gate.reindex(days[180:],method="bfill")
    assert legacy.events_for("TEST","KR",frame.iloc[180:],{"KR":gate},bench)==[]
    new=recovery_events(frame.iloc[180:],gate,bench,days,"KR")
    assert len(new)==1 and new[0]["signal"]==days[260]


def test_missing_asset_bar_does_not_hide_gate_opening():
    days,frame,gate,bench=fixture()
    new=recovery_events(frame.drop(days[264]),gate,bench,days,"KR")
    assert new[0]["gate"]==days[264]


def test_never_open_and_no_future_gate_forward_fill():
    days,frame,gate,bench=fixture()
    gate[:]=True
    new=recovery_events(frame,gate,bench,days,"KR")
    assert new==[{"signal":days[260],"gate":None}]
    assert recovery_events(frame,gate.iloc[:40],bench,days,"KR")==[]


def test_unmatched_events_do_not_enter_paired_returns():
    base={"ticker":"TEST","signal":pd.Timestamp("2024-01-02"),"gate":None,"kind":"stock",
          "status":"ok","end":"2024-04-01","A_return":.1,"difference":.1}
    after={**base,"gate":pd.Timestamp("2024-01-04"),"difference":.02}
    added={**after,"ticker":"OTHER"}
    r=paired_summary([base],[after,added])
    assert (r['common'],r['added'],r['removed'],r['gate_date_changed'])==(1,1,0,1)
    assert r['groups']['stock']['paired_valid']==1
    assert abs(r['groups']['stock']['difference_change_mean']+.08)<1e-12


def test_end_to_end_fixed_snapshot_does_not_mutate_inputs(monkeypatch):
    from scripts import core_gate_event_comparison as study
    days,frame,gate,bench=fixture()
    frames={t:frame.copy() for t,_ in legacy.BENCH}
    frames['TEST']=frame.copy()
    old={r:gate.copy() for r in ('KR','US')}
    new={r:gate.copy() for r in ('KR','US')}
    new['KR'].loc[days[264]:days[266],['closed_KR','closed_US']]=True
    monkeypatch.setattr(study,'generate_gates',lambda b,f,legacy:old if legacy else new)
    snapshot={'frames':frames,'kinds':{'TEST':'stock'},'markets':{'TEST':'KR'},
              'flow_tickers':['QQQ'],'sessions':{'KR':days,'US':days},'cutoff':str(days[-1].date())}
    copy=frame.copy(deep=True)
    # Flat relative benchmark ensures own recovery passes the RS condition.
    snapshot['frames']['^KS11']=pd.DataFrame({'Close':bench,'Open':bench,'Low':bench},index=days)
    summary,rows,_=run_study(snapshot)
    assert summary['paired']['10']['common']==1
    assert summary['paired']['10']['gate_date_changed']==1
    assert summary['versions']['after']['costs']['10']['groups']['stock']['endpoint_valid']==1
    pd.testing.assert_frame_equal(snapshot['frames']['TEST'],copy)
