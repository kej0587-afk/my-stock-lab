from datetime import datetime, timezone

import pytest

from stock_lab_core.today_news import partition_session_market_news


SESSIONS = {
    "US": {"date": "2026-10-16", "previous_date": "2026-10-15"},
    "KR": {"date": "2026-10-16", "previous_date": "2026-10-15"},
}
NOW = datetime.fromisoformat("2026-10-18T18:00:00+09:00")


def article(title, timestamp, market="US", **extra):
    return dict(title=title, market=market, published_at=timestamp, **extra)


def test_close_boundaries_exclude_previous_close_and_include_reference_close():
    rows = [
        article("previous", "2026-10-15T16:00:00-04:00"),
        article("overnight", "2026-10-15T16:00:01-04:00"),
        article("Stocks close higher", "2026-10-16T16:00:00-04:00"),
        article("post-close", "2026-10-16T16:00:01-04:00"),
        article("Saturday", "2026-10-17T12:00:00-04:00"),
        article("Sunday", "2026-10-18T02:00:00-04:00"),
    ]
    result = partition_session_market_news(rows, SESSIONS, now=NOW)
    assert [r["title"] for r in result["session_news"]] == ["Stocks close higher", "overnight"]
    assert {r["title"] for r in result["next_session_news"]} == {"post-close", "Saturday", "Sunday"}
    assert all(r["session_date"] == "2026-10-16" for r in result["next_session_news"])


def test_post_close_wrap_is_labeled_retrospective_not_a_preclose_cause():
    result = partition_session_market_news([
        article("Wall Street stocks close lower due to chip stocks", "2026-10-16T16:05:00-04:00"),
        article("뉴욕증시 마감: 반도체 하락", "2026-10-17T06:00:00+09:00"),
    ], SESSIONS, now=NOW)
    assert not result["next_session_news"]
    assert len(result["session_news"]) == 2
    assert all(r["retrospective_close_wrap"] for r in result["session_news"])
    window = next(w for w in result["windows"] if w["market"] == "US")
    assert window["capture_end"] == "2026-10-18T00:00:00-04:00"
    assert datetime.fromisoformat(window["capture_end"]) < NOW


def test_timezones_and_markets_never_infer_from_korean_language():
    instant = "2026-10-16T16:00:00+09:00"
    result = partition_session_market_news([
        article("한국어 미국 증시 기사", instant, "US"),
        article("Korean stock market", instant, "KR"),
        article("미국 증시", instant, ""),
        article("코스피", instant, "US,KR"),
    ], SESSIONS, now=NOW)
    assert [r["title"] for r in result["session_news"]] == ["한국어 미국 증시 기사"]
    assert [r["title"] for r in result["next_session_news"]] == ["Korean stock market"]
    assert any("명시된 시장" in reason for reason in result["missing"])


@pytest.mark.parametrize("stamp", ["", None, "10/16 15:00", "2026-10-16", "bad", "2026-10-32T00:00:00Z"])
def test_ambiguous_or_invalid_publication_time_is_excluded(stamp):
    result = partition_session_market_news([article("Stocks rise", stamp)], SESSIONS, now=NOW)
    assert not result["session_news"] and not result["next_session_news"]
    assert any("발행시각" in reason for reason in result["missing"])


def test_iso_naive_is_kst_and_future_has_no_tolerance():
    result = partition_session_market_news([
        article("naive", "2026-10-17 04:59:00"),
        article("exact now", NOW),
        article("future", "2026-10-18T18:00:01+09:00"),
    ], SESSIONS, now=NOW)
    assert [r["title"] for r in result["session_news"]] == ["naive"]
    assert [r["title"] for r in result["next_session_news"]] == ["exact now"]


@pytest.mark.parametrize("session", [
    "2026-10-16", {}, {"date": "2026-10-16"},
    {"date": "2026-10-16", "previous_date": "2026-10-16"},
    {"date": "2026-10-16", "previous_date": "2026-10-17"},
    {"date": "2026-10-18", "previous_date": "2026-10-16"},
])
def test_no_guessed_previous_session(session):
    result = partition_session_market_news([], {"US": session}, now=NOW)
    assert not result["windows"] and result["missing"]


def test_unclosed_reference_is_missing_and_empty_sessions_are_explicit():
    result = partition_session_market_news([], {"US": SESSIONS["US"]},
                                           now="2026-10-16T15:59:59-04:00")
    assert not result["windows"] and any("미마감" in r for r in result["missing"])
    assert partition_session_market_news([], {}, now=NOW)["missing"]


def test_supplied_previous_session_spans_weekend_without_calendar_guessing():
    sessions = {"US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}
    result = partition_session_market_news([
        article("Sunday news is Monday context", "2026-10-18T18:00:00-04:00"),
    ], sessions, now="2026-10-19T17:00:00-04:00")
    assert len(result["session_news"]) == 1
    assert result["windows"][0]["start"] == "2026-10-16T16:00:00-04:00"


def test_us_dst_changes_between_previous_and_current_session():
    sessions = {"US": {"date": "2026-11-02", "previous_date": "2026-10-30"}}
    result = partition_session_market_news([
        article("Stocks close", "2026-11-02T21:00:00Z"),
        article("Stocks post close", "2026-11-02T21:00:01Z"),
    ], sessions, now=datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert result["windows"][0]["start"].endswith("16:00:00-04:00")
    assert result["windows"][0]["end"].endswith("16:00:00-05:00")
    assert len(result["session_news"]) == len(result["next_session_news"]) == 1


def test_partition_is_pure_and_preserves_explicit_metadata():
    row = article("Stocks rise", "2026-10-16T15:00:00-04:00", source_id="N1", event_key="supplied")
    before = dict(row)
    result = partition_session_market_news([row], SESSIONS, now=NOW)
    assert row == before
    assert result["session_news"][0]["event_key"] == "supplied"
    assert result["session_news"][0]["source_id"] == "N1"


def test_conflicting_market_region_metadata_is_excluded():
    result = partition_session_market_news([
        article("Mixed stock market report", "2026-10-16T15:00:00-04:00", region="KR"),
    ], SESSIONS, now=NOW)
    assert not result["session_news"] and not result["next_session_news"]


def test_close_wrap_priority_survives_a_more_recent_intraday_story():
    result = partition_session_market_news([
        article("Oil prices rise", "2026-10-16T15:59:00-04:00"),
        article("US stock market closes lower", "2026-10-16T15:58:00-04:00"),
    ], SESSIONS, now=NOW)
    assert result["session_news"][0]["is_close_wrap"]

