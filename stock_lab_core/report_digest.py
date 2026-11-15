"""Reading-only weekly headlines and explicit connection checks; no forecasts."""
from datetime import timedelta
import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, _cell, first, is_held, records, stamp, text

register_loaded_source(__name__, __file__)

# Subjects, not assertions about direction or a supplied example's truth.
_THEMES = (
    ("엔비디아 경영·규제 보도", r"(?:NVIDIA|엔비디아|젠슨\s*황|Jensen).*(?:사임|사퇴|퇴임|퇴진|경영|CEO|조사|규제|수출|resign|export|probe|leadership)",
     "반도체", "회사·규제기관 원문, 고객 계약·공급 일정 변경 여부"),
    ("AI 인프라 투자·자금 부담", r"(?:AI|데이터센터|data cent[er]+|클라우드|cloud).*(?:투자|부채|차입|신용|부담|조정|수요|급락|capex|debt|credit|spend|invest)",
     "클라우드·소프트웨어", "투자 전망 대비 영업현금·리스·차입, 주문 지연·가동률"),
    ("통화정책·금리·물가", r"연준|연은|금리|국채|물가|한국은행|금통위|\bFed\b|FOMC|CPI|PPI|Treasury|inflation|yields?",
     "금리·경제지표", "공식 발표·이전치 수정, 금리·달러의 동반 반응"),
    ("지정학·에너지", r"이란|중동|우크라이나|제재|유가|원유|호르무즈|Iran|Middle East|Ukraine|sanction|\boil\b|OPEC",
     "에너지·지정학", "공식 조치·공급 차질 여부, 유가·운송비 지속성"),
    ("암호화폐·유동성", r"비트코인|암호화폐|이더리움|Bitcoin|Ethereum|\bBTC\b|crypto",
     "암호화폐", "현물 가격·거래량, 청산·자금 유출의 확인 출처"),
)


def _theme(row):
    from stock_lab_core.report_brief import brief_theme
    # The subject of a crypto/oil headline stays crypto/oil even when it also
    # mentions rates. Broad close-wrap labels are not distinct weekly themes.
    for label, pattern, category, check in (*_THEMES[-2:], *_THEMES[:-2]):
        if re.search(pattern, text(row.get("title")), re.I):
            return label, category, check
    category = brief_theme(row, comprehensive=True)
    return category, category, "회사·기관 원문, 실적 전망 변화와 다음 정규장 흐름"


def weekly_themes(context, news, summary_rows, now):
    """Unique collected headlines over seven calendar days; not a full crawl.

    Context rows are accepted as dated weekly background, not close-session
    causes. Count a duplicated URL/title once across all collection buckets.
    No holding weight, rating or market return is modified or inferred.
    """
    from stock_lab_core.article_context import verified_body_facts
    from stock_lab_core.report_brief import ENTITIES, _holding_links, _validated_brief_row, material_news
    from stock_lab_core.today_news import _session_article_keys
    from stock_lab_core.report_presentation import is_preopen_outlook

    local = now.astimezone(KST)
    start = (local - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    raw = records(news) + [row for bucket in ("session_news", "current_session_news", "next_session_news", "other_market_news")
                           for row in records(context.get(bucket))]
    held = [row for row in records(summary_rows) if is_held(row)]
    unique, urls, titles = [], set(), set()
    for row in sorted(raw, key=lambda row: bool(verified_body_facts(row)), reverse=True):
        at = stamp(first(row, "published_at", "published"))
        if not at or not start <= at <= now or not material_news(row) or is_preopen_outlook(row):
            continue
        clean = _validated_brief_row(row, context, now, other=True)
        if not clean or re.search(r"^\s*\[표\]|순(?:매수|매도)\s*(?:상위|순위)", text(clean.get("title"))):
            continue
        url, title_key = _session_article_keys(clean)
        if url in urls or title_key in titles:
            continue
        urls.add(url); titles.add(title_key)
        unique.append(clean)
    groups = {}
    for row in unique:
        label, category, check = _theme(row)
        if label in {"시장·업종", "한국 시황", "미국 시황"}:
            continue
        group = groups.setdefault(label, {"label": label, "category": category, "check": check, "articles": []})
        group["articles"].append(row)
    result = []
    for group in groups.values():
        items = sorted(group["articles"], key=lambda r: (bool(verified_body_facts(r)), stamp(first(r, "published_at", "published"))), reverse=True)
        title = " / ".join(text(row.get("title")) for row in items)
        entities = [symbol for symbol, pattern in ENTITIES if re.search(pattern, title, re.I)]
        if group["label"] == "엔비디아 경영·규제 보도" and "NVDA" not in entities:
            entities.append("NVDA")  # Jensen Huang headlines already identify this issuer in _theme.
        links = [_holding_links(held, title, entities, group["category"], market) for market in
                 sorted({text(row.get("market")) or "GLOBAL" for row in items})]
        direct = [link for link in links if not link.startswith(("타시장", "직접 보유 연결 없음"))]
        related = " / ".join(dict.fromkeys(direct or links)) or "직접 보유 연결 없음 · 시장 참고"
        group.update(articles=items, count=len(items), related=related,
                     body_count=sum(bool(verified_body_facts(row)) for row in items))
        result.append(group)
    result.sort(key=lambda group: (-group["count"], -group["body_count"], group["label"]))
    return {"start": start, "end": local, "themes": result[:5], "headlines": len(unique)}


def weekly_theme_lines(digest):
    lines = ["## 이번 주 테마 5개", "",
             f"최근 7일 · {digest['start']:%m/%d}~{digest['end']:%m/%d %H:%M} KST · 수집 헤드라인 {digest['headlines']}건에서 구체적 테마 선정(중복 제외).", ""]
    if not digest["themes"]:
        return lines + ["출처·발행시각·관련성 기준을 통과한 이번 주 기사 미확보.", ""]
    lines += ["테마 | 헤드라인 | 관련 보유 | 다음 확인", "--- | --- | --- | ---"]
    for group in digest["themes"]:
        lines.append(" | ".join(_cell(x) for x in (
            f"**{group['label']}**",
            f"{group['count']}건 · 본문 근거 {group['body_count']}건", group["related"], group["check"])))
    if len(digest["themes"]) < 5:
        lines += [f"확인된 테마 {len(digest['themes'])}개만 표시합니다."]
    return lines + [""]


def weekly_source_lines(digest):
    from stock_lab_core.article_context import body_connection_state, body_unavailable_reason
    lines = ["### 주간 테마 집계 근거", "",
             "테마 | 헤드라인·출처 | 발행시각(KST) | 본문 상태", "--- | --- | --- | ---"]
    for group in digest["themes"]:
        for row in group["articles"]:
            headline, source = text(row.get("title")), first(row, "link", "url")
            published = stamp(first(row, "published_at", "published")).astimezone(KST)
            state = body_connection_state(row)
            if state == "접근·검증 실패":
                state += " · " + body_unavailable_reason(row)
            lines.append(" | ".join(_cell(x) for x in (group["label"], f"[{headline}]({source})", f"{published:%m/%d %H:%M}", state)))
    return lines + [""] if digest["themes"] else []


def connection_checks(context, summary_rows, digest, reading, now):
    """Observable connection checks, explicitly not truth/forecast certification."""
    from stock_lab_core.public_flow_backfill import summarize_backfill
    checks = []
    for market, ticker in (("KR", "^KS11"), ("US", "^GSPC")):
        day = context.get("sessions", {}).get(market)
        price = context.get("prices", {}).get(ticker, {})
        at = stamp(day)
        status = "미확인" if not at or not price else "실패" if (
            at.date() > now.astimezone(KST).date() or price.get("date") != day) else "통과"
        checks.append((f"{market} 대표지수 기준일", status, f"확정 세션 {day or '미확보'} / 시세 {price.get('date') or '미확보'}"))
    checks.append(("계좌 입력", "통과" if records(summary_rows) else "미확인",
                   f"오늘점검 {len(records(summary_rows))}행 연결; 시세 최신성·전체 계좌 완전성은 별도"))
    groups = digest["themes"]
    total, bodies = sum(g["count"] for g in groups), sum(g["body_count"] for g in groups)
    from collections import Counter
    from stock_lab_core.article_context import body_connection_state
    coverage = Counter(body_connection_state(row) for group in groups for row in group["articles"])
    reasons = " · ".join(f"{label} {coverage[label]}건" for label in (
        "조회 대상 제외", "미지원 출처", "본문 확인·해석 보류", "접근·검증 실패") if coverage[label])
    checks.append(("상위 테마 본문", "통과" if total and total == bodies else "미확인",
                   f"헤드라인 {total}건 중 검증 본문 {bodies}건; {reasons or '미연결 항목 없음'}; 미검증 보도는 시장 원인 확정 아님"))
    rows, failure = summarize_backfill(context.get("public_flow_backfill"), checked_at=context.get("market_evidence_checked_at"))
    individual = [row for row in rows if row["label"] == "개인"]
    linked = len(individual) == 2 and all(row.get("sum_5") is not None and row.get("sum_20") is not None for row in individual)
    checks.append(("개인 수급 이력", "통과" if linked else "미확인", "KOSPI·KOSDAQ 5·20거래일 연결" if linked else failure or "개인 원자료/거래일 누락; 0 대체 안 함"))
    from stock_lab_core.release_calendar import BOK_URL
    has_bok = BOK_URL in reading and any(
        row.get("indicator") == "KR_BOK_RATE_DECISION" and row.get("source_url") == BOK_URL
        and not row.get("stale") and row.get("status") not in {"unavailable", "missing", "error", "stale"}
        and (at := stamp(row.get("date"))) and at.date() >= now.astimezone(KST).date()
        for row in records(context.get("calendar_events")))
    checks.append(("한국은행 일정 표시", "통과" if has_bok else "미확인", "공식 일정 연결·결정 결과와 별도" if has_bok else "현재 표시 구간의 공식 일정 미확보"))
    return checks


def check_lines(checks):
    counts = {state: sum(row[1] == state for row in checks) for state in ("통과", "실패", "미확인")}
    summary = "자동점검(연결·구조): " + " · ".join(f"{state} {count}" for state, count in counts.items()) + " — 항목별 근거는 상세 근거에 표시."
    detail = ["### 자동점검 항목", "연결·기준일 점검이며 기사 주장·투자 판단의 정확도 보증은 아닙니다.", "",
              "항목 | 상태 | 확인 범위", "--- | --- | ---"]
    detail += [" | ".join(_cell(x) for x in row) for row in checks]
    return summary, detail + [""]
