"""Opt-in offline observation of resolved decision branches, never order approval.

Integration: after finalization, just before build_decision_result(locals()),
update the caller's private sink with capture_decision_branch_trace(locals()).
Do not put that sink in the public operational result. No OHLC/network replay:
features, macro penalties, scores, rates and allocations remain frozen.
"""
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
import hashlib
import inspect
import marshal
import math
from numbers import Integral, Real

from stock_lab_core import decision_engine as engine
from stock_lab_core import decision_finalization as finalization
from stock_lab_core import decision_followup as followup
from stock_lab_core import decision_policies as policies
from stock_lab_core import decision_priority as priority

SCHEMA = "resolved-market-guard/v1"
MARKET_GUARD_CODES = frozenset({"CORE_STORM_DCA", "MACRO_STORM_HOLDING_CAUTION"})
FINAL_CHECKS = (
    "data_freshness", "financial", "target_weight", "structure", "mtf",
    "overheat", "risk_reward", "valuation", "new_etf", "leverage", "l3",
    "sideways_quality", "current_price", "macro", "holding_position",
    "money_flow", "execution_gate", "governance_alignment", "account_budget", "broker_buying_power",
)
_CALLBACKS = {
    "_apply_safety_state_override": engine.apply_safety_state_override,
    "_translate_new_entry_decision_for_holding": engine.translate_new_entry_decision_for_holding,
    "enforce_non_core_panic_scope": engine.observation_non_core_panic_scope,
    "build_decision_outcome": engine.build_decision_outcome,
    "_compute_sizing_hint": engine.compute_sizing_hint,
}


def _encode(value):
    """Strict JSON values; preserve NaN comparisons and tuples on replay."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else {"__float__": repr(number)}
    if isinstance(value, tuple):
        return {"__tuple__": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) or key.startswith("__") for key in value):
            raise TypeError("unsupported mapping key")
        return {key: _encode(item) for key, item in value.items()}
    # Numpy booleans/scalars occur in resolved pandas comparisons.
    if type(value).__module__.startswith("numpy") and hasattr(value, "item"):
        return _encode(value.item())
    raise TypeError("unsupported trace value")


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {"__float__"}:
            return float(value["__float__"])
        if set(value) == {"__tuple__"}:
            return tuple(_decode(item) for item in value["__tuple__"])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


@lru_cache(maxsize=1)
def _implementation_id():
    """Once per process: loaded pure branch dependencies, never network helpers.

    A fresh process recomputes this identity; files changing underneath a loaded
    app cannot relabel the old implementation as new.
    """
    digest = hashlib.sha256()
    pending = [obj for module in (finalization, followup, policies, priority)
               for obj in vars(module).values()
               if inspect.isfunction(obj) and obj.__module__ == module.__name__]
    pending.extend(_CALLBACKS.values())
    pending.append(engine.mark_macro_unknown_reasons)
    seen = {}
    while pending:
        function = pending.pop()
        name = function.__module__ + "." + function.__qualname__
        if name in seen:
            continue
        seen[name] = function
        for key in function.__code__.co_names:
            dependency = function.__globals__.get(key)
            if inspect.isfunction(dependency) and dependency.__module__.startswith("stock_lab_core."):
                pending.append(dependency)
    for name, function in sorted(seen.items()):
        digest.update(name.encode())
        digest.update(marshal.dumps(function.__code__))
    return digest.hexdigest()


def _kwargs(function, resolved, *, exclude=()):
    return {key: resolved[key] for key in inspect.signature(function).parameters if key not in exclude}


def _result(outcome, buy_amount, sizing_hint):
    return {"outcome": asdict(outcome), "buy_amt": buy_amount, "sizing_hint": sizing_hint}


def capture_decision_branch_trace(resolved):
    """Copy only explicit policy inputs from final calc locals; never retain locals.

    Missing/unsupported input disables observation, not the operational result.
    The pre-finalization amount comes from position_context (DATA_ERROR may have
    zeroed the final amount). Account/session objects, OHLC and secrets are absent.
    """
    try:
        context = dict(resolved)
        context["history_days"] = len(resolved["df"])
        is_free = bool(context["is_free"])
        branches = ({"free": _kwargs(policies.select_free_mode_decision, context)} if is_free else {
            "priority": _kwargs(priority.select_portfolio_priority_decision, context),
            "followup": _kwargs(followup.select_portfolio_followup_decision, context),
        })
        final = _kwargs(finalization.finalize_decision_sizing, context,
                        exclude=(*_CALLBACKS, "decision_outcome", "dec", "col"))
        final["buy_amount"] = context["position_context"]["buy_amount"]
        payload = {
            "is_free": is_free, "branches": branches, "finalization": final,
            "macro_state": context["macro_state"],
            "frozen": {key: context[key] for key in (
                "_fmr", "_mp", "adj_tech_score", "main_score", "tech_total",
                "core_dca_rate", "core_dca_context", "cur_p", "eff_total")},
            "expected": _result(context["decision_outcome"], context["buy_amount"], context["sizing_hint"]),
        }
        return {"schema": SCHEMA, "status": "captured", "implementation_id": _implementation_id(),
                "payload": _encode(payload)}
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return {"schema": SCHEMA, "status": "capture_unavailable", "error_type": type(error).__name__,
                "missing_input": str(error.args[0]) if isinstance(error, KeyError) else None}


def _replay(payload, *, skip_market_guard):
    branches = payload["branches"]
    if payload["is_free"]:
        outcome = policies.select_free_mode_decision(**branches["free"])
        route = "free"
    else:
        selector = (priority.select_portfolio_priority_without_market_guard if skip_market_guard
                    else priority.select_portfolio_priority_decision)
        outcome = selector(**branches["priority"])
        route = "priority"
        if outcome is None:
            outcome = followup.select_portfolio_followup_decision(**branches["followup"])
            route = "followup"
    selected = outcome
    outcome, _, _, amount, hint = finalization.finalize_decision_sizing(
        decision_outcome=outcome, dec=outcome.label, col=outcome.color,
        **payload["finalization"], **_CALLBACKS)
    if payload["macro_state"] == "UNKNOWN":
        outcome = engine.mark_macro_unknown_reasons(outcome)
    return _result(outcome, amount, hint), {"route": route, "selected": asdict(selected)}


def observe_market_guard_only(trace, *, final_checks=None, funding=None):
    """Replay normal first, then omit exactly the portfolio storm guard.

    External evidence is retained as recorded_unverified, never promoted to a
    counterfactual pass. Baseline final checks can depend on the original decision
    and must be re-evaluated separately for the hypothetical outcome. Likewise a
    cash/reserve tracker is not broker buying power. This API never authorizes.
    """
    report = {
        "schema": SCHEMA, "status": "unavailable", "baseline_identity": False,
        "execution_allowed": None, "market_only_execution_verified": False,
        "scope": "resolved_features_skip_portfolio_market_guard_only",
        "gaps": ["macro_dependent_features_scores_rates_frozen",
                 "other_macro_dependent_branches_preserved",
                 "counterfactual_final_checks_not_recomputed",
                 "broker_buying_power_and_final_order_cash_unverified"],
        "final_checks": {key: {"status": "unknown"} for key in FINAL_CHECKS},
        "funding": {"status": "unknown", "cash_gap": None},
    }
    try:
        if final_checks is not None:
            report["recorded_final_check_inputs"] = _encode(final_checks)
        for key, value in (final_checks or {}).items():
            if key in report["final_checks"]:
                report["final_checks"][key] = {"status": "recorded_unverified", "evidence": _encode(value)}
        if funding is not None:
            report["funding"]["recorded_evidence"] = _encode(funding)
        if not isinstance(trace, dict) or trace.get("schema") != SCHEMA or trace.get("status") != "captured":
            report["reason"] = "complete_trace_unavailable"
            return report
        if trace.get("implementation_id") != _implementation_id():
            report["reason"] = "implementation_changed"
            return report
        payload = _decode(trace["payload"])
        baseline, baseline_path = _replay(payload, skip_market_guard=False)
        report["baseline"] = _encode(baseline)
        mismatches = [key for key in baseline if _encode(baseline[key]) != _encode(payload["expected"][key])]
        if mismatches:
            report.update(status="baseline_mismatch", mismatches=mismatches)
            return report
        counterfactual, path = _replay(payload, skip_market_guard=True)
        report.update(
            status="observed", baseline_identity=True,
            counterfactual=_encode(counterfactual),
            baseline_path=_encode(baseline_path), counterfactual_path=_encode(path),
            market_guard_removed=(not payload["is_free"] and baseline_path["selected"]["code"] in MARKET_GUARD_CODES),
            changed=_encode(baseline) != _encode(counterfactual),
            frozen=_encode(payload["frozen"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        report.update(status="unavailable", reason="invalid_trace_or_evidence", error_type=type(error).__name__)
    return report
