"""C-6/C-11 step 1 (2026-11-26) AST restore helper for frozen-function tests.

``_compute_summary_item`` gained a side channel for the shared decision record: an optional
``_record_sink`` keyword, a read-only copy of the raw engine decision (``engine_view``) and one
``if isinstance(_record_sink, dict)`` block. The returned item is unchanged. This helper removes only
those additions before comparing against the historical AST.
``get_all_summary`` gained a local ``record_sink``, the ``_record_sink=`` keyword and one
``store_today_decision_records`` call; those are removed the same way.
"""
import ast


def _is_record_stmt(node):
    if isinstance(node, ast.ImportFrom) and node.module == "stock_lab_core.decision_record":
        return True
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "engine_view" for t in node.targets):
        return True
    if (isinstance(node, ast.If) and isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Name)
            and node.test.func.id == "isinstance" and node.test.args
            and isinstance(node.test.args[0], ast.Name) and node.test.args[0].id == "_record_sink"):
        return True
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "record_sink":
        return True
    if isinstance(node, ast.Expr) and "store_today_decision_records" in ast.unparse(node):
        return True
    return False


def _strip_get_all_summary(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            node.keywords = [k for k in node.keywords if k.arg != "_record_sink"]
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                setattr(node, field, [s for s in stmts if not _is_record_stmt(s)])
    return fn


def without_decision_record_capture(fn):
    if isinstance(fn, ast.FunctionDef) and fn.name == "get_all_summary":
        return _strip_get_all_summary(fn)
    if not isinstance(fn, ast.FunctionDef) or fn.name != "_compute_summary_item":
        return fn
    args = fn.args
    keep = [i for i, a in enumerate(args.kwonlyargs) if a.arg != "_record_sink"]
    args.kwonlyargs = [args.kwonlyargs[i] for i in keep]
    args.kw_defaults = [args.kw_defaults[i] for i in keep]
    for node in ast.walk(fn):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                setattr(node, field, [s for s in stmts if not _is_record_stmt(s)])
    return fn
