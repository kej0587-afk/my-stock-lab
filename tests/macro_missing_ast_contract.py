"""A-5/A-6 (2026-11-25): undo the reviewed macro-missing edits so older AST contracts still compare.

Removed edits in calc_scores_and_decision:
- macro_risk_observed / macro_missing_components assignments and the `if not finite_num(_fmr)` neutral block
- classify_macro_state(macro_risk_observed) -> classify_macro_state(_fmr)
- the final `if macro_state == "UNKNOWN": mark_macro_unknown_reasons(...)` block
"""
import ast
from copy import deepcopy


def _assigns(node, name):
    return isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
        and node.targets[0].id == name


def _is_macro_if(node):
    if not isinstance(node, ast.If):
        return False
    text = ast.unparse(node.test)
    return text in {"not finite_num(_fmr)", "macro_state == 'UNKNOWN'"}


def before_macro_missing(fn):
    fn = deepcopy(fn)
    fn.body = [n for n in fn.body if not (_assigns(n, "macro_risk_observed") or _assigns(n, "macro_missing_components")
                                          or _is_macro_if(n))]
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "classify_macro_state":
            node.args = [ast.Name(id="_fmr", ctx=ast.Load()) if isinstance(a, ast.Name) and a.id == "macro_risk_observed" else a
                         for a in node.args]
    return fn


def without_macro_missing_key(node):
    """A-5/A-6: drop the additive "매크로누락" row key (diagnostics for the execution gate)."""
    node = deepcopy(node)
    for item in ast.walk(node):
        if isinstance(item, ast.Dict):
            pairs = [(k, v) for k, v in zip(item.keys, item.values)
                     if not (isinstance(k, ast.Constant) and k.value == "매크로누락")]
            item.keys, item.values = [k for k, _ in pairs], [v for _, v in pairs]
    return node
