"""Show the owner's last completed market report first, then replace it with a new one.

The report text names holdings, so it is stored only owner-bound: in the user's Supabase
(``report_latest``, docs/20261127_report_latest.sql) and an owner-hashed local file under
``cache/`` (git-ignored). Without the table the local copy still covers new sessions on the
same server; a reboot then shows nothing until a report is generated, as before.
Nothing here alters report contents, decisions or the frozen memo panel.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from stock_lab_core.report_history_store import ReportHistoryStoreError, _database_error, _owner
from stock_lab_core.report_widget_state import MEMO_KEY

TABLE_NAME = "report_latest"
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "cache" / "market_report_latest.json"
MAX_CHARS = 1_000_000
MARKER = "Stock Lab 자동 뉴스픽"
RESTORED_KEY = "_today_market_memo_restored"   # sha of the text restored this session ("" if none)
SAVED_KEY = "_today_market_memo_persisted"     # sha of the last text stored this session
TRIED_KEY = "_today_market_memo_restore_tried"
STATUS_KEY = "_today_market_memo_latest_status"
ENGINE_KEY = "_today_market_memo_engine_version"  # report_build.invalidate_saved_report


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_complete_report(value):
    """Only a finished generated report: the notice-only fallback has no 기준일 section."""
    value = str(value or "")
    return MARKER in value and "## 기준일" in value and len(value) <= MAX_CHARS


class SupabaseReportLatestStore:
    """One row per verified owner; construct per owner like SupabaseReportHistoryStore."""

    def __init__(self, client, *, owner_scope):
        self._client = client
        self._owner_scope = _owner(owner_scope)

    def _check(self, owner_scope):
        if not self._owner_scope or _owner(owner_scope) != self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")

    def load(self, *, owner_scope):
        self._check(owner_scope)
        try:
            response = (self._client.table(TABLE_NAME).select("owner_email,generated_at,report_text")
                        .eq("owner_email", self._owner_scope).limit(1).execute())
        except Exception as exc:
            raise _database_error(exc) from None
        rows = getattr(response, "data", None)
        if not isinstance(rows, list):
            raise ReportHistoryStoreError("invalid_data")
        if not rows:
            return None
        row = rows[0]
        if not isinstance(row, dict) or row.get("owner_email") != self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")
        if not is_complete_report(row.get("report_text")):
            raise ReportHistoryStoreError("invalid_data")
        return {"report_text": row["report_text"], "generated_at": str(row.get("generated_at") or "")}

    def save(self, report_text, generated_at, *, owner_scope):
        self._check(owner_scope)
        if not is_complete_report(report_text):
            raise ReportHistoryStoreError("invalid_data")
        row = {"owner_email": self._owner_scope, "generated_at": generated_at, "report_text": report_text}
        try:
            response = self._client.table(TABLE_NAME).upsert(row, on_conflict="owner_email").execute()
        except Exception as exc:
            raise _database_error(exc) from None
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) != 1 or data[0].get("owner_email") != self._owner_scope:
            raise ReportHistoryStoreError("write_unconfirmed")


def _local_path(path, owner_scope):
    scope = _owner(owner_scope)
    if not scope:
        return None
    base = Path(path) if path is not None else DEFAULT_PATH
    return base.with_name(f"{base.stem}_{_sha(scope)}{base.suffix}")


def _load_local(path, owner_scope):
    location = _local_path(path, owner_scope)
    if location is None:
        return None
    try:
        saved = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or saved.get("owner_hash") != _sha(_owner(owner_scope)):
        return None
    if not is_complete_report(saved.get("report_text")):
        return None
    return {"report_text": saved["report_text"], "generated_at": str(saved.get("generated_at") or "")}


def _save_local(path, owner_scope, report_text, generated_at):
    location = _local_path(path, owner_scope)
    if location is None:
        return False
    temporary = None
    try:
        location.parent.mkdir(parents=True, exist_ok=True)
        payload = {"owner_hash": _sha(_owner(owner_scope)), "generated_at": generated_at, "report_text": report_text}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=location.parent, delete=False,
                                         suffix=".tmp") as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(temporary, location)
        return True
    except OSError:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        return False


def restore_last_report(state, *, owner_scope, store=None, build_id="", path=None):
    """Once per session, fill an empty report slot with the owner's last completed report.

    The engine version is set to the current build so the code-change invalidation does not wipe
    the restored copy; the notice from ``restored_notice`` tells the reader it is an earlier report.
    """
    if state.get(TRIED_KEY):
        return False
    state[TRIED_KEY] = True
    if str(state.get(MEMO_KEY) or "").strip() or not _owner(owner_scope):
        return False
    found, source = None, ""
    if store is not None:
        try:
            found, source = store.load(owner_scope=owner_scope), "supabase"
        except Exception as exc:
            state[STATUS_KEY] = exc.code if isinstance(exc, ReportHistoryStoreError) else "store_unavailable"
    if found is None:
        found, source = _load_local(path, owner_scope), "local"
    if found is None:
        return False
    state[MEMO_KEY] = found["report_text"]
    state[RESTORED_KEY] = state[SAVED_KEY] = _sha(found["report_text"])
    state[STATUS_KEY + "_source"] = source
    if build_id:
        state[ENGINE_KEY] = build_id
    return True


def restored_notice(state):
    """Text for the banner while the restored copy is still the one on screen, else ''."""
    text = str(state.get(MEMO_KEY) or "")
    if not text or state.get(RESTORED_KEY) != _sha(text):
        return ""
    from stock_lab_core.report_widget_state import saved_report_label
    label = saved_report_label(text).replace("저장된 리포트 · ", "")
    return (f"마지막 완성본을 먼저 표시합니다({label}). 현재 시세·공시와 다를 수 있습니다. "
            "아래 ‘자동 뉴스픽 생성’으로 새 시황을 만들면 완성되는 즉시 이 화면이 교체됩니다.")


def persist_last_report(state, *, owner_scope, store=None, path=None, now=None):
    """Store a newly completed report once (no write for the restored copy or a handwritten memo)."""
    text = str(state.get(MEMO_KEY) or "")
    if not _owner(owner_scope) or not is_complete_report(text):
        return ""
    digest = _sha(text)
    if state.get(SAVED_KEY) == digest:
        return ""
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    local = _save_local(path, owner_scope, text, generated_at)
    status = "local" if local else "unavailable"
    if store is not None:
        try:
            store.save(text, generated_at, owner_scope=owner_scope)
            status = "supabase"
        except Exception as exc:
            code = exc.code if isinstance(exc, ReportHistoryStoreError) else "store_unavailable"
            status = f"{status}:{code}"
    state[SAVED_KEY] = digest
    state[RESTORED_KEY] = ""
    state[STATUS_KEY] = status
    return status
