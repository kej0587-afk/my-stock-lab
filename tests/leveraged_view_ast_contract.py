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
