"""Exact UI, allocation and state parity with the pre-extraction calculator."""

import ast
from copy import deepcopy
import datetime
from functools import lru_cache
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.asset_classifier import is_known_etf_ticker, resolve_effective_investment_bucket
from stock_lab_core.formatters import clean_bool, clean_float, is_kr_listed, normalize_bucket
from tests.test_money_flow_renderer_refactor import UI as BaseUI
from tests.test_portfolio_renderer_refactor import freeze
from tests.test_print_report_refactor import holdings


ROOT = Path(__file__).resolve().parents[1]
BASE = "8d6ee440f4fe2386fc8c218ccbabf165b944b795"
MAIN = "render_monthly_rebalancing_calculator"


@pytest.fixture(scope="module")
def sources():
    old = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    return old, (ROOT / "app.py").read_text(encoding="utf-8-sig")


@lru_cache(maxsize=2)
def compiled_functions(source):
    names = {MAIN, "_rebcalc_signal_multiplier"}
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names]
    return compile(ast.Module(body=nodes, type_ignores=[]), "<monthly-calculator>", "exec")


class Rerun(BaseException):
    pass


class UI(BaseUI):
    def __init__(self, state, inputs, action):
        super().__init__(None)
        self.session_state = deepcopy(state)
        self.inputs, self.action = inputs, action

    def record(self, name, *args, **kwargs):
        self.log.append((name, freeze(args), freeze(kwargs)))

    def expander(self, *args, **kwargs):
        self.record("expander", *args, **kwargs)
        return self

    def container(self):
        self.record("container")
        return self

    def number_input(self, label, **kwargs):
        self.record("number_input", label, **kwargs)
        value = self.inputs.get(kwargs["key"], self.inputs.get(label, kwargs.get("value")))
        self.session_state[kwargs["key"]] = value
        return value

    checkbox = number_input

    def multiselect(self, label, **kwargs):
        formatter = kwargs.pop("format_func")
        self.record("multiselect", label, formatted=[formatter(t) for t in kwargs["options"]], **kwargs)
        value = self.inputs.get(kwargs["key"], kwargs["default"])
        self.session_state[kwargs["key"]] = list(value)
        return value

    def button(self, *args, **kwargs):
        self.record("button", *args, **kwargs)
        # Permit a stale click too; the save branch must enforce its own guard.
        return kwargs["key"] == self.action

    def rerun(self):
        self.record("rerun")
        raise Rerun()


def scenario():
    frame = holdings()
    frame.loc[3, "bucket"] = "swing"
    frame["기술적타점"] = ["분할 매수", "과열", "분할 매수", "-", "-", "-"]
    return frame


def run(source, frame, *, state=None, inputs=None, action=None, fx=1400., demo=False,
        logs="previous", save_ok=True, month="2026-11"):
    state = dict({"_app_all_holding_accounts": ["A", "B"], "acc_filter": ["A", "B"]}, **(state or {}))
    ui = UI(state, inputs or {}, action)
    before = frame.copy(deep=True) if frame is not None else None
    monthly_logs = pd.DataFrame([{"month": "2026-10", "total_invested": 1000000.,
        "evaluated_value": 1100000., "dividend": 2000.}])
    if logs == "current":
        monthly_logs.loc[len(monthly_logs)] = [month, 1500000., 1600000., 0.]
    elif logs == "empty":
        monthly_logs = monthly_logs.iloc[:0].copy()
    elif logs is None:
        monthly_logs = None
    logs_before = monthly_logs.copy(deep=True) if monthly_logs is not None else None

    def save(df):
        ui.record("save_monthly_logs", df)
        return save_ok

    class FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(int(month[:4]), int(month[5:]), 2)

    namespace = dict(globals(), st=ui, CURRENT_USER_EMAIL="owner@example.invalid",
        IS_PUBLIC_DEMO=demo, save_monthly_logs_db=save)
    exec(compiled_functions(source), namespace)
    with patch("datetime.date", FixedDate):
        try:
            namespace[MAIN](frame, fx, {"current_asset": 2000000.}, monthly_logs)
        except Rerun:
            pass
    if before is not None:
        pd.testing.assert_frame_equal(frame, before, check_exact=True)
    if logs_before is not None:
        pd.testing.assert_frame_equal(monthly_logs, logs_before, check_exact=True)
    return ui.log, ui.session_state


@pytest.mark.parametrize("redistribute", [False, True])
@pytest.mark.parametrize("kind", ["default", "signals", "always", "underalloc", "accumulated", "all_blocked", "string_weights", "zero_price"])
def test_tables_metrics_labels_keys_and_state_are_identical(sources, redistribute, kind):
    frame = scenario()
    state = {"rebcalc_redistribute": redistribute}
    if kind == "signals":
        state["_ticker_signal_cache"] = {"SOXL": "추세방어", "MSFT": "매수", "ABC": "매수"}
    elif kind == "always":
        state["rebcalc_always_invest"] = ["MSFT", "SOXL", "removed"]
    elif kind == "underalloc":
        state["rebcalc_monthly"] = 1000
    elif kind == "accumulated":
        state["rebcalc_accum"] = {"MSFT": 400000., "SOXL": 50000.}
    elif kind == "all_blocked":
        frame["기술적타점"] = "추세방어"
    elif kind == "string_weights":
        frame["목표비중"] = ["40", "30", "10", "10", "bad", None]
    elif kind == "zero_price":
        frame["현재가"] = 0.
    assert run(sources[0], frame, state=state) == run(sources[1], frame, state=state)


@pytest.mark.parametrize("kind", ["empty", "none", "zero_budget", "no_target", "no_active", "reserve", "cash"])
def test_early_returns_do_not_change(sources, kind):
    frame, state = scenario(), {}
    if kind == "empty":
        frame = frame.iloc[:0].copy()
    elif kind == "none":
        frame = None
    elif kind == "zero_budget":
        state["rebcalc_monthly"] = 0
    elif kind == "no_target":
        frame["목표비중"] = 0.
    elif kind == "no_active":
        frame["운용대상"] = False
    else:
        frame["bucket"] = kind
    assert run(sources[0], frame, state=state) == run(sources[1], frame, state=state)


@pytest.mark.parametrize("action", ["rebcalc_accum_add", "rebcalc_accum_reset", "rebcalc_do_carryover", "rebcalc_reset"])
def test_buttons_preserve_amount_updates_and_rerun_boundary(sources, action):
    state = {"rebcalc_monthly": 1000, "rebcalc_carryover": 100, "rebcalc_accum": {"SOXL": 10.},
        "rebcalc_done_2026-11": {"MSFT": True}}
    old, new = (run(source, scenario(), state=state, action=action) for source in sources)
    assert old == new
    assert new[0][-1][0] == "rerun"


@pytest.mark.parametrize("kind", ["unchecked", "confirmed", "partial_scope", "demo", "missing_logs", "current", "empty", "save_failed"])
def test_monthly_save_guards_payloads_and_side_effects_are_preserved(sources, kind):
    inputs = {"확인한 실제 누적 순입금액(원)": 1800000., "배당을 뺀 평가금액(원)": 2000000.,
        "해당 월 수령 배당금(원)": 1000.,
        "실제 누적 순입금액·배당 제외 평가금액·해당 월 배당과 전체 계좌 범위를 확인했습니다": kind != "unchecked"}
    kwargs = dict(inputs=inputs, action="rebcalc_save_log", demo=kind == "demo",
        state={"acc_filter": ["A"]} if kind == "partial_scope" else {},
        logs=None if kind == "missing_logs" else kind if kind in {"current", "empty"} else "previous",
        save_ok=kind != "save_failed")
    old, new = (run(source, scenario(), **kwargs) for source in sources)
    assert old == new
    saves = [event for event in new[0] if event[0] == "save_monthly_logs"]
    assert bool(saves) == (kind in {"confirmed", "current", "empty", "save_failed"})


def test_completion_and_month_rollover(sources):
    state = {"rebcalc_done_2026-11": {"379810.KS": True, "MSFT": True, "SOXL": True, "ABC": True}}
    for month in ("2026-11", "2026-12"):
        assert run(sources[0], scenario(), state=state, month=month) == run(sources[1], scenario(), state=state, month=month)


@pytest.mark.parametrize("fx", [0., -1., 1300.5])
def test_fx_boundaries_keep_the_same_arithmetic(sources, fx):
    assert run(sources[0], scenario(), fx=fx) == run(sources[1], scenario(), fx=fx)


@pytest.fixture(scope="module")
def original_calculation(sources):
    tree = ast.parse(sources[0])
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == MAIN)
    body = next(n for n in fn.body if isinstance(n, ast.With)).body
    # Exact original filter, denominator, base allocation, redistribution and share/status phases.
    nodes = [deepcopy(n) for n in body if 69 <= n.lineno - fn.lineno <= 74
             or n.lineno - fn.lineno == 80 or 103 <= n.lineno - fn.lineno <= 265]
    multiplier = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_rebcalc_signal_multiplier")
    env = dict(globals())
    exec(compile(ast.Module(body=[multiplier], type_ignores=[]), "<baseline-multiplier>", "exec"), env)
    code = compile(ast.Module(body=nodes, type_ignores=[]), "<baseline-allocation>", "exec")
    return env, code


def calculate_pair(original_calculation, frame, *, total=750000., fx=1400., signals=None,
                   always=(), redistribute=True, accumulated=None, multiplier=None):
    from stock_lab_core.monthly_rebalance import prepare_rebalance_holdings, build_rebalance_plan

    env, code = original_calculation
    env = dict(env, holdings_table=frame, total_invest=total, usdkrw=fx,
        _signal_cache=signals or {}, always_invest_set=set(always), redistribute_mode=redistribute,
        st=SimpleNamespace(session_state={"rebcalc_accum": accumulated or {}}))
    if multiplier is not None:
        env["_rebcalc_signal_multiplier"] = multiplier
    frame_before = frame.copy(deep=True)
    exec(code, env)
    eligible = prepare_rebalance_holdings(frame)
    eligible_before = eligible.copy(deep=True)
    state_before = deepcopy(accumulated)
    result = build_rebalance_plan(eligible, float(eligible["목표비중"].sum()), total, fx,
        signals or {}, set(always), redistribute, accumulated or {}, env["_rebcalc_signal_multiplier"])
    assert freeze(result) == freeze(env["calc_rows"])
    pd.testing.assert_frame_equal(frame, frame_before, check_exact=True)
    pd.testing.assert_frame_equal(eligible, eligible_before, check_exact=True)
    assert accumulated == state_before
    return result


@pytest.mark.parametrize("seed", range(80))
def test_raw_amounts_share_counts_multipliers_and_statuses_are_exact(original_calculation, seed):
    rng = np.random.default_rng(seed)
    frame = scenario()
    frame["현재가"] = rng.choice([0., np.nan, 85., 90., 95., 100., 10000.], len(frame))
    frame["매입가"] = rng.choice([0., 100., 11000.], len(frame))
    frame["목표비중"] = rng.choice(["0", "bad", "10", "20.001", "30", "-1"], len(frame))
    frame.loc[0, "목표비중"] = "40.123456789"
    signals = {ticker: str(rng.choice(["분할 매수", "추세방어", "과열", "소액 1차", "-", "DCA 대기", "150% 적립"]))
        for ticker in ["379810.KS", "MSFT", "SOXL", "ABC"]}
    calculate_pair(original_calculation, frame, signals=signals, always=["MSFT", "SOXL"] if seed % 3 else [],
        redistribute=bool(seed % 2), total=float(rng.choice([0., 1., 1000., 750000., 1000000.])),
        fx=float(rng.choice([1300., 1400.5])), accumulated={"SOXL": float(rng.choice([0., 100., 50000.]))})


@pytest.mark.parametrize("multiplier", [1., 1.004999999, 1.005, 1.005000001, 1.5, 2.])
def test_half_percent_normalization_boundary_is_unchanged(original_calculation, multiplier):
    frame = scenario().iloc[:1].copy()
    result = calculate_pair(original_calculation, frame, total=10000., multiplier=lambda *a, **k: multiplier)
    expected = 10000. * multiplier
    if expected > 10000. * 1.005:
        expected *= 10000. / expected
    assert result[0]["final_alloc"] == expected


def test_target_weights_are_converted_once_without_cross_render_cache(original_calculation):
    from stock_lab_core import monthly_rebalance as core

    env, code = original_calculation
    frame = scenario().iloc[:2].copy()
    frame["목표비중"] = ["40.125", "30.375"]
    with patch.object(core, "clean_float", wraps=clean_float) as converter:
        first = core.prepare_rebalance_holdings(frame)
        core.build_rebalance_plan(first, float(first["목표비중"].sum()), 750000., 1400., {}, set(), True, {}, env["_rebcalc_signal_multiplier"])
        assert [c.args[0] for c in converter.call_args_list].count("40.125") == 1
        assert [c.args[0] for c in converter.call_args_list].count("30.375") == 1
    frame.loc[0, "목표비중"] = "0"
    second = core.prepare_rebalance_holdings(frame)
    assert len(first) == 2 and len(second) == 1


def test_all_extracted_statements_match_baseline_except_target_conversion(sources):
    old = next(n for n in ast.parse(sources[0]).body if isinstance(n, ast.FunctionDef) and n.name == MAIN)
    old_body = next(n for n in old.body if isinstance(n, ast.With)).body
    ranges = {
        "build_base_allocations": (103, 165), "redistribute_allocations": (168, 186),
        "apply_share_counts": (189, 265), "_render_inputs": (31, 62),
        "_select_always_invest": (86, 100), "_refresh_accumulated_state": (269, 277),
        "_render_allocation_table": (289, 320), "_render_budget_summary": (322, 350),
        "_render_accumulation": (353, 399), "_render_leverage": (402, 441),
        "_render_target_shares": (444, 481), "_render_completion": (484, 522),
        "render_monthly_log_panel": (525, 630),
    }
    functions = {}
    for filename in ("monthly_rebalance.py", "monthly_rebalance_view.py", "monthly_rebalance_log.py"):
        for node in ast.parse((ROOT / "stock_lab_core" / filename).read_text(encoding="utf8")).body:
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = node
                assert node.end_lineno - node.lineno + 1 <= 115

    class ExplicitInputs(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == "_rebcalc_signal_multiplier":
                node.id = "signal_multiplier"
            return node

    for name, (start, end) in ranges.items():
        before = [deepcopy(n) for n in old_body if start <= n.lineno - old.lineno <= end]
        after = deepcopy(functions[name].body)
        if isinstance(after[-1], ast.Return):
            after.pop()
        if name == "build_base_allocations":
            before = [ExplicitInputs().visit(n) for n in before]
            loop = next(n for n in before if isinstance(n, ast.For))
            target = next(n for n in loop.body if isinstance(n, ast.Assign)
                          and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "target_w")
            target.value = ast.parse('row.get("목표비중")', mode="eval").body
        if name == "apply_share_counts":
            before[0] = ast.parse("_accum = dict(accumulated)").body[0]
        assert ast.dump(ast.Module(body=before, type_ignores=[])) == ast.dump(
            ast.Module(body=after, type_ignores=[])), name


def test_real_streamlit_calculator_inputs_and_accumulation_buttons():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
from pathlib import Path
import streamlit as st
import pandas as pd
from tests.test_monthly_rebalance_refactor import compiled_functions, scenario
CURRENT_USER_EMAIL = "offline@example.invalid"
IS_PUBLIC_DEMO = True
def save_monthly_logs_db(df):
    raise AssertionError("No persistence is permitted in this smoke test")
exec(compiled_functions(Path("app.py").read_text(encoding="utf-8-sig")), globals())
render_monthly_rebalancing_calculator(scenario(), 1400., {"current_asset": 2000000.},
    pd.DataFrame(columns=["month", "total_invested", "evaluated_value", "dividend"]))
''').run(timeout=30)
    assert not app.exception
    assert app.dataframe and app.metric
    app.number_input(key="rebcalc_monthly_inp").set_value(1000).run()
    assert not app.exception
    app.button(key="rebcalc_accum_add").click().run()
    assert not app.exception
    assert sum(app.session_state["rebcalc_accum"].values()) > 0
    app.button(key="rebcalc_accum_reset").click().run()
    assert not app.exception
    assert app.session_state["rebcalc_accum"] == {}
    assert app.button(key="rebcalc_save_log").disabled
