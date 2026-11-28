import copy

import pandas as pd
import pytest

from scripts.core_full_universe import select_candidates,selection_summary,assert_frozen_extension


def row(ticker="TEST",**overrides):
    return {"티커":ticker,"bucket":"core","has_pos":"False","유형":"개별주","시장":"미국",**overrides}


def test_include_unheld_without_requiring_signal_or_grade():
    master=pd.DataFrame([row(),row("OTHER",**{"게이트상태":"데이터확인"}),
        row("HELD",has_pos=True),row("SGOV",bucket="reserve"),row("LEV",bucket="leverage")])
    holdings=pd.DataFrame({"티커":["HELD"],"보유량":["1,000"]})
    before=master.copy(deep=True)
    kinds,markets,excluded=select_candidates(master,holdings)
    assert kinds=={"TEST":"stock","OTHER":"stock"}
    assert excluded=={"noncore":2,"held":1,"duplicate":0}
    pd.testing.assert_frame_equal(master,before)


def test_actual_holdings_override_false_flag_and_aliases():
    master=pd.DataFrame([row("BRK.B"),row("000001.KS",**{"시장":"한국"}),row("TEST")])
    holdings=pd.DataFrame({"티커":["BRK-B","000001"],"보유량":["1","2"]})
    kinds,_,ex=select_candidates(master,holdings)
    assert list(kinds)==["TEST"] and ex["held"]==2


@pytest.mark.parametrize("bad",[None,"unknown"])
def test_unknown_holding_state_not_silently_unheld(bad):
    with pytest.raises(ValueError):
        select_candidates(pd.DataFrame([row(has_pos=bad)]),pd.DataFrame(columns=["티커","보유량"]))


def test_duplicates_do_not_inflate_denominator_and_conflicts_fail():
    holdings=pd.DataFrame(columns=["티커","보유량"])
    kinds,_,excluded=select_candidates(pd.DataFrame([row(),row()]),holdings)
    assert len(kinds)==1 and excluded["duplicate"]==1
    with pytest.raises(ValueError):
        select_candidates(pd.DataFrame([row(),row(**{"유형":"ETF"})]),holdings)


def test_no_signal_is_a_candidate_count_not_a_zero_return_event():
    dates=pd.bdate_range("2020-01-01",periods=130)
    frames={t:pd.DataFrame({"Close":1.},index=dates) for t in ("OLD","NEW","NONE")}
    frames["SHORT"]=frames["OLD"].iloc[:10]
    snap={"frames":frames,"kinds":dict.fromkeys(frames,"stock"),"cutoff":"2021-01-01"}
    events=[{"ticker":t,"cost_bps":10,"kind":"stock","status":"incomplete_horizon"} for t in ("OLD","NEW")]
    out=selection_summary(snap,{"before":events,"after":events},["OLD"])["after"]
    assert out["full"]["candidates"]==4 and out["full"]["event_candidates"]==2
    assert out["full"]["no_signal"]==1 and out["full"]["insufficient"]==1
    assert out["full"]["event_results"]["groups"]["stock"]["endpoint_valid"]==0
    assert out["additional"]["candidates"]==3
    assert "NONE" not in str(out)


@pytest.mark.parametrize("change",["frame","flow","cutoff","classification"])
def test_frozen_inputs_cannot_be_replaced(change):
    dates=pd.bdate_range("2020-01-01",periods=3)
    base={"frames":{"TEST":pd.DataFrame({"Close":1.},index=dates)},"kinds":{"TEST":"stock"},
          "markets":{"TEST":"US"},"sessions":{"US":dates},"cutoff":"2020-01-03","flow_tickers":["TEST"]}
    expanded=copy.deepcopy(base)
    assert_frozen_extension(expanded,base)
    if change=="frame":expanded["frames"]["TEST"].iloc[0,0]=2
    elif change=="flow":expanded["flow_tickers"]=[]
    elif change=="cutoff":expanded["cutoff"]="2020-01-02"
    else:expanded["kinds"]["TEST"]="ETF"
    with pytest.raises((ValueError,AssertionError)):
        assert_frozen_extension(expanded,base)
