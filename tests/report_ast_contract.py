"""Normalize only the approved Nov08 report collection addition for old contracts."""
import ast


def before_msft_cash_report(node):
    from tests.report_timing_ast_contract import before_report_timing
    node = before_report_timing(node)
    from tests.mtf_ast_contract import before_optional_daily_snapshot
    node = before_optional_daily_snapshot(node)
    if node.name == 'render_today_market_memo_panel':
        node.body = [s for s in node.body if not (
            isinstance(s, ast.ImportFrom) and s.module == 'stock_lab_core.company_deep_dive'
            or isinstance(s, ast.If) and isinstance(s.test, ast.Compare)
            and isinstance(s.test.left, ast.Call)
            and ast.unparse(s.test.left.func) == 'st.radio'
            and s.test.left.args and isinstance(s.test.left.args[0], ast.Constant)
            and s.test.left.args[0].value == '시황 보기')]
    if node.name == '_collect_today_report_context':
        node.body = [s for s in node.body if not (
            isinstance(s, ast.ImportFrom) and s.module == 'stock_lab_core.report_msft_cash'
            or isinstance(s, ast.With) and ast.unparse(s.items[0].context_expr)
            == "measure('external_data', 'msft_cash_evidence')")]
    if node.name == '_generate_today_briefing_market_memo':
        for value in ast.walk(node):
            if isinstance(value, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == 'report_context' for k in value.keys):
                pairs = list(zip(value.keys, value.values))
                pairs.sort(key=lambda p: 1 if p[0].value == 'now' else 2 if p[0].value == 'report_context' else 0)
                value.keys, value.values = map(list, zip(*pairs))
    return node
