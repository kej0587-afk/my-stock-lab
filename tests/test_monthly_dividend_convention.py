"""Legacy monthly values exclude dividends; account ledger NAV includes them."""

import ast
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core.account_performance import calculate_account_performance
from stock_lab_core.portfolio import calc_portfolio_summary, prepare_monthly_performance_df


def test_monthly_receipts_are_added_once_without_mutating_historical_values():
    records = pd.DataFrame([
        {"month": "2026-03", "total_invested": 1500., "evaluated_value": 1500., "dividend": 0.},
        {"month": "2026-01", "total_invested": 1000., "evaluated_value": 1040., "dividend": 10.},
        {"month": "2026-02", "total_invested": 1500., "evaluated_value": 1540., "dividend": 20.},
    ])
    original = records.copy(deep=True)
    result = prepare_monthly_performance_df(records)
    pd.testing.assert_frame_equal(records, original)
    assert result["evaluated_value"].tolist() == [1040., 1540., 1500.]
    assert result["dividend"].tolist() == [10., 20., 0.]
    assert result["cum_dividend"].tolist() == [10., 30., 30.]
    assert result["cum_profit"].tolist() == [50., 70., 30.]
    assert result["cum_return_pct"].tolist() == pytest.approx([5., 70. / 1500 * 100, 2.])
    pd.testing.assert_frame_equal(prepare_monthly_performance_df(records), result)


def test_legacy_ex_dividend_and_nav_inclusive_examples_agree_without_double_counting():
    records = pd.DataFrame([{
        "month": "2026-10", "total_invested": 100_000., "evaluated_value": 110_000., "dividend": 5000.,
    }])
    legacy = prepare_monthly_performance_df(records).iloc[0]
    navs = pd.DataFrame([
        {"date": "2026-09-30", "account": "example", "value_krw": 100_000.},
        {"date": "2026-10-30", "account": "example", "value_krw": 115_000.},
    ])
    flows = pd.DataFrame(columns=["id", "date", "account", "amount", "currency", "fx_rate"])
    result = calculate_account_performance(navs, flows, "example", flows_complete=True)
    assert result["status"] == "ready"
    assert result["summary"]["investment_pnl_krw"] == legacy["cum_profit"] == 15_000.
    assert result["summary"]["return_pct"] == pytest.approx(legacy["cum_return_pct"])
    assert result["summary"]["net_flow_krw"] == 0.


def test_future_ledger_discloses_the_different_dividend_basis():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
import pandas as pd
import streamlit as st
from stock_lab_core.account_performance_view import render_account_performance
render_account_performance(st, owner_scope="example", monthly_logs_df=pd.DataFrame({"month": ["2026-10"]}))
''').run()
    assert not app.exception
    captions = [item.value for item in app.caption]
    assert any("자동 변환하지 않았습니다" in value for value in captions)
    assert any("배당 제외 평가금액과 기준이 다릅니다" in value for value in captions)
    assert not app.metric


@lru_cache(maxsize=1)
def monthly_editor_block():
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    marker = ast.dump(ast.parse('st.markdown("### 4) 월별 로그 관리")').body[0])
    save_button = ast.dump(ast.parse('st.button("월별 로그 저장")').body[0].value)
    for parent in ast.walk(tree):
        for _, items in ast.iter_fields(parent):
            if not isinstance(items, list):
                continue
            start = next((i for i, node in enumerate(items) if isinstance(node, ast.Expr)
                          and ast.dump(node) == marker), None)
            if start is not None:
                end = next(i for i in range(start + 1, len(items)) if isinstance(items[i], ast.If)
                           and ast.dump(items[i].test) == save_button)
                return compile(ast.Module(body=items[start:end + 1], type_ignores=[]), str(source), "exec")
    raise AssertionError("Monthly editor not found")


@pytest.mark.parametrize("empty", [True, False])
def test_monthly_editor_labels_preserve_the_existing_raw_columns(empty):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
import pandas as pd
import streamlit as st
from tests.test_monthly_dividend_convention import monthly_editor_block
source = pd.DataFrame([dict(month="2026-10", total_invested=100000., evaluated_value=110000., dividend=5000.)])
if st.session_state["empty"]:
    source = source.iloc[:0].copy()
def load_monthly_logs_db():
    return source.copy(deep=True)
exec(monthly_editor_block(), globals())
''')
    app.session_state["empty"] = empty
    app.run()
    assert not app.exception
    frame = app.dataframe[0].value
    assert frame.columns.tolist() == ["month", "total_invested", "evaluated_value", "dividend"]
    assert len(frame) == (0 if empty else 1)
    if not empty:
        assert frame["evaluated_value"].tolist() == [110000.]
        assert frame["dividend"].tolist() == [5000.]
    assert any("해당 월 수령액" in item.value for item in app.caption)


@pytest.mark.parametrize("dividends", [None, pd.DataFrame(), pd.DataFrame([
    {"amount": 5000., "currency": "KRW"}, {"amount": 10., "currency": "USD"},
])])
def test_live_dividend_inclusive_balances_do_not_add_the_receipt_history_again(dividends):
    holdings = pd.DataFrame({"원화환산": [120_000.]})
    result = calc_portfolio_summary(holdings, 100_000., 5000., 10., 1300., dividends)
    assert result["current_asset"] == 138_000.
    assert result["cum_profit"] == 38_000.
    assert result["cum_return"] == 38.
    assert result["cash_value"] == 18_000.
    expected = 18_000. if dividends is not None and not dividends.empty else 0.
    assert result["total_dividend"] == expected


def test_reinvested_dividend_is_already_in_holdings_even_with_no_cash():
    holdings = pd.DataFrame({"원화환산": [115_000.]})
    dividends = pd.DataFrame([{"amount": 5000., "currency": "KRW"}])
    result = calc_portfolio_summary(holdings, 100_000., 0., 0., 1300., dividends)
    assert result["cum_profit"] == 15_000.
    assert result["cum_return"] == 15.
    assert result["total_dividend"] == 5000.


@pytest.mark.parametrize("fx", [1300., 1400.])
def test_cash_only_fx_translation_is_applied_once_to_profit(fx):
    result = calc_portfolio_summary(pd.DataFrame(), 130_000., 0., 105., fx,
                                    pd.DataFrame([{"amount": 5., "currency": "USD"}]))
    assert result["current_asset"] == 105. * fx
    assert result["cum_profit"] == 105. * fx - 130_000.
    assert result["total_dividend"] == 5. * fx
