"""Include loaded observatory helpers in the existing source provenance."""

from copy import deepcopy
import hashlib
from pathlib import Path
import sys

from stock_lab_core import report_build


MODULES = ("chart_scorecard", "scorecard_review", "etf_holdings", "precision_review_export",
           "chart_patterns", "chart_execution", "precision_chart_view", "chart_structure")


def precision_build_info(entrypoint=None):
    info = deepcopy(report_build.get_report_build_info(entrypoint))
    sources = info.setdefault("sources", {})
    stale = set(info.get("stale_modules", []))
    for short_name in MODULES:
        name = "stock_lab_core." + short_name
        module = sys.modules.get(name)
        if module is None:
            continue
        loaded = dict(report_build._LOADED.get(name, {}))
        path = loaded.get("path") or getattr(module, "__file__", "")
        try:
            disk = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except (OSError, TypeError, ValueError):
            disk = "unavailable"
        loaded.update(path=path, sha256=loaded.get("sha256", "unrecorded"), disk_sha256=disk)
        sources[name] = loaded
        if loaded["sha256"] in {"unrecorded", "unavailable"} or loaded["sha256"] != disk:
            stale.add(name)
    info["stale_modules"] = sorted(stale)
    info["restart_required"] = bool(stale)
    info["loaded_source_sha256"] = hashlib.sha256(
        repr(sorted((name, row["sha256"]) for name, row in sources.items())).encode()
    ).hexdigest()
    return info
