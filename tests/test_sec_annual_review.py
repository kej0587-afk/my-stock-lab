"""Official NBIS evidence plus boundary contracts; never live network or scoring."""

from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from stock_lab_core import sec_annual_review as review
from stock_lab_core.sec_financial_periods import build_sec_statement_records


TAGS = {"revenue": ["Revenue", "RevenueAlt"], "ocf": ["OCF"], "assets": ["Assets"]}
FLOW = {"revenue", "ocf"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Annual evidence parser must run offline")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def official():
    path = Path(__file__).parent / "fixtures" / "nbis_20f_annual_20261107.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fact(value, *, start="2025-01-01", **extra):
    row = {"end": "2025-12-31", "filed": "2026-04-30", "form": "20-F",
           "accn": "0001104659-26-052948", "val": value, **extra}
    if start is not None:
        row["start"] = start
    return row


def payload():
    return {"cik": 1513845, "facts": {"us-gaap": {
        "Revenue": {"units": {"USD": [fact(100)]}},
        "OCF": {"units": {"USD": [fact(-20)]}},
        "Assets": {"units": {"USD": [fact(1000, start=None)]}},
    }}}


def rows(data, name):
    return data["facts"]["us-gaap"][name]["units"]["USD"]


def build(data, tags=TAGS, flow=FLOW, **kwargs):
    basis = {"expected_cik": "0001513845", "currency": "USD", "as_of": "2026-11-07"}
    return review.build_sec_20f_annual_review(data, tags, flow, **{**basis, **kwargs})


def test_official_three_years_values_scope_provenance_and_no_score(official):
    result = build(official["company_facts"], official["tags"], official["flow_fields"])
    assert result["review_only"] and not result["eligible_for_scoring"]
    assert not result["latest_release_verified"] and result["quarter"] == []
    annual = result["annual"]
    assert [r["date"] for r in annual] == ["2023-12-31", "2024-12-31", "2025-12-31"]
    assert [r["revenue"] for r in annual] == [9800000, 91500000, 529800000]
    assert [r["ocf"] for r in annual] == [829800000, 245600000, 384800000]
    assert [r["ocf_continuing"] for r in annual] == [-222000000, -269900000, 401900000]
    assert "mixed_filing_accessions" in annual[0]["comparability_flags"]
    for row in annual:
        assert row["missing_fields"] == []
        assert row["unit"] == "USD" and row["report_code"] == "20-F"
        assert "continuing_and_discontinued_scope" in row["comparability_flags"]
        assert row["ocf_continuing"] + row["ocf_discontinued"] == row["ocf"]
        assert row["provenance"]["revenue"]["facts"][0]["accession"] == "0001104659-26-052948"
    assert annual[-1]["net_income"] == 82500000
    assert annual[-1]["assets"] == 12430600000
    assert annual[-1]["liabilities"] + annual[-1]["equity"] == annual[-1]["assets"]


def test_existing_scoring_parser_stays_unsupported_and_input_is_unchanged(official):
    data, tags, flow = official["company_facts"], official["tags"], official["flow_fields"]
    before = deepcopy(data)
    assert build_sec_statement_records(data, tags, flow) == ([], [])
    baseline = build(data, tags, flow)
    assert data == before
    for concept in data["facts"]["us-gaap"].values():
        for values in concept["units"].values():
            values.reverse()
    assert build(data, tags, flow) == baseline
    assert build_sec_statement_records(data, tags, flow) == ([], [])


def test_exhibit_only_amendment_does_not_erase_financials():
    data = payload()
    before = build(data)
    data["facts"]["us-gaap"]["UnrelatedConcept"] = {"units": {"USD": [
        fact(1, form="20-F/A", filed="2026-05-22", accn="0001104659-26-065681")]}}
    assert build(data) == before


def test_real_fact_amendment_is_selected_per_field_with_source_and_cutoff():
    data = payload()
    rows(data, "OCF").append(fact(0, form="20-F/A", filed="2026-05-22", accn="0001104659-26-065681"))
    row = build(data)["annual"][0]
    assert row["ocf"] == 0 and "mixed_filing_accessions" in row["comparability_flags"]
    assert row["provenance"]["ocf"]["facts"][0]["form"] == "20-F/A"
    assert build(data, as_of="2026-05-21")["annual"][0]["ocf"] == -20


def test_currency_is_explicit_and_missing_is_not_zero():
    data = payload()
    data["facts"]["us-gaap"]["OCF"]["units"] = {"RUB": [fact(12345)]}
    row = build(data)["annual"][0]
    assert row["ocf"] is None and row["missing_fields"] == ["ocf"]
    assert build(data, currency="RUB")["annual"] == []


def test_conflict_is_missing_and_never_falls_through_to_alternative_concept():
    data = payload()
    rows(data, "OCF").append(fact(-21))
    assert build(data)["annual"][0]["ocf"] is None
    rows(data, "Revenue").append(fact(101))
    data["facts"]["us-gaap"]["RevenueAlt"] = {"units": {"USD": [fact(200)]}}
    result = build(data)
    assert result["annual"] == []
    assert result["issues"][0]["reason"] == "ambiguous_revenue"


@pytest.mark.parametrize("change", [
    {"form": "6-K"}, {"form": "10-K"}, {"form": []}, {"form": None},
    {"filed": "2027-01-01"}, {"filed": "2025-11-30"}, {"filed": "invalid"},
    {"start": "2025-07-01"}, {"start": "2025-1-1"}, {"accn": "invalid"},
    {"val": True}, {"val": float("nan")}, {"val": float("inf")},
])
def test_invalid_or_unsupported_anchor_is_not_annual(change):
    data = payload()
    rows(data, "Revenue")[0].update(change)
    assert build(data)["annual"] == []


def test_instant_balance_cannot_use_flow_period():
    data = payload()
    rows(data, "Assets")[0]["start"] = "2025-01-01"
    assert build(data)["annual"][0]["assets"] is None


def test_ambiguous_year_start_is_not_guessed():
    data = payload()
    rows(data, "Revenue").append(fact(90, start="2025-01-02"))
    result = build(data)
    assert result["annual"] == []
    assert result["issues"][0]["reason"] == "ambiguous_annual_start"


@pytest.mark.parametrize("start", ["2024-12-26", "2025-01-02"])
def test_52_and_53_week_years_keep_actual_periods(start):
    data = payload()
    rows(data, "Revenue")[0]["start"] = start
    row = build(data)["annual"][0]
    assert row["start"] == start and row["ocf"] is None


def test_oversized_field_withheld_not_sliced(monkeypatch):
    monkeypatch.setattr(review, "MAX_FACTS_PER_FIELD", 1)
    data = payload()
    rows(data, "OCF").append(fact(0))
    result = build(data)
    assert result["annual"][0]["ocf"] is None
    assert {"field": "ocf", "reason": "field_limit"} in result["issues"]


def test_ifrs_is_not_silently_mapped_to_us_gaap():
    data = payload()
    data["facts"]["ifrs-full"] = data["facts"].pop("us-gaap")
    assert build(data)["issues"] == [{"reason": "us_gaap_unavailable"}]


@pytest.mark.parametrize("kwargs,reason", [
    ({"expected_cik": "0000000001"}, "cik_mismatch"),
    ({"currency": "usd"}, "invalid_review_basis"),
    ({"as_of": "2026-1-1"}, "invalid_review_basis"),
    ({"tags": {"revenue": []}}, "invalid_tags"),
    ({"flow": ["revenue", {}]}, "invalid_flow_fields"),
    ({"tags": {**TAGS, "provenance": ["Assets"]}}, "reserved_metric_name"),
])
def test_invalid_configuration_fails_explicitly(kwargs, reason):
    with pytest.raises(ValueError, match=reason):
        build(payload(), **kwargs)
