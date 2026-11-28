"""Fixed-input decision replay; no account data, network or golden updates."""
import ast
from copy import deepcopy
from dataclasses import asdict
import inspect
import json

import pytest

from stock_lab_core import decision_engine as engine
from stock_lab_core import decision_priority as priority
from stock_lab_core import market_guard_observation as observation
from tests.test_decision_priority_refactor import defaults
from tests.test_decision_refactor_parity import run_scenario, scenarios


def capture_scenario(app, monkeypatch, scenario):
    captured = {}
    build = app.build_decision_result

    def record(context):
        captured.update(observation.capture_decision_branch_trace(context))
        return build(context)

    with monkeypatch.context() as patch:
        patch.setattr(app, "build_decision_result", record)
        actual = run_scenario(app, patch, scenario)
    assert captured["status"] == "captured", captured
    # The durable representation must preserve nonfinite values and tuples.
    return actual, json.loads(json.dumps(captured, allow_nan=False))


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda value: value[0])
def test_original_decision_and_amount_match_replay(app_module, monkeypatch, scenario):
    ordinary = run_scenario(app_module, monkeypatch, scenario)
    actual, trace = capture_scenario(app_module, monkeypatch, scenario)
    assert actual == ordinary  # no operational keys/values or caller frame change
    original = deepcopy(trace)
    report = observation.observe_market_guard_only(trace)
    assert report["status"] == "observed", json.dumps(report, ensure_ascii=True)
    assert report["baseline_identity"] is True
    assert report["baseline"]["outcome"]["code"] == actual["decision_code"]
    assert report["baseline"]["buy_amt"] == actual["buy_amt"]
    assert report["baseline"]["sizing_hint"] == actual["sizing_hint"]
    assert report["execution_allowed"] is None
    assert report["market_only_execution_verified"] is False
    assert report["funding"] == {"status": "unknown", "cash_gap": None}
    assert trace == original
    serialized = json.dumps(trace)
    assert "supabase" not in serialized and '"df"' not in serialized


@pytest.mark.parametrize("updates,code", [
    ({"fin_score": 1}, "HARD_BLOCK_FINANCIAL_F"),
    ({"is_zero_target_holding": True}, "TARGET_ZERO_NO_ADD"),
    ({"curr_w": 11}, "HARD_BLOCK_OVERWEIGHT"),
    ({"curr_w": 10}, "HARD_BLOCK_TARGET_FILLED"),
    ({"is_structure_damage_entry_risk": True}, "STRUCTURE_DAMAGE_NO_ENTRY"),
    ({"is_leveraged_daily_drop": True}, "LEVERAGED_DAILY_DROP_NO_ADD"),
    ({"current_dd": -.5}, "STOCK_PANIC_CAUSE_CHECK"),
])
def test_only_market_guard_removed_independent_blocks_preserved(updates, code):
    context = defaults() | {"_fmr": 5.0} | updates
    original = deepcopy(context)
    assert priority.select_portfolio_priority_without_market_guard(**context).code == code
    assert context == original


@pytest.mark.parametrize("fmr", [0., 4.499999, float("nan")])
def test_below_boundary_or_unknown_does_not_change_selection(fmr):
    context = defaults() | {"_fmr": fmr, "is_structure_damage_entry_risk": True}
    assert (priority.select_portfolio_priority_without_market_guard(**context)
            == priority.select_portfolio_priority_decision(**context))


def test_storm_core_guard_only_removed_rate_context_and_fmr_preserved():
    context = defaults() | {"_fmr": 4.5, "is_core_dca_allowed": True, "current_dd": -.5}
    original = deepcopy(context)
    assert priority.select_portfolio_priority_decision(**context).code == "CORE_STORM_DCA"
    assert priority.select_portfolio_priority_without_market_guard(**context).code == "PANIC_FINAL_DEPLOY"
    assert context == original


def test_replay_stage_order_is_exact_operational_order():
    operational = ast.parse(inspect.getsource(priority.select_portfolio_priority_decision))
    stages = [node.func.id for node in ast.walk(operational)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.startswith("_select_")]
    observer = ast.parse(inspect.getsource(priority.select_portfolio_priority_without_market_guard))
    loop = next(node for node in ast.walk(observer) if isinstance(node, ast.For))
    assert stages == [node.id for node in loop.iter.elts]


@pytest.mark.parametrize("is_etf", [False, True])
@pytest.mark.parametrize("is_core", [False, True])
@pytest.mark.parametrize("dd", [-.500001, -.5, -.499999, -.4, -.399999, -.3, 0., float("nan")])
def test_pure_panic_finalization_matches_original(app_module, is_etf, is_core, dd):
    for code, label in [("PANIC_FINAL_DEPLOY", ""), ("PANIC_CASH_DEPLOY", ""),
                        ("CRISIS_CORE_FOCUS", ""), ("OTHER", "최종투입"),
                        ("OTHER", "현금 투입"), ("OTHER", "코어 집중"), ("OTHER", "ordinary")]:
        outcome = engine.build_decision_outcome(label, "#000", code)
        kwargs = dict(is_core_dca_allowed=is_core, is_etf=is_etf, current_dd=dd)
        assert engine.observation_non_core_panic_scope(outcome, **kwargs) == app_module.enforce_non_core_panic_scope(outcome, **kwargs)


def test_missing_trace_and_inputs_cannot_report_allowed():
    trace = observation.capture_decision_branch_trace({"secret": "must not retain"})
    assert trace["status"] == "capture_unavailable"
    assert "must not retain" not in str(trace)
    for value in (None, {}, trace):
        report = observation.observe_market_guard_only(value)
        assert report["status"] == "unavailable"
        assert "counterfactual" not in report
        assert report["execution_allowed"] is None


def test_baseline_mismatch_version_drift_and_external_evidence_fail_closed(app_module, monkeypatch):
    _, trace = capture_scenario(app_module, monkeypatch, scenarios()[0])
    bad = deepcopy(trace)
    bad["payload"]["expected"]["buy_amt"] += 1
    report = observation.observe_market_guard_only(bad)
    assert report["status"] == "baseline_mismatch"
    assert report["mismatches"] == ["buy_amt"]
    assert "counterfactual" not in report
    bad = deepcopy(trace)
    bad["implementation_id"] = "old"
    assert observation.observe_market_guard_only(bad)["reason"] == "implementation_changed"
    report = observation.observe_market_guard_only(trace,
        final_checks={key: {"passed": True} for key in observation.FINAL_CHECKS},
        funding={"cash": 100000, "reserve": 100000, "currency": "KRW"})
    assert report["execution_allowed"] is None
    assert report["funding"]["cash_gap"] is None
    assert report["funding"]["status"] == "unknown"
    assert all(item["status"] == "recorded_unverified" for item in report["final_checks"].values())


def test_data_error_zero_amount_and_macro_unknown_finalize_preserved(app_module, monkeypatch):
    _, trace = capture_scenario(app_module, monkeypatch, scenarios()[0])
    payload = observation._decode(trace["payload"])
    payload["finalization"]["indicator_data_issue"] = "fixed data gap"
    payload["macro_state"] = "UNKNOWN"
    # Independent operational finalizer supplies the expected DATA_ERROR result.
    selected = engine.build_decision_outcome("any", "#000", "EXCEPTION_ENTRY")
    result = app_module.finalize_decision_sizing(
        decision_outcome=selected, dec=selected.label, col=selected.color,
        **payload["finalization"],
        _apply_safety_state_override=app_module._apply_safety_state_override,
        _translate_new_entry_decision_for_holding=app_module._translate_new_entry_decision_for_holding,
        enforce_non_core_panic_scope=app_module.enforce_non_core_panic_scope,
        build_decision_outcome=app_module.build_decision_outcome,
        _compute_sizing_hint=app_module._compute_sizing_hint)
    payload["expected"] = {"outcome": asdict(result[0]), "buy_amt": result[3], "sizing_hint": result[4]}
    trace["payload"] = observation._encode(payload)
    report = observation.observe_market_guard_only(trace)
    assert report["baseline_identity"] is True
    assert report["counterfactual"]["buy_amt"] == 0
    assert report["counterfactual"]["outcome"]["code"] == "DATA_ERROR"


def test_parent_opt_in_sink_is_private_and_replay_is_network_free(app_module, monkeypatch):
    import socket

    scenario = scenarios()[17]  # exact storm boundary, portfolio mode
    ordinary = run_scenario(app_module, monkeypatch, scenario)
    sid, prices, rs, slope, kwargs, live_gap = scenario
    sink = {}
    actual = run_scenario(app_module, monkeypatch,
                          (sid, prices, rs, slope, kwargs | {"_observation_sink": sink}, live_gap))
    assert actual == ordinary
    assert sink["status"] == "captured"
    assert "branch_trace" not in actual and "_observation_sink" not in actual

    def no_network(*args, **kwargs):
        pytest.fail("Resolved branch observation must not fetch external data")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    report = observation.observe_market_guard_only(sink)
    assert report["baseline_identity"] is True
    assert report["market_guard_removed"] is True
    assert report["frozen"]["_fmr"] == 4.5


def test_implementation_hash_is_cached_and_survives_json_capture():
    before = observation._implementation_id.cache_info()
    first = observation._implementation_id()
    assert first == observation._implementation_id()
    after = observation._implementation_id.cache_info()
    assert after.misses - before.misses <= 1
    assert after.hits > before.hits


def test_skipping_guard_does_not_neutralize_later_macro_condition():
    from tests.test_decision_followup_refactor import defaults as followup_defaults
    from tests.test_decision_finalization_refactor import context as final_context

    final = final_context()
    for key in ("decision_outcome", "dec", "col"):
        final.pop(key)
    payload = {
        "is_free": False, "macro_state": "STORM", "finalization": final,
        "branches": {
            "priority": defaults() | {"_fmr": 5., "rsi_now": 60.},
            "followup": followup_defaults() | {"_fmr": 5., "rsi_now": 60.},
        },
    }
    frozen = deepcopy(payload)
    storm, path = observation._replay(payload, skip_market_guard=True)
    assert path["route"] == "followup"
    neutral = deepcopy(payload)
    for branch in neutral["branches"].values():
        branch["_fmr"] = 0.
    neutral_result, _ = observation._replay(neutral, skip_market_guard=True)
    assert neutral_result["outcome"]["code"] == "QUALITY_PULLBACK_ENTRY"
    assert storm["outcome"]["code"] != neutral_result["outcome"]["code"]
    assert payload == frozen
