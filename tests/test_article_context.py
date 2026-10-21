from copy import deepcopy
from datetime import datetime
import json
from unittest.mock import patch

import pytest

from stock_lab_core import article_context as articles
from stock_lab_core.report_brief import news_brief_lines
from stock_lab_core.report_market_summary import market_summary
from stock_lab_core.report_session import market_session_states

NOW = datetime.fromisoformat("2026-10-21T20:00:00+09:00")
URL = "https://www.yna.co.kr/view/FIXTURE"
TITLE = "코스피, AI 투자심리 회복에 상승 마감"


def page(*, published="2026-10-21T16:20:00+09:00", modified=None, free=True, headline=TITLE):
    meta = {"@type": "NewsArticle", "headline": headline, "datePublished": published,
            "dateModified": modified or published, "isAccessibleForFree": free}
    return ('<meta charset="utf-8"><script type="application/ld+json">' + json.dumps(meta) + '</script>'
            '<article class="story-summary">AI 투자 붕괴와 차입 우려라고 오분류하지 않습니다.</article>'
            '<div class="story-news article">'
            '<p>AI 관련 기업의 호실적과 설비투자 확대 발표가 투자심리 개선 배경으로 거론됐다.</p>'
            '<p>한국의 수출이 일평균 역대 최대를 기록해 투자심리가 개선됐다는 설명이다.</p>'
            '<p>외국인은 유가증권시장에서 현물을 순매수했다. 선물 수급은 다른 방향이었다.</p>'
            '</div>').encode()


def row(**changes):
    return dict(title=TITLE, link=URL, publisher="연합뉴스", market="KR", session_date="2026-10-21",
                published_at="2026-10-21T16:20:00+09:00", news_bucket="session_news", is_close_wrap=True, **changes)


def test_public_body_rules_exclude_summary_and_retain_only_short_evidence():
    result = articles.parse_article(page(), URL, TITLE)
    assert result["body_status"] == "verified"
    assert [fact["topic"] for fact in result["body_facts"]] == ["ai_investment", "exports", "foreign_buying"]
    assert all(len(fact["evidence"]) <= 141 for fact in result["body_facts"])
    assert "articleBody" not in result and "paragraphs" not in result
    assert len(result["body_sha256"]) == 64


@pytest.mark.parametrize("url", ["http://www.yna.co.kr/view/FIXTURE", "https://127.0.0.1/a", "https://www.yna.co.kr.evil.invalid/a",
                                "https://user:password@www.yna.co.kr/a", "https://www.yna.co.kr:8501/a"])
def test_article_source_validation_rejects_private_redirect_and_credentials(url):
    assert not articles._safe_url(url)
    assert articles.parse_article(page(), url, TITLE)["body_status"] == "unsupported_source"


@pytest.mark.parametrize("kwargs,status", [({"free": False}, "restricted_article"),
                                          ({"headline": "다른 기사의 제목"}, "headline_mismatch"),
                                          ({"published": "2026-10-21"}, "article_timestamp_unavailable")])
def test_article_requires_matching_identity_public_access_and_timestamp(kwargs, status):
    assert articles.parse_article(page(**kwargs), URL, TITLE)["body_status"] == status


def test_feed_ignores_unrelated_and_unapproved_links():
    xml = b'''<rss><channel><item><title>KOSPI</title><link>https://127.0.0.1/a</link><pubDate>Wed, 21 Oct 2026 16:20:00 +0900</pubDate></item></channel></rss>'''
    assert not articles.parse_publisher_feed(xml)


def test_enrichment_is_bounded_and_rejects_future_revision():
    rows = [dict(row(), link=URL + str(i), market="KR" if i < 5 else "US") for i in range(10)]
    result = {"session_news": rows}
    with patch.object(articles, "_article", return_value=articles.parse_article(page(modified="2026-10-21T21:00:00+09:00"), URL, TITLE)) as loader:
        articles.enrich_article_context(result, NOW)
    assert loader.call_count == articles.MAX_ARTICLES
    assert result["news_retrieval"]["article_body_verified"] == 0
    assert sum(r.get("body_status") == "article_version_after_report" for r in rows) == 4


def test_body_story_connects_event_interpretation_holdings_and_next_check_without_mutation():
    item = dict(row(), **articles.parse_article(page(), URL, TITLE))
    context = {"sessions": {"KR": "2026-10-21", "US": "2026-10-20"},
               "prices": {"^KS11": {"date": "2026-10-21", "return": .0329}}}
    held = [{"티커": "SOXL", "보유량": 1, "게이트상태": "방어우선"}]
    original = deepcopy((context, item, held))
    brief = "\n".join(news_brief_lines(context, [item], held, NOW))
    assert "사실(본문)" in brief and "해석(추정)" in brief and "SOXL" in brief and "다음 확인" in brief
    assert "기사 본문 확인" in brief and "제목만 확인" not in brief
    summary = market_summary(context, [item], [], market_session_states(NOW, context["sessions"]), NOW)
    assert "설비투자" not in summary["headline"]  # Raw article prose is not copied.
    assert "AI 실적·투자 확대" in summary["headline"] and "한국 수출 호조" in summary["headline"]
    assert (context, item, held) == original


def test_generic_ai_credit_article_links_underlying_exposure_without_direct_ticker_mention():
    item = dict(row(), title="Wall Street AI debt concerns", market="US", session_date="2026-10-20",
                published_at="2026-10-20T15:00:00-04:00", is_close_wrap=False)
    context = {"sessions": {"KR": "2026-10-21", "US": "2026-10-20"}}
    brief = "\n".join(news_brief_lines(context, [item], [{"티커": "SOXL", "보유량": 1}], NOW))
    assert "SOXL" in brief and "제목만 확인" in brief


def test_verified_original_link_only_backfills_its_exact_close_session_without_network():
    with patch.object(articles, "_feed", return_value={"rows": [], "status": "unavailable"}):
        rows = articles.publisher_news({"US": {"date": "2026-10-20"}}, NOW)
        assert len(rows) == 1 and rows[0]["session_date"] == "2026-10-20"
        assert not articles.publisher_news({"US": {"date": "2026-10-21"}}, NOW)
        assert not articles.publisher_news({"US": {"date": "2026-10-20"}}, datetime.fromisoformat("2026-10-20T20:00:00+09:00"))
