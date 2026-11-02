"""Exact pre-extraction control flow and full decision-output parity."""

import ast
from copy import deepcopy
from functools import lru_cache
import inspect
import json
from pathlib import Path
import random
import subprocess
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_lab_core import decision_engine, decision_policies, decision_priority
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable
from tests.test_decision_refactor_parity import scenarios
from tests.test_decision_followup_refactor import restore_followup_for_ast


ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "9ced3c66"
SELECT = decision_priority.select_portfolio_priority_decision


@lru_cache(maxsize=1)
def old_function():
    source = subprocess.check_output(["git", "show", BASE_COMMIT + ":app.py"], cwd=ROOT, encoding="utf-8")
    return next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                and node.name == "calc_scores_and_decision")


def choice(fn):
    return next(node for node in fn.body if isinstance(node, ast.If)
                and isinstance(node.test, ast.Name) and node.test.id == "is_free")


def cut_priority(fn):
    branch = deepcopy(choice(fn).orelse)
    cursor = branch[1]
    while True:
        tail = cursor.orelse[0]
        if isinstance(tail, ast.If) and isinstance(tail.test, ast.Name) and tail.test.id == "is_core_dca_allowed":
            break
        cursor = tail
    cursor.orelse = [ast.Return(value=ast.Constant(None))]
    return branch, cursor, tail


@lru_cache(maxsize=1)
def old_priority():
    branch, _, _ = cut_priority(old_function())
    actual = next(node for node in ast.parse(Path(decision_priority.__file__).read_text(encoding="utf-8-sig")).body
                  if isinstance(node, ast.FunctionDef) and node.name == SELECT.__name__)
    baseline = ast.FunctionDef(name="baseline_priority", args=deepcopy(actual.args),
        body=[*branch, ast.Return(value=ast.Name(id="decision_outcome", ctx=ast.Load()))], decorator_list=[])
    namespace = dict(vars(decision_policies))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[baseline], type_ignores=[])), "<pre-refactor-priority>", "exec"), namespace)
    return namespace["baseline_priority"]


def defaults():
    return dict(
        _entry_risk_code="STRUCTURE_DAMAGE_NO_ENTRY", _entry_risk_label="entry risk",
        _holding_risk_code="STRUCTURE_DAMAGE_HOLDING_CHECK", _holding_risk_label="holding risk",
        _sd_reasons_t=("original reason",), _single_day_only_entry_risk=False, _fmr=1.,
        core_dca_context={"core_dca_label": "original DCA", "extra": ["preserved"]}, core_dca_rate=1.,
        cur_p=100., curr_w=0., current_dd=-.1, day_ret=.01, fin_score=4, has_pos=False,
        is_core_dca_allowed=False, is_etf=False, is_exception_entry=False,
        is_leveraged_daily_drop=False, is_leveraged_dca_conditional=False, is_leveraged_dca_wait_high=False,
        is_leveraged_or_inverse=False, is_live_gap_shock=False, is_quality_recovery_candidate=False,
        is_quality_recovery_scout=False, is_quality_recovery_watch=False, is_structure_damage_entry_risk=False,
        is_zero_target_holding=False, leveraged_drop_ret=-.1, live_gap_move=-.1, live_price_used=False,
        live_rebound_holding_label="holding rebound", live_rebound_holding_note="holding note",
        live_rebound_label="entry rebound", live_rebound_note="entry note", mfi_now=50., my_price=100.,
        pct_b_now=.5, price_vs_avg=0., ret_1m=.01, rs_label="🚀강함", rsi_now=50., short_history=False,
        targ_w=10., trend="🚀정배열(상승)", weight_gap=10.,
    )


def restore_priority_stages_for_ast(functions):
    """Inline only stage boundaries, retaining every original branch body."""
    public = deepcopy(functions[SELECT.__name__])
    guard_assignment, chain = public.body[1:3]
    assert isinstance(chain.body[-1], ast.Return)
    chain.body.pop()
    cursor = chain
    for name in (
        "_select_leverage_and_core_priority",
        "_select_recovery_and_drawdown_priority",
        "_select_structure_and_exception_priority",
    ):
        stage = deepcopy(functions[name])
        branch = stage.body[0]
        cursor.orelse = [branch]
        cursor = branch
        while len(cursor.orelse) == 1 and isinstance(cursor.orelse[0], ast.If):
            cursor = cursor.orelse[0]
        assert isinstance(cursor.orelse[0], ast.Return)
    return [guard_assignment, chain, stage.body[-1]]


def test_all_moved_conditions_literals_and_order_are_exact_and_fallback_is_untouched():
    source = Path(decision_priority.__file__).read_text(encoding="utf-8-sig")
    functions = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    actual = functions[SELECT.__name__]
    expected, _, fallback = cut_priority(old_function())
    expected.append(ast.Return(value=ast.Name(id="decision_outcome", ctx=ast.Load())))
    restored = restore_priority_stages_for_ast(functions)
    assert ast.dump(ast.Module(body=restored, type_ignores=[])) == ast.dump(ast.Module(body=expected, type_ignores=[]))
    assert set(inspect.signature(SELECT).parameters) == set(defaults())
    assert all(not isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(actual))
    assert not any(isinstance(node, ast.Name) and node.id in {"st", "df", "supabase", "locals"} for node in ast.walk(actual))

    current = next(node for node in ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig")).body
                   if isinstance(node, ast.FunctionDef) and node.name == "calc_scores_and_decision")
    # Follow-up extraction has its own exact AST and full-output parity suite.
    current = restore_followup_for_ast(current)
    new_choice = choice(current)
    current_fallback = new_choice.orelse[1].orelse[0]
    assert ast.dump(current_fallback) == ast.dump(fallback)
    original_prefix, last, _ = cut_priority(old_function())
    last.orelse = [current_fallback]
    new_choice.orelse = original_prefix
    assert ast.dump(current) == ast.dump(old_function())


@pytest.mark.parametrize("updates,code", [
    ({}, None), ({"fin_score": 1}, "HARD_BLOCK_FINANCIAL_F"),
    ({"curr_w": 11.}, "HARD_BLOCK_OVERWEIGHT"), ({"curr_w": 10.}, "HARD_BLOCK_TARGET_FILLED"),
    ({"is_zero_target_holding": True}, "TARGET_ZERO_NO_ADD"),
    ({"_fmr": 4.5}, "MACRO_STORM_HOLDING_CAUTION"),
    ({"_fmr": 4.5, "is_core_dca_allowed": True}, "CORE_STORM_DCA"),
    ({"is_leveraged_daily_drop": True}, "LEVERAGED_DAILY_DROP_NO_ADD"),
    ({"is_leveraged_dca_wait_high": True}, "LEVERAGED_DCA_OVERHEAT_PASS"),
    ({"is_leveraged_dca_conditional": True}, "LEVERAGED_DCA_CONDITIONAL"),
    ({"is_core_dca_allowed": True, "current_dd": -.5}, "PANIC_FINAL_DEPLOY"),
    ({"is_core_dca_allowed": True, "current_dd": -.4}, "PANIC_CASH_DEPLOY"),
    ({"is_core_dca_allowed": True, "current_dd": -.3}, "CORE_CRASH_DCA"),
    ({"is_core_dca_allowed": True, "current_dd": -.2}, "CORE_DRAWDOWN_DCA"),
    ({"is_leveraged_or_inverse": True, "current_dd": -.5}, "LEVERAGED_RECOVERY_DCA_BLOCK"),
    ({"is_quality_recovery_candidate": True, "current_dd": -.5}, "QUALITY_RECOVERY_CANDIDATE"),
    ({"is_quality_recovery_scout": True}, "QUALITY_RECOVERY_SCOUT"),
    ({"is_quality_recovery_watch": True}, "QUALITY_RECOVERY_WATCH"),
    ({"current_dd": -.5}, "STOCK_PANIC_CAUSE_CHECK"),
    ({"current_dd": -.4, "is_etf": True}, "NON_CORE_ETF_DRAWDOWN_CAUSE_CHECK"),
    ({"current_dd": -.3}, "STOCK_CRISIS_CAUSE_CHECK"),
    ({"is_live_gap_shock": True}, "LIVE_GAP_SHOCK_WAIT"),
    ({"is_live_gap_shock": True, "has_pos": True}, "LIVE_GAP_SHOCK_HOLDING_CHECK"),
    ({"is_structure_damage_entry_risk": True}, "STRUCTURE_DAMAGE_NO_ENTRY"),
    ({"is_structure_damage_entry_risk": True, "has_pos": True}, "STRUCTURE_DAMAGE_HOLDING_CHECK"),
    ({"current_dd": -.2, "has_pos": True, "is_structure_damage_entry_risk": True}, "DRAWDOWN_20_HOLDING_STOP_CHECK"),
    ({"current_dd": -.2, "has_pos": True, "_single_day_only_entry_risk": True}, "DRAWDOWN_20_HOLDING_CAUSE_CHECK"),
    ({"current_dd": -.2}, "DRAWDOWN_20_NO_ENTRY"),
    ({"live_price_used": True, "is_exception_entry": True}, "PREMARKET_REBOUND_WAIT"),
    ({"live_price_used": True, "is_exception_entry": True, "has_pos": True}, "PREMARKET_REBOUND_HOLDING_WAIT"),
    ({"is_exception_entry": True, "has_pos": True}, "EXCEPTION_ADD_ON"),
    ({"is_exception_entry": True}, "EXCEPTION_ENTRY"),
    ({"is_exception_entry": True, "has_pos": True, "cur_p": 103.}, None),
    ({"current_dd": float("nan"), "_fmr": float("nan")}, None),
])
def test_priority_branches_and_handoff_preserve_pre_refactor_result(updates, code):
    context = defaults() | updates
    original = deepcopy(context)
    actual = SELECT(**context)
    assert actual == old_priority()(**context)
    assert (actual.code if actual else None) == code
    assert context["core_dca_context"] == original["core_dca_context"]


def test_randomized_priority_collisions_and_threshold_neighbors_match_original():
    randomizer = random.Random(20261101)
    base = defaults()
    flags = [key for key, value in base.items() if isinstance(value, bool)]
    for _ in range(300):
        context = deepcopy(base)
        context.update({key: randomizer.random() < .18 for key in flags})
        context.update(_fmr=randomizer.choice([1., 4.499999, 4.5, 5.]),
            current_dd=randomizer.choice([-.500001, -.5, -.499999, -.4, -.399999, -.3, -.299999, -.2, -.199999, 0.]),
            curr_w=randomizer.choice([0., 5., 10., 12.]), targ_w=randomizer.choice([0., 10., 20.]),
            fin_score=randomizer.choice([1, 2, 4]), cur_p=randomizer.choice([99., 102., 102.0001, 103.]))
        original = deepcopy(context)
        assert SELECT(**context) == old_priority()(**context)
        assert context == original


@pytest.mark.parametrize("stale", [False, True])
def test_priority_source_is_included_even_with_a_cached_old_metadata_list(app_module, monkeypatch, stale):
    from stock_lab_core import precision_build, report_build

    name = decision_priority.__name__
    captured = deepcopy(report_build._LOADED[name])
    if stale:
        captured["sha256"] = "old-import-hash"
    monkeypatch.setattr(report_build, "_LOADED", {name: captured})
    monkeypatch.setattr(report_build, "get_report_build_info", lambda *args: {"sources": {}, "stale_modules": []})
    monkeypatch.setattr(precision_build, "MODULES", ())
    warnings = []
    monkeypatch.setattr(app_module, "st", SimpleNamespace(warning=warnings.append))
    result = app_module.get_precision_build_info()
    assert result["sources"][name]["sha256"] == captured["sha256"]
    assert result["restart_required"] == stale
    assert bool(warnings) == stale


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda item: item[0])
def test_full_unrounded_output_matches_frozen_pre_extraction_function(app_module, monkeypatch, scenario):
    _, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *args: rs)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *args: slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *args: _bench_info())
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    old = deepcopy(old_function())
    old.decorator_list = []
    namespace = dict(vars(app_module))
    exec(compile(ast.Module(body=[old], type_ignores=[]), "<pre-refactor-decision>", "exec"), namespace)
    original = frame.copy(deep=True)
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.
    expected = namespace[old.name](df=frame, live_price=live, **kwargs)
    actual = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    normalize = lambda value: json.loads(json.dumps(_to_jsonable(value), sort_keys=True, default=str, allow_nan=False))
    assert normalize(actual) == normalize(expected)
    pd.testing.assert_frame_equal(frame, original)
