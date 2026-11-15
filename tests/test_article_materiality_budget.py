from copy import deepcopy
from stock_lab_core import article_context
from tests.test_news_impact_priority import NOW, CONTEXT, news


def test_promotions_do_not_consume_body_slots_and_distinct_us_topics_are_retained(monkeypatch):
    titles = ["Fed financial stability report warns about credit risk",
              "Nvidia reports quarterly earnings", "Oracle raises cloud capital expenditure plan",
              "Bitcoin falls after liquidation surge", "Exxon raises oil production outlook",
              "Eli Lilly clinical trial meets primary endpoint", "JPMorgan raises loan loss provisions",
              "Tesla reports record sales", "BAE wins defense contract", "Gold prices rise"]
    rows = [dict(news(title, str(i)), market="US", session_date="2026-11-04",
                 published_at="2026-11-05T06:19:00+09:00") for i, title in enumerate(titles)]
    promo = news("우리은행, 임직원과 폐전자제품 모아 재활용", "promo")
    promo_copy = deepcopy(promo)
    calls = []
    monkeypatch.setattr(article_context, "_article", lambda url, title: calls.append(title) or {"body_status": "fetch_unavailable"})
    result = {"session_news": [promo, *rows]}
    article_context.enrich_article_context(result, NOW, priority_context=CONTEXT)
    assert len(calls) == article_context.MAX_ARTICLES == 8
    assert promo["title"] not in calls
    assert promo == promo_copy  # retained as collected evidence
    assert titles[0] in calls and titles[1] in calls
    assert len(set(calls)) == len(calls)
    assert result["news_retrieval"]["article_body_verified"] == 0
    assert not any(article_context.verified_body_facts(row) for row in rows)
