"""Owner-scoped report history keyed by reference trading session, not run date."""

import json
import os
from pathlib import Path
import tempfile

from stock_lab_core.report_evidence import first, holding_reasons, records, text
from stock_lab_core.today_snapshot import _snapshot_location

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "cache" / "market_report_history.json"


def normalized_decisions(rows):
    return [{"티커": text(first(row, "티커", "ticker")),
             "최종읽기": text(first(row, "최종읽기", "🔥기술적 타점", "판정코드")),
             "게이트상태": text(first(row, "게이트상태", "gate_state")),
             "저장사유": holding_reasons(row)} for row in records(rows)]


def update_report_history(rows, sessions, *, owner_scope="", path=None, macro_data=None):
    # A KR/US pair avoids comparing mismatched cross-market report sessions.
    dates = {key: text(sessions.get(key)) for key in ("KR", "US")}
    result = {"summary_date": dates["US"] + "/" + dates["KR"], "previous_summary": [], "previous_date": ""}
    if not all(dates.values()):
        return dict(result, history_status="기준 거래일 미확보: 비교 저장 보류")
    if not records(rows):
        return dict(result, history_status="점검 판정 미연결: 비교 저장 보류")
    location, owner_hash = _snapshot_location(path or DEFAULT_PATH, owner_scope)
    if not owner_scope and path is None:
        return dict(result, history_status="로그인 계정 미연결: 개인 비교 저장 보류")
    key = dates["US"] + "/" + dates["KR"]
    temporary = None
    try:
        payload = {"owner_hash": owner_hash, "sessions": {}}
        if location.exists():
            old = json.loads(location.read_text(encoding="utf-8"))
            if old.get("owner_hash") == owner_hash:
                payload = old
        saved = payload["sessions"]
        # A refreshed quote may revise the same session; keep its old evidence too.
        last = saved.get(key)
        if last is None and saved:
            candidates = [value for value in saved.values() if all(value["dates"][m] <= dates[m] for m in dates)]
            last = max(candidates, key=lambda value: (value["dates"]["US"], value["dates"]["KR"])) if candidates else None
        if last and last.get("macro_data"):
            result["previous_macro_data"] = last["macro_data"]
        earlier = [value for value in saved.values() if
                   all(value["dates"][m] <= dates[m] for m in dates) and
                   any(value["dates"][m] < dates[m] for m in dates)]
        if earlier:
            previous = max(earlier, key=lambda value: (value["dates"]["US"], value["dates"]["KR"]))
            result.update(previous_summary=previous["rows"], previous_date=previous["dates"]["US"] + "/" + previous["dates"]["KR"], previous_sessions=previous["dates"])
        saved[key] = {"dates": dates, "rows": normalized_decisions(rows)}
        if macro_data:
            saved[key]["macro_data"] = macro_data
        payload["sessions"] = {key: saved[key] for key in sorted(saved)[-40:]}
        location.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=location.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, location)
        return dict(result, history_status="거래일별 판정·사유 저장 완료(동일 거래일 덮어쓰기)")
    except (OSError, ValueError, TypeError, KeyError):
        return dict(result, history_status="비교 저장 실패: 로컬 저장소 사용 불가/손상")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
