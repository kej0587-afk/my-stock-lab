"""Offline regressions for precision's final execution checks."""

from copy import deepcopy
import ast
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK,
    GATE_DEFENSE,
    GATE_EXECUTABLE,
    GATE_WAIT,
    GATE_WATCH_ONLY,
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


def test_precision_rendering_does_not_reference_removed_local_context():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    assert not any(isinstance(node, ast.Name) and node.id == "precision_context" for node in ast.walk(tree))


def test_precision_workflow_display_tolerates_partial_cached_workflow(precision_app):
    frame = precision_app.build_execution_workflow_display_df({"게이트상태": GATE_WAIT})

    assert list(frame.columns) == ["후보품질", "후보점수", "후보검토사항", "게이트상태", "게이트근거"]
    assert frame.loc[0, "게이트상태"] == GATE_WAIT
    assert frame.loc[0, "게이트근거"] == "실행 게이트 재확인 필요"


def test_precision_rendering_uses_safe_workflow_display_helper():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig")

    assert 'pd.DataFrame([c["execution_workflow"]])[["후보품질"' not in source


@pytest.mark.parametrize("overrides,flow_verdict,expected", [
    ({}, "", GATE_EXECUTABLE),
    ({"decision_code": "A_UPTREND_SEARCH_ENTRY", "dec": "🔍A급 정배열: 타점 탐색 중"}, "", GATE_WAIT),
    ({"mtf_bias_label": "상위 시간대 경고"}, "", GATE_DEFENSE),
    ({}, "눌림대기", GATE_WAIT),
])
def test_shared_precision_context_preserves_sources_and_gate(precision_app, monkeypatch, overrides, flow_verdict, expected):
    app = precision_app
    decision = _decision(**overrides)
    original = deepcopy(decision)
    monkeypatch.setattr(app, "get_auto_benchmark_info", lambda *args: {
        "sector_bench": "XLK", "sector_rs_label": "🐢약함", "sector_rs_asof": "2026-10-05",
        "sector_rs_change_pct": -5.0, "sector_provenance": {"섹터분류출처": "https://example.org/sector"},
    })
    monkeypatch.setattr(app, "get_benchmark_display_name", lambda ticker: ticker)
    snapshot = {"saved": True}
    monkeypatch.setattr(app, "get_cached_today_market_flow_snapshot", lambda: snapshot)
    monkeypatch.setattr(app, "build_today_flow_shortlist_df", lambda value: pd.DataFrame())

    def attach_flow(frame, shortlist):
        result = frame.copy()
        result["돈흐름_판정"] = flow_verdict
        return result

    monkeypatch.setattr(app, "attach_today_flow_context", attach_flow)
    monkeypatch.setattr(app, "build_today_market_guard", lambda *args: {"mode": "정상"})
    calls = []

    def analyst(ticker):
        calls.append(ticker)
        return {
            "ok": True, "source": "consensus provider", "asof": "2026-10-02",
            "source_url": "https://example.org/consensus",
            "data": {"targetMeanPrice": 90.0, "currentPrice": 95.0, "numberOfAnalystOpinions": 10},
        }

    monkeypatch.setattr(app, "get_analyst_snapshot", analyst)
    monkeypatch.setattr(app, "load_latest_price", lambda ticker: pytest.fail("Displayed price should be used"))

    workflow = app.build_precision_execution_workflow("Microsoft", "MSFT", decision, False, "us_stock", False)

    assert decision == original
    assert workflow["게이트상태"] == expected
    assert workflow["애널목표Upside값"] == pytest.approx(-10.0)
    assert workflow["애널목표출처"] == "consensus provider"
    assert workflow["애널목표기준일"] == "2026-10-02"
    assert workflow["섹터RS기준일"] == "2026-10-05"
    assert workflow["섹터분류출처"] == "https://example.org/sector"
    assert "섹터RS 약함" in workflow["후보검토사항"]
    assert "애널목표Upside" in workflow["후보검토사항"]
    assert calls == ["MSFT"]


@pytest.mark.parametrize("code,label", [
    ("A_UPTREND_SEARCH_ENTRY", "🔍A급 정배열: 타점 탐색 중"),
    ("S_UPTREND_WAIT_PULLBACK", "🔍S급 정배열: 눌림 구간 진입 대기"),
])
def test_candidate_grade_cannot_pass_a_pending_entry(precision_app, code, label):
    decision = _decision(dec=label, decision_code=code, decision_group="watch")
    original = deepcopy(decision)

    rows, summary = _checks(precision_app, decision)

    assert _check(rows, "시스템 타점")["상태"] == "주의"
    assert summary["final_label"] == "대기"
    assert decision == original


@pytest.mark.parametrize("overrides", [
    {"rr_ratio": None, "rr_target": None, "rr_stop": None},
    {"rr_ratio": 0.6, "rr_target": 106.0},
    {"rr_ratio": 0.6, "rr_target": 106.0, "rr_target_is_projection": True},
    {"rr_ratio": 2.0, "rr_target": 120.0, "rr_target_is_projection": True},
], ids=["missing-rr", "low-rr", "low-projected-rr", "projected-target"])
def test_unconfirmed_rr_cannot_be_promoted_by_other_passes(precision_app, overrides):
    rows, summary = _checks(precision_app, _decision(**overrides))

    assert _check(rows, "시스템 타점")["상태"] != "통과"
    assert summary["final_label"] in {"대기", "매수 금지"}


@pytest.mark.parametrize("state", [GATE_WAIT, GATE_DEFENSE, GATE_DATA_CHECK, GATE_WATCH_ONLY])
def test_enriched_gate_is_respected_by_final_checks(precision_app, state):
    decision = _decision(execution_workflow={"게이트상태": state, "게이트근거": "조건 확인 대기"})

    rows, summary = _checks(precision_app, decision)

    assert _check(rows, "시스템 타점")["상태"] != "통과"
    assert summary["final_label"] == "대기"


def test_confirmed_entry_remains_actionable(precision_app):
    rows, summary = _checks(precision_app, _decision())

    assert _check(rows, "시스템 타점")["상태"] == "통과"
    assert summary["final_label"] == "분할 가능"


def test_low_target_only_is_upside_limited_not_valuation_burden(app_module):
    valuation = app_module.build_valuation_interpretation(
        {"targetMeanPrice": 100.9},
        100.0,
        "ALAB",
    )

    assert valuation["headline"] == "업사이드 제한"
    assert valuation["valuation_data_count"] == 1
    assert valuation["target_upside"] == pytest.approx(0.9)


def test_valuation_derives_psr_and_pe_from_market_cap(app_module):
    valuation = app_module.build_valuation_interpretation(
        {
            "marketCap": 1_000_000_000,
            "totalRevenue": 100_000_000,
            "netIncomeToCommon": 50_000_000,
            "targetMedianPrice": 130.0,
        },
        100.0,
        "TEST",
    )
    rows = {row["항목"]: row for row in valuation["rows"]}

    assert valuation["target_mean"] == pytest.approx(130.0)
    assert valuation["trailing_pe"] == pytest.approx(20.0)
    assert valuation["ps"] == pytest.approx(10.0)
    assert rows["PER"]["값"] == "20.0x"
    assert rows["PSR"]["값"] == "10.0x"


def test_valuation_reuses_fin_score_financial_records(app_module):
    fin_meta = {
        "metrics": {
            "annual_latest": {
                "revenue": 200_000_000,
                "op_income": 40_000_000,
                "net_income": 24_000_000,
                "op_margin": 20.0,
                "net_margin": 12.0,
                "roe": 18.0,
            },
            "derived": {"rev_growth": 35.0, "net_growth": 42.0},
        }
    }
    valuation = app_module.build_valuation_interpretation(
        {"targetMeanPrice": 100.5, "marketCap": 1_000_000_000},
        100.0,
        "ALAB",
        fin_meta=fin_meta,
    )
    rows = {row["항목"]: row for row in valuation["rows"]}

    assert rows["연매출"]["값"] == "2.0억"
    assert rows["영업이익"]["값"] == "40.0백만"
    assert rows["순이익"]["값"] == "24.0백만"
    assert rows["매출 성장"]["값"] == "35.0%"
    assert rows["순이익률"]["값"] == "12.0%"
    assert rows["PSR"]["값"] == "5.0x"
    assert valuation["headline"] != "밸류 데이터 부족"


def test_upside_limited_valuation_is_caution_not_hard_block(precision_app, monkeypatch):
    monkeypatch.setattr(
        precision_app,
        "get_valuation_headline_for_final_check",
        lambda *args, **kwargs: (
            "업사이드 제한",
            "목표가 기준 상승여력은 작지만 세부 밸류 데이터가 부족합니다.",
            0.9,
        ),
    )

    rows, summary = _checks(precision_app, _decision())

    assert _check(rows, "밸류/가격")["상태"] == "주의"
    assert summary["final_label"] != "매수 금지"


def test_held_mtf_damage_still_blocks_final_addition(precision_app):
    decision = _decision(current_w=1.0)
    decision = precision_app.apply_precision_mtf_decision_guard(
        decision, {"주봉": {"snapshot": {"state": "추세훼손"}}}, has_pos=True,
    )
    original = deepcopy(decision)
    workflow = build_decision_workflow("Test", "TEST", decision, has_pos=True)

    rows, summary = _checks(precision_app, decision, has_pos=True)

    assert workflow["게이트상태"] == GATE_DEFENSE
    assert _check(rows, "상위 시간대")["상태"] == "차단"
    assert _check(rows, "시스템 타점")["상태"] == "차단"
    assert summary["final_label"] in {"대기", "매수 금지"}
    assert decision == original


def test_recovery_watch_cannot_be_promoted_by_a_valid_pattern(precision_app):
    decision = _decision(
        dec="🔎우량주 회복관찰", decision_code="QUALITY_RECOVERY_WATCH", decision_group="neutral",
    )
    decision["execution_workflow"] = build_decision_workflow(
        "Test", "TEST", decision, pattern_timing="✅패턴유효: 정밀확인", pattern_bucket="interest",
    )

    rows, summary = _checks(precision_app, decision)

    assert decision["execution_workflow"]["게이트상태"] == GATE_WAIT
    assert _check(rows, "시스템 타점")["상태"] != "통과"
    assert summary["final_label"] in {"대기", "매수 금지"}


def test_leveraged_entry_cannot_override_a_waiting_gate(precision_app, monkeypatch):
    monkeypatch.setattr(precision_app, "build_leveraged_precision_state", lambda *args: {
        "dca_multiple": "×0", "dca_stage": "미보유 관찰", "recovery_passed": 6,
    })
    monkeypatch.setattr(precision_app, "build_leveraged_dca_timing_state", lambda *args: {
        "status": "타점 가능", "entry1_verdict": "가능",
    })
    decision = _decision(execution_workflow={"게이트상태": GATE_WAIT, "게이트근거": "조건 확인 대기"})

    _, summary = _checks(precision_app, decision, is_etf=True)

    assert summary["final_label"] == "대기"
