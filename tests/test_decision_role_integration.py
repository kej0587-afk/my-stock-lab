"""Role views and the audit add no points, market calls or saved-score changes."""

from copy import deepcopy
import pytest

from stock_lab_core.decision_governance import quality_label, role_rows
from stock_lab_core.execution_gate import build_execution_gate


@pytest.mark.parametrize("code,cause", [
    ("HARD_BLOCK_FINANCIAL_F", "quality"), ("HARD_BLOCK_MACRO_STORM", "macro"),
    ("MACRO_STORM_HOLDING_CAUTION", "macro"), ("PRICE_DRAWDOWN_NO_ENTRY", "structure"),
    ("STRUCTURE_DAMAGE_HOLDING_CHECK", "structure"), ("SINGLE_DAY_BREAKDOWN_NO_ENTRY", "structure"),
    ("DOWNTREND_NO_ENTRY", "structure"), ("REVERSE_TREND_NO_ENTRY", "structure"),
])
def test_real_decision_codes_have_structured_evidence_ids(code, cause):
    gate = build_execution_gate({"판정코드": code, "판정분류": "buyish", "R/R": 2.0})
    assert gate["게이트상태"] == "방어우선"
    assert gate["게이트근거ID"] == cause


def test_quality_is_independent_of_technical_rank_or_account_gate():
    meta = {"auto_score": 4, "manual_score": None, "source": "fixture",
            "metrics": {"quarter_latest": {"date": "2026-09-30"}}}
    original = deepcopy(meta)
    before = role_rows({"grade": "S", "t_score": 10, "dec": "기존 타점"},
                      {"게이트상태": "실행가능"}, 4, meta)
    after = role_rows({"grade": "B", "t_score": 2, "dec": "다른 타점"},
                     {"게이트상태": "방어우선", "게이트근거": "시장방어"}, 4, meta)
    assert before[0] == after[0]
    assert before[2] != after[2]
    assert meta == original


def test_etf_role_does_not_invent_a_corporate_score():
    rows = role_rows({"is_leveraged_or_inverse": True}, {}, 0, {}, is_etf=True)
    assert rows[0]["구분"] == "상품 구조"
    assert "레버리지" in rows[0]["평가"]
    assert "0/4" not in str(rows)


def test_manual_quality_is_explicit():
    assert "수동 지정" in role_rows({}, {}, 2, {"manual_score": 2})[0]["평가"]


def test_temporary_default_is_not_presented_as_verified_quality():
    assert quality_label(3, {}) == "3/4 · 임시/미계산"
    assert quality_label(4, {"auto_score": 4}) == "4/4"
    assert "임시" not in quality_label(2, {"manual_score": 2})


def test_financial_audit_keeps_existing_grade_and_does_not_mutate(app_module):
    app = app_module
    keys = app.FIN_S_KEYS + app.FIN_A_KEYS + app.FIN_B_KEYS
    annual = {key: "✅ 원래 판정" for key in keys if key.startswith("annual")}
    quarter = {key: "✅ 원래 판정" for key in keys if key.startswith("quarter")}
    meta = {"auto_score": 4, "final_score": 4, "notes": {"annual_judgements": annual, "quarter_judgements": quarter}}
    original = deepcopy(meta)
    old_score = app.calc_middle_fin_total({**annual, **quarter})
    review = app.build_financial_evidence_review(meta)
    assert review["status"] == "comparison_only" and review["calibrated"] is False
    assert review["max_legacy_capacity"] == 62
    assert review["max_dedup_capacity"] == 53
    assert review["raw_net"] == old_score[1]["weighted_net_score"]
    assert app.calc_middle_fin_total({**annual, **quarter}) == old_score
    assert meta == original


def test_financial_audit_tolerates_partial_saved_notes(app_module):
    assert app_module.build_financial_evidence_review({"notes": {"annual_judgements": None}})["status"] == "no_evidence"
