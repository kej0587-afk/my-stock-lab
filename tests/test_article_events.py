"""Synthetic evidence regressions; no copied publisher article or network."""

from copy import deepcopy
from datetime import datetime
from html import escape
import json

import pytest

from stock_lab_core import article_context as articles
from stock_lab_core import article_events as events


URL = "https://www.yna.co.kr/view/SYNTHETIC_EVENTS"
NOW = datetime.fromisoformat("2026-11-04T10:00:00+09:00")
STAMP = "2026-11-03T15:00:00+09:00"


def page(paragraphs, title="Market strategy", modified=STAMP):
    meta = {"@type": "NewsArticle", "headline": title,
            "datePublished": STAMP, "dateModified": modified}
    return ('<meta charset="utf-8"><script type="application/ld+json">' + json.dumps(meta)
            + '</script><div class="story-news article">'
            + ''.join('<p>' + escape(p) + '</p>' for p in paragraphs) + '</div>').encode()


@pytest.mark.parametrize("sentence,tag,tickers", [
    ("Amazon earnings missed estimates by 12 percent in the latest release.", "earnings_shock", ["AMZN"]),
    ("아마존과 인텔의 실적이 시장 기대치를 하회했다.", "earnings_shock", ["AMZN", "INTC"]),
    ("NVIDIA export controls were tightened in the latest announcement.", "regulation", ["NVDA"]),
    ("The Fed policy rates were cut by 25 basis points at the meeting.", "rates", []),
    ("코어위브의 차입 부담이 증가했다는 회사 발표가 공개됐다.", "credit", ["CRWV"]),
    ("Tariffs were imposed on imported components during the session.", "geopolitics", []),
    ("SOXL recorded net inflows of 15 million dollars during the session.", "flows", ["SOXL"]),
])
def test_explicit_event_tags_and_local_company_or_etf_subject(sentence, tag, tickers):
    facts = articles._body_facts([sentence])
    found = [e for f in facts for e in f.get("events", []) if e["event_tag"] == tag]
    assert found
    assert [s["ticker"] for s in found[0]["subjects"]] == tickers
    assert found[0]["basis"] == "body"
    assert found[0]["evidence"] == sentence
    if tickers == ["SOXL"]:
        assert found[0]["subjects"][0]["kind"] == "ETF"
    assert any(f.get("concrete_summary") == sentence for f in facts)


@pytest.mark.parametrize("paragraph", [
    "Amazon held a conference. Corporate earnings missed estimates by 12 percent.",
    "Amazon discussed its outlook; competitors' earnings missed estimates.",
    'Amazon analysts said "corporate earnings missed estimates" in their note.',
    "A partner of Amazon reported earnings missed estimates this quarter.",
])
def test_subject_cannot_be_donated_by_an_unrelated_sentence_or_attribution(paragraph):
    found = [e for f in articles._body_facts([paragraph]) for e in f.get("events", [])]
    assert found
    assert all(not e["subjects"] for e in found)


@pytest.mark.parametrize("sentence", [
    'An analyst recalled "last year Amazon earnings missed estimates".',
    'The company said "Amazon earnings missed estimates" was not true.',
    "Amazon earnings missed estimates; that claim was not confirmed.",
    "Amazon earnings could miss estimates in the coming quarter.",
    "AI 투자 우려만 언급됐으며 구체적인 차입이나 신용 문제는 설명되지 않았다.",
])
def test_qualified_claims_do_not_get_current_event_metadata(sentence):
    assert events.event_metadata(sentence) == []


def test_quote_attribution_and_decimal_amount_are_not_removed():
    sentence = 'An analyst said "Amazon earnings missed estimates by 2.5 percent" in a note.'
    fact = articles._body_facts([sentence])[0]
    assert fact["concrete_summary"] == sentence
    assert fact["evidence"] == sentence
    assert len(fact["evidence"]) <= 141


def test_multisentence_quote_keeps_its_later_historical_qualification():
    paragraph = 'The analyst said "Amazon earnings missed estimates. That was last year."'
    assert list(events.body_sentences([paragraph])) == [paragraph]
    assert articles._body_facts([paragraph]) == []


def test_issuer_title_cannot_donate_subject_across_body_sentences():
    title = "Amazon earnings outlook"
    parsed = articles.parse_article(page([
        "Amazon held a conference. Corporate earnings missed estimates in the latest release."
    ], title), URL, title)
    assert parsed["body_status"] == "verified"
    assert all(not fact.get("subject_ticker") for fact in parsed["body_facts"])
    assert all(not event["subjects"] for fact in parsed["body_facts"] for event in fact.get("events", []))


def test_long_sentence_cannot_gain_specific_metadata_by_losing_a_trailing_denial():
    sentence = "Amazon earnings missed estimates " + "according to an unverified report " * 5 + "but this was not true."
    facts = articles._body_facts([sentence])
    assert all(not f.get("events") and not f.get("concrete_summary") for f in facts)


def test_generic_ai_concern_is_not_itself_a_credit_event():
    fact = articles._body_facts(["AI 인프라 투자 수익성 우려가 확산되며 기술주 투자심리가 약해졌다."])[0]
    assert fact["topic"] == "ai_credit"  # Legacy topic contract.
    assert fact["event_tags"] == []
    assert "수익성 우려" in fact["concrete_summary"]


def test_enrichment_is_idempotent_and_does_not_repeat_event_topics():
    paragraphs = ["NVIDIA export controls were tightened in the latest announcement.",
                  "Intel export controls were tightened in another announcement."]
    facts = events.enhance_facts([], paragraphs)
    original = deepcopy(facts)
    assert len(facts) == 1
    assert events.enhance_facts(facts, paragraphs) == facts == original


def test_headline_only_metadata_never_supplies_body_facts_or_subject():
    title = "Amazon earnings missed estimates"
    parsed = articles.parse_article(page(["The company held a conference on its general business operations."], title), URL, title)
    assert parsed["body_status"] == "no_supported_context"
    assert parsed["body_facts"] == []
    assert parsed["headline_events"][0]["basis"] == "headline"
    assert parsed["headline_events"][0]["subjects"][0]["ticker"] == "AMZN"


SCENARIOS = [
    '민주당이 상·하원 모두에서 다수당을 확보할 경우 "AI와 반도체 정책을 점검해야 한다"고 연구원은 말했다.',
    "양당이 상·하원을 나눠 갖는 '분점 의회'가 구성되면 정책 협의가 필요하다는 분석이다. 다음 문장은 방산과 금융 업종을 설명한다.",
    "공화당이 양원 다수당을 유지할 경우 의회 절차를 살펴야 한다는 의견이 나왔다.",
]


def test_three_explicit_conditions_keep_empty_sectors_and_exact_claims():
    parsed = articles.parse_article(page(SCENARIOS), URL, "Market strategy")
    assert parsed["body_status"] == "verified"
    assert parsed["body_facts"] == []
    scenarios = parsed["body_scenarios"]
    assert [s["condition"] for s in scenarios] == ["민주당 양원", "분점 의회", "공화당 양원"]
    assert [s["sectors"] for s in scenarios] == [["AI·반도체"], [], []]
    assert scenarios[0]["evidence"] == SCENARIOS[0]
    assert "방산" not in scenarios[1]["evidence"]
    assert all(set(s) == {"condition", "sectors", "evidence"} for s in scenarios)
    assert "공화당 상원" not in [s["condition"] for s in scenarios]


def test_senate_is_not_both_and_sectors_are_literal_mentions_only():
    sentence = "공화당이 상원 다수당을 확보할 경우 방산·헬스케어·금융의 입법 논의가 주목된다는 의견이다."
    assert events.body_scenarios([sentence]) == [dict(condition="공화당 상원",
        sectors=["방산", "헬스케어", "금융"], evidence=sentence)]


def test_scenarios_are_deduplicated_and_bounded_without_hardcoded_article_identity():
    extra = "공화당이 상원 다수당을 확보할 경우 금융 업종의 법안을 점검한다."
    assert len(events.body_scenarios([*SCENARIOS, SCENARIOS[0], extra])) == 3
    assert len(events.body_scenarios([SCENARIOS[0], SCENARIOS[0]])) == 1


@pytest.mark.parametrize("sentence", [
    "지난해 민주당이 양원 다수당을 확보할 경우 AI 규제가 달라질 것이라고 예측했다.",
    "민주당이 양원 다수당을 확보하지 못할 경우 AI 정책을 점검한다.",
    "민주당과 공화당이 선거 전략을 논의하며 방산과 금융 업종을 언급했다.",
])
def test_historical_negated_or_missing_condition_is_not_recast(sentence):
    assert not events.body_scenarios([sentence])


def test_scenario_headline_and_page_aside_cannot_become_body_scenarios():
    title = SCENARIOS[0]
    data = page(["회사는 투자자 간담회에서 일반적인 사업 운영 상황을 설명했다."], title)
    data += ('<aside>' + escape(SCENARIOS[1]) + '</aside>').encode()
    parsed = articles.parse_article(data, URL, title)
    assert parsed["body_status"] == "no_supported_context"
    assert parsed["body_scenarios"] == []


@pytest.mark.parametrize("modified,published,status", [
    ("2026-11-04T11:00:00+09:00", STAMP, "article_version_after_report"),
    (STAMP, "2026-11-02T15:00:00+09:00", "article_timestamp_mismatch"),
])
def test_scenario_only_bodies_obey_date_guard_and_clear_stale_metadata(monkeypatch, modified, published, status):
    evidence = articles.parse_article(page(SCENARIOS, modified=modified), URL, "Market strategy")
    original = deepcopy(evidence)
    item = dict(title="Market strategy", link=URL, market="US", published_at=published,
                body_facts=[{"stale": True}], body_scenarios=[{"stale": True}])
    monkeypatch.setattr(articles, "_article", lambda *args: evidence)
    articles.enrich_article_context({"session_news": [item]}, NOW)
    assert item["body_status"] == status
    assert not item.get("body_scenarios") and not articles.verified_body_facts(item)
    assert evidence == original


def test_one_strategy_slot_keeps_market_wrap_material_diversity_and_allowlist(monkeypatch):
    titles = ["WallSt strategy: election scenarios", "Wall Street strategist outlook", "월가 선거 시나리오",
              "코스피 상승 마감", "뉴욕증시 하락 마감", "조선주 수주 소식에 상승"]
    rows = [dict(title=t, link=URL + str(i), market="US" if i < 3 or i == 4 else "KR",
                 published_at=STAMP) for i, t in enumerate(titles)]
    rows.insert(0, dict(title="Election scenarios", link="https://unapproved.invalid/news", market="GLOBAL"))
    rows.append(dict(rows[1]))  # Same URL cannot consume another slot.
    calls = []
    monkeypatch.setattr(articles, "_article", lambda url, title: calls.append(title) or {"body_status": "fetch_unavailable"})
    result = {"session_news": rows}
    articles.enrich_article_context(result, NOW)
    assert len(calls) == articles.MAX_ARTICLES == 4
    assert sum(events.is_strategy_article(title) for title in calls) == 1
    assert titles[3] in calls and titles[4] in calls
    assert "Election scenarios" not in calls
    assert result["news_retrieval"]["article_body_attempted"] == 4


def test_headline_events_survive_body_failure_without_verified_promotion(monkeypatch):
    item = dict(title="Amazon earnings did not miss estimates", link=URL, market="US", published_at=STAMP)
    monkeypatch.setattr(articles, "_article", lambda *args: {"body_status": "restricted_article"})
    articles.enrich_article_context({"session_news": [item]}, NOW)
    event = item["headline_events"][0]
    assert event["basis"] == "headline" and event["claim_context"] == ["negated"]
    assert not articles.verified_body_facts(item)


def test_verified_getter_and_report_brief_use_concrete_claim_without_mutating_row():
    from stock_lab_core.report_brief import news_brief_lines
    sentence = "코어위브의 차입 부담이 증가했다는 회사 발표가 공개됐다."
    parsed = articles.parse_article(page([sentence]), URL, "Market strategy")
    item = dict(title="AI debt concerns", link=URL, market="US", session_date="2026-11-03",
                published_at=STAMP, news_bucket="session_news", **parsed)
    original = deepcopy(item)
    facts = articles.verified_body_facts(item)
    assert facts[0]["summary"] == "본문 보도: " + sentence
    assert facts[0] is not item["body_facts"][0]
    context = {"sessions": {"KR": "2026-11-03", "US": "2026-11-03"}}
    brief = "\n".join(news_brief_lines(context, [item], [], NOW))
    assert sentence in brief
    assert "AI 투자 부담·성과에 대한 우려가 보도됐습니다" not in brief
    assert item == original


@pytest.mark.parametrize("condition,expected", [
    ("If Democrats control both chambers, AI policy deserves scrutiny.", "민주당 양원"),
    ("If Republicans retain the Senate, banking policy deserves scrutiny.", "공화당 상원"),
    ("민주당 양원 장악 시 금융 정책을 살펴야 한다는 분석이다.", "민주당 양원"),
])
def test_condition_word_order_and_short_forms(condition, expected):
    assert events.body_scenarios([condition])[0]["condition"] == expected


def test_article_cache_retains_original_body_timestamps_and_new_schema(monkeypatch):
    calls = []
    def read(url):
        calls.append(url)
        return page(SCENARIOS), url
    monkeypatch.setattr(articles, "_public_bytes", read)
    articles._article.clear()
    try:
        first = articles._article(URL, "Market strategy")
        second = articles._article(URL, "Market strategy")
        assert calls == [URL]
        assert first == second
        assert first["body_published_at"] == first["body_modified_at"] == STAMP
        assert first["body_scenarios"] == events.body_scenarios(SCENARIOS)
    finally:
        articles._article.clear()
