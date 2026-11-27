"""Read-only Korean filing actuals, separate from announcement catalysts."""

from datetime import timedelta
from decimal import Decimal

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, safe_link, stamp

register_loaded_source(__name__, __file__)


def _packets(pipeline):
    now = stamp(pipeline["generated_at"])
    selected = [packet for packet in pipeline["packets"] if packet["event"].get("financial_values")
                and (day := stamp(packet["date"])) is not None
                and now - timedelta(days=200) <= day <= now]
    return sorted(selected, key=lambda p: (p["relationship"] == "보유", p["relationship"] == "관심·점검", p["date"]), reverse=True)


def _value(metric, column):
    value = metric.get(column)
    return f"{Decimal(value):,} {metric['currency']}" if value is not None else "미연결"


def readable_krw(text):
    """"104,615,483,000,000 KRW" -> "104.62조원" for reading; exact won values stay in 상세 근거."""
    import re

    def short(match):
        value = Decimal(match[1].replace(",", ""))
        size = abs(value)
        if size >= Decimal(10) ** 12:
            return f"{value / Decimal(10) ** 12:,.2f}조원"
        if size >= Decimal(10) ** 8:
            return f"{value / Decimal(10) ** 8:,.0f}억원"
        return f"{value:,}원"
    return re.sub(r"(-?\d[\d,]*(?:\.\d+)?) KRW\b", short, str(text))


_FAILURE_WORDS = ("한도", "실패", "시간초과", "HTTP", "오류", "제한")


def filing_gap_line(pipeline):
    """Why Korean filing actuals are absent: 미계산 / 일부 조회 실패 / 공식값 없음 / 확인 결과 0개.

    Counts come from the pipeline's own coverage gaps and filing packets; nothing is estimated.
    Returns "" when every requested Korean issuer has filing actuals.
    """
    coverage = pipeline.get("coverage") or {}
    gaps = [row for row in coverage.get("missing") or [] if str(row.get("ticker", "")).endswith((".KS", ".KQ"))]
    # A filing was found but its statements were not connected (reason kept on the event).
    held = [p for p in pipeline.get("packets") or [] if p["event"].get("source_kind") == "dart_discovered_report"
            and not p["event"].get("financial_values")]
    connected = len(_packets(pipeline))
    if not gaps and not held:
        if connected or coverage.get("summary_available"):
            return "" if connected else "한국 공시 실제치: 확인 결과 0개(대상 기업의 최근 200일 정기보고서 실제치 없음)."
        return "한국 공시 실제치: 오늘 점검 미계산 · 대상 기업 미정(오늘 점검 후 다시 만들면 연결됩니다)."
    reasons = {}
    for row in gaps:
        reason = str(row.get("reason") or "사유 미기록")
        reasons[reason] = reasons.get(reason, 0) + 1
    for packet in held:
        why = packet["event"].get("financial_reason")
        reason = f"정기보고서 확인·수치 연결 보류({why})" if why else "정기보고서 확인·재무제표 수치 미수집"
        reasons[reason] = reasons.get(reason, 0) + 1
    failed = sum(count for reason, count in reasons.items() if any(word in reason for word in _FAILURE_WORDS))
    absent = sum(reasons.values()) - failed
    kinds = ([f"일부 조회 실패 {failed}개"] if failed else []) + ([f"공식값 없음·미연결 {absent}개"] if absent else [])
    return ("한국 공시 실제치: 연결 " + f"{connected}개 · " + " · ".join(kinds) + " — "
            + " / ".join(f"{reason} {count}개" for reason, count in reasons.items())
            + ". 빠진 기업의 수치를 추정하거나 다른 기간 값으로 채우지 않습니다.")


def filing_actual_lines(pipeline, *, detailed=False):
    packets = _packets(pipeline)
    gap = filing_gap_line(pipeline)
    if not packets:
        return ["", "**한국 공시 실제 실적 · 발표일과 별도**", gap, ""] if gap and _has_kr_scope(pipeline) else []
    lines = ["", "**한국 공시 실제 실적 · 발표일과 별도**"]
    if not detailed:
        lines.extend(["기업·보고기간 | 확인된 실제치 | 해석·남은 확인", "--- | --- | ---"])
        for packet in packets[:3]:
            values = packet["event"]["financial_values"]
            facts = [values[key]["text"] for key in ("revenue", "operating_profit", "net_income")
                     if values[key].get("status") == "reported"]
            identity = f"{packet['name']}({packet['ticker']}) · {packet['fiscal_period']} · 접수 {packet['date']}"
            source = safe_link(packet["source_url"])
            facts = readable_krw(" / ".join(facts)) or "직접 공시된 손익 수치 미연결"
            reading = "손익과 누적 영업현금흐름을 함께 확인합니다. 전망·예상치 대조 전에는 실적 상회/하회나 주가 방향을 판단하지 않습니다."
            lines.append(" | ".join(_cell(v) for v in (identity, facts + f" [공시]({source})", reading)))
        lines.extend(["", "보유·관심 종목 우선 최대 3개입니다. 분기값을 누적값으로 대체하거나 역산하지 않았으며, 공시 접수를 새로운 실적 발표로 해석하지 않습니다. "
                      "조·억원은 공시 원 단위 값을 반올림해 읽기 쉽게 표시한 것이며, 원 단위 값은 상세 근거의 실적 표에 있습니다.", ""])
        return lines + ([gap, ""] if gap else [])
    lines.extend(["손익계산서의 3개월 값과 누적값은 별도 열입니다. 현금흐름은 누적으로 보며, 연간 보고서는 4분기값으로 바꾸지 않습니다.", ""])
    for packet in packets:
        event = packet["event"]
        basis = "연결재무제표" if event["financial_discovery"]["fs_div"] == "CFS" else "별도재무제표 · 연결 자료 없음"
        lines.extend([f"**{packet['name']}({packet['ticker']}) · {packet['fiscal_period']}**",
                      f"보고기간 말 {event['reporting_period_end_month']} · {basis} · 공시 접수일 {packet['date']} · 실적 발표일 미확인 · [DART 공시]({safe_link(packet['source_url'])})",
                      "항목 | 분기(3개월) | 누적 / 연간 | 범위·미연결 사유", "--- | --- | --- | ---"])
        for key, metric in event["financial_values"].items():
            scope = metric.get("period_scope")
            cumulative = _value(metric, "annual_value" if scope == "annual" else "cumulative_value")
            note = "연간·4분기값 아님" if scope == "annual" else "누적·분기 역산 안 함" if scope == "year_to_date" else "공시 열 직접 확인"
            if metric["status"] == "missing":
                note = {"account_not_reported": "직접 공시 계정 미확인", "ambiguous_account": "동일 계정 값 충돌",
                        "currency_unavailable": "통화 단위 미확인", "amount_unavailable": "공시 금액 미연결"}.get(metric.get("reason"), "미연결")
            elif key in {"operating_cash_flow", "tangible_purchases", "capex", "free_cash_flow"}:
                note += " · 현금흐름표"
            lines.append(" | ".join(_cell(v) for v in (metric["label"], _value(metric, "quarter_value"), cumulative, note)))
        lines.extend(["회사 전망·발표 당시 예상치·발표 전후 주가 반응은 별도 미연결입니다. 유형자산 취득을 전체 CAPEX로 간주하거나 영업현금흐름에서 빼서 FCF를 만들지 않습니다.", ""])
    return lines + ([gap, ""] if gap else [])


def _has_kr_scope(pipeline):
    """Only explain absent Korean actuals when Korean issuers were in scope or Today was not calculated."""
    coverage = pipeline.get("coverage") or {}
    if not coverage.get("summary_available"):
        return True
    return any(str(row.get("ticker", "")).endswith((".KS", ".KQ")) for row in coverage.get("missing") or []) or any(
        p["event"].get("source_kind") == "dart_discovered_report" for p in pipeline.get("packets") or [])


def identity_notice_lines(context):
    """State when KR issuers were identified from a dated list, not a live download."""
    from stock_lab_core.dart_corporate_snapshot import snapshot_notice
    for key in ("earnings_sources", "earnings_result_sources"):
        for row in (context or {}).get(key) or []:
            if (isinstance(row, dict) and str(row.get("ticker", "")).endswith((".KS", ".KQ"))
                    and row.get("mapping_source") in {"official_snapshot", "official_cache"}):
                diagnostic = {k: row.get(k) for k in ("mapping_source", "snapshot_origin", "snapshot_asof", "snapshot_valid_until")}
                try:
                    from datetime import datetime
                    diagnostic["snapshot_age_days"] = (datetime.fromisoformat(str(row.get("checked_at")))
                                                       - datetime.fromisoformat(str(row.get("snapshot_asof")))).days
                except (TypeError, ValueError):
                    diagnostic["snapshot_age_days"] = "?"
                return ["", snapshot_notice(diagnostic), ""]
    return []
