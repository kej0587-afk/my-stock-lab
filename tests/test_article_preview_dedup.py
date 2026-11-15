"""Offline selection contracts: fewer equivalent reads, no news-row merging."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from stock_lab_core import article_context as articles
from stock_lab_core import news_priority, report_brief


NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
STAMP = "2026-11-15T10:00:00+00:00"
PREVIEWS = (
    "(뉴욕증시-주간전망) 엔비디아 실적에 앤트로픽 상장…'AI 빅위크'",
    "엔비디아 실적발표에 쏠리는 눈...앤스로픽 상장까지(주간증시전망)",
)


def row(title, key, **changes):
    return dict(title=title, link=f"https://www.fnnews.com/news/{key}",
                publisher="파이낸셜뉴스", market="US", session_date="2026-11-13",
                published_at=STAMP, **changes)


@pytest.fixture
def reads(monkeypatch):
    calls = []

    def fetch(url, title):
        calls.append(url)
        return {"body_status": "fetch_unavailable"}

    def no_network(*args, **kwargs):
        pytest.fail("selection tests must not fetch HTTP")

    monkeypatch.setattr(articles, "_article", fetch)
    monkeypatch.setattr(articles, "_public_bytes", no_network)
    return calls


@pytest.mark.parametrize("titles", [
    PREVIEWS,
    ("Weekly preview: NVIDIA earnings and Anthropic IPO",
     "Weekly outlook: Anthropic IPO and NVDA earnings"),
    ("주간전망: 엔비디아 실적", "엔비디아 실적 발표 주목 (주간증시전망)"),
    ("주간전망: 앤트로픽 IPO", "앤스로픽 기업공개 주목 (주간증시전망)"),
])
def test_equivalent_weekly_previews_use_one_read_and_preserve_rows(reads, titles):
    rows = [row(title, str(i)) for i, title in enumerate(titles)]
    originals = deepcopy(rows)
    result = {"session_news": rows}
    articles.enrich_article_context(result, NOW)
    assert len(reads) == 1
    assert result["session_news"] is rows and len(rows) == 2
    for actual, original in zip(rows, originals):
        assert {key: actual[key] for key in original} == original
    assert sum("body_status" in item for item in rows) == 1
    assert all(not articles.verified_body_facts(item) for item in rows)


@pytest.mark.parametrize("other", [
    "주간전망: 엔비디아 실적 예상 상회",
    "주간전망: 엔비디아 실적 30% 증가",
    "주간전망: 엔비디아 실적 가이던스 하향",
    "주간전망: 엔비디아 실적과 AMD 실적",
    "주간전망: 엔비디아 실적과 FOMC",
    "주간전망: 엔비디아 실적과 앤트로픽 IPO",
    "다음 주 엔비디아 실적",
    "엔비디아 실적 발표",  # no weekly-preview marker
])
def test_distinct_facts_issuers_events_or_week_focus_keep_separate_reads(reads, other):
    items = [row("주간전망: 엔비디아 실적", "preview"), row(other, "distinct")]
    articles.enrich_article_context({"session_news": items}, NOW)
    assert set(reads) == {item["link"] for item in items}


def test_issuer_event_pairs_are_not_interchangeable(reads):
    items = [row("Weekly preview: NVIDIA earnings and Anthropic IPO", "preview"),
             row("Weekly preview: NVIDIA IPO and Anthropic earnings", "different")]
    articles.enrich_article_context({"session_news": items}, NOW)
    assert len(reads) == 2


@pytest.mark.parametrize("field,value", [
    ("published_at", "2026-11-08T10:00:00+00:00"),
    ("published_at", None),
    ("session_date", "2026-11-12"),
    ("market", "KR"),
    ("body_facts", [{"evidence": "Distinct collected result"}]),
    ("body_scenarios", [{"evidence": "Distinct collected condition"}]),
])
def test_different_coverage_or_existing_body_evidence_is_not_merged(reads, field, value):
    items = [row(PREVIEWS[0], "first"), row(PREVIEWS[1], "second")]
    items[1][field] = value
    articles.enrich_article_context({"session_news": items}, NOW)
    assert len(reads) == 2


def test_current_and_next_session_buckets_keep_independent_reads(reads):
    items = [row(PREVIEWS[0], "current"), row(PREVIEWS[1], "next")]
    result = {"session_news": [items[0]], "next_session_news": [items[1]]}
    articles.enrich_article_context(result, NOW)
    assert len(reads) == 2


def test_preview_dedup_also_applies_to_reserved_editorial_slots(reads, monkeypatch):
    items = [row(PREVIEWS[0], "first"), row(PREVIEWS[1], "second"),
             row("NVIDIA reports earnings above estimates", "result")]
    monkeypatch.setattr(report_brief, "build_news_brief", lambda *args, **kwargs: {
        "article_keys": [item["link"] for item in items]})
    articles.enrich_article_context({"session_news": items}, NOW,
                                    priority_context={"sessions": {"US": "2026-11-13"}})
    assert set(reads) == {items[0]["link"], items[2]["link"]}


def test_unsupported_preview_does_not_suppress_supported_reserved_story(reads, monkeypatch):
    items = [row(PREVIEWS[0], "unsupported"), row(PREVIEWS[1], "supported")]
    items[0]["link"] = "https://unapproved.invalid/preview"
    monkeypatch.setattr(report_brief, "build_news_brief", lambda *args, **kwargs: {
        "article_keys": [item["link"] for item in items]})
    articles.enrich_article_context({"session_news": items}, NOW,
                                    priority_context={"sessions": {"US": "2026-11-13"}})
    assert reads == [items[1]["link"]]
    assert items[0]["body_status"] == "unsupported_source"


def test_freed_preview_slot_reaches_distinct_result_within_eight_read_budget(reads, monkeypatch):
    titles = [*PREVIEWS, "NVIDIA reports earnings above estimates",
              "Fed financial stability report warns about credit risk",
              "Oracle raises cloud capital expenditure plan",
              "Eli Lilly clinical trial meets primary endpoint",
              "JPMorgan raises loan loss provisions", "Exxon raises oil production outlook",
              "Tesla reports record sales", "BAE wins defense contract"]
    items = [row(title, str(i)) for i, title in enumerate(titles)]
    monkeypatch.setattr(news_priority, "editorial_priority", lambda *args: 0)
    result = {"session_news": items}
    articles.enrich_article_context(result, NOW)
    assert len(reads) == articles.MAX_ARTICLES == 8
    assert sum(item["link"] in reads for item in items[:2]) == 1
    assert items[2]["link"] in reads  # real earnings result has its own body slot
    assert result["session_news"] == items and len(items) == len(titles)
    assert result["news_retrieval"]["article_body_attempted"] == 8


def test_verified_body_is_not_copied_to_equivalent_unread_preview(reads, monkeypatch):
    items = [row(PREVIEWS[0], "first"), row(PREVIEWS[1], "second")]

    def verified(url, title):
        reads.append(url)
        return {"body_status": "verified", "body_published_at": STAMP,
                "body_modified_at": STAMP, "body_facts": [{"evidence_basis": "body",
                "concrete_summary": "원문에서 확인한 별도 내용", "evidence": "원문에서 확인한 별도 내용"}]}

    monkeypatch.setattr(articles, "_article", verified)
    articles.enrich_article_context({"session_news": items}, NOW)
    assert len(reads) == 1
    fetched = next(item for item in items if item["link"] in reads)
    unread = next(item for item in items if item["link"] not in reads)
    assert articles.verified_body_facts(fetched)
    assert "body_status" not in unread and "body_facts" not in unread
