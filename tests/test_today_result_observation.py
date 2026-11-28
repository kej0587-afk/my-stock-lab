"""Frozen synthetic Today inputs only; no private files, providers or clock."""
from copy import deepcopy
from unittest.mock import MagicMock
import ast
import io
from pathlib import Path
import socket
import zipfile

import pandas as pd
import pytest

from stock_lab_core.today_queue_session import (
    EXPECTED_CONTEXT_KEY, LAST_RUN_KEY, ORIGIN_KEY, SIGNATURE_KEY, SUMMARY_KEY,
    restore_cached_summary, remember_calculated_summary, finalize_summary,
)
from stock_lab_core.today_result_observation import (
    META_COLUMNS, OBS_COLUMNS, result_metadata, attach_result_metadata,
    attach_market_observation, metadata_frame, observation_frame, render_result_observation,
    reuse_or_build_market_observation, unheld_observation_tables, capture_observation_inputs, INPUTS_KEY,
)
from stock_lab_core.backup import build_review_export_zip


def source(**overrides):
    row = {"티커": "EXAMPLE", "종목명": "Synthetic", "판정분류": "buyish", "판정코드": "TEST_ENTRY",
           "최종읽기": "정밀확인", "실행메모": "정찰", "🔥기술적 타점": "진입",
           "계산시각": "2026-11-28 10:19:00 KST", "가격입력ID": "fixed-price-id",
           "가격자료기준일": "2026-11-27", "지표마지막봉": "2026-11-27",
           "가격신선도": "current", "가격신선도검증대상": True,
           "데이터상태": "OK", "RR값": 2., "R/R성격": "차트구조",
           "RSI": 50., "MFI": 50., "볼린저 %B": .5, "후보점수": 88, "부족액": "1000",
           "게이트상태": "실행가능", "게이트근거": "original", "qty": 0., "has_pos": False}
    row.update(overrides)
    frame = pd.DataFrame([row])
    frame.attrs = {"portfolio_signal_context": "scope-a", "portfolio_signal_at": "2026-11-28T01:19:00Z"}
    return frame


def metadata(frame, *, fresh=True, context="scope-a"):
    state = {SIGNATURE_KEY: "sig", LAST_RUN_KEY: "2026-11-28 10:19", ORIGIN_KEY: "저장 결과 복원"}
    return result_metadata(frame, state, run_summary=fresh, signature="sig", account_context=context)


def observe(frame, meta=None):
    meta = meta or metadata(frame)
    displayed = attach_result_metadata(frame, meta)
    displayed["시장실행상태"] = "시장방어: 신규매수 중단"
    displayed["게이트상태"] = "방어우선"
    displayed["게이트근거"] = "시장방어"
    return attach_market_observation(displayed, frame, meta)


@pytest.mark.parametrize("fresh,origin,expected", [(True,"세션 계산 재사용","새 전체 계산"),
    (False,"저장 결과 복원","저장 결과 복원"), (False,"세션 계산 재사용","세션 계산 재사용")])
def test_metadata_separates_fresh_restore_and_rerender_without_restamping(fresh, origin, expected):
    state = {SIGNATURE_KEY:"sig", LAST_RUN_KEY:"2026-11-28 13:52", ORIGIN_KEY:origin}
    meta = result_metadata(source(),state,run_summary=fresh,signature="sig",account_context="scope-a")
    assert meta["점검결과상태"] == expected
    assert meta["점검원계산시각"] == "2026-11-28 13:52"


def test_restored_104_context_mismatch_remains_data_and_unknown_without_new_calculation():
    frame = pd.concat([source(**{"티커":f"X{i}"}) for i in range(104)],ignore_index=True)
    frame.attrs["portfolio_signal_context"] = "scope-a"
    before = frame.copy(deep=True)
    state = {EXPECTED_CONTEXT_KEY:"scope-b"}
    restored = restore_cached_summary(state,"owner","sig",load_today_queue_summary_snapshot=lambda **_: (frame,"sig","2026-11-28 10:19"))
    assert restored["게이트상태"].eq("데이터확인").all()
    assert restored["저장당시게이트상태"].eq("실행가능").all()
    assert state[LAST_RUN_KEY] == "2026-11-28 10:19"
    meta = result_metadata(restored,state,run_summary=False,signature="sig",account_context="scope-b")
    assert meta["점검결과출처"] == "저장 결과 복원"
    assert meta["점검결과상태"] == "현재 입력 달라 재계산 필요"
    observed = observe(restored,meta)
    assert observed["시장만모의해제"].eq("미확인").all()
    assert observed["시장만모의해제_실행가능"].eq("미확인").all()
    pd.testing.assert_frame_equal(frame,before)
    saves = []
    finalize_summary(state,restored,"sig",False,"owner",dedupe_dashboard_summary_df=lambda x:x,
                     save_today_queue_summary_snapshot=lambda *a,**k:saves.append(a))
    assert saves == []


def test_fresh_calculation_clears_stale_origin_and_preserves_original_payload():
    state = {EXPECTED_CONTEXT_KEY:"scope-a",ORIGIN_KEY:"저장 결과 복원","today_queue_summary_stale_reason":"old"}
    frame = source()
    remember_calculated_summary(state,frame,"sig","2026-11-28 13:52")
    meta = result_metadata(frame,state,run_summary=True,signature="sig",account_context="scope-a")
    assert meta["점검결과상태"] == "새 전체 계산"
    assert "today_queue_summary_stale_reason" not in state
    assert state[SUMMARY_KEY] is frame


@pytest.mark.parametrize("changes,expected", [
    ({"RR값":.5},"rr"), ({"R/R성격":"투영상단"},"rr"),
    ({"판정코드":"HARD_BLOCK_OVERWEIGHT"},"비중"),
    ({"상위시간대상태":"상위 시간대 경고"},"추세"),
    ({"판정코드":"STRUCTURE_DAMAGE"},"방어"),
    ({"판정코드":"HARD_BLOCK_MFI_OVERHEAT"},"과열"),
    ({"돈흐름_판정":"눌림대기","돈흐름신선도":"aligned","돈흐름_거래량기준일":"2026-11-27"},"돈흐름"),
])
def test_only_attach_market_is_relaxed_other_real_gate_vetoes_remain(changes,expected):
    frame=source(**changes)
    original=frame.copy(deep=True)
    row=observe(frame).iloc[0]
    assert row["시장만모의해제"] == "다른 조건도 차단"
    reason=row["시장만모의해제_근거"]
    assert ("R/R" in reason if expected=="rr" else expected in reason)
    assert row["시장만모의해제_실행가능"] == "미확인"
    pd.testing.assert_frame_equal(frame,original)


@pytest.mark.parametrize("code", ["MACRO_STORM", "HARD_BLOCK_MACRO_STORM", "MACRO_STORM_HOLDING_CAUTION"])
def test_original_macro_is_not_an_independent_other_gate(code):
    frame = source(판정코드=code)
    row = observe(frame).iloc[0]
    assert row["시장만모의해제"] == "미확인"
    assert "원판정에 시장조건 포함" in row["시장만모의해제_근거"]
    assert frame.iloc[0]["판정코드"] == code


@pytest.mark.parametrize("weight,expected", [(0., "미확인"), (11., "다른 조건도 차단")])
def test_shared_macro_check_is_excluded_but_independent_weight_veto_remains(weight, expected):
    frame = source()
    sink = {"EXAMPLE": {"post": {"target_w":10., "current_w":weight, "trend":"상승", "rs_label":"강함"},
                        "row":frame.iloc[0].to_dict(), "has_pos":False}}
    frame.attrs[INPUTS_KEY] = capture_observation_inputs(sink,cash=1000.,reserve=0.,fx=1400.,macro=5.,mode="개인모드")
    row = observe(frame).iloc[0]
    assert row["시장만모의해제"] == expected
    assert "원판정에 시장조건 포함" in row["시장만모의해제_근거"]
    if weight:
        assert "비중:" in row["시장만모의해제_근거"]


def test_clean_gate_with_zero_cash_amount_and_overweight_is_never_permission():
    frame=source(cash_available=0,buy_amt=0,현재비중=20,목표비중=10)
    row=observe(frame).iloc[0]
    assert row["시장만모의해제_선별결과"] == "선별 통과 · 실행 미확인"
    assert row["시장만모의해제"] == "미확인" and row["시장만모의해제_실행가능"] == "미확인"
    assert "현금" in row["시장만모의해제_미확인항목"]


@pytest.mark.parametrize("field,value",[("가격자료기준일","2026-11-25"),("가격신선도","stale"),
    ("데이터상태","입력 변경"),("RSI",float("nan")),("돈흐름신선도","older")])
def test_date_data_or_indicator_uncertainty_is_unknown(field,value):
    frame=source(**{"돈흐름_판정":"눌림대기","돈흐름신선도":"aligned","돈흐름_거래량기준일":"2026-11-27",field:value})
    row=observe(frame).iloc[0]
    assert row["시장만모의해제"] == "미확인"
    assert row["시장만모의해제_선별결과"] == "미재생"


def test_duplicate_and_restored_context_are_not_replayed():
    frame=pd.concat([source(),source()],ignore_index=True)
    frame.attrs["portfolio_signal_context"]="scope-a"
    assert observe(frame)["시장만모의해제_근거"].str.contains("유일 매칭").all()
    assert "원시장연결 시점" in observe(source(),metadata(source(),fresh=False)).iloc[0]["시장만모의해제_근거"]


@pytest.mark.parametrize("bad", [
    {"가격자료기준일":"", "지표마지막봉":""},
    {"가격자료기준일":"2026-11-25", "지표마지막봉":"2026-11-25", "가격신선도":"stale"},
    {"가격자료기준일":"2026-11-25"},
])
def test_invalid_date_row_does_not_poison_valid_same_market_rows(bad):
    frame = pd.concat([source(RR값=.5), source(티커="OTHER", **bad)], ignore_index=True)
    before = frame.copy(deep=True)
    result = observe(frame)
    assert result.iloc[0]["시장만모의해제"] == "다른 조건도 차단"
    assert result.iloc[1]["시장만모의해제"] == "미확인"
    assert result.iloc[1]["시장만모의해제_선별결과"] == "미재생"
    pd.testing.assert_frame_equal(frame, before)


def test_each_row_still_requires_original_and_display_date_agreement():
    frame = source(RR값=.5)
    shown = frame.copy(deep=True)
    shown["가격자료기준일"] = "2026-11-26"
    shown["시장실행상태"] = "시장방어: 신규매수 중단"
    result = attach_market_observation(shown, frame, metadata(frame))
    assert result.iloc[0]["시장만모의해제_선별결과"] == "미재생"
    assert "가격자료기준일 불일치" in result.iloc[0]["시장만모의해제_근거"]


def test_observation_uses_pre_display_prose_and_preserves_all_existing_columns(monkeypatch):
    monkeypatch.setattr(socket.socket,"connect",lambda *a:pytest.fail("network forbidden"))
    frame=source()
    meta=metadata(frame)
    displayed=attach_result_metadata(frame,meta)
    displayed["시장실행상태"]="시장방어: 신규매수 중단"
    displayed["실행메모"]="레버리지 시장대기"
    before=displayed.copy(deep=True)
    observed=attach_market_observation(displayed,frame,meta)
    pd.testing.assert_frame_equal(observed[before.columns],before)
    pd.testing.assert_frame_equal(displayed,before)
    assert observed.iloc[0]["시장만모의해제_선별결과"] == "선별 통과 · 실행 미확인"
    ui=MagicMock()
    render_result_observation(ui,observed)
    assert any("주문가능액·최종체크가 미검증이면 ‘시장만 차단’으로 확정하지 않습니다" in str(call) for call in ui.caption.call_args_list)


def test_csv_metadata_equals_screen_and_unknown_is_not_zero():
    frame=source()
    meta=metadata(frame,context="scope-b",fresh=False)
    result=observe(frame,meta)
    payload=build_review_export_zip({"01.csv":result,"12.csv":metadata_frame(result),"13.csv":observation_frame(result)})
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        one=pd.read_csv(io.BytesIO(archive.read("01.csv")))
        twelve=pd.read_csv(io.BytesIO(archive.read("12.csv")))
        thirteen=pd.read_csv(io.BytesIO(archive.read("13.csv")))
    assert one[list(META_COLUMNS)].iloc[0].to_dict() == twelve.iloc[0].to_dict() == meta
    assert thirteen["시장만모의해제_실행가능"].eq("미확인").all()


def test_app_wires_observation_after_gate_from_pre_display_source_and_exports_metadata():
    tree=ast.parse((Path(__file__).parents[1]/"app.py").read_text(encoding="utf-8"))
    queue=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_render_today_queue_tab")
    code=ast.unparse(queue)
    assert code.index("original_observation_input =") < code.index("prepare_today_queue_display(")
    assert code.index("prepare_execution_context(") < code.index("reuse_or_build_market_observation(")
    export=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="render_today_review_export_download")
    code=ast.unparse(export)
    assert "12_today_result_metadata.csv" in code and "13_market_only_observation.csv" in code


def test_same_calculation_evidence_reused_without_calling_checks(monkeypatch):
    import stock_lab_core.today_result_observation as module
    frame=source(**{"RR값":.5})
    shown=frame.copy(deep=True)
    shown["시장실행상태"]="시장방어: 신규매수 중단"
    state={}
    first=reuse_or_build_market_observation(shown,frame,metadata(frame),state,signature="sig",context="scope-a")
    monkeypatch.setattr(module,"attach_market_observation",lambda *a:pytest.fail("must reuse evidence"))
    again=reuse_or_build_market_observation(shown,frame,metadata(frame,fresh=False),state,signature="sig",context="scope-a")
    cols=[key for key in OBS_COLUMNS if key!="시장만모의해제_증거출처"]
    pd.testing.assert_frame_equal(first[cols],again[cols])
    assert "재사용" in again.iloc[0]["시장만모의해제_증거출처"]


@pytest.mark.parametrize("missing", [None, float("nan"), pd.NA, "", "absent"])
def test_unheld_missing_quantity_and_zero_have_same_key_without_mutating_source(missing):
    from stock_lab_core.today_result_observation import _observation_key
    raw = source(qty=missing)
    if missing == "absent" if isinstance(missing, str) else False:
        raw = raw.drop(columns="qty")
    before = raw.copy(deep=True)
    filled = raw.copy(deep=True)
    filled["qty"] = 0.
    kwargs = dict(signature="sig", context="scope-a", calculation_id=raw.attrs["portfolio_signal_at"])
    assert _observation_key(raw, raw, **kwargs) == _observation_key(filled, filled, **kwargs)
    pd.testing.assert_frame_equal(raw, before)


@pytest.mark.parametrize("changes", [
    {"qty":1.}, {"qty":-1.}, {"qty":float("inf")}, {"qty":"invalid"}, {"qty":False},
    {"has_pos":True}, {"has_pos":None}, {"has_pos":"False"},
])
def test_real_quantity_change_conflict_or_unknown_ownership_never_matches_unheld_zero(changes):
    from stock_lab_core.today_result_observation import _observation_key
    raw, changed = source(), source(**changes)
    kwargs = dict(signature="sig", context="scope-a", calculation_id=raw.attrs["portfolio_signal_at"])
    assert _observation_key(raw, raw, **kwargs) != _observation_key(changed, changed, **kwargs)


def test_session_ownership_zero_repair_reuses_all_evidence_without_recheck(monkeypatch):
    import stock_lab_core.today_result_observation as module
    raw = pd.concat([source(qty=float("nan"), RR값=.5),
                     source(티커="OTHER", qty=float("nan"), RR값=.5)], ignore_index=True)
    original = raw.copy(deep=True)
    shown = raw.copy(deep=True)
    shown["시장실행상태"] = "시장방어: 신규매수 중단"
    shown["애널목표조회시각"] = "first display"
    state = {EXPECTED_CONTEXT_KEY:"scope-a", "_app_holdings_table":pd.DataFrame([{"티커":"EXAMPLE", "보유량":0.}])}
    remember_calculated_summary(state, raw, "sig", "2026-11-28 10:19")
    first = reuse_or_build_market_observation(shown,raw,metadata(raw),state,signature="sig",context="scope-a")
    restored = restore_cached_summary(state,"owner","sig",
        load_today_queue_summary_snapshot=lambda **kw:pytest.fail("same session must not load"))
    assert restored.iloc[0]["qty"] == 0 and pd.isna(restored.iloc[1]["qty"])
    rerender = restored.copy(deep=True)
    rerender["시장실행상태"] = "시장방어: 신규매수 중단"
    rerender["애널목표조회시각"] = "later display"
    monkeypatch.setattr(module,"attach_market_observation",lambda *a:pytest.fail("must reuse evidence"))
    second = reuse_or_build_market_observation(rerender,restored,metadata(restored,fresh=False),state,signature="sig",context="scope-a")
    cols = [key for key in OBS_COLUMNS if key != "시장만모의해제_증거출처"]
    pd.testing.assert_frame_equal(first[cols], second[cols])
    assert second["시장만모의해제_증거출처"].str.contains("재사용").all()
    pd.testing.assert_frame_equal(raw, original)


@pytest.mark.parametrize("change",["signature","context","calculation","market","price","new_session"])
def test_changed_evidence_key_or_legacy_session_cannot_reuse(change):
    frame=source(**{"RR값":.5})
    shown=frame.copy(deep=True)
    shown["시장실행상태"]="시장방어: 신규매수 중단"
    state={}
    reuse_or_build_market_observation(shown,frame,metadata(frame),state,signature="sig",context="scope-a")
    signature,context="sig","scope-a"
    if change=="signature": signature="new"
    if change=="context": context="scope-b"
    if change=="calculation": frame.attrs["portfolio_signal_at"]="2026-11-28T04:52:00Z"
    if change=="market": shown["시장실행상태"]="정상"
    if change=="price": shown["가격신선도"]="stale"
    if change=="new_session": state={}
    result=reuse_or_build_market_observation(shown,frame,metadata(frame,fresh=False,context=context),state,signature=signature,context=context)
    assert result.iloc[0]["시장만모의해제"]=="미확인"
    assert result.iloc[0]["시장만모의해제_선별결과"]=="미재생"


def test_ui_only_explicit_unheld_and_separates_unknown_held_state():
    rows=[source(),source(티커="HELD",has_pos=True,qty=2),source(티커="UNKNOWN",has_pos=None),
          source(티커="CONFLICT",has_pos=False,qty=1),source(티커="STRING",has_pos="False")]
    unheld,unknown=unheld_observation_tables(pd.concat(rows,ignore_index=True))
    assert len(unheld)==1 and "EXAMPLE" in unheld.iloc[0]["종목"]
    assert len(unknown)==3 and unknown["시장 차단 관찰"].eq("자료 부족").all()
    assert list(unheld)==["종목","섹터·돈흐름 기준일","실제 최종 게이트","시장 차단 관찰","원판정 재현","시장방어 제외 비교","독립 최종체크","남은 사유"]


@pytest.mark.parametrize("qty", [None, float("nan"), pd.NA, "", 0., "absent"])
def test_explicit_unheld_remains_visible_when_quantity_is_missing(qty):
    frame = source(qty=qty)
    if isinstance(qty, str) and qty == "absent":
        frame = frame.drop(columns="qty")
    unheld, unknown = unheld_observation_tables(frame)
    assert len(unheld) == 1 and unknown.empty
    frame["has_pos"] = True
    if qty != 0 if isinstance(qty, (int, float)) else True:
        held, unknown = unheld_observation_tables(frame)
        assert held.empty and unknown.empty


@pytest.mark.parametrize("qty", [1., -1., float("inf"), "invalid", False])
def test_unheld_quantity_conflict_or_invalid_value_is_separate_unknown(qty):
    unheld, unknown = unheld_observation_tables(source(qty=qty))
    assert unheld.empty and len(unknown) == 1
    assert unknown.iloc[0]["시장 차단 관찰"] == "자료 부족"


@pytest.mark.parametrize("change,reason",[({"structure_risk":True},"구조/추세"),({"mfi":90.},"과열"),
    ({"current_w":11.,"target_w":10.},"비중")])
def test_original_precision_inputs_use_shared_pure_final_checks(change,reason):
    frame=source()
    c={"dd":-.1,"day_ret":0.,"live_gap_shock":False,"structure_risk":False,
       "trend":"상승","rs_label":"강함","mtf_bias_label":"상위 시간대 우호",
       "mfi":50.,"rsi":50.,"pct_b":.5,"core_dca_rate":0.,"bucket":"swing",
       "target_w":10.,"current_w":0.,"buy_amt":1000.,"effective_total_asset":10000.}
    c.update(change)
    sink={"EXAMPLE":{"post":c,"row":frame.iloc[0].to_dict(),"has_pos":False}}
    frame.attrs[INPUTS_KEY]=capture_observation_inputs(sink,cash=1000.,reserve=0.,fx=1400.,macro=0.,mode="개인모드")
    before=deepcopy(frame.attrs)
    row=observe(frame).iloc[0]
    assert row["시장만모의해제"]=="다른 조건도 차단" and reason in row["시장만모의해제_근거"]
    assert "공통체크" in row["시장만모의해제_확인범위"]
    assert "주문가능액" in row["시장만모의해제_미확인항목"]
    assert row["시장만모의해제_실행가능"]=="미확인"
    assert frame.attrs==before
