"""Synthetic period-matching contracts; no app startup or provider access."""

from copy import deepcopy
import socket

import pytest

from stock_lab_core.financial_periods import match_statement_period


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Statement period matching must remain offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


def statement(end="2026-06-30", year="2026", period="Q2", **values):
    return {"date": end, "calendarYear": year, "period": period, **values}


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_date_beats_nearby_date_regardless_of_order(reverse):
    exact = statement(totalAssets=100)
    nearby = statement(end="2026-06-27", totalAssets=90)
    rows = [nearby, exact]
    if reverse:
        rows.reverse()
    before = deepcopy(rows)
    assert match_statement_period(rows, statement()) is exact
    assert rows == before


@pytest.mark.parametrize("field,value", [
    ("calendarYear", "2025"), ("fiscalYear", "2025"),
    ("period", "Q1"), ("period", "FY"),
])
def test_exact_date_cannot_override_conflicting_period_metadata(field, value):
    candidate = statement(**{field: value})
    assert match_statement_period([candidate], statement()) == {}


@pytest.mark.parametrize("bad_date", [
    None, "", "null", "2026-02-30", "20260630", "2026-6-30",
    "2026-06-30T00:00:00", 20260630,
])
def test_invalid_dates_are_held_back_on_either_side(bad_date):
    invalid = statement(end=bad_date)
    assert match_statement_period([invalid], statement()) == {}
    assert match_statement_period([statement()], invalid) == {}


@pytest.mark.parametrize("patch", [
    {"period": None}, {"period": ""}, {"period": "Q5"},
    {"calendarYear": None}, {"calendarYear": "2026-06-30"},
    {"calendarYear": 2026.0}, {"calendarYear": True},
    {"calendarYear": "2026", "fiscalYear": "2025"},
])
def test_missing_or_invalid_year_and_period_are_not_inferred_from_date(patch):
    invalid = {**statement(), **patch}
    assert match_statement_period([invalid], statement()) == {}
    assert match_statement_period([statement()], invalid) == {}


def test_modern_fiscal_year_and_legacy_calendar_year_are_compatible():
    candidate = {"date": "2026-06-30", "fiscalYear": 2026, "period": "q2"}
    assert match_statement_period([candidate], statement()) is candidate


def test_off_calendar_fiscal_year_is_not_relabelled_using_the_end_date():
    income = statement(end="2026-02-27", year="2025", period="FY")
    candidate = statement(end="2026-02-28", year="2025", period="FY")
    assert match_statement_period([candidate], income) is candidate


@pytest.mark.parametrize("end", ["2026-06-08", "2026-06-22"])
def test_same_quarter_date_drift_accepts_up_to_seven_days(end):
    candidate = statement(end=end)
    assert match_statement_period([candidate], statement(end="2026-06-15")) is candidate


@pytest.mark.parametrize("candidate,income", [
    (statement(end="2026-06-07"), statement(end="2026-06-15")),
    (statement(end="2026-06-23"), statement(end="2026-06-15")),
    (statement(end="2026-07-01"), statement()),
    (statement(end="2025-12-31", period="FY"), statement(end="2026-01-01", period="FY")),
    (statement(end="2026-06-29", year="2025"), statement()),
    (statement(end="2026-06-29", period="Q1"), statement()),
])
def test_drift_never_crosses_year_or_quarter_or_metadata_boundaries(candidate, income):
    assert match_statement_period([candidate], income) == {}


def test_annual_statement_never_substitutes_for_q4_at_the_same_year_end():
    annual = statement(end="2025-12-31", year="2025", period="FY")
    quarter = statement(end="2025-12-31", year="2025", period="Q4")
    assert match_statement_period([annual], quarter) == {}
    assert match_statement_period([quarter], annual) == {}


def test_matching_year_without_matching_quarter_has_no_first_row_fallback():
    first = statement(end="2026-03-31", period="Q1", totalAssets=100)
    assert match_statement_period([first], statement(end="2026-09-30", period="Q3")) == {}
    assert match_statement_period([statement(end="2026-04-30")], statement()) == {}


def test_nearest_compatible_candidate_wins_regardless_of_order():
    near = statement(end="2026-06-29", totalAssets=100)
    far = statement(end="2026-06-27", totalAssets=90)
    assert match_statement_period([far, near], statement()) is near
    assert match_statement_period([near, far], statement()) is near


@pytest.mark.parametrize("exact", [False, True])
def test_conflicting_best_candidates_are_held_back_instead_of_using_list_order(exact):
    income = statement(end="2026-06-15")
    rows = [statement(end="2026-06-15" if exact else "2026-06-14", totalAssets=100),
            statement(end="2026-06-15" if exact else "2026-06-16", totalAssets=90)]
    assert match_statement_period(rows, income) == {}
    assert match_statement_period(list(reversed(rows)), income) == {}


def test_exact_conflicts_do_not_fall_back_to_a_nearby_date():
    rows = [statement(totalAssets=100), statement(totalAssets=90),
            statement(end="2026-06-29", totalAssets=80)]
    assert match_statement_period(rows, statement()) == {}


def test_identical_duplicates_are_safe_without_modifying_either_input():
    income = statement()
    row = statement(totalAssets=0, netCashProvidedByOperatingActivities=None)
    records = [row, deepcopy(row)]
    before = deepcopy((income, records))
    assert match_statement_period(records, income) is row
    assert (income, records) == before


@pytest.mark.parametrize("records", [None, {}, [], [None, [], "bad", {}]])
def test_empty_or_malformed_records_do_not_supply_a_match(records):
    assert match_statement_period(records, statement()) == {}


@pytest.mark.parametrize("income", [None, [], {}, "bad"])
def test_malformed_income_row_does_not_supply_a_match(income):
    assert match_statement_period([statement()], income) == {}
