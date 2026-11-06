"""SMC extraction parity: original expressions, complete results and failure order."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from stock_lab_core import decision_engine, decision_smc
from tests.decision_smc_reference import (
    ROOT, OUTPUTS, DEPENDENCIES, baseline, function, smc_block, restore_smc_for_ast, run_original,
)
from tests.fixtures_price import make_price_df
from tests.test_decision_inputs_refactor import assert_exact
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable
from tests.test_decision_refactor_parity import scenarios


def inputs(app, kind="normal"):
    df = make_price_df(seed=71)
    levels = app.get_recent_levels(df)
    if kind in ("up", "down"):
        sign = 1 if kind == "up" else -1
        df.loc[df.index[-1], "Close"] = levels["ext_high" if sign == 1 else "ext_low"] * (1 + sign * .05)
    elif kind == "nan":
        df.loc[df.index[-1], ["Close", "MA20", "MA50"]] = np.nan
    elif kind in ("empty", "one", "short"):
        df = df.iloc[:{"empty": 0, "one": 1, "short": 20}[kind]].copy()
    elif kind == "missing_column":
        df = df.drop(columns=["Close"])
    elif kind == "missing_level":
        levels = {}
    df.attrs["fixture"] = kind
    return dict(df=df, levels=levels, trend="🚀정배열(상승)", rs_label="🚀강함",
                macd_state="📈추세유지(상승중)", rsi_now=50., mfi_now=50., pct_b_now=.5,
                sqz_status="관망", rs_slope_label="📈RS상승중")


def dependencies(app, calls):
    result = {}
    for name in DEPENDENCIES:
        fn = getattr(app, name)
        def counted(*args, _fn=fn, _name=name, **kwargs):
            calls.append(_name)
            return _fn(*args, **kwargs)
        result[name] = counted
    return result


@pytest.mark.parametrize("kind", ["normal", "up", "down", "nan", "empty", "one", "short", "missing_column", "missing_level"])
def test_real_detectors_outputs_failures_and_inputs_match(app_module, kind):
    ctx = inputs(app_module, kind)
    untouched, calls = deepcopy(ctx), []
    deps = dependencies(app_module, calls)
    try:
        expected = run_original(ctx, deps)
    except Exception as error:
        old_calls = list(calls)
        calls.clear()
        with pytest.raises(type(error)) as actual_error:
            decision_smc.build_decision_smc_context(**ctx, **deps)
        assert str(actual_error.value) == str(error)
    else:
        old_calls = list(calls)
        calls.clear()
        actual = decision_smc.build_decision_smc_context(**ctx, **deps)
        for a, b in zip(actual, expected, strict=True):
            assert_exact(a, b)
        assert tuple(map(type, actual)) == tuple(map(type, expected))
        assert old_calls == list(DEPENDENCIES)
    assert calls == old_calls
    assert_exact(ctx, untouched)


@pytest.mark.parametrize("failed", DEPENDENCIES)
def test_dependency_failure_not_retried_or_hidden(app_module, failed):
    ctx, calls = inputs(app_module), []
    deps = dependencies(app_module, calls)
    def fail(*args, **kwargs):
        calls.append(failed)
        raise ValueError("fixture SMC failure")
    deps[failed] = fail
    with pytest.raises(ValueError, match="fixture SMC failure"):
        run_original(ctx, deps)
    old_calls = list(calls)
    calls.clear()
    with pytest.raises(ValueError, match="fixture SMC failure"):
        decision_smc.build_decision_smc_context(**ctx, **deps)
    assert calls == old_calls


def test_only_assembly_extracted_with_same_expressions_and_wiring(app_module):
    current = function((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    assert ast.dump(restore_smc_for_ast(current)) == ast.dump(baseline())
    helper = next(n for n in ast.parse(Path(decision_smc.__file__).read_text(encoding="utf8")).body
                  if isinstance(n, ast.FunctionDef))
    start, end = smc_block(baseline())
    assert ast.dump(ast.Module(body=helper.body[1:-1], type_ignores=[])) == ast.dump(
        ast.Module(body=baseline().body[start:end], type_ignores=[]))
    assert [n.id for n in helper.body[-1].value.elts] == list(OUTPUTS)
    start, end = smc_block(current)
    assert end == start + 1
    assignment = current.body[start]
    assert [n.id for n in assignment.targets[0].elts] == list(OUTPUTS)
    call = assignment.value
    assert not call.args
    assert all(isinstance(k.value, ast.Name) and k.arg == k.value.id for k in call.keywords)
    assert {k.arg for k in call.keywords} == set(inputs(app_module)) | set(DEPENDENCIES)


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s[0])
def test_full_unrounded_outputs_and_call_order(app_module, monkeypatch, scenario):
    sid, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *a: rs)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *a: slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(app_module, "get_sector_flow_state", lambda *a: "fixture flow")
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    calls = []
    for name, fn in dependencies(app_module, calls).items():
        monkeypatch.setattr(app_module, name, fn)
    old = deepcopy(baseline())
    env = dict(vars(app_module))
    exec(compile(ast.Module(body=[old], type_ignores=[]), "<original-score-decision>", "exec"), env)
    untouched = frame.copy(deep=True)
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.
    expected = env[old.name](df=frame, live_price=live, **kwargs)
    old_calls = list(calls)
    calls.clear()
    actual = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    assert_exact(actual, expected)
    assert calls == old_calls == list(DEPENDENCIES)
    assert_exact(frame, untouched)
    frozen = ROOT / "cache/decision_smc_before.json"
    if frozen.exists():
        assert json.loads(frozen.read_text(encoding="utf8"))[sid] == json.loads(
            json.dumps(_to_jsonable(actual), sort_keys=True, default=str, allow_nan=False))


@pytest.mark.parametrize("stale", [False, True])
def test_loaded_source_provenance(app_module, monkeypatch, stale):
    from types import SimpleNamespace
    from stock_lab_core import precision_build, report_build
    name = decision_smc.__name__
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
