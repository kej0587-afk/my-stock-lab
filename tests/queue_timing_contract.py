"""Ignore only the reviewed presentation timers in historical policy contracts."""
import ast

QUEUE_PHASES = {
    "queue_financial_revision", "queue_restore_summary", "queue_finalize_summary",
    "queue_observation_prepare", "queue_display_prepare", "queue_observation_reuse",
    "queue_record_gate_sync",
}


class StripQueueTimers(ast.NodeTransformer):
    def visit_With(self, node):
        self.generic_visit(node)
        if len(node.items) == 1:
            call = node.items[0].context_expr
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "measure" and not call.keywords
                    and len(call.args) == 2 and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == "phase" and isinstance(call.args[1], ast.Constant)
                    and call.args[1].value in QUEUE_PHASES and node.items[0].optional_vars is None):
                return node.body
        return node
