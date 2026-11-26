"""C-6/C-11 step 2 (2026-11-26) AST restore helper for frozen-engine tests.

``calc_scores_and_decision`` changed only the defaults of ``user_curr_w`` and ``user_targ_w`` from 0.0 to
None, so weights a caller passes explicitly win over the global account table (app screens pass none and
still read the selected account's row). This helper puts the old 0.0 defaults back before comparing.
"""
import ast


def restore_weight_defaults(fn):
    if not isinstance(fn, ast.FunctionDef) or fn.name != "calc_scores_and_decision":
        return fn
    args = fn.args.args
    offset = len(args) - len(fn.args.defaults)
    for i, arg in enumerate(args):
        if arg.arg in ("user_curr_w", "user_targ_w") and i >= offset:
            default = fn.args.defaults[i - offset]
            if isinstance(default, ast.Constant) and default.value is None:
                fn.args.defaults[i - offset] = ast.Constant(value=0.0)
    return fn
