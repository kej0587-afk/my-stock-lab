from contextlib import nullcontext
import sys
from types import SimpleNamespace

from stock_lab_core.report_view import REPORT_STYLE, render_market_report


def test_report_scroll_layout_is_scoped_and_never_enables_raw_article_html(monkeypatch):
    calls = []
    def container(**kwargs):
        calls.append(("container", kwargs))
        return nullcontext()

    fake = SimpleNamespace(markdown=lambda *args, **kwargs: calls.append((args, kwargs)), container=container)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    report = "## 판정 이력 비교\n\n<script>untrusted</script>"
    render_market_report(report)
    assert calls == [((REPORT_STYLE,), {"unsafe_allow_html": True}),
                     ("container", {"key": "market_report_reading"}), ((report,), {})]
    assert ".st-key-market_report_reading table" in REPORT_STYLE
    assert "overflow-x: auto" in REPORT_STYLE
