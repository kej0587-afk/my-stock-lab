from contextlib import contextmanager, nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace

from stock_lab_core.report_view import REPORT_STYLE, render_market_report, split_report_sections


def test_report_scroll_layout_is_scoped_and_never_enables_raw_article_html(monkeypatch):
    calls = []
    def container(**kwargs):
        calls.append(("container", kwargs))
        return nullcontext()

    fake = SimpleNamespace(markdown=lambda *args, **kwargs: calls.append((args, kwargs)), container=container)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    report = "## 새 섹션\n\n<script>untrusted</script>"
    render_market_report(report)
    assert calls == [((REPORT_STYLE,), {"unsafe_allow_html": True}),
                     ("container", {"key": "market_report_reading"}), ((report,), {})]
    assert ".st-key-market_report_reading table" in REPORT_STYLE
    assert "overflow-x: auto" in REPORT_STYLE


def _render(monkeypatch, report):
    chunks, expanders, current = [], [], []

    @contextmanager
    def expander(label, *, expanded):
        assert expanded is False
        assert not current
        expanders.append(label)
        current.append(label)
        yield
        current.pop()

    def markdown(value, **kwargs):
        if value == REPORT_STYLE:
            assert kwargs == {"unsafe_allow_html": True}
        else:
            assert not kwargs
            chunks.append((current[0] if current else None, value))

    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(
        markdown=markdown, container=lambda **kwargs: nullcontext(), expander=expander))
    render_market_report(report)
    assert "".join(value for _, value in chunks) == report
    return chunks, expanders


def test_sections_preserve_order_duplicates_whitespace_and_fenced_headings():
    report = ("# 보고서\r\n\r\n## 한 줄 결론\r\n요약\r\n"
              "````markdown\r\n## 가짜 제목\r\n```\r\n````\r\n"
              "~~~\r\n## 다른 예제\r\n~~~\r\n"
              "## 한 줄 결론\r\n### 소제목\r\n마지막")
    sections = split_report_sections(report)
    assert [title for title, _ in sections] == ["", "한 줄 결론", "한 줄 결론"]
    assert "".join(section for _, section in sections) == report
    assert split_report_sections("") == []


def test_readability_sample_keeps_summary_and_caveats_visible(monkeypatch):
    report = (Path(__file__).resolve().parents[1] / "docs/samples/market_report_readability_20261021.md").read_text(encoding="utf-8")
    chunks, expanders = _render(monkeypatch, report)
    visible = "".join(value for label, value in chunks if label is None)
    for title in ("한 줄 결론", "내 보유 종목 영향", "오늘의 시장 스토리"):
        assert f"## {title}" in visible
    assert "재현 기준(내부 추정):" not in visible
    assert "관측 축 |" not in visible
    assert "빌드:" not in visible
    assert "보유 종목별 상세 · 산출 근거" in expanders
    assert "시장 스토리 상세 · 출처" in expanders
    assert "매크로 수치 근거" in expanders
    assert "기존 점검 · 중기 흐름 참고" in expanders


def test_account_caveats_and_story_summary_stay_with_their_numbers(monkeypatch):
    report = ("## 내 보유 종목 영향\n계좌 추정 보류(연결 90% 미만)\n"
              "- 실제 계좌 손익과 다릅니다.\n재현 기준(내부 추정): 상세 산식\n원시 표\n"
              "## 오늘의 시장 스토리\n종합 판단 근거 | 확인 내용\n--- | ---\n시장 | 반등\n"
              "관측 축 | 확인된 수치·범위\n--- | ---\n반복 수치 | 상세\n")
    chunks, _ = _render(monkeypatch, report)
    visible = "".join(value for label, value in chunks if label is None)
    assert "연결 90% 미만" in visible
    assert "실제 계좌 손익과 다릅니다." in visible
    assert "시장 | 반등" in visible
    assert "원시 표" not in visible
    assert "반복 수치" not in visible


def test_older_and_unknown_sections_fall_back_to_visible_markdown(monkeypatch):
    report = ("예전 형식\n## 내 보유 종목 영향\n미연결\n"
              "## 오늘의 시장 스토리\n자료 없음\n## 새 섹션\n<script>untrusted</script>")
    chunks, expanders = _render(monkeypatch, report)
    assert expanders == []
    assert all(label is None for label, _ in chunks)


def test_streamlit_report_smoke_collapsed_expanded_collapsed():
    from streamlit.testing.v1 import AppTest

    def report_app(report):
        from unittest.mock import patch

        import streamlit as st
        from stock_lab_core.report_view import render_market_report

        opened = st.checkbox("보유 상세 펼치기", key="smoke_open_details")
        real_expander = st.expander

        # AppTest has no expander click API; delegate to real Streamlit containers.
        def expander(label, *, expanded=False):
            if label == "보유 종목별 상세 · 산출 근거":
                expanded = opened
            return real_expander(label, expanded=expanded)

        with patch.object(st, "expander", expander):
            render_market_report(report)
        st.download_button("리포트 다운로드", report.encode("utf-8"),
                           file_name="stock_lab_market_report.md", mime="text/markdown",
                           key="smoke_report_download")

    report = (Path(__file__).resolve().parents[1] / "docs/samples/market_report_readability_20261021.md").read_text(encoding="utf-8")
    app = AppTest.from_function(report_app, args=(report,), default_timeout=15).run()
    original_markdown = [item.value for item in app.markdown]
    original_labels = [item.label for item in app.expander]
    assert len(original_labels) == 14

    for opened in (False, True, False):
        if opened != app.checkbox[0].value:
            app.checkbox[0].set_value(opened).run()
        assert not app.exception
        assert [item.value for item in app.markdown] == original_markdown
        assert [item.label for item in app.expander] == original_labels
        assert len(app.get("download_button")) == 1
        for item in app.expander:
            assert len(item.expander) == 1  # Only itself, no nested expander.
            assert item.proto.expanded == (opened and item.label == "보유 종목별 상세 · 산출 근거")
            assert item.markdown
