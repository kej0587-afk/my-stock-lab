"""Last verified public observations, separate from the short-lived request cache."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import threading

CACHE_PATH = Path(__file__).resolve().parents[1] / "cache" / "economic_last_success.json"
_LOCK = threading.Lock()
_SERIES = {"KR_CPI", "KR_EXPORTS", "US_RETAIL_SALES"}
_FIELDS = {"indicator", "period", "actual", "previous", "unit", "basis", "source", "source_url",
           "seasonal_adjustment", "retrieved_at", "previous_period", "previous_source", "previous_unit",
           "previous_basis", "series_id", "value_kind", "raw_unit", "raw_actual", "raw_year_ago",
           "raw_year_ago_period", "history", "history_frequency", "data_vintage"}


def _valid(row, now):
    try:
        at = datetime.fromisoformat(row["retrieved_at"]).astimezone(timezone.utc)
        period = datetime.strptime(row["period"], "%Y-%m").replace(tzinfo=timezone.utc)
        return (row.get("indicator") in _SERIES and row.get("unit") == "%"
                and row.get("basis") == ("MoM" if row["indicator"] == "US_RETAIL_SALES" else "YoY")
                and not isinstance(row["actual"], bool) and math.isfinite(float(row["actual"]))
                and now - timedelta(days=120) <= at <= now and period <= now
                and now - period < timedelta(days=180))
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def retain_successful_observations(rows, now):
    """Never promote failures to success or carry event/forecast data across months.

    Stored values must originate from a verified provider response. Missing cache
    is not seeded from report text. Public observations only; no keys or account data.
    """
    output = deepcopy(rows)
    temporary = None
    with _LOCK:
        try:
            saved = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            saved = saved if isinstance(saved, dict) else {}
        except (OSError, ValueError):
            saved = {}
        changed = False
        for row in output:
            indicator = row.get("indicator")
            if indicator not in _SERIES:
                continue
            if row.get("status") == "released" and _valid(row, now):
                saved[indicator] = {key: row[key] for key in _FIELDS if key in row}
                changed = True
            elif row.get("actual") is None and _valid(saved.get(indicator, {}), now):
                reason = row.get("missing_reason", "collection_failed")
                row.update(deepcopy(saved[indicator]), status="stale", collection_error=reason,
                           last_success_at=saved[indicator]["retrieved_at"], as_of=now.isoformat())
        if changed:
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CACHE_PATH.parent,
                                                 delete=False) as handle:
                    temporary = Path(handle.name)
                    json.dump(saved, handle, ensure_ascii=False, allow_nan=False)
                os.replace(temporary, CACHE_PATH)
            except (OSError, ValueError, TypeError):
                for row in output:
                    if row.get("indicator") in _SERIES:
                        row["cache_warning"] = "last_success_write_failed"
            finally:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
    return output


def collection_status(row):
    """Only controlled codes reach the report, never credential-bearing exceptions."""
    reason = str(row.get("collection_error") or row.get("missing_reason") or "")
    if "API_KEY_missing" in reason:
        return "키 미설정"
    if "API_KEY_invalid_format" in reason:
        return "키 형식 확인 필요"
    if any(code in reason for code in ("http_401", "http_403", "INFO-100", "ERROR-100")):
        return "인증/접근 거절(키·허용 환경 확인)"
    if "http_429" in reason:
        return "호출 한도 초과"
    if "Timeout" in reason:
        return "응답 시간 초과"
    if "request_failed" in reason:
        return "네트워크 연결 실패"
    if any(code in reason for code in ("mapping", "unit_mismatch", "series_or_unit")):
        return "통계 항목/단위 검증 실패"
    if "http_" in reason:
        return "공급처 HTTP 오류"
    return "공급처 응답/관측치 확인 실패"
