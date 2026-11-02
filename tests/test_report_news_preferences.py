from datetime import datetime
from copy import deepcopy
from threading import Event
import ast
from pathlib import Path

from stock_lab_core import today_news
from stock_lab_core.report_news_selection import (
    matching_categories, report_news_options, restore_news_preferences,
    save_news_preferences, selected_category_lines,
)

NOW = datetime.fromisoformat("2026-11-02T18:00:00+09:00")
SESSIONS = {"KR": {"date": "2026-11-02", "previous_date": "2026-10-30"},
            "US": {"date": "2026-10-30", "previous_date": "2026-10-29"}}


def row(title, link="a", **kw):
    return dict(title=title, link="https://www.reuters.com/" + link, publisher="Reuters",
                published_at="2026-11-02T16:00:00+09:00", market="GLOBAL",
                news_bucket="other_market_news", session_date="", **kw)


def test_all_requested_categories_fit_budget_with_market_windows_and_exposures():
    categories = [p["category"] for p in today_news.TODAY_MARKET_STORY_RSS_PLAN]
    windows, _ = today_news._session_news_windows(SESSIONS, NOW)
    specs = today_news._session_query_specs(windows, categories, NOW,
        held_exposures=[{"Ticker": ticker} for ticker in ("SOXL", "RAM", "CIBR", "XLK", "XLE")])
    assert len(specs) <= 16
    assert {c for spec in specs for c in spec.get("selected_categories", [])} == set(categories)
    assert {s["market"] for s in specs[:2]} == {"KR", "US"}
    assert all("코스피" not in s["url"] for s in specs if s.get("selected_categories"))


def test_preferences_survive_widget_cleanup_and_empty_is_not_defaults():
    state = {"today_market_memo_story_categories": [], "today_market_memo_story_per_category": 4,
             "today_market_memo_include_rss": True, "today_market_memo_news_count": 7}
    save_news_preferences(state)
    saved = {"_report_news_preferences": deepcopy(state["_report_news_preferences"])}
    assert report_news_options(saved)["categories"] == ()
    assert report_news_options(saved)["stock_count"] == 7
    restore_news_preferences(saved)
    assert saved["today_market_memo_story_per_category"] == 4
    assert saved["today_market_memo_include_rss"] is True


def test_topics_use_article_subject_not_search_category_and_ignore_publisher():
    assert matching_categories("조선호텔, 가을 객실 할인", ["조선"]) == []
    assert matching_categories("HD현대중공업 강세", ["조선"]) == ["조선"]
    assert matching_categories("Bitcoin gains", ["암호화폐", "에너지/해운"]) == ["암호화폐"]
    assert matching_categories("China infrastructure spending rises", ["매크로/중국", "건설·인프라"]) == ["매크로/중국", "건설·인프라"]


def test_selected_table_limits_count_shows_empty_and_avoids_fake_causality():
    context = {"news_retrieval": {"requested_categories": ["암호화폐", "조선"], "per_category": 1},
               "other_market_news": [row("Bitcoin gains", "one"), row("Ethereum falls", "two")]}
    one = "\n".join(selected_category_lines(context, NOW))
    assert one.count("암호화폐 |") == 1 and "조선 | 날짜·출처·주제 검증을 통과한 기사 없음" in one
    assert "한국/미국 등락 원인 미확정" in one
    context["news_retrieval"]["per_category"] = 3
    three = "\n".join(selected_category_lines(context, NOW))
    assert three.count("암호화폐 |") == 2
    context["other_market_news"].append(row("Bitcoin rises", "unsafe", publisher_url="https://spam.invalid"))
    context["other_market_news"][-1]["publisher"] = "spam"
    assert "unsafe" not in "\n".join(selected_category_lines(context, NOW))


def test_global_news_keeps_publication_time_and_cannot_become_us_close_cause():
    result = today_news.partition_session_market_news([
        row("Iran ceasefire agreed"), row("China infrastructure spending rises", "b"),
        dict(row("Bitcoin rises", "future"), published_at="2026-11-03T16:00:00+09:00")], SESSIONS, now=NOW)
    assert len(result["other_market_news"]) == 2
    assert not result["session_news"] and not result["next_session_news"]
    assert all(not r["session_date"] for r in result["other_market_news"])


def test_report_context_passes_preferences_to_actual_collector(monkeypatch):
    import pandas as pd
    from stock_lab_core.report_context import collect_report_context
    calls = []
    def fetch(*a, **kw):
        calls.append(kw)
        return {"session_news": [], "missing": []}
    monkeypatch.setattr(today_news, "fetch_session_market_news", fetch)
    frames = {t: pd.DataFrame({"Close": [100., 101.]}, index=pd.to_datetime(["2026-10-29", "2026-10-30"]))
              for t in ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI")}
    collect_report_context(now=NOW, price_frames=frames, economic_releases=[],
                           calendar={"events": [], "sources": []}, quote_data={}, scenario_frames={},
                           include_news=True, news_categories=("조선", "지정학"), news_per_category=1)
    assert calls[0]["categories"] == ("조선", "지정학") and calls[0]["per_category"] == 1


def test_rss_and_publisher_feed_overlap_without_duplicate_requests(monkeypatch):
    from stock_lab_core import article_context
    rss_started, publisher_started = Event(), Event()
    calls = []
    def rss(*a, **kw):
        calls.append("rss")
        rss_started.set()
        assert publisher_started.wait(2), "publisher fetch waited for RSS"
        return {"rows": [], "failures": {}, "complete": False}
    def publisher(*a, **kw):
        calls.append("publisher")
        publisher_started.set()
        assert rss_started.wait(2), "RSS waited for publisher"
        return []
    monkeypatch.setattr(today_news, "_retrieve_session_rss", rss)
    monkeypatch.setattr(article_context, "publisher_news", publisher)
    monkeypatch.setattr(article_context, "enrich_article_context", lambda *a: None)
    today_news.fetch_session_market_news(SESSIONS, now=NOW, include_article_bodies=True)
    assert sorted(calls) == ["publisher", "rss"]


def test_market_context_does_not_discard_optional_stock_news(monkeypatch):
    from stock_lab_core.market_memo import build_auto_market_memo
    import stock_lab_core.market_memo as evidence
    captured = []
    original = evidence.report_sections
    def capture(*args, **kwargs):
        captured.extend(kwargs["news"])
        return original(*args, **kwargs)
    monkeypatch.setattr(evidence, "report_sections", capture)
    stock = dict(row("NVIDIA earnings rise", "stock"), market="US", published_at="2026-10-30T15:00:00-04:00")
    context = {"news_sessions": SESSIONS, "sessions": {m: r["date"] for m, r in SESSIONS.items()},
               "session_news": [], "macro_data": {}, "prices": {}}
    build_auto_market_memo(report_context=context, news_rows=[stock], now=NOW)
    assert any(r["link"] == stock["link"] for r in captured)


def test_both_ui_generation_paths_use_preferences():
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8-sig"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    panel = functions["render_today_market_memo_panel"]
    calls = [n for n in ast.walk(panel) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_collect_today_report_context"]
    keys = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}
    assert keys["news_categories"] == "tuple(selected_market_story_categories)"
    assert keys["news_per_category"] == "market_story_per_category"
    briefing = ast.unparse(functions["_generate_today_briefing_market_memo"])
    assert "options['stock_count']" in briefing and "options['include_market']" in briefing


def test_kr_listed_stock_query_does_not_backdate_us_issuer_news():
    article = dict(row("NVIDIA announces new AI chip", "issuer"), market="KR",
                   query_market="KR", market_basis="search_query_only")
    result = today_news.partition_session_market_news([article], SESSIONS, now=NOW)
    assert not result["session_news"]
    assert result["next_session_news"][0]["market"] == "US"


def test_explicit_korean_shipbuilder_enters_kr_session_from_global_search():
    article = dict(row("조선주, 美 수주 희소식…한화오션 9.8% 상승", "ship"),
                   query_market="GLOBAL", market_basis="search_query_only")
    result = today_news.partition_session_market_news([article], SESSIONS, now=NOW)
    assert result["session_news"][0]["market"] == "KR"
    assert result["session_news"][0]["session_date"] == "2026-11-02"


def test_display_one_keeps_cross_topic_evidence(monkeypatch):
    articles = [row("Banks earnings rise", "bank"), row("Banks fund infrastructure construction", "infra")]
    monkeypatch.setattr(today_news, "_retrieve_session_rss", lambda *a, **k:
                        {"rows": articles, "failures": {}, "complete": True})
    result = today_news.fetch_session_market_news(SESSIONS, now=NOW,
        categories=("금융·은행", "건설·인프라"), per_category=1)
    assert len(result["other_market_news"]) == 2
    lines = "\n".join(selected_category_lines(result, NOW))
    assert "건설·인프라 | 날짜·출처" not in lines and "construction" in lines


def test_streamlit_controls_change_actual_generation_arguments():
    from streamlit.testing.v1 import AppTest
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8-sig"))
    panel = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_today_market_memo_panel")
    setup = '''
import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from stock_lab_core.today_news import TODAY_MARKET_STORY_RSS_PLAN
def resolve_today_market_memo_summary_df(*args): return pd.DataFrame(), "test"
def build_today_market_memo_universe(*args): return [], {}
def get_report_build_info(*args): return {"loaded_source_sha256": "test", "restart_required": False}
def invalidate_saved_report(*args): return False
def get_cached_today_market_flow_snapshot(): return {}
def build_macro_event_risk_table(): return pd.DataFrame(), None, None
def _collect_today_report_context(*args, **kwargs):
    st.session_state["collected"] = kwargs
    return {"session_news": [], "next_session_news": []}
def collect_today_auto_newspick_news(*args, **kwargs):
    st.session_state["stock_count_used"] = kwargs["max_count"]
    return [], []
def build_auto_market_memo(**kwargs): return "## 기준일\\n설정 연결 검증"
def analyze_market_memo(*args): return {"has_content": False}
'''
    app = AppTest.from_string(setup + "\n" + ast.unparse(panel) + "\nrender_today_market_memo_panel()")
    app.run()
    assert not app.exception
    assert app.number_input(key="today_market_memo_news_count").disabled
    app.checkbox(key="today_market_memo_include_rss").check().run()
    app.number_input(key="today_market_memo_news_count").set_value(7)
    app.multiselect(key="today_market_memo_story_categories").set_value(["조선", "금융·은행"])
    app.number_input(key="today_market_memo_story_per_category").set_value(1).run()
    app.button(key="today_market_memo_auto_generate").click().run()
    assert not app.exception
    assert app.session_state["stock_count_used"] == 7
    assert app.session_state["collected"] == {"include_news": True, "news_categories": ("조선", "금융·은행"), "news_per_category": 1}
    app.checkbox(key="today_market_memo_include_market_rss").uncheck().run()
    assert app.multiselect(key="today_market_memo_story_categories").disabled
    app.button(key="today_market_memo_auto_generate").click().run()
    assert not app.exception and not app.session_state["collected"]["include_news"]
