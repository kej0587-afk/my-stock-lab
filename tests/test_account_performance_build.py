"""New optional modules remain auditable with an older cached metadata list."""

from copy import deepcopy
from types import SimpleNamespace

from stock_lab_core import account_performance, account_performance_io, account_performance_view, account_performance_store
from stock_lab_core import precision_build, report_build


def setup_registry(monkeypatch, app):
    names = [module.__name__ for module in (account_performance, account_performance_io, account_performance_view, account_performance_store)]
    registry = {name: deepcopy(report_build._LOADED[name]) for name in names}
    monkeypatch.setattr(report_build, "_LOADED", registry)
    monkeypatch.setattr(precision_build, "MODULES", ())
    monkeypatch.setattr(report_build, "get_report_build_info", lambda *a: {"sources": {}, "stale_modules": []})
    warnings = []
    monkeypatch.setattr(app, "st", SimpleNamespace(warning=warnings.append))
    return names, registry, warnings


def test_cached_old_module_list_gains_actual_registered_sources_without_a_reload(app_module, monkeypatch):
    names, registry, warnings = setup_registry(monkeypatch, app_module)
    original = deepcopy(registry)
    info = app_module.get_precision_build_info()
    assert set(info["sources"]) == set(names)
    assert not info["restart_required"]
    assert not warnings
    assert registry == original
    first = precision_build.MODULES
    assert app_module.get_precision_build_info() == info
    assert precision_build.MODULES == first


def test_old_loaded_code_is_not_relabeled_as_new_disk_code(app_module, monkeypatch):
    names, registry, warnings = setup_registry(monkeypatch, app_module)
    old = names[-1]
    registry[old]["sha256"] = "original-old-loaded-hash"
    info = app_module.get_precision_build_info()
    assert info["restart_required"]
    assert old in info["stale_modules"]
    assert info["sources"][old]["sha256"] == "original-old-loaded-hash"
    assert info["sources"][old]["disk_sha256"] != "original-old-loaded-hash"
    assert registry[old]["sha256"] == "original-old-loaded-hash"
    assert warnings
