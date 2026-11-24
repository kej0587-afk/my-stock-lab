"""Compact reading path over the existing report. No fetching or decision rules."""

import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, records
from stock_lab_core.report_document import additional_evidence, decision_summary_lines
from stock_lab_core.report_view import split_report_sections

register_loaded_source(__name__, __file__)

# Keep importing this new module safe during Streamlit's mixed-module reload.
# The existing report code guard still requires a restart before generation.
AUDIT_TITLE = "상세 근거 · 계산 기준 · 연결 상태"

def tables(markdown):
    """Read generated pipe tables without interpreting prose as a data row."""
    lines = markdown.splitlines()
    result = []
    for i, line in enumerate(lines[:-1]):
        if " | " not in line or not re.fullmatch(r"[\s|:\-]+", lines[i + 1]) or "---" not in lines[i + 1]:
            continue
        header = line.split(" | ")
        rows = []
        for candidate in lines[i + 2:]:
            cells = candidate.split(" | ")
            if len(cells) != len(header):
                break
            rows.append(cells)
        result.append((header, rows))
    return result


def _table(header, rows):
    return [" | ".join(header), " | ".join("---" for _ in header),
            *(" | ".join(_cell(value) for value in row) for row in rows), ""]


def _board(sections):
    from stock_lab_core.report_dashboard import INDEX_BOARD
    source = tables(sections.get("지수·매크로 한눈에", ""))
    if not source:
        return [], []
    header, rows = source[0]
    indices, macro = [], []
    for row in rows:
        target = indices if any(row[0].endswith(f"({ticker})") for ticker in INDEX_BOARD) else macro
        target.append(row)
    return _table(header, macro), _table(header, indices)


def _sector_table(sections, market):
    blocks = tables(sections.get("업종별 왜", ""))
    if not blocks:
        return []
    header, rows = blocks[0]
    # Select rows only; retain the existing same-date excess return and source.
    selected = [r for r in rows if bool(re.search(r"\.(?:KS|KQ)\)", r[0])) == (market == "KR")
                and "(^SOX)" not in r[0]]  # Index already shown above; retain sector ETF here.
    if not selected:
        return []
    columns = [0, 1, 4, 5]
    return ["**업종 움직임**", *_table([header[i] for i in columns], [[r[i] for i in columns] for r in selected])]


def _recent_releases(sections, context, now):
    from stock_lab_core.report_analysis import recent_economic_releases, select_economic_stories
    from stock_lab_core.report_evidence import citation

    original = records(context.get("economic_releases"))
    recent = recent_economic_releases(original, context, now)
    ranked = select_economic_stories(recent, limit=max(1, len(recent)))
    identity = lambda row: tuple(row.get(k) for k in ("indicator", "period", "basis", "release_at"))
    ranked_ids = {identity(row) for row in ranked}
    selected = ranked + [row for row in recent if identity(row) not in ranked_ids]
    blocks = tables(sections.get("경제지표", ""))
    if not blocks or len(blocks[0][1]) != len(original):
        return []  # Never align rows by a guessed name or changed table schema.
    header, source = blocks[0]
    if len(header) != 6:
        return []
    rows = []
    for picked in selected:
        for index, row in enumerate(original):
            if all(row.get(k) == picked.get(k) for k in ("indicator", "period", "basis", "release_at")):
                values = source[index][:]
                if " · 발표 " not in values[0]:
                    values[0] += f" · 발표 {row.get('release_at')} " + citation(row)
                rows.append(values)
                break
    return ["**최근 발표 · 변화가 큰 지표부터**", *_table(header, rows)] if rows else []


def _flow_lines(sections):
    source = sections.get("주도 업종 교체 관측", "")
    lines = ["## 돈흐름 · 업종 순환", "가격·거래량 기반 관측입니다. 실제 순매수액은 한국 시황의 수급과 구분합니다.", ""]
    # Only the existing measured tables, not repeated explanations/boilerplate.
    for header, rows in tables(source):
        if header[0] == "시장·업종·기준일":
            lines += _table(header, rows)
    if len(lines) == 3:
        lines += ["동일 기준일 업종 비교 자료 미연결.", ""]
    return lines


def _portfolio_lines(sections):
    source = sections.get("내 보유 종목 영향", "")
    lines = ["## 포트폴리오 · 교체 검토", ""]
    # Account summary tables carry exact aggregate values, units and as-of labels.
    for header, rows in tables(source):
        if header[0] == "종목":
            # Session timestamps and missing-quote reasons are data, even without a return.
            lines += _table(header, rows)
        elif "재현 기준" not in header[0]:
            lines += _table(header, rows)
            if "계좌 기여(추정)" in header:
                lines += ["현재비중 기반 노출 추정이며 실제 계좌 수익률이 아닙니다. 시장별 기간이 다르고 환율·거래 변동은 미반영입니다.", ""]
            if "환율 영향 근사치" in header:
                lines += ["별도 환율 민감도이며 위 계좌 추정에 합산하지 않습니다.", ""]
    if not tables(source):
        lines += [line for line in source.splitlines() if line and not line.startswith("##")]
    # Preserve actual account mode/quality warnings; move derivation prose only.
    for line in source.splitlines():
        if line.startswith(("**", "통합", "계좌", "최신 확정", "자료 부족", "미연결")) and " | " not in line:
            lines += [line]
    lines += ["", "**비교 검토 후보 · 기존 게이트 유지**", ""]
    candidate = sections.get("관심 후보 상위 3개", "")
    for header, rows in tables(candidate):
        lines += _table(header, rows)
    if not tables(candidate):
        lines += ["관심 후보 입력 미연결." if "미연결" in candidate else "계산된 미보유 후보 없음."]
    lines += ["교체는 보유 사유와 후보의 게이트·해제 조건을 함께 검토합니다. 위 표는 자동 교체 지시가 아닙니다.", ""]
    return lines


def _quick_summary_lines(judgment_lines, current_state, indices, states, interpretation, context):
    """Reader's first screen: market movement first, account state in one line."""
    def basis(market, label):
        state = (states or {}).get(market) or {}
        close = state.get("last_close") or "미확인"
        return f"{label} {state.get('label', '거래일정 미확인')} · 마지막 확정 종가 {close}"
    lines = ["## 빠른 요약", "", "**기준** · " + basis("KR", "한국") + " / " + basis("US", "미국")
             + " · 숫자는 이 보고서 생성시점 기준입니다.", ""]
    if interpretation:
        lines += ["**시장 해석** · " + interpretation, ""]
    if indices:
        lines += ["**주요시장**", *indices]
    guard = (context.get("market_guard") or {}).get("action")
    action = str(guard or "").strip() or "시장 게이트 입력 미연결"
    lines += ["**기존 실행 방향** · " + action + " · 근거와 해제 조건은 아래 「오늘의 판단」에 있습니다.", ""]
    # Stale-input warnings must stay on the first screen, not only in the account area.
    lines += [line for line in judgment_lines if line.startswith(("> ", "**기준일 지연"))]
    if lines[-1] != "":
        lines.append("")
    # The existing current-state block keeps its own heading right below.
    if current_state:
        lines += [current_state, ""]
    return lines


def _korea_first(states):
    """Korean session report reads Korea first; otherwise the US close leads."""
    kr = ((states or {}).get("KR") or {}).get("phase")
    us = ((states or {}).get("US") or {}).get("phase")
    return kr == "intraday" or (kr == "closed" and us != "intraday")


def _observatory_status_lines(rendered, *, country):
    """Every registered observatory item keeps a visible status instead of vanishing."""
    from stock_lab_core.macro_monitor import METRICS
    # Same series under another provider symbol already shown in the report tables.
    equivalent = {"VIXCLS": "^VIX", "DGS10": "^TNX", "KRW=X": "USDKRW=X"}
    groups = {}
    for metric in METRICS:
        if (metric.group == "국가 ETF") != country:
            continue
        shown = f"({equivalent.get(metric.symbol, metric.symbol)})" in rendered
        groups.setdefault(metric.group, []).append(
            f"{metric.name}({metric.symbol}) · {'본문 표시' if shown else '미연결'}")
    lines = []
    for group, items in groups.items():
        lines.append(f"- **{group}**: " + " / ".join(items))
    return lines


def compose_reading_report(report, *, context, news, summary_rows, now):
    """Quick summary -> market body -> appendix; one reading path, evidence once.

    The legacy renderer stays independently testable. Tables are copied, not
    recomputed; all per-row missing/stale/session qualifiers remain attached.
    Section order only: no scores, gates or collectors change here.
    """
    from stock_lab_core.report_brief import build_news_brief, brief_theme
    from stock_lab_core.report_market_summary import _market_fact, korean_flow_tables, market_summary
    from stock_lab_core.report_session import market_session_states
    from stock_lab_core.earnings_pipeline import build_earnings_pipeline
    from stock_lab_core.report_earnings import compact_catalyst_lines
    from stock_lab_core.report_dart_earnings import filing_actual_lines, identity_notice_lines
    from stock_lab_core.report_coverage import sector_coverage_lines, company_coverage_lines, context_news_lines

    report = report.lstrip("\ufeff")
    parts = split_report_sections(report)
    sections = dict(parts)
    preamble = sections.get("", "")
    states = context.get("market_states") or market_session_states(now, context.get("sessions"))
    macro, indices = _board(sections)
    title = next((line for line in preamble.splitlines() if line.startswith("# ")), "# Stock Lab 자동 뉴스픽")
    macro_brief = build_news_brief(context, [r for r in records(news)
        if brief_theme(r) in {"금리·경제지표", "에너지·지정학"}], summary_rows, now, limit=None, compact=True)
    from stock_lab_core.report_digest import weekly_themes, weekly_theme_lines, weekly_source_lines, connection_checks, check_lines
    digest = weekly_themes(context, news, summary_rows, now)
    synthesis = market_summary(context, news, context.get("closed_flow_rows", []), states, now)
    interpretation = synthesis.get("interpretation", "")

    # Existing decision block, split into the account preamble and the judgment.
    decision = decision_summary_lines(sections, context=context, summary_rows=summary_rows,
                                      interpretation=interpretation)
    cut = decision.index("## 오늘의 판단") if "## 오늘의 판단" in decision else len(decision)
    account_preamble, judgment = decision[:cut], decision[cut:]
    current_state = sections.get("지금 상태 3줄", "").strip()
    if current_state and current_state in judgment:
        judgment = [line for line in judgment if line != current_state]
    judgment = [line for line in judgment if not line.startswith("**시장 해석** · ")]

    head = [title, ""]
    quick = _quick_summary_lines(judgment, current_state, indices, states, interpretation, context)
    board = ["## 지수", "", *indices]

    macro_lines = ["## 매크로", "", *macro]
    policy = tables(sections.get("중앙은행 공식 결과", ""))
    if policy:
        macro_lines += ["**중앙은행 공식 발표**"]
        for header, rows in policy:
            macro_lines += _table(header, rows)
    if macro_brief["article_keys"]:
        macro_lines += macro_brief["lines"] + [""]
    economy = _recent_releases(sections, context, now)
    economy_lines = ["## 물가·고용·소비·경기", "", *(economy or ["최근 발표로 고른 지표가 없습니다. 전체 경제지표 표는 상세 근거에 있습니다.", ""])]

    shared = context_news_lines(context, now, bucket="other_market_news", excluded=macro_brief["article_keys"], summary_rows=summary_rows)
    events = ["## 주요 기업과 사건", "", *(["**해외·공통 재료**", *shared] if shared else
                                      ["시장별 기업 실적·사건은 미국·한국 시장 구역에 있습니다.", ""])]

    pipeline = build_earnings_pipeline(context, summary_rows, news, now)
    explained = {(r.get("link") or r.get("url")) for r in synthesis.get("background_news", [])}
    market_blocks = {}
    for market, label in (("KR", "한국 시황"), ("US", "미국 시황")):
        lines = []
        fact = _market_fact(context, market, states, now)
        # The event/implication/check table immediately below carries the body
        # evidence once; keep only observed market context in this introduction.
        overview = synthesis.get("market_observations", synthesis.get("market_readings", {}))
        lines += ["## " + label, "", overview.get(market) or fact["phrase"], ""]
        if market == "KR":
            # The data tables retain market, source, provisional status and unit.
            flow = korean_flow_tables(context, fact)
            for header, rows in tables("\n".join(flow)):
                lines += _table([header[0] + " · 억원(잠정)", *header[1:]], rows)
            lines += [line for line in flow if line.startswith(("출처:", "프로그램 자료 미연결:", "프로그램은", "KRX 시장 전체"))]
            lines += [""]
            for header, rows in tables(sections.get("시장 안전장치 발동 근거", "")):
                lines += ["**시장 안전장치 · 확인 근거**", *_table(header, rows)]
        brief = build_news_brief(context, [r for r in records(news) if r.get("market") == market
            and (r.get("link") or r.get("url")) not in set(macro_brief["article_keys"])],
                                 summary_rows, now, limit=None, compact=True)
        if brief["article_keys"]:
            lines += [*brief["lines"], ""]
        elif not any(r.get("market") == market for r in synthesis.get("background_news", [])):
            lines += ["해당 세션의 출처·시각 기준을 통과한 핵심 기사 미확보.", ""]
        lines += sector_coverage_lines(context, news, market, now) or _sector_table(sections, market)
        lines += company_coverage_lines(context, summary_rows, market)
        lines += compact_catalyst_lines(pipeline, market, limit=None)
        if market == "KR":
            lines += filing_actual_lines(pipeline)
            lines += identity_notice_lines(context)
        after = context_news_lines(context, now, bucket="next_session_news", market=market,
                                   excluded=[*macro_brief["article_keys"], *brief["article_keys"], *explained], summary_rows=summary_rows)
        if after:
            lines += ["**장 마감 후 · 다음 세션 재료**", *after]
        market_blocks[market] = lines
    order = ("KR", "US") if _korea_first(states) else ("US", "KR")

    rendered = "\n".join([*board, *macro_lines])
    world = ["## 세계 시장과 국가 ETF", "",
             "매크로 관측실에 등록된 국가 ETF의 현재 연결 상태입니다. 다른 국가 현지 지수는 아직 수집 대상이 아닙니다.", "",
             *_observatory_status_lines(rendered, country=True), ""]
    observatory = ["## 관측실 지표 연결 상태", "",
                   "매크로 관측실 등록 지표 가운데 이 보고서 표에 들어온 항목과 아직 연결되지 않은 항목입니다. "
                   "미연결 항목은 관측실 화면에서만 조회됩니다.", "",
                   *_observatory_status_lines(rendered, country=False), ""]

    calendar_lines = ["## 다음 일정", ""]
    calendar_start = len(calendar_lines)
    calendar = sections.get("다가오는 일정", "")
    # Future calendar table only. Released results are in the market catalysts.
    scheduled = calendar.split("**기업 실적 촉매**", 1)[0]
    for header, rows in tables(scheduled):
        connected = [row for row in rows if not any("미연결" in cell for cell in row)]
        if connected:
            calendar_lines += _table(header, connected)
    for header, rows in tables(calendar):
        if header[0] == "기업·상태":
            future = [row for row in rows if row[0].endswith(" · 예정")]
            if future:
                calendar_lines += _table(header, future)
    if len(calendar_lines) == calendar_start:
        calendar_lines += ["확인된 향후 일정 미연결. 상세 연결 상태는 아래 근거에서 확인할 수 있습니다.", ""]
    from stock_lab_core.report_event_watch import event_watch_lines
    watch = event_watch_lines(context, news, summary_rows, now, pipeline=pipeline)
    if watch:
        calendar_lines[calendar_start:] = watch
        # Keep distinct policy/debt deadlines; IPO news already has a watch row.
        for header, rows in tables(scheduled):
            if header[0] == "일정·촉매":
                extra = [row for row in rows if row[0] != "최근 IPO 보도"
                         and not any("미연결" in cell for cell in row)]
                if extra:
                    calendar_lines += ["**추가 정책·발행 일정**", "", *_table(header, extra)]

    lines = [*head, *quick, *board, *market_blocks[order[0]], *market_blocks[order[1]], *world,
             *macro_lines, *economy_lines, *observatory, *weekly_theme_lines(digest), *_flow_lines(sections),
             *events, *judgment, *account_preamble, *_portfolio_lines(sections), *calendar_lines]
    # Keep unique evidence; do not append a second complete legacy report.
    reading = "\n".join(lines)
    status, checks = check_lines(connection_checks(context, summary_rows, digest, reading, now))
    lines += [status, "", f"## {AUDIT_TITLE}", "", "시장별 기준시각·원문·산식·누락 자료를 보관한 상세 근거입니다.", "", *checks, *weekly_source_lines(digest)]
    lines.append(additional_evidence(report, reading))
    return "\n".join(lines).strip()
