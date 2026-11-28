"""Remove only the opt-in, read-only branch trace from historical engine contracts."""
import ast


def without_observation_capture(fn):
    if not isinstance(fn, ast.FunctionDef) or fn.name != "calc_scores_and_decision":
        return fn
    expected = ast.parse('''
if isinstance(_observation_sink, dict):
    from stock_lab_core.market_guard_observation import capture_decision_branch_trace
    _observation_sink.update(capture_decision_branch_trace(locals()))
''').body[0]
    if fn.args.args[-1].arg == "_observation_sink":
        assert ast.dump(fn.args.defaults[-1]) == ast.dump(ast.Constant(value=None))
        assert sum(ast.dump(n) == ast.dump(expected) for n in fn.body) == 1
        fn.args.args.pop()
        fn.args.defaults.pop()
        fn.body = [n for n in fn.body if ast.dump(n) != ast.dump(expected)]
    return fn
