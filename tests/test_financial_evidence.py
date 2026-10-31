"""Synthetic, offline contracts for the proposed financial evidence audit."""

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from stock_lab_core.financial_evidence import (
    EXACT_EQUIVALENT_FAMILIES,
    audit_financial_evidence,
)


PASS = "\u2705 evidence"
FAIL = "\u26a0\ufe0f evidence"
NEUTRAL = "\u2796 excluded"
DANGER = "\U0001f6a8 risk"


def app_definitions():
    """Read app contracts without executing UI, credentials or network clients."""
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    names = {"FIN_S_KEYS", "FIN_A_KEYS", "FIN_B_KEYS"}
    functions = {"getsymbol_score", "calc_weighted_fin_total"}
    nodes = [node for node in tree.body if (
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
    ) or isinstance(node, ast.FunctionDef) and node.name in functions]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app-financial-contract", "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def legacy():
    return app_definitions()


@pytest.fixture(scope="module")
def app_tiers(legacy):
    return {key: weight for name, weight in (
        ("FIN_S_KEYS", 3), ("FIN_A_KEYS", 2), ("FIN_B_KEYS", 1)
    ) for key in legacy[name]}


@pytest.mark.parametrize("outcome", [PASS, FAIL, DANGER, NEUTRAL])
def test_all_app_keys_match_raw_legacy_net(legacy, app_tiers, outcome):
    judgements = dict.fromkeys(app_tiers, outcome)
    audit = audit_financial_evidence(judgements, app_tiers)
    _, detail = legacy["calc_weighted_fin_total"](judgements, danger_limit=1)
    assert audit["raw_net"] == detail["weighted_net_score"]
    assert audit["danger_count"] == detail["danger_count"]
    assert audit["max_legacy_capacity"] == 62
    assert audit["max_dedup_capacity"] == 53
    assert len(audit["evidence_rows"]) == len(app_tiers) - 6
    if outcome == PASS:
        assert audit["unique_net"] == 53
        assert audit["normalized_legacy_equivalent_net"] == pytest.approx(62)


@pytest.mark.parametrize("family", EXACT_EQUIVALENT_FAMILIES)
@pytest.mark.parametrize("outcome", [PASS, FAIL])
def test_lower_weight_duplicate_invariance(family, outcome, app_tiers):
    tiers = {key: app_tiers[key] for key in family}
    strongest = max(tiers, key=tiers.get)
    single = audit_financial_evidence({strongest: outcome}, {strongest: tiers[strongest]})
    sparse = audit_financial_evidence({strongest: outcome}, tiers)
    repeated = audit_financial_evidence(dict.fromkeys(tiers, outcome), tiers)
    assert single["unique_net"] == sparse["unique_net"] == repeated["unique_net"]
    assert sparse["max_dedup_capacity"] == repeated["max_dedup_capacity"] == tiers[strongest]
    assert len(repeated["evidence_rows"]) == 1
    assert repeated["evidence_rows"][0]["aliases"] == sorted(family)
    assert repeated["evidence_rows"][0]["selected_key"] == strongest
    assert abs(repeated["raw_net"]) > abs(single["raw_net"])


@pytest.mark.parametrize("case", ["opposite", "neutral", "unknown", "missing"])
def test_conflict_unknown_and_missing_do_not_select_a_passing_alias(case):
    values = {"opposite": FAIL, "neutral": NEUTRAL, "unknown": "unrecognized", "missing": None}
    judgements = {"quarter_revenue_momentum": PASS, "quarter_revenue_increase": values[case]}
    audit = audit_financial_evidence(judgements, {
        "quarter_revenue_momentum": 3, "quarter_revenue_increase": 2})
    row = audit["evidence_rows"][0]
    expected = {"opposite": ("conflict", -3), "neutral": ("conflict", 0),
                "unknown": ("unknown", 0), "missing": ("positive", 3)}
    assert (row["status"], row["points"]) == expected[case]
    assert row["weight"] == 3
    if case != "missing":
        assert row["selected_key"] == "quarter_revenue_increase"


@pytest.mark.parametrize("other", [None, NEUTRAL, "unrecognized", PASS])
def test_lower_weight_failure_retains_family_harshness(other):
    audit = audit_financial_evidence({
        "quarter_cashflow_quality": other, "quarter_ocf_positive": "\u274c OCF 0",
        "quarter_cash_quality": FAIL,
    }, {"quarter_cashflow_quality": 3, "quarter_ocf_positive": 2, "quarter_cash_quality": 1})
    row = audit["evidence_rows"][0]
    assert audit["unique_net"] == -3
    assert row["selected_key"] == "quarter_ocf_positive"
    assert row["weight"] == 3
    assert row["status"] == ("negative" if other is None else "unknown" if other == "unrecognized" else "conflict")


def test_valid_zero_missing_unknown_and_danger_are_distinct():
    judgements = {"zero": 0, "neutral": NEUTRAL, "none": None, "blank": "  ",
                  "nan": float("nan"), "unknown": "no outcome", "boolean": True, "risk": DANGER}
    audit = audit_financial_evidence(judgements, dict.fromkeys([*judgements, "absent"], 1))
    statuses = {row["family"]: row["status"] for row in audit["evidence_rows"]}
    assert statuses == {"zero": "neutral", "neutral": "neutral", "none": "missing", "blank": "missing",
                        "nan": "missing", "unknown": "unknown", "boolean": "unknown",
                        "risk": "danger", "absent": "missing"}
    assert audit["raw_net"] == audit["unique_net"] == audit["normalized_legacy_equivalent_net"] == 0
    assert audit["max_legacy_capacity"] == audit["max_dedup_capacity"] == 9
    assert audit["danger_keys"] == ["risk"]


def test_zero_net_is_not_missing_evidence():
    audit = audit_financial_evidence({"pass": PASS, "fail": FAIL}, {"pass": 2, "fail": 2})
    assert audit["unique_net"] == 0
    assert {row["status"] for row in audit["evidence_rows"]} == {"positive", "negative"}


def test_ocf_sign_is_shared_even_when_display_mentions_growth():
    audit = audit_financial_evidence({
        "quarter_cashflow_quality": "\u2705 OCF 10",
        "quarter_ocf_positive": "\u2705 OCF 10",
        "quarter_cash_quality": "\u2705 growth -90%",
    }, {"quarter_cashflow_quality": 3, "quarter_ocf_positive": 2, "quarter_cash_quality": 1})
    assert audit["raw_net"] == 6
    assert audit["unique_net"] == 3


def test_finance_criteria_and_neutral_debt_ratio_are_independent():
    judgements = {
        "annual_debt_stability": PASS, "annual_debt_ratio_quality": NEUTRAL,
        "annual_profitability_good": PASS, "annual_margin_quality": FAIL,
        "quarter_debt_stability": PASS, "quarter_debt_ratio_quality": NEUTRAL,
        "quarter_equity_maintained": FAIL, "quarter_profit_quality": PASS,
        "quarter_margin_good": PASS, "quarter_margin_quality": PASS,
        "quarter_cashflow_quality": NEUTRAL, "quarter_ocf_positive": NEUTRAL,
        "quarter_cash_quality": NEUTRAL,
    }
    tiers = {key: 1 for key in judgements}
    tiers.update(annual_debt_stability=2, quarter_debt_stability=2,
                 quarter_cashflow_quality=3, quarter_ocf_positive=2)
    audit = audit_financial_evidence(judgements, tiers)
    rows = {row["family"]: row for row in audit["evidence_rows"]}
    for key in ("annual_debt_stability", "annual_debt_ratio_quality", "annual_profitability_good",
                "annual_margin_quality", "quarter_debt_stability", "quarter_debt_ratio_quality",
                "quarter_equity_maintained", "quarter_profit_quality"):
        assert rows[key]["aliases"] == [key]
    assert rows["quarter_debt_stability"]["points"] == 2
    assert rows["quarter_debt_ratio_quality"]["points"] == 0
    assert rows["quarter_cashflow_quality"]["points"] == 0
    assert rows["quarter_margin_good"]["aliases"] == ["quarter_margin_good", "quarter_margin_quality"]
    assert rows["quarter_margin_good"]["points"] == 1


def test_identical_titles_unlisted_keys_and_risk_flags_are_not_aliases():
    judgements = {key: DANGER for key in (
        "annual_hard_risk", "quarter_warning", "extra_risk")}
    judgements.update(annual_ocf_strength=PASS, annual_cash_buffer=PASS,
                      annual_debt_stability=PASS, annual_debt_ratio_quality=PASS,
                      quarter_revenue_quality=PASS, q_rev_momentum=PASS)
    tiers = dict.fromkeys((key for key in judgements if key != "extra_risk"), 1)
    audit = audit_financial_evidence(judgements, tiers)
    assert all(len(row["aliases"]) == 1 for row in audit["evidence_rows"])
    assert audit["danger_keys"] == ["annual_hard_risk", "extra_risk", "quarter_warning"]
    assert audit["danger_count"] == 3
    assert audit["unscored_keys"] == ["extra_risk"]
    assert audit["unique_net"] == audit["raw_net"] == 6


def test_danger_alias_is_not_replaced_by_positive_and_flag_count_is_original():
    judgements = {"quarter_revenue_momentum": PASS, "quarter_revenue_increase": DANGER,
                  "annual_hard_risk": DANGER, "quarter_warning": DANGER}
    audit = audit_financial_evidence(judgements, {
        "quarter_revenue_momentum": 3, "quarter_revenue_increase": 2})
    assert audit["unique_net"] == 0
    assert audit["evidence_rows"][0]["status"] == "conflict"
    assert audit["danger_count"] == 3


def test_contradictory_icons_preserve_raw_precedence_but_never_reward_conflict(legacy):
    value = f"{PASS} {FAIL}"
    audit = audit_financial_evidence({"criterion": value}, {"criterion": 2})
    assert audit["raw_net"] == legacy["getsymbol_score"](value) * 2 == 2
    assert audit["unique_net"] == -2
    assert audit["evidence_rows"][0]["status"] == "conflict"


def test_capacity_normalization_is_not_grade_calibration_or_schema_invariance():
    one = audit_financial_evidence({"quarter_revenue_momentum": PASS, "other": FAIL},
                                   {"quarter_revenue_momentum": 3, "other": 1})
    two = audit_financial_evidence({"quarter_revenue_momentum": PASS,
                                   "quarter_revenue_increase": PASS, "other": FAIL},
                                   {"quarter_revenue_momentum": 3, "quarter_revenue_increase": 2, "other": 1})
    assert one["unique_net"] == two["unique_net"] == 2
    assert one["normalized_legacy_equivalent_net"] == 2
    assert two["normalized_legacy_equivalent_net"] == 3
    assert two["calibrated"] is False
    assert "separate calibration" in two["calibration_note"]
    assert not {"grade", "total", "trade_grade", "thresholds"} & two.keys()


def test_missing_coverage_does_not_shrink_capacities_or_amplify_points(app_tiers):
    sparse = audit_financial_evidence({"annual_3y_revenue_uptrend": PASS}, app_tiers)
    complete = audit_financial_evidence(dict.fromkeys(app_tiers, PASS), app_tiers)
    assert sparse["max_legacy_capacity"] == complete["max_legacy_capacity"] == 62
    assert sparse["max_dedup_capacity"] == complete["max_dedup_capacity"] == 53
    assert sparse["unique_net"] == 3
    assert sparse["normalized_legacy_equivalent_net"] == pytest.approx(3 * 62 / 53)


def test_fractional_zero_weights_and_empty_schema():
    audit = audit_financial_evidence({"a": PASS, "b": FAIL}, {"a": 0.5, "b": 0})
    assert audit["raw_net"] == audit["unique_net"] == audit["max_dedup_capacity"] == 0.5
    for tiers in ({}, {"a": 0}):
        empty = audit_financial_evidence({"a": PASS}, tiers)
        assert empty["scale_factor"] is None
        assert empty["normalized_legacy_equivalent_net"] == 0


@pytest.mark.parametrize("weight, error", [(-1, ValueError), (float("nan"), ValueError),
    (float("inf"), ValueError), ("3", TypeError), (True, TypeError), (None, TypeError)])
def test_invalid_weights_are_rejected(weight, error):
    with pytest.raises(error):
        audit_financial_evidence({"a": PASS}, {"a": weight})


def test_order_and_input_immutability():
    judgements = {"quarter_revenue_momentum": PASS, "quarter_revenue_increase": FAIL,
                  "annual_hard_risk": DANGER, "outside": "unknown", "annual_margin_quality": NEUTRAL}
    tiers = {key: 2 for key in judgements if key != "outside"}
    before = deepcopy((judgements, tiers))
    forward = audit_financial_evidence(judgements, tiers)
    reversed_inputs = audit_financial_evidence(dict(reversed(list(judgements.items()))),
                                              dict(reversed(list(tiers.items()))))
    assert forward == reversed_inputs
    assert (judgements, tiers) == before


def test_equal_weight_selection_uses_stable_key_order():
    audit = audit_financial_evidence({"quarter_margin_good": PASS, "quarter_margin_quality": PASS},
                                     {"quarter_margin_quality": 1, "quarter_margin_good": 1})
    assert audit["evidence_rows"][0]["selected_key"] == "quarter_margin_good"
