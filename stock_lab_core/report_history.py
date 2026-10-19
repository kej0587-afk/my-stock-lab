"""Owner-scoped report history keyed by reference trading session, not run date."""

import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from copy import deepcopy
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

from stock_lab_core.report_evidence import first, holding_reasons, records, text
from stock_lab_core.today_snapshot import _snapshot_location
from stock_lab_core.report_history_store import ReportHistoryStoreError, validate_session

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "cache" / "market_report_history.json"


def normalized_decisions(rows):
    return [{"티커": text(first(row, "티커", "ticker")),
             "최종읽기": text(first(row, "최종읽기", "🔥기술적 타점", "판정코드")),
             "게이트상태": text(first(row, "게이트상태", "gate_state")),
             "저장사유": holding_reasons(row)} for row in records(rows)]


def _load_local(location, owner_hash):
    if not location.exists():
        return {}
    payload = json.loads(location.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("owner_hash") != owner_hash:
        raise ValueError("history owner mismatch")
    saved = payload["sessions"]
    if not isinstance(saved, dict) or any(validate_session(value) != key for key, value in saved.items()):
        raise ValueError("invalid history sessions")
    return saved


def _save_local(location, owner_hash, saved):
    temporary = None
    try:
        location.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=location.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"owner_hash": owner_hash, "sessions": saved}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, location)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _run_time(session):
    try:
        stamp = datetime.fromisoformat(session.get("generated_at", "").replace("Z", "+00:00"))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _comparisons(saved, dates, result):
    key = result["summary_date"]
    candidates = [value for value in saved.values() if all(value["dates"][m] <= dates[m] for m in dates)]
    last = saved.get(key)
    if last is None and candidates:
        last = max(candidates, key=lambda value: (value["dates"]["US"], value["dates"]["KR"]))
    if last and last.get("macro_data"):
        result["previous_macro_data"] = deepcopy(last["macro_data"])
    if last and last.get("dates") == dates:
        result.update(previous_run_summary=deepcopy(last["rows"]),
                      previous_run_at=last.get("generated_at", "저장 시각 미확보"),
                      previous_run_date=key)
    earlier = [value for value in candidates if any(value["dates"][m] < dates[m] for m in dates)]
    if earlier:
        previous = max(earlier, key=lambda value: (value["dates"]["US"], value["dates"]["KR"]))
        result.update(previous_summary=deepcopy(previous["rows"]),
                      previous_date=previous["dates"]["US"] + "/" + previous["dates"]["KR"],
                      previous_sessions=deepcopy(previous["dates"]))


def update_report_history(rows, sessions, *, owner_scope="", path=None, macro_data=None, generated_at=None, store=None):
    """Update a session pair, optionally using an owner-bound injected store.

    Stores implement load_sessions(dates, *, owner_scope) -> dict and
    upsert_session(session, *, owner_scope). Local JSON remains a fallback and
    a best-effort mirror. history_durable is true only after a confirmed upsert.
    """
    # A KR/US pair avoids comparing mismatched cross-market report sessions.
    dates = {key: text(sessions.get(key)) for key in ("KR", "US")}
    result = {"summary_date": dates["US"] + "/" + dates["KR"], "previous_summary": [], "previous_date": "",
              "history_backend": "none", "history_durable": False, "history_fallback": False}
    if not all(dates.values()):
        return dict(result, history_status="기준 거래일 미확보: 비교 저장 보류")
    rows = records(rows)
    if not rows:
        return dict(result, history_status="점검 판정 미연결: 비교 저장 보류")
    owner_scope = str(owner_scope or "").strip().lower()
    if not owner_scope and path is None:
        return dict(result, history_status="로그인 계정 미연결: 개인 비교 저장 보류")
    location, owner_hash = _snapshot_location(path or DEFAULT_PATH, owner_scope)
    try:
        current = {"dates": dates, "rows": normalized_decisions(rows),
                   "generated_at": generated_at or datetime.now(timezone.utc).isoformat()}
        if macro_data:
            current["macro_data"] = deepcopy(macro_data)
        key = validate_session(current)
    except (ValueError, TypeError):
        return dict(result, history_status="거래일/판정 자료 오류: 비교 저장 보류")
    local_available = True
    try:
        saved = _load_local(location, owner_hash)
    except (OSError, ValueError, TypeError, KeyError):
        saved, local_available = {}, False
    if store is not None:
        try:
            if not owner_scope:
                raise ReportHistoryStoreError("owner_scope_mismatch")
            remote = store.load_sessions(dates, owner_scope=owner_scope)
            if not isinstance(remote, dict) or any(validate_session(value) != k for k, value in remote.items()):
                raise ReportHistoryStoreError("invalid_data")
            # A local outage run may be newer than the last successful DB write.
            for remote_key, value in remote.items():
                if remote_key not in saved or _run_time(value) >= _run_time(saved[remote_key]):
                    saved[remote_key] = deepcopy(value)
            store.upsert_session(current, owner_scope=owner_scope)
            result.update(history_backend="supabase", history_durable=True)
        except Exception as exc:
            code = exc.code if isinstance(exc, ReportHistoryStoreError) else "store_unavailable"
            result.update(history_fallback=True, history_error=code)
    _comparisons(saved, dates, result)
    saved[key] = current
    try:
        if local_available:
            _save_local(location, owner_hash, saved)
    except (OSError, ValueError, TypeError):
        local_available = False
    result["history_local_status"] = "saved" if local_available else "unavailable"
    if result["history_durable"]:
        status = "Supabase 개인 이력 저장 완료(동일 거래일 쌍 갱신)"
        if not local_available:
            status += " · 로컬 사본 저장 불가"
        return dict(result, history_status=status)
    result["history_backend"] = "local" if local_available else "unavailable"
    status = ("거래일별 판정·사유 로컬 저장 완료(동일 거래일 덮어쓰기)"
              if local_available else "비교 저장 실패: 로컬 저장소 사용 불가/손상")
    if store is not None:
        reason = ("Supabase 이력 테이블 미준비(SQL 적용 미확인)"
                  if result.get("history_error") == "schema_unavailable" else "Supabase 영구 저장 미확인")
        status = reason + ": " + status
    return dict(result, history_status=status)
