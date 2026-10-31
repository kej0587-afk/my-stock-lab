"""Synthetic market-wrap regressions; no network or copied article body."""

from copy import deepcopy
from datetime import datetime
from html import escape
import json

import pytest

from stock_lab_core import article_context as articles
from stock_lab_core.report_brief import news_brief_lines
from stock_lab_core.report_market_summary import market_summary
from stock_lab_core.report_session import market_session_states


URL = "https://www.yna.co.kr/view/SYNTHETIC_OCT31"
TITLE = "뉴욕증시, AI 투자 우려에 기술주 하락 마감"
NOW = datetime.fromisoformat("2026-10-31T07:16:00+09:00")
WRAP = (
    "에너지 기업은 예상치를 웃도는 실적을 발표했고 해당 업종 주가는 상승했다.",
    "국제유가는 공급 차질로 상승했고 금값은 하락했다.",
    "아마존과 인텔의 실적과 향후 전망이 시장 기대치에 미치지 못하며 기술주가 약세를 보였다.",
    "대형 기술기업의 AI 인프라 투자에 대한 수익성 우려가 커지며 반도체주 투자심리가 위축됐다.",
)


def page(paragraphs=WRAP, *, modified="2026-10-31T06:40:00+09:00"):
    meta = {"@type": "NewsArticle", "headline": TITLE,
            "datePublished": "2026-10-31T06:32:00+09:00", "dateModified": modified}
    return ('<meta charset="utf-8"><script type="application/ld+json">' + json.dumps(meta)
            + '</script><aside>AI 실적 호조가 나타났다는 과거 자료</aside>'
            + '<div class="story-news article">'
            + ''.join('<p>' + escape(p) + '</p>' for p in paragraphs) + '</div>').encode()


def row(parsed):
    return dict(title=TITLE, link=URL, market="US", publisher="연합뉴스",
                session_date="2026-10-30", published_at="2026-10-31T06:32:00+09:00",
                news_bucket="session_news", is_close_wrap=True, **parsed)


def test_wrap_prioritizes_supported_miss_and_ai_concern_over_oil_and_unrelated_beat():
    parsed = articles.parse_article(page(), URL, TITLE)
    assert parsed["body_status"] == "verified"
    facts = parsed["body_facts"]
    assert [f["topic"] for f in facts] == ["earnings", "ai_credit", "oil_rising"]
    assert facts[0]["polarity"] == "negative"
    assert "실적·전망 부진" in facts[0]["summary"]
    assert "아마존과 인텔" in facts[0]["evidence"]
    assert "AI 인프라 투자" in facts[1]["evidence"]
    assert all(set(("topic", "summary", "implication", "check", "evidence")) <= set(f) for f in facts)
    assert all(len(f["evidence"]) <= 141 for f in facts)
    assert "paragraphs" not in parsed and "articleBody" not in parsed
    sentence = articles.body_context_sentence(parsed)
    assert "실적·전망 부진" in sentence and "AI 투자" in sentence and "유가 상승" in sentence
    assert "호실적" not in sentence and "자금조달" not in sentence


@pytest.mark.parametrize("paragraph", [
    "기업이 예상치를 웃도는 실적을 발표했다는 설명은 사실이 아니었다.",
    "일부 기업의 실적 호조는 없었다는 평가가 증시 마감 뒤 나왔다.",
    "기업 실적이 시장 기대치를 하회하지 않았다는 분석이 공개됐다.",
    "기업의 실적 부진이 예상된다는 전망만 있으며 아직 발표되지 않았다.",
    "기업 실적이 시장 기대치에 미치지 못할 수 있다는 우려가 나왔다.",
    '전문가는 "지난 분기 예상치를 웃도는 실적이 증시를 지지했다"고 회고했다.',
    '전문가는 "과거 AI 설비투자 확대가 호재였다"고 당시 상황을 설명했다.',
    "AI 설비투자 확대 계획은 없었다는 사실을 기업이 확인했다.",
    "AI 인프라 투자 우려는 없었다는 평가가 컨퍼런스에서 제시됐다.",
    "AI 인프라 투자 부담은 완화됐다는 평가가 시장에서 나왔다.",
    "Companies did not report strong earnings in the current quarter.",
    "Corporate earnings did not miss estimates in the latest release.",
    'An analyst recalled "last year strong earnings supported stocks".',
])
def test_negated_forecast_or_historical_claims_do_not_become_current_facts(paragraph):
    assert articles._body_facts([paragraph]) == []


@pytest.mark.parametrize("paragraph,topic", [
    ("아마존과 인텔의 실적과 향후 전망이 기대치에 미치지 못하며 기술주가 하락했다.", "earnings"),
    ("기업의 실적 부진이 확인되면서 관련 업종 주가가 일제히 약세로 마감했다.", "earnings"),
    ("Corporate earnings missed estimates and technology shares declined.", "earnings"),
    ("대형 기업들의 AI 인프라 투자에 대한 우려가 다시 커지며 기술주가 약세를 보였다.", "ai_credit"),
    ("AI 인프라 투자가 실질적인 수익과 생산성 개선으로 이어질지 회의론이 확산했다.", "ai_credit"),
    ("코어위브의 차입 우려가 커지면서 관련 기업의 투자심리도 약해졌다.", "ai_credit"),
])
def test_adverse_context_requires_a_local_supported_predicate(paragraph, topic):
    facts = articles._body_facts([paragraph])
    assert [f["topic"] for f in facts] == [topic]
    if topic == "earnings":
        assert facts[0]["polarity"] == "negative"


def test_headline_and_unrelated_sentences_cannot_supply_missing_body_cause():
    paragraphs = ["아마존과 인텔은 실적 발표를 준비하며 다음 분기 투자 계획을 설명했다.",
                  "AI 인프라 투자는 계속됐다. 다른 업종에서는 수익성 우려가 커졌다."]
    parsed = articles.parse_article(page(paragraphs), URL, TITLE)
    assert parsed["body_status"] == "no_supported_context"
    assert parsed["body_facts"] == [] and articles.body_context_sentence(parsed) == ""


def test_ai_capex_with_explicit_burden_is_not_an_optimistic_demand_fact():
    facts = articles._body_facts(["AI 설비투자 확대에 따른 투자 부담과 수익성 우려가 커지며 반도체주가 약세를 보였다."])
    assert [f["topic"] for f in facts] == ["ai_credit"]


def test_ai_concern_in_following_clause_does_not_turn_reported_miss_into_forecast():
    facts = articles._body_facts(["기업 실적이 시장 기대치를 하회하면서 AI 투자 우려가 다시 확산됐다."])
    assert [f["topic"] for f in facts] == ["earnings", "ai_credit"]
    assert facts[0]["polarity"] == "negative"


def test_current_positive_claims_survive_negation_in_a_different_sentence():
    facts = articles._body_facts(["일부 기업은 예상치를 웃도는 실적을 발표했다. 다른 기업의 호조는 없었다.",
                                  "AI 관련 기업의 호실적과 설비투자 확대 발표가 투자심리를 지지했다."])
    assert [f["topic"] for f in facts] == ["ai_investment", "earnings"]
    assert "기업 호실적" in articles.body_context_sentence({"body_status": "verified", "body_facts": facts})


def test_adverse_facts_remain_inside_four_fact_limit_with_other_supported_topics():
    facts = articles._body_facts([
        "미국과 이란의 중재 협상이 진전될 가능성이 보도됐다.",
        "한국 수출이 역대 최대를 기록해 기업 매출 기대가 높아졌다.",
        "외국인은 유가증권시장에서 현물을 순매수해 수급을 지지했다.",
        *WRAP,
    ])
    assert len(facts) == 4
    assert [f["topic"] for f in facts[:2]] == ["earnings", "ai_credit"]


def test_common_summary_and_brief_receive_adverse_context_without_decision_mutation():
    item = row(articles.parse_article(page(), URL, TITLE))
    context = {"sessions": {"KR": "2026-10-30", "US": "2026-10-30"},
               "prices": {"^IXIC": {"date": "2026-10-30", "return": -.021}}}
    held = [{"티커": "SOXL", "보유량": 1, "게이트상태": "방어우선"}]
    original = deepcopy((context, item, held))
    summary = market_summary(context, [item], [], market_session_states(NOW, context["sessions"]), NOW)
    assert "실적·전망 부진" in summary["headline"] and "AI 투자" in summary["headline"]
    assert "호실적" not in summary["headline"]
    brief = "\n".join(news_brief_lines(context, [item], held, NOW))
    assert "실적·전망 부진" in brief and "AI 투자" in brief and "SOXL" in brief
    assert "사실(본문)" in brief and "해석(추정)" in brief and "다음 확인" in brief
    assert (context, item, held) == original


def test_revision_after_report_still_cannot_backfill_the_earlier_report(monkeypatch):
    parsed = articles.parse_article(page(modified="2026-10-31T09:15:00+09:00"), URL, TITLE)
    monkeypatch.setattr(articles, "_article", lambda url, title: parsed)
    item = row({})
    articles.enrich_article_context({"session_news": [item]}, NOW)
    assert item["body_status"] == "article_version_after_report"
    assert articles.verified_body_facts(item) == []
