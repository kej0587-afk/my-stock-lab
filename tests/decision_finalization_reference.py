"""Immutable reference for the final safety/sizing extraction (no live providers)."""
import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "c623569b"
OUTPUTS = ("decision_outcome", "dec", "col", "buy_amount", "sizing_hint")
DEPENDENCIES = ("_apply_safety_state_override", "_translate_new_entry_decision_for_holding",
                "enforce_non_core_panic_scope", "build_decision_outcome", "_compute_sizing_hint")


def function(source):
    return next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "calc_scores_and_decision")


@lru_cache
def baseline():
    return function(subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8"))


def final_block(fn):
    start = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                 and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Name)
                 and n.value.func.id in ("_apply_safety_state_override", "finalize_decision_sizing"))
    return start, len(fn.body) - 1


def restore_finalization_for_ast(fn):
    fn = deepcopy(fn)
    start, end = final_block(fn)
    old_start, old_end = final_block(baseline())
    fn.body[start:end] = deepcopy(baseline().body[old_start:old_end])
    return fn


def run_original(context, dependencies):
    env = deepcopy(context) | dependencies
    start, end = final_block(baseline())
    exec(compile(ast.Module(body=deepcopy(baseline().body[start:end]), type_ignores=[]),
                 "<original-finalization>", "exec"), env)
    return tuple(env[key] for key in OUTPUTS)
