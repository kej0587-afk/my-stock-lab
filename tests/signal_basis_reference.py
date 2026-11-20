"""Normalize only reviewed price-provenance arguments in old AST contracts."""

import ast


def before_price_basis_identity(function):
    calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'build_signal_basis']
    assert len(calls) == 1
    call = calls[0]
    expected = ast.parse('build_signal_basis(df, live_context, ticker=tkr, input_price=_live_p)', mode='eval').body
    assert ast.dump(call) == ast.dump(expected)
    call.keywords = []
    return function
