"""Exact retained-baseline checks for price/technical input preparation."""

import ast
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import decision_engine, decision_inputs, ta_engine
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable
from tests.test_decision_refactor_parity import scenarios


ROOT = Path(__file__).resolve().parents[1]
BASE = "01c5a522d75c59ce5a43c5e4dda5da1574c1cff9"
PRICE_KEYS = (
    "df", "last", "prev", "indicator_data_issue", "daily_close", "cur_p",
    "live_price_used", "ret_1m", "ret_3m", "ret_6m", "regular_day_ret",
    "live_ref_ret", "day_ret", "day_ret_label", "live_gap_move",
)
TECH_KEYS = (
    "trend", "macd_state", "rt_macd_label", "rsi_now", "mfi_now", "pct_b_now",
    "rs_label", "rs_slope_val", "rs_slope_label", "rs_slope_s", "sqz_status",
    "rs_s", "mfi_s", "trend_s", "macd_s", "sqz_s", "tech_total",
)


def function(source):
    return next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "calc_scores_and_decision")


@lru_cache(maxsize=1)
def baseline_function():
    return function(subprocess.check_output(
        ["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8"))


def restore_inputs_for_ast(fn):
    """Allow older extraction suites to inspect their unchanged downstream code."""
    from tests.decision_finalization_reference import restore_finalization_for_ast
    fn = restore_finalization_for_ast(fn)
    for first, end, start_old, end_old in (
        ("price_inputs", "live_rebound_context", 4, 26),
        ("technical_inputs", "tactical_price_context", 35, 53),
    ):
        names = [n.targets[0].id if isinstance(n, ast.Assign)
                 and isinstance(n.targets[0], ast.Name) else "" for n in fn.body]
        start, stop = names.index(first), names.index(end)
        fn.body[start:stop] = deepcopy(baseline_function().body[start_old:end_old])
    return fn


def assert_exact(actual, expected):
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
    elif isinstance(expected, pd.Series):
        pd.testing.assert_series_equal(actual, expected, check_exact=True)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_exact(actual[key], expected[key])
    elif isinstance(expected, float) and np.isnan(expected):
        assert np.isnan(actual)
    else:
        assert actual == expected


def run_old_stage(start, end, context, keys):
    env = dict(vars(decision_engine))
    env.update(vars(ta_engine))
    env.update(context)
    exec(compile(ast.Module(body=deepcopy(baseline_function().body[start:end]),
                            type_ignores=[]), "<original-input-stage>", "exec"), env)
    return {key: env[key] for key in keys}


@pytest.mark.parametrize("days", [1, 2, 14, 20, 21, 60, 61, 120, 121, 260])
@pytest.mark.parametrize("mode", ["close", "live", "prepared", "failed", "missing_close"])
def test_price_input_parity_for_history_live_prepared_failure_and_nan(monkeypatch, days, mode):
    df = make_price_df().tail(days).copy(deep=True)
    df.attrs["source_date"] = str(df.index[-1])
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: df.index[-1])
    live = float(df.Close.iloc[-1]) * 1.02 if mode in {"live", "prepared", "failed"} else 0.
    prepared = None
    if mode == "missing_close":
        df.loc[df.index[-1], "Close"] = np.nan
    if mode in {"prepared", "failed"}:
        prepared = (df.copy(deep=True), False, "indicator failure" if mode == "failed" else "")
    context = dict(df=df, ticker="TEST", live_price=live, _live_indicator_context=prepared,
                   build_indicators=ta_engine.build_indicators,
                   apply_live_price_with_indicators=decision_engine.apply_live_price_with_indicators)
    original = df.copy(deep=True)
    expected = run_old_stage(4, 26, context, PRICE_KEYS)
    actual = decision_inputs.prepare_decision_price_inputs(**context)
    assert_exact(actual, expected)
    assert_exact(df, original)
    if prepared:
        assert actual["df"] is not prepared[0]
        assert_exact(prepared[0], original)


@pytest.mark.parametrize("empty", [None, pd.DataFrame()])
def test_empty_input_error_is_unchanged(empty):
    context = dict(df=empty, ticker="TEST", live_price=0., _live_indicator_context=None,
                   build_indicators=ta_engine.build_indicators,
                   apply_live_price_with_indicators=decision_engine.apply_live_price_with_indicators)
    with pytest.raises(ValueError) as old:
        run_old_stage(4, 26, context, PRICE_KEYS)
    with pytest.raises(type(old.value), match=str(old.value)):
        decision_inputs.prepare_decision_price_inputs(**context)


@pytest.mark.parametrize("macd_pair", [(1., 2.), (2., 1.), (1., 1.), (np.nan, 1.), (1., np.nan)])
@pytest.mark.parametrize("missing", [False, True])
def test_technical_values_call_order_nan_and_missing_squeeze_are_unchanged(macd_pair, missing):
    df = make_price_df()
    df.loc[df.index[-2:], "MACD"] = list(macd_pair)
    if missing:
        df = df.drop(columns=["SQZ_NEAR", "SQZ_ON"], errors="ignore")
        df.loc[df.index[-1], ["RSI", "MFI", "%B"]] = np.nan
    calls = []
    def rs(*args):
        calls.append(("rs", args))
        return 2, "🚀강함"
    def slope(*args):
        calls.append(("slope", args))
        return .01, "📈RS상승중", 1
    def score(*args):
        calls.append(("score", args))
        return decision_engine.score_technical_components(*args)
    context = dict(df=df, last=df.iloc[-1], prev=df.iloc[-2], ticker="TEST", asset_class="us_stock",
                   get_rs_score=rs, get_rs_slope=slope, score_technical_components=score)
    original = df.copy(deep=True)
    expected = run_old_stage(35, 53, context, TECH_KEYS)
    old_calls = list(calls)
    calls.clear()
    actual = decision_inputs.prepare_decision_technical_inputs(**context)
    assert_exact(actual, expected)
    # Arguments can contain NaN; compare their unchanged serialization.
    assert repr(calls) == repr(old_calls)
    assert [name for name, _ in calls] == ["rs", "slope", "score"]
    assert_exact(df, original)


def test_input_exceptions_are_not_swallowed_or_retried():
    frame = make_price_df()
    def fail(*args):
        raise RuntimeError("RS unavailable")
    def unexpected(*args):
        pytest.fail("No downstream call after a failed input")
    with pytest.raises(RuntimeError, match="RS unavailable"):
        decision_inputs.prepare_decision_technical_inputs(
            frame, frame.iloc[-1], frame.iloc[-2], "TEST", "us_stock",
            get_rs_score=fail, get_rs_slope=unexpected, score_technical_components=unexpected)


def test_only_input_extraction_and_reused_row_reads_changed():
    source = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    current = function(source)
    assert ast.dump(restore_inputs_for_ast(current)) == ast.dump(baseline_function())
    helpers = {n.name: n for n in ast.parse(Path(decision_inputs.__file__).read_text(encoding="utf8")).body
               if isinstance(n, ast.FunctionDef)}
    class ReusedReads(ast.NodeTransformer):
        def visit_Name(self, node):
            reused = {"last_macd": 'last["MACD"]', "prev_macd": 'prev["MACD"]',
                      "last_sig": 'last["MACD_Sig"]', "prev_sig": 'prev["MACD_Sig"]'}
            if isinstance(node.ctx, ast.Load) and node.id in reused:
                return ast.parse(reused[node.id], mode="eval").body
            return node
    for name, start, end in (("prepare_decision_price_inputs", 4, 26),
                              ("prepare_decision_technical_inputs", 35, 53)):
        body = deepcopy(helpers[name].body[1:-1])  # docstring and explicit result mapping
        if name == "prepare_decision_price_inputs":
            daily = next(n for n in body if isinstance(n, ast.Assign)
                         and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "daily_close")
            daily.value.orelse = ast.parse('float(df.iloc[-1]["Close"])', mode="eval").body
        else:
            body = [n for n in body if not (isinstance(n, ast.Assign)
                    and isinstance(n.targets[0], ast.Tuple)
                    and ast.unparse(n.targets[0]) == "(last_macd, last_sig, prev_macd, prev_sig)")]
            body = [ReusedReads().visit(n) for n in body]
        assert ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(
            ast.Module(body=baseline_function().body[start:end], type_ignores=[]))


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s[0])
def test_full_unrounded_output_and_provider_calls_match_baseline(app_module, monkeypatch, scenario):
    _, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *a: rs)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *a: slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(app_module, "get_sector_flow_state", lambda *a: "fixture flow")
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    calls = []
    for name in ("apply_live_price_with_indicators", "get_rs_score", "get_rs_slope",
                 "score_technical_components", "get_auto_benchmark_info", "get_sector_flow_state",
                 "build_rr_context", "score_main_entry", "build_decision_result"):
        original_fn = getattr(app_module, name)
        def counted(*args, _fn=original_fn, _name=name, **options):
            calls.append(_name)
            return _fn(*args, **options)
        monkeypatch.setattr(app_module, name, counted)
    old = deepcopy(baseline_function())
    old.decorator_list = []
    env = dict(vars(app_module))
    exec(compile(ast.Module(body=[old], type_ignores=[]), "<before-input-refactor>", "exec"), env)
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.
    expected = env[old.name](df=frame, live_price=live, **kwargs)
    expected_calls = list(calls)
    calls.clear()
    actual = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    def normalize(value):
        return json.loads(json.dumps(_to_jsonable(value), sort_keys=True, default=str, allow_nan=False))
    assert normalize(actual) == normalize(expected)
    assert calls == expected_calls


@pytest.mark.parametrize("stale", [False, True])
def test_input_module_build_mismatch_requires_restart(app_module, monkeypatch, stale):
    from types import SimpleNamespace
    from stock_lab_core import precision_build, report_build
    name = decision_inputs.__name__
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

