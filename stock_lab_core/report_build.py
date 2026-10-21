"""Identify loaded report code separately from files currently on disk."""

from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

_LOADED = {}
_RENDER_MODULES = (
    "market_memo", "report_evidence", "report_analysis", "report_presentation",
    "report_holdings", "report_session", "today_news",
    "report_history", "report_prices", "report_context", "report_live", "report_quotes", "report_history_store",
    "report_scenario", "report_reference",
    "report_comparison", "report_market_summary", "report_brief", "report_view", "report_intraday",
    "economic_releases", "economic_cache", "economic_bulletins", "report_economic_reading", "release_calendar",
)


def _file_hash(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def register_loaded_source(name, filename):
    # Capture at module execution, never re-label an old import with a new hash.
    path = str(Path(filename).resolve())
    _LOADED[name] = {"path": path, "sha256": _file_hash(path)}


def _revision():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=2, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def get_report_build_info(entrypoint=None):
    sources = {}
    for short_name in _RENDER_MODULES:
        name = "stock_lab_core." + short_name
        module = importlib.import_module(name)
        loaded = _LOADED.get(name, {"path": module.__file__, "sha256": "unrecorded"})
        sources[name] = dict(loaded, disk_sha256=_file_hash(loaded["path"]))
    if "stock_lab.app_entry" in _LOADED:
        loaded = _LOADED["stock_lab.app_entry"]
        sources["stock_lab.app_entry"] = dict(loaded, disk_sha256=_file_hash(loaded["path"]))
    stale = [name for name, row in sources.items()
             if row["sha256"] in {"unavailable", "unrecorded"} or row["sha256"] != row["disk_sha256"]]
    fingerprint = hashlib.sha256(json.dumps(
        {name: row["sha256"] for name, row in sources.items()}, sort_keys=True,
    ).encode()).hexdigest()
    return {
        "base_commit": _revision(), "loaded_source_sha256": fingerprint,
        "entrypoint": str(Path(entrypoint or sys.argv[0]).resolve()),
        "renderer_path": sources["stock_lab_core.market_memo"]["path"],
        "restart_required": bool(stale), "stale_modules": stale, "sources": sources,
    }


def completed_measurement_reference(reference, archive):
    """Resolve timestamps only from the exact measurement, never latest rerun."""
    result = dict(reference or {})
    identity = result.get("measurement_id")
    saved = (archive or {}).get(identity, {}) if identity else {}
    if saved.get("measurement_id") == identity:
        result.update({key: value for key, value in saved.items()
                       if key.startswith("measurement_") and value is not None})
    return result


def report_footer(*, entrypoint=None, queue_measurement=None):
    info = get_report_build_info(entrypoint)
    queue = queue_measurement or {}
    warning = " · 로드 코드/디스크 불일치: 앱 재시작 필요" if info["restart_required"] else ""
    return (
        "빌드: 기준커밋 " + info["base_commit"][:12]
        + " · 로드 소스 " + info["loaded_source_sha256"][:16]
        + " · 실행 " + info["entrypoint"] + " · 렌더 " + info["renderer_path"]
        + " · 생성ID " + uuid4().hex[:12]
        + " · 실제 생성시각 " + datetime.now(timezone.utc).isoformat(timespec="seconds")
        + " · 점검 측정ID " + str(queue.get("measurement_id") or "미연결")
        + " (" + str(queue.get("measurement_finished_at") or
                      ("시작 " + queue["measurement_started_at"] + " · 완료 시각 미확보" if queue.get("measurement_started_at") else "시각 미확보")) + ")" + warning
    )


def invalidate_saved_report(state, build_id):
    """Only invalidate generated text, never a user's handwritten memo."""
    if state.get("_today_market_memo_engine_version") == build_id:
        return False
    state["_today_market_memo_engine_version"] = build_id
    old = str(state.get("today_market_memo_text") or "")
    if "Stock Lab 자동 뉴스픽" in old:
        state["today_market_memo_text"] = ""
        return True
    return False
