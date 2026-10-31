"""A new Git commit must not disguise older cached Python modules."""

from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from stock_lab_core import precision_build as module


@pytest.mark.parametrize("state", ["matching", "changed", "unregistered", "missing_file", "not_loaded"])
def test_loaded_precision_sources_are_verified_without_importing_them(tmp_path, monkeypatch, state):
    path = tmp_path / "scorecard.py"
    path.write_text("loaded implementation", encoding="utf8")
    loaded_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    name = "stock_lab_core.chart_scorecard"
    base = {"sources": {"report": {"sha256": "base"}}, "stale_modules": [], "restart_required": False}
    original = deepcopy(base)
    monkeypatch.setattr(module, "MODULES", ("chart_scorecard",))
    monkeypatch.setattr(module.report_build, "get_report_build_info", lambda entrypoint: base)
    monkeypatch.setattr(module.report_build, "_LOADED", {name: {"path": str(path), "sha256": loaded_hash}})
    monkeypatch.setitem(module.sys.modules, name, SimpleNamespace(__file__=str(path)))
    if state == "changed":
        path.write_text("new file, old module", encoding="utf8")
    elif state == "unregistered":
        module.report_build._LOADED.clear()
    elif state == "missing_file":
        path.unlink()
    elif state == "not_loaded":
        monkeypatch.delitem(module.sys.modules, name)
    result = module.precision_build_info("app.py")
    assert result["restart_required"] is (state in {"changed", "unregistered", "missing_file"})
    assert (name in result["sources"]) is (state != "not_loaded")
    if state == "unregistered":
        assert result["sources"][name]["sha256"] == "unrecorded"
    assert base == original


def test_existing_report_restart_warning_is_preserved(monkeypatch):
    monkeypatch.setattr(module, "MODULES", ())
    monkeypatch.setattr(module.report_build, "get_report_build_info", lambda entrypoint: {
        "sources": {}, "stale_modules": ["original.report"], "restart_required": True,
    })
    result = module.precision_build_info()
    assert result["restart_required"] is True
    assert result["stale_modules"] == ["original.report"]
