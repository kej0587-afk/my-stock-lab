"""Retained original SMC assembly for exact parity and older AST contracts."""
import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "11565166"
OUTPUTS = ("smc_structure_labels", "ext_structure", "int_structure", "int_event", "ext_event",
           "liq_state", "fvg_info", "pd_zone", "smc_action", "smc_insight")
DEPENDENCIES = ("build_smc_structure_labels", "detect_structure_event", "detect_liquidity_grab",
                "detect_recent_fvg", "get_pd_zone", "summarize_smc_action", "build_smc_insight")


def function(source):
    return next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "calc_scores_and_decision")


@lru_cache
def baseline():
    return function(subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8"))


def smc_block(fn):
    start = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                 and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                 and n.value.func.id in ("build_smc_structure_labels", "build_decision_smc_context"))
    end = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "position_context")
    return start, end


def restore_smc_for_ast(fn):
    fn = deepcopy(fn)
    start, end = smc_block(fn)
    old_start, old_end = smc_block(baseline())
    fn.body[start:end] = deepcopy(baseline().body[old_start:old_end])
    return fn


def run_original(inputs, dependencies):
    env = dict(inputs) | dependencies
    start, end = smc_block(baseline())
    exec(compile(ast.Module(body=deepcopy(baseline().body[start:end]), type_ignores=[]),
                 "<original-smc-context>", "exec"), env)
    return tuple(env[k] for k in OUTPUTS)
