"""Synthetic collection-to-headline regressions; no publisher text or requests."""

from copy import deepcopy
from datetime import datetime
from html import escape
import json

import pytest

from stock_lab_core import article_context as articles
from stock_lab_core.report_editorial import editorial_lines
from stock_lab_core.report_market_summary import market_summary
from stock_lab_core.report_session import market_session_states


NOW = datetime.fromisoformat("2026-11-13T09:33:00+09:00")
PUBLISHED = "2026-11-13T07:00:00+09:00"
URL = "https://www.yna.co.kr/view/SYNTHETIC_MARKET_EVENTS"


def article(paragraphs, title="뉴욕증시, 경영진 교체와 유가 상승 속 하락 마감"):
    meta = dict(**{"@type": "NewsArticle"}, headline=title,
                datePublished=PUBLISHED, dateModified=PUBLISHED)
    data = ('<meta charset="utf-8"><script type="application/ld+json">'
            + json.dumps(meta) + '</script><div class="story-news article">'
            + ''.join('<p>' + escape(p) + '</p>' for p in paragraphs) + '</div>').encode()
    return dict(title=title, link=URL, publisher="연합뉴스", market="US",
                session_date="2026-11-12", news_bucket="session_news", is_close_wrap=True,
                published_at=PUBLISHED, **articles.parse_article(data, URL, title))


def context():
    return {"sessions": {"US": "2026-11-12", "KR": "2026-11-12"},
            "prices": {"^IXIC": {"date": "2026-11-12", "return": -.004},
                       "^GSPC": {"date": "2026-11-12", "return": -.003}}}


@pytest.mark.parametrize("sentence", [
    "미국은 이란과 협상이 더는 필요 없다고 밝혔다.",
    "미국과 이란의 협상이 결렬됐다는 소식이 전해졌다.",
    "미국과 이란의 협상 결렬 보도는 사실이 아니라고 당국이 밝혔다.",
    "미국과 이란의 협상이 재개될 수 있다는 관측이 나왔다.",
    "미국과 이란은 협상을 재개하기로 합의했다고 밝혔다.",
])
def test_diplomacy_preserves_negation_and_qualification_without_optimism(sentence):
    row = article([sentence])
    rendered = articles.body_context_sentence(row)
    assert sentence in rendered
    assert "중재 기대" not in rendered and "위험 프리미엄이 낮아질" not in str(row)


@pytest.mark.parametrize("company", ["가온테크", "다온바이오", "NVIDIA"])
def test_generic_leadership_event_survives_oil_and_first_four_fact_limit(company):
    event = f"{company} CEO가 경영 업무에서 즉시 사임했다고 회사가 발표했다."
    row = article([
        "국제유가는 공급 불안에 상승하며 투자자들의 관심을 모았다.",
        "한국 수출은 역대 최대를 기록하며 실적 기대를 높였다.",
        "외국인은 유가증권시장 현물을 순매수하며 매수세를 이어갔다.",
        "기관은 주식시장에서 순매수 규모를 확대했다고 집계됐다.", event,
    ])
    ctx = context()
    original = deepcopy((row, ctx))
    states = market_session_states(NOW, ctx["sessions"])
    summary = market_summary(ctx, [row], [], states, NOW)
    assert event in summary["headline"]
    assert summary["headline"].index(event) < summary["headline"].index("유가 상승")
    assert URL in summary["headline"]
    rendered = "\n".join(editorial_lines(ctx, summary, [], states, NOW))
    table = rendered.split("**근거에서 계좌까지**")[1]
    assert event in table and "유가 상승" in table
    assert "해석(추정)" in table
    assert (row, ctx) == original


def test_issuer_specific_title_does_not_discard_leadership():
    sentence = "NVIDIA CEO가 경영 업무에서 즉시 사임했다고 회사가 발표했다."
    row = article([sentence], title="NVIDIA CEO 사임 발표")
    assert sentence in articles.body_context_sentence(row)


@pytest.mark.parametrize("sentence", [
    "가온테크 CEO는 사임하지 않았다고 회사가 발표했다.",
    "가온테크 CEO가 사임할 가능성이 있다는 관측이 나왔다.",
    "가온테크 CEO가 사임했다는 보도는 사실이 아니라고 밝혔다.",
    "지난해 가온테크 CEO가 사임한 사건을 다시 설명했다.",
    "가온테크 CEO의 사임을 요구하는 주주들의 목소리가 커졌다.",
    "가온테크 CEO 교체가 필요하다는 분석이 시장에서 나왔다.",
    "Example Corp CEO will resign next month, the company announced.",
    "Investors called for Example Corp CEO resignation at the meeting.",
])
def test_denied_historical_or_conditional_leadership_not_confirmed(sentence):
    assert not any(f["topic"] == "leadership" for f in article([sentence])["body_facts"])


def test_long_diplomatic_quote_is_not_truncated_before_its_denial():
    sentence = "미국과 이란의 협상이 재개된다는 " + "시장 내 여러 관측과 설명 " * 15 + "보도는 사실이 아니라고 밝혔다."
    assert not any(f["topic"] == "mediation" for f in article([sentence])["body_facts"])


@pytest.mark.parametrize("changes", [
    {"session_date": "2026-11-11"}, {"market": "KR"},
    {"body_status": "fetch_unavailable"}, {"news_bucket": "next_session_news"},
])
def test_event_cannot_cross_market_session_or_verification_guard(changes):
    event = "가온테크 CEO가 경영 업무에서 즉시 사임했다고 회사가 발표했다."
    row = article([event])
    row.update(changes)
    ctx = context()
    result = market_summary(ctx, [row], [], market_session_states(NOW, ctx["sessions"]), NOW)
    assert event not in result["headline"]


def test_same_session_separate_event_article_is_not_hidden_by_generic_wrap():
    wrap = article(["국제유가는 공급 불안에 상승하며 투자자들의 관심을 모았다."])
    event = "가온테크 CEO가 경영 업무에서 즉시 사임했다고 회사가 발표했다."
    row = article([event], title="가온테크 CEO 사임 발표")
    row.update(link=URL + "_EVENT", is_close_wrap=False)
    ctx = context()
    summary = market_summary(ctx, [wrap, row], [], market_session_states(NOW, ctx["sessions"]), NOW)
    assert event in summary["headline"] and "유가 상승" in summary["headline"]
    assert row["link"] in summary["headline"] and wrap["link"] in summary["headline"]


def test_headline_only_never_promoted_to_body_event():
    row = article(["회사는 일반적인 영업 상황을 설명하고 향후 회의를 안내했다."], title="가온테크 CEO 사임")
    assert "사임" not in articles.body_context_sentence(row)


def test_named_issuer_in_market_wrap_keeps_explicit_oil_not_generic_optimism():
    event = "NVIDIA CEO가 경영 업무에서 즉시 사임했다고 회사가 발표했다."
    row = article([event, "국제유가는 공급 불안에 상승하며 투자자들의 관심을 모았다."],
                  title="NVIDIA CEO 사임과 유가 상승 속 뉴욕증시 하락")
    out = articles.body_context_sentence(row)
    assert event in out and "유가 상승" in out
    assert "기업 호실적" not in out


def test_collection_to_top_report_keeps_events_and_inputs(monkeypatch):
    from stock_lab_core.report_evidence import report_sections
    from stock_lab_core.report_build import get_report_build_info

    event = "다온바이오 CEO가 경영 업무에서 즉시 사임했다고 회사가 발표했다."
    parsed = article([event, "미국은 이란과 협상이 더는 필요 없다고 밝혔다.",
                      "국제유가는 공급 불안에 상승하며 투자자들의 관심을 모았다."])
    row = {k: v for k, v in parsed.items() if not k.startswith("body_")}
    calls = []
    monkeypatch.setattr(articles, "_article", lambda *args: calls.append(args) or
                        {k: v for k, v in parsed.items() if k.startswith("body_")})
    result = articles.enrich_article_context({"session_news": [row]}, NOW)
    assert len(calls) == result["news_retrieval"]["article_body_verified"] == 1
    ctx = context()
    saved = deepcopy((ctx, row))
    lines, _ = report_sections(context=ctx, news=[row], flow_rows=[], event_rows=[], summary_rows=[], now=NOW)
    top = "\n".join(lines).split("## 핵심 해석")[1].split("\n## ")[0]
    assert event in top and "협상이 더는 필요 없다" in top and "유가 상승" in top
    assert "중재 기대" not in top
    assert "해석(추정)" in top and URL in top
    assert (ctx, row) == saved
    source = get_report_build_info()["sources"]["stock_lab_core.article_market_events"]
    assert source["sha256"] == source["disk_sha256"]
