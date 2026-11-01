"""External-flow performance contracts, with no application or market access."""

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from stock_lab_core.account_performance import (
    PERIOD_COLUMNS, PRIMARY_METHOD_URL, calculate_account_performance,
)


def nav(values=(100, 110), dates=("2026-05-31", "2026-06-30"), account="A"):
    return pd.DataFrame({"date": dates, "account": account, "value_krw": values})


def flows(*rows):
    return pd.DataFrame(rows, columns=["id", "date", "account", "amount", "currency", "fx_rate"])


def flow(day="2026-06-30", amount=10, **changes):
    return dict(id="f1", date=day, account="A", amount=amount,
                currency="KRW", fx_rate=1) | changes


def calculate(values=None, cash=None, **kwargs):
    return calculate_account_performance(
        nav() if values is None else values, flows() if cash is None else cash,
        "A", **({"flows_complete": True} | kwargs),
    )


def test_gips_modified_dietz_end_of_day_example():
    result = calculate(nav((100000, 135000)), flows(
        flow("2026-06-06", -2000), flow("2026-06-11", 20000, id="f2")))
    row = result["periods"].iloc[0]
    assert result["status"] == "ready"
    assert row.opening_value_krw + row.weighted_flow_krw == pytest.approx(111066.6666667)
    assert row.return_pct == pytest.approx(15.30612244898)
    assert row.investment_pnl_krw == 17000
    assert row.method == "Modified Dietz(추정)"
    assert result["summary"]["method"] == "Modified Dietz 연결(추정)"


def test_end_deposit_does_not_fabricate_profit():
    result = calculate(cash=flows(flow()))
    assert result["summary"]["return_pct"] == 0
    assert result["summary"]["investment_pnl_krw"] == 0
    assert result["periods"].iloc[0].weighted_flow_krw == 0
    assert result["periods"].iloc[0].method == "구간수익률"


@pytest.mark.parametrize("day,weight", [("2026-06-01", 29 / 30),
                                       ("2026-06-15", 15 / 30), ("2026-06-30", 0)])
def test_calendar_day_weights(day, weight):
    row = calculate(nav((100, 130)), flows(flow(day, 20)))["periods"].iloc[0]
    assert row.weighted_flow_krw == pytest.approx(20 * weight)
    assert row.return_pct == pytest.approx(1000 / (100 + 20 * weight))


def test_anchor_flow_excluded_outside_flows_counted_and_boundaries_used_once():
    values = nav((100, 120, 132), ("2026-05-31", "2026-06-15", "2026-06-30"))
    cash = flows(*[flow(day, 10, id=str(i)) for i, day in enumerate(
        ["2026-05-30", "2026-05-31", "2026-06-15", "2026-07-01"])])
    result = calculate(values, cash)
    assert result["summary"]["outside_flow_count"] == 2
    assert result["summary"]["net_flow_krw"] == 10
    assert result["summary"]["return_pct"] == pytest.approx(21)
    assert result["periods"]["net_flow_krw"].tolist() == [10, 0]
    assert any("2건" in issue for issue in result["issues"])


def test_no_flow_geometric_link_and_public_schema():
    result = calculate(nav((100, 120, 108), ("2026-05-31", "2026-06-15", "2026-06-30")))
    assert result["summary"] == {
        "start": date(2026, 5, 31), "end": date(2026, 6, 30),
        "opening_value_krw": 100, "closing_value_krw": 108, "net_flow_krw": 0,
        "investment_pnl_krw": 8, "return_pct": pytest.approx(8),
        "method": "구간 연결", "outside_flow_count": 0, "period_count": 2,
    }
    assert list(result["periods"]) == PERIOD_COLUMNS


def test_internal_dividends_are_already_in_nav():
    values = nav((100, 110)).assign(internal_dividends=[0, 10])
    result = calculate(values)
    values["internal_dividends"] = [999, 999]
    assert calculate(values)["summary"] == result["summary"]
    assert result["summary"]["investment_pnl_krw"] == 10
    assert result["summary"]["net_flow_krw"] == 0


def test_account_outer_whitespace_has_consistent_selection_semantics():
    values = nav().assign(account=" A ")
    cash = flows(flow(account=" A "))
    assert calculate_account_performance(values, cash, "A", flows_complete=True)["summary"]["return_pct"] == 0


def test_transaction_ids_cannot_be_duplicated_with_outer_whitespace():
    result = calculate(cash=flows(flow(id="f1"), flow(id=" f1 ")))
    assert result["status"] == "invalid"


@pytest.mark.parametrize("rate", [None, "", np.nan, 1])
def test_krw_blank_rate_means_one(rate):
    assert calculate(cash=flows(flow(fx_rate=rate)))["summary"]["return_pct"] == 0


def test_usd_uses_each_flows_explicit_rate():
    cash = flows(flow("2026-06-10", 1, currency="USD", fx_rate=1300),
                 flow("2026-06-30", -1, id="f2", currency="USD", fx_rate=1400))
    row = calculate(nav((10000, 10000)), cash)["periods"].iloc[0]
    assert row.net_flow_krw == -100
    assert row.weighted_flow_krw == pytest.approx(1300 * 20 / 30)
    assert row.investment_pnl_krw == 100


@pytest.mark.parametrize("change,status", [
    ({"currency": None}, "missing"), ({"currency": "EUR"}, "invalid"),
    ({"currency": "USD", "fx_rate": None}, "missing"),
    ({"currency": "USD", "fx_rate": 0}, "invalid"),
    ({"currency": "USD", "fx_rate": -1}, "invalid"),
    ({"currency": "USD", "fx_rate": float("inf")}, "invalid"),
    ({"fx_rate": 1300}, "invalid"), ({"fx_rate": True}, "invalid"),
])
def test_currency_contract(change, status):
    result = calculate(cash=flows(flow(**change)))
    assert result["status"] == status
    assert result["summary"] == {} and result["issues"]


@pytest.mark.parametrize("bad", [True, np.bool_(False), np.nan, float("inf"),
                                 -float("inf"), "100", complex(1, 0), np.complex128(1)])
@pytest.mark.parametrize("target", ["nav", "amount"])
def test_strict_finite_nonbool_amounts(target, bad):
    values, cash = nav(), flows(flow())
    frame, key = (values, "value_krw") if target == "nav" else (cash, "amount")
    frame[key] = frame[key].astype(object)
    frame.at[0, key] = bad
    result = calculate(values, cash)
    assert result["status"] == "invalid"
    assert not result["summary"] and result["periods"].empty


@pytest.mark.parametrize("bad", ["2026-6-01", "2026-02-30", "2026-06-01T00:00:00",
                                 20260601, datetime(2026, 6, 1, 1),
                                 datetime(2026, 6, 1, tzinfo=timezone.utc),
                                 pd.Timestamp("2026-06-01 00:00:00.000000001")])
@pytest.mark.parametrize("target", ["nav", "flow"])
def test_rejects_ambiguous_or_intraday_dates(target, bad):
    values, cash = nav(), flows(flow())
    (values if target == "nav" else cash).at[0, "date"] = bad
    result = calculate(values, cash)
    assert result["status"] == "invalid" and result["summary"] == {}


def test_date_and_naive_midnight_timestamp_inputs():
    values = nav(dates=(date(2026, 5, 31), pd.Timestamp("2026-06-30")))
    assert calculate(values, flows(flow(datetime(2026, 6, 30))))["status"] == "ready"


@pytest.mark.parametrize("target", ["nav", "flow"])
def test_duplicate_dates_or_ids_rejected_even_on_different_flow_dates(target):
    values = nav()
    cash = flows(flow(), flow("2026-06-15"))
    if target == "nav":
        values = pd.concat([values, values.iloc[:1]], ignore_index=True)
        cash = flows()
    assert calculate(values, cash)["status"] == "invalid"


def test_accounts_are_isolated_and_unselected_bad_rows_ignored():
    values = pd.concat([nav(), nav((False, -5), account="B")], ignore_index=True)
    cash = flows(flow(), flow("bad", False, account="B"))
    assert calculate(values, cash)["summary"]["return_pct"] == 0
    assert calculate(nav(account="B"))["status"] == "missing"


@pytest.mark.parametrize("target", ["nav", "flow"])
def test_unassigned_account_must_not_disappear(target):
    values, cash = nav(), flows(flow())
    (values if target == "nav" else cash).at[0, "account"] = None
    result = calculate(values, cash)
    assert result["status"] == "missing" and any("계좌" in text for text in result["issues"])


@pytest.mark.parametrize("confirmation", [False, None, 1, "True", np.bool_(True)])
def test_literal_flow_completeness_required(confirmation):
    result = calculate(flows_complete=confirmation)
    assert result["status"] == "missing" and result["summary"] == {}
    assert result["periods"].empty


def test_default_does_not_assume_complete_flows():
    assert calculate_account_performance(nav(), flows(), "A")["status"] == "missing"
    result = calculate(nav((-1, 100)), flows_complete=1)
    assert result["status"] == "missing" and result["periods"].empty


@pytest.mark.parametrize("values,cash", [
    (pd.DataFrame(), flows()), (nav().iloc[:1], flows()), (nav().iloc[:0], flows()),
    (nav(), pd.DataFrame()), (nav(), flows(flow(amount=None))),
    (nav(), flows(flow(id=""))), (nav(), flows(flow(date=None))),
    (nav(dates=(None, "2026-06-30")), flows()),
])
def test_incomplete_inputs_have_no_returns(values, cash):
    result = calculate(values, cash)
    assert result["status"] == "missing" and not result["summary"]
    assert result["periods"].empty


def test_only_fully_blank_rows_skip():
    values = pd.concat([nav(), pd.DataFrame([{key: None for key in nav().columns}])])
    assert calculate(values, flows({key: None for key in flows().columns}))["status"] == "ready"
    assert calculate(values, flows(flow(amount="")))["status"] == "missing"


@pytest.mark.parametrize("values,cash", [
    (nav((0, 100)), flows()), (nav((-1, 100)), flows()),
    (nav((100, -1)), flows()),
    (nav((100, 0)), flows(flow("2026-06-01", -200))),
    (nav((100, 0)), flows(flow("2026-06-15", -200))),
    (nav((100, 0)), flows(flow("2026-06-30", 1))),
    (nav((1e308, 1e308)), flows(flow("2026-06-01", 1e308),
                                         flow("2026-06-02", 1e308, id="f2"))),
    (nav(), flows(flow(amount=1e308, currency="USD", fx_rate=1e308))),
])
def test_invalid_values_denominators_and_overflow_suppress_summary(values, cash):
    result = calculate(values, cash)
    assert result["status"] == "invalid" and result["summary"] == {}


def test_exact_total_loss_allowed_but_later_zero_opening_not_bridged():
    assert calculate(nav((100, 0)))["summary"]["return_pct"] == -100
    result = calculate(nav((100, 0, 20, 22),
                           ("2026-05-31", "2026-06-10", "2026-06-20", "2026-06-30")))
    assert result["status"] == "invalid" and result["summary"] == {}
    assert result["periods"]["status"].tolist() == ["ready", "invalid", "ready"]
    assert pd.isna(result["periods"].iloc[1].return_pct)


def test_no_invented_dates_sorting_and_input_immutability():
    values = nav((110, 100), ("2026-06-30", "2026-05-31"))
    cash = flows(flow(fx_rate=None))
    originals = values.copy(deep=True), cash.copy(deep=True)
    result = calculate(values, cash)
    assert result["periods"].shape[0] == 1
    assert result["periods"].iloc[0].start == date(2026, 5, 31)
    result["periods"].at[0, "opening_value_krw"] = 999
    assert_frame_equal(values, originals[0])
    assert_frame_equal(cash, originals[1])


def test_method_source_registered_at_import():
    from stock_lab_core.report_build import _LOADED

    assert PRIMARY_METHOD_URL.startswith("https://www.gipsstandards.org/")
    assert _LOADED["stock_lab_core.account_performance"]["sha256"] != "unavailable"
