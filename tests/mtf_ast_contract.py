"""Restore only the optional, unused Today daily snapshot for older AST gates."""
import ast


def before_optional_daily_snapshot(node):
    if node.name == 'build_precision_multi_timeframe_pack':
        for i, arg in enumerate(node.args.kwonlyargs):
            if arg.arg == '_include_daily_snapshot':
                assert ast.dump(node.args.kw_defaults[i]) == ast.dump(ast.Constant(True))
                node.args.kwonlyargs.pop(i)
                node.args.kw_defaults.pop(i)
                break
        class Restore(ast.NodeTransformer):
            def visit_IfExp(self, value):
                if ast.unparse(value.test) == '_include_daily_snapshot':
                    assert ast.unparse(value.body) == "build_precision_timeframe_snapshot('일봉', daily_df)"
                    assert ast.unparse(value.orelse) == '{}'
                    return value.body
                return self.generic_visit(value)
        node = Restore().visit(node)
    if node.name == '_compute_summary_item':
        for value in ast.walk(node):
            if isinstance(value, ast.Call) and ast.unparse(value.func) == 'build_precision_multi_timeframe_pack':
                for keyword in list(value.keywords):
                    if keyword.arg == '_include_daily_snapshot':
                        assert ast.dump(keyword.value) == ast.dump(ast.Constant(False))
                        value.keywords.remove(keyword)
    return node
