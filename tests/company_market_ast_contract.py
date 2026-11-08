"""Undo only the reviewed, display-only company context arguments for old gates."""
import ast
from copy import deepcopy


def before_company_market_context(node):
    from tests.report_timing_ast_contract import before_report_timing
    node = before_report_timing(node)
    node = deepcopy(node)
    if node.name != 'render_today_market_memo_panel':
        return node
    class Restore(ast.NodeTransformer):
        def visit_ImportFrom(self, value):
            if value.module == 'stock_lab_core.sec_cash_recovery':
                assert [(x.name,x.asname) for x in value.names] == [('collect_cash_release',None)]
                return None
            if value.module == 'stock_lab_core.portfolio_market_review':
                assert [(x.name,x.asname) for x in value.names] == [('select_market_review',None)]
                return None
            return value

        def visit_Call(self, value):
            for kw in list(value.keywords):
                if ast.unparse(value.func) == 'render_company_deep_dive' and kw.arg == 'cash_release_loader':
                    expected = 'lambda packet: collect_cash_release(packet, fetch_json=sec_request_json, user_agent=get_sec_user_agent())'
                    assert ast.dump(kw.value) == ast.dump(ast.parse(expected,mode='eval').body)
                    value.keywords.remove(kw)
                if ast.unparse(value.func) == 'dict' and kw.arg == 'sector':
                    expected = "SECTOR_BENCHMARK_MAP.get(normalize_ticker(item['ticker']), SECTOR_BENCHMARK_MAP.get(clean_symbol(item['ticker']), ()))"
                    assert ast.dump(kw.value) == ast.dump(ast.parse(expected,mode='eval').body)
                    value.keywords.remove(kw)
                if ast.unparse(value.func) == 'render_company_deep_dive' and kw.arg == 'market_context':
                    expected = 'lambda: select_market_review(st.session_state, portfolio_signal_input_context())'
                    assert ast.dump(kw.value) == ast.dump(ast.parse(expected,mode='eval').body)
                    value.keywords.remove(kw)
            return self.generic_visit(value)
    return Restore().visit(node)
