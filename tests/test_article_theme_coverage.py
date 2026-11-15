"""Public-body slots cover distinct themes; headline claims remain unverified."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from stock_lab_core import article_context as articles, news_priority, report_brief


NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
STAMP = "2026-11-13T21:30:00+00:00"


def item(title, key, market="US"):
    return dict(title=title, link=f"https://www.yna.co.kr/view/SYNTHETIC_{key}",
                publisher="연합뉴스", market=market, session_date="2026-11-13",
                news_bucket="session_news", published_at=STAMP)


@pytest.fixture
def reads(monkeypatch):
    calls = []
    monkeypatch.setattr(articles, "_article", lambda url, title:
                        calls.append(url) or {"body_status": "fetch_unavailable"})
    def fail(*args, **kwargs):
        pytest.fail("selection regression must not perform HTTP")
    monkeypatch.setattr(articles, "_public_bytes", fail)
    return calls


def crowded_fixture(monkeypatch):
    primary = [item("뉴욕증시 혼조 마감", "us-wrap"), item("코스피 상승 마감", "kr-wrap", "KR"),
               item("NVIDIA earnings beat estimates", "result")]
    extra = [item("NVIDIA earnings guidance increased", "guidance", "GLOBAL"),
             item("NVIDIA CEO return petition after shares fall", "request"),
             item("NVIDIA CEO leadership uncertainty after shares fall", "leadership", "GLOBAL"),
             item("AI cloud investment credit concerns", "ai", "GLOBAL"),
             item("Bitcoin price falls after liquidation surge", "crypto", "GLOBAL"),
             item("Fed rate outlook after inflation report", "rates"),
             item("Iran oil supply disruption", "geopolitics", "GLOBAL")]
    priorities = {row["title"]: 100 - i for i, row in enumerate(primary + extra)}
    monkeypatch.setattr(news_priority, "editorial_priority", lambda row, context: priorities[row["title"]])
    monkeypatch.setattr(report_brief, "build_news_brief", lambda *args, **kwargs:
                        {"article_keys": [row["link"] for row in primary]})
    return primary, extra


def test_missing_rates_and_geopolitics_precede_second_same_theme_reads(reads, monkeypatch):
    primary, extra = crowded_fixture(monkeypatch)
    rows = primary + extra
    before = deepcopy(rows)
    result = {"session_news": rows}
    articles.enrich_article_context(result, NOW, priority_context={"sessions": {"US": "2026-11-13"}})
    assert len(reads) == articles.MAX_ARTICLES == 8
    assert all(row["link"] in reads for row in [*primary, extra[-2], extra[-1]])
    selected = result["news_retrieval"]["article_body_results"]
    assert [row["link"] for row in selected[:3]] == [row["link"] for row in primary]
    assert len(rows) == len(before)  # no original article is discarded or merged
    for row, original in zip(rows, before):
        assert {key: row[key] for key in original} == original
        assert not articles.verified_body_facts(row)
    assert result["news_retrieval"]["article_body_verified"] == 0


def test_missing_theme_with_only_unsupported_links_does_not_consume_a_slot(reads, monkeypatch):
    primary, extra = crowded_fixture(monkeypatch)
    for row in extra[-2:]:
        row["link"] = "https://news.google.com/rss/articles/" + row["link"].rsplit("_", 1)[-1]
    articles.enrich_article_context({"session_news": primary + extra}, NOW,
                                    priority_context={"sessions": {"US": "2026-11-13"}})
    assert len(reads) == 8 and not any("google.com" in url for url in reads)
    assert extra[0]["link"] in reads and extra[2]["link"] in reads  # spare slots fill distinct events


def test_visible_high_volume_themes_precede_new_single_company_categories(reads, monkeypatch):
    from stock_lab_core.report_digest import weekly_themes
    primary = [item("뉴욕증시 혼조 마감", "us-wrap"), item("코스피 상승 마감", "kr-wrap", "KR"),
               item("NVIDIA earnings beat estimates", "result")]
    headlines = ["Eli Lilly clinical trial results", "JPMorgan earnings beat forecasts",
                 "BAE defense contract announced", "Tesla sales rise", "Oracle cloud earnings beat forecasts"]
    fresh = [item(title, 'fresh'+str(i), 'GLOBAL') for i, title in enumerate(headlines)]
    themes = [item(title+str(i), 'theme'+str(i)+str(j), 'GLOBAL')
              for j,title in enumerate(("Iran oil supply disruption ", "Fed rate outlook ", "Bitcoin prices fall "))
              for i in range(4)]
    rows=primary+fresh+themes
    monkeypatch.setattr(report_brief, "build_news_brief", lambda *args, **kwargs:
                        {"article_keys": [row["link"] for row in primary]})
    monkeypatch.setattr(news_priority, "editorial_priority", lambda row, context: 100-rows.index(row))
    context={"session_news": rows}
    visible={group['label'] for group in weekly_themes(context, [], [], NOW)['themes']}
    assert {'지정학·에너지', '통화정책·금리·물가', '암호화폐·유동성'} <= visible
    articles.enrich_article_context(context, NOW, priority_context={"sessions": {"US":"2026-11-13"}})
    assert len(reads)==8
    for term in ('Iran', 'Fed', 'Bitcoin'):
        assert any(row['link'] in reads and term in row['title'] for row in themes)


def test_close_wraps_remain_selected_before_uncovered_themes_fill_budget(reads, monkeypatch):
    primary = [item("NVIDIA earnings beat estimates", "p1"),
               item("Oracle cloud earnings beat forecasts", "p2"),
               item("JPMorgan earnings beat forecasts", "p3")]
    wraps = [item("뉴욕증시 혼조 마감", "us-wrap"), item("코스피 상승 마감", "kr-wrap", "KR")]
    themes = [item(title, str(i), "GLOBAL") for i, title in enumerate([
        "Fed rate outlook", "Iran oil supply concerns", "Bitcoin prices fall", "Tesla sales rise",
        "Eli Lilly clinical trial results", "BAE defense contract announced"])]
    monkeypatch.setattr(report_brief, "build_news_brief", lambda *args, **kwargs:
                        {"article_keys": [row["link"] for row in primary]})
    monkeypatch.setattr(news_priority, "editorial_priority", lambda row, context: 0 if row in wraps else 10)
    articles.enrich_article_context({"session_news": primary + themes + wraps}, NOW,
                                    priority_context={"sessions": {"US": "2026-11-13"}})
    assert len(reads) == 8
    assert all(row["link"] in reads for row in primary + wraps)


def test_different_events_in_one_theme_fill_remaining_slots_and_url_dedup_holds(reads, monkeypatch):
    rows = [item("NVIDIA earnings beat estimates", "result"),
            item("NVIDIA raises earnings guidance", "guidance"),
            item("NVIDIA export regulation announced", "regulation", "GLOBAL")]
    monkeypatch.setattr(news_priority, "editorial_priority", lambda *args: 0)
    result = {"session_news": [*rows, deepcopy(rows[0])]}
    articles.enrich_article_context(result, NOW)
    assert set(reads) == {row["link"] for row in rows} and len(reads) == 3


def test_generic_index_mention_does_not_receive_a_close_wrap_reservation(reads, monkeypatch):
    primary = [item(title, str(i)) for i, title in enumerate([
        "NVIDIA earnings beat estimates", "Oracle cloud earnings beat forecasts", "JPMorgan earnings beat forecasts"])]
    others = [item(title, str(i + 3), "GLOBAL") for i, title in enumerate([
        "Fed rate outlook", "Iran oil supply concerns", "Bitcoin prices fall", "Tesla sales rise", "Eli Lilly clinical trial results"])]
    generic = item("뉴욕증시 시장 동향 분석", "generic")
    monkeypatch.setattr(report_brief, "build_news_brief", lambda *args, **kwargs:
                        {"article_keys": [row["link"] for row in primary]})
    monkeypatch.setattr(news_priority, "editorial_priority", lambda row, context: 0 if row is generic else 10)
    articles.enrich_article_context({"session_news": primary + others + [generic]}, NOW,
                                    priority_context={"sessions": {"US": "2026-11-13"}})
    assert len(reads) == 8 and generic["link"] not in reads


@pytest.mark.parametrize("status", ["no_supported_context", "fetch_unavailable"])
def test_unsuccessful_new_theme_never_triggers_ninth_read_or_fact_promotion(reads, monkeypatch, status):
    primary, extra = crowded_fixture(monkeypatch)
    def fetch(url, title):
        reads.append(url)
        return dict(body_status=status, body_published_at=STAMP, body_modified_at=STAMP)
    monkeypatch.setattr(articles, "_article", fetch)
    result = {"session_news": primary + extra}
    articles.enrich_article_context(result, NOW, priority_context={"sessions": {"US": "2026-11-13"}})
    assert len(reads) == 8 and result["news_retrieval"]["article_body_verified"] == 0
    assert not any(articles.verified_body_facts(row) for row in result["session_news"])
