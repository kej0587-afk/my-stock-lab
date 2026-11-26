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
    return _macro_groups(header, macro), _table(header, indices)


# Reader grouping only: rows are copied unchanged from the dashboard table.
MACRO_GROUPS = (
    ("금리", ("^TNX", "^TYX")),
    ("환율·달러", ("USDKRW=X", "DX-Y.NYB")),
    ("원자재", ("CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F")),
    ("심리·변동성", ("^VIX", "^MOVE")),
)


def _macro_groups(header, rows):
    """Split the macro rows by ticker; unknown tickers stay visible under 기타."""
    remaining = list(rows)
    lines = []
    for title, tickers in MACRO_GROUPS:
        picked = [row for row in remaining if any(row[0].endswith(f"({t})") for t in tickers)]
        if picked:
            remaining = [row for row in remaining if row not in picked]
            lines += [f"**{title}**", *_table(header, picked)]
    if remaining:
        lines += ["**기타**", *_table(header, remaining)]
    return lines


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
    title = "**최근 발표 · 변화가 큰 지표부터**"
    if not selected:
        # Nothing inside the recent-session window: show the last confirmed
        # publications instead of an empty section, labelled as older. Rows
        # without a known publication date are not promoted.
        from stock_lab_core.report_evidence import stamp, text
        dated = [(stamp(text(row.get("release_at"))), row) for row in original
                 if row.get("status") not in {"pending", "scheduled", "예정", "stale"}]
        dated = [(at, row) for at, row in dated if at and at <= now]
        selected = [row for _, row in sorted(dated, key=lambda pair: pair[0], reverse=True)[:6]]
        title = "**최근 3거래일 안 새 발표 없음 · 마지막으로 확인된 발표(최근 순)**"
    rows = []
    for picked in selected:
        for index, row in enumerate(original):
            if all(row.get(k) == picked.get(k) for k in ("indicator", "period", "basis", "release_at")):
                values = source[index][:]
                if " · 발표 " not in values[0]:
                    values[0] += f" · 발표 {row.get('release_at')} " + citation(row)
                rows.append(values)
                break
    return [title, *_table(header, rows)] if rows else []


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


def _quick_summary_lines(judgment_lines, current_state, indices, states, interpretation, context, changes=()):
    """Reader's first screen: market movement first, account state in one line."""
    def basis(market, label):
        state = (states or {}).get(market) or {}
        close = state.get("last_close") or "미확인"
        return f"{label} {state.get('label', '거래일정 미확인')} · 마지막 확정 종가 {close}"
    lines = ["## 빠른 요약", "", "**기준** · " + basis("KR", "한국") + " / " + basis("US", "미국")
             + " · 숫자는 이 보고서 생성시점 기준입니다.", ""]
    if interpretation:
        lines += ["**시장 해석** · " + interpretation, ""]
    # Always visible (2026-11-26): an empty list says the comparison is missing, not that nothing changed.
    lines += ["**오늘 달라진 점**", *(["- " + change for change in changes] if changes else
                                    ["- 전 거래일과 비교할 변화 자료 미연결 · 변화가 없다는 뜻은 아닙니다."]), ""]
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


def _closing_lines(portfolio_lines, calendar_lines, *, limit=5):
    """마무리: holdings impact and next checks, copied from the tables above (no new numbers)."""
    lines = ["## 마무리 · 보유 종목 영향과 다음 확인 사항", ""]
    impact = []
    for header, rows in tables("\n".join(portfolio_lines)):
        if header and header[0] == "종목":
            status = len(header) - 1
            impact = [(row[0], row[1], row[status]) for row in rows]
            break
    lines += ["**보유 종목에 미치는 영향**", ""]
    if impact:
        lines += _table(["종목", "일간(위 보유 표 그대로)", "상태/사유"], impact)
    else:
        lines += ["보유 종목 표 미연결 · 영향 미확인.", ""]
    checks = []
    for header, rows in tables("\n".join(calendar_lines)):
        if header and header[0].startswith("일정") and header[-1].startswith("확인할"):
            checks += [(row[0], row[-1]) for row in rows]
        elif header and header[0] in ("일정·촉매", "기업·상태") and not checks:
            checks += [(row[0], row[1]) for row in rows]
    lines += ["**다음 확인 사항**", ""]
    if checks:
        lines += _table(["일정", "확인할 것"], checks[:limit])
    else:
        lines += ["확인된 다음 일정 미연결 · 일정이 없다는 뜻은 아닙니다.", ""]
    lines += ["표는 위 「포트폴리오 · 교체 검토」와 「다음 일정」에서 그대로 옮겼습니다. 매수·매도 지시가 아닙니다.", ""]
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


def _kr_flow_table_lines(flow):
    """Copy flow tables; history keeps its completed-day period and sign meaning."""
    lines = []
    flow_dates = []
    for header, rows in tables("\n".join(flow)):
        history = any("연속" in cell for cell in header)
        # Npay backfill ("누적") excludes today's session; the stored-snapshot
        # history ("합계") may include the base day's intraday values.
        completed = history and any("누적" in cell for cell in header)
        lines += _table([header[0] + (" · 억원(완료 거래일)" if completed else " · 억원(잠정)"), *header[1:]], rows)
        if not history:
            flow_dates += [row[-1] for row in rows if row]
            continue
        # The source note is dropped in this copy; keep the period and sign meaning beside the table.
        asof = sorted({row[-1] for row in rows if row})
        note = (f"이력 표는 기준일({' / '.join(asof)}) 마감까지의 완료 거래일 기준입니다." if completed else
                f"이력 표는 기준일({' / '.join(asof)})까지이며 기준일 장중 수치가 포함될 수 있습니다.")
        later = sorted({day for day in flow_dates if asof and day > asof[-1]})
        if later:
            note += f" 위 {' / '.join(later)} 잠정 수급은 포함하지 않습니다."
        lines += [note + " 연속 일수는 마지막 거래일부터 같은 방향이 이어진 날수, 누적은 기간 합계라 부호가 서로 다를 수 있습니다.", ""]
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
    quick = _quick_summary_lines(judgment, current_state, indices, states, interpretation, context,
                                 changes=synthesis.get("daily_changes", ()))
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
            lines += _kr_flow_table_lines(flow)
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

    from stock_lab_core.report_dashboard import COUNTRY_ETFS, OBSERVATORY_DAILY, local_index_table_lines, observatory_table_lines
    collected = context.get("observatory_daily") or {}
    options = [ticker for ticker in OBSERVATORY_DAILY if ticker not in COUNTRY_ETFS]
    # Only items with an actual observation count as shown; a 미연결 row is not.
    rendered = "\n".join([*board, *macro_lines, *(f"({ticker})" for ticker, obs in collected.items() if obs)])
    if any(collected.get(ticker) for ticker in options):
        # Right after the 심리·변동성 group, before central-bank and news rows.
        at = 2 + len(macro)
        macro_lines[at:at] = ["**옵션 위험 · 관측실 지표**", *observatory_table_lines(context, options)]
    world = ["## 세계 시장과 국가 ETF", "",
             "미국 상장 국가 ETF의 달러 가격(완료 일봉)입니다. 환율·거래시간 차이로 현지 지수와 다를 수 있습니다.", "",
             *observatory_table_lines(context, COUNTRY_ETFS),
             "현지 지수는 현지 통화·현지 거래소 마감 기준이며 ETF와 기준일이 다를 수 있습니다. 서로 환산하거나 대신 쓰지 않습니다.", "",
             *local_index_table_lines(context),
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

    portfolio = _portfolio_lines(sections)
    lines = [*head, *quick, *board, *market_blocks[order[0]], *market_blocks[order[1]], *world,
             *macro_lines, *economy_lines, *observatory, *weekly_theme_lines(digest), *_flow_lines(sections),
             *events, *judgment, *account_preamble, *portfolio, *calendar_lines,
             *_closing_lines(portfolio, calendar_lines)]
    # Keep unique evidence; do not append a second complete legacy report.
    reading = "\n".join(lines)
    status, checks = check_lines(connection_checks(context, summary_rows, digest, reading, now))
    lines += [status, "", f"## {AUDIT_TITLE}", "", "시장별 기준시각·원문·산식·누락 자료를 보관한 상세 근거입니다.", "", *checks, *weekly_source_lines(digest)]
    lines.append(additional_evidence(report, reading))
    return "\n".join(lines).strip()
