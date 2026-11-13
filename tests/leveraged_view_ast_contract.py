"""Undo only the reviewed display adapter; retain immutable decision baselines."""

import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess


@lru_cache(maxsize=1)
def original_watch_block():
    source = subprocess.check_output(
        ["git", "show", "21428d1b:app.py"],
        cwd=Path(__file__).resolve().parents[1], encoding="utf-8-sig")
    function = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == "render_leveraged_etf_precision_panel")
    return next(n for n in function.body if isinstance(n, ast.With)
                and "기초축/대표 프록시 확인" in ast.unparse(n.items[0].context_expr))


def before_leveraged_product_view(node):
    if node.name in {"build_leveraged_precision_watch_rows", "build_leveraged_precision_state"}:
        node = deepcopy(node)
        if node.name == "build_leveraged_precision_watch_rows" and len(node.args.args) == 2:
            assert node.args.args[-1].arg == "comparison_ticker"
            assert len(node.args.defaults) == 1 and ast.literal_eval(node.args.defaults[0]) == ""
            node.args.args.pop()
            node.args.defaults.pop()
            guard = ast.parse('''if comparison_ticker and not getattr(watch_loader, "SESSION_COMPARISON_VERSION", ""):
    st.warning("레버리지 비교 모듈 갱신 대기 · 비교값 사용 보류. Cloud 앱 재시작이 필요합니다.")
    return []''').body[0]
            node.body = [value for value in node.body if ast.dump(value) != ast.dump(guard)]
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            target = ast.unparse(call.func)
            allowed = {"batch_builder", "build_leveraged_watch_rows"} if node.name == "build_leveraged_precision_watch_rows" else {"build_leveraged_precision_watch_rows"}
            if target not in allowed:
                continue
            kept = []
            for keyword in call.keywords:
                if keyword.arg == "comparison_profile":
                    assert node.name == "build_leveraged_precision_watch_rows" and ast.unparse(keyword.value) == "profile_key"
                elif keyword.arg == "comparison_ticker":
                    assert ast.unparse(keyword.value) == ("comparison_ticker" if node.name == "build_leveraged_precision_watch_rows" else "ticker")
                else:
                    kept.append(keyword)
            call.keywords = kept
        return node
    if node.name not in {"render_precision_candlestick_chart", "render_leveraged_etf_precision_panel"}:
        return node
    if not any(isinstance(n, ast.ImportFrom) and n.module == "stock_lab_core.leveraged_product_view" for n in node.body):
        return node
    node = deepcopy(node)
    body = []
    for value in node.body:
        text = ast.unparse(value)
        if isinstance(value, ast.ImportFrom) and value.module == "stock_lab_core.leveraged_product_view":
            assert [(a.name, a.asname) for a in value.names] in [
                [("channel_basis_note", None)], [("render_product_basis", None), ("render_watch_basis", None)]]
            continue
        if text == "leverage_basis_note = channel_basis_note(ticker)":
            continue
        if text == "if leverage_basis_note:\n    st.caption(leverage_basis_note)":
            continue
        if isinstance(value, ast.If) and ast.unparse(value.test) == "not render_product_basis(st, ticker)":
            assert not value.orelse and len(value.body) == 1
            body.extend(value.body)  # Its original markup remains checked against Git.
            continue
        if text == "render_watch_basis(st, ticker, state.get('watch_rows_raw', []))":
            body.append(deepcopy(original_watch_block()))
            continue
        if text == "dca_stage = state.get('dca_stage', '')":
            body.extend(ast.parse("watch_rows = state.get('watch_rows', [])").body)
        body.append(value)
    node.body = body
    return node
