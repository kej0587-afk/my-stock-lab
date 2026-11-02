"""Present the shared earnings pipeline: facts, questions and coverage apart."""

from stock_lab_core.earnings_reconciliation import METRIC_LABELS
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, safe_link, text

register_loaded_source(__name__, __file__)


def earnings_story_lines(pipeline):
    selected = pipeline["highlights"]
    if not selected:
        return []
    lines = ["", "**실적에서 확인할 시장 쟁점**",
             "기업·대상 | 확인된 사실·보도 | 해석과 남은 확인", "--- | --- | ---"]
    for packet in selected:
        metrics = packet["metrics"]
        facts = []
        for key in ("free_cash_flow", "capex", "guidance", "revenue", "profit"):
            metric = metrics.get(key, {})
            if metric.get("status") not in {"reported", "available"} or not safe_link(metric.get("source_url")) or not text(metric.get("text")):
                continue
            scope = "TTM·분기값 아님" if metric.get("period_scope") == "trailing_twelve_months" else packet["fiscal_period"]
            # Keep the complete source sentence; truncating can remove a sign or unit.
            facts.append(f"{METRIC_LABELS[key]} ({scope}): {text(metric['text'])} "
                         + f"[원문]({safe_link(metric['source_url'])})")
            if len(facts) == 2:
                break
        if not facts:
            facts = ["제목 기준·기사 주장: " + citation(packet["articles"][0])] if packet["articles"] else [packet["release_status"]]
        target = f"{packet['name']}({packet['ticker']}) · {packet['sector']} · {packet['relationship']}"
        target += f" · {packet['date']} {packet['date_basis']}"
        reading = packet["commentary"] + " " + packet["consensus_status"] + "."
        lines.append(" | ".join(_cell(v) for v in (target, " / ".join(facts), reading)))
    lines.extend(["", "최근 7일의 수집된 발표·보도에서 기업 중복을 줄이고 업종을 분산한 최대 3개입니다. 시장 영향도 순위나 매수 후보가 아니며, 근거가 없는 업종은 채우지 않습니다.", ""])
    return lines


def earnings_coverage_lines(pipeline):
    coverage = pipeline["coverage"]
    lines = ["", "**실적 연결 상태**",
             f"점검 기업 {coverage['registered']}개 · 공식 발표 확인 기업 {coverage['official']}개 · 기존 뉴스에서 발견 {coverage['discovered']}개(서로 중복 가능). "
             "전시장 실적 캘린더가 아니라 기존 수집자료의 연결 범위입니다.",
             "기업·분기 | 일정·발표 확인 | 실제치·현금흐름 | 예상치·전망·반응", "--- | --- | --- | ---"]
    for packet in pipeline["packets"]:
        stage = packet["stages"]
        actual = " / ".join(METRIC_LABELS[key] + " " + stage[key] for key in ("revenue", "profit", "capex", "free_cash_flow"))
        pending = packet["consensus_status"] + " / 회사 전망 " + stage["guidance"] + " / 주가 반응 " + stage["price_reaction"]
        if packet["gaps"]:
            pending += " · " + packet["gaps"][0]
        lines.append(" | ".join(_cell(v) for v in (
            f"{packet['name']}({packet['ticker']}) · {packet['fiscal_period'] or '분기 미확인'}",
            f"{packet['release_status']} · {packet['date']} {packet['date_basis']}", actual, pending)))
    if not pipeline["packets"]:
        lines.append("기업 실적 | 연결 자료 없음 | 미연결 | 미발표·일정 없음으로 해석하지 않음")
    excluded = pipeline["discovery"]["excluded"]
    if excluded:
        lines.extend(["", "보도 연결 보류: " + " / ".join(f"{reason} {count}건" for reason, count in excluded.items())])
    if coverage["missing"]:
        lines.extend(["", "기업 | 연결되지 않은 단계", "--- | ---"])
        lines.extend(" | ".join(_cell(v) for v in (f"{row['name']}({row['ticker']})", row["reason"])) for row in coverage["missing"])
    lines.extend(["", "미연결은 0·미발표·실적 부진이 아닙니다. 회사 전망, 현재 예상치, 발표 당시 예상치는 서로 대체하지 않습니다.", ""])
    return lines
