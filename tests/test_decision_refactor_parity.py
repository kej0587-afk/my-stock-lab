"""Full-output snapshots and structural checks for policy extraction."""

import ast
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core import decision_engine
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import SCENARIOS, _bench_info, _to_jsonable


ROOT = Path(__file__).parents[1]
SNAPSHOT_PATH = ROOT / "tests/golden/decision_refactor_full_snapshots.json"
STRUCTURE_PATH = ROOT / "tests/golden/decision_policy_structure.json"
EXTRA_CASES = [
    ("live_new_stock", {"live_gap": 0.02}),
    ("live_held_profit", {"has_pos": True, "my_price": 75.0, "is_free": False, "live_gap": 0.02}),
    ("live_held_loss", {"has_pos": True, "my_price": 150.0, "is_free": False, "live_gap": 0.02}),
    ("zero_target_holding", {"has_pos": True, "my_price": 100.0, "user_curr_w": 3.0, "user_targ_w": 0.0, "is_free": False}),
    ("below_storm_boundary", {"_final_macro_risk": 4.499, "is_free": False}),
    ("at_storm_boundary", {"_final_macro_risk": 4.5, "is_free": False}),
    ("short_history_etf", {"is_etf": True, "ticker": "TEST_ETF", "asset_class": "us_etf", "days": 30}),
    ("free_short_core", {"is_etf": True, "ticker": "QQQM", "asset_class": "us_etf_nasdaq", "days": 30}),
]


def scenarios():
    cases = [(sid, dict(px), rs, slope, dict(kwargs), 0.0) for sid, px, rs, slope, kwargs in SCENARIOS]
    _, base_prices, rs, slope, base_kwargs = SCENARIOS[0]
    for i, (sid, updates) in enumerate(EXTRA_CASES):
        updates = dict(updates)
        px = dict(base_prices, seed=60 + i)
        px["days"] = updates.pop("days", 260)
        live_gap = updates.pop("live_gap", 0.0)
        cases.append((sid, px, rs, slope, {**base_kwargs, **updates}, live_gap))
    assert len(cases) == 20
    return cases


def run_scenario(app, monkeypatch, scenario):
    _, prices, rs, slope, kwargs, live_gap = scenario
    frame = make_price_df(**prices)
    monkeypatch.setattr(app, "get_rs_score", lambda *a: rs)
    monkeypatch.setattr(app, "get_rs_slope", lambda *a: slope)
    monkeypatch.setattr(app, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.0
    original = frame.copy(deep=True)
    result = app.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    pd.testing.assert_frame_equal(frame, original)
    return json.loads(json.dumps(_to_jsonable(result), sort_keys=True, default=str, allow_nan=False))


def test_full_output_snapshots(app_module, monkeypatch):
    actual = {scenario[0]: run_scenario(app_module, monkeypatch, scenario) for scenario in scenarios()}
    if os.getenv("CREATE_DECISION_REFACTOR_BASELINE") == "1":
        assert not SNAPSHOT_PATH.exists(), "Never overwrite the pre-refactor baseline"
        SNAPSHOT_PATH.write_text(json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert actual == expected


class NormalizePolicy(ast.NodeTransformer):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "df":
            return ast.Name(id="history_days", ctx=ast.Load())
        return self.generic_visit(node)

    def visit_If(self, node):
        node = self.generic_visit(node)
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.Return) and isinstance(node.orelse[0].value, ast.Constant) and node.orelse[0].value.value is None:
            node.orelse = []
        return node


def policy_hash(statements):
    tree = NormalizePolicy().visit(ast.Module(body=statements, type_ignores=[]))
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode("utf-8")).hexdigest()


def test_extracted_policies_preserve_all_original_conditions_and_literals():
    path = ROOT / "stock_lab_core/decision_policies.py"
    assert path.exists()
    expected = json.loads(STRUCTURE_PATH.read_text(encoding="utf-8"))
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in expected}
    assert found == set(expected), "An extracted policy disappeared"
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in expected:
            body = [statement for statement in node.body if isinstance(statement, ast.If)]
            assert policy_hash(body) == expected[node.name], node.name
            assert all(not isinstance(statement, (ast.Global, ast.Nonlocal)) for statement in ast.walk(node))


@pytest.mark.parametrize("updates,code", [
    ({}, None),
    ({"fin_score": 1, "curr_w": 20}, "HARD_BLOCK_FINANCIAL_F"),
    ({"is_zero_target_holding": True, "curr_w": 20}, "TARGET_ZERO_NO_ADD"),
    ({"curr_w": 11, "_fmr": 5}, "HARD_BLOCK_OVERWEIGHT"),
    ({"curr_w": 10}, "HARD_BLOCK_TARGET_FILLED"),
    ({"_fmr": 4.499}, None),
    ({"_fmr": 4.5}, "MACRO_STORM_HOLDING_CAUTION"),
    ({"is_etf": True, "is_core_dca_allowed": True, "_fmr": 4.5}, "CORE_STORM_DCA"),
])
def test_portfolio_guard_priority_and_unmatched_handoff(updates, code):
    from stock_lab_core.decision_policies import select_portfolio_guard_decision

    context = {"is_etf": False, "fin_score": 4, "is_zero_target_holding": False,
               "curr_w": 0.0, "targ_w": 10.0, "_fmr": 1.0, "is_core_dca_allowed": False,
               "core_dca_context": {"core_dca_label": "Original DCA"}, "core_dca_rate": 1.0,
               "short_history": False, **updates}
    original = dict(context["core_dca_context"])
    outcome = select_portfolio_guard_decision(**context)
    assert (outcome.code if outcome else None) == code
    assert context["core_dca_context"] == original
