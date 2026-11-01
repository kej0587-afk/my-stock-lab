"""Exercise the actual entry block without UI, credentials or provider calls."""

import ast
from contextlib import nullcontext
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_lab_core import performance


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "7e67afba"


def _baseline_nodes():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:app.py"], cwd=ROOT).decode("utf-8-sig")
    nodes = ast.parse(source).body
    start = next(i for i, n in enumerate(nodes) if isinstance(n, ast.Assign)
                 and isinstance(n.targets[0], ast.Tuple)
                 and getattr(n.targets[0].elts[0], "id", None) == "macro_res")
    end = next(i for i in range(start, len(nodes)) if isinstance(nodes[i], ast.Assign)
               and getattr(nodes[i].targets[0], "id", None) == "total_eval")
    return nodes[start:end + 1]


def _instrumented_nodes():
    nodes = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig")).body
    start = next(i for i, n in enumerate(nodes) if isinstance(n, ast.With)
                 and any(isinstance(item.context_expr, ast.Call)
                         and getattr(item.context_expr.func, "id", None) == "PerformanceTrace"
                         for item in n.items))
    return nodes[start:start + 2]


def _without_timing(nodes):
    result = []
    for node in nodes:
        if isinstance(node, ast.With):
            assert len(node.items) in {1, 2}
            assert node.items[0].context_expr.func.id in {"PerformanceTrace", "measure"}
            if len(node.items) == 2:
                expected = ast.parse('getattr(_entry_price_loader, "realtime_quote_scope", nullcontext)()', mode="eval").body
                assert ast.dump(node.items[1].context_expr, include_attributes=False) == ast.dump(expected, include_attributes=False)
                assert node.items[0].context_expr.args[1].value == "entry_holdings_table"
            result.extend(_without_timing(node.body))
        else:
            result.append(node)
    return result


def test_entry_business_ast_is_identical_before_and_after_timing():
    expected = ast.Module(body=_baseline_nodes(), type_ignores=[])
    actual = ast.Module(body=_without_timing(_instrumented_nodes()[:1]), type_ignores=[])
    assert ast.dump(actual, include_attributes=False) == ast.dump(expected, include_attributes=False)


def _run(nodes, *, demo=False, fail_at=None):
    now = [0.0]
    calls = []
    traces = []
    state = {}
    holdings = pd.DataFrame({"account_type": ["ordinary", "pension"]})
    table = pd.DataFrame({"value": [12.0]})

    def callback(name, result, seconds):
        def run(*args):
            calls.append(name)
            now[0] += seconds
            if name == fail_at:
                raise SystemExit("entry interrupted")
            return result
        return run

    def trace_factory(**kwargs):
        trace = performance.PerformanceTrace(clock=lambda: now[0], **kwargs)
        traces.append(trace)
        return trace

    namespace = {
        "PerformanceTrace": trace_factory, "measure": performance.measure,
        "_entry_price_loader": SimpleNamespace(), "nullcontext": nullcontext,
        "IS_PUBLIC_DEMO": demo, "app_mode_label": "test", "pd": pd,
        "st": SimpleNamespace(session_state=state, caption=lambda *a: None,
                              warning=lambda *a: None, info=lambda *a: None),
        "get_macro_analysis": callback("macro", ({}, 3.0, 0.5, 100.0), 0.8),
        "get_public_demo_macro_analysis": callback("demo_macro", ({}, 1.0, 0.0, 90.0), 0.1),
        "build_macro_event_risk_table": callback("events", (pd.DataFrame(), 0.5, 2), 0.1),
        "load_settings_db": callback("settings", {"seed_money": 100.0, "usdkrw": 1300.0}, 0.05),
        "load_holdings_db": callback("holdings", holdings, 0.05),
        "load_dividends_db": callback("dividends", pd.DataFrame(), 0.05),
        "load_monthly_logs_db": callback("monthly", pd.DataFrame(), 0.05),
        "load_usdkrw_rate": callback("fx", 1400.0, 0.3),
        "render_refresh_control_panel": callback("refresh", None, 0.0),
        "build_holdings_table": callback("table", table, 12.0),
        "calc_portfolio_summary": callback("portfolio", {"current_asset": 1234.0}, 0.01),
    }
    error = None
    try:
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    except SystemExit as exc:
        error = exc
    return namespace, calls, traces, error


@pytest.mark.parametrize("demo", [False, True])
def test_instrumented_entry_keeps_calls_state_and_values(demo):
    baseline, calls, _, error = _run(_baseline_nodes(), demo=demo)
    current, new_calls, traces, new_error = _run(_instrumented_nodes(), demo=demo)
    assert error is new_error is None
    assert new_calls == calls
    for key in ("total_eval", "usdkrw", "usdkrw_source", "effective_settings", "final_macro_risk", "macro_event_risk"):
        assert current[key] == baseline[key]
    assert set(current["st"].session_state) == set(baseline["st"].session_state)
    for key, value in baseline["st"].session_state.items():
        if isinstance(value, pd.DataFrame):
            pd.testing.assert_frame_equal(current["st"].session_state[key], value)
        else:
            assert current["st"].session_state[key] == value
    report = current["ENTRY_INITIALIZATION_PERFORMANCE"]
    assert report == traces[0].report()
    assert report["measurement_status"] == "completed"
    assert {f["name"] for f in report["functions"]} == {
        "entry_macro", "entry_events", "entry_settings", "entry_holdings",
        "entry_dividends", "entry_monthly_logs", "entry_fx", "entry_holdings_table", "entry_portfolio",
    }
    assert next(f for f in report["functions"] if f["name"] == "entry_holdings_table")["total_seconds"] == pytest.approx(12.0)
    assert performance._trace.get() is None


@pytest.mark.parametrize("fail_at", ["holdings", "refresh", "table"])
def test_entry_interrupt_does_not_leak_trace_or_hide_error(fail_at):
    baseline, calls, _, error = _run(_baseline_nodes(), fail_at=fail_at)
    current, new_calls, traces, new_error = _run(_instrumented_nodes(), fail_at=fail_at)
    assert type(error) is type(new_error) is SystemExit
    assert new_calls == calls
    assert "total_eval" not in current and "total_eval" not in baseline
    assert traces[0].report()["measurement_status"] == "interrupted"
    assert performance._trace.get() is None


def test_today_attempt_attaches_entry_to_its_own_measurement_only():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    renderer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_today_queue_tab")
    final = next(n.finalbody for n in renderer.body if isinstance(n, ast.Try) and n.finalbody)
    start = next(i for i, n in enumerate(final) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", None) == "entry_timing")
    nodes = final[start:start + 2]
    entry = {"measurement_id": "entry-one", "elapsed_seconds": 12.0}
    ns = {"attempt": {}, "before_today_seconds": 17.0, "ENTRY_INITIALIZATION_PERFORMANCE": entry}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), ns)
    assert ns["attempt"] == {"entry_initialization": entry, "other_before_today_seconds": 5.0}
    ns.pop("ENTRY_INITIALIZATION_PERFORMANCE")
    ns["attempt"] = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), ns)
    assert ns["attempt"] == {}
