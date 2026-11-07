"""Read-only evidence presentation and explicit identity verification."""

from datetime import datetime, timedelta, timezone
import math
import re

import pandas as pd
import requests

from stock_lab_core.dart_evidence import EvidenceError, decode_json, require, stamp, validate_bundle

LABELS = {"11011": "사업보고서", "11013": "1분기", "11012": "반기", "11014": "3분기"}


def resolve_identity(ticker, corporate_loader, *, get=requests.get, now=None):
    """Called only by explicit UI action. No filename/payload controls a URL."""
    current = now or datetime.now(timezone.utc)
    require(isinstance(ticker, str) and re.fullmatch(r"[0-9A-Z]{6}\.(KS|KQ)", ticker), "invalid_ticker")
    code, market = ticker.split(".")
    codes = corporate_loader()
    require(isinstance(codes, dict) and re.fullmatch(r"[0-9]{8}", str(codes.get(code, ""))), "identity_map_required")
    until = current + timedelta(minutes=10)
    diagnostic = getattr(codes, "diagnostic", {})
    if diagnostic.get("mapping_source") == "official_snapshot":
        until = min(until, stamp(diagnostic.get("snapshot_valid_until")))
        require(until > current, "identity_expired")
    try:
        response = get(f"https://m.stock.naver.com/api/stock/{code}/basic",
                       headers={"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"},
                       timeout=5, allow_redirects=False)
        require(response.status_code == 200, "listing_unavailable")
        data = response.json()
        require(isinstance(data, dict) and data.get("itemCode") == code, "listing_mismatch")
        exchange = data.get("stockExchangeType")
        require(isinstance(exchange, dict) and exchange.get("code") == market, "listing_mismatch")
    except (requests.RequestException, ValueError, TypeError):
        raise EvidenceError("listing_unavailable_or_mismatch") from None
    return {"ticker": ticker, "codes": {code: codes[code]}, "checked_at": current.isoformat(),
            "valid_until": until.isoformat(), "source": "DART 기업코드 · 네이버 상장시장"}


def verified_codes(identity, ticker, now):
    if not isinstance(identity, dict) or identity.get("ticker") != ticker:
        return None
    try:
        if stamp(identity["checked_at"]) <= now < stamp(identity["valid_until"]):
            return identity["codes"]
    except (ValueError, KeyError, TypeError):
        pass
    return None


def preview_file(raw, ticker, *, now=None):
    payload = decode_json(raw)
    summary = validate_bundle(payload, now=now)
    require(payload["ticker"] == ticker, "selected_ticker_mismatch")
    return payload, summary


def coverage_rows(payload):
    rows = []
    for scope in payload["requested_reports"]:
        attempts = [a for a in payload["attempts"] if all(a[k] == scope[k] for k in ("year", "report_code"))]
        last = attempts[-1] if attempts else {}
        rows.append({"사업연도": scope["year"], "보고서": LABELS[scope["report_code"]],
                     "수집 상태": {"success": "수집", "no_data": "공급처 자료 없음", "failed": "조회 실패"}.get(last.get("status"), "미요청"),
                     "연결/별도": last.get("fs_div", "-"), "API 상태": last.get("api_status") or "-"})
    return rows


def metric_rows(payload, extract_metrics):
    """Use the existing app parser; show cumulative reports, never score them."""
    result = []
    for report in payload["reports"]:
        values = extract_metrics(pd.DataFrame(report["rows"]), report["year"], report["report_code"])
        currencies = sorted({r.get("currency") for r in report["rows"] if r.get("currency")})
        row = {"사업연도": report["year"], "보고서": LABELS[report["report_code"]],
               "금액 기준": "연간" if report["report_code"] == "11011" else "누적 (단일 분기 아님)",
               "연결/별도": report["fs_div"], "통화": ", ".join(currencies) or "미확인"}
        missing = []
        for label, field in (("매출", "revenue"), ("영업이익", "op_income"), ("순이익", "net_income"),
                             ("영업현금흐름", "ocf"), ("자본", "equity"), ("부채", "liabilities")):
            value = values.get(field)
            valid = not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)
            row[label] = value if valid else None
            if not valid:
                missing.append(label)
        row["미수집"] = ", ".join(missing) or "없음"
        row["공시 원문"] = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + report["rows"][0]["rcept_no"]
        result.append(row)
    return result
