"""Independent, offline integration checks and regressions found in review."""

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import socket
import subprocess
import sys

import pandas as pd
import pytest

from stock_lab_core.report_brief import build_news_brief
from stock_lab_core.report_catalysts import post_close_brief
from stock_lab_core.report_evidence import curate_news


NOW = datetime.fromisoformat("2026-10-29T10:32:00+09:00")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Independent integration review is offline")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def article(**overrides):
    return dict({"title": "Alphabet stock falls after hours following earnings",
                 "market": "US", "published_at": "2026-10-28T17:00:00-04:00",
                 "publisher": "CNBC", "link": "https://www.cnbc.com/review-fixture"}, **overrides)


def context(rows):
    return {"sessions": {"US": "2026-10-28", "KR": "2026-10-28"},
            "windows": [{"market": "US", "date": "2026-10-28", "end": "2026-10-28T16:00:00-04:00"}],
            "next_session_news": rows}


@pytest.mark.parametrize("input_field", ["news", "next_session_news"])
def test_post_close_highlights_do_not_bypass_existing_source_validation(input_field):
    raw = article(publisher="Unknown publisher", link="https://unverified.example/review-fixture")
    assert curate_news([raw], now=NOW) == []
    result = post_close_brief(context([raw] if input_field == "next_session_news" else []),
                              [raw] if input_field == "news" else [], [], NOW)
    assert result == {"overview": "", "lines": [], "article_keys": []}


def test_post_close_source_validation_preserves_candidates_without_an_extra_quota(monkeypatch):
    from stock_lab_core import report_catalysts

    valid = [article(title=f"Alphabet earnings report update {index}",
                     link=f"https://www.cnbc.com/review-fixture-{index}") for index in range(6)]
    invalid = article(publisher="Unknown publisher", link="https://unverified.example/review-fixture")
    news = valid[:3]
    data = context([invalid, *valid[3:]])
    before = deepcopy((news, data))
    captured = []

    def select(rows, **kwargs):
        captured.extend(rows)
        return []

    monkeypatch.setattr(report_catalysts, "after_close_catalysts", select)
    assert post_close_brief(data, news, [], NOW) == {"overview": "", "lines": [], "article_keys": []}
    assert [row["link"] for row in captured] == [row["link"] for row in valid]
    assert (news, data) == before


def test_report_does_not_turn_cash_flow_decline_into_after_hours_share_decline():
    raw = article(title="Alphabet earnings released after hours; free cash flow falls")
    assert curate_news([raw], now=NOW)
    result = post_close_brief(context([raw]), [], [], NOW)
    assert result["article_keys"] == [raw["link"]]
    output = result["overview"] + "\n" + "\n".join(result["lines"])
    assert "시간외 하락 보도" not in output
    assert "시간외 상승 보도" not in output


def test_post_close_dataframe_shape_and_inputs_are_preserved():
    frame = pd.DataFrame([article()])
    before = frame.copy(deep=True)
    result = post_close_brief(context(frame), pd.DataFrame(), pd.DataFrame([{"티커": "CIBR"}]), NOW)
    assert set(result) == {"overview", "lines", "article_keys"}
    assert isinstance(result["overview"], str)
    assert all(isinstance(line, str) for line in result["lines"])
    pd.testing.assert_frame_equal(frame, before)


def test_post_close_paragraph_and_following_brief_are_separate_tables():
    markdown_it = pytest.importorskip("markdown_it")
    data = context([article()])
    before = deepcopy(data)
    post = post_close_brief(data, [], [], NOW)
    regular = article(title="Microsoft earnings report", published_at="2026-10-28T15:00:00-04:00",
                      session_date="2026-10-28", news_bucket="session_news")
    brief = build_news_brief(data, [regular], [], NOW)
    tokens = markdown_it.MarkdownIt("commonmark").enable("table").parse("\n".join(post["lines"] + brief["lines"]))
    assert sum(token.type == "table_open" for token in tokens) == 2
    assert data == before


@pytest.mark.parametrize("modules", [
    ("report_catalysts", "report_brief", "market_memo", "report_evidence", "report_build", "report_session"),
    ("report_evidence", "market_memo", "report_build", "report_brief", "report_catalysts", "report_session"),
])
def test_new_report_imports_have_no_cycle_in_a_fresh_offline_process(modules):
    script = f"""
import importlib
import socket
def forbidden(*args, **kwargs):
    raise AssertionError('Import must not access the network')
socket.create_connection = forbidden
socket.socket.connect = forbidden
for name in {modules!r}:
    importlib.import_module('stock_lab_core.' + name)
from stock_lab_core.report_build import get_report_build_info
sources = get_report_build_info()['sources']
for name in ('catalyst_news', 'report_catalysts'):
    assert sources['stock_lab_core.' + name]['sha256'] not in ('unavailable', 'unrecorded')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
