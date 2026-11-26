"""Policy decisions and market halts as evidence, never as trading gates."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, number, records, safe_link
from stock_lab_core.report_presentation import kst_time
from stock_lab_core.market_safeguards import safeguard_events

register_loaded_source(__name__, __file__)


def _source(row):
    url = safe_link(row.get("source_url"))
    name = row.get("source") or "출처"
    return f"[{name}]({url})" if url else "공식 출처 미연결"


BANKS = ("BOK", "FOMC", "BOJ")  # report order; BOK added 2026-11-26
BANK_NAMES = {"BOK": "한국은행 금통위", "FOMC": "FOMC", "BOJ": "BOJ"}
_ACTIONS = {"hold": "동결", "hike": "인상", "cut": "인하"}


def central_bank_result_text(row):
    """Official decision and rate as printed in the official document; '' when no official row."""
    if (row or {}).get("status") != "official":
        return ""
    action = _ACTIONS.get(row.get("action"))
    lower, upper = number(row.get("rate_lower")), number(row.get("rate_upper"))
    rate, previous = number(row.get("policy_rate")), number(row.get("previous_rate"))
    if row.get("bank") == "FOMC" and lower is not None and upper is not None:
        return f"{action or '목표'} · 연방기금 목표 {lower:g}~{upper:g}%"
    if row.get("bank") == "BOK" and action and rate is not None:
        if action == "hold" or previous is None:
            return f"{action} · 기준금리 {rate:.2f}%"
        return f"{action} · 기준금리 {previous:.2f}% → {rate:.2f}%"
    if rate is not None:
        return f"익일물 콜금리 목표 약 {rate:g}%"
    return "공식 수치 미연결"


def policy_evidence_lines(context, news, now):
    lines = ["", "## 중앙은행 공식 결과", "기관 | 공식 결정·금리 | 발표 시각(KST) | 대조 상태·출처",
             "--- | --- | --- | ---"]
    results = {r.get("bank"): r for r in records(context.get("central_bank_results"))}
    for bank in BANKS:
        row = results.get(bank, {})
        if row.get("status") != "official":
            result = "결과 미연결 · 추정하지 않음"
            basis = row.get("reason") or "공식 결과 수집 전: 시황 다시 생성 필요"
            at = "미확인"
        else:
            result = central_bank_result_text(row)
            at = kst_time(row.get("release_at")) if row.get("release_at") else f"{row.get('date', '-')} · 시각 미제공"
            basis = {"BOK": "한국은행 통화정책방향 결정문 확인",
                     "BOJ": "공식 성명 확인 · 전회 대비 변동은 별도 미대조"}.get(bank, "공식 성명 확인")
        lines.append(" | ".join(_cell(v) for v in (BANK_NAMES[bank], result, at, basis + " · " + _source(row))))
    lines += ["", "공식 성명의 결정값입니다. 기자회견 해석·주가 변동 원인이나 매수 허용을 뜻하지 않습니다.",
              "", "## 시장 안전장치 발동 근거",
              "발동일 | 시장·조치 | 확인 수준 | 보도·공시 출처", "--- | --- | --- | ---"]
    from stock_lab_core.safeguard_history import merge_safeguard_history, observed_kr_sessions

    events = merge_safeguard_history(safeguard_events(news, now), context.get("safeguard_events", []),
                                     observed_kr_sessions(context), now)
    for row in events[:10]:
        kind = "사이드카" if row["kind"] == "sidecar" else "서킷브레이커"
        direction = {"buy": "매수", "sell": "매도", "down": "하락", "unknown": "방향 미확인"}[row["direction"]]
        status = "거래소 원문 확인" if row["status"] == "official" else "보도상 발동 · 거래소 원문 미대조"
        if row.get("date_basis") == "publication_date":
            status += " · 기사 발행일 기준"
        if row.get("retained_from_history"):
            status += " · 최근 5거래일 저장 이력"
        links = list(dict.fromkeys(_source(s) for s in row.get("sources", [row])))[:3]
        lines.append(" | ".join(_cell(v) for v in (row["date"], f"{row['market']} {direction} {kind}", status, " / ".join(links))))
    if not events:
        lines.append("미연결 | 매수·매도 사이드카 / 서킷브레이커 | 발동 근거 미수집(미발동 의미 아님) | -")
    lines.append("수집된 근거 내 이력이며 전체 발동 이력·누적 횟수가 아닙니다. 지수 낙폭만으로 발동을 판정하지 않습니다.")
    return lines
