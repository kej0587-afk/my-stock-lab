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
    "report_scenario", "report_reference", "report_close_basis", "report_price_quality",
    "report_comparison", "report_market_summary", "report_brief", "report_view", "report_intraday", "article_context", "report_news_selection",
    "economic_releases", "economic_cache", "economic_bulletins", "report_economic_reading", "release_calendar",
    "economic_consensus", "report_consensus",
    "report_account", "report_calendar", "report_observation_panel",
    "market_observation", "market_sentiment", "public_market_data", "earnings_sources", "catalyst_news", "report_catalysts",
    "earnings_result_sources", "earnings_result_pdf", "earnings_cash_outlook", "earnings_reconciliation",
    "earnings_collection", "earnings_discovery", "earnings_pipeline", "report_earnings", "report_market_connections",
    "official_outlook", "outlook_sources", "report_outlook", "report_dashboard", "news_priority", "market_guard_explanation",
    "central_bank_results", "market_safeguards", "report_policy_panel", "report_eventstudy",
    "report_policy_catalysts", "report_energy_basis", "article_events", "public_market_flow_history", "public_flow_backfill",
    "report_account_section", "report_calendar_section", "report_editorial",
    "portfolio_market_review", "portfolio_holding_review", "portfolio_commentary",
    "etf_review", "etf_issuer_evidence", "etf_roundhill",
    "holding_evidence_commentary",
    "msft_ir_review", "msft_ir_source", "report_msft", "report_msft_source",
    "msft_cash_trend", "msft_cash_q4", "report_msft_cash", "sec_quarter_review", "sec_quarter_review_view", "sec_financial_periods",
    "company_deep_dive", "company_cash_reading", "company_kr_evidence", "dart_evidence_store", "report_leadership",
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
    # This calendar is read afresh by the renderer, unlike imported Python code.
    calendar = Path(__file__).with_name("data") / "verified_policy_calendar_20261104.json"
    digest = _file_hash(calendar)
    sources["data.policy_calendar"] = {"path": str(calendar), "sha256": digest, "disk_sha256": digest}
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
