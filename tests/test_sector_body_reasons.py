"""Offline body-to-sector attribution, independent of price/scoring inputs."""

from copy import deepcopy
from datetime import datetime
from html import escape
import json

import pytest
import requests

from stock_lab_core.article_context import parse_article
from stock_lab_core.report_analysis import sector_body_reasons, sector_evidence
from stock_lab_core.report_coverage import sector_coverage_lines


NOW = datetime.fromisoformat("2026-11-15T18:00:00+09:00")
DAY = "2026-11-13"
STAMP = "2026-11-14T07:00:00+09:00"
AI = "AI 인프라 확충 부담으로 관련 서버 업종에 대한 경계가 이어졌다고 전했다."
RATES = "미국 국채 금리는 상승하며 기업 자금조달 비용에 대한 관심을 높였다."


@pytest.fixture(autouse=True)
def no_http(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("sector reasons must reuse collected evidence without HTTP")
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


def sector(ticker="SOXX", daily=-.04):
    return dict(Ticker=ticker, 섹터={"SOXX": "반도체", "IGV": "소프트웨어", "CIBR": "사이버보안"}.get(ticker, ticker),
                기준일=DAY, 수치종류="확정 종가", **{"1일수익률": daily})


def context(*rows):
    return dict(sessions={"US": DAY}, sector_rows=list(rows or [sector()]),
                prices={"^GSPC": dict(date=DAY, **{"return": -.01})})


def article(sentences, *, title="뉴욕증시, NVIDIA 약세와 국채금리 상승에 혼조 마감", key="wrap", published=STAMP):
    url = "https://www.yna.co.kr/view/SYNTHETIC_SECTOR_" + key
    meta = {"@type": "NewsArticle", "headline": title,
            "datePublished": published, "dateModified": published}
    page = ('<meta charset="utf-8"><script type="application/ld+json">' + json.dumps(meta)
            + '</script><div class="story-news article">'
            + ''.join('<p>' + escape(s) + '</p>' for s in sentences) + '</div>').encode()
    return dict(title=title, link=url, publisher="연합뉴스", market="US", session_date=DAY,
                news_bucket="session_news", published_at=published, is_close_wrap="마감" in title,
                **parse_article(page, url, title))


def test_body_channels_reach_semiconductor_and_software_without_explaining_excess():
    ctx = context(sector(), sector("IGV", -.008))
    item = article([AI, RATES])
    before = deepcopy((ctx, item))
    baseline = '\n'.join(sector_coverage_lines(ctx, [], "US", NOW))
    rendered = '\n'.join(sector_coverage_lines(ctx, [item], "US", NOW))
    for ticker in ("SOXX", "IGV"):
        line = next(line for line in rendered.splitlines() if f"({ticker})" in line)
        old = next(line for line in baseline.splitlines() if f"({ticker})" in line)
        assert line.split(" | ")[:3] == old.split(" | ")[:3]
        assert AI in line and RATES in line and item["link"] in line
        assert "동일 시장 공통 배경" in line and "초과수익의 직접 근거 아님" in line
        assert "해석(추정)" in line and "다음 확인" in line and "현금흐름" in line
        assert "제목 기준 보도" not in line and "마감 보도" in line
    soxx = next(line for line in rendered.splitlines() if "(SOXX)" in line)
    assert "-3.00%p 초과 움직임의 개별 원인 미확인" in soxx
    assert (ctx, item) == before


@pytest.mark.parametrize("ticker,sentence", [
    ("SOXX", "반도체 기업의 실적이 시장 기대치를 하회했다."),
    ("IGV", "소프트웨어 기업의 실적이 시장 기대치를 하회했다."),
])
def test_sector_specific_evidence_requires_the_body_not_headline(ticker, sentence):
    item = article([sentence])
    reasons = sector_body_reasons(sector(ticker), [item], context(), NOW)
    assert reasons and all(r["scope"] == "sector_report" for r in reasons)
    result = sector_evidence(sector(ticker), {}, [], observations=context()["prices"], body_reasons=reasons)
    assert sentence in result["reading"] and "초과수익 인과 기여 미확정" in result["reading"]
    unrelated = article(["리더십 공백과 규제 불확실성에 대한 우려가 커졌다."])
    assert sector_body_reasons(sector(ticker), [unrelated], context(), NOW) == []


def test_ai_concern_does_not_become_an_unrelated_sector_or_cybersecurity_fact():
    item = article([AI])
    for ticker in ("XLE", "XLV", "CIBR"):
        assert sector_body_reasons(sector(ticker), [item], context(), NOW) == []
    software = article(["소프트웨어 기업의 실적이 시장 기대치를 하회했다."])
    assert sector_body_reasons(sector(), [software], context(), NOW) == []


@pytest.mark.parametrize("change", [
    {"body_status": "fetch_unavailable"},
    {"body_status": "no_supported_context"},
    {"session_date": "2026-11-12"},
    {"market": "KR"},
    {"market": "GLOBAL"},
    {"news_bucket": "next_session_news"},
    {"news_bucket": "other_market_news"},
    {"body_source_url": "https://unapproved.invalid/article"},
    {"body_source_url": "javascript:alert(1)"},
    {"body_source_url": ""},
    {"body_published_at": None},
    {"body_modified_at": "invalid"},
    {"body_modified_at": "2026-11-16T00:00:00+09:00"},
    {"body_modified_at": "2026-11-15T12:00:00+09:00"},
    {"body_published_at": "2026-11-12T07:00:00+09:00", "body_modified_at": "2026-11-12T07:00:00+09:00"},
    {"published_at": "2026-11-15T18:01:00+09:00"},
    {"published_at": "2026-11-14T07:00:00"},
    {"publisher": "Unknown", "link": "https://unapproved.invalid/article"},
    {"title": "코스피, 반도체주 하락 마감"},
    {"title": "Wall Street futures rise on AI credit concerns"},
])
def test_source_session_and_body_version_guards(change):
    item = article([AI])
    item.update(change)
    assert sector_body_reasons(sector(), [item], context(), NOW) == []


def test_old_session_is_not_made_current_by_a_saved_verified_flag():
    assert sector_body_reasons(sector(), [article([AI])], context(),
                               datetime.fromisoformat("2026-12-01T12:00:00+09:00")) == []


def test_intraday_is_explicit_and_scheduled_early_close_is_not_news_window_end():
    item = article([AI], title="미국 AI 투자 부담 점검", published="2026-11-13T12:00:00-05:00")
    ctx = context()
    reasons = sector_body_reasons(sector(), [item], ctx, NOW)
    assert reasons and "장중 관측 · 종가와 구분" in reasons[0]["observation"]
    ctx["windows"] = [dict(market="US", date=DAY, scheduled_close="2026-11-13T11:00:00-05:00",
                           end="2026-11-14T20:00:00-05:00")]
    assert sector_body_reasons(sector(), [item], ctx, NOW) == []


def test_cross_market_body_does_not_borrow_the_us_headline_scope():
    item = article(["삼성전자 실적이 시장 기대치를 하회했다."])
    assert sector_body_reasons(sector(), [item], context(), NOW) == []


def test_incomplete_fact_cannot_borrow_a_headline_or_unverified_summary():
    item = article([AI])
    assert item["body_facts"]
    item["body_facts"][0].pop("concrete_summary", None)
    assert sector_body_reasons(sector(), [item], context(), NOW) == []


def test_distinct_body_events_and_sources_survive_title_deduplication():
    a = article([AI], key="one")
    b = article(["반도체 기업의 실적이 시장 기대치를 하회했다."], key="two")
    reasons = sector_body_reasons(sector(), [a, b, deepcopy(a)], context(), NOW)
    assert len(reasons) == 2
    assert {r["scope"] for r in reasons} == {"sector_report", "market_common_theme"}
    rendered = '\n'.join(sector_coverage_lines(context(), [a, b], "US", NOW))
    assert a["link"] in rendered and b["link"] in rendered


def test_shared_sentence_retains_each_relevant_interpretation_and_check():
    sentence = "은행권 신용 부담이 커졌고 국채 금리는 상승했다."
    item = article([sentence])
    reasons = sector_body_reasons(sector("XLF"), [item], context(), NOW)
    assert len(reasons) == 1
    assert len(reasons[0]["implications"]) == len(reasons[0]["checks"]) == 2
    assert reasons[0]["scope"] == "sector_report"


def test_legacy_no_body_contract_is_unchanged():
    args = sector(), {}, []
    assert sector_evidence(*args) == sector_evidence(*args, body_reasons=[])
