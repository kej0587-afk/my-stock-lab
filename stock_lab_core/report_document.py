"""Assemble one report from existing observations and decisions, without scoring."""

import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import records
from stock_lab_core.report_view import _report_lines, split_report_sections

register_loaded_source(__name__, __file__)

# Only subtract material from the sections to which it was explicitly moved.
# Identical tables in unrelated contexts must not silently disappear.
MOVED_SECTIONS = {
    "": ("", "오늘의 판단"),
    "시장방어 게이트 근거": ("오늘의 판단",),
    "지금 상태 3줄": ("지금 상태 3줄",),
    "지수·매크로 한눈에": ("매크로", "지수", "빠른 요약"),  # index table lives in 빠른 요약 (2026-11-27)
    "내 보유 종목 영향": ("포트폴리오 · 교체 검토",),
    "관심 후보 상위 3개": ("포트폴리오 · 교체 검토",),
    "주도 업종 교체 관측": ("돈흐름 · 업종 순환",),
    "중앙은행 공식 결과": ("매크로",),
    "시장 안전장치 발동 근거": ("한국 시황",),
    "다가오는 일정": ("다음 일정",),
    "경제지표": ("매크로", "물가·고용·소비·경기"),
}


def decision_summary_lines(sections, *, context, summary_rows, interpretation=""):
    """Promote the existing action/reasons/boundaries, including stale warnings."""
    preamble = sections.get("", "")
    lines = [line for line in preamble.splitlines() if line and not line.startswith("# ")]
    lines += ["", "## 오늘의 판단", ""]
    guard = context.get("market_guard") or {}
    action = str(guard.get("action") or "").strip()
    if action:
        lines += ["**기존 실행 방향** · " + action, ""]
    source = sections.get("시장방어 게이트 근거", "")
    state = next((line for line in source.splitlines() if line.startswith("현재 ")), "")
    lines += [state or "시장 게이트 입력 미연결. 현재 매수 허용 여부는 판단하지 않습니다.", ""]
    warnings = list(dict.fromkeys(str(row.get("게이트근거") or row.get("데이터상태") or "")
        for row in records(summary_rows) if "재계산 필요" in str(row.get("데이터상태") or "")))
    for warning in warnings[:1]:
        lines += ["> " + warning + ". 아래 판정은 현재 입력으로 재확인하기 전 결과입니다.", ""]
    for line in source.splitlines():
        if line.startswith("**기준일 지연"):
            lines += [line, ""]
    if interpretation:
        lines += ["**시장 해석** · " + interpretation, ""]
    reason = next((line for line in source.splitlines() if line.startswith("**핵심 요약**")), "")
    boundary = next((line for line in source.splitlines() if line.startswith("**다음 경계**")), "")
    lines += [reason or "핵심 근거 미연결: 보고서 스트레스로 시장 게이트를 대체하지 않습니다.", "",
              boundary or "재검토 조건 미연결: 오늘점검 입력을 확인하고 다시 계산해야 합니다.", "",
              "신규 진입 제한은 보유 전량 매도 지시가 아닙니다. 위 경계에 도달해도 종목별 비중·추세·손익비 체크는 별도입니다.", ""]
    current = sections.get("지금 상태 3줄", "")
    if current:
        lines += [current.strip(), ""]
    return lines


def _blocks(markdown):
    """Keep fenced text atomic and identify generated tables independently of blanks."""
    visible = {offset for offset, _ in _report_lines(markdown)}
    lines = markdown.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    def table_at(i):
        return (i + 1 < len(lines) and offsets[i] in visible and " | " in lines[i]
                and "---" in lines[i + 1] and re.fullmatch(r"[\s|:\-]+", lines[i + 1]))

    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        start = i
        if table_at(i):
            width = len(lines[i].strip().split(" | "))
            i += 2
            while i < len(lines) and len(lines[i].strip().split(" | ")) == width:
                i += 1
            yield "table", "".join(lines[start:i]).strip()
        else:
            i += 1
            while i < len(lines):
                if offsets[i] in visible and (not lines[i].strip() or table_at(i) or lines[i].startswith("#")):
                    break
                i += 1
            yield "text", "".join(lines[start:i]).strip()


def additional_evidence(report, reading):
    """Retain unique legacy evidence, not a second report or copied reader tables.

    Match complete cells (including dates, units and sources). Projected tables
    keep their original full form if it contains fields absent from the reader.
    """
    destinations = dict(split_report_sections(reading))
    output = []
    for title, section in split_report_sections(report):
        covered_text, covered_rows = set(), {}
        for destination in MOVED_SECTIONS.get(title, ()):
            for kind, block in _blocks(destinations.get(destination, "")):
                if kind == "table":
                    table = block.splitlines()
                    covered_rows.setdefault(table[0], set()).update(table[2:])
                else:
                    covered_text.add(block)
                    covered_text.update(block.splitlines())
        body = section.splitlines()
        # The legacy title is not an evidence section. Its scope/counts are above.
        if title:
            body = body[1:]
        else:
            body = [line for line in body if not line.startswith("# ")]
        remaining = []
        moved_tables = kept_tables = 0
        for kind, block in _blocks("\n".join(body)):
            if kind == "table":
                table = block.splitlines()
                rows = [row for row in table[2:] if row not in covered_rows.get(table[0], set())]
                if rows:
                    remaining.append("\n".join([*table[:2], *rows]))
                    kept_tables += 1
                else:
                    moved_tables += 1
            elif block not in covered_text:
                remaining.append(block)
        if remaining and title and moved_tables and not kept_tables:
            # Only the explanation is left; say where its table went instead of looking empty.
            shown = [name for name in MOVED_SECTIONS.get(title, ()) if name in destinations]
            if shown:
                remaining.append("표는 위 " + " · ".join(f"'{name}'" for name in shown) + " 구역에 있습니다.")
        if remaining:
            output += (["## " + title] if title else []) + remaining
    return "\n\n".join(output)
