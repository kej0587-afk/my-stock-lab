"""Execute the real monthly-save branch without touching Supabase."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_lab_core.formatters import clean_float


class UI:
    def __init__(self, confirmed, accounts, *, stale_click=False):
        self.confirmed, self.stale_click = confirmed, stale_click
        self.session_state = {"_app_all_holding_accounts": ["A", "B"], "acc_filter": accounts}
        self.defaults, self.messages = [], []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def number_input(self, *args, **kwargs):
        self.defaults.append(kwargs["value"])
        return 9700.

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


def run_branch(*, confirmed=True, accounts=("A", "B"), current=False, stale_click=False, empty=False, current_total=9000.):
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "render_monthly_rebalancing_calculator")
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
    logs = pd.DataFrame([{"month": "2026-10", "total_invested": 8000., "evaluated_value": 8500., "dividend": 10.}])
    if current:
        logs.loc[len(logs)] = ["2026-11", current_total, 9200., 20.]
    if empty:
        logs = logs.iloc[:0].copy()
    original = logs.copy(deep=True)
    ui, saved = UI(confirmed, list(accounts), stale_click=stale_click), []
    env = dict(st=ui, pd=pd, CURRENT_USER_EMAIL="owner@example.invalid", monthly_logs_df=logs,
               _this_month="2026-11", prev_total_invested=0. if empty else 8000., clean_float=clean_float,
               portfolio_summary={"current_asset": 10000.}, IS_PUBLIC_DEMO=False,
               new_total_invested=999999., save_monthly_logs_db=lambda df: saved.append(df.copy()) or True)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), env)
    pd.testing.assert_frame_equal(logs, original)
    return ui, saved


@pytest.mark.parametrize("confirmed,accounts", [(False, ("A", "B")), (True, ("A",)), (True, ())])
@pytest.mark.parametrize("stale_click", [False, True])
def test_unconfirmed_or_partial_account_save_is_blocked(confirmed, accounts, stale_click):
    _, saved = run_branch(confirmed=confirmed, accounts=accounts, stale_click=stale_click)
    assert not saved


def test_first_record_does_not_invent_initial_capital_from_planned_contribution():
    ui, saved = run_branch(empty=True)
    assert ui.defaults == [0.]
    assert saved[0].iloc[-1]["total_invested"] == 9700.


def test_current_month_update_uses_actual_input_and_keeps_dividend_and_prior_month():
    ui, saved = run_branch(current=True)
    assert ui.defaults == [9000.]
    frame = saved[0].set_index("month")
    assert frame.loc["2026-11", "total_invested"] == 9700.
    assert frame.loc["2026-11", "dividend"] == 20.
    assert frame.loc["2026-10", "total_invested"] == 8000.


def test_withdrawals_can_leave_negative_cumulative_net_contributions():
    ui, _ = run_branch(current=True, current_total=-500.)
    assert ui.defaults == [-500.]
