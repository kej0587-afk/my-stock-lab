"""Synthetic restored scope only: no accounts, providers, or private watchlists."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import today_snapshot as store
from stock_lab_core.today_restore_inputs import (
    INPUTS_KEY, SAVED_ATTR_KEYS, capture_restore_inputs, validate_restore_inputs,
    restore_expiry_reason, encode_snapshot_value, decode_snapshot_value,
    flow_input_identity,
)


AT = datetime(2026, 11, 28, 6, 10, tzinfo=timezone.utc)


def fixture():
    base = tuple({"ticker":f"SYN{i:03d}", "name":f"Synthetic {i}", "qty":0.,
                  "fin_score":3, "target_weight":1., "bucket":"core"} for i in range(92))
    auto = tuple({"ticker":f"AUTO{i:02d}", "name":f"Auto {i}", "qty":0.,
                  "fin_score":3, "target_weight":0., "bucket":"flow_candidate"} for i in range(12))
    flow = pd.DataFrame({"Ticker":["SYN000", "AUTO00"], "돈흐름점수":[1.123456789123456, np.nan],
                         "기준일":["2026-11-27"]*2, "active":pd.array([True, pd.NA],dtype="boolean")},
                        index=pd.date_range("2026-11-26",periods=2,tz="Asia/Seoul",name="session"))
    flow.attrs = {"source_time":pd.Timestamp(AT), "source_dates":("2026-11-26", "2026-11-27")}
    args = dict(raw_watch_items=base, base_items=base, watch_items=base+auto, flow_auto_items=auto,
                mode="개인모드",logic_version="fixture:fin-v1",account_context="account-hash-a",
                flow_snapshot={"flow_df":flow, "theme_top5":flow.copy(), "nested":({"date":date(2026,11,27)}, AT)},
                calculated_at=AT, refresh_flow_candidates=True,
                account_inputs={"cash":np.float64(1000.25), "reserve":0., "budget":300., "fx":1400.})
    frame = pd.DataFrame({"티커":[i["ticker"] for i in base+auto], "판정코드":"MACRO_STORM",
                          "Adj점수":1.123456789123456,"buy_amt":12345.678901234567,"qty":np.nan,"has_pos":False})
    frame.attrs={"portfolio_signal_context":args["account_context"],"portfolio_signal_at":AT.isoformat()}
    return args,frame


def validate(envelope,args,**changes):
    current={key:args[key] for key in ("raw_watch_items","base_items","mode","logic_version","account_context")}
    current["now"]=AT+timedelta(minutes=10)
    current.update(changes)
    return validate_restore_inputs(envelope,**current)


def saved(tmp_path):
    args,frame=fixture()
    frame.attrs[INPUTS_KEY]=capture_restore_inputs(**args)
    display=frame.copy(deep=True)
    display.attrs={}
    display["게이트상태"]="방어우선"
    frame.attrs["today_saved_display"]=display
    frame.attrs["today_observation_inputs"]={"SYN000":{"decision":{"buy_amt":12345.678901234567},"fx_input":1400.}}
    frame.attrs["today_observation_cache"]={"key":"evidence-key","columns":pd.DataFrame({"観察":["미확인"]*104})}
    frame.attrs["today_saved_market_guard"]={"mode":"방어", "score":1.123456789123456,
        "benchmark_df":pd.DataFrame({"region":["US"],"return":[-.123456789123456]}),
        "basis":("2026-11-27",AT)}
    path=tmp_path/"snapshot.json"
    sig=frame.attrs[INPUTS_KEY]["signature"]
    store.save_today_queue_summary_snapshot(frame,sig,"2026-11-28 15:10",path=path,owner_scope="owner-a")
    return args,frame,path,sig


def test_fresh_104_restores_same_scope_with_92_current_base_without_recalculation(tmp_path):
    args,original,path,sig=saved(tmp_path)
    frame,loaded_sig,at=store.load_today_queue_summary_snapshot(path=path,owner_scope="owner-a")
    envelope=frame.attrs[INPUTS_KEY]
    assert len(args["base_items"])==92 and len(envelope["watch_items"])==104 and len(envelope["flow_auto_items"])==12
    assert validate(envelope,args)==""
    assert loaded_sig==sig and at=="2026-11-28 15:10"
    pd.testing.assert_frame_equal(frame,original,check_exact=True,check_flags=True)
    pd.testing.assert_frame_equal(frame.attrs["today_saved_display"],original.attrs["today_saved_display"],check_exact=True)
    pd.testing.assert_frame_equal(envelope["flow_snapshot"]["flow_df"],args["flow_snapshot"]["flow_df"],check_exact=True)
    assert isinstance(envelope["flow_snapshot"]["nested"],tuple)
    assert envelope["flow_snapshot"]["nested"][0]["date"]==date(2026,11,27)
    assert envelope["calculated_at"]==AT
    assert frame.attrs["portfolio_signal_context"]==original.attrs["portfolio_signal_context"]
    assert frame.attrs["portfolio_signal_at"]==original.attrs["portfolio_signal_at"]
    assert frame.attrs["today_observation_inputs"]==original.attrs["today_observation_inputs"]
    pd.testing.assert_frame_equal(frame.attrs["today_observation_cache"]["columns"],original.attrs["today_observation_cache"]["columns"])
    assert encode_snapshot_value(frame.attrs["today_saved_market_guard"])==encode_snapshot_value(original.attrs["today_saved_market_guard"])
    frame.attrs[INPUTS_KEY]["watch_items"][0]["target_weight"]=99.
    again,_,_=store.load_today_queue_summary_snapshot(path=path,owner_scope="owner-a")
    assert again.attrs[INPUTS_KEY]["watch_items"][0]["target_weight"]==1.
    assert store.load_today_queue_summary_snapshot(path=path,owner_scope="owner-b")[0].empty


@pytest.mark.parametrize("field",["qty","avg_price","target_weight","fin_score","bucket"])
def test_real_base_input_change_rejects_without_touching_original(field):
    args,frame=fixture()
    envelope=capture_restore_inputs(**args)
    original=encode_snapshot_value(envelope)
    base=deepcopy(args["base_items"])
    base[0][field]="swing" if field=="bucket" else 7.
    assert "변경" in validate(envelope,args,base_items=base)
    assert encode_snapshot_value(envelope)==original
    assert frame["판정코드"].eq("MACRO_STORM").all()


@pytest.mark.parametrize("change",["raw_watch","account","mode","logic"])
def test_owner_watchlist_mode_and_financial_revision_changes_are_not_spoofed(change):
    args,_=fixture()
    envelope=capture_restore_inputs(**args)
    changes={"raw_watch":{"raw_watch_items":args["raw_watch_items"][:-1]},
             "account":{"account_context":"account-hash-b"},"mode":{"mode":"공개모드"},
             "logic":{"logic_version":"fixture:fin-v2"}}[change]
    assert validate(envelope,args,**changes)
    assert envelope["account_context"]=="account-hash-a" and envelope["calculated_at"]==AT


@pytest.mark.parametrize("seconds,valid",[(0,True),(7199,True),(7200,True),(7201,False),(-1,False)])
def test_same_two_hour_boundary_on_initial_restore_and_later_session(seconds,valid):
    args,_=fixture()
    envelope=capture_restore_inputs(**args)
    now=AT+timedelta(seconds=seconds)
    assert (validate(envelope,args,now=now)=="")==valid
    assert restore_expiry_reason(envelope,now)==validate(envelope,args,now=now)


def test_naive_app_calculation_time_is_kst_and_legacy_gains_no_ttl():
    args,_=fixture()
    args["calculated_at"]="2026-11-28 15:10"
    envelope=capture_restore_inputs(**args)
    assert validate(envelope,args,now=AT+timedelta(hours=2))==""
    assert restore_expiry_reason(envelope,AT+timedelta(hours=2,seconds=1))
    assert restore_expiry_reason(None,AT+timedelta(days=100))==""
    assert restore_expiry_reason({},AT+timedelta(days=100))==""


@pytest.mark.parametrize("bad",[None,{},[],{"version":99},{"version":1},"legacy"])
def test_legacy_or_malformed_envelope_is_unknown_not_valid(bad):
    args,_=fixture()
    assert validate(bad,args)


@pytest.mark.parametrize("field,value",[("watch_items",()),("signature","wrong"),
    ("calculated_at","2099-01-01"),("account_context","wrong"),("flow_snapshot",{})])
def test_tampered_inputs_fail_closed(field,value):
    args,_=fixture()
    envelope=capture_restore_inputs(**args)
    envelope[field]=value
    assert "무결성" in validate(envelope,args)


@pytest.mark.parametrize("changes",[{"account_context":{"owner":"fixture"}}, {"flow_snapshot":{"bad":object()}},
    {"calculated_at":"bad"},{"raw_watch_items":None},{"refresh_flow_candidates":False}])
def test_invalid_capture_is_nonthrowing_and_never_marked_valid(changes):
    args,_=fixture()
    args.update(changes)
    assert capture_restore_inputs(**args)=={}


def test_mismatched_calculated_item_values_are_rejected_even_with_same_ticker():
    args,_=fixture()
    args["watch_items"]=deepcopy(args["watch_items"])
    args["watch_items"][0]["target_weight"]=99.
    assert capture_restore_inputs(**args)=={}


def test_codec_types_nan_nullable_categories_and_leading_zero_ticker():
    frame=pd.DataFrame({"ticker":["001234", "005678"],"n":pd.array([1,pd.NA],dtype="Int64"),
                        "category":pd.Categorical(["b","a"],categories=["b","a","unused"],ordered=True),
                        "object":pd.Series([(1,"two"),None],dtype=object),"float":[np.inf,np.nan]})
    frame.attrs={"stamp":pd.Timestamp("2026-11-28",tz="Asia/Seoul"),"duration":pd.Timedelta(days=1),"missing":pd.NaT}
    value={"frame":frame,"numpy":np.int64(3),"tuple":(date(2026,11,28),AT,np.bool_(True)),"tag":{"kind":"frame"}}
    encoded=encode_snapshot_value(value)
    decoded=decode_snapshot_value(json.loads(json.dumps(encoded,allow_nan=False)))
    pd.testing.assert_frame_equal(decoded["frame"],frame,check_exact=True)
    assert type(decoded["numpy"]) is np.int64
    assert isinstance(decoded["tuple"],tuple) and decoded["tuple"]==value["tuple"]
    assert decoded["tag"]==value["tag"]
    assert encode_snapshot_value(decoded)==encoded


@pytest.mark.parametrize("bad",[{"kind":"pickle","value":"unused"},{"kind":"frame"},
    {"kind":"dict","items":[["a",1],["a",2]]},{"kind":"numpy","dtype":"object","value":0}])
def test_codec_rejects_unknown_or_malformed_types(bad):
    with pytest.raises((ValueError,TypeError,KeyError)):
        decode_snapshot_value(bad)


@pytest.mark.parametrize("damage",["codec","display_type","display_identity","guard_type"])
def test_invalid_extra_attrs_keep_raw_only_and_cannot_hydrate(tmp_path,damage):
    _,original,path,_=saved(tmp_path)
    location,_=store._snapshot_location(path,"owner-a")
    payload=json.loads(location.read_text(encoding="utf8"))
    if damage=="codec":
        payload["restore_attrs"]={"kind":"unknown"}
    else:
        attrs=decode_snapshot_value(payload["restore_attrs"])
        if damage=="guard_type":
            attrs["today_saved_market_guard"]="invalid"
        else:
            attrs["today_saved_display"]="invalid" if damage=="display_type" else pd.DataFrame({"티커":["OTHER"]})
        payload["restore_attrs"]=encode_snapshot_value(attrs)
    location.write_text(json.dumps(payload,allow_nan=False),encoding="utf8")
    loaded,_,_=store.load_today_queue_summary_snapshot(path=path,owner_scope="owner-a")
    pd.testing.assert_frame_equal(loaded,original,check_exact=True)
    assert not any(key in loaded.attrs for key in SAVED_ATTR_KEYS)


def test_legacy_snapshot_without_extra_attrs_still_loads_at_original_time(tmp_path):
    _,frame=fixture()
    path=tmp_path/"legacy.json"
    store.save_today_queue_summary_snapshot(frame,"legacy","2020-01-01 10:00",path=path)
    payload=json.loads(path.read_text(encoding="utf8"))
    payload.pop("restore_attrs")
    path.write_text(json.dumps(payload),encoding="utf8")
    loaded,sig,at=store.load_today_queue_summary_snapshot(path=path)
    assert len(loaded)==104 and sig=="legacy" and at=="2020-01-01 10:00"
    assert loaded.attrs==frame.attrs and INPUTS_KEY not in loaded.attrs


def test_local_concat_strips_only_restore_attrs_without_mutating_persisted_input():
    args,frame=fixture()
    frame.attrs[INPUTS_KEY]=capture_restore_inputs(**args)
    display=frame.copy(deep=True);display.attrs={}
    frame.attrs["today_saved_display"]=display
    parts=[frame.iloc[:1].copy(),frame.iloc[1:].copy()]
    for part in parts:
        part.attrs={key:value for key,value in part.attrs.items() if key not in SAVED_ATTR_KEYS}
    combined=pd.concat(parts)
    pd.testing.assert_frame_equal(combined,frame,check_exact=True)
    assert INPUTS_KEY in frame.attrs and "today_saved_display" in frame.attrs


def test_flow_identity_ignores_only_top_level_cache_and_mapping_insertion_order():
    args,_=fixture()
    flow=args["flow_snapshot"]
    before=encode_snapshot_value(flow)
    same=dict(reversed(list(deepcopy(flow).items())))
    same.update(_flow_shortlist_df=pd.DataFrame({"derived":[99]}),_unsupported_cache=object())
    assert flow_input_identity(flow) and flow_input_identity(flow)==flow_input_identity(same)
    restored=decode_snapshot_value(json.loads(json.dumps(encode_snapshot_value(flow),allow_nan=False)))
    assert flow_input_identity(restored)==flow_input_identity(flow)
    assert encode_snapshot_value(flow)==before


@pytest.mark.parametrize("change",["value","date","index","nested_private","attrs","add_public","remove_public"])
def test_flow_identity_detects_every_nonexcluded_evidence_change(change):
    args,_=fixture()
    original=args["flow_snapshot"]
    changed=deepcopy(original)
    frame=changed["flow_df"]
    if change=="value": frame.iloc[0,frame.columns.get_loc("돈흐름점수")]+=1
    if change=="date": frame["기준일"]="2026-11-28"
    if change=="index": frame.index=frame.index+pd.Timedelta(days=1)
    if change=="nested_private": changed["nested"][0]["_source_revision"]=2
    if change=="attrs": frame.attrs["_source_revision"]=2
    if change=="add_public": changed["new_market_input"]=1
    if change=="remove_public": changed.pop("theme_top5")
    assert flow_input_identity(original)!=flow_input_identity(changed)


def test_known_sector_display_cache_does_not_invalidate_source_flow():
    original = {"flow_df": pd.DataFrame({"score": [1.]})}
    shown = dict(original, sector_ability_cards=[{"title": "derived card"}], sector_cards_view_version="v1")
    assert flow_input_identity(original) == flow_input_identity(shown)


def test_flow_identity_normalizes_nested_mapping_order_but_not_sequence_order():
    first={"meta":{"one":1,"two":2},"sequence":(1,2)}
    second={"sequence":(1,2),"meta":{"two":2,"one":1}}
    assert flow_input_identity(first)==flow_input_identity(second)
    second["sequence"]=(2,1)
    assert flow_input_identity(first)!=flow_input_identity(second)


@pytest.mark.parametrize("bad",[None,[],{"public":object()}])
def test_flow_identity_unsupported_is_unknown_not_a_valid_hash(bad):
    assert flow_input_identity(bad)==""
