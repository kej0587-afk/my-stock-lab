"""Scoped report layout; retain Markdown for safe links and file exports."""

import re

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

REPORT_STYLE = """
<style>
.st-key-market_report_reading h1 { font-size: 1.5rem; }
.st-key-market_report_reading h2 { font-size: 1.2rem; }
.st-key-market_report_reading h3 { font-size: 1.05rem; }
.st-key-market_report_reading { letter-spacing: 0; }
.st-key-market_report_reading table {
    display: block;
    width: 100%;
    overflow-x: auto;
}
.st-key-market_report_reading th { white-space: nowrap; }
.st-key-market_report_reading td {
    min-width: 5rem;
    max-width: 36rem;
    word-break: keep-all;
    overflow-wrap: break-word;
}
</style>
"""

AUDIT_TITLE = "상세 근거 · 계산 기준 · 연결 상태"
COLLAPSED_SECTIONS = frozenset({
    AUDIT_TITLE,
    "관찰 근거 · 매매 판정과 별도",
    "기준일", "경제지표", "업종별 왜", "관심 후보 상위 3개",
    "추가 핵심 뉴스", "판정 이력 비교", "다음 세션 재료", "다른 시장/다른 날짜 맥락",
    "매크로 수치 근거", "스타일 비교", "기존 점검 · 중기 흐름 참고",
    "시장방어 게이트 근거", "선택 분야별 뉴스",
    "유가 기준 감사 (보고서 전용)", "중앙은행 공식 결과", "시장 안전장치 발동 근거", "공식 중장기 전망",
})
SECTION_DETAILS = {
    "주도 업종 교체 관측": (("**반도체·AI 연관 업종의 현재 방향**", "**다른 업종에서 확인할 후보**"), "업종별 가격·RS 상세 근거"),
    "내 보유 종목 영향": ("재현 기준(내부 추정):", "보유 종목별 상세 · 산출 근거"),
    "오늘의 시장 스토리": (("### 중기·최근 거래일·현재 맥락", "관측 축 |"), "시장 스토리 상세 · 출처"),
    "다가오는 일정": ("**기업 실적 촉매**", "기업별 실적 원문·연결 상태"),
}


def _report_lines(report):
    """Locate generated Markdown boundaries without splitting fenced examples."""
    offset, fence = 0, ""
    for line in report.splitlines(keepends=True):
        marker = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = ""
        elif marker:
            fence = marker[1]
        else:
            yield offset, line
        offset += len(line)


def split_report_sections(report):
    """Return ordered (title, Markdown) slices; joining them restores the input."""
    sections, start, title = [], 0, ""
    for offset, line in _report_lines(report):
        if line.startswith("## "):
            if offset > start:
                sections.append((title, report[start:offset]))
            start, title = offset, line[3:].strip()
    if start < len(report):
        sections.append((title, report[start:]))
    return sections


def split_report_documents(report):
    """Lossless summary/evidence split, ignoring headings inside code fences."""
    for offset, line in _report_lines(report):
        if line.strip() == "## " + AUDIT_TITLE:
            return report[:offset], report[offset:]
    return report, ""


def render_report_downloads(report):
    import streamlit as st

    summary, evidence = split_report_documents(report)
    if evidence:
        for label, content, suffix in (("요약 다운로드", summary, "summary"), ("상세 근거 다운로드", evidence, "evidence")):
            st.download_button(label, content.encode("utf-8"), file_name=f"stock_lab_market_report_{suffix}.md",
                               mime="text/markdown", key=f"today_market_report_{suffix}_download", on_click="ignore")


def render_market_report(report):
    import streamlit as st

    st.markdown(REPORT_STYLE, unsafe_allow_html=True)
    with st.container(key="market_report_reading"):
        summary, evidence = split_report_documents(report)
        if evidence:
            reading_tab, evidence_tab = st.tabs(["요약", "상세 근거"])
            with reading_tab:
                _render_sections(summary)
            with evidence_tab:
                _render_sections(evidence, evidence_page=True)
            render_report_downloads(report)
        else:
            _render_sections(report)


def _render_sections(report, *, evidence_page=False):
    import streamlit as st

    for title, section in split_report_sections(report):
        if title == AUDIT_TITLE and evidence_page:
            st.markdown(section)
            continue
        if title in COLLAPSED_SECTIONS:
            with st.expander(title, expanded=False):
                st.markdown(section)
            continue
        detail = SECTION_DETAILS.get(title)
        if detail:
            marker, label = detail
            boundary = next((offset for offset, line in _report_lines(section)
                             if line.startswith(marker)), None)
            if boundary is not None:
                st.markdown(section[:boundary])
                with st.expander(label, expanded=False):
                    st.markdown(section[boundary:])
                continue
        # Unknown/older sections stay visible rather than losing their context.
        st.markdown(section)
