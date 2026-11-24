"""Complete coverage of collected evidence, not market-wide collection claims."""

from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_brief import brief_theme, build_news_brief
from tests.test_report_brief import article, CONTEXT, NOW


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests
    import urllib.request
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: pytest.fail("Unexpected HTTP"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("Unexpected HTTP"))


def corpus():
    titles = ["NVIDIA chip supply agreement announced", "NVIDIA chip export restrictions revised",
              "NVIDIA chip earnings guidance updated", "NVIDIA chip acquisition announced",
              "CoreWeave debt refinancing announced", "CoreWeave debt maturity extended",
              "Walmart earnings improve", "JPMorgan earnings improve", "Eli Lilly earnings improve",
              "Exxon Mobil earnings improve", "Applied Materials earnings improve",
              "Oracle cloud contract announced"]
    return [article(title, link=f"https://www.reuters.com/coverage-{i}") for i, title in enumerate(titles)]


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("mode", [{"comprehensive": True}, {"limit": None}])
def test_all_distinct_collected_events_survive_both_caps_and_legacy_topic_clusters(compact, mode):
    rows = corpus()
    before = deepcopy((CONTEXT, rows))
    result = build_news_brief(CONTEXT, rows, [], NOW, compact=compact, **mode)
    assert set(result["article_keys"]) == {row["link"] for row in rows}
    assert len(result["article_keys"]) == len(rows)
    assert (CONTEXT, rows) == before
    legacy = build_news_brief(CONTEXT, rows, [], NOW)
    assert len(legacy["article_keys"]) <= 6
    assert sum(line.startswith("반도체·AI |") for line in legacy["lines"]) <= 2


def test_exact_article_dedup_does_not_collapse_different_wraps_or_same_issuer_events():
    a, b = corpus()[:2]
    wrap1 = article("U.S. stocks close higher as bank shares gain", link="https://www.reuters.com/close-a", is_close_wrap=True)
    wrap2 = article("U.S. stocks close higher as healthcare shares recover", link="https://www.reuters.com/close-b", is_close_wrap=True)
    rows = [a, dict(a, link=a["link"] + "?utm_source=test"), dict(a, link="https://www.reuters.com/syndicated"), b, wrap1, wrap2]
    result = build_news_brief(CONTEXT, rows, [], NOW, comprehensive=True)
    assert set(result["article_keys"]) == {a["link"], b["link"], wrap1["link"], wrap2["link"]}
    assert len(result["article_keys"]) == 4


@pytest.mark.parametrize("body", [False, True])
def test_explicit_exclusion_is_final_even_for_urgent_or_body_verified_article(body):
    row = article("코스피·코스닥 5% 급락 마감", market="KR", session_date="2026-10-21",
                  published_at="2026-10-21T16:00:00+09:00", is_close_wrap=True)
    if body:
        row.update(body_status="verified", body_facts=[dict(topic="earnings", summary="Synthetic verified fact",
                   implication="Synthetic conditional reading", check="Synthetic source check")])
    result = build_news_brief(CONTEXT, [row], [], NOW, comprehensive=True, exclude_keys=[row["link"]])
    assert result["article_keys"] == []


@pytest.mark.parametrize("changes", [
    {"published_at": "2026-10-22T10:00:00-04:00"},
    {"published_at": "2026-10-19T15:00:00-04:00"},
    {"published_at": "2026-10-20"}, {"news_bucket": "next_session_news"},
    {"session_date": "2026-10-19"}, {"market": "JP"},
    {"publisher": "anonymous", "link": "https://spam.invalid/news"},
    {"link": "javascript:alert(1)"},
])
def test_comprehensive_does_not_relax_sources_dates_market_or_future_guards(changes):
    row = dict(corpus()[0], **changes)
    assert not build_news_brief(CONTEXT, [row], [], NOW, comprehensive=True)["article_keys"]


@pytest.mark.parametrize("title,theme", [
    ("Walmart AI investment announced", "소비·유통"),
    ("JPMorgan AI investment announced", "금융"),
    ("Eli Lilly earnings improve", "헬스케어·바이오"),
    ("Exxon Mobil earnings improve", "에너지·소재"),
    ("Constellation Energy earnings improve", "전력·산업재"),
    ("CoreWeave AI debt worries", "클라우드·소프트웨어"),
    ("Oracle earnings improve", "클라우드·소프트웨어"),
    ("Applied Materials earnings improve", "반도체"),
    ("AWS cloud demand grows", "클라우드·소프트웨어"),
    ("AWS Trainium chip supply grows", "반도체"),
])
def test_comprehensive_theme_uses_company_or_explicit_business_identity(title, theme):
    row = article(title)
    assert brief_theme(row, comprehensive=True) == theme
    if "CoreWeave" in title:
        assert brief_theme(row) == "반도체·AI"


def test_headline_claims_do_not_receive_invented_why_and_body_claims_keep_sources():
    row = corpus()[0]
    output = "\n".join(build_news_brief(CONTEXT, [row], [], NOW, comprehensive=True, compact=True)["lines"])
    assert "제목 확인·기사 주장" in output and "해석(추정)" not in output
    row.update(body_status="verified", body_facts=[dict(topic="earnings", summary="Synthetic collected body fact",
               implication="Synthetic collected conditional reading", check="Synthetic collected next check")])
    result = build_news_brief(CONTEXT, [row], [], NOW, comprehensive=True, compact=True)
    output = "\n".join(result["lines"])
    assert row["link"] in output and "Synthetic collected body fact" in output
    assert "Synthetic collected conditional reading" in output and "Synthetic collected next check" in output


def test_global_context_is_opt_in_dated_and_never_relabelled_as_us_session_cause():
    row = article("Bank of Japan rate decision announced", market="GLOBAL", session_date="",
                  news_bucket="other_market_news")
    assert not build_news_brief(CONTEXT, [row], [], NOW, comprehensive=True)["article_keys"]
    output = build_news_brief(CONTEXT, [row], [{"ticker": "SOXL", "qty": 1}], NOW,
                              comprehensive=True, include_other_markets=True, compact=True)
    rendered = "\n".join(output["lines"])
    assert output["article_keys"] == [row["link"]]
    assert "GLOBAL" in rendered and "타시장·공통 맥락" in rendered and "10/21 04:00 KST" in rendered
    assert "US 2026-10-20 종가 세션" not in rendered and "SOXL" not in rendered
    old = dict(row, published_at="2026-09-01T15:00:00-04:00")
    assert not build_news_brief(CONTEXT, [old], [], NOW, comprehensive=True, include_other_markets=True)["article_keys"]


def test_current_session_rows_and_previous_close_windows_use_existing_timestamp_partition():
    now = datetime.fromisoformat("2026-10-22T00:00:00+09:00")
    context = dict(CONTEXT, news_sessions={"US": {"date": "2026-10-20", "previous_date": "2026-10-19"}},
                   current_news_sessions={"US": {"date": "2026-10-21", "previous_date": "2026-10-20"}})
    current = dict(corpus()[0], published_at="2026-10-21T10:00:00-04:00", session_date="2026-10-21", news_bucket="current_session_news")
    result = build_news_brief(context, [current, corpus()[1]], [], now, comprehensive=True)
    assert result["article_keys"] == [current["link"]]
    wrong = dict(current, published_at="2026-10-19T15:00:00-04:00")
    assert not build_news_brief(context, [wrong], [], now, comprehensive=True)["article_keys"]


@pytest.mark.parametrize("compact", [False, True])
def test_all_collected_body_events_survive_comprehensive_rendering(compact):
    row = corpus()[0]
    row.update(body_status="verified", body_facts=[dict(topic="earnings", summary=f"Verified event {i}",
               implication=f"Collected reading {i}", check=f"Collected check {i}") for i in range(4)])
    result = build_news_brief(CONTEXT, [row], [], NOW, comprehensive=True, compact=compact)
    rendered = "\n".join(result["lines"])
    assert result["article_keys"] == [row["link"]]
    for i in range(4):
        assert f"Verified event {i}" in rendered
        assert f"Collected reading {i}" in rendered and f"Collected check {i}" in rendered


@pytest.mark.parametrize("compact", [False, True])
def test_comprehensive_wrap_keeps_distinct_facts_and_unique_readings_checks(compact):
    row = article("U.S. stocks close higher as bank shares gain", is_close_wrap=True)
    row.update(body_status="verified", body_facts=[
        dict(topic="earnings", summary="Collected demand fact", implication="Demand reading", check="Demand check"),
        dict(topic="earnings", summary="Collected demand fact", implication="Demand reading", check="Demand check"),
        dict(topic="ai_credit", summary="Collected credit fact", implication="Credit reading", check="Credit check"),
        dict(topic="earnings", summary="Collected margin fact", implication="Demand reading", check="Margin check"),
    ])
    rendered = "\n".join(build_news_brief(CONTEXT, [row], [], NOW, comprehensive=True, compact=compact)["lines"])
    for value in ("Collected demand fact", "Collected credit fact", "Collected margin fact",
                  "Demand reading", "Credit reading", "Demand check", "Credit check", "Margin check"):
        assert rendered.count(value) == 1


@pytest.mark.parametrize("mode", [{"comprehensive": True}, {"limit": None}])
def test_two_article_ids_with_the_same_verified_body_sentence_show_once(mode):
    fact = dict(topic="ai_credit", summary="AI 투자 관련 보도: AI 관련 기업들의 주가 거품 논란과 자금조달 부담이 여전하다.",
                implication="Synthetic conditional reading", check="Synthetic source check")
    first = article("NVIDIA chip supply agreement announced", link="https://www.reuters.com/same-1",
                    body_status="verified", body_facts=[fact])
    second = article("AI stocks swing as funding worries return", link="https://www.reuters.com/same-2",
                     body_status="verified", body_facts=[dict(fact)])
    other = article("CoreWeave debt refinancing announced", link="https://www.reuters.com/other",
                    body_status="verified", body_facts=[dict(fact, summary="본문 보도: 다른 사실.")])
    result = build_news_brief(CONTEXT, [first, second, other], [], NOW, **mode)
    assert len({first["link"], second["link"]} & set(result["article_keys"])) == 1
    assert other["link"] in result["article_keys"]
