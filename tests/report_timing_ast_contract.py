"""Remove only reviewed measurement calls for immutable older app contracts."""
import ast
from copy import deepcopy


def before_report_timing(node):
    if node.name not in {'render_today_market_memo_panel', '_collect_today_report_context'}:
        return node

    class Restore(ast.NodeTransformer):
        def visit_ImportFrom(self, value):
            if value.module == 'stock_lab_core.report_generation_performance':
                assert all(x.name in {'render_generation_timing', 'generation_measurement',
                                     'set_report_stage', 'component', 'report_degraded'} for x in value.names)
                return None
            return value

        def visit_Expr(self, value):
            call = value.value
            if isinstance(call, ast.Call) and ast.unparse(call.func) in {'set_report_stage', 'report_degraded', 'render_generation_timing'}:
                return None
            return self.generic_visit(value)

        def visit_Call(self, value):
            if ast.unparse(value.func) == 'component':
                assert ast.unparse(value.args[0]) in {'load_credit_spread', 'load_investor_flow_evidence',
                    'collect_public_flow_backfill', 'load_public_market_evidence', 'update_report_history'}
                value.func, value.args = value.args[0], value.args[1:]
            return self.generic_visit(value)

        def visit_If(self, value):
            if ast.unparse(value.test) == 'auto_generate':
                for i, stmt in enumerate(value.body):
                    if isinstance(stmt, ast.With) and any(isinstance(item.context_expr, ast.Call)
                        and ast.unparse(item.context_expr.func) == 'generation_measurement' for item in stmt.items):
                        assert ast.unparse(value.body[i + 1]) == 'st.rerun()'
                        stmt.body.append(value.body.pop(i + 1))
                        stmt.items = [item for item in stmt.items if ast.unparse(item.context_expr.func) != 'generation_measurement']
                        break
            return self.generic_visit(value)

    return Restore().visit(deepcopy(node))
