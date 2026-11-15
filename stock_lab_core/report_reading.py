"""Compact reading path over the existing report. No fetching or decision rules."""

import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, records
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
    selected = select_economic_stories(recent_economic_releases(original, context, now), limit=3)
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
                values = source[index][:5]
                values[0] += f" · 발표 {row.get('release_at')} " + citation(row)
                rows.append(values)
                break
    return ["**최근 발표 · 변화가 큰 지표**", *_table(header[:5], rows)] if rows else []


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


def _portfolio_lines(sections, preamble):
    source = sections.get("내 보유 종목 영향", "")
    lines = ["## 포트폴리오 · 교체 검토", ""]
    status = [line for line in preamble.splitlines() if "실행" in line and "매크로" in line]
    lines += status[:1] + [""]
    # Account summary tables carry exact aggregate values, units and as-of labels.
    for header, rows in tables(source):
        if header[0] == "종목":
            current = len(header) == 5 and any(re.search(r"[+\-]\d+\.\d+%", r[3]) for r in rows)
            columns = [0, 1] + ([3] if current else []) + [len(header) - 1]
            lines += _table([header[i] for i in columns], [[r[i] for i in columns] for r in rows])
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


def compose_reading_report(report, *, context, news, summary_rows, now):
    """Expose one concise main path; keep original evidence intact in one appendix.

    The legacy renderer stays independently testable. Tables are copied, not
    recomputed; all per-row missing/stale/session qualifiers remain attached.
    """
    from stock_lab_core.report_brief import build_news_brief, brief_theme
    from stock_lab_core.report_market_summary import _market_fact, korean_flow_tables, market_summary
    from stock_lab_core.report_session import market_session_states
    from stock_lab_core.earnings_pipeline import build_earnings_pipeline
    from stock_lab_core.report_earnings import compact_catalyst_lines
    from stock_lab_core.report_catalysts import post_close_brief

    parts = split_report_sections(report)
    sections = dict(parts)
    preamble = sections.get("", "")
    states = context.get("market_states") or market_session_states(now, context.get("sessions"))
    macro, indices = _board(sections)
    title = next((line for line in preamble.splitlines() if line.startswith("# ")), "# Stock Lab 자동 뉴스픽")
    macro_brief = build_news_brief(context, [r for r in records(news)
        if brief_theme(r) in {"금리·경제지표", "에너지·지정학"}], summary_rows, now, limit=3, compact=True)
    lines = [title, "", "## 매크로", "", *macro]
    lines += _recent_releases(sections, context, now)
    if macro_brief["article_keys"]:
        lines += macro_brief["lines"] + [""]
    lines += ["## 지수", "", *indices]
    pipeline = build_earnings_pipeline(context, summary_rows, news, now)
    synthesis = market_summary(context, news, context.get("closed_flow_rows", []), states, now)
    explained = {(r.get("link") or r.get("url")) for r in synthesis.get("background_news", [])}
    for market, label in (("KR", "한국 시황"), ("US", "미국 시황")):
        fact = _market_fact(context, market, states, now)
        lines += ["## " + label, "", synthesis["market_readings"].get(market) or fact["phrase"], ""]
        if market == "KR":
            # The data tables retain market, source, provisional status and unit.
            flow = korean_flow_tables(context, fact)
            for header, rows in tables("\n".join(flow)):
                lines += _table([header[0] + " · 억원(잠정)", *header[1:]], rows)
            lines += [line for line in flow if line.startswith(("출처:", "프로그램 자료 미연결:", "프로그램은", "KRX 시장 전체"))]
            lines += [""]
        brief = build_news_brief(context, [r for r in records(news) if r.get("market") == market
            and (r.get("link") or r.get("url")) not in explained | set(macro_brief["article_keys"])],
                                 summary_rows, now, limit=4, compact=True)
        if brief["article_keys"]:
            lines += [*brief["lines"], ""]
        elif not any(r.get("market") == market for r in synthesis.get("background_news", [])):
            lines += ["해당 세션의 출처·시각 기준을 통과한 핵심 기사 미확보.", ""]
        lines += _sector_table(sections, market)
        lines += compact_catalyst_lines(pipeline, market)
        if market == "US":
            after = post_close_brief(context, news, summary_rows, now)
            if after["article_keys"]:
                lines += ["**장 마감 후 · 다음 세션 재료**", *after["lines"], ""]
    lines += _portfolio_lines(sections, preamble)
    lines += _flow_lines(sections)
    lines += ["## 다음 일정", ""]
    calendar_start = len(lines)
    calendar = sections.get("다가오는 일정", "")
    # Future calendar table only. Released results are in the market catalysts.
    scheduled = calendar.split("**기업 실적 촉매**", 1)[0]
    for header, rows in tables(scheduled):
        connected = [row for row in rows if not any("미연결" in cell for cell in row)]
        if connected:
            lines += _table(header, connected)
    for header, rows in tables(calendar):
        if header[0] == "기업·상태":
            future = [row for row in rows if row[0].endswith(" · 예정")]
            if future:
                lines += _table(header, future)
    if len(lines) == calendar_start:
        lines += ["확인된 향후 일정 미연결. 상세 연결 상태는 아래 근거에서 확인할 수 있습니다.", ""]
    # Keep every original number, condition, diagnostic and source for review.
    # Retain heading structure for saved-report readers; the UI folds the rest
    # from this boundary into one expander, rather than rewriting old sections.
    lines += [f"## {AUDIT_TITLE}", "", "시장별 기준시각·원문·산식·누락 자료를 보관한 상세 근거입니다.", ""]
    lines.append(report)
    return "\n".join(lines).strip()
