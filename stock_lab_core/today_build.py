"""Record loaded Today-only helpers without importing unused UI modules."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

from stock_lab_core import report_build

MODULES = ("today_briefing_assets", "today_briefing_text", "flow_shortlist_render",
           "today_flow_queue", "today_build")


def today_build_info(entrypoint=None):
    info = deepcopy(report_build.get_report_build_info(entrypoint))
    stale = set(info.get("stale_modules", []))
    sources = info.setdefault("sources", {})
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


report_build.register_loaded_source(__name__, __file__)
