"""Retained-baseline checks for personal-mode follow-up selection."""

import ast
from copy import deepcopy
from functools import lru_cache
import json
import inspect
from pathlib import Path
import random
import subprocess

import pandas as pd
import pytest

from stock_lab_core import decision_engine, decision_policies
from stock_lab_core import decision_followup
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable
from tests.test_decision_refactor_parity import scenarios
from tests.test_decision_inputs_refactor import restore_inputs_for_ast


ROOT = Path(__file__).resolve().parents[1]
BASE = "bf1302fff6b2b657095d20bea9bc70967029ebdd"


@lru_cache(maxsize=1)
def baseline_function():
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    return function(source)


def function(source):
    return next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "calc_scores_and_decision")


def choice(fn):
    return next(n for n in fn.body if isinstance(n, ast.If)
                and isinstance(n.test, ast.Name) and n.test.id == "is_free")


def restore_followup_for_ast(fn):
    """Reverse just this extraction; older extraction suites retain their scope."""
    fn = restore_inputs_for_ast(fn)
    choice(fn).orelse[1].orelse = deepcopy(choice(baseline_function()).orelse[1].orelse)
    local_helper = next(n for n in baseline_function().body if isinstance(n, ast.FunctionDef)
                        and n.name == "_set_decision")
    fn.body.insert(fn.body.index(choice(fn)), deepcopy(local_helper))
    return fn


def defaults():
    return dict(_fmr=1., adj_tech_score=4., core_dca_context={"core_dca_label": "original DCA"},
        core_dca_rate=.5, cur_p=100., curr_w=1., current_dd=-.1, day_ret=.01,
        day_ret_label="regular", fin_score=4, grade="A급", has_pos=False,
        is_52w_breakout=False, is_breakout_extreme=False, is_breakout_normal=False,
        is_clean_leader_entry=False, is_concentrated_upper_wait=False,
        is_core_dca_allowed=False, is_core_etf=False, is_early_entry=False,
        is_etf=False, is_etf_accumulation_ok=False, is_holding_upper_pullback_wait=False,
        is_quality_recovery_candidate=False, is_quality_recovery_scout=False,
        is_quality_recovery_watch=False, is_stock_add_on_strength=False, is_tdf_or_fund=False,
        live_ref_ret=.01, ma20_now=100., ma5_now=100., mfi_now=50., my_price=100.,
        pct_b_now=.5, price_vs_avg=0., ret_1m=.05, ret_3m=.1, rs_label="🚀강함",
        rs_slope_label="📈RS상승중", rsi_now=50., short_history=False,
        targ_w=10., trend="🚀정배열(상승)", weight_gap=9., history_days=260)


def run_branch(fn, context, namespace=None):
    env = dict(vars(decision_policies), **deepcopy(context))
    env.update(namespace or {})
    # Match the old len(df) without involving data providers.
    env["df"] = range(context["history_days"])
    branch = deepcopy(choice(fn).orelse[1].orelse)
    exec(compile(ast.Module(body=branch, type_ignores=[]), "<followup-selection>", "exec"), env)
    return env["decision_outcome"]


@pytest.fixture(scope="module")
def current():
    source = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    env = {}
    for n in ast.parse(source).body:
        if isinstance(n, ast.ImportFrom) and n.module == "stock_lab_core.decision_followup":
            exec(compile(ast.Module(body=[n], type_ignores=[]), "<followup-import>", "exec"), env)
    return function(source), env


BRANCHES = [
    ({}, None),
    ({"is_core_dca_allowed": True}, None),
    ({"is_core_dca_allowed": True, "short_history": True}, None),
    ({"is_etf": True, "short_history": True, "history_days": 14}, "NEW_ETF_MIN_DATA_WATCH"),
    ({"is_etf": True, "short_history": True, "history_days": 50}, None),
    ({"mfi_now": 85.}, "HARD_BLOCK_MFI_OVERHEAT"),
    ({"is_breakout_extreme": True}, "OVERHEAT_EXTENSION_WAIT_MA5"),
    ({"is_breakout_normal": True}, "LEADER_MA5_PULLBACK_ENTRY"),
    ({"pct_b_now": .95}, "HARD_BLOCK_BOLLINGER_UPPER"),
    ({"pct_b_now": 1.}, "HARD_BLOCK_BOLLINGER_UPPER"),
    ({"pct_b_now": 1.0001}, "HARD_BLOCK_BOLLINGER_UPPER"),
    ({"is_etf": True, "is_etf_accumulation_ok": True, "weight_gap": 10.}, "ETF_LARGE_GAP_DCA_OK"),
    ({"is_etf": True, "is_etf_accumulation_ok": True, "weight_gap": 9.9999}, "ETF_DCA_OK"),
    ({"is_stock_add_on_strength": True}, "STRENGTH_ADD_ON_OK"),
    ({"has_pos": True, "cur_p": 102.}, None),
    ({"has_pos": True, "cur_p": 102.0001}, None),
    ({"has_pos": True, "my_price": 0.}, None),
    ({"has_pos": True, "is_tdf_or_fund": True}, None),
    ({"_fmr": float("nan"), "mfi_now": float("nan"), "pct_b_now": float("nan")}, None),
]


@pytest.mark.parametrize("updates,code", BRANCHES)
def test_every_followup_branch_preserves_outcome_and_reason_order(current, updates, code):
    context = defaults() | updates
    before = deepcopy(context)
    expected = run_branch(baseline_function(), context)
    actual = run_branch(current[0], context, current[1])
    assert actual == expected
    if code:
        assert actual.code == code
    assert context == before


@pytest.mark.parametrize("seed", range(8))
def test_colliding_conditions_threshold_edges_and_nan_preserve_precedence(current, seed):
    rng = random.Random(seed)
    base = defaults()
    flags = [k for k, v in base.items() if isinstance(v, bool)]
    for _ in range(50):
        context = deepcopy(base)
        context.update({k: rng.random() < .2 for k in flags})
        context.update(mfi_now=rng.choice([79.999, 80., 84.999, 85., 90., float("nan")]),
            pct_b_now=rng.choice([.94999, .95, 1., 1.0001, 1.02, float("nan")]),
            rsi_now=rng.choice([50., 65., 70., 75., 80., float("nan")]),
            weight_gap=rng.choice([0., 2.999, 3., 9.999, 10.]),
            cur_p=rng.choice([0., 90., 102., 102.00001, 110.]),
            my_price=rng.choice([0., 100.]), core_dca_rate=rng.choice([0., .25, .5, 1.]),
            _fmr=rng.choice([0., 4.4999, 4.5, 5., float("nan")]))
        assert run_branch(current[0], context, current[1]) == run_branch(baseline_function(), context)


def unrounded(value):
    return json.loads(json.dumps(_to_jsonable(value), sort_keys=True, default=str, allow_nan=False))


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s[0])
def test_full_score_price_amount_sizing_and_decision_output_is_unchanged(app_module, monkeypatch, scenario):
    _, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *a: rs)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *a: slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(app_module, "get_sector_flow_state", lambda *a: "fixture flow")
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    calls = []
    for name in ("apply_live_price_with_indicators", "get_rs_score", "get_rs_slope",
                 "get_auto_benchmark_info", "get_sector_flow_state", "score_technical_components",
                 "score_main_entry", "build_rr_context", "build_position_management_context",
                 "build_entry_signal_context", "build_structure_damage_context",
                 "_apply_safety_state_override", "_compute_sizing_hint", "build_decision_result"):
        original_fn = getattr(app_module, name)
        def counted(*args, _fn=original_fn, _name=name, **options):
            calls.append(_name)
            return _fn(*args, **options)
        monkeypatch.setattr(app_module, name, counted)
    old = deepcopy(baseline_function())
    old.decorator_list = []
    env = dict(vars(app_module))
    exec(compile(ast.Module(body=[old], type_ignores=[]), "<baseline-score-decision>", "exec"), env)
    original = frame.copy(deep=True)
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.
    expected = env[old.name](df=frame, live_price=live, **kwargs)
    expected_calls = list(calls)
    calls.clear()
    actual = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    assert unrounded(actual) == unrounded(expected)
    assert calls == expected_calls
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert frame.attrs == original.attrs


def test_conditions_literals_policy_arguments_and_main_pipeline_are_identical(current):
    source = Path(decision_followup.__file__).read_text(encoding="utf8")
    funcs = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    common = deepcopy(next(n for n in funcs["_select_core_or_technical_signal"].body if isinstance(n, ast.If)))
    position = deepcopy(next(n for n in funcs["select_portfolio_followup_decision"].body
                             if isinstance(n, ast.If) and isinstance(n.test, ast.BoolOp)))
    tail = common
    while tail.orelse:
        tail = tail.orelse[0]
    tail.orelse = [position]

    class ResultOnly(ast.NodeTransformer):
        def visit_Call(self, node):
            if ast.unparse(node) == "len(df)":
                return ast.Name(id="history_days", ctx=ast.Load())
            return self.generic_visit(node)

        def visit_Assign(self, node):
            node = self.generic_visit(node)
            if isinstance(node.targets[0], ast.Tuple):
                if isinstance(node.value, ast.Call):
                    assert node.value.func.id == "_set_decision"
                    node.value.func.id = "build_decision_outcome"
                    return ast.Return(value=node.value)
                return ast.Return(value=ast.Name(id="decision_outcome", ctx=ast.Load()))
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id.startswith("select_"):
                return ast.Return(value=node.value)
            return node

        def visit_If(self, node):
            node = self.generic_visit(node)
            if len(node.body) == 2 and all(isinstance(n, ast.Return) for n in node.body):
                node.body = node.body[:1]
            if len(node.orelse) == 2 and all(isinstance(n, ast.Return) for n in node.orelse):
                node.orelse = node.orelse[:1]
            return node

    old = deepcopy(choice(baseline_function()).orelse[1].orelse[0])
    assert ast.dump(ResultOnly().visit(old)) == ast.dump(common)
    assert ast.dump(restore_followup_for_ast(current[0])) == ast.dump(baseline_function())
    assert set(inspect.signature(decision_followup.select_portfolio_followup_decision).parameters) == set(defaults())
    for fn in funcs.values():
        assert not any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(fn))
        assert not any(isinstance(n, ast.Name) and n.id in {"st", "df", "locals", "supabase"} for n in ast.walk(fn))


@pytest.mark.parametrize("updates,expected", [
    ({"mfi_now": 85., "has_pos": True}, "build_decision_outcome"),
    ({"is_core_dca_allowed": True, "mfi_now": 90.}, "build_core_dca_outcome"),
    ({"is_etf": True, "short_history": True, "mfi_now": 90.}, "build_limited_history_etf_outcome"),
    ({"has_pos": True, "cur_p": 103.}, "select_profitable_holding_decision"),
    ({"has_pos": True, "cur_p": 102.}, "select_holding_decision"),
    ({}, "select_new_entry_decision"),
])
def test_only_the_selected_path_runs_and_outcome_is_built_once(monkeypatch, updates, expected):
    calls = []
    sentinel = decision_engine.build_decision_outcome("fixture", "color", "FIXTURE")
    names = ["build_core_dca_outcome", "build_decision_outcome", "build_limited_history_etf_outcome",
             "select_profitable_holding_decision", "select_holding_decision", "select_new_entry_decision"]
    for name in names:
        def capture(*args, _name=name, **kwargs):
            calls.append(_name)
            return sentinel
        monkeypatch.setattr(decision_followup, name, capture)
    assert decision_followup.select_portfolio_followup_decision(**(defaults() | updates)) is sentinel
    assert calls == [expected]


def test_policy_failure_propagates_without_trying_other_decisions(monkeypatch):
    def failed(*args, **kwargs):
        raise ValueError("selected policy failed")

    def unexpected(**kwargs):
        pytest.fail("Must not fall through after a selected policy failure")

    monkeypatch.setattr(decision_followup, "build_decision_outcome", failed)
    monkeypatch.setattr(decision_followup, "select_new_entry_decision", unexpected)
    with pytest.raises(ValueError, match="selected policy failed"):
        decision_followup.select_portfolio_followup_decision(**(defaults() | {"mfi_now": 85.}))


def test_priority_and_free_mode_skip_followup_selection(app_module, monkeypatch):
    _, prices, rs, slope, kwargs, _ = scenarios()[0]
    frame = make_price_df(**prices)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *a: rs)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *a: slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(app_module, "get_sector_flow_state", lambda *a: "fixture flow")

    def unexpected(**kwargs):
        pytest.fail("Follow-up must not run after a priority decision or in free mode")

    monkeypatch.setattr(app_module, "select_portfolio_followup_decision", unexpected)
    app_module.calc_scores_and_decision(df=frame, **(kwargs | {"is_free": True}))
    app_module.calc_scores_and_decision(df=frame, **(kwargs | {"is_free": False, "fin_score": 0}))


@pytest.mark.parametrize("stale", [False, True])
def test_followup_build_source_is_checked_with_old_cached_module_list(app_module, monkeypatch, stale):
    from types import SimpleNamespace
    from stock_lab_core import precision_build, report_build

    name = decision_followup.__name__
    captured = deepcopy(report_build._LOADED[name])
    if stale:
        captured["sha256"] = "old-import"
    monkeypatch.setattr(report_build, "_LOADED", {name: captured})
    monkeypatch.setattr(report_build, "get_report_build_info", lambda *a: {"sources": {}, "stale_modules": []})
    monkeypatch.setattr(precision_build, "MODULES", ())
    warnings = []
    monkeypatch.setattr(app_module, "st", SimpleNamespace(warning=warnings.append))
    result = app_module.get_precision_build_info()
    assert result["sources"][name]["sha256"] == captured["sha256"]
    assert result["restart_required"] == stale
    assert bool(warnings) == stale
