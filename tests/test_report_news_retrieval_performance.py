"""Offline report-news measurements: synthetic latency, never Cloud timings."""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
from threading import Lock
from time import perf_counter, sleep
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from stock_lab_core import article_context, today_news
from stock_lab_core.report_context import collect_report_context
from stock_lab_core.performance import PerformanceTrace


NOW = datetime.fromisoformat("2026-10-28T14:00:10+09:00")
CLOSED = {market: {"date": "2026-10-27", "previous_date": "2026-10-26"}
          for market in ("KR", "US")}
ACTIVE = {"KR": {"date": "2026-10-28", "previous_date": "2026-10-27", "is_active": True}}


def clear_news_caches():
    clear = getattr(today_news, "clear_session_market_news_cache", today_news._cached_session_rss.clear)
    clear()
    article_context._feed.clear()
    article_context._article.clear()


@pytest.fixture(autouse=True)
def isolated_news(monkeypatch):
    clear_news_caches()

    def unexpected(*args, **kwargs):
        raise AssertionError("Unexpected real network or credential access")

    monkeypatch.setattr(today_news.urllib.request, "urlopen", unexpected)
    monkeypatch.setattr(article_context.requests.sessions.Session, "request", unexpected)
    from stock_lab_core import economic_releases
    monkeypatch.setattr(economic_releases, "_api_key", unexpected)
    yield
    clear_news_caches()


def rss(market="US", published=None):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = ("Wall Street stocks close higher on earnings" if market == "US"
                                          else "코스피 반도체 강세")
    ET.SubElement(item, "link").text = "https://www.reuters.com/markets/" + market.lower()
    ET.SubElement(item, "pubDate").text = published or (
        "Tue, 27 Oct 2026 16:05:00 -0400" if market == "US" else "Wed, 28 Oct 2026 13:55:00 +0900")
    ET.SubElement(item, "source", url="https://www.reuters.com").text = "Reuters"
    return ET.tostring(root)


def install_providers(monkeypatch, delay=0.01):
    counts, lock = Counter(), Lock()

    def fetch(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)["q"][0]
        market = "KR" if any(word in query for word in ("코스피", "한국", "바이오")) else "US"
        with lock:
            counts["rss"] += 1
        sleep(delay)
        return BytesIO(rss(market))

    def public_bytes(url):
        with lock:
            counts["publisher_feed"] += 1
        sleep(delay)
        return rss(), url

    monkeypatch.setattr(today_news.urllib.request, "urlopen", fetch)
    monkeypatch.setattr(article_context, "_public_bytes", public_bytes)
    # Use the real feed cache with a stable, supported direct article.
    monkeypatch.setattr(article_context, "parse_publisher_feed", lambda data: [{
        "title": "뉴욕증시 마감: 실적 호조", "link": "https://www.yna.co.kr/view/offline-fixture",
        "publisher": "연합뉴스", "publisher_url": "https://www.yna.co.kr", "market": "US",
        "published_at": "2026-10-27T16:10:00-04:00", "source": "Yonhap public RSS",
    }])

    def article(url, title):
        with lock:
            counts["article_body"] += 1
        sleep(delay)
        return {"body_status": "verified", "body_facts": [{"topic": "earnings"}],
                "body_published_at": "2026-10-27T16:10:00-04:00",
                "body_modified_at": "2026-10-27T16:10:00-04:00"}

    # Keep the existing success/failure cache while injecting body retrieval.
    monkeypatch.setattr(article_context, "_article", today_news.cache_result(
        ttl=21_600, failure_ttl=30, is_success=lambda row: row.get("body_status") == "verified")(article))
    return counts


def report_context():
    frames = {ticker: pd.DataFrame({"Close": [100.0, 101.0]},
                                   index=pd.to_datetime(["2026-10-26", "2026-10-27"]))
              for ticker in ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI")}
    return collect_report_context(now=NOW, price_frames=frames, economic_releases=[],
                                  calendar={"events": [], "sources": []}, live_frames={},
                                  scenario_frames={}, quote_data={}, include_news=True)


def news_payload(context):
    return {key: deepcopy(context[key]) for key in (
        "session_news", "next_session_news", "current_session_news", "other_market_news",
        "windows", "current_windows", "news_retrieval", "missing", "market_states", "sessions")}


def test_controlled_report_news_cold_and_warm_three_repeats(monkeypatch):
    """Run unchanged before/after; preserve real lower-level cache behavior."""
    counts = install_providers(monkeypatch)
    # Imports and deterministic classification are warmed before the measured runs.
    expected = news_payload(report_context())
    measurements = []
    for repeat in range(3):
        clear_news_caches()
        counts.clear()
        for state in ("cold", "warm", "warm"):
            previous = counts.copy()
            started = perf_counter()
            result = report_context()
            elapsed = perf_counter() - started
            assert news_payload(result) == expected
            calls = dict(counts - previous)
            if state == "warm":
                assert not calls
            else:
                assert calls["rss"] > 0 and calls["publisher_feed"] == 2 and calls["article_body"] == 1
            measurements.append({"repeat": repeat + 1, "state": state,
                                 "seconds": round(elapsed, 6), "synthetic_requests": calls})
    print("synthetic_report_news=" + json.dumps({
        "provider_delay_seconds": 0.01, "cloud_measurement": False,
        "output_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(),
        "output_equal": True, "runs": measurements}, sort_keys=True))


def test_warm_batch_repartitions_exact_now_and_does_not_leak_mutations(monkeypatch):
    calls = []
    original = today_news._retrieve_session_rss

    def retrieve(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(today_news, "_retrieve_session_rss", retrieve)
    monkeypatch.setattr(today_news.urllib.request, "urlopen", lambda *a, **kw:
                        BytesIO(rss("KR", "Wed, 28 Oct 2026 14:00:20 +0900")))
    options = dict(sessions=CLOSED, current_sessions=ACTIVE, use_cache=True)
    early = today_news.fetch_session_market_news(now=NOW, **options)
    assert not early["current_session_news"]
    later = today_news.fetch_session_market_news(now=NOW + timedelta(seconds=20), **options)
    assert len(calls) == 1
    assert later["current_session_news"][0]["market"] == "KR"
    assert later["current_windows"][0]["end"] == "2026-10-28T14:00:30+09:00"
    later["current_session_news"][0]["title"] = "mutated"
    again = today_news.fetch_session_market_news(now=NOW + timedelta(seconds=20), **options)
    assert again["current_session_news"][0]["title"] != "mutated"
    assert early == today_news.fetch_session_market_news(now=NOW, **options)


@pytest.mark.parametrize("change", ["market", "date", "previous_date", "close_at", "exposure", "category", "minute"])
def test_batch_key_includes_sessions_market_queries_and_time(monkeypatch, change):
    calls = []

    def retrieve(specs, **kwargs):
        calls.append(deepcopy(specs))
        return {"rows": [], "failures": Counter(), "complete": True}

    monkeypatch.setattr(today_news, "_retrieve_session_rss", retrieve)
    options = dict(sessions=deepcopy(CLOSED), current_sessions=deepcopy(ACTIVE), now=NOW, use_cache=True)
    today_news.fetch_session_market_news(**options)
    today_news.fetch_session_market_news(**dict(options, now=NOW.astimezone(timezone.utc)))
    assert len(calls) == 1
    if change == "market":
        options["sessions"].pop("US")
    elif change in ("date", "previous_date"):
        options["sessions"]["US"][change] = "2026-10-26" if change == "date" else "2026-10-23"
        options["sessions"]["US"]["previous_date"] = "2026-10-23"
    elif change == "close_at":
        options["current_sessions"]["KR"]["close_at"] = "2026-10-28T14:30:00+09:00"
    elif change == "exposure":
        options["held_exposures"] = [{"Ticker": "XLE"}]
    elif change == "category":
        options["categories"] = ("반도체·AI",)
    else:
        options["now"] += timedelta(minutes=1)
    today_news.fetch_session_market_news(**options)
    assert len(calls) == 2


@pytest.mark.parametrize("bad", [([], ""), ([], "US: RSS unavailable")])
def test_empty_and_failed_batch_not_retained_by_success_cache(monkeypatch, bad):
    calls = []
    spec = {"market": "US", "category": "market", "url": "https://example.test/rss"}

    def fetch(spec):
        calls.append(1)
        return bad if len(calls) == 1 else ([{"title": "recovered"}], "")

    # Isolate the new layer; underlying failures have their existing 30s cooldown.
    fetch.clear = lambda: None
    monkeypatch.setattr(today_news, "_cached_session_rss", fetch)
    first = today_news._cached_session_rss_batch([spec], ("US",), 1)
    assert not first["complete"]
    recovered = today_news._cached_session_rss_batch([spec], ("US",), 1)
    assert recovered["rows"] == [{"title": "recovered"}]
    assert recovered == today_news._cached_session_rss_batch([spec], ("US",), 1)
    assert len(calls) == 2


def test_partial_batch_and_exceptions_are_not_retained(monkeypatch):
    calls = []

    def retrieve(specs, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {"rows": [{"title": "partial"}], "failures": Counter({"US: failed": 1}), "complete": False}
        if len(calls) == 2:
            raise TimeoutError("offline")
        return {"rows": [{"title": "complete"}], "failures": Counter(), "complete": True}

    monkeypatch.setattr(today_news, "_retrieve_session_rss", retrieve)
    assert not today_news._cached_session_rss_batch([], (), 1)["complete"]
    with pytest.raises(TimeoutError):
        today_news._cached_session_rss_batch([], (), 1)
    assert today_news._cached_session_rss_batch([], (), 1)["complete"]
    assert today_news._cached_session_rss_batch([], (), 1)["complete"]
    assert len(calls) == 3


def test_success_ttl_is_short_and_failure_cooldown_is_not_extended():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(today_news._cached_session_rss_batch))
    decorator = tree.body[0].decorator_list[0]
    options = {item.arg: ast.literal_eval(item.value) for item in decorator.keywords if item.arg != "is_success"}
    assert options == {"ttl": 60, "failure_ttl": 0}


def test_explicit_refresh_clears_both_rss_layers_and_public_articles(monkeypatch):
    counts = install_providers(monkeypatch, delay=0)
    first = news_payload(report_context())
    initial = counts.copy()
    assert news_payload(report_context()) == first
    assert counts == initial
    today_news.clear_session_market_news_cache()
    assert news_payload(report_context()) == first
    assert counts == Counter({key: value * 2 for key, value in initial.items()})


def test_report_news_span_is_separate_from_full_context(monkeypatch):
    install_providers(monkeypatch, delay=0)
    with PerformanceTrace(scope="offline_report_news") as trace:
        report_context()
    entries = {row["name"]: row for row in trace.report()["functions"]}
    assert entries["report_news"]["calls"] == 1
    assert 0 < entries["report_news"]["active_wall_seconds"] <= entries["report_context"]["active_wall_seconds"]


def test_cached_retrieval_respects_explicit_us_early_close_and_holiday_gap(monkeypatch):
    sessions = {"US": {"date": "2026-11-25", "previous_date": "2026-11-24"}}
    active = {"US": {"date": "2026-11-27", "previous_date": "2026-11-25",
                     "close_at": "2026-11-27T13:00:00-05:00"}}
    row = {"title": "Wall Street semiconductor stocks rise", "market": "US",
           "published_at": "2026-11-27T12:59:55-05:00", "publisher": "Reuters",
           "publisher_url": "https://www.reuters.com", "link": "https://www.reuters.com/markets/early-close"}
    monkeypatch.setattr(today_news, "_fetch_session_rss", lambda spec: ([dict(row)], ""))
    options = dict(sessions=sessions, current_sessions=active, use_cache=True)
    before = today_news.fetch_session_market_news(now="2026-11-27T12:59:50-05:00", **options)
    assert not before["current_session_news"]
    during = today_news.fetch_session_market_news(now="2026-11-27T12:59:55-05:00", **options)
    assert during["current_session_news"][0]["session_date"] == "2026-11-27"
    assert during["current_windows"][0]["start"] == "2026-11-25T16:00:00-05:00"
    closed = today_news.fetch_session_market_news(now="2026-11-27T13:00:00-05:00", **options)
    assert not closed["current_session_news"] and not closed["current_windows"]
    assert any("개폐장" in reason for reason in closed["missing"])


def test_cached_raw_news_rechecks_article_version_at_exact_now(monkeypatch):
    install_providers(monkeypatch, delay=0)
    original = article_context._article.__wrapped__

    def article(url, title):
        return dict(original(url, title), body_modified_at="2026-10-27T16:10:20-04:00")

    monkeypatch.setattr(article_context, "_article", today_news.cache_result(
        ttl=21_600, failure_ttl=30, is_success=lambda row: row.get("body_status") == "verified")(article))
    options = dict(sessions=CLOSED, include_article_bodies=True, use_cache=True)
    early = today_news.fetch_session_market_news(now="2026-10-27T16:10:10-04:00", **options)
    later = today_news.fetch_session_market_news(now="2026-10-27T16:10:30-04:00", **options)
    early_article = next(row for row in early["session_news"] if "yna.co.kr" in row["link"])
    later_article = next(row for row in later["session_news"] if "yna.co.kr" in row["link"])
    assert early_article["body_status"] == "article_version_after_report"
    assert later_article["body_status"] == "verified"


@pytest.mark.parametrize("query_market", ["US", "KR"])
def test_oct28_0643_kst_anthropic_recap_belongs_to_oct27_us_close(monkeypatch, query_market):
    # User-supplied headline/time fixture, not a live source verification.
    story = {"title": "뉴욕증시, 앤트로픽 훈풍에 기술주 강세…나스닥 1.2%↑ 마감",
             "published_at": "2026-10-28T06:43:00+09:00", "publisher": "연합뉴스",
             "publisher_url": "https://www.yna.co.kr", "link": "https://www.yna.co.kr/view/offline-anthropic-recap",
             "source": "Google News RSS", "market": query_market, "query_market": query_market}
    monkeypatch.setattr(today_news, "_fetch_session_rss", lambda spec: ([deepcopy(story)], ""))
    options = dict(sessions=CLOSED, current_sessions=ACTIVE, now=NOW, use_cache=True)
    for _ in range(2):
        result = today_news.fetch_session_market_news(**options)
        row, = result["session_news"]
        assert row["market"] == "US" and row["session_date"] == "2026-10-27"
        assert row["is_close_wrap"] and row["retrospective_close_wrap"] and row["is_closed"]
        assert row["market_local_published_at"] == "2026-10-27T17:43:00-04:00"
        assert row["news_timing"] == "미국장 마감 회고 · 기사 주장"
        assert not result["current_session_news"] and not result["next_session_news"]
    assert story["market"] == query_market
