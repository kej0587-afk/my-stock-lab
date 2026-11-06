"""Exact safety/sizing and complete-result parity against c623569b."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from stock_lab_core import decision_engine
from tests.decision_finalization_reference import (
    ROOT, OUTPUTS, DEPENDENCIES, baseline, final_block, function,
    restore_finalization_for_ast, run_original,
)
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable
from tests.test_decision_refactor_parity import scenarios


def context(code="NEW_ENTRY_LEADER", **updates):
    outcome = decision_engine.build_decision_outcome("original", "#123456", code, reasons=("first", "second"))
    return dict(decision_outcome=outcome, dec=outcome.label, col=outcome.color,
                buy_amount=123456.789, safety_state="GREEN", has_pos=False,
                tech_total=5., main_score=4., adj_tech_score=4.5, weight_gap=3.,
                is_core_dca_allowed=False, is_etf=False, current_dd=-.1,
                indicator_data_issue="", targ_w=10., eff_total=12345678.9,
                cur_p=123.456, ticker="TEST") | updates


CASES = [context(code, **updates) for code in (
    "NEW_ENTRY_LEADER", "LEADER_MA5_PULLBACK_ENTRY", "PANIC_FINAL_DEPLOY", "CORE_STORM_DCA"
) for updates in (
    {}, {"safety_state": "RED"}, {"safety_state": "RED", "has_pos": True},
    {"has_pos": True, "weight_gap": .9999}, {"has_pos": True, "weight_gap": 1., "ticker": "005930.KS"},
    {"is_etf": True}, {"is_etf": True, "is_core_dca_allowed": True},
    {"indicator_data_issue": "fixture issue", "is_etf": True, "is_core_dca_allowed": True},
    {"indicator_data_issue": "fixture issue", "has_pos": True, "safety_state": "RED"},
)] + [context(decision_outcome=None), context(cur_p=0., eff_total=0., targ_w=0.)]


def dependencies(app, calls):
    result = {}
    for name in DEPENDENCIES:
        fn = getattr(app, name)
        def tracked(*args, _fn=fn, _name=name, **kwargs):
            calls.append(_name)
            return _fn(*args, **kwargs)
        result[name] = tracked
    return result


@pytest.mark.parametrize("inputs", CASES)
def test_final_outputs_order_and_nonmutation(app_module, inputs):
    from stock_lab_core.decision_finalization import finalize_decision_sizing
    before, calls = deepcopy(inputs), []
    deps = dependencies(app_module, calls)
    expected = run_original(inputs, deps)
    old_calls = list(calls)
    calls.clear()
    actual = finalize_decision_sizing(**inputs, **deps)
    assert actual == expected
    assert tuple(map(type, actual)) == tuple(map(type, expected))
    assert calls == old_calls
    assert inputs == before
    if inputs["indicator_data_issue"]:
        assert actual[0].code == "DATA_ERROR"
        assert actual[3] == 0.0


def test_only_final_block_changes_and_all_expressions_are_identical():
    from stock_lab_core import decision_finalization
    current = function((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    assert ast.dump(restore_finalization_for_ast(current)) == ast.dump(baseline())
    helper = next(n for n in ast.parse(Path(decision_finalization.__file__).read_text(encoding="utf8")).body
                  if isinstance(n, ast.FunctionDef))
    start, end = final_block(baseline())
    assert ast.dump(ast.Module(body=helper.body[1:-1], type_ignores=[])) == ast.dump(
        ast.Module(body=baseline().body[start:end], type_ignores=[]))
    assert [n.id for n in helper.body[-1].value.elts] == list(OUTPUTS)
    start, end = final_block(current)
    assert end == start + 1
    call = current.body[start].value
    assert not call.args
    assert all(isinstance(k.value, ast.Name) and k.arg == k.value.id for k in call.keywords)
    assert {k.arg for k in call.keywords} == set(context()) | set(DEPENDENCIES)


@pytest.mark.parametrize("data_issue", [False, True])
@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s[0])
def test_full_unrounded_results_and_calls(app_module, monkeypatch, scenario, data_issue):
    from tests.test_decision_inputs_refactor import assert_exact
    sid, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *a: rs)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *a: slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(app_module, "get_sector_flow_state", lambda *a: "fixture flow")
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    if data_issue:
        original = app_module.prepare_decision_price_inputs
        def faulty(*args, **kwargs):
            return original(*args, **kwargs) | {"indicator_data_issue": "fixture issue"}
        monkeypatch.setattr(app_module, "prepare_decision_price_inputs", faulty)
    calls = []
    for name, fn in dependencies(app_module, calls).items():
        monkeypatch.setattr(app_module, name, fn)
    old = deepcopy(baseline())
    env = dict(vars(app_module))
    exec(compile(ast.Module(body=[old], type_ignores=[]), "<original-decision>", "exec"), env)
    untouched = frame.copy(deep=True)
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.
    expected = env[old.name](df=frame, live_price=live, **kwargs)
    old_calls = list(calls)
    calls.clear()
    actual = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    assert_exact(actual, expected)
    assert calls == old_calls
    assert_exact(frame, untouched)
    path = ROOT / "cache" / "decision_finalization_before" / f"{sid}_{int(data_issue)}.json"
    if os.getenv("FREEZE_FINALIZATION_REFERENCE") == "1":
        assert not path.exists(), "Never replace pre-edit outputs"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_to_jsonable(expected), ensure_ascii=False, sort_keys=True, default=str), encoding="utf8")
    elif path.exists():
        assert json.loads(path.read_text(encoding="utf8")) == json.loads(
            json.dumps(_to_jsonable(actual), sort_keys=True, default=str))


def test_new_module_records_loaded_source():
    from stock_lab_core import decision_finalization, report_build
    assert report_build._LOADED[decision_finalization.__name__]["sha256"]


@pytest.mark.parametrize("failed", DEPENDENCIES)
def test_policy_failures_propagate_without_retry(app_module, failed):
    from stock_lab_core.decision_finalization import finalize_decision_sizing
    calls = []
    deps = dependencies(app_module, calls)
    def fail(*args, **kwargs):
        calls.append(failed)
        raise ValueError("fixture failure")
    deps[failed] = fail
    inputs = context(indicator_data_issue="fixture issue")
    with pytest.raises(ValueError, match="fixture failure"):
        run_original(inputs, deps)
    old_calls = list(calls)
    calls.clear()
    with pytest.raises(ValueError, match="fixture failure"):
        finalize_decision_sizing(**inputs, **deps)
    assert calls == old_calls


@pytest.mark.parametrize("stale", [False, True])
def test_new_module_is_in_precision_provenance(app_module, monkeypatch, stale):
    from types import SimpleNamespace
    from stock_lab_core import decision_finalization, precision_build, report_build
    name = decision_finalization.__name__
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
