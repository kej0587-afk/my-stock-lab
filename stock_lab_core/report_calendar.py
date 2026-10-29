"""Corporate release/call coverage, separate from macro schedule rendering."""

from stock_lab_core.report_evidence import _cell, records, safe_link, stamp, text
from stock_lab_core.report_presentation import kst_time
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.earnings_reconciliation import METRIC_LABELS, reconcile_earnings

register_loaded_source(__name__, __file__)


def earnings_calendar_lines(context, now):
    events = [r for r in reconcile_earnings(context, now) if r.get("event_status")]
    sources = records(context.get("earnings_sources"))
    lines = ["", "**기업 실적 촉매**", "기업·상태 | 발표일 / 콜 시각 | 근거·연결 범위", "--- | --- | ---"]
    count = 0
    result_details = []
    for row in events:
        day = stamp(row.get("date"))
        if day is None or not -30 <= (day.date() - now.date()).days <= 45:
            continue
        status = {"released": "공식 결과 발표 확인", "reported_results": "실적 보도 확인·공식 대조 대기",
                  "scheduled": "예정", "elapsed_unconfirmed": "예정일 경과·결과 미확인"}.get(row["event_status"], "미확인")
        time = text(row.get("date")) + " (발표 분 시각 미제공)"
        if row.get("release_precision") == "datetime" and row.get("release_at"):
            time = kst_time(row["release_at"])
        if row.get("event_status") == "reported_results":
            time += " · 예정일, 실제 발표시각 미확인"
        elif row.get("event_kind") == "conference_call":
            time = kst_time(row["conference_call_at"]) if row.get("conference_call_at") else row["date"] + " 콜(시각 미확인)"
            time += " · 결과 공개일은 별도 미확인"
        elif row.get("conference_call_at"):
            time += " / 콜 " + kst_time(row["conference_call_at"])
        source = safe_link(row.get("result_source_url") or row.get("source_url"))
        label = row.get("event", row.get("ticker", "기업 미확인"))
        source_label = "결과 보도" if row.get("result_confirmation") == "news_report" else "공식 결과" if row.get("result_confirmation") else "공식 IR"
        provenance = f"[{source_label}]({source})" if source else "공식 출처 미연결"
        if row.get("source_kind") == "verified_snapshot" and row.get("result_confirmation") in {None, "", "official_snapshot"}:
            provenance += " · 확인한 공지 보관값"
        if row.get("result_stale"):
            provenance += " · 수집 실패, 마지막 확인 결과 " + kst_time(row.get("result_checked_at"))
        elif row.get("result_checked_at"):
            provenance += " · 확인 " + kst_time(row["result_checked_at"])
        provenance += " · 범위 만료 " + str(row.get("coverage_expires_at", "미제공"))
        lines.append(" | ".join(_cell(v) for v in (label + " · " + status, time, provenance)))
        count += 1
        if row.get("result_metrics"):
            result_details.extend(_result_detail_lines(row))
    if not count:
        lines.append("기업 실적 | 미연결 | 확정 공지·결과 자료 미확보, 일정 없음이 아님")
    lines.append("")
    if result_details:
        lines.extend(["실제 실적·회사 전망·주가 반응은 별도 항목입니다. 전년비 성장과 컨센서스 상회는 다르며, 예상치 미연결 항목은 서프라이즈로 판정하지 않습니다.", ""])
    lines.extend(result_details)
    missing = [r.get("ticker", r.get("name", "")) for r in sources if r.get("status") != "connected"]
    if missing:
        lines.append("미연결 범위: " + ", ".join(dict.fromkeys(missing)) + ". 지원 기업·공지 범위 밖 또는 조회 실패이며 추정 일정으로 채우지 않습니다.")
        lines.append("")
    diagnostics = []
    for row in records(context.get("earnings_result_sources")):
        reason = text(row.get("reason"))
        if row.get("status") in {"connected", "fallback"} or reason in {"future_event", "refresh_disabled"}:
            continue
        message = ("HTTP " + reason[5:] if reason.startswith("http_") else
                   "요청 시간초과/통신 실패" if reason.startswith("request_failed:") or reason == "request_deadline" else
                   "결과 원문·분기·발표시각 대조 실패" if row.get("attempted") else "해당 기업·분기 결과 출처 미연결")
        diagnostics.append(text(row.get("ticker")) + " " + message)
    if diagnostics:
        lines.extend(["공식 결과 수집: " + " / ".join(dict.fromkeys(diagnostics)) + ". 발표 여부와 세부 수치의 수집 상태는 별도입니다.", ""])
    lines.append("최근 발표는 예정 목록에서 삭제하지 않고 구분 보존합니다. 메타·테슬라는 이전의 ‘향후 일정만’ 필터로 숨겨졌던 항목입니다. 다음 분기 일정까지 자동 확보한 것은 아닙니다.")
    return lines


def _result_detail_lines(row):
    """Keep each result dimension visible without a wide six-metric table."""
    name = text(row.get("event", row.get("ticker", "기업")))
    lines = [f"**{name} · {row.get('fiscal_period', '')} 결과 대조**", "항목 | 확인 내용 | 근거", "--- | --- | ---"]
    for key, label in METRIC_LABELS.items():
        metric = row["result_metrics"].get(key, {})
        detail = text(metric.get("text")) or "미연결"
        url = safe_link(metric.get("source_url"))
        source_label = "보도" if key == "price_reaction" and metric.get("status") == "reported" else "공식 원문"
        source = f"[{source_label}]({url})" if url else text(metric.get("source")) or "미연결"
        if metric.get("observed_at"):
            source += " · " + kst_time(metric["observed_at"])
        lines.append(" | ".join(_cell(v) for v in (label, detail, source)))
    lines.append("")
    return lines
