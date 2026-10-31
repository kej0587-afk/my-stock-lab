"""Synthetic SEC period identity, cumulative-flow and provenance contracts."""

from copy import deepcopy
import random
import socket

import pytest

from stock_lab_core import sec_financial_periods as sec


TAGS = {"revenue": ["Revenue", "RevenueAlt"], "ocf": ["CashFlow", "CashFlowAlt"], "assets": ["Assets"]}
FLOW = {"revenue", "ocf"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("SEC statement records must be built offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


def fact(start, end, value, **extra):
    row = {"end": end, "val": value, "fy": 2025, "fp": "FY",
           "form": "10-K" if end == "2025-12-31" else "10-Q",
           "filed": "2026-02-15", "accn": "synthetic", **extra}
    if start is not None:
        row["start"] = start
    return row


def payload():
    ends = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
    return {"facts": {"us-gaap": {
        "Revenue": {"units": {"USD": [fact("2025-01-01", e, v) for e, v in zip(ends, [100, 220, 360, 520])]}},
        "CashFlow": {"units": {"USD": [fact("2025-01-01", e, v) for e, v in zip(ends, [10, 25, 45, 70])]}},
        "Assets": {"units": {"USD": [fact(None, e, v) for e, v in zip(ends, [1000, 1050, 1100, 1200])]}},
    }}}


def rows(data, tag, unit="USD"):
    return data["facts"]["us-gaap"][tag]["units"][unit]


def build(data):
    return sec.build_sec_statement_records(data, TAGS, FLOW)


def test_cumulative_cf_q4_and_balance_instants_preserve_actual_dates_and_provenance():
    data = payload()
    before = deepcopy(data)
    annual, quarters = build(data)
    assert len(annual) == 1 and len(quarters) == 4
    assert annual[0]["revenue"] == 520 and annual[0]["ocf"] == 70
    assert [r["revenue"] for r in quarters] == [100, 120, 140, 160]
    assert [r["ocf"] for r in quarters] == [10, 15, 20, 25]
    assert [r["assets"] for r in quarters] == [1000, 1050, 1100, 1200]
    q4 = quarters[-1]
    assert q4["date"] == "2025-12-31" and q4["start"] == "2025-10-01"
    assert q4["fiscal_quarter"] == 4 and q4["is_cumulative_ytd"] is False
    provenance = q4["provenance"]["ocf"]
    assert provenance["method"] == "cumulative_difference"
    assert [f["value"] for f in provenance["facts"]] == [70, 45]
    assert {f["start"] for f in provenance["facts"]} == {"2025-01-01"}
    assert {f["unit"] for f in provenance["facts"]} == {"USD"}
    assert q4["provenance"]["assets"]["method"] == "reported"
    assert "op_margin" not in q4 and data == before


def test_current_and_comparative_facts_with_identical_filing_labels_keep_actual_periods():
    data = payload()
    rows(data, "Revenue").extend([
        fact("2024-01-01", "2024-12-31", 400, form="10-K", filed="2026-03-01"),
        fact("2025-10-01", "2025-12-31", 160, form="10-K", filed="2026-03-01"),
    ])
    rows(data, "CashFlow").append(fact("2024-01-01", "2024-12-31", 999, form="10-K", filed="2026-03-01"))
    annual, quarters = build(data)
    assert [(r["date"], r["revenue"]) for r in annual] == [("2024-12-31", 400), ("2025-12-31", 520)]
    assert annual[-1]["ocf"] == 70 and quarters[-1]["revenue"] == 160


def test_direct_single_quarter_flow_wins_over_cumulative_derivation():
    data = payload()
    rows(data, "CashFlow").append(fact("2025-04-01", "2025-06-30", 16))
    q2 = build(data)[1][1]
    assert q2["ocf"] == 16
    assert q2["provenance"]["ocf"]["method"] == "reported"


def test_missing_cumulative_component_is_not_zero_or_a_previous_period():
    data = payload()
    rows(data, "CashFlow").pop(1)
    quarters = build(data)[1]
    assert [r["ocf"] for r in quarters] == [10, None, None, 25]
    assert quarters[1]["provenance"]["ocf"]["status"] == "missing_or_ambiguous"


def test_q4_cannot_subtract_a_standalone_q3_instead_of_nine_months():
    data = payload()
    rows(data, "CashFlow")[2] = fact("2025-07-01", "2025-09-30", 20)
    quarters = build(data)[1]
    assert quarters[2]["ocf"] == 20 and quarters[3]["ocf"] is None


def test_missing_nine_months_revenue_anchor_does_not_turn_annual_into_q4():
    data = payload()
    rows(data, "Revenue").pop(2)
    annual, quarters = build(data)
    assert annual[0]["revenue"] == 520
    assert [r["fiscal_quarter"] for r in quarters] == [1, 2]


@pytest.mark.parametrize("mismatch", ["unit", "tag", "start"])
def test_cumulative_subtraction_requires_same_unit_tag_and_start(mismatch):
    data = payload()
    previous = rows(data, "CashFlow").pop(2)
    if mismatch == "unit":
        data["facts"]["us-gaap"]["CashFlow"]["units"]["EUR"] = [previous]
    elif mismatch == "tag":
        data["facts"]["us-gaap"]["CashFlowAlt"] = {"units": {"USD": [previous]}}
    else:
        previous["start"] = "2025-01-02"
        rows(data, "CashFlow").append(previous)
    assert build(data)[1][-1]["ocf"] is None


def test_missing_balance_at_current_end_does_not_reuse_or_subtract_prior_balance():
    data = payload()
    rows(data, "Assets").pop()
    assert build(data)[1][-1]["assets"] is None


def test_non_december_year_uses_actual_fiscal_origin_and_quarter_ordinal():
    data = payload()
    ends = ["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30"]
    for tag in ("Revenue", "CashFlow", "Assets"):
        for index, row in enumerate(rows(data, tag)):
            row.update(end=ends[index], fy=2099, fp="Q2", form="10-K" if index == 3 else "10-Q")
            if "start" in row:
                row["start"] = "2024-10-01"
    annual, quarters = build(data)
    assert annual[0]["date"] == "2025-09-30" and annual[0]["fiscal_year"] == "2025"
    assert [r["fiscal_quarter"] for r in quarters] == [1, 2, 3, 4]
    assert [r["ocf"] for r in quarters] == [10, 15, 20, 25]
    assert all(r["fiscal_year_start"] == "2024-10-01" for r in quarters)


def test_next_year_q1_can_use_observed_prior_annual_end_without_inventing_fy_label():
    data = payload()
    rows(data, "Revenue").append(fact("2026-01-01", "2026-03-31", 150, fy=2026, fp="Q1"))
    rows(data, "CashFlow").append(fact("2026-01-01", "2026-03-31", 12, fy=2026, fp="Q1"))
    q1 = build(data)[1][-1]
    assert q1["date"] == "2026-03-31" and q1["fiscal_quarter"] == 1
    assert q1["fiscal_year"] is None and q1["fiscal_year_start"] == "2026-01-01"
    assert q1["ocf"] == 12


def test_orphan_three_month_fact_is_not_assumed_to_be_q1_from_filing_labels():
    data = payload()
    rows(data, "Revenue")[:] = [fact("2025-07-01", "2025-09-30", 140, fp="Q1")]
    assert build(data) == ([], [])


def test_unsorted_facts_and_field_order_do_not_change_results():
    data = payload()
    expected = build(data)
    for tag in ("Revenue", "CashFlow", "Assets"):
        random.Random(7).shuffle(rows(data, tag))
    assert sec.build_sec_statement_records(data, dict(reversed(list(TAGS.items()))), FLOW) == expected


def test_amendment_changes_only_the_matching_actual_start_end():
    data = payload()
    rows(data, "CashFlow").append(fact("2025-01-01", "2025-12-31", 75, form="10-K/A", filed="2026-03-01"))
    annual, quarters = build(data)
    assert annual[0]["ocf"] == 75 and quarters[-1]["ocf"] == 30
    assert quarters[-1]["provenance"]["ocf"]["facts"][0]["filed"] == "2026-03-01"


@pytest.mark.parametrize("conflict", ["same_filed", "unknown_filed"])
def test_ambiguous_current_values_are_missing_instead_of_falling_back(conflict):
    data = payload()
    extra = fact("2025-01-01", "2025-12-31", 75, form="10-K")
    if conflict == "unknown_filed":
        extra.pop("filed")
    rows(data, "CashFlow").append(extra)
    data["facts"]["us-gaap"]["CashFlowAlt"] = {"units": {"USD": [
        fact("2025-01-01", "2025-12-31", 99, form="10-K", filed="2026-04-01")]}}
    annual, quarters = build(data)
    assert annual[0]["ocf"] is None and quarters[-1]["ocf"] is None


def test_ambiguous_revenue_currency_is_held_back():
    data = payload()
    data["facts"]["us-gaap"]["Revenue"]["units"]["EUR"] = deepcopy(rows(data, "Revenue"))
    assert build(data) == ([], [])


@pytest.mark.parametrize("bad", [None, {}, {"facts": None}, {"facts": {"us-gaap": []}}])
def test_missing_or_malformed_payloads_are_empty(bad):
    assert build(bad) == ([], [])


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf")])
def test_invalid_flow_values_are_missing_not_zero(value):
    data = payload()
    rows(data, "CashFlow")[-1]["val"] = value
    assert build(data)[0][0]["ocf"] is None


def test_oversized_field_is_withheld_without_order_based_truncation(monkeypatch):
    monkeypatch.setattr(sec, "MAX_FACTS_PER_FIELD", 3)
    assert build(payload()) == ([], [])


def test_zero_and_negative_flows_remain_valid_values():
    data = payload()
    for row, value in zip(rows(data, "CashFlow"), [0, -10, -5, -20]):
        row["val"] = value
    assert [r["ocf"] for r in build(data)[1]] == [0, -10, 5, -15]


@pytest.mark.parametrize("field,value", [
    ("start", "2025-02-30"), ("start", "20250101"),
    ("end", "2025-12-32"), ("end", None), ("form", []),
])
def test_invalid_dates_and_form_are_withheld_without_unrelated_fallback(field, value):
    data = payload()
    rows(data, "CashFlow")[-1][field] = value
    annual, quarters = build(data)
    assert annual[0]["ocf"] is None and quarters[-1]["ocf"] is None


def test_direct_q4_survives_missing_q3_anchor_without_deriving_other_flows():
    data = payload()
    rows(data, "Revenue").pop(2)
    rows(data, "Revenue").append(fact("2025-10-01", "2025-12-31", 160, form="10-K"))
    q4 = build(data)[1][-1]
    assert q4["fiscal_quarter"] == 4 and q4["revenue"] == 160
    assert q4["ocf"] is None and q4["assets"] == 1200


def test_conflicting_observed_revenue_boundaries_are_not_guessed():
    data = payload()
    rows(data, "Revenue").append(fact("2025-01-01", "2025-06-29", 220))
    quarters = build(data)[1]
    assert [r["fiscal_quarter"] for r in quarters] == [1, 4]


def test_lower_priority_sibling_does_not_erase_preferred_concept_or_override_its_latest_filing():
    data = payload()
    rows(data, "CashFlow").append(fact("2025-01-01", "2025-12-31", 75,
                                       form="10-K/A", filed="2026-03-01"))
    data["facts"]["us-gaap"]["CashFlowAlt"] = {"units": {"USD": [
        fact("2025-01-01", "2025-12-31", 999, form="10-K/A", filed="2026-04-01")]}}
    annual, quarters = build(data)
    assert annual[0]["ocf"] == 75 and quarters[-1]["ocf"] == 30
    assert annual[0]["provenance"]["ocf"]["facts"][0]["tag"] == "CashFlow"
    assert annual[0]["provenance"]["ocf"]["facts"][0]["filed"] == "2026-03-01"


@pytest.mark.parametrize("sibling_value", [12, 10])
def test_coexisting_net_income_concepts_keep_the_explicit_preferred_value(sibling_value):
    data = payload()
    namespace = data["facts"]["us-gaap"]
    namespace["NetIncomeLoss"] = {"units": {"USD": [fact("2025-01-01", "2025-12-31", 12)]}}
    namespace["ProfitLoss"] = {"units": {"USD": [fact("2025-01-01", "2025-12-31", sibling_value)]}}
    tags = dict(TAGS, net_income=["NetIncomeLoss", "ProfitLoss"])
    annual, _ = sec.build_sec_statement_records(data, tags, FLOW | {"net_income"})
    assert annual[0]["net_income"] == 12
    assert annual[0]["provenance"]["net_income"]["facts"][0]["tag"] == "NetIncomeLoss"


def test_multiple_revenue_concepts_preserve_anchors_and_priority_is_explicit():
    data = payload()
    alternate = deepcopy(rows(data, "Revenue"))
    for row in alternate:
        row["val"] *= 2
    data["facts"]["us-gaap"]["RevenueAlt"] = {"units": {"USD": alternate}}
    annual, quarters = build(data)
    assert annual[0]["revenue"] == 520 and len(quarters) == 4
    assert [r["revenue"] for r in quarters] == [100, 120, 140, 160]
    tags = dict(TAGS, revenue=["RevenueAlt", "Revenue"])
    annual, quarters = sec.build_sec_statement_records(data, tags, FLOW)
    assert annual[0]["revenue"] == 1040 and quarters[-1]["revenue"] == 320


def test_cumulative_previous_uses_the_current_chosen_concept_even_if_previously_lower_priority():
    data = payload()
    rows(data, "CashFlow").pop()
    data["facts"]["us-gaap"]["CashFlowAlt"] = {"units": {"USD": [
        fact("2025-01-01", "2025-09-30", 40),
        fact("2025-01-01", "2025-12-31", 75, form="10-K")]}}
    annual, quarters = build(data)
    assert annual[0]["ocf"] == 75 and quarters[-1]["ocf"] == 35
    sources = quarters[-1]["provenance"]["ocf"]["facts"]
    assert {f["tag"] for f in sources} == {"CashFlowAlt"}


def test_secondary_current_concept_conflict_does_not_erase_same_concept_difference():
    data = payload()
    data["facts"]["us-gaap"]["CashFlowAlt"] = {"units": {"USD": [
        fact("2025-01-01", "2025-06-30", 999),
        fact("2025-01-01", "2025-06-30", 998)]}}
    assert build(data)[1][1]["ocf"] == 15


def test_tag_priority_is_independent_of_namespace_and_fact_order():
    data = payload()
    data["facts"]["us-gaap"]["CashFlowAlt"] = {"units": {"USD": [
        fact("2025-01-01", "2025-12-31", 999, form="10-K")]}}
    expected = build(data)
    namespace = data["facts"]["us-gaap"]
    data["facts"]["us-gaap"] = dict(reversed(list(namespace.items())))
    for tag in ("Revenue", "CashFlow", "Assets"):
        random.Random(19).shuffle(rows(data, tag))
    assert build(data) == expected
