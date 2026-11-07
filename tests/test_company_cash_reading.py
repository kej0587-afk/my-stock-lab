"""Synthetic SEC packets only: no live company/account data or market calls."""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import socket

import pytest

from stock_lab_core import company_cash_reading as reading
from stock_lab_core.report_build import _LOADED
from stock_lab_core.sec_quarter_review import TAGS
from stock_lab_core.sec_quarter_review_view import load_quarter_evidence


def packet(ticker="ACME", *, cumulative=False, productive=False):
    data = {"cik": 123, "facts": {"us-gaap": {}}}
    values = dict(revenue=100e6, op_income=20e6, net_income=15e6,
                  ocf=30e6, cash_capex=12e6, cash=200e6)
    # Six-month anchors plus direct quarters exercise the real loader contract.
    for field, names in TAGS.items():
        facts = []
        for q, end in ((1, "2026-03-31"), (2, "2026-06-30")):
            fact = dict(end=end, val=values[field] * (q if field != "cash" else 1),
                        form="10-Q", filed="2026-08-01", accn="0000000123-26-000001")
            if field != "cash":
                fact["start"] = "2026-01-01"
            facts.append(fact)
        if not cumulative and field != "cash":
            facts.append(dict(facts[-1], start="2026-04-01", val=values[field]))
        tag = names[1] if productive and field == "cash_capex" else names[0]
        data["facts"]["us-gaap"][tag] = {"units": {"USD": facts}}
    return load_quarter_evidence(
        ticker, resolve_cik=lambda symbol: (123, {"ticker": symbol, "cik_str": 123}),
        fetch_facts=lambda cik: data, now=datetime(2026, 11, 8, tzinfo=timezone.utc))


def facts(result, axis):
    return next(row["확인된 사실"] for row in result if row["검토축"] == axis)


def set_value(p, field, value):
    row = p["quarter"][-1]
    row[field] = row["provenance"][field]["facts"][0]["value"] = value


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("reading must not request network")
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.mark.parametrize("ticker", ["ACME", "NVDA", "MSFT", "BRK.B"])
@pytest.mark.parametrize("cumulative", [False, True])
def test_success_uses_validated_latest_amounts_not_cached_derived_values(ticker, cumulative):
    p = packet(ticker, cumulative=cumulative)
    p["quarter"][-1].update(fcf_cash=999e6, op_margin_pct=999, yoy_pct={"revenue": 999})
    result = reading.company_cash_reading(p)
    assert len(result) == 3
    assert all(set(row) == {"검토축", "확인된 사실", "왜 중요한가", "다음 확인"} for row in result)
    assert all(isinstance(value, str) and value for row in result for value in row.values())
    income, cash = facts(result, "매출·이익"), facts(result, "현금 창출·투자")
    assert "2026-04-01 ~ 2026-06-30" in income
    assert "매출 100.0백만 USD" in income and "순이익 15.0백만 USD" in income
    assert "영업이익률 20.0%" in income
    assert "단순차액(영업현금흐름 − 현금 투자지출) 18.0백만 USD" in cash
    assert "투자지출/영업현금흐름 40.0%" in cash
    assert "999" not in str(result) and "최근 실적발표 전체 반영 미확인" in str(result)


def test_productive_assets_are_explicit_not_relabeled_as_ppe_or_ai():
    result = reading.company_cash_reading(packet(productive=True))
    assert "투자지출 범위: 유형·소프트웨어·무형자산" in facts(result, "현금 창출·투자")
    assert "18.0백만 USD" in facts(result, "현금 창출·투자")
    assert "비현금 리스·구매약정·인수대금" in result[-1]["왜 중요한가"]
    assert "AI 매출이나 주가 변동 원인으로 연결할 수 없습니다" in result[0]["왜 중요한가"]


def test_week_based_non_calendar_fiscal_quarter_is_supported():
    p = packet("NVDA")
    row = p["quarter"][-1]
    row.update(start="2026-05-04", end="2026-08-02", fiscal_quarter=2)
    for field in ("revenue", "op_income", "net_income", "ocf", "cash_capex"):
        row["provenance"][field]["facts"][0].update(start=row["start"], end=row["end"], filed="2026-08-20")
    result = reading.company_cash_reading(p)
    assert "2026-05-04 ~ 2026-08-02" in facts(result, "매출·이익")
    assert "투자지출/영업현금흐름 40.0%" in facts(result, "현금 창출·투자")


@pytest.mark.parametrize("p", [None, {}, {"quarter": [], "status": "no_supported_quarter_data"}])
def test_unsupported_is_explicit_not_a_fabricated_zero(p):
    result = reading.company_cash_reading(p)
    assert len(result) == 1 and result[0]["검토축"] == "자료 범위"
    assert "분기 근거 없음" in result[0]["확인된 사실"]
    assert "20-F" in result[0]["다음 확인"]


@pytest.mark.parametrize("field,axis", [("revenue", "매출·이익"), ("op_income", "매출·이익"),
                                       ("net_income", "매출·이익"), ("ocf", "현금 창출·투자"),
                                       ("cash_capex", "현금 창출·투자")])
def test_missing_field_retains_other_evidence_without_older_fallback(field, axis):
    p = packet()
    p["quarter"][-1][field] = None
    p["quarter"][-1]["provenance"][field] = {"status": "missing_or_ambiguous"}
    result = reading.company_cash_reading(p)
    assert "부분 확인" in facts(result, axis) and "보류" in facts(result, axis)
    assert "5개 항목 중 4개 확인" in facts(result, "자료 범위")
    assert "2026-04-01 ~ 2026-06-30" in facts(result, axis)
    if axis == "현금 창출·투자":
        assert "단순차액·투자지출 비율 보류" in facts(result, axis)
        assert "18.0백만 USD" not in facts(result, axis)
    else:
        assert "18.0백만 USD" in facts(result, "현금 창출·투자")


@pytest.mark.parametrize("status", ["cross_filing_difference_review", "later_revision_in_subtrahend",
                                   "direct_cumulative_conflict", "unknown_status"])
def test_status_holds_even_a_finite_amount_with_matching_signatures(status):
    p = packet(cumulative=True)
    p["quarter"][-1]["provenance"]["ocf"]["status"] = status
    cash = facts(reading.company_cash_reading(p), "현금 창출·투자")
    assert "영업현금흐름 보류" in cash and "현금 투자지출 12.0백만 USD" in cash
    assert "18.0백만 USD" not in cash and "40.0%" not in cash


@pytest.mark.parametrize("field,axis", [("cash_capex", "현금 창출·투자"), ("op_income", "매출·이익")])
def test_valid_individual_fields_from_different_filings_cannot_form_ratios(field, axis):
    p = packet()
    p["quarter"][-1]["provenance"][field]["facts"][0]["accession"] = "0000000123-26-000002"
    text = facts(reading.company_cash_reading(p), axis)
    assert "동일 기간·제출본" in text and "보류" in text
    assert ("12.0백만 USD" if field == "cash_capex" else "20.0백만 USD") in text
    assert "40.0%" not in text and "20.0%" not in text and "18.0백만 USD" not in text


def test_matching_crossfiling_operands_cannot_bypass_guard_without_status():
    p = packet("MSFT", cumulative=True)
    for field in ("ocf", "cash_capex"):
        p["quarter"][-1]["provenance"][field]["facts"][1]["accession"] = "0000000123-26-000002"
    cash = facts(reading.company_cash_reading(p), "현금 창출·투자")
    assert "확인 보류" in cash and "서로 다른 제출본 누적차감" in cash
    assert "18.0백만 USD" not in cash


@pytest.mark.parametrize("mutation", ["currency", "period", "future_filing", "tag", "form",
                                     "no_facts", "no_provenance", "mismatch", "scope", "negative"])
def test_finite_amount_is_not_enough_without_its_own_valid_provenance(mutation):
    p = packet()
    row = p["quarter"][-1]
    evidence = row["provenance"]["cash_capex"]
    fact = evidence["facts"][0]
    if mutation == "currency": fact["unit"] = "EUR"
    elif mutation == "period": fact["start"] = "2026-01-01"
    elif mutation == "future_filing": fact["filed"] = "2026-12-01"
    elif mutation == "tag": fact["tag"] = "Revenues"
    elif mutation == "form": fact["form"] = "20-F"
    elif mutation == "no_facts": evidence["facts"] = []
    elif mutation == "no_provenance": del row["provenance"]["cash_capex"]
    elif mutation == "mismatch": row["cash_capex"] = 13e6
    elif mutation == "scope": row["cash_capex_scope"] = "AI 투자"
    else: set_value(p, "cash_capex", -12e6)
    cash = facts(reading.company_cash_reading(p), "현금 창출·투자")
    assert "영업현금흐름 30.0백만 USD" in cash and "현금 투자지출 보류" in cash
    assert "18.0백만 USD" not in cash and "40.0%" not in cash


@pytest.mark.parametrize("where", ["packet", "row"])
def test_non_usd_basis_is_unsupported(where):
    p = packet()
    if where == "packet": p["currency"] = "EUR"
    else: p["quarter"][-1]["unit"] = "EUR"
    result = reading.company_cash_reading(p)
    assert len(result) == 1 and "통화" in result[0]["확인된 사실"]


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), True, "30000000", 10**400])
def test_invalid_numbers_are_not_coerced_or_zero_filled(value):
    p = packet()
    set_value(p, "ocf", value)
    cash = facts(reading.company_cash_reading(p), "현금 창출·투자")
    assert "영업현금흐름 보류" in cash and "40.0%" not in cash


@pytest.mark.parametrize("ocf,residual", [(0, "-12.0"), (-30e6, "-42.0")])
def test_nonpositive_ocf_preserves_amounts_and_difference_but_not_ratio(ocf, residual):
    p = packet()
    set_value(p, "ocf", ocf)
    result = reading.company_cash_reading(p)
    cash = facts(result, "현금 창출·투자")
    assert f") {residual}백만 USD" in cash and "투자지출/영업현금흐름 보류" in cash
    assert "영업현금흐름이 0 이하" in result[-1]["왜 중요한가"]


def test_zero_capex_is_confirmed_zero_and_negative_residual_has_bounded_explanation():
    p = packet()
    set_value(p, "cash_capex", 0)
    assert "투자지출/영업현금흐름 0.0%" in facts(reading.company_cash_reading(p), "현금 창출·투자")
    set_value(p, "cash_capex", 40e6)
    result = reading.company_cash_reading(p)
    assert ") -10.0백만 USD" in facts(result, "현금 창출·투자")
    assert "현금 투자지출이 영업에서 창출한 현금을 초과" in result[-1]["왜 중요한가"]


@pytest.mark.parametrize("revenue", [0, -100e6])
def test_nonpositive_revenue_withholds_margin(revenue):
    p = packet()
    set_value(p, "revenue", revenue)
    assert "영업이익률 보류" in facts(reading.company_cash_reading(p), "매출·이익")


def test_pure_repeatable_no_packet_or_registration_mutation_and_no_io(monkeypatch):
    p = packet(cumulative=True)
    p["gaps"] = [{"after": "2025-12-31", "before": "2026-04-01"}]
    before, loaded = deepcopy(p), deepcopy(_LOADED)
    def fail(*args, **kwargs):
        pytest.fail("reading must not do file I/O")
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr(Path, "open", fail)
    first = reading.company_cash_reading(p)
    second = reading.company_cash_reading(p)
    assert first == second and p == before and _LOADED == loaded
    assert "누락 구간 있음" in facts(first, "자료 범위")
    first[-1]["확인된 사실"] = "caller edit"
    assert reading.company_cash_reading(p) == second


def test_module_registers_loaded_source():
    source = Path(reading.__file__).resolve()
    assert _LOADED[reading.__name__] == {"path": str(source), "sha256": sha256(source.read_bytes()).hexdigest()}
