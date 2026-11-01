"""Check the real lazy app wiring without authentication, prices or a database."""

import ast
from functools import lru_cache
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest


@lru_cache(maxsize=1)
def wiring():
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "render_portfolio_analysis_tab")
    start = next(i for i, node in enumerate(fn.body) if isinstance(node, ast.ImportFrom)
                 and node.module == "stock_lab_core.account_performance_view")
    end = next(i for i, node in enumerate(fn.body[start:], start) if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "period" for target in node.targets))
    return compile(ast.Module(body=fn.body[start:end], type_ignores=[]), str(source), "exec")


@pytest.mark.parametrize("demo", [True, False])
def test_injected_store_uses_verified_owner_and_does_not_query_on_construction(demo):
    warnings, calls = [], []
    client = SimpleNamespace(table=lambda *args: pytest.fail("Unexpected background database call"))

    def current(st, *, owner_scope, monthly_logs_df, store):
        calls.append((owner_scope, store))

    env = dict(st=SimpleNamespace(warning=warnings.append), inspect=inspect, CURRENT_USER_EMAIL=" Alice@Example.Test ",
               monthly_logs_df=pd.DataFrame(), supabase=client, IS_PUBLIC_DEMO=demo)
    with patch("stock_lab_core.account_performance_view.render_account_performance", current):
        exec(wiring(), env)
    assert not warnings
    assert calls[0][0] == " Alice@Example.Test "
    if demo:
        assert calls[0][1] is None
    else:
        assert calls[0][1]._owner_scope == "alice@example.test"
        assert calls[0][1]._client is client


def test_cached_old_view_falls_back_without_unexpected_keyword_or_store_construction():
    warnings, calls = [], []

    def legacy(st, *, owner_scope, monthly_logs_df):
        calls.append(owner_scope)

    env = dict(st=SimpleNamespace(warning=warnings.append), inspect=inspect, CURRENT_USER_EMAIL="owner@example.test",
               monthly_logs_df=pd.DataFrame(), supabase=object(), IS_PUBLIC_DEMO=False)
    with patch("stock_lab_core.account_performance_view.render_account_performance", legacy), patch(
        "stock_lab_core.account_performance_store.SupabaseAccountPerformanceStore", side_effect=AssertionError,
    ):
        exec(wiring(), env)
    assert calls == ["owner@example.test"]
    assert any("현재는 파일 보관만" in message for message in warnings)
