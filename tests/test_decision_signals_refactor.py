"""Compare extracted signal stages against the retained pre-refactor function."""

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

from stock_lab_core import decision_engine, decision_signals, precision_build, report_build
from tests.fixtures_price import make_price_df
from tests.test_decision_helpers import _entry_signal_kwargs
from tests.test_decision_inputs_refactor import assert_exact
from tests.test_decision_golden_snapshot import _bench_info
from tests.test_decision_refactor_parity import scenarios


ROOT = Path(__file__).resolve().parents[1]
BASE = "3e872d1f39d288047246aacba240e089e1814d54"
STAGES = (
    "_build_momentum_entry_flags", "_build_pullback_entry_flags",
    "_build_quality_recovery_flags", "_build_structure_and_accumulation_flags",
)


@lru_cache(maxsize=1)
def baseline():
    source = subprocess.check_output(
        ["git", "show", BASE + ":stock_lab_core/decision_engine.py"], cwd=ROOT, encoding="utf8")
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
              and n.name == "build_entry_signal_context")
    env = dict(vars(decision_engine))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<before-signal-refactor>", "exec"), env)
    return fn, env[fn.name]


def check_context(context):
    untouched = deepcopy(context)
    expected = baseline()[1](**context)
    actual = decision_signals.build_entry_signal_context(**context)
    assert list(actual) == list(expected)
    assert_exact(actual, expected)
    assert {k: type(v) for k, v in actual.items()} == {k: type(v) for k, v in expected.items()}
    assert_exact(context, untouched)


def test_original_expressions_order_constants_and_signature_are_preserved():
    funcs = {n.name: n for n in ast.parse(Path(decision_signals.__file__).read_text(encoding="utf8")).body
             if isinstance(n, ast.FunctionDef)}
    original, old_fn = baseline()
    statements = [n for name in STAGES for n in funcs[name].body[1:-1]]
    assert ast.dump(ast.Module(body=statements, type_ignores=[])) == ast.dump(
        ast.Module(body=original.body[1:-1], type_ignores=[]))
    pairs = [(ast.dump(k), ast.dump(v)) for name in STAGES
             for k, v in zip(funcs[name].body[-1].value.keys, funcs[name].body[-1].value.values)]
    assert pairs == [(ast.dump(k), ast.dump(v))
                     for k, v in zip(original.body[-1].value.keys, original.body[-1].value.values)]
    assert inspect.signature(decision_engine.build_entry_signal_context) == inspect.signature(old_fn)
    assert decision_engine.build_entry_signal_context is decision_signals.build_entry_signal_context
    current_app = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    old_app = ast.parse(subprocess.check_output(
        ["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8"))
    for name in ("calc_scores_and_decision", "build_position_management_context"):
        current = next(n for n in current_app.body if isinstance(n, ast.FunctionDef) and n.name == name)
        old = next(n for n in old_app.body if isinstance(n, ast.FunctionDef) and n.name == name)
        if name == "calc_scores_and_decision":
            from tests.decision_finalization_reference import restore_finalization_for_ast
            current = restore_finalization_for_ast(current)
        assert ast.dump(current) == ast.dump(old)


BOUNDARIES = {
    "my_price": [0, 100], "targ_w": [0, 5], "weight_gap": [2, 3, 10],
    "price_vs_avg": [0, .05], "cur_p": [93, 97, 98, 99, 100, 101, 102.5, 105, 120],
    "fin_score": [3, 4], "adj_tech_score": [4, 4.5], "mfi_now": [80, 82, 85],
    "rsi_now": [50, 65, 70, 72, 75], "pct_b_now": [.85, .95, .98, 1, 1.02, 1.03],
    "vol_ratio": [2.5], "macro_risk_value": [4.5],
    "current_dd": [-.12, -.15, -.20, -.35], "ret_1m": [-.08, -.03],
    "ret_3m": [0], "ret_6m": [0], "day_ret": [-.04, 0],
    "ma5_raw": [0, 100], "ma20_now": [0, 100], "ma50_now": [0, 100], "ma120_now": [0, 100],
    "last_macd": [1], "prev_macd": [1.2], "low_now": [101],
}


@pytest.mark.parametrize("field", BOUNDARIES)
def test_threshold_neighbors_nan_and_zero_preserve_all_flags(field):
    values = [math.nan, 0.0]
    for point in BOUNDARIES[field]:
        values.extend([point - 1e-9, point, point + 1e-9])
    for values_profile in (
        {}, {"has_pos": True, "my_price": 100, "price_vs_avg": .03},
        {"fin_score": 3, "current_dd": -.20, "ret_3m": -.05},
        {"is_etf": True, "has_pos": True},
        {"is_etf": True, "has_pos": True, "is_leveraged_or_inverse": True},
    ):
        for value in values:
            check_context(_entry_signal_kwargs(**{**values_profile, field: value}))


def test_combined_flags_and_missing_values_match_for_seeded_cases():
    rng = random.Random(20261102)
    base = _entry_signal_kwargs()
    options = {k: [False, True] for k, v in base.items() if isinstance(v, bool)}
    options.update({k: [math.nan, *v] for k, v in BOUNDARIES.items()})
    options.update(
        trend=["🚀정배열(상승)", "🌊역배열(하락)", "⏳혼조세", "🆕신규상장/자료부족"],
        rs_label=["🚀강함", "➖보통", "🐢약함"],
        rs_slope_label=["📈RS상승중", "📉RS하락중", "➖RS중립"],
        macd_state=["🔥매수신호(골든크로스)", "📈추세유지(상승중)", "📉하락주의(데드크로스)", "⏳추세관망"],
        fvg_info=[{"type": "None", "bottom": None, "top": None},
                  {"type": "Bullish FVG", "bottom": 99, "top": 102},
                  {"type": "Bearish FVG", "bottom": 99, "top": 102},
                  {"type": "Bullish FVG", "bottom": math.nan, "top": None}],
    )
    for _ in range(2000):
        check_context({**base, **{k: rng.choice(v) for k, v in options.items()}})


@pytest.mark.parametrize("fvg", [{}, {"type": "Bullish FVG"},
                                    {"type": "Bullish FVG", "bottom": "bad", "top": 102}])
def test_invalid_fvg_exceptions_are_not_hidden_or_retried(fvg):
    context = _entry_signal_kwargs(fvg_info=fvg)
    with pytest.raises(Exception) as original:
        baseline()[1](**context)
    with pytest.raises(type(original.value)) as current:
        decision_signals.build_entry_signal_context(**context)
    assert str(current.value) == str(original.value)


def test_stages_are_called_once_in_original_order(monkeypatch):
    calls = []
    for name in STAGES:
        original = getattr(decision_signals, name)
        def tracked(*args, _name=name, _fn=original, **kwargs):
            calls.append(_name)
            return _fn(*args, **kwargs)
        monkeypatch.setattr(decision_signals, name, tracked)
    check_context(_entry_signal_kwargs())
    assert calls == list(STAGES)


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s[0])
def test_full_unrounded_decision_result_and_external_calls_match(app_module, monkeypatch, scenario):
    _, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
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
    original_frame = frame.copy(deep=True)
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.
    monkeypatch.setattr(app_module, "build_entry_signal_context", baseline()[1])
    expected = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    previous_calls = list(calls)
    calls.clear()
    monkeypatch.setattr(app_module, "build_entry_signal_context", decision_signals.build_entry_signal_context)
    actual = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    assert_exact(actual, expected)
    assert calls == previous_calls
    pd.testing.assert_frame_equal(frame, original_frame, check_exact=True)
    assert frame.attrs == original_frame.attrs


@pytest.mark.parametrize("stale", [False, True])
def test_new_module_is_tracked_for_cloud_restart(app_module, monkeypatch, stale):
    from types import SimpleNamespace
    name = decision_signals.__name__
    captured = deepcopy(report_build._LOADED[name])
    if stale:
        captured["sha256"] = "previous-import"
    monkeypatch.setattr(report_build, "_LOADED", {name: captured})
    monkeypatch.setattr(report_build, "get_report_build_info", lambda *a: {"sources": {}, "stale_modules": []})
    monkeypatch.setattr(precision_build, "MODULES", ())
    warnings = []
    monkeypatch.setattr(app_module, "st", SimpleNamespace(warning=warnings.append))
    info = app_module.get_precision_build_info()
    assert info["sources"][name]["sha256"] == captured["sha256"]
    assert info["restart_required"] == stale
    assert bool(warnings) == stale


def test_app_import_does_not_reuse_the_previous_engine_binding(monkeypatch):
    source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    imports = [n for n in source.body if isinstance(n, ast.ImportFrom)
               and any(alias.name == "build_entry_signal_context" for alias in n.names)]
    assert len(imports) == 1
    assert imports[0].module == "stock_lab_core.decision_signals"
    monkeypatch.setattr(decision_engine, "build_entry_signal_context", object())
    env = {}
    exec(compile(ast.Module(body=imports, type_ignores=[]), "<cloud-rerun-import>", "exec"), env)
    assert env["build_entry_signal_context"] is decision_signals.build_entry_signal_context
