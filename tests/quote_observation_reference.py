"""Normalize only the reviewed scalar metadata transport in historical AST gates."""

import ast


def before_quote_observation(function):
    pairs = [
        ('observed = load_latest_price(ticker)', None),
        ('latest = clean_float(observed, 0.0)', 'latest = clean_float(load_latest_price(ticker), 0.0)'),
        ('return observed if isinstance(observed, float) else latest', 'return latest'),
        ('observed_close = _fetch_yahoo_regular_close_price(ticker)', None),
        ('regular_close = clean_float(observed_close, 0.0)',
         'regular_close = clean_float(_fetch_yahoo_regular_close_price(ticker), 0.0)'),
        ('return observed_close if isinstance(observed_close, float) else regular_close', 'return regular_close'),
    ]
    replacements = {ast.dump(ast.parse(a).body[0]): ast.parse(b).body[0] if b else None for a,b in pairs}
    seen = []
    class Restore(ast.NodeTransformer):
        def visit(self, node):
            key = ast.dump(node)
            if key in replacements:
                seen.append(key)
                return replacements[key]
            return super().visit(node)
    result = Restore().visit(function)
    assert len(seen) == len(replacements) and set(seen) == set(replacements)
    return result


def before_provider_observation(function):
    """Keep the old provider priority AST; normalize only exact evidence wiring."""
    if function.name == '_fetch_us_realtime_price':
        first = ast.parse('selected = source() or 0.0').body[0]
        second = ast.parse('price = selected if isinstance(selected, QuoteObservation) else float(selected)').body[0]
        seen = []
        class Restore(ast.NodeTransformer):
            def visit_Assign(self, node):
                if ast.dump(node) == ast.dump(first):
                    seen.append('source')
                    return None
                if ast.dump(node) == ast.dump(second):
                    seen.append('scalar')
                    return ast.parse('price = float(source() or 0.0)').body[0]
                return self.generic_visit(node)
        function = Restore().visit(function)
        assert seen == ['source', 'scalar']
    elif function.name == '_fetch_yahoo_chart':
        calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == '_last_candle_close']
        assert len(calls) == 1
        expected = ast.parse('_last_candle_close(result, ticker=ticker, source="yahoo_chart")', mode='eval').body
        assert ast.dump(calls[0]) == ast.dump(expected)
        calls[0].keywords = []
    return function
