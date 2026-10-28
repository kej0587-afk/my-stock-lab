"""Corporate release/call coverage, separate from macro schedule rendering."""

from stock_lab_core.report_evidence import _cell, records, safe_link, stamp, text
from stock_lab_core.report_presentation import kst_time
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def earnings_calendar_lines(context, now):
    events = [r for r in records(context.get("calendar_events")) if r.get("event_status")]
    sources = records(context.get("earnings_sources"))
    lines = ["", "**기업 실적 촉매**", "기업·상태 | 발표일 / 콜 시각 | 근거·연결 범위", "--- | --- | ---"]
    count = 0
    for row in events:
        day = stamp(row.get("date"))
        if day is None or not -30 <= (day.date() - now.date()).days <= 45:
            continue
        status = {"released": "결과 발표 확인", "scheduled": "예정", "elapsed_unconfirmed": "예정일 경과·결과 미확인"}.get(row["event_status"], "미확인")
        time = text(row.get("date")) + " (발표 분 시각 미제공)"
        if row.get("event_kind") == "conference_call":
            time = kst_time(row["conference_call_at"]) if row.get("conference_call_at") else row["date"] + " 콜(시각 미확인)"
            time += " · 결과 공개일은 별도 미확인"
        elif row.get("conference_call_at"):
            time += " / 콜 " + kst_time(row["conference_call_at"])
        source = safe_link(row.get("source_url"))
        label = row.get("event", row.get("ticker", "기업 미확인"))
        provenance = f"[공식 IR]({source})" if source else "공식 출처 미연결"
        if row.get("source_kind") == "verified_snapshot":
            provenance += " · 확인한 공지 보관값"
        provenance += " · 범위 만료 " + str(row.get("coverage_expires_at", "미제공"))
        lines.append(" | ".join(_cell(v) for v in (label + " · " + status, time, provenance)))
        count += 1
    if not count:
        lines.append("기업 실적 | 미연결 | 확정 공지·결과 자료 미확보, 일정 없음이 아님")
    lines.append("")
    missing = [r.get("ticker", r.get("name", "")) for r in sources if r.get("status") != "connected"]
    if missing:
        lines.append("미연결 범위: " + ", ".join(dict.fromkeys(missing)) + ". 지원 기업·공지 범위 밖 또는 조회 실패이며 추정 일정으로 채우지 않습니다.")
        lines.append("")
    lines.append("최근 발표는 예정 목록에서 삭제하지 않고 구분 보존합니다. 메타·테슬라는 이전의 ‘향후 일정만’ 필터로 숨겨졌던 항목입니다. 다음 분기 일정까지 자동 확보한 것은 아닙니다.")
    return lines
