"""C-1c (2026-11-25) AST restore helper for frozen-function tests.

The Today chain now passes ``ticker=tkr`` to ``apply_precision_mtf_decision_guard`` so the guard can
look up the benchmark regime. ``without_guard_ticker`` removes only that keyword before comparing
against the historical AST.
"""
import ast


def without_guard_ticker(fn):
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "apply_precision_mtf_decision_guard"):
            node.keywords = [k for k in node.keywords if k.arg != "ticker"]
    return fn
