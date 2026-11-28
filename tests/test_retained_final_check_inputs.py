"""Original-input final checks: type parity, missing evidence and no permission."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.final_check_rows import build_risk_check_rows
from stock_lab_core.today_restore_inputs import encode_snapshot_value, decode_snapshot_value
from stock_lab_core.today_result_observation import (
    INPUTS_KEY, OBS_COLUMNS, CACHE_KEY, capture_observation_inputs, replay_retained_final_checks,
    retained_final_check_inputs, reuse_or_build_market_observation,
)
from tests.test_today_result_observation import source, observe, metadata


def retained(**changes):
    frame = source()
    c = dict(dd=-.25, day_ret=-.01, live_gap_shock=False, structure_risk=True,
             trend="상승", rs_label="강함", mtf_bias_label="상위 시간대 우호",
             mtf_bias_text="", mfi=50., rsi=50., pct_b=.5,
             core_dca_rate=0., core_dca_label="", bucket="swing",
             current_w=0., target_w=10., buy_amt=1000., effective_total_asset=10000.)
    c.update(changes)
    envelope = capture_observation_inputs(
        {"EXAMPLE": {"post": c, "row": frame.iloc[0].to_dict(), "has_pos": False}},
        cash=1000., reserve=0., fx=1400., macro=5., mode="개인모드")["EXAMPLE"]
    return frame, envelope


@pytest.mark.parametrize("flags", [(False, True), (False, False), (True, False)])
@pytest.mark.parametrize("indicators", [(-.25, 50.), (-.1, 90.), (-.1, 50.)])
def test_numpy_flags_replay_exact_same_shared_checks_and_preserve_original(flags, indicators):
    frame, envelope = retained(live_gap_shock=flags[0], structure_risk=flags[1],
                               dd=indicators[0], mfi=indicators[1])
    native = deepcopy(envelope)
    for key in ("live_gap_shock", "structure_risk"):
        envelope["decision"][key] = np.bool_(envelope["decision"][key])
    envelope["has_pos"] = np.bool_(False)
    envelope = decode_snapshot_value(encode_snapshot_value(envelope))
    before = encode_snapshot_value(envelope)
    raw = frame.iloc[0].to_dict()
    result = replay_retained_final_checks(envelope, raw)
    assert result == replay_retained_final_checks(native, raw)
    c = native["decision"]
    expected = build_risk_check_rows(is_core_dca=False, **{key: c[key] for key in (
        "dd", "live_gap_shock", "day_ret", "structure_risk", "trend", "rs_label",
        "mtf_bias_label", "mtf_bias_text", "mfi", "rsi", "pct_b", "core_dca_label")})
    assert result[0][:len(expected)] == expected
    frame.attrs[INPUTS_KEY] = {"EXAMPLE": envelope}
    observed = observe(frame)
    expected_display = frame.copy()
    expected_display["게이트상태"] = "방어우선"
    expected_display["게이트근거"] = "시장방어"
    pd.testing.assert_frame_equal(observed[list(frame.columns)], expected_display)
    assert observed.iloc[0]["시장만모의해제_실행가능"] == "미확인"
    assert "주문가능액" in observed.iloc[0]["시장만모의해제_미확인항목"]
    assert encode_snapshot_value(envelope) == before


@pytest.mark.parametrize("bad", [None, "False", "True", 0, 1, [], {}, pd.NA])
def test_flag_missing_or_invalid_type_never_inferred(bad):
    frame, envelope = retained(structure_risk=bad)
    checks, verified, gaps = replay_retained_final_checks(envelope, frame.iloc[0].to_dict())
    assert not any(row["점검항목"] in ("구조/추세", "과열") for row in checks)
    assert "structure_risk(" in gaps
    assert not any("정밀 구조" in note for note in verified)


@pytest.mark.parametrize("bad", [True, np.bool_(False), None, "invalid", float("nan"), float("inf")])
def test_non_numeric_evidence_is_not_zero_or_pass(bad):
    frame, envelope = retained(mfi=bad)
    _, issues = retained_final_check_inputs(envelope, frame.iloc[0].to_dict())
    assert any("mfi(" in item for item in issues["risk"])


def test_finite_numeric_strings_use_precision_scalar_conversion_only_on_copy():
    frame, envelope = retained()
    expected = replay_retained_final_checks(envelope, frame.iloc[0].to_dict())
    for key in ("dd", "day_ret", "mfi", "rsi", "pct_b", "core_dca_rate", "target_w", "current_w"):
        envelope["decision"][key] = str(envelope["decision"][key])
    assert replay_retained_final_checks(envelope, frame.iloc[0].to_dict()) == expected
    assert isinstance(envelope["decision"]["dd"], str)


def test_missing_field_and_identity_are_explicit_and_do_not_authorize():
    frame, envelope = retained()
    del envelope["decision"]["structure_risk"]
    frame.attrs[INPUTS_KEY] = {"EXAMPLE": envelope}
    row = observe(frame).iloc[0]
    assert "structure_risk(미저장)" in row["시장모의_최종체크입력"]
    assert row["시장만모의해제"] == "미확인"
    envelope["price_input_id"] = None
    assert replay_retained_final_checks(envelope, {"가격입력ID": None})[0] == []


def test_macro_block_is_not_reported_as_an_independent_block():
    frame, envelope = retained(dd=-.1, structure_risk=np.bool_(False))
    frame.attrs[INPUTS_KEY] = {"EXAMPLE": envelope}
    row = observe(frame).iloc[0]
    assert row["시장만모의해제"] == "미확인"
    assert "매크로" not in row["시장모의_독립체크"]
    assert "구조/추세: 통과" in row["시장모의_독립체크"]
    assert row["시장만모의해제_실행가능"] == "미확인"


def test_numpy_flags_are_reachable_from_actual_engine_comparison():
    from stock_lab_core.decision_signals import _build_structure_and_accumulation_flags
    result = _build_structure_and_accumulation_flags(
        is_etf=False, has_pos=False, cur_p=100., targ_w=10., weight_gap=10.,
        trend="상승", rs_label="강함", fin_score=3, adj_tech_score=4., mfi_now=50.,
        rsi_now=50., pct_b_now=.5, macro_risk_value=5., current_dd=np.float64(-.3),
        short_history=False, is_single_day_breakdown=False, ma20_now=110.,
        below_ma20=True, below_ma50=True, day_ret=-.01, is_leveraged_or_inverse=False)
    flag = result["is_structure_damage_entry_risk"]
    assert isinstance(flag, np.bool_) and not isinstance(flag, bool)
    frame, envelope = retained(structure_risk=flag)
    checks, _, _ = replay_retained_final_checks(envelope, frame.iloc[0].to_dict())
    assert any(row["점검항목"] == "구조/추세" and row["상태"] == "차단" for row in checks)


def test_legacy_cache_keeps_observations_and_marks_new_audit_missing_without_fetch(monkeypatch):
    import stock_lab_core.today_result_observation as module
    frame, envelope = retained(structure_risk=np.bool_(True))
    frame.attrs[INPUTS_KEY] = {"EXAMPLE": envelope}
    shown = frame.copy()
    shown["시장실행상태"] = "시장방어: 신규매수 중단"
    state = {}
    first = reuse_or_build_market_observation(shown, frame, metadata(frame), state,
                                            signature="sig", context="scope-a")
    new_columns = ["시장모의_최종체크입력", "시장모의_독립체크"]
    state[CACHE_KEY]["columns"] = state[CACHE_KEY]["columns"].drop(columns=new_columns)
    monkeypatch.setattr(module, "attach_market_observation", lambda *a: pytest.fail("must reuse"))
    restored = reuse_or_build_market_observation(shown, frame, metadata(frame, fresh=False), state,
                                               signature="sig", context="scope-a")
    old_columns = [key for key in OBS_COLUMNS if key not in new_columns + ["시장만모의해제_증거출처"]]
    pd.testing.assert_frame_equal(first[old_columns], restored[old_columns])
    assert all("상세 감사 미보존" in restored.iloc[0][key] for key in new_columns)
