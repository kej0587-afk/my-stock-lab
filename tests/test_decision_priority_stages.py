"""Differential checks for the staged priority selector, without live services."""

import ast
from copy import deepcopy
from functools import lru_cache
import inspect
import math
from pathlib import Path
import random
import subprocess

import pandas as pd
import pytest

from stock_lab_core import decision_engine, decision_priority
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import _bench_info
from tests.test_decision_inputs_refactor import assert_exact
from tests.test_decision_priority_refactor import defaults, restore_priority_stages_for_ast
from tests.test_decision_refactor_parity import scenarios


ROOT = Path(__file__).resolve().parents[1]
BASE = "16624fdef58509d461785c26ad7592d1e69f6047"
STAGES = (
    "_select_leverage_and_core_priority",
    "_select_recovery_and_drawdown_priority",
    "_select_structure_and_exception_priority",
)
SELECT = decision_priority.select_portfolio_priority_decision


@lru_cache(maxsize=1)
def baseline():
    source = subprocess.check_output(
        ["git", "show", BASE + ":stock_lab_core/decision_priority.py"],
        cwd=ROOT, encoding="utf8",
    )
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == SELECT.__name__)
    namespace = dict(vars(decision_priority))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<before-priority-stages>", "exec"), namespace)
    return node, namespace[node.name]


def check(context):
    original = deepcopy(context)
    expected = baseline()[1](**context)
    actual = SELECT(**context)
    assert actual == expected
    assert type(actual) is type(expected)
    assert_exact(context, original)
    return actual


def test_stage_conditions_bodies_and_public_signature_are_unchanged():
    functions = {n.name: n for n in ast.parse(Path(decision_priority.__file__).read_text(encoding="utf8")).body
                 if isinstance(n, ast.FunctionDef)}
    restored = restore_priority_stages_for_ast(functions)
    assert ast.dump(ast.Module(body=restored, type_ignores=[])) == ast.dump(
        ast.Module(body=baseline()[0].body[1:], type_ignores=[]))
    assert inspect.signature(SELECT) == inspect.signature(baseline()[1])
    # Wiring must forward each original value, not recompute/coerce it.
    calls = [n for n in ast.walk(functions[SELECT.__name__]) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id in STAGES]
    assert [call.func.id for call in calls] == list(STAGES)
    for call in calls:
        assert not call.args
        assert [kw.arg for kw in call.keywords] == list(inspect.signature(getattr(decision_priority, call.func.id)).parameters)
        assert all(isinstance(kw.value, ast.Name) and kw.value.id == kw.arg for kw in call.keywords)


@pytest.mark.parametrize("field,boundaries", [
    ("current_dd", [-.5, -.4, -.3, -.2]), ("_fmr", [0., 4.5]),
    ("cur_p", [0., 102.]), ("curr_w", [0., 10.]),
    ("targ_w", [0., 10.]), ("my_price", [0., 100.]),
    ("fin_score", [1., 2.]), ("pct_b_now", [.95, 1.]),
])
def test_boundaries_and_nan_preserve_branch_precedence(field, boundaries):
    profiles = [
        {}, {"is_etf": True, "is_core_dca_allowed": True},
        {"is_etf": True, "is_leveraged_or_inverse": True},
        {"is_quality_recovery_candidate": True},
        {"is_structure_damage_entry_risk": True, "has_pos": True},
        {"is_exception_entry": True, "has_pos": True},
    ]
    values = [0., math.nan, math.inf, -math.inf]
    values += [v for b in boundaries for v in (math.nextafter(b, -math.inf), b, math.nextafter(b, math.inf))]
    for profile in profiles:
        for value in values:
            check(defaults() | profile | {field: value})


def test_seeded_overlapping_flags_and_none_handoff_match():
    rng = random.Random(20261102)
    base = defaults()
    flags = [k for k, v in base.items() if isinstance(v, bool)]
    for _ in range(2000):
        context = deepcopy(base)
        context.update({k: rng.random() < .3 for k in flags})
        context.update(current_dd=rng.choice([-.6, -.5, -.4, -.3, -.2, -.1, 0., math.nan]),
                       _fmr=rng.choice([0., 1., 4.49, 4.5, math.nan]),
                       curr_w=rng.choice([0., 5., 10., 11.]),
                       fin_score=rng.choice([1, 2, 3, 4]))
        check(context)


@pytest.mark.parametrize("winning_stage", [0, 1, 2, 3, None])
def test_stages_run_once_and_stop_at_first_match(monkeypatch, winning_stage):
    names = ("select_portfolio_guard_decision",) + STAGES
    outcome = decision_engine.DecisionOutcome("fixture", "fixture", "#000000", "caution")
    calls = []
    for i, name in enumerate(names):
        def stage(*, _i=i, _name=name, **kwargs):
            calls.append(_name)
            return outcome if _i == winning_stage else None
        monkeypatch.setattr(decision_priority, name, stage)
    result = SELECT(**defaults())
    assert result is (None if winning_stage is None else outcome)
    assert calls == list(names[:winning_stage + 1] if winning_stage is not None else names)


@pytest.mark.parametrize("updates", [
    {"is_core_dca_allowed": True, "current_dd": -.5, "core_dca_context": {}},
    {"is_leveraged_daily_drop": True, "leveraged_drop_ret": None},
    {"current_dd": None},
])
def test_invalid_input_errors_are_not_swallowed_or_retried(updates):
    context = defaults() | updates
    with pytest.raises(Exception) as previous:
        baseline()[1](**context)
    with pytest.raises(type(previous.value)) as current:
        SELECT(**context)
    assert str(current.value) == str(previous.value)


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda item: item[0])
def test_full_result_and_external_call_order_match(app_module, monkeypatch, scenario):
    _, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
    original_frame = frame.copy(deep=True)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *a: rs)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *a: slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(app_module, "get_sector_flow_state", lambda *a: "fixture flow")
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    calls = []
    for name in ("apply_live_price_with_indicators", "get_rs_score", "get_rs_slope",
                 "get_auto_benchmark_info", "get_sector_flow_state", "build_rr_context",
                 "build_position_management_context", "_compute_sizing_hint"):
        original = getattr(app_module, name)
        def tracked(*args, _fn=original, _name=name, **options):
            calls.append(_name)
            return _fn(*args, **options)
        monkeypatch.setattr(app_module, name, tracked)
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.
    monkeypatch.setattr(app_module, SELECT.__name__, baseline()[1])
    expected = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    previous_calls = list(calls)
    calls.clear()
    monkeypatch.setattr(app_module, SELECT.__name__, SELECT)
    actual = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    assert_exact(actual, expected)
    assert calls == previous_calls
    pd.testing.assert_frame_equal(frame, original_frame, check_exact=True)
    assert frame.attrs == original_frame.attrs
