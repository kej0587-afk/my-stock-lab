"""Offline regressions for independent evidence and final execution vetoes."""

from copy import deepcopy
from math import isnan

import pytest

from stock_lab_core.decision_governance import independent_check_summary
from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK,
    GATE_DEFENSE,
    GATE_EXECUTABLE,
    GATE_WAIT,
    GATE_WATCH_ONLY,
    build_execution_gate,
)


@pytest.fixture
def precision_app(app_module, monkeypatch):
    monkeypatch.setattr(app_module.st, "session_state", {"_app_final_macro_risk": 0.0})
    monkeypatch.setattr(
        app_module, "get_valuation_headline_for_final_check",
        lambda *args, **kwargs: ("가격매력 우수", "", 20.0),
    )
    monkeypatch.setattr(app_module, "is_leveraged_or_inverse_product", lambda *args: False)
    monkeypatch.setattr(app_module, "build_leveraged_precision_state", lambda *args: {})
    monkeypatch.setattr(app_module, "build_sideways_quality_state", lambda *args, **kwargs: {})
    return app_module


def _decision(**overrides):
    return {
        "dec": "🚀신규진입: 대장주 포착",
        "decision_code": "NEW_ENTRY_LEADER",
        "decision_group": "buyish",
        "grade": "✅A급 (분할 매수)",
        "t_score": 8,
        "cur_p": 100.0,
        "rr_stop": 90.0,
        "rr_target": 116.0,
        "rr_ratio": 1.6,
        "atr": 5.0,
        "trend": "🚀정배열(상승)",
        "rs_label": "🚀강함",
        "mfi": 55.0,
        "rsi": 55.0,
        "pct_b": 0.5,
        "dd": -0.05,
        "day_ret": 0.01,
        "target_w": 5.0,
        "current_w": 0.0,
        **overrides,
    }


def _checks(app, decision, *, has_pos=False, is_etf=False):
    return app.build_pre_buy_final_checks(
        "Test", "TEST", is_etf, decision, 0 if is_etf else 4,
        has_pos, 100.0 if has_pos else 0.0,
    )


def _check(rows, name):
    return next(row for row in rows if row["점검항목"] == name)


@pytest.mark.parametrize("macro_status,blocks", [("통과", 1), ("차단", 2)])
def test_independent_summary_preserves_rows_and_counts_mtf_once(macro_status, blocks):
    rows = [
        {"점검항목": "시스템 타점", "상태": "차단", "해석": "aggregate"},
        {"점검항목": "상위 시간대", "상태": "차단", "해석": "specific"},
        {"점검항목": "매크로", "상태": macro_status, "해석": "macro"},
    ]
    workflow = {"게이트상태": GATE_DEFENSE, "게이트근거ID": "mtf"}
    original_rows, original_workflow = deepcopy(rows), deepcopy(workflow)

    annotated, meta = independent_check_summary(rows, workflow)

    assert [{key: row[key] for key in original} for row, original in zip(annotated, rows)] == rows
    assert len(annotated) == len(rows)
    assert meta["status_counts"]["차단"] == blocks
    assert meta["duplicate_count"] == 1
    assert [item["근거ID"] for item in meta["evidence"]].count("mtf") == 1
    assert _check(annotated, "시스템 타점")["집계"] == "중복 제외"
    assert _check(annotated, "상위 시간대")["집계"] == "독립근거"
    assert rows == original_rows
    assert workflow == original_workflow


def test_summary_uses_pipe_ids_despite_misleading_prose_without_mutating_inputs():
    rows = [
        {"점검항목": "시스템 타점", "상태": "차단", "해석": "R/R warning"},
        {"점검항목": "상위 시간대", "상태": "차단", "해석": "macro warning"},
        {"점검항목": "매크로", "상태": "차단", "해석": "MTF warning"},
    ]
    workflow = {
        "게이트상태": GATE_DEFENSE, "게이트근거ID": "mtf|macro|mtf",
        "게이트근거": "unrelated explanation",
    }
    original_rows, original_workflow = deepcopy(rows), deepcopy(workflow)
    annotated, meta = independent_check_summary(rows, workflow)
    changed_rows, changed_workflow = deepcopy(rows), deepcopy(workflow)
    for row in changed_rows:
        row["해석"] = "reworded; no evidence names"
    changed_workflow["게이트근거"] = "different explanation"

    reworded, reworded_meta = independent_check_summary(changed_rows, changed_workflow)

    assert reworded_meta == meta
    assert meta["status_counts"]["차단"] == 2
    assert {item["근거ID"] for item in meta["evidence"]} == {"mtf", "macro"}
    assert [(row["근거ID"], row["집계"]) for row in reworded] == [
        (row["근거ID"], row["집계"]) for row in annotated
    ]
    assert rows == original_rows
    assert workflow == original_workflow


def test_legacy_gate_without_ids_is_not_deduplicated_from_prose():
    rows = [
        {"점검항목": "시스템 타점", "상태": "차단", "해석": "상위 시간대 추세훼손"},
        {"점검항목": "상위 시간대", "상태": "차단", "해석": "상위 시간대 추세훼손"},
    ]

    _, meta = independent_check_summary(rows, {"게이트상태": GATE_DEFENSE})

    assert meta["status_counts"]["차단"] == 2
    assert meta["duplicate_count"] == 0
    assert {item["근거ID"] for item in meta["evidence"]} == {"gate.unresolved", "mtf"}


@pytest.mark.parametrize("macro_risk,blocks,label", [
    (0.0, 1, "대기"), (4.5, 2, "매수 금지"),
])
def test_final_check_deduplicates_mtf_but_keeps_independent_macro(
    precision_app, macro_risk, blocks, label,
):
    precision_app.st.session_state["_app_final_macro_risk"] = macro_risk
    decision = _decision(mtf_bias_label="상위 시간대 경고")
    workflow = build_decision_workflow("Test", "TEST", decision)
    decision["execution_workflow"] = workflow
    original = deepcopy(decision)

    rows, summary = _checks(precision_app, decision)

    assert workflow["게이트상태"] == GATE_DEFENSE
    assert workflow["게이트근거ID"] == "mtf"
    assert sum(row["상태"] == "차단" for row in rows) == blocks + 1
    assert _check(rows, "시스템 타점")["상태"] == "차단"
    assert _check(rows, "상위 시간대")["상태"] == "차단"
    assert summary["block_count"] == blocks
    assert summary["duplicate_count"] == 1
    assert summary["final_label"] == label
    assert summary["execution_allowed"] is False
    assert decision == original


def test_normal_entry_and_financial_quality_remain_single_votes(precision_app):
    decision = _decision()
    original = deepcopy(decision)

    rows, summary = _checks(precision_app, decision)

    assert [row["점검항목"] for row in rows] == [
        "시스템 타점", "재무/상품", "밸류/가격", "구조/추세", "과열",
        "손익비", "비중", "매크로", "보유상태",
    ]
    assert all(row["상태"] == "통과" for row in rows)
    assert _check(rows, "시스템 타점")["집계"] == "요약"
    assert _check(rows, "재무/상품")["근거ID"] == "quality"
    assert [item["근거ID"] for item in summary["evidence"]].count("quality") == 1
    assert summary["pass_count"] == len(rows) - 1
    assert summary["block_count"] == summary["caution_count"] == summary["unknown_count"] == 0
    assert summary["duplicate_count"] == 0
    assert summary["core_missing_ids"] == []
    assert summary["final_label"] == "분할 가능"
    assert summary["execution_allowed"] is True
    assert decision == original


@pytest.mark.parametrize("status", ["차단", "주의", "미확인"])
def test_executable_saved_gate_never_erases_local_adverse_status(status):
    rows = [{"점검항목": "시스템 타점", "상태": status}]
    annotated, summary = independent_check_summary(rows, {
        "게이트상태": GATE_EXECUTABLE, "게이트근거ID": "mtf",
    })
    assert annotated[0]["근거ID"] == "gate.local"
    assert annotated[0]["집계"] == "독립근거"
    assert summary["status_counts"][status] == 1
    assert summary["core_missing_ids"] == (["gate.local"] if status == "미확인" else [])


def test_executable_saved_gate_does_not_allow_current_hard_block(precision_app):
    decision = _decision(dec="하드차단", execution_workflow={
        "게이트상태": GATE_EXECUTABLE, "게이트근거ID": "",
    })
    rows, summary = _checks(precision_app, decision)
    assert _check(rows, "시스템 타점")["상태"] == "차단"
    assert summary["block_count"] == 1
    assert summary["execution_allowed"] is False
    assert summary["final_label"] == "대기"


@pytest.mark.parametrize("branch,allowed_label", [
    ("initial", "타점 가능"), ("ram-scout", "1차 소액만"), ("ram-dca", "조건부 DCA 소액"),
])
@pytest.mark.parametrize("restriction", ["macro", "weight", "missing-mfi"])
def test_forced_executable_leverage_cannot_bypass_local_veto(
    precision_app, monkeypatch, branch, allowed_label, restriction,
):
    monkeypatch.setattr(precision_app, "build_leveraged_precision_state", lambda *args: {
        "dca_multiple": "×0" if branch == "initial" else "×1",
        "dca_stage": "미보유 관찰" if branch == "initial" else "회복 후보",
        "profile_key": "RAM", "recovery_passed": 6,
    })
    monkeypatch.setattr(precision_app, "build_leveraged_dca_timing_state", lambda *args: {
        "status": "1차 소액" if branch == "ram-scout" else "타점 가능",
        "entry1_verdict": "가능",
    })
    monkeypatch.setattr(precision_app, "_leveraged_rr_entry_threshold", lambda *args: (
        99.0 if branch == "ram-scout" else 101.0
    ))
    decision = _decision(execution_workflow={
        "게이트상태": GATE_EXECUTABLE, "게이트근거": "R/R·패턴·방어 게이트 통과",
        "게이트근거ID": "",
    })
    _, baseline = _checks(precision_app, decision, is_etf=True)
    assert baseline["final_label"] == allowed_label
    assert baseline["execution_allowed"] is True

    if restriction == "macro":
        precision_app.st.session_state["_app_final_macro_risk"] = 4.5
    elif restriction == "weight":
        decision["current_w"] = decision["target_w"]
    else:
        decision["mfi"] = None
    original = deepcopy(decision)

    _, summary = _checks(precision_app, decision, is_etf=True)

    assert summary["block_count"] == (0 if restriction == "missing-mfi" else 1)
    if restriction == "missing-mfi":
        assert "overheat" in summary["core_missing_ids"]
    assert summary["final_label"] == "대기"
    assert summary["execution_allowed"] is False
    assert decision == original


@pytest.mark.parametrize("rsi,heat_status", [(55.0, "미확인"), (70.0, "주의"), (90.0, "차단")])
def test_missing_mfi_never_passes_or_erases_known_heat(precision_app, rsi, heat_status):
    decision = _decision(mfi=float("nan"), rsi=rsi, execution_workflow={
        "게이트상태": GATE_EXECUTABLE, "게이트근거ID": "",
    })

    rows, summary = _checks(precision_app, decision)

    assert _check(rows, "과열")["상태"] == heat_status
    assert "overheat" in summary["core_missing_ids"]
    assert summary["final_label"] == "대기"
    assert summary["execution_allowed"] is False
    assert isnan(decision["mfi"])


def test_all_missing_indicators_remain_unknown_and_reach_gate(precision_app):
    decision = _decision(rsi=None, mfi=float("nan"), pct_b=None)

    workflow = build_decision_workflow("Test", "TEST", decision)
    rows, summary = _checks(precision_app, decision)

    assert workflow["RSI"] is None
    assert isnan(workflow["MFI"])
    assert workflow["볼린저 %B"] is None
    assert workflow["게이트상태"] == GATE_DATA_CHECK
    assert workflow["게이트근거ID"] == "overheat"
    assert _check(rows, "과열")["상태"] == "미확인"
    assert "overheat" in summary["core_missing_ids"]
    assert summary["execution_allowed"] is False
    assert summary["final_label"] == "대기"


def test_missing_macro_is_unknown_and_vetoes_forced_executable(precision_app):
    precision_app.st.session_state["_app_final_macro_risk"] = None
    decision = _decision(execution_workflow={"게이트상태": GATE_EXECUTABLE})

    rows, summary = _checks(precision_app, decision)

    assert _check(rows, "매크로")["상태"] == "미확인"
    assert summary["core_missing_ids"] == ["macro"]
    assert summary["unknown_count"] == 1
    assert summary["execution_allowed"] is False
    assert summary["final_label"] == "대기"


@pytest.mark.parametrize("overrides,category,evidence_id", [
    ({"rr_ratio": None}, "손익비", "rr"),
    ({"cur_p": None}, "현재가", "price"),
])
def test_missing_execution_inputs_veto_forced_executable(
    precision_app, overrides, category, evidence_id,
):
    decision = _decision(**overrides, execution_workflow={"게이트상태": GATE_EXECUTABLE})

    rows, summary = _checks(precision_app, decision)

    assert _check(rows, category)["상태"] == "미확인"
    assert evidence_id in summary["core_missing_ids"]
    assert summary["execution_allowed"] is False
    assert summary["final_label"] == "대기"


@pytest.mark.parametrize("state", [GATE_WAIT, GATE_DEFENSE, GATE_DATA_CHECK, GATE_WATCH_ONLY])
def test_nonexecutable_authority_survives_positive_local_checks(precision_app, state):
    decision = _decision(execution_workflow={
        "게이트상태": state, "게이트근거ID": "entry", "게이트근거": "조건 확인 대기",
    })

    _, summary = _checks(precision_app, decision)

    assert summary["execution_allowed"] is False
    assert summary["final_label"] == "대기"


def test_structured_mtf_gate_ids_ignore_signal_prose_and_preserve_input():
    row = {
        "판정코드": "NEW_ENTRY_LEADER", "판정분류": "buyish", "RR값": 1.6,
        "상위시간대상태": "상위 시간대 경고", "최종읽기": "진입 후보",
    }
    original = deepcopy(row)
    before = build_execution_gate(row)
    changed = {**row, "최종읽기": "reworded signal", "핵심근거": "different explanation"}
    changed_original = deepcopy(changed)

    after = build_execution_gate(changed)

    assert before == after
    assert before["게이트상태"] == GATE_DEFENSE
    assert before["게이트근거ID"] == "mtf"
    assert before["게이트근거"] == "상위 시간대 추세훼손"
    assert row == original
    assert changed == changed_original
