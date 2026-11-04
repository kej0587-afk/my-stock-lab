"""Render the calendar block from collected evidence; never fetch or infer results."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, records, text, first, stamp, safe_link, _cell
from stock_lab_core.report_presentation import kst_time

register_loaded_source(__name__, __file__)


def upcoming_calendar_lines(context, news, event_rows, now, earnings_pipeline):
    lines, missing = [], []
    lines.extend(["", "## 다가오는 일정"])
    from stock_lab_core.report_policy_catalysts import policy_calendar_lines
    lines.extend(policy_calendar_lines(context, news, now))
    lines.append("")
    lines.append("기업 실적 일정은 연결·확인된 IR 공지만 포함합니다. 전체 보유·관심종목의 일정이 아니므로 목록에 없다고 미발표/일정 없음으로 판단하지 않습니다.")
    scheduled = []
    calendar_rows = records(context.get("calendar_events", event_rows))
    next_monthly = {}
    for row in calendar_rows:
        indicator = row.get("indicator")
        day = text(row.get("date"))
        if indicator in {"US_CPI", "US_PPI", "US_NONFARM_PAYROLLS"} and day >= now.date().isoformat():
            if indicator not in next_monthly or day < next_monthly[indicator]:
                next_monthly[indicator] = day
    for row in calendar_rows:
        date_text = text(first(row, "date", "날짜", "일자", "시작일", "발표일"))
        if row.get("event_status"):
            continue
        dt = stamp(date_text)
        title = text(first(row, "이벤트", "event", "title"))
        is_next_monthly = next_monthly.get(row.get("indicator")) == date_text
        horizon = 90 if is_next_monthly else 45 if "FOMC" in title.upper() else 7
        if dt and text(first(row, "source", "출처")) != "fallback" and now.date() <= dt.date() <= (now + timedelta(days=horizon)).date():
            scheduled.append((date_text, row))
    if scheduled:
        lines.extend(["일정·남은 일수 | 발표·콜 시각 | 공식 출처", "--- | --- | ---"])
    for date_text, row in sorted(scheduled, key=lambda item: item[0]):
        title = text(first(row, '이벤트', 'event', 'title'))
        source = text(first(row, '출처', 'source')) or '출처 미제공'
        link = safe_link(row.get("source_url"))
        days = (stamp(date_text).date() - now.date()).days
        release_at = text(row.get("release_at")) or date_text
        display = kst_time(release_at) if "T" in release_at or " " in release_at else date_text + " (발표 시각 미제공)"
        if row.get("indicator") == "US_FED_RATE_DECISION" and len(release_at) == 10:
            # Regular FOMC statement convention; not an individually confirmed timestamp.
            standard = datetime.fromisoformat(release_at + "T14:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
            display = kst_time(standard.isoformat()) + " (미국 14:00 ET 표준 적용, 예외 시각 미확인)"
            days = (standard.astimezone(KST).date() - now.date()).days
        if row.get("session_timing") == "after_market_close":
            local_close = datetime.fromisoformat(date_text + "T16:00:00").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(KST)
            display = f"미국 {date_text} 장 마감 후 / 한국 {local_close:%Y-%m-%d} 새벽(발표 분 시각 미확정)"
            days = (local_close.date() - now.date()).days
            if row.get("conference_call_at"):
                display += " · 실적 콜 " + kst_time(row["conference_call_at"])
        if row.get("release_precision") == "schedule_rule":
            display += " (BLS 표준 08:30 ET 적용, 예외 시각 미확인)"
        lines.append(" | ".join(_cell(value) for value in (f"{title} · D-{days}", display, f"[{source}]({link})" if link else source)))
    if not scheduled:
        sources = records(context.get("calendar_sources"))
        connected = [row["name"] for row in sources if row.get("status") == "connected"]
        lines.append("- 연결된 일정 범위에서 향후 7일 항목 미수집(일정 없음으로 단정하지 않음): " + ", ".join(connected) if connected else "- 일정 미연결: 공식 캘린더 수집 실패/자료 미제공. 일정 없음으로 판단하지 않습니다.")
        if not connected:
            missing.append("향후 7일 확정 일정 미연결")
    failed_bls = []
    for source in records(context.get("calendar_sources")):
        if source.get("status") == "connected" and source.get("provider") == "FRED":
            continue
        elif source.get("status") != "connected":
            if text(source.get("name")).startswith("BLS "):
                failed_bls.append(source["name"])
                continue
            lines.append(f"- 일정 미연결: {source['name']} · {source.get('reason', '응답 없음')}")
            missing.append(f"공식 일정: {source['name']} · {source.get('reason', '응답 없음')}")
            if source.get("fallback_reason"):
                lines.append(f"- FRED 일정 보완 실패: {source['name']} · {source['fallback_reason']}")
    if failed_bls:
        note = "미국 CPI·PPI·고용 중 일부 다음 확정 발표일 미연결: 공식 캘린더/FRED 보완 미확보(일정 없음이 아님)"
        lines.append("- " + note)
        missing.append(note)
    from stock_lab_core.report_calendar import earnings_calendar_lines
    lines.extend(earnings_calendar_lines(context, now, pipeline=earnings_pipeline))
    return lines, missing
