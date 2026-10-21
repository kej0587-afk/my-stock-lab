"""Report-only session repair must not change trading inputs or invent closes."""

from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_prices import align_us_report_frames
from stock_lab_core.report_evidence import price_observation

NOW = datetime.fromisoformat("2026-10-21T09:15:00+09:00")


def frame(dates, values):
    return pd.DataFrame({key: values for key in ("Open", "High", "Low", "Close")}, index=pd.to_datetime(dates))


def histories():
    current = frame(["2026-10-19", "2026-10-20"], [100, 101])
    return {"^GSPC": current, "^IXIC": current.copy(), "^DJI": current.copy(),
            "SOXX": frame(["2026-10-16", "2026-10-19"], [90, 100])}


def test_lagging_assets_retried_in_one_batch_and_inputs_unchanged():
    frames = histories()
    frames["RAM"] = frames["SOXX"].copy()
    before = deepcopy(frames)
    calls = []
    def reload(tickers, period):
        calls.append((tickers, period))
        return {t: frame(["2026-10-19", "2026-10-20"], [100, 97]) for t in tickers}
    repaired, audit = align_us_report_frames(frames, frames, NOW, reload_batch=reload)
    assert calls == [(("RAM", "SOXX"), "1y")]
    assert audit["refreshed"] == ["RAM", "SOXX"] and not audit["missing"]
    assert price_observation(repaired["SOXX"], "SOXX", NOW)["return"] == pytest.approx(-.03)
    for ticker in frames:
        pd.testing.assert_frame_equal(frames[ticker], before[ticker])
    assert repaired["^GSPC"] is frames["^GSPC"]


@pytest.mark.parametrize("retry", [None, "stale", "missing_previous", "failure"])
def test_missing_or_failed_retry_never_relabels_old_close(retry):
    frames = histories()
    def reload(tickers, period):
        if retry == "failure":
            raise RuntimeError("offline")
        if retry == "missing_previous":
            return {"SOXX": frame(["2026-10-16", "2026-10-20"], [100, 97])}
        return {"SOXX": frames["SOXX"]}
    repaired, audit = align_us_report_frames(frames, frames, NOW, reload_batch=reload if retry else None)
    assert price_observation(repaired["SOXX"], "SOXX", NOW)["date"] == "2026-10-19"
    assert not audit["refreshed"] and "SOXX:" in audit["missing"][0]


def test_no_retry_for_aligned_frames_or_missing_reference():
    def forbidden(*args):
        pytest.fail("Unneeded external request")
    frames = histories()
    frames["SOXX"] = frames["^GSPC"].copy()
    _, audit = align_us_report_frames(frames, frames, NOW, reload_batch=forbidden)
    assert not audit["requested"]
    _, audit = align_us_report_frames({}, ["SOXX"], NOW, reload_batch=forbidden)
    assert not audit["expected_date"]


def test_current_kr_news_session_is_separate_from_completed_prices():
    frames = histories()
    frames["^KS11"] = frames["^GSPC"].copy()
    frames["^KQ11"] = frames["^GSPC"].copy()
    context = collect_report_context(now=NOW, price_frames=frames, economic_releases=[],
                                     calendar={"events": [], "sources": []})
    assert context["sessions"] == {"KR": "2026-10-20", "US": "2026-10-20"}
    assert context["current_news_sessions"]["KR"]["date"] == "2026-10-21"
    assert context["current_news_sessions"]["KR"]["previous_date"] == "2026-10-20"
    from stock_lab_core.today_news import partition_session_market_news
    article = {"title": "코스피 반등 전망 외국인 수급", "market": "KR", "publisher": "연합뉴스",
               "published_at": "2026-10-21T08:18:00+09:00", "link": "https://example.com/morning"}
    result = partition_session_market_news([article], context["news_sessions"], now=NOW,
                                          current_sessions=context["current_news_sessions"])
    assert not result["next_session_news"]
    assert result["current_session_news"][0]["session_date"] == "2026-10-21"
    assert result["current_session_news"][0]["is_closed"] is False


def test_real_collection_path_repairs_report_data_without_changing_summary(monkeypatch):
    from stock_lab_core import prices, report_live, report_quotes
    rows = [{"티커": "RAM", "보유량": 1, "현재비중": 10, "게이트상태": "방어우선", "Adj점수": 4}]
    before = deepcopy(rows)
    calls = []
    def batch(tickers, period):
        calls.append(tickers)
        result = {t: frame(["2026-10-19", "2026-10-20"], [100, 97]) for t in tickers}
        if len(calls) == 1:
            for t in ("SOXX", "RAM"):
                result[t] = frame(["2026-10-16", "2026-10-19"], [90, 100])
        return result
    monkeypatch.setattr(prices, "load_price_frames_batch", batch)
    monkeypatch.setattr(prices, "load_price_df", lambda *args: frame(["2026-10-19", "2026-10-20"], [100, 97]))
    monkeypatch.setattr(report_live, "supplement_kr_indices", lambda frames: frames)
    monkeypatch.setattr(report_quotes, "load_report_quotes", lambda *args, **kwargs: {})
    context = collect_report_context(rows, now=NOW, economic_releases=[],
                                     calendar={"events": [], "sources": []}, scenario_frames={})
    assert len(calls) == 2 and calls[-1] == ("RAM", "SOXX")
    assert context["prices"]["RAM"]["date"] == context["sessions"]["US"] == "2026-10-20"
    assert context["prices"]["RAM"]["return"] == pytest.approx(-.03)
    assert context["price_alignment"]["refreshed"] == ["RAM", "SOXX"]
    assert rows == before


def test_missing_prior_session_is_not_reported_as_daily_return():
    frames = histories()
    frames["SOXX"] = frame(["2026-10-16", "2026-10-20"], [90, 97])
    context = collect_report_context(now=NOW, price_frames=frames, economic_releases=[],
                                     calendar={"events": [], "sources": []})
    assert context["prices"]["SOXX"]["date"] == "2026-10-20"
    assert context["prices"]["SOXX"]["return"] is None
    assert not any(row["Ticker"] == "SOXX" for row in context["sector_rows"])


def test_gapped_reference_index_cannot_reject_normal_assets():
    frames = histories()
    frames["SOXX"] = frames["^IXIC"].copy()
    frames["^GSPC"] = frame(["2026-10-16", "2026-10-20"], [90, 101])
    context = collect_report_context(now=NOW, price_frames=frames, economic_releases=[],
                                     calendar={"events": [], "sources": []})
    assert "^GSPC" in context["price_alignment"]["unaligned"]
    assert "SOXX" not in context["price_alignment"]["unaligned"]
    assert context["prices"]["^GSPC"]["return"] is None
    assert context["prices"]["SOXX"]["return"] == pytest.approx(.01)
    assert context["news_sessions"]["US"]["previous_date"] == "2026-10-19"


def test_live_us_bar_does_not_advance_closed_reference():
    now = datetime.fromisoformat("2026-10-21T00:15:00+09:00")
    frames = histories()
    for ticker in ("^GSPC", "^IXIC", "^DJI"):
        frames[ticker] = frame(["2026-10-16", "2026-10-19", "2026-10-20"], [90, 100, 101])
    repaired, audit = align_us_report_frames(frames, frames, now)
    assert audit["expected_date"] == "2026-10-19"
    assert price_observation(repaired["SOXX"], "SOXX", now)["date"] == "2026-10-19"


def test_repartitioned_cached_articles_deduplicate_tracking_urls():
    from stock_lab_core.report_evidence import curate_news, news_article_key
    first = {"title": "코스피 하락 마감", "publisher": "연합뉴스", "published_at": "2026-10-20T16:00:00+09:00",
             "link": "https://example.com/story?id=1&utm_source=rss#top", "market": "KR", "session_date": "2026-10-20"}
    duplicate = dict(first, title="코스피 3.73% 하락 마감", link="https://example.com/story?id=1&utm_source=web")
    distinct = dict(first, title="코스피 외국인 매도 마감", link="https://example.com/story?id=2")
    result = curate_news([first, duplicate, distinct], now=NOW, session_scoped=True)
    assert len(result) == 2
    assert news_article_key(first) == news_article_key(duplicate) != news_article_key(distinct)
