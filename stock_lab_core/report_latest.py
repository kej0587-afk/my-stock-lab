"""Show the last completed market report first, then replace it with a new complete one.

The report names holdings, so it is stored per verified login (owner) and per selected account set
(``account_key``): in the user's Supabase (``report_latest``, docs/20261127_report_latest.sql) and an
owner+account-hashed local file under ``cache/`` (git-ignored). Without the table the local copy still
covers new sessions on the same server; a reboot then shows nothing until a report is generated.
A new report that failed or was made before Today (오늘 점검 미계산) never replaces or overwrites the last
complete one. Nothing here alters report contents, decisions or the frozen memo panel.
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
UNCOMPUTED = "오늘 점검 미계산"  # report made before Today: holdings and company earnings missing
LAST_KEY = "_today_market_memo_last_complete"    # last complete report text in this session
SCOPE_KEY = "_today_market_memo_last_scope"      # account_key of LAST_KEY
RESTORED_KEY = "_today_market_memo_restored"     # sha of the restored text still on screen ("" if none)
SAVED_KEY = "_today_market_memo_persisted"       # sha of the last text stored this session
TRIED_KEY = "_today_market_memo_restore_tried"   # account_key already tried this session
STATUS_KEY = "_today_market_memo_latest_status"
ENGINE_KEY = "_today_market_memo_engine_version"  # report_build.invalidate_saved_report


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def account_key(accounts):
    """Stable, name-free key for the selected account set (order and duplicates ignored)."""
    names = sorted({str(name).strip() for name in (accounts or []) if str(name).strip()})
    return "acc_" + _sha(json.dumps(names, ensure_ascii=False))[:32]


def is_complete_report(value):
    """A finished report with holdings: not the notice-only fallback (no 기준일) nor a 미계산 report."""
    value = str(value or "")
    return MARKER in value and "## 기준일" in value and UNCOMPUTED not in value and len(value) <= MAX_CHARS


def incomplete_reason(value):
    value = str(value or "")
    if MARKER not in value or is_complete_report(value):
        return ""
    return "uncomputed" if UNCOMPUTED in value else "failed"


class SupabaseReportLatestStore:
    """One row per verified owner and account set; construct per owner like SupabaseReportHistoryStore."""

    def __init__(self, client, *, owner_scope):
        self._client = client
        self._owner_scope = _owner(owner_scope)

    def _check(self, owner_scope, account):
        if not self._owner_scope or _owner(owner_scope) != self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")
        if not str(account or "").startswith("acc_"):
            raise ReportHistoryStoreError("account_scope_mismatch")

    def load(self, *, owner_scope, account):
        self._check(owner_scope, account)
        try:
            response = (self._client.table(TABLE_NAME).select("owner_email,account_key,generated_at,report_text")
                        .eq("owner_email", self._owner_scope).eq("account_key", account).limit(1).execute())
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
        if row.get("account_key") != account:
            raise ReportHistoryStoreError("account_scope_mismatch")
        if not is_complete_report(row.get("report_text")):
            raise ReportHistoryStoreError("invalid_data")
        return {"report_text": row["report_text"], "generated_at": str(row.get("generated_at") or "")}

    def save(self, report_text, generated_at, *, owner_scope, account):
        self._check(owner_scope, account)
        if not is_complete_report(report_text):
            raise ReportHistoryStoreError("invalid_data")
        row = {"owner_email": self._owner_scope, "account_key": account,
               "generated_at": generated_at, "report_text": report_text}
        try:
            response = self._client.table(TABLE_NAME).upsert(row, on_conflict="owner_email,account_key").execute()
        except Exception as exc:
            raise _database_error(exc) from None
        data = getattr(response, "data", None)
        if (not isinstance(data, list) or len(data) != 1 or data[0].get("owner_email") != self._owner_scope
                or data[0].get("account_key") != account):
            raise ReportHistoryStoreError("write_unconfirmed")


def _local_path(path, owner_scope, account):
    scope = _owner(owner_scope)
    if not scope or not account:
        return None
    base = Path(path) if path is not None else DEFAULT_PATH
    return base.with_name(f"{base.stem}_{_sha(scope + '|' + account)}{base.suffix}")


def _load_local(path, owner_scope, account):
    location = _local_path(path, owner_scope, account)
    if location is None:
        return None
    try:
        saved = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or saved.get("owner_hash") != _sha(_owner(owner_scope)) \
            or saved.get("account_key") != account or not is_complete_report(saved.get("report_text")):
        return None
    return {"report_text": saved["report_text"], "generated_at": str(saved.get("generated_at") or "")}


def _save_local(path, owner_scope, account, report_text, generated_at):
    location = _local_path(path, owner_scope, account)
    if location is None:
        return False
    temporary = None
    try:
        location.parent.mkdir(parents=True, exist_ok=True)
        payload = {"owner_hash": _sha(_owner(owner_scope)), "account_key": account,
                   "generated_at": generated_at, "report_text": report_text}
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


def restore_last_report(state, *, owner_scope, accounts=(), store=None, build_id="", path=None):
    """Once per session and account set, show the last complete report for that owner and account set.

    Fills the report slot only when it is empty or holds an auto report of another account set; a
    handwritten memo or a report of the current account set is never replaced. The engine version is
    set to the current build so the code-change invalidation does not wipe the restored copy.
    """
    account = account_key(accounts)
    if state.get(TRIED_KEY) == account:
        return False
    state[TRIED_KEY] = account
    if not _owner(owner_scope):
        return False
    text = str(state.get(MEMO_KEY) or "")
    other_scope = MARKER in text and state.get(SCOPE_KEY) not in (None, account)
    if text.strip() and not other_scope:
        return False
    found, source = None, ""
    if store is not None:
        try:
            found, source = store.load(owner_scope=owner_scope, account=account), "supabase"
        except Exception as exc:
            state[STATUS_KEY] = exc.code if isinstance(exc, ReportHistoryStoreError) else "store_unavailable"
    if found is None:
        found, source = _load_local(path, owner_scope, account), "local"
    if found is None:
        if other_scope:  # never label another account set's report as this one's
            state[LAST_KEY], state[SCOPE_KEY], state[RESTORED_KEY] = "", account, ""
        return False
    state[MEMO_KEY] = state[LAST_KEY] = found["report_text"]
    state[SCOPE_KEY] = account
    state[RESTORED_KEY] = state[SAVED_KEY] = _sha(found["report_text"])
    state[STATUS_KEY + "_source"] = source
    if build_id:
        state[ENGINE_KEY] = build_id
    return True


def keep_last_complete(state):
    """A new auto report that failed or lacks holdings never replaces the last complete one.

    Returns "uncomputed" / "failed" when the previous complete report was put back, else "".
    The incomplete text is not stored. A handwritten memo is never touched.
    """
    text = str(state.get(MEMO_KEY) or "")
    last = str(state.get(LAST_KEY) or "")
    reason = incomplete_reason(text)
    if not reason or not is_complete_report(last):
        return ""
    state[MEMO_KEY] = last
    state[RESTORED_KEY] = _sha(last)
    state[STATUS_KEY + "_kept"] = reason
    return reason


def kept_notice(reason):
    if reason == "uncomputed":
        return ("새로 만든 시황은 오늘 점검이 미계산이라 보유 종목 영향이 빠져 있어 교체하지 않고 마지막 완성본을 유지합니다. "
                "오늘 점검을 계산한 뒤 다시 생성하면 교체됩니다.")
    if reason == "failed":
        return "새 시황 생성이 완료되지 않아 마지막 완성본을 유지합니다. 다시 생성하면 완성되는 즉시 교체됩니다."
    return ""


def _label(text):
    from stock_lab_core.report_widget_state import saved_report_label
    return saved_report_label(text).replace("저장된 리포트 · ", "")


def last_report_caption(state):
    """One line for views other than 시황: the last complete report and its time, or ''."""
    last = str(state.get(LAST_KEY) or "")
    if not is_complete_report(last):
        return ""
    return f"마지막 시황 완성본: {_label(last)} · ‘시황’ 보기에서 바로 읽을 수 있습니다."


def restored_notice(state):
    """Text for the banner while the restored copy is still the one on screen, else ''."""
    text = str(state.get(MEMO_KEY) or "")
    if not text or state.get(RESTORED_KEY) != _sha(text):
        return ""
    return (f"마지막 완성본을 먼저 표시합니다({_label(text)}). 현재 시세·공시와 다를 수 있습니다. "
            "아래 ‘자동 뉴스픽 생성’으로 새 시황을 만들면 완성되는 즉시 이 화면이 교체됩니다.")


def persist_last_report(state, *, owner_scope, accounts=(), store=None, path=None, now=None):
    """Store a newly completed report once (no write for a restored copy, a handwritten memo or a
    failed / 미계산 report)."""
    text = str(state.get(MEMO_KEY) or "")
    if not _owner(owner_scope) or not is_complete_report(text):
        return ""
    digest = _sha(text)
    if state.get(SAVED_KEY) == digest:
        return ""
    account = account_key(accounts)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    local = _save_local(path, owner_scope, account, text, generated_at)
    status = "local" if local else "unavailable"
    if store is not None:
        try:
            store.save(text, generated_at, owner_scope=owner_scope, account=account)
            status = "supabase"
        except Exception as exc:
            code = exc.code if isinstance(exc, ReportHistoryStoreError) else "store_unavailable"
            status = f"{status}:{code}"
    state[SAVED_KEY] = digest
    state[LAST_KEY], state[SCOPE_KEY], state[RESTORED_KEY] = text, account, ""
    state[STATUS_KEY] = status
    return status
