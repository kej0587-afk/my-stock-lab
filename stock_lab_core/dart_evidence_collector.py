"""Bounded local-only collection. No score calculation or app imports."""

from datetime import datetime, timezone
import re
from time import perf_counter

import requests

from stock_lab_core.dart_evidence import (
    ENDPOINT, MAX_BYTES, MAX_ROWS, ROW_FIELDS, EvidenceError, canonical_bytes,
    decode_json, require, validate_bundle, validate_rows, validate_scope,
)


def fetch_statement(api_key, corp_code, year, report_code, fs_div, *, get=requests.get,
                    clock=lambda: datetime.now(timezone.utc)):
    """No retries/redirects; bounded streamed response; only allowlisted diagnostics."""
    started = perf_counter()
    attempt = {"year": year, "report_code": report_code, "fs_div": fs_div,
               "status": "failed", "cause": "transport_error", "http_status": None, "api_status": None}
    rows = None
    try:
        with get(ENDPOINT, params={"crtfc_key": api_key, "corp_code": corp_code,
                 "bsns_year": year, "reprt_code": report_code, "fs_div": fs_div},
                 timeout=(8, 15), allow_redirects=False, stream=True) as response:
            attempt["http_status"] = response.status_code
            if response.status_code != 200:
                attempt["cause"] = "http_error"
            else:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    body.extend(chunk)
                    require(len(body) <= MAX_BYTES, "response_too_large")
                    require(perf_counter() - started < 60, "response_deadline")
                data = decode_json(bytes(body))
                require(isinstance(data, dict), "invalid_response")
                status = data.get("status")
                require(isinstance(status, str) and re.fullmatch(r"[0-9]{3}", status), "invalid_api_status")
                attempt["api_status"] = status
                if status == "013":
                    require(not data.get("list"), "inconsistent_no_data")
                    attempt.update(status="no_data", cause="no_data")
                elif status != "000":
                    attempt["cause"] = "api_error"
                else:
                    raw_rows = data.get("list")
                    require(isinstance(raw_rows, list) and all(isinstance(r, dict) for r in raw_rows), "invalid_rows")
                    rows = [{k: v for k, v in row.items() if k in ROW_FIELDS} for row in raw_rows]
                    validate_rows(rows, corp_code=corp_code, year=year, report_code=report_code, fs_div=fs_div)
                    require(api_key.encode() not in canonical_bytes(rows), "credential_in_response")
                    attempt.update(status="success", cause="ok")
    except requests.RequestException:
        attempt.update(status="failed", cause="transport_error")
        rows = None
    except (EvidenceError, ValueError, TypeError):
        attempt.update(status="failed", cause="invalid_response")
        rows = None
    attempt.update(elapsed_seconds=round(perf_counter() - started, 6), retrieved_at=clock().isoformat())
    return attempt, rows


def collect_evidence(ticker, scope, api_key, corporate_codes, *, get=requests.get,
                     clock=lambda: datetime.now(timezone.utc)):
    """Map must come from a fresh official lookup, never from the upload itself."""
    require(isinstance(api_key, str) and bool(api_key), "missing_key")
    require(isinstance(ticker, str) and re.fullmatch(r"[0-9A-Z]{6}\.(KS|KQ)", ticker), "invalid_ticker")
    keys = validate_scope(scope, now=clock())
    corp_code = corporate_codes.get(ticker.split(".")[0])
    require(isinstance(corp_code, str) and re.fullmatch(r"[0-9]{8}", corp_code), "corporate_id_unavailable")
    payload = {"schema_version": 1, "collector_version": "1", "source": "dart", "endpoint": ENDPOINT,
               "ticker": ticker, "corp_code": corp_code, "requested_reports": [dict(x) for x in scope],
               "reports": [], "attempts": []}
    for year, report_code in keys:
        for fs_div in ("CFS", "OFS"):
            attempt, rows = fetch_statement(api_key, corp_code, year, report_code, fs_div, get=get, clock=clock)
            payload["attempts"].append(attempt)
            if attempt["status"] == "success":
                payload["reports"].append({"year": year, "report_code": report_code, "fs_div": fs_div,
                                           "retrieved_at": attempt["retrieved_at"], "rows": rows})
                require(len(canonical_bytes(payload)) <= MAX_BYTES, "package_too_large")
                require(sum(len(r["rows"]) for r in payload["reports"]) <= MAX_ROWS, "too_many_rows")
            if attempt["status"] != "no_data":
                break
        if attempt["status"] == "failed":
            break
    payload["collected_at"] = clock().isoformat()
    validate_bundle(payload, corporate_codes=corporate_codes, now=clock())
    return payload
