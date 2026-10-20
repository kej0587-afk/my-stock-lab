"""Last verified public observations, separate from the short-lived request cache."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

CACHE_PATH = Path(__file__).resolve().parents[1] / "cache" / "economic_last_success.json"
_LOCK = threading.Lock()
_SERIES = {"KR_CPI", "KR_EXPORTS", "US_RETAIL_SALES"}
_BLS = {"US_CPI", "US_CORE_CPI", "US_PPI", "US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT"}
_FIELDS = {"indicator", "period", "actual", "previous", "unit", "basis", "source", "source_url", "source_urls",
           "seasonal_adjustment", "retrieved_at", "previous_period", "previous_source", "previous_unit",
           "previous_basis", "series_id", "value_kind", "raw_unit", "raw_actual", "raw_year_ago",
           "raw_year_ago_period", "history", "history_frequency", "data_vintage", "previous3mean", "previous3mean_reason"}


def _key(row):
    indicator = row.get("indicator")
    return "|".join(str(row.get(k, "")) for k in ("indicator", "basis", "unit", "series_id")) if indicator in _BLS else indicator


def _valid(row, now):
    if not isinstance(row, dict) or row.get("value_kind") in {"supplied_event", "verified_official_bulletin"}:
        return False
    try:
        from stock_lab_core.economic_releases import _month

        at = datetime.fromisoformat(row["retrieved_at"])
        if at.tzinfo is None or _month(row["period"]) != row["period"]:
            return False
        at = at.astimezone(timezone.utc)
        period = datetime.strptime(row["period"], "%Y-%m").replace(tzinfo=timezone.utc)
        valid_measure = (row.get("indicator") in _SERIES and row.get("unit") == "%"
                         and row.get("basis") == ("MoM" if row["indicator"] == "US_RETAIL_SALES" else "YoY")
                         and _provider_series(row) is not None)
        if row.get("indicator") in _BLS:
            from stock_lab_core.economic_releases import _BLS_SERIES
            valid_measure = row.get("source") == "BLS" and any(
                row.get("indicator") == spec.indicator and row.get("series_id") == spec.series and row.get("basis") == spec.basis
                and row.get("unit") == ("thousand persons" if spec.mode == "change" else "%") for spec in _BLS_SERIES)
        return (valid_measure
                and not isinstance(row["actual"], bool) and math.isfinite(float(row["actual"]))
                and now - timedelta(days=120) <= at <= now and period <= now
                and now - period < timedelta(days=180))
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return False


def _provider_series(row):
    """Legacy cache rows may omit the id, but must still name the same provider."""
    indicator, source = row.get("indicator"), row.get("source")
    if source == "Bank of Korea ECOS" and indicator in {"KR_CPI", "KR_EXPORTS"}:
        from stock_lab_core.economic_releases import _ECOS_SERIES

        stat, item, _, _ = _ECOS_SERIES[indicator]
        expected = f"{stat}/{item}"
    elif indicator == "US_RETAIL_SALES" and source == "US Census Bureau (MARTS)":
        expected = "MARTS/44X72/MPCSM"
    elif indicator == "KR_EXPORTS" and source == "Korea Customs Service (monthly final bulletin)":
        expected = "customs/monthly_final"
    else:
        return None
    return expected if row.get("series_id") in (None, "", expected) else None


def _same_series(left, right):
    if any(left.get(field) != right.get(field) for field in ("indicator", "unit", "basis", "source")):
        return False
    if left.get("indicator") in _BLS:
        if left.get("series_id") != right.get("series_id"):
            return False
    elif _provider_series(left) is None or _provider_series(left) != _provider_series(right):
        return False
    return all(not (left.get(field) and right.get(field)) or left[field] == right[field]
               for field in ("seasonal_adjustment", "raw_unit", "history_frequency"))


def _monthly_values(row):
    from stock_lab_core.economic_releases import _month, _number, _shift

    values = {}
    period = row.get("period", "")
    if _month(period) != period or row.get("history_frequency", "monthly") != "monthly":
        return values
    history = row.get("history", [])
    for entry in history if isinstance(history, list) else []:
        if not isinstance(entry, dict):
            continue
        if any(entry.get(field) is not None and entry[field] != row.get(field)
               for field in ("unit", "basis", "source", "series_id")):
            continue
        month, value = entry.get("period"), _number(entry.get("value"))
        if month and _month(month) == month and month <= period and value is not None:
            values[month] = value
    previous = _number(row.get("previous"))
    if (previous is not None and row.get("previous_period") == _shift(period, -1)
            and row.get("previous_unit") == row.get("unit") and row.get("previous_basis") == row.get("basis")
            and row.get("previous_source") in {row.get("source"), str(row.get("source")) + " (latest revised)"}):
        values[row["previous_period"]] = previous
    actual = _number(row.get("actual"))
    if actual is not None:
        values[period] = actual
    return values


def _merge_months(row, saved):
    from stock_lab_core.economic_releases import _monthly_history, _shift

    old, new = _monthly_values(saved), _monthly_values(row)
    older = {month: value for month, value in old.items() if month <= row["period"]}
    if not older.keys() - new.keys():
        return
    _monthly_history(row, {**older, **new})
    previous_period = _shift(row["period"], -1)
    if previous_period in older and previous_period not in new:
        row.update(previous=older[previous_period], previous_period=previous_period,
                   previous_source=saved["source"], previous_unit=row["unit"], previous_basis=row["basis"])
        row["actual_minus_previous"] = round(row["actual"] - row["previous"], 6)
        row["missing_reason"] = ";".join(code for code in row.get("missing_reason", "").split(";")
                                         if code and code != "previous_unavailable")
    row.update(history_restored_from_cache=True, history_last_success_at=saved["retrieved_at"])


def _restore(row, saved, now, reason):
    # Request diagnostics stay attached to this failed attempt. Observation fields
    # and period-bound comparisons come exclusively from the last successful row.
    for field in _FIELDS:
        row.pop(field, None)
    row.update(deepcopy(saved), status="stale", collection_error=reason,
               last_success_at=saved["retrieved_at"], as_of=now.isoformat())
    for field in ("forecast", "forecast_source", "forecast_source_url", "forecast_unit", "forecast_basis",
                  "release_at", "release_precision", "release_source", "release_source_url",
                  "actual_minus_forecast", "actual_minus_previous"):
        row[field] = None
    row.setdefault("previous", None)
    row.setdefault("previous_unit", None)
    row.setdefault("previous_basis", None)
    row.setdefault("history", [])
    row.setdefault("previous3mean", None)
    row.setdefault("previous3mean_reason", "monthly_history_unavailable")


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
            if indicator not in _SERIES | _BLS:
                continue
            if row.get("status") == "pending" or row.get("value_kind") == "supplied_event":
                continue
            key = _key(row)
            previous = saved.get(key, {})
            compatible = _valid(previous, now) and _same_series(row, previous)
            if (compatible and row.get("actual") is not None and row.get("period")
                    and row["period"] < previous["period"] and row.get("status") in {"released", "stale"}):
                _restore(row, previous, now, row.get("missing_reason") or "provider_observation_older_than_last_success")
                continue
            if row.get("status") == "released" and _valid(row, now):
                if compatible:
                    _merge_months(row, previous)
                saved[key] = {field: row[field] for field in _FIELDS if field in row}
                changed = True
            elif row.get("actual") is None and (compatible or (
                    indicator == "KR_EXPORTS" and row.get("official_bulletin_fetch")
                    and row.get("source") == "Bank of Korea ECOS" and _valid(previous, now)
                    and previous.get("source") == "Korea Customs Service (monthly final bulletin)"
                    and row.get("unit") == previous.get("unit") and row.get("basis") == previous.get("basis"))):
                reason = row.get("missing_reason", "collection_failed")
                _restore(row, previous, now, reason)
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
                    if row.get("indicator") in _SERIES | _BLS:
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
    if "census_api_key_required" in reason:
        return "Census API 키 필요"
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
