from copy import deepcopy
import ast
from pathlib import Path
import socket
import subprocess

import pytest

from stock_lab_core.sec_quarter_review import TAGS, build_sec_quarter_review, quarter_tables, review_questions


def payload():
    data = {"cik": 123, "facts": {"us-gaap": {}}}
    for field, names in TAGS.items():
        facts = []
        for year in (2023, 2024, 2025):
            for q, end in enumerate(("03-31", "06-30", "09-30", "12-31"), 1):
                value = {"revenue": 100, "op_income": 20, "net_income": 15,
                         "ocf": 30, "cash_capex": 40, "cash": 200}[field]
                value *= 1 + (year - 2023) / 10
                row = {"end": f"{year}-{end}", "val": value * q if field != "cash" else value,
                       "form": "10-K" if q == 4 else "10-Q", "filed": "2026-02-15",
                       "accn": "0000000123-26-000001"}
                if field != "cash":
                    row["start"] = f"{year}-01-01"
                facts.append(row)
        data["facts"]["us-gaap"][names[0]] = {"units": {"USD": facts}}
    return data


def rows(data, field):
    return data["facts"]["us-gaap"][TAGS[field][0]]["units"]["USD"]


def build(data):
    return build_sec_quarter_review(data, expected_cik="0000000123", as_of="2026-11-08")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*a, **k):
        pytest.fail("pure review must not request network")
    monkeypatch.setattr(socket.socket, "connect", fail)


def test_eight_quarters_calculated_from_ytd_and_prior_year_retained_before_slicing():
    data = payload()
    before = deepcopy(data)
    result = build(data)
    assert data == before and result["eligible_for_scoring"] is False
    assert len(result["quarter"]) == 8 and not result["gaps"]
    assert result["quarter"][0]["start"] == "2024-01-01"
    assert result["quarter"][0]["yoy_pct"]["revenue"] == pytest.approx(10)
    for row in result["quarter"]:
        assert row["fcf_cash"] == pytest.approx(-11 if row["end"].startswith("2024") else -12)
        assert row["cash"] > 200 and row["op_margin_pct"] == pytest.approx(20)
    tables = quarter_tables(result)
    assert len(tables[0]) == len(tables[1]) == 8 and tables[2]
    assert "누적차감 계산" in tables[1][-1]["계산·공시 확인"]
    assert len(review_questions(result)) == 2


@pytest.mark.parametrize("mutation", ["missing", "other_currency", "negative", "revised_previous", "mixed_ocf_capex"])
def test_fcf_withheld_for_missing_or_incompatible_cash_capex(mutation):
    data = payload()
    capex = rows(data, "cash_capex")
    if mutation == "missing":
        capex.clear()
    elif mutation == "other_currency":
        data["facts"]["us-gaap"][TAGS["cash_capex"][0]]["units"] = {"EUR": capex}
    elif mutation == "negative":
        capex[-1]["val"] = -100
    elif mutation == "revised_previous":
        capex[-2]["filed"] = "2026-03-01"
    else:
        capex[-1]["accn"] = "0000000123-26-000002"
    assert build(data)["quarter"][-1]["fcf_cash"] is None


def test_cutoff_missing_dates_forms_and_identity_not_assumed():
    data = payload()
    original = deepcopy(data)
    for field in TAGS:
        rows(data, field).extend([dict(rows(data, field)[-1], val=9999, filed="2027-01-01"),
                                 dict(rows(data, field)[-1], val=9999, form="20-F"),
                                 dict(rows(data, field)[-1], val=9999, filed=None)])
    assert build(data) == build(original)
    data["cik"] = 456
    with pytest.raises(ValueError, match="cik_mismatch"):
        build(data)


def test_nonadjacent_quarters_visible_as_gap_not_zero_filled():
    data = payload()
    rows(data, "revenue")[:] = [r for r in rows(data, "revenue") if r["end"] != "2025-06-30"]
    result = build(data)
    assert result["gaps"] and all(r["end"] != "2025-06-30" for r in result["quarter"])


def test_changed_tag_and_negative_base_withhold_yoy():
    data = payload()
    rev = rows(data, "revenue")
    alternate = [r for r in rev if r["end"].startswith("2024")]
    rev[:] = [r for r in rev if not r["end"].startswith("2024")]
    data["facts"]["us-gaap"][TAGS["revenue"][1]] = {"units": {"USD": alternate}}
    assert build(data)["quarter"][-1]["yoy_pct"]["revenue"] is None
    data = payload()
    rows(data, "revenue")[4]["val"] = -100
    assert build(data)["quarter"][4]["yoy_pct"]["revenue"] is None


def test_cross_filing_subtraction_flagged_and_growth_not_interpreted():
    data = payload()
    for field in TAGS:
        rows(data, field)[-2]["accn"] = "0000000123-25-000099"
    latest = build(data)["quarter"][-1]
    assert latest["fcf_cash"] == -12
    assert "cross_filing_difference_review" in latest["comparability_flags"]
    assert latest["yoy_pct"]["ocf"] is None


def test_existing_app_functions_unchanged_and_no_score_provider_imports():
    old = subprocess.check_output(["git", "show", "68d617a4:app.py"]).decode("utf-8-sig")
    new = Path("app.py").read_text(encoding="utf-8-sig")
    def functions(text):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
    assert functions(old) == functions(new)
    for name in ("sec_quarter_review.py", "sec_quarter_review_view.py"):
        text = Path("stock_lab_core", name).read_text(encoding="utf-8")
        assert "supabase" not in text and "get_final_fin_score" not in text


def test_newer_cumulative_conflicts_with_old_direct_quarter_withheld():
    data = payload()
    rows(data, "ocf").append(dict(rows(data, "ocf")[-1], start="2025-10-01", val=999, filed="2026-01-30"))
    latest = build(data)["quarter"][-1]
    assert latest["ocf"] is None and latest["fcf_cash"] is None
    assert latest["provenance"]["ocf"]["status"] == "direct_cumulative_conflict"


def test_productive_assets_preserve_broader_cash_investment_scope():
    data = payload()
    namespace = data["facts"]["us-gaap"]
    namespace[TAGS["cash_capex"][1]] = namespace.pop(TAGS["cash_capex"][0])
    latest = build(data)["quarter"][-1]
    assert latest["fcf_cash"] == -12
    assert latest["cash_capex_scope"] == "유형·소프트웨어·무형자산"


def test_direct_quarter_preferred_to_cross_filing_difference_in_same_submission():
    data = payload()
    rows(data, "revenue").append(dict(rows(data, "revenue")[-1], start="2025-10-01", val=119.9))
    assert build(data)["quarter"][-1]["revenue"] == 119.9
