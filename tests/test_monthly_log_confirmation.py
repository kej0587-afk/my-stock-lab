"""Execute the real monthly-save branch without touching Supabase."""

import ast
import math
from pathlib import Path
from functools import lru_cache

import pandas as pd
import pytest

from stock_lab_core.formatters import clean_float


class UI:
    def __init__(self, confirmed, accounts, *, inputs, stale_click=False):
        self.confirmed, self.stale_click = confirmed, stale_click
        self.inputs = inputs
        self.session_state = {"_app_all_holding_accounts": ["A", "B"], "acc_filter": accounts}
        self.defaults, self.messages = [], []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def number_input(self, *args, **kwargs):
        self.defaults.append(kwargs["value"])
        return self.inputs.get(args[0], kwargs["value"])

    def caption(self, *args, **kwargs):
        pass

    def checkbox(self, *args, **kwargs):
        return self.confirmed

    def columns(self, count):
        return [self] * count

    def button(self, *args, **kwargs):
        return self.stale_click or not kwargs["disabled"]

    def warning(self, message):
        self.messages.append(message)

    success = error = warning

    def rerun(self):
        pass


TOTAL = "확인한 실제 누적 순입금액(원)"
VALUE = "배당을 뺀 평가금액(원)"
DIVIDEND = "해당 월 수령 배당금(원)"


@lru_cache(maxsize=1)
def monthly_save_branch():
    source = Path(__file__).resolve().parents[1] / "stock_lab_core" / "monthly_rebalance_log.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "render_monthly_log_panel")
    selected = None
    for parent in ast.walk(fn):
        for _, items in ast.iter_fields(parent):
            if not isinstance(items, list):
                continue
            starts = [i for i, node in enumerate(items)
                      if isinstance(node, ast.ImportFrom) and node.module == "hashlib"]
            if starts:
                start = starts[0]
                end = next(i for i in range(start, len(items)) if isinstance(items[i], ast.With)
                           and ast.unparse(items[i].items[0].context_expr) == "b1")
                selected = items[start:end + 1]
    assert selected
    return compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec")


def run_branch(*, confirmed=True, accounts=("A", "B"), current=False, stale_click=False, empty=False,
               current_total=9000., inputs=None):
    logs = pd.DataFrame([{"month": "2026-10", "total_invested": 8000., "evaluated_value": 8500., "dividend": 10.}])
    if current:
        logs.loc[len(logs)] = ["2026-11", current_total, 9200., 20.]
    if empty:
        logs = logs.iloc[:0].copy()
    original = logs.copy(deep=True)
    if inputs is None:
        inputs = {TOTAL: 9700., VALUE: 9400., DIVIDEND: 30.}
    ui, saved = UI(confirmed, list(accounts), inputs=inputs, stale_click=stale_click), []
    env = dict(st=ui, pd=pd, math=math, CURRENT_USER_EMAIL="owner@example.invalid", monthly_logs_df=logs,
               _this_month="2026-11", prev_total_invested=0. if empty else 8000., clean_float=clean_float,
               portfolio_summary={"current_asset": 10000.}, IS_PUBLIC_DEMO=False,
               new_total_invested=999999., save_monthly_logs_db=lambda df: saved.append(df.copy()) or True)
    exec(monthly_save_branch(), env)
    pd.testing.assert_frame_equal(logs, original)
    return ui, saved


@pytest.mark.parametrize("confirmed,accounts", [(False, ("A", "B")), (True, ("A",)), (True, ())])
@pytest.mark.parametrize("stale_click", [False, True])
def test_unconfirmed_or_partial_account_save_is_blocked(confirmed, accounts, stale_click):
    _, saved = run_branch(confirmed=confirmed, accounts=accounts, stale_click=stale_click)
    assert not saved


def test_first_record_does_not_invent_initial_capital_from_planned_contribution():
    ui, saved = run_branch(empty=True)
    assert ui.defaults == [0., None, None]
    assert saved[0].iloc[-1]["total_invested"] == 9700.
    assert saved[0].iloc[-1]["evaluated_value"] == 9400.
    assert saved[0].iloc[-1]["dividend"] == 30.


def test_current_month_update_uses_actual_input_and_keeps_dividend_and_prior_month():
    ui, saved = run_branch(current=True, inputs={TOTAL: 9700., VALUE: 9400.})
    assert ui.defaults == [9000., 9200., 20.]
    frame = saved[0].set_index("month")
    assert frame.loc["2026-11", "total_invested"] == 9700.
    assert frame.loc["2026-11", "evaluated_value"] == 9400.
    assert frame.loc["2026-11", "dividend"] == 20.
    assert frame.loc["2026-10", "total_invested"] == 8000.
    assert frame.loc["2026-10", "evaluated_value"] == 8500.
    assert frame.loc["2026-10", "dividend"] == 10.


def test_withdrawals_can_leave_negative_cumulative_net_contributions():
    ui, _ = run_branch(current=True, current_total=-500.)
    assert ui.defaults == [-500., 9200., 20.]


@pytest.mark.parametrize("stale_click", [False, True])
@pytest.mark.parametrize("inputs", [{}, {TOTAL: 9700.}, {TOTAL: 9700., VALUE: 9400.}])
def test_new_month_requires_explicit_dividend_excluded_value_and_month_dividend(inputs, stale_click):
    ui, saved = run_branch(inputs=inputs, stale_click=stale_click)
    assert ui.defaults == [8000., None, None]
    assert not saved


@pytest.mark.parametrize("field", [TOTAL, VALUE, DIVIDEND])
@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), float("-inf"), True])
def test_nonfinite_or_missing_input_does_not_write_even_on_stale_click(field, bad):
    inputs = {TOTAL: 9700., VALUE: 9400., DIVIDEND: 30., field: bad}
    _, saved = run_branch(inputs=inputs, stale_click=True)
    assert not saved


@pytest.mark.parametrize("field", [VALUE, DIVIDEND])
def test_negative_value_or_dividend_does_not_write(field):
    inputs = {TOTAL: 9700., VALUE: 9400., DIVIDEND: 30., field: -1.}
    _, saved = run_branch(inputs=inputs, stale_click=True)
    assert not saved


def test_zero_dividend_is_confirmed_not_missing_and_existing_month_can_be_corrected():
    _, saved = run_branch(current=True, inputs={TOTAL: -500., VALUE: 0., DIVIDEND: 0.})
    row = saved[0].set_index("month").loc["2026-11"]
    assert row[["total_invested", "evaluated_value", "dividend"]].tolist() == [-500., 0., 0.]


def test_current_month_dividend_is_replaced_not_accumulated_on_resave():
    _, saved = run_branch(current=True)
    assert saved[0].set_index("month").loc["2026-11", "dividend"] == 30.


def test_real_widgets_do_not_fill_dividend_excluded_nav_from_current_total():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
import math
import pandas as pd
import streamlit as st
from stock_lab_core.formatters import clean_float
from tests.test_monthly_log_confirmation import monthly_save_branch
CURRENT_USER_EMAIL = "offline@example.invalid"
_this_month = "2026-11"
prev_total_invested = 8000.
IS_PUBLIC_DEMO = False
monthly_logs_df = pd.DataFrame([dict(month="2026-10", total_invested=8000., evaluated_value=8500., dividend=10.)])
portfolio_summary = {"current_asset": 10000.}
st.session_state["_app_all_holding_accounts"] = ["A", "B"]
st.session_state["acc_filter"] = ["A", "B"]
def save_monthly_logs_db(df):
    st.session_state["saved"] = df
    return False
exec(monthly_save_branch(), globals())
''').run()
    assert not app.exception
    assert [widget.value for widget in app.number_input] == [8000., None, None]
    app.checkbox[0].check().run()
    assert app.button[0].disabled
    app.number_input[1].set_value(9400.).run()
    assert app.button[0].disabled
    app.number_input[2].set_value(0.).run()
    assert not app.button[0].disabled
    app.button[0].click().run()
    assert not app.exception
    row = app.session_state["saved"].set_index("month").loc["2026-11"]
    assert row[["total_invested", "evaluated_value", "dividend"]].tolist() == [8000., 9400., 0.]
