"""Reverse only the reviewed guard input repair for older extraction contracts."""
import ast
from copy import deepcopy


def before_guard_input_repair(node):
    if node.name not in {'get_macro_analysis', '_today_benchmark_guard_stats', 'build_today_market_guard'}:
        return node
    node = deepcopy(node)
    removals = {
        'get_macro_analysis': [
            'for info in results.values():\n    info["guard_macro_base"] = storm_count + macro_trend + move_score\n    info["guard_event_risk"] = event_risk'],
        '_today_benchmark_guard_stats': ['from stock_lab_core.market_basis import unique_guard_benchmarks'],
        'build_today_market_guard': [
            'flow_calc = pd.DataFrame()',
            'from stock_lab_core.market_basis import guard_macro_input, guard_input_dates',
            'macro_input = guard_macro_input(globals().get("macro_res", {}), macro_risk)',
            'macro_risk = macro_input["risk"]',
            'input_dates = guard_input_dates(flow_calc, globals().get("macro_res", {}))'],
    }
    exact = {ast.dump(ast.parse(s).body[0]) for s in removals[node.name]}
    replacement = ast.dump(ast.parse('valid_df, excluded_duplicates = unique_guard_benchmarks(valid_df)').body[0])
    body = []
    for statement in node.body:
        dump = ast.dump(statement)
        if dump in exact:
            continue
        if node.name == '_today_benchmark_guard_stats' and dump == replacement:
            statement = ast.parse('valid_df = valid_df.copy() if isinstance(valid_df, pd.DataFrame) else pd.DataFrame()').body[0]
        body.append(statement)
    node.body = body
    fields = {
        '_today_benchmark_guard_stats': {
            'benchmark_tickers': 'valid_df["티커"].astype(str).tolist() if "티커" in valid_df else []',
            'excluded_duplicate_tickers': 'excluded_duplicates'},
        'build_today_market_guard': {'input_dates': 'input_dates', 'macro_risk_input': 'macro_input'},
    }.get(node.name, {})
    for statement in node.body:
        if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Dict):
            continue
        pairs = []
        for key, value in zip(statement.value.keys, statement.value.values):
            if isinstance(key, ast.Constant) and key.value in fields:
                assert ast.dump(value) == ast.dump(ast.parse(fields[key.value], mode='eval').body)
            else:
                pairs.append((key, value))
        statement.value.keys = [key for key, _ in pairs]
        statement.value.values = [value for _, value in pairs]
    return node
