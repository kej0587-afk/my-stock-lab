"""A cached pre-batching module must not prevent Streamlit from starting."""

import ast
from contextlib import contextmanager
import logging
from pathlib import Path
import sys
from types import ModuleType

import pytest


def startup_block():
    path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.ImportFrom)
                 and node.module == "stock_lab_core.kr_sector_snapshot")
    end = next(i for i, node in enumerate(tree.body[start + 1:], start + 1) if isinstance(node, ast.ImportFrom)
               and node.module == "stock_lab_core.us_sector_snapshot")
    return compile(ast.Module(body=tree.body[start:end], type_ignores=[]), str(path), "exec")


@pytest.mark.parametrize("missing", ["scope", "preload", "both"])
def test_old_or_partial_module_keeps_real_builder_and_uses_atomic_fallback(monkeypatch, caplog, missing):
    module = ModuleType("stock_lab_core.kr_sector_snapshot")
    calls = []

    def builder(*args, **kwargs):
        calls.append((args, kwargs))
        return {"state": "existing analysis", "ticker": "005930.KS"}

    def must_not_run(*args, **kwargs):
        raise AssertionError("Partial batching hooks must never be combined")

    module.build_kr_cluster_snapshot = builder
    if missing == "scope":
        module.preload_kr_cluster_snapshots = must_not_run
    elif missing == "preload":
        module.kr_cluster_snapshot_scope = must_not_run
    monkeypatch.setitem(sys.modules, module.__name__, module)
    namespace = {"logging": logging}
    with caplog.at_level(logging.WARNING):
        exec(startup_block(), namespace)
    assert namespace["KR_CLUSTER_SCOPED_PREFETCH_AVAILABLE"] is False
    assert "KR cluster batching unavailable" in caplog.text
    with namespace["kr_cluster_snapshot_scope"](owner_scope="test-owner"):
        namespace["preload_kr_cluster_snapshots"]([("AI", "semiconductor")])
        assert namespace["build_kr_cluster_snapshot"]("AI", live_prices=True) == builder("AI", live_prices=True)
    assert calls == [(("AI",), {"live_prices": True})] * 2


def test_current_module_keeps_real_batching_hooks(monkeypatch):
    module = ModuleType("stock_lab_core.kr_sector_snapshot")
    module.build_kr_cluster_snapshot = lambda *args, **kwargs: {}

    @contextmanager
    def scope(*args, **kwargs):
        yield "active"

    module.kr_cluster_snapshot_scope = scope
    module.preload_kr_cluster_snapshots = lambda requests: "preloaded"
    monkeypatch.setitem(sys.modules, module.__name__, module)
    namespace = {"logging": logging}
    exec(startup_block(), namespace)
    assert namespace["KR_CLUSTER_SCOPED_PREFETCH_AVAILABLE"] is True
    assert namespace["kr_cluster_snapshot_scope"] is scope
    assert namespace["preload_kr_cluster_snapshots"] is module.preload_kr_cluster_snapshots
    with namespace["kr_cluster_snapshot_scope"](owner_scope="test-owner") as state:
        assert state == "active"


def test_missing_essential_builder_is_not_hidden(monkeypatch):
    monkeypatch.setitem(sys.modules, "stock_lab_core.kr_sector_snapshot", ModuleType("stock_lab_core.kr_sector_snapshot"))
    with pytest.raises(ImportError):
        exec(startup_block(), {"logging": logging})
