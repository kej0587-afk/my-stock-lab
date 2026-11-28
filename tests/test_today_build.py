"""Today helper provenance must detect stale imports, not just the Git head."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import ast
from pathlib import Path

import pytest
from stock_lab_core import today_build as module


@pytest.mark.parametrize("state", ["matching", "changed", "unregistered", "missing", "not_loaded"])
def test_loaded_sources_are_checked_without_import(tmp_path, monkeypatch, state):
    path = tmp_path / "source.py"
    path.write_text("original", encoding="utf8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    name = "stock_lab_core.flow_shortlist_render"
    base = {"sources": {"report": {"sha256": "base"}}, "stale_modules": [], "restart_required": False}
    before = deepcopy(base)
    monkeypatch.setattr(module, "MODULES", ("flow_shortlist_render",))
    monkeypatch.setattr(module.report_build, "get_report_build_info", lambda _: base)
    monkeypatch.setattr(module.report_build, "_LOADED", {name: {"path": str(path), "sha256": digest}})
    monkeypatch.setitem(module.sys.modules, name, SimpleNamespace(__file__=str(path)))
    if state == "changed": path.write_text("new", encoding="utf8")
    elif state == "unregistered": module.report_build._LOADED.clear()
    elif state == "missing": path.unlink()
    elif state == "not_loaded": monkeypatch.delitem(module.sys.modules, name)
    value = module.today_build_info("app.py")
    assert value["restart_required"] is (state in {"changed", "unregistered", "missing"})
    assert (name in value["sources"]) is (state != "not_loaded")
    assert base == before


def test_keeps_existing_stale_report(monkeypatch):
    monkeypatch.setattr(module, "MODULES", ())
    monkeypatch.setattr(module.report_build, "get_report_build_info", lambda _: {
        "sources": {}, "stale_modules": ["report"], "restart_required": True})
    assert module.today_build_info()["stale_modules"] == ["report"]


def test_both_today_diagnostics_use_the_same_helper():
    tree = ast.parse(Path('app.py').read_text('utf-8-sig'))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(ast.unparse(t) in {"attempt['build']", "report['build']"} for t in n.targets)]
    assert len(calls) == 2
    assert all(ast.unparse(n.value) == "today_build_info(__file__)" for n in calls)
