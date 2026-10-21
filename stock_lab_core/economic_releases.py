"""Bounded official observations for deterministic economic report tables.

Public entrypoint: ``load_economic_releases(event_rows=None, now=None, *, include_calendar=False)``.
``period`` is the observation month (or the daily Fed rate's effective date),
never its announcement date. ``release_at`` is nullable and has its own source.
BLS percentages are calculated from published index levels, rounded to 0.1;
payrolls are monthly changes in thousands. Previous values use the latest
revised vintage, not the values originally announced. This is not a historical
point-in-time database; ``now`` sets the report clock, not a data vintage.

Optional FRED_API_KEY / CENSUS_API_KEY / ECOS_API_KEY come from the environment
or flat / [economic] Streamlit secrets. FRED supplies the *daily upper target limit*, not an FOMC
decision or the effective federal funds rate. Census's MARTS API now requires
a key in production; a keyless attempt is still supported if the API allows it.
KR CPI/exports use ECOS monthly levels, with the mapping verified against ECOS
item metadata before collection. Missing keys remain explicitly unavailable.
Monthly history contains the row's units/basis, never raw index/amount levels.

Events accept dict rows, an iterable of dicts, or a DataFrame. Existing app
fields event/raw_title/date/end_date/source/actual/forecast/previous are read,
as are indicator/period/unit/basis/release_at/forecast_source. Consensus is
merged only with the same observation period or a verified release date;
otherwise the event remains a separate row. Generic CPI titles without a
MoM/YoY qualifier remain ambiguous. No consensus is generated from observations.

Primary documentation:
https://www.bls.gov/developers/api_signature.htm
https://www.bls.gov/schedule/news_release/cpi.htm
https://www.bls.gov/ppi/fd-id/ppi-final-demand-intermediate-demand-aggregation-indexes-by-title-and-series-id.htm
https://api.census.gov/data/timeseries/eits/marts/examples.html
https://www2.census.gov/api-documentation/EITS_API_User_Guide_Dec2020.pdf
https://fred.stlouisfed.org/docs/api/fred/series_observations.html
https://ecos.bok.or.kr/api/
https://kosis.kr/openapi/devGuide/devGuide_0201List.do
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
from itertools import islice
import math
import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from stock_lab_core.release_calendar import (
    SCHEDULE_URLS as _SCHEDULE_URLS,
    clear_release_calendar_cache,
    load_release_calendar,
)
from stock_lab_core.report_build import register_loaded_source


register_loaded_source(__name__, __file__)

BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
CENSUS_URL = "https://api.census.gov/data/timeseries/eits/marts"
CENSUS_PUBLICATION_URL = "https://www.census.gov/retail/sales.html"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
ECOS_URL = "https://ecos.bok.or.kr/api/"
REQUEST_TIMEOUT = 4.0
CACHE_TTL = 900
MAX_EVENT_ROWS = 64
_CACHE_LIMIT = 16
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_ECOS_SERIES = {
    "KR_CPI": ("901Y009", "0", "소비자물가지수", "총지수"),
    "KR_EXPORTS": ("901Y118", "T002", "수출입 총괄", "수출금액"),
}


@dataclass(frozen=True)
class _Series:
    indicator: str
    series: str
    basis: str
    adjustment: str
    group: str
    mode: str = "percent"


_BLS_SERIES = (
    _Series("US_CPI", "CUSR0000SA0", "MoM", "SA", "cpi"),
    _Series("US_CPI", "CUUR0000SA0", "YoY", "NSA", "cpi"),
    _Series("US_CORE_CPI", "CUSR0000SA0L1E", "MoM", "SA", "cpi"),
    _Series("US_CORE_CPI", "CUUR0000SA0L1E", "YoY", "NSA", "cpi"),
    _Series("US_PPI", "WPSFD4", "MoM", "SA", "ppi"),
    _Series("US_PPI", "WPUFD4", "YoY", "NSA", "ppi"),
    _Series("US_NONFARM_PAYROLLS", "CES0000000001", "MoM", "SA", "empsit", "change"),
    _Series("US_UNEMPLOYMENT", "LNS14000000", "level", "SA", "empsit", "level"),
)
_INDICATORS = {spec.indicator for spec in _BLS_SERIES} | {
    "US_RETAIL_SALES", "US_FED_TARGET_UPPER", "KR_CPI", "KR_EXPORTS",
    "US_CORE_PPI", "US_CORE_RETAIL_SALES", "KR_CORE_CPI", "US_FED_RATE_DECISION",
}


def clear_economic_releases_cache():
    """Clear this collector's process-local, successful-response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()
    clear_release_calendar_cache()


class _Unavailable(ValueError):
    pass


def _cached(key, loader, now):
    tick = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and tick - entry[0] < CACHE_TTL and entry[1] <= now.isoformat():
            _CACHE.move_to_end(key)
            return deepcopy(entry[2]), "", entry[1]
    try:
        value = loader()
        if not value:
            raise _Unavailable("empty_response")
    except _Unavailable as exc:
        return None, str(exc), None
    except requests.RequestException as exc:
        # Request exceptions can contain credential-bearing URLs. Never echo them.
        return None, f"request_failed:{type(exc).__name__}", None
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return None, "invalid_response", None
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), now.isoformat(), deepcopy(value))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return value, "", now.isoformat()


def _census_safe_params(params):
    """Allow known query values, not just names; never retain a prepared URL."""
    fields = {"cell_value", "time_slot_date", "category_code", "data_type_code",
              "seasonally_adj", "error_data"}
    fixed = {"category_code": "44X72", "data_type_code": "MPCSM",
             "seasonally_adj": "yes", "error_data": "no"}
    safe = {}
    for key, value in (params or {}).items():
        if key not in fields | {"get", "time"}:
            continue
        valid = isinstance(value, str) and (
            (key == "get" and bool(value) and set(value.split(",")) <= fields)
            or (key == "time" and re.fullmatch(r"from \d{4}-\d{2} to \d{4}-\d{2}", value))
            or (key in fixed and value == fixed[key]))
        safe[key] = value if valid else "[redacted]"
    return safe


def _census_response_summary(payload, secret=""):
    """Bounded, allowlisted evidence; never copy error bodies or arbitrary fields."""
    summary = {"type": type(payload).__name__}
    if not isinstance(payload, list):
        return summary
    summary["row_count"] = max(0, len(payload) - 1)
    if not payload or not isinstance(payload[0], list):
        return summary
    header = payload[0]
    fields = {"cell_value", "time_slot_date", "time", "category_code", "data_type_code",
              "seasonally_adj", "error_data", "program_code", "geo_level_code", "us"}
    summary["column_count"] = len(header)
    summary["columns"] = [field if isinstance(field, str) and field in fields
                          else "[redacted]" for field in header[:16]]

    def safe_cell(field, value):
        if value is None:
            return None
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return "[redacted]"
        value = str(value)
        if len(value) > 32 or (secret and secret in value):
            return "[redacted]"
        allowed = {"category_code": {"44X72", "44000"}, "data_type_code": {"MPCSM", "SM"},
                   "seasonally_adj": {"yes", "no"}, "error_data": {"yes", "no"},
                   "program_code": {"MARTS"}, "geo_level_code": {"US"}, "us": {"1"}}
        if (value in allowed.get(field, set())
                or (field == "cell_value" and re.fullmatch(r"[+-]?\d{1,12}(?:\.\d{1,6})?", value))
                or (field in {"time", "time_slot_date"} and re.fullmatch(r"[0-9T:./ -]{4,32}", value))):
            return value
        return "[redacted]"

    summary["sample_rows"] = [
        [safe_cell(field, value) for field, value in zip(summary["columns"], cells[:16])]
        if isinstance(cells, list) else "[invalid_row]" for cells in payload[1:3]]
    return summary


def _request(url, *, params=None, payload=None, text=False, diagnostics=None):
    method = requests.post if payload is not None else requests.get
    kwargs = {"timeout": REQUEST_TIMEOUT, "allow_redirects": False,
              "headers": {"User-Agent": "StockLab-Economic-Releases/1.0"}}
    if payload is not None:
        kwargs["json"] = payload
    if params is not None:
        kwargs["params"] = params
    census = url == CENSUS_URL
    safe_params = _census_safe_params(params) if census else {}
    if diagnostics is not None:
        if census or "attempted" in diagnostics:
            diagnostics.update(attempted=True, from_cache=False, origin="network", http_status=None)
        if census:
            diagnostics["parameters"] = safe_params
    try:
        response = method(url, **kwargs)
    except requests.RequestException as exc:
        if diagnostics is not None:
            diagnostics["transport_error"] = type(exc).__name__
            diagnostics["exception_type"] = type(exc).__name__
        if census:
            logging.getLogger(__name__).warning("Census transport=%s params=%s", type(exc).__name__, safe_params)
            raise type(exc)("census_transport_failed") from None
        raise
    try:
        if diagnostics is not None:
            diagnostics["http_status"] = response.status_code
            diagnostics["response_status"] = "http_ok" if response.status_code == 200 else "http_error"
        if census:
            if diagnostics is not None:
                if 300 <= response.status_code < 400:
                    diagnostics["response_status"] = "redirect_not_followed"
                    # This public redirect is verified; never expose Location/query/body.
                    location = urlsplit(getattr(response, "headers", {}).get("Location", ""))
                    if (location.hostname == "api.census.gov"
                            and location.path == "/data/missing_key.html"):
                        diagnostics["response_status"] = "api_key_required"
            log = logging.getLogger(__name__)
            (log.info if response.status_code == 200 else log.warning)(
                "Census HTTP=%s params=%s", response.status_code, safe_params)
        if response.status_code != 200:
            raise _Unavailable(f"http_{response.status_code}")
        if url.startswith(ECOS_URL):
            response.encoding = "utf-8"
        try:
            result = response.text if text else response.json()
            if census and diagnostics is not None:
                diagnostics["response_summary"] = _census_response_summary(result, (params or {}).get("key", ""))
            return result
        except ValueError:
            if census:
                logging.getLogger(__name__).warning("Census response_not_json HTTP=%s", response.status_code)
                if diagnostics is not None:
                    diagnostics["response_status"] = "response_not_json"
                    diagnostics["exception_type"] = "ValueError"
                    diagnostics["response_summary"] = {"type": "non_json"}
                raise ValueError("census_response_not_json") from None
            raise
    finally:
        response.close()


def _api_key(name):
    value = os.environ.get(name, "").strip()
    if not value:
        try:
            import streamlit as st
            value = st.secrets.get(name, "")
            if not value:
                value = st.secrets.get("economic", {}).get(name, "")
        except (FileNotFoundError, KeyError, RuntimeError):
            value = ""
    return value.strip() if isinstance(value, str) else ""


def _clock(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, date) and not isinstance(now, datetime):
        now = datetime.combine(now, datetime.min.time())
    if not isinstance(now, datetime):
        raise TypeError("now must be a date or datetime")
    return (now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now).astimezone(timezone.utc)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(str(value).strip().replace(",", ""))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _month(value):
    text = str(value or "")
    if not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", text):
        return ""
    try:
        date.fromisoformat(text if len(text) == 10 else text + "-01")
        return text[:7]
    except ValueError:
        return ""


def _shift(period, offset):
    year, month = map(int, period.split("-"))
    index = year * 12 + month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _row(indicator, unit, basis, source, source_url, now, **values):
    row = {
        "indicator": indicator, "period": "", "actual": None, "forecast": None,
        "previous": None, "unit": unit, "basis": basis,
        "seasonal_adjustment": "unknown", "release_at": None,
        "release_precision": None, "release_source": None, "release_source_url": None,
        "status": "unavailable", "source": source, "source_url": source_url,
        "as_of": now.isoformat(), "retrieved_at": None,
        "forecast_source": None, "forecast_source_url": None,
        "forecast_unit": None, "forecast_basis": None,
        "previous_source": None, "previous_unit": None, "previous_basis": None,
        "previous_period": "", "actual_minus_forecast": None,
        "actual_minus_previous": None, "difference_unit": "pp" if unit == "%" else unit,
        "value_kind": "official_observation", "data_vintage": "latest_revised",
        "history": [], "history_frequency": "monthly", "previous3mean": None,
        "previous3mean_reason": "monthly_history_unavailable",
        "missing_reason": "", "publication_status": "unconfirmed",
    }
    row.update(values)
    return row


def _reason(row, *reasons):
    parts = row["missing_reason"].split(";") if row["missing_reason"] else []
    row["missing_reason"] = ";".join(dict.fromkeys(parts + [s for s in reasons if s]))


def _monthly_history(row, values):
    """Only same-unit monthly measures; require three consecutive prior months."""
    period = row["period"]
    normalized = {month: _number(value) for month, value in values.items()
                  if _month(month) == month and month <= period and _number(value) is not None}
    row["history"] = [{"period": month, "value": normalized[month]}
                      for month in sorted(normalized)[-36:]]
    prior = [normalized.get(_shift(period, -offset)) for offset in (1, 2, 3)]
    if all(value is not None for value in prior):
        row.update(previous3mean=round(sum(prior) / 3, 6), previous3mean_reason="")
    else:
        row.update(previous3mean=None, previous3mean_reason="three_consecutive_prior_months_unavailable")


def _bls(now):
    ids = list(dict.fromkeys(spec.series for spec in _BLS_SERIES))
    diagnostics = {"endpoint": BLS_URL, "http_status": None}

    def fetch():
        data = _request(BLS_URL, payload={"seriesid": ids,
                        "startyear": str(now.year - 2), "endyear": str(now.year)},
                        diagnostics=diagnostics)
        if not isinstance(data, dict) or data.get("status") != "REQUEST_SUCCEEDED":
            raise _Unavailable("bls_request_not_succeeded")
        result = {}
        for series in data.get("Results", {}).get("series", []):
            observations = {}
            for item in series.get("data", []):
                if not re.fullmatch(r"M(?:0[1-9]|1[0-2])", str(item.get("period", ""))):
                    continue
                period = _month(f"{item.get('year')}-{item['period'][1:]}")
                value = _number(item.get("value"))
                if period and period <= now.strftime("%Y-%m") and value is not None:
                    observations[period] = value
            if observations:
                result[series.get("seriesID")] = observations
        # A partial batch stays usable, but is retried on the next call.
        return {"observations": result, "request": deepcopy(diagnostics)} if result else {}

    key = ("bls", now.strftime("%Y-%m"))
    cached, error, retrieved = _cached(key, fetch, now)
    data = cached["observations"] if cached else {}
    request = deepcopy(cached["request"] if cached else diagnostics)
    request["from_cache"] = bool(cached and diagnostics["http_status"] is None)
    if data and any(spec.series not in data for spec in _BLS_SERIES):
        with _CACHE_LOCK:
            _CACHE.pop(key, None)
    rows = []
    for spec in _BLS_SERIES:
        row = _row(spec.indicator, "thousand persons" if spec.mode == "change" else "%",
                   spec.basis, "BLS", BLS_URL + spec.series, now,
                   seasonal_adjustment=spec.adjustment, series_id=spec.series,
                   retrieved_at=retrieved, request_metadata=deepcopy(request))
        observations = (data or {}).get(spec.series, {})
        if not observations:
            _reason(row, error or "bls_series_unavailable")
        else:
            period = max(observations)
            previous_period = _shift(period, -1)

            def measure(at):
                value = observations.get(at)
                if value is None or spec.mode == "level":
                    return value
                prior = observations.get(_shift(at, -12 if spec.basis == "YoY" else -1))
                if prior is None or (spec.mode == "percent" and prior <= 0):
                    return None
                return round(value - prior, 3) if spec.mode == "change" else round((value / prior - 1) * 100, 1)

            row.update(period=period, actual=measure(period), previous=measure(previous_period),
                       previous_period=previous_period, previous_source="BLS (latest revised)",
                       previous_unit=row["unit"], previous_basis=spec.basis,
                       value_kind="official_observation" if spec.mode == "level" else "calculated_from_official_levels")
            _monthly_history(row, {month: measure(month) for month in observations})
            row["status"] = "released" if row["actual"] is not None else "unavailable"
            if row["actual"] is None:
                _reason(row, "comparison_period_unavailable")
        row["publication_status"] = "available" if row["actual"] is not None else "unconfirmed"
        row["request_metadata"].update(failure_reason=row["missing_reason"],
                                       publication_status=row["publication_status"],
                                       latest_observation_period=row["period"])
        rows.append(row)
    if any(row["actual"] is None for row in rows):
        logging.getLogger(__name__).warning(
            "BLS HTTP=%s transport=%s publication_status=unconfirmed failures=%s",
            request["http_status"], request.get("transport_error", "none"),
            sorted({row["missing_reason"] for row in rows if row["actual"] is None}))
    return rows


def _retail(now, api_key):
    params = {"get": "cell_value,time_slot_date,category_code,data_type_code,seasonally_adj,error_data",
              "time": f"from {now.year - 1}-01 to {now:%Y-%m}",
              "category_code": "44X72", "data_type_code": "MPCSM",
              "seasonally_adj": "yes", "error_data": "no"}
    diagnostics = {"endpoint": CENSUS_URL, "parameters": _census_safe_params(params),
                   "http_status": None, "response_status": "not_received",
                   "api_key_configured": bool(api_key)}

    def fetch():
        request_params = dict(params)
        if api_key:
            request_params["key"] = api_key
        try:
            payload = _request(CENSUS_URL, params=request_params, diagnostics=diagnostics)
        except _Unavailable:
            raise
        except ValueError as exc:
            if not api_key:
                raise _Unavailable("CENSUS_API_KEY_required_or_invalid_response") from None
            raise exc
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
            raise _Unavailable("census_invalid_response")
        header = payload[0]
        required = {"cell_value", "category_code", "data_type_code", "seasonally_adj", "error_data"}
        if (not all(isinstance(field, str) for field in header) or len(set(header)) != len(header)
                or not required <= set(header) or not {"time_slot_date", "time"} & set(header)):
            raise _Unavailable("census_invalid_columns")
        values = {}
        rejected = diagnostics["rejected_rows"] = {}
        diagnostics["observation_count"] = 0
        for cells in payload[1:]:
            if not isinstance(cells, list) or len(cells) != len(header):
                raise _Unavailable("census_invalid_row")
            item = dict(zip(header, cells))
            period = _month(item.get("time_slot_date") or item.get("time"))
            value = _number(item.get("cell_value"))
            reason = next((code for invalid, code in (
                (item.get("category_code") != "44X72", "category_mismatch"),
                (item.get("data_type_code") != "MPCSM", "data_type_mismatch"),
                (str(item.get("seasonally_adj", "")).lower() != "yes", "adjustment_mismatch"),
                (str(item.get("error_data", "")).lower() != "no", "error_data"),
                (not period, "invalid_period"),
                (not f"{now.year - 1}-01" <= period < now.strftime("%Y-%m"), "outside_completed_range"),
                (value is None, "invalid_value"),
            ) if invalid), None)
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            if period in values and values[period] != value:
                raise _Unavailable("census_conflicting_observations")
            values[period] = value
        if values:
            logging.getLogger(__name__).info("Census observations=%s latest_period=%s", len(values), max(values))
        else:
            diagnostics["response_status"] = "no_valid_observations"
            logging.getLogger(__name__).warning("Census no_valid_observations; publication_status=unconfirmed")
            raise _Unavailable("census_no_valid_observations")
        diagnostics.update(response_status="observations_validated", observation_count=len(values),
                           latest_observation_period=max(values))
        return {"observations": values, "request": dict(diagnostics)}

    data, error, retrieved = _cached(("retail", now.strftime("%Y-%m"), hashlib.sha256(api_key.encode()).hexdigest()), fetch, now)
    row = _row("US_RETAIL_SALES", "%", "MoM", "US Census Bureau (MARTS)", CENSUS_URL, now,
               seasonal_adjustment="SA", retrieved_at=retrieved, api_key_configured=bool(api_key))
    if data:
        values = data["observations"]
        period = max(values)
        row.update(period=period, actual=values[period], previous=values.get(_shift(period, -1)),
                   previous_period=_shift(period, -1), previous_source=row["source"],
                   previous_unit="%", previous_basis="MoM", status="released")
        _monthly_history(row, values)
    else:
        _reason(row, error)
    if diagnostics.get("response_status") == "api_key_required":
        _reason(row, "census_api_key_required")
    row["request_metadata"] = deepcopy(data["request"] if data else diagnostics)
    row["request_metadata"]["from_cache"] = bool(data and diagnostics["http_status"] is None)
    if row["request_metadata"]["from_cache"]:
        row["request_metadata"].update(attempted=False, origin="success_cache")
    row["publication_status"] = "available" if data else "unconfirmed"
    row["publication_source_url"] = CENSUS_PUBLICATION_URL
    row["latest_completed_period"] = _shift(now.strftime("%Y-%m"), -1)
    row["observation_recency"] = ("latest_completed_month" if row["period"] == row["latest_completed_period"]
                                 else "older_period" if data else "unconfirmed")
    if data and row["observation_recency"] == "older_period":
        row["status"] = "stale"
        row["publication_status"] = "unconfirmed"
        _reason(row, "latest_completed_month_not_in_response")
    row["request_metadata"].update(
        failure_reason=row["missing_reason"], publication_status=row["publication_status"],
        latest_completed_period=row["latest_completed_period"], observation_recency=row["observation_recency"])
    log = logging.getLogger(__name__)
    (log.warning if row["missing_reason"] else log.info)(
        "Census HTTP=%s params=%s response_status=%s publication_status=%s latest_period=%s reason=%s summary=%s rejected=%s",
        row["request_metadata"]["http_status"], row["request_metadata"]["parameters"],
        row["request_metadata"]["response_status"], row["publication_status"],
        row["period"] or "unavailable", row["missing_reason"] or "none",
        row["request_metadata"].get("response_summary", {}), row["request_metadata"].get("rejected_rows", {}))
    return row


def _fed(now, api_key):
    row = _row("US_FED_TARGET_UPPER", "%", "level", "Federal Reserve via FRED",
               "https://fred.stlouisfed.org/series/DFEDTARU", now, seasonal_adjustment="NSA",
               history_frequency="daily", previous3mean_reason="daily_series_not_monthly")
    if not api_key:
        _reason(row, "FRED_API_KEY_missing")
        return row

    def fetch():
        payload = _request(FRED_URL, params={"series_id": "DFEDTARU", "api_key": api_key,
                           "file_type": "json", "sort_order": "desc", "limit": 10,
                           "observation_end": now.date().isoformat()})
        values = {}
        for item in payload.get("observations", []):
            try:
                day = date.fromisoformat(item["date"])
            except (ValueError, KeyError):
                continue
            value = _number(item.get("value"))
            if day <= now.date() and value is not None:
                values[day.isoformat()] = value
        return values

    data, error, retrieved = _cached(("fed", now.date().isoformat(), hashlib.sha256(api_key.encode()).hexdigest()), fetch, now)
    row["retrieved_at"] = retrieved
    if data:
        days = sorted(data, reverse=True)
        row.update(period=days[0], actual=data[days[0]], status="released",
                   previous=data[days[1]] if len(days) > 1 else None,
                   previous_period=days[1] if len(days) > 1 else "",
                   previous_source=row["source"] + " (previous daily observation)",
                   previous_unit="%", previous_basis="level")
    else:
        _reason(row, error)
    return row


def _ecos_payload_rows(payload, service):
    if not isinstance(payload, dict):
        raise _Unavailable("ecos_invalid_response")
    if "RESULT" in payload:
        result = payload["RESULT"]
        code = result.get("CODE", "") if isinstance(result, dict) else ""
        suffix = ":" + code if isinstance(code, str) and re.fullmatch(r"(?:INFO|ERROR)-\d{3}", code) else ""
        stage = "metadata" if service == "StatisticItemList" else "observations"
        raise _Unavailable("ecos_" + stage + "_rejected" + suffix)
    data = payload.get(service)
    rows = data.get("row") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > 100 or not all(isinstance(row, dict) for row in rows):
        raise _Unavailable("ecos_invalid_response")
    return rows


def _ecos_metadata(payload, indicator):
    stat, item, stat_name, item_name = _ECOS_SERIES[indicator]
    matches = [entry for entry in _ecos_payload_rows(payload, "StatisticItemList")
               if entry.get("STAT_CODE") == stat and entry.get("ITEM_CODE") == item
               and entry.get("GRP_CODE") == "Group1" and entry.get("CYCLE") == "M"
               and stat_name in str(entry.get("STAT_NAME", "")) and entry.get("ITEM_NAME") == item_name]
    if len(matches) != 1:
        raise _Unavailable("ecos_series_mapping_unverified")
    unit = matches[0].get("UNIT_NAME", "")
    if not isinstance(unit, str) or not (
            re.fullmatch(r"\d{4}=100", unit) if indicator == "KR_CPI" else unit == "천불"):
        raise _Unavailable("ecos_series_unit_mismatch")
    return {"unit": unit}


def _ecos_levels(payload, indicator, unit, start, end):
    stat, item, _, item_name = _ECOS_SERIES[indicator]
    values = {}
    for entry in _ecos_payload_rows(payload, "StatisticSearch"):
        if (entry.get("STAT_CODE") != stat or entry.get("ITEM_CODE1") != item
                or entry.get("ITEM_NAME1") != item_name
                or any(entry.get(f"ITEM_CODE{index}") for index in (2, 3, 4))
                or entry.get("UNIT_NAME") != unit):
            raise _Unavailable("ecos_observation_series_or_unit_mismatch")
        raw_period = str(entry.get("TIME", ""))
        if not re.fullmatch(r"\d{6}", raw_period):
            continue
        period = _month(raw_period[:4] + "-" + raw_period[4:])
        value = _number(entry.get("DATA_VALUE"))
        if period and start <= period <= end and value is not None:
            if indicator == "KR_CPI" and value <= 0:
                raise _Unavailable("ecos_invalid_index_level")
            if period in values and values[period] != value:
                raise _Unavailable("ecos_conflicting_observations")
            values[period] = value
    return values


def _ecos_rates(row, data, unit):
    rates = {period: round((value / data[_shift(period, -12)] - 1) * 100, 1)
             for period, value in data.items() if data.get(_shift(period, -12), 0) > 0}
    period = max(data)
    row.update(period=period, actual=rates.get(period), previous=rates.get(_shift(period, -1)),
               previous_period=_shift(period, -1), previous_source=row["source"] + " (latest revised)",
               previous_unit="%", previous_basis="YoY", raw_unit=unit,
               raw_actual=data[period], raw_year_ago=data.get(_shift(period, -12)),
               raw_year_ago_period=_shift(period, -12))
    row["status"] = "released" if row["actual"] is not None else "unavailable"
    if row["actual"] is None:
        _reason(row, "comparison_period_unavailable")
    _monthly_history(row, rates)


def _ecos(now, api_key, indicator):
    stat, item, _, _ = _ECOS_SERIES[indicator]
    row = _row(indicator, "%", "YoY", "Bank of Korea ECOS", ECOS_URL, now,
               seasonal_adjustment="NSA", series_id=f"{stat}/{item}",
               value_kind="calculated_from_official_levels", api_key_configured=bool(api_key))
    # The report bulletin hook can use bounded, public primary-source fallbacks.
    row["official_bulletin_fetch"] = True
    if not api_key:
        _reason(row, "ECOS_API_KEY_missing")
        return row
    if not re.fullmatch(r"[A-Za-z0-9]+", api_key):
        _reason(row, "ECOS_API_KEY_invalid_format")
        return row
    credential_id = hashlib.sha256(api_key.encode()).hexdigest()

    def metadata():
        payload = _request(f"{ECOS_URL}StatisticItemList/{api_key}/json/kr/1/100/{stat}")
        return _ecos_metadata(payload, indicator)

    meta, error, _ = _cached(("ecos_metadata", indicator, credential_id), metadata, now)
    if not meta:
        _reason(row, error)
        return row

    def fetch():
        payload = _request(f"{ECOS_URL}StatisticSearch/{api_key}/json/kr/1/100/{stat}/M/"
                           f"{now.year - 3}01/{now:%Y%m}/{item}")
        return _ecos_levels(payload, indicator, meta["unit"], f"{now.year - 3}-01", now.strftime("%Y-%m"))

    data, error, retrieved = _cached(("ecos", indicator, now.strftime("%Y-%m"), credential_id), fetch, now)
    row["retrieved_at"] = retrieved
    if not data:
        _reason(row, error)
        return row
    _ecos_rates(row, data, meta["unit"])
    return row


def _first(item, *keys):
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip().lower() not in {"", "none", "nan", "n/a", "-"}:
            return value
    return None


def _basis(value):
    text = str(value or "").lower().replace(" ", "")
    if text in {"level", "rate"}:
        return "level"
    if any(s in text for s in ("mom", "m/m", "month-over-month", "\uc804\uc6d4\ube44")):
        return "MoM"
    if any(s in text for s in ("yoy", "y/y", "year-over-year", "\uc804\ub144\ube44", "\uc804\ub144\ub3d9\uc6d4")):
        return "YoY"
    return "unknown"


def _unit(value):
    text = str(value or "").strip().lower()
    if text in {"%", "percent", "pct"}:
        return "%"
    if text in {"k", "thousand persons", "thousands", "\ucc9c\uba85"}:
        return "thousand persons"
    if text in {"persons", "jobs", "\uba85"}:
        return "persons"
    return text or "unknown"


def _measure(value, unit=None):
    text = str(value if value is not None else "").strip().replace(",", "")
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([%KkMm]?)", text)
    if not match:
        return None, _unit(unit)
    number, suffix = _number(match[1]), match[2].upper()
    inferred = "%" if suffix == "%" else "thousand persons" if suffix else _unit(unit)
    if suffix == "M" and number is not None:
        number *= 1000
    if unit and _unit(unit) != inferred:
        return None, _unit(unit)
    return number, inferred


def _indicator(item):
    explicit = str(item.get("indicator") or "").upper()
    if explicit in _INDICATORS:
        return explicit
    title = str(_first(item, "raw_title", "event", "\uc774\ubca4\ud2b8", "indicator") or "").lower()
    country = str(item.get("country") or "").upper()
    korean = country in {"KR", "KOR", "KRW"} or any(s in title for s in ("korea", "\ud55c\uad6d", "\uad6d\ub0b4"))
    if country and country not in {"US", "USA", "USD", "KR", "KOR", "KRW"}:
        return None
    if not korean and re.search(r"\b(euro|eurozone|german|french|uk|british|china|chinese|japan|japanese|canada|canadian|australia)\b", title):
        return None
    core = "core" in title or "\uadfc\uc6d0" in title
    if "cpi" in title or "consumer price" in title or "\uc18c\ube44\uc790\ubb3c\uac00" in title:
        return ("KR_CORE_CPI" if core else "KR_CPI") if korean else "US_CORE_CPI" if core else "US_CPI"
    if korean:
        return "KR_EXPORTS" if "export" in title or "\uc218\ucd9c" in title else None
    if "ppi" in title or "producer price" in title or "\uc0dd\uc0b0\uc790\ubb3c\uac00" in title:
        return "US_CORE_PPI" if core else "US_PPI"
    if any(s in title for s in ("nonfarm", "non-farm", "non farm", "\ube44\ub18d\uc5c5")):
        return "US_NONFARM_PAYROLLS"
    if "unemployment" in title or "\uc2e4\uc5c5\ub960" in title:
        return "US_UNEMPLOYMENT"
    if "retail sales" in title or "\uc18c\ub9e4\ud310\ub9e4" in title:
        return "US_CORE_RETAIL_SALES" if core else "US_RETAIL_SALES"
    if "federal funds rate" in title or "fed interest rate" in title:
        return "US_FED_RATE_DECISION"
    # A generic FOMC meeting/minutes is not a numeric rate decision.
    return None


def _release(value):
    text = str(value or "").strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text).isoformat(), "date"
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if at.tzinfo is not None:
            return at.isoformat(), "datetime"
    except ValueError:
        pass
    return None, None


def _future(row, now):
    at = row.get("release_at")
    if not at:
        return False
    if row.get("release_precision") == "date":
        return date.fromisoformat(at) > now.date()
    return datetime.fromisoformat(at) > now


def _event(item, now):
    indicator = _indicator(item)
    if not indicator:
        return None
    title = _first(item, "raw_title", "event", "\uc774\ubca4\ud2b8", "indicator")
    basis = _basis(_first(item, "basis", "comparison_basis") or title)
    if basis == "unknown" and indicator in {"US_UNEMPLOYMENT", "US_FED_TARGET_UPPER", "US_FED_RATE_DECISION"}:
        basis = "level"
    if basis == "unknown" and indicator == "US_NONFARM_PAYROLLS":
        basis = "MoM"
    source = _first(item, "source", "\ucd9c\ucc98")
    unit = _first(item, "unit", "actual_unit")
    actual, actual_unit = _measure(_first(item, "actual", "result", "\uc2e4\uc81c", "\uacb0\uacfc"), unit)
    forecast, forecast_unit = _measure(_first(item, "forecast", "consensus", "\uc608\uc0c1", "\ucee8\uc13c\uc11c\uc2a4"), item.get("forecast_unit") or unit)
    previous, previous_unit = _measure(_first(item, "previous", "\uc774\uc804"), item.get("previous_unit") or unit)
    resolved_unit = _unit(unit) if unit else next((u for u in (actual_unit, forecast_unit, previous_unit) if u != "unknown"), "unknown")
    at, precision = _release(_first(item, "release_at", "end_date", "\uc885\ub8cc\uc77c", "date", "\uc2dc\uc791\uc77c"))
    period_value = _first(item, "period", "observation_period", "reference_period")
    period = _month(period_value)
    if indicator == "US_FED_TARGET_UPPER" and period and len(str(period_value)) == 10:
        period = str(period_value)
    row = _row(indicator, resolved_unit, basis, source, _first(item, "source_url"), now,
               period=period, raw_title=title,
               actual=actual, forecast=forecast, previous=previous,
               release_at=at, release_precision=precision, release_source=source,
               release_source_url=_first(item, "release_source_url", "source_url"),
               forecast_source=_first(item, "forecast_source", "consensus_source") or source,
               forecast_source_url=_first(item, "forecast_source_url", "consensus_source_url", "source_url"),
               forecast_unit=forecast_unit,
               forecast_basis=_basis(item.get("forecast_basis")) if item.get("forecast_basis") else basis,
               previous_source=_first(item, "previous_source") or source,
               previous_unit=previous_unit,
               previous_basis=_basis(item.get("previous_basis")) if item.get("previous_basis") else basis,
               seasonal_adjustment=str(item.get("seasonal_adjustment") or "unknown"),
               value_kind="supplied_event", data_vintage="supplied_event")
    for key in ("schedule_rule", "schedule_rule_source", "schedule_rule_source_url", "release_time_confirmed"):
        if key in item:
            row[key] = item[key]
    if item.get("release_precision") == "schedule_rule" and precision == "datetime":
        row["release_precision"] = "schedule_rule"
    if actual is not None and actual_unit != resolved_unit:
        row["actual"] = None
        _reason(row, "actual_unit_mismatch")
    if _future(row, now):
        if row["actual"] is not None:
            _reason(row, "future_release_actual_ignored")
        row.update(actual=None, status="pending")
    elif row["actual"] is not None:
        row["status"] = "released"
    elif (precision == "date" and at == now.date().isoformat()) or str(_first(item, "status", "\uc0c1\ud0dc") or "").lower() in {"pending", "\ub300\uae30", "\uc784\ubc15", "\ub2f9\uc77c"}:
        row["status"] = "pending"
    else:
        _reason(row, "event_actual_unavailable")
    return row


def _merge_events(rows, event_rows, now):
    if event_rows is None:
        return
    if hasattr(event_rows, "to_dict") and not isinstance(event_rows, dict):
        event_rows = event_rows.head(MAX_EVENT_ROWS).to_dict("records")
    if isinstance(event_rows, dict):
        event_rows = [event_rows]
    for item in islice(event_rows, MAX_EVENT_ROWS):
        if not isinstance(item, dict):
            continue
        event = _event(item, now)
        if event is None:
            continue
        target = None
        for row in rows:
            if (row["indicator"], row["unit"], row["basis"]) != (event["indicator"], event["unit"], event["basis"]):
                continue
            if (row["seasonal_adjustment"] != "unknown" and event["seasonal_adjustment"] != "unknown"
                    and row["seasonal_adjustment"] != event["seasonal_adjustment"]):
                continue
            same_period = bool(event["period"] and row["period"] == event["period"])
            same_release = bool(event["release_at"] and row["release_at"]
                                and row["release_at"][:10] == event["release_at"][:10]
                                and (not event["period"] or same_period))
            empty = not row["period"] and not row["release_at"] and row["actual"] is None
            if (same_period or same_release or empty) and not (_future(event, now) and row["actual"] is not None):
                target = row
                break
        if target is None:
            rows.append(event)
            continue
        if target["actual"] is None:
            # Preserve why an official collector failed, even if an event has data.
            failure = target["missing_reason"]
            target.update(event)
            _reason(target, failure)
            continue
        if event["forecast"] is not None:
            for key in ("forecast", "forecast_source", "forecast_source_url", "forecast_unit", "forecast_basis"):
                target[key] = event[key]
        if not target["release_at"] and event["release_at"]:
            for key in ("release_at", "release_precision", "release_source", "release_source_url"):
                target[key] = event[key]


def _finish(row):
    row["publication_status"] = ("pending" if row["status"] == "pending" else
                                 "available" if row["actual"] is not None and row["status"] == "released"
                                 else "unconfirmed")
    if row["actual"] is None:
        _reason(row, "actual_unavailable" if row["status"] != "pending" else "awaiting_release")
    if row["forecast"] is None:
        _reason(row, "forecast_not_supplied")
    elif not row["forecast_source"]:
        _reason(row, "forecast_source_unavailable")
    if row["previous"] is None:
        _reason(row, "previous_unavailable")
    if row["release_at"] is None:
        _reason(row, "release_date_unavailable")
    if not row["period"]:
        _reason(row, "observation_period_unavailable")
    for field in ("forecast", "previous"):
        compatible = (row["unit"] != "unknown" and row["basis"] != "unknown"
                      and row[field + "_unit"] == row["unit"]
                      and row[field + "_basis"] == row["basis"])
        if row["actual"] is not None and row[field] is not None and compatible:
            if field != "forecast" or row["forecast_source"]:
                row["actual_minus_" + field] = round(row["actual"] - row[field], 6)
        elif row[field] is not None and not compatible:
            _reason(row, field + "_unit_or_basis_mismatch")


def _link_bls_calendar(row, spec, calendar, now):
    primary = {"cpi": "US_CPI", "ppi": "US_PPI", "empsit": "US_NONFARM_PAYROLLS"}
    name = {"cpi": "BLS CPI", "ppi": "BLS PPI", "empsit": "BLS Employment Situation"}[spec.group]
    source = next((source for source in calendar["sources"] if source["name"] == name), {})
    row["release_calendar_status"] = dict(source)
    row["fallback_connected"] = bool(source.get("fallback_connected"))
    matches = [event for event in calendar["events"]
               if event["indicator"] == primary[spec.group] and event.get("period") == row["period"]]
    if len(matches) == 1:
        event, = matches
        at = event["release_at"]
        row.update(release_at=at, release_precision="datetime" if "T" in at else "date",
                   release_source="BLS schedule", release_source_url=event["source_url"])
        row["missing_reason"] = ";".join(code for code in row["missing_reason"].split(";")
                                          if code and not code.startswith("release_schedule_")
                                          and code != "release_date_unavailable")
        if _future(row, now):
            row.update(actual=None, status="pending")
            row["history"] = [entry for entry in row["history"] if entry["period"] < row["period"]]
            _reason(row, "scheduled_release_not_yet_due")
    elif not row.get("release_at"):
        _reason(row, "release_schedule_" + (source.get("reason") or "period_unavailable"))


def load_economic_releases(event_rows=None, now=None, *, include_calendar=False):
    """Return normalized rows; persist validated public monthly observations only.

    With include_calendar=True, return (rows, calendar) using the same calendar
    already collected below, including unavailable-source diagnostics.

    Requests have 4-second timeouts. One BLS batch, one Census query, up to one
    FRED query, five calendar pages, and up to four ECOS metadata/data queries.
    Provider errors are not cached as success. Last verified monthly values are
    retained separately and explicitly marked stale if collection fails.
    Supplied events are bounded to 64 rows. Dates without a time/value remain
    pending throughout that UTC date; timezone-less timestamps are not guessed.
    """
    now = _clock(now)
    census_key, fred_key, ecos_key = (_api_key(name) for name in ("CENSUS_API_KEY", "FRED_API_KEY", "ECOS_API_KEY"))
    with ThreadPoolExecutor(max_workers=6) as executor:
        bls = executor.submit(_bls, now)
        retail = executor.submit(_retail, now, census_key)
        fed = executor.submit(_fed, now, fred_key)
        calendar = executor.submit(load_release_calendar, now=now, fred_api_key=fred_key)
        korea = [executor.submit(_ecos, now, ecos_key, indicator) for indicator in _ECOS_SERIES]
        rows = bls.result() + [retail.result(), fed.result()] + [future.result() for future in korea]
        calendar = calendar.result()
        for row, spec in zip(rows, _BLS_SERIES):
            _link_bls_calendar(row, spec, calendar, now)
    from stock_lab_core.economic_cache import retain_successful_observations
    rows = retain_successful_observations(rows, now)
    # A failed batch has no period until the last successful observation is restored.
    for row, spec in zip(rows, _BLS_SERIES):
        if row["status"] == "stale":
            _link_bls_calendar(row, spec, calendar, now)
    _merge_events(rows, event_rows, now)
    for row in rows:
        _finish(row)
        if row["source"] == "BLS" and "request_metadata" in row:
            row["request_metadata"]["publication_status"] = row["publication_status"]
        if row["indicator"] == "US_RETAIL_SALES" and row["status"] == "stale":
            row["observation_recency"] = "stale"
            row["publication_status"] = "unconfirmed"
        if row["indicator"] == "US_RETAIL_SALES" and row["status"] == "pending":
            row["publication_status"] = "pending"
            logging.getLogger(__name__).info("Census publication_status=pending period=%s release_at=%s",
                                            row["period"] or "unavailable", row["release_at"] or "unavailable")
        if row["indicator"] == "US_RETAIL_SALES" and "request_metadata" in row:
            row["request_metadata"].update(publication_status=row["publication_status"],
                                           observation_recency=row["observation_recency"])
    return (rows, calendar) if include_calendar else rows


load_economic_releases.clear = clear_economic_releases_cache
