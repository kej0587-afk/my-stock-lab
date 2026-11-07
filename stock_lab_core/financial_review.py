"""Read-only financial evidence review; never calculates or persists scores."""

from collections.abc import Mapping
from datetime import datetime, timezone
import math
import re

from stock_lab_core.financial_freshness import financial_basis


class DartProviderError(RuntimeError):
    """Safe provider error without a credential-bearing request URL."""


def dart_status_error(status):
    labels = {"010": "키 미등록", "011": "키 사용 중지", "012": "접근 IP 제한",
              "020": "요청 한도 초과", "100": "요청 인자 오류", "101": "접근 오류",
              "800": "서비스 점검", "900": "서비스 오류", "901": "키 사용기간 만료"}
    code = str(status or "unknown")
    if not re.fullmatch(r"\d{3}", code):
        code = "unknown"
    return DartProviderError(f"DART status {code}: {labels.get(code, '응답 상태 확인 필요')}")


def stored_financial_diagnostic(meta):
    """Explain provenance without promoting a missing/failed input to success."""
    meta = meta if isinstance(meta, Mapping) else {}
    notes = meta.get("notes") if isinstance(meta.get("notes"), Mapping) else {}
    reason = str(notes.get("reason") or "")
    if meta.get("auto_score") is None:
        cause = "자동 계산 기록 없음 · 수동 점수 사용" if meta.get("manual_score") is not None else "자동 계산 기록 없음 · 임시 점수 사용"
    elif notes.get("ok") is False:
        parts = []
        if "402" in reason:
            parts.append("FMP 구독/권한 제한(HTTP 402)")
        if "under 2 years" in reason:
            parts.append("SEC 파서가 사용 가능한 연간 자료 2개 미확보")
        if "DART annual financials: 0 years" in reason:
            parts.append("과거 DART 추출 0건 · 당시 상세 오류 미저장")
        for marker, label in (("SEC User-Agent missing", "SEC 연락처 User-Agent 미설정"),
                              ("DART API 키 없음", "DART API 키 미설정"),
                              ("DART corp_code 매핑 실패", "DART 기업코드 매핑 실패"),
                              ("DART 전송 실패", "DART 통신 실패"),
                              ("DART 응답 JSON 오류", "DART 응답 형식 오류"),
                              ("unsupported_statement_forms", "SEC 공시 형식 미지원(20-F/6-K 등)")):
            if marker in reason:
                parts.append(label)
        status = re.search(r"DART status (\d{3})", reason)
        if status:
            parts.append(str(dart_status_error(status.group(1))))
        cause = " / ".join(parts) or "저장된 조회 실패 · 원자료 재확인 필요"
        if meta.get("source") == "naver_fallback":
            cause += " · Naver 간이 추정"
    else:
        cause = "저장 자료 사용 · 최신 발표 반영 여부 별도 확인"
    return {"자료 경로": str(meta.get("source") or "미저장"), "입력 사유": cause,
            "점수 적용": "수동 점수 우선" if meta.get("manual_score") is not None else "기존 저장/임시 점수 유지"}


def sec_statement_coverage(company_facts):
    """Explain rejected formats; do not treat their periods as parsed statements."""
    facts = company_facts.get("facts", {})
    forms = set()
    for namespace in facts.values():
        for concept in namespace.values():
            for rows in concept.get("units", {}).values():
                forms.update(row.get("form") for row in rows if isinstance(row, Mapping) and row.get("form"))
    unsupported_only = bool(forms) and not forms.intersection({"10-K", "10-K/A", "10-Q", "10-Q/A"})
    return {"namespaces": sorted(facts), "forms": sorted(forms),
            "limitation": "unsupported_statement_forms" if unsupported_only else "insufficient_parsed_annual_records"}


def build_financial_review(meta, financials, *, checked_at=None):
    """Compare stored input to a provider response, not to an assumed release date."""
    fin = financials if isinstance(financials, Mapping) else {}
    metrics = {"annual_records": fin.get("annual", []), "quarter_records": fin.get("quarter", [])}
    provider_basis = financial_basis({"auto_score": 0, "metrics": metrics})
    rows = []
    for kind, key in (("연간", "annual"), ("분기", "quarter")):
        for record in fin.get(key, []) or []:
            row = {"구분": kind, "보고기간": financial_basis({"auto_score": 0, "metrics": {
                "annual_latest" if key == "annual" else "quarter_latest": record}})["재무자료기간"]}
            missing = []
            for label, field in (("매출", "revenue"), ("영업이익", "op_income"), ("순이익", "net_income"),
                                 ("영업현금흐름", "ocf"), ("자본", "equity"), ("부채", "liabilities")):
                value = record.get(field)
                try:
                    valid = value is not None and not isinstance(value, bool) and math.isfinite(float(value))
                except (TypeError, ValueError, OverflowError):
                    valid = False
                row[label] = float(value) if valid else None
                if not valid:
                    missing.append(label)
            row["통화"] = record.get("unit") or record.get("currency") or "미확인"
            row["미수집"] = ", ".join(missing) or "없음"
            rows.append(row)
    return {"확인 시각": checked_at or datetime.now(timezone.utc).isoformat(),
            "저장 점수 기준": financial_basis(meta)["재무자료기간"],
            "공급처 조회 기간": provider_basis["재무자료기간"],
            "공급처": str(fin.get("source") or "미확인"),
            "조회 상태": "원자료 조회됨 · 최신 발표 전체 반영 보장은 아님" if fin.get("ok") else "조회 실패 · 저장 점수 유지",
            "원자료": rows,
            "실패 사유": stored_financial_diagnostic({"auto_score": 0, "source": fin.get("source"),
                "notes": {"ok": False, "reason": fin.get("reason")}})["입력 사유"] if not fin.get("ok") else ""}
