"""Strict, score-free DART evidence files. No network, UI or database imports."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re


ENDPOINT = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
MAX_BYTES = 8 * 1024 * 1024
MAX_REPORTS = 25
MAX_ROWS = 25000
REPORT_CODES = {"11011", "11013", "11012", "11014"}
ROW_FIELDS = frozenset("""rcept_no reprt_code bsns_year corp_code sj_div sj_nm
    account_id account_nm account_detail thstrm_nm thstrm_amount thstrm_add_amount
    frmtrm_nm frmtrm_amount frmtrm_q_nm frmtrm_q_amount frmtrm_add_amount
    bfefrmtrm_nm bfefrmtrm_amount ord currency fs_div""".split())
CAUSES = {"ok", "no_data", "transport_error", "http_error", "api_error", "invalid_response"}


class EvidenceError(ValueError):
    """Messages contain only fixed codes, never uploaded values or credentials."""


def require(condition, code):
    if not condition:
        raise EvidenceError(code)


def fields(value, required, optional=()):
    require(isinstance(value, dict), "object_required")
    require(set(required) <= value.keys() <= set(required) | set(optional), "invalid_fields")


def stamp(value):
    try:
        require(isinstance(value, str) and len(value) <= 40, "invalid_timestamp")
        parsed = datetime.fromisoformat(value)
        require(parsed.utcoffset() == timedelta(0), "utc_timestamp_required")
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise EvidenceError("invalid_timestamp") from None


def report_key(value):
    year, code = value.get("year"), value.get("report_code")
    require(isinstance(year, str) and re.fullmatch(r"20[0-9]{2}", year)
            and 2015 <= int(year) <= 2099, "invalid_year")
    require(isinstance(code, str) and code in REPORT_CODES, "invalid_report_code")
    return year, code


def validate_scope(scope, *, now=None):
    current = now or datetime.now(timezone.utc)
    require(isinstance(scope, list) and 0 < len(scope) <= MAX_REPORTS, "invalid_scope")
    keys = []
    for request in scope:
        fields(request, {"year", "report_code"})
        key = report_key(request)
        require(int(key[0]) <= current.year and key not in keys, "invalid_scope")
        keys.append(key)
    return keys


def validate_rows(rows, *, corp_code, year, report_code, fs_div):
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_ROWS, "invalid_rows")
    receipts, currencies = set(), set()
    required = {"rcept_no", "corp_code", "bsns_year", "reprt_code", "sj_div", "account_id", "account_nm"}
    for row in rows:
        fields(row, required, ROW_FIELDS - required)
        require(all(v is None or isinstance(v, str) and len(v) <= 4096 for v in row.values()), "invalid_row_value")
        require((row["corp_code"], row["bsns_year"], row["reprt_code"]) ==
                (corp_code, year, report_code), "row_identity_mismatch")
        require(isinstance(row["rcept_no"], str) and re.fullmatch(r"[0-9]{14}", row["rcept_no"]), "invalid_receipt")
        require(row["sj_div"] in {"BS", "IS", "CIS", "CF", "SCE"} and bool(row["account_nm"])
                and isinstance(row["account_id"], str), "invalid_account")
        require("fs_div" not in row or row["fs_div"] == fs_div, "basis_mismatch")
        receipts.add(row["rcept_no"])
        if row.get("currency"):
            require(re.fullmatch(r"[A-Z]{3}", row["currency"]), "invalid_currency")
            currencies.add(row["currency"])
    require(len(receipts) == 1 and len(currencies) <= 1, "mixed_report_basis")


def canonical_bytes(payload):
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise EvidenceError("invalid_json") from None


def validate_bundle(payload, *, now=None, corporate_codes=None):
    """Validate without mutation. Caller must supply a currently usable official map.

    With no map, inspection is possible but identity_verified/eligible stay false.
    SHA-256 is content identity, not proof of issuer authenticity.
    """
    require(len(canonical_bytes(payload)) <= MAX_BYTES, "file_too_large")
    fields(payload, {"schema_version", "collector_version", "source", "endpoint", "ticker",
                     "corp_code", "collected_at", "requested_reports", "reports", "attempts"})
    require(type(payload["schema_version"]) is int and payload["schema_version"] == 1, "unsupported_version")
    require(payload["collector_version"] == "1" and payload["source"] == "dart"
            and payload["endpoint"] == ENDPOINT, "invalid_source")
    ticker, corp = payload["ticker"], payload["corp_code"]
    require(isinstance(ticker, str) and re.fullmatch(r"[0-9A-Z]{6}\.(KS|KQ)", ticker), "invalid_ticker")
    require(isinstance(corp, str) and re.fullmatch(r"[0-9]{8}", corp), "invalid_corporate_id")
    identity_verified = corporate_codes is not None
    if identity_verified:
        require(corporate_codes.get(ticker.split(".")[0]) == corp, "corporate_id_mismatch")
    current = now or datetime.now(timezone.utc)
    require(current.tzinfo is not None, "timezone_required")
    collected = stamp(payload["collected_at"])
    age = current - collected
    require(age >= -timedelta(minutes=5), "future_collection")
    scope, reports, attempts = (payload[k] for k in ("requested_reports", "reports", "attempts"))
    keys = validate_scope(scope, now=current)
    require(isinstance(reports, list) and len(reports) <= len(keys), "invalid_reports")
    require(isinstance(attempts, list) and 0 < len(attempts) <= 2 * len(keys), "invalid_attempts")
    index, expected_basis, stopped = 0, "CFS", False
    successes = {}
    previous_time = None
    for attempt in attempts:
        fields(attempt, {"year", "report_code", "fs_div", "status", "cause", "http_status",
                         "api_status", "elapsed_seconds", "retrieved_at"})
        require(not stopped and index < len(keys), "unexpected_attempt")
        key = report_key(attempt)
        require(key == keys[index] and attempt["fs_div"] == expected_basis, "attempt_order_mismatch")
        elapsed = attempt["elapsed_seconds"]
        require(type(elapsed) in (float, int) and math.isfinite(elapsed) and elapsed >= 0, "invalid_duration")
        request_time = stamp(attempt["retrieved_at"])
        require(request_time <= collected and (previous_time is None or request_time >= previous_time),
                "invalid_request_time")
        previous_time = request_time
        http, api = attempt["http_status"], attempt["api_status"]
        require(http is None or type(http) is int and 100 <= http <= 599, "invalid_http_status")
        require(api is None or isinstance(api, str) and re.fullmatch(r"[0-9]{3}", api), "invalid_api_status")
        status, cause = attempt["status"], attempt["cause"]
        require(isinstance(cause, str) and cause in CAUSES, "invalid_cause")
        if status in ("success", "no_data"):
            require(http == 200 and api == ("000" if status == "success" else "013")
                    and cause == ("ok" if status == "success" else "no_data"), "inconsistent_status")
            if status == "success":
                successes[key] = attempt
            if status == "no_data" and expected_basis == "CFS":
                expected_basis = "OFS"
            else:
                index += 1
                expected_basis = "CFS"
        else:
            require(status == "failed" and cause not in {"ok", "no_data"}, "invalid_failure")
            if cause == "http_error":
                require(http is not None and http != 200 and api is None, "inconsistent_failure")
            elif cause == "api_error":
                require(http == 200 and api is not None and api not in {"000", "013"}, "inconsistent_failure")
            elif cause == "transport_error":
                require(api is None, "inconsistent_failure")
            stopped = True
    require(stopped or index == len(keys), "unaccounted_scope")
    seen, total_rows = set(), 0
    for report in reports:
        fields(report, {"year", "report_code", "fs_div", "retrieved_at", "rows"})
        key = report_key(report)
        require(key in successes and key not in seen, "unexpected_report")
        attempt = successes[key]
        require((report["fs_div"], report["retrieved_at"]) ==
                (attempt["fs_div"], attempt["retrieved_at"]), "report_provenance_mismatch")
        validate_rows(report["rows"], corp_code=corp, year=key[0], report_code=key[1], fs_div=report["fs_div"])
        total_rows += len(report["rows"])
        seen.add(key)
    require(seen == set(successes) and total_rows <= MAX_ROWS, "incomplete_reports")
    freshness = "recent" if age <= timedelta(days=1) else "stale" if age <= timedelta(days=7) else "expired"
    return {"sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
            "complete": not stopped, "identity_verified": identity_verified, "freshness": freshness,
            "eligible": not stopped and bool(reports) and identity_verified and freshness != "expired",
            "report_count": len(reports), "request_count": len(attempts), "row_count": total_rows,
            "unattempted_count": len(keys) - index - (1 if stopped else 0)}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def decode_json(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, "file_too_large")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: require(False, "nonfinite_json"))
    except (ValueError, UnicodeError, RecursionError):
        raise EvidenceError("invalid_json") from None


def read_bundle(path, **validation):
    with Path(path).open("rb") as handle:
        payload = decode_json(handle.read(MAX_BYTES + 1))
    return payload, validate_bundle(payload, **validation)


def write_bundle(path, payload, **validation):
    """Exclusive create: neither successful nor failed runs can overwrite a file."""
    summary = validate_bundle(payload, **validation)
    raw = canonical_bytes(payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        try:
            handle.write(raw)
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
    return summary
