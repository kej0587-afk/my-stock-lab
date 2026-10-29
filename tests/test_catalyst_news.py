from datetime import datetime, timedelta
from email.utils import format_datetime
from io import BytesIO
import json
from xml.sax.saxutils import escape

import pytest

from stock_lab_core import catalyst_news as cn, today_news, news, article_context
from stock_lab_core.report_evidence import news_article_key


NOW = datetime.fromisoformat("2026-10-29T10:32:00+09:00")
END = "2026-10-28T16:00:00-04:00"
SESSIONS = {"US": {"date": "2026-10-28", "previous_date": "2026-10-27"}}


def row(title="Alphabet misses earnings expectations, stock slides in extended trading", **kwargs):
    return dict(title=title, link="https://www.cnbc.com/test.html?utm_source=test", publisher="CNBC",
                market="US", published_at="2026-10-29T06:51:00+09:00", **kwargs)


def select(rows, **kwargs):
    return cn.after_close_catalysts(rows, closed_end=END, now=NOW, **kwargs)


def test_after_close_is_independent_of_bucket_and_regular_close():
    source = row(news_bucket="next_session_news")
    result = select([source], exposures=[{"Ticker": "GOOGL"}])[0]
    assert result["reaction"] == "reported_extended_decline"
    assert result["source_keys"] == [news_article_key(source)]
    assert result["direct_exposures"] == ["GOOGL"]
    assert result["topics"] == ["earnings"]
    assert result["evidence_level"] == "headline_only"
    assert not result["prior_close_cause"] and not result["price_contribution_verified"]
    assert "capex_cash_flow" not in result["topics"]
    assert source["news_bucket"] == "next_session_news"


@pytest.mark.parametrize("stamp", [END, "2026-10-29T11:00:00+09:00", "2026-10-29", "2026-10-29T07:00:00", "bad"])
def test_reject_boundary_future_and_imprecise_publication(stamp):
    source = row()
    source["published_at"] = stamp
    assert not select([source])


def test_publication_upper_bound_and_precision_timestamp():
    source = row()
    source.pop("published_at")
    source["_pub_dt"] = NOW
    source["published"] = "2026-10-29 10:32"
    assert select([source])


def test_preview_and_unverified_price_not_upcoming_fact():
    assert not select([row("Alphabet earnings preview ahead of earnings")])
    result = select([row("Alphabet revenue grows as capex and free cash flow draw scrutiny")])[0]
    assert result["reaction"] == "unconfirmed"
    assert "capex_cash_flow" in result["topics"]


def test_mixed_sessions_does_not_infer_single_price_direction():
    assert select([row("Alphabet shares rose before earnings but fell after hours")])[0]["reaction"] == "reported_mixed_sessions"


@pytest.mark.parametrize("title,expected", [
    ("Alphabet earnings released after hours; free cash flow falls", "unconfirmed"),
    ("Alphabet earnings rise after hours; free cash flow falls", "unconfirmed"),
    ("Alphabet stock flat after hours as free cash flow falls", "unconfirmed"),
    ("Alphabet earnings released after hours; stock falls during regular trading", "unconfirmed"),
    ("Alphabet earnings released after hours and stock falls during regular trading", "unconfirmed"),
    ("Alphabet earnings; Amazon stock falls after hours", "unconfirmed"),
    ("Alphabet stock rises after hours as free cash flow falls", "reported_extended_rise"),
    ("Alphabet shares fall after hours as revenue rises", "reported_extended_decline"),
    ("Alphabet earnings miss, stock continues to slide in extended trading", "reported_extended_decline"),
    ("알파벳 실적 발표; 시간외 현금흐름 하락", "unconfirmed"),
    ("알파벳 실적 발표; 주가 시간외 하락", "reported_extended_decline"),
])
def test_extended_direction_belongs_to_stock_not_financial_metric(title, expected):
    assert select([row(title)])[0]["reaction"] == expected


def recorded_catalyst_feed():
    # Recorded review headlines/timestamps; extra duplicates exercise both caps.
    entries = [
        ("Our next steps for Alphabet stock after earnings disappoint at nearly every turn", "CNBC", "2026-10-29T01:20:00+00:00"),
        ("What investors need to know about Alphabet's stock-busting earnings report", "CNBC", "2026-10-29T01:10:00+00:00"),
        ("Microsoft and Alphabet Just Reported Earnings, Putting the AI Boom to the Test", "Yahoo Finance", "2026-10-29T00:19:00+00:00"),
        ("Alphabet earnings preview: capex and free cash flow in focus", "CNBC", "2026-10-29T01:00:00+00:00"),
        ("Alphabet earnings report: what investors need to know", "CNBC", "2026-10-29T00:58:00+00:00"),
        ("Alphabet earnings report: another investor view", "CNBC", "2026-10-29T00:57:00+00:00"),
        ("F5 earnings outlook draws scrutiny", "Yahoo Finance", "2026-10-29T00:55:00+00:00"),
        ("Alphabet shares fall after revenue miss, cash burn worsens", "Reuters", "2026-10-28T21:47:55+00:00"),
        ("Fortinet (FTNT) Q3 Earnings and Revenues Top Estimates", "Yahoo Finance", "2026-10-28T20:20:02+00:00"),
    ]
    return [dict(title=title, publisher=publisher, published_at=stamp, market="US",
                 link=f"https://news.google.com/rss/articles/recorded-catalyst-{index}",
                 market_category="기업 촉매", source="Google News RSS", query_market="US",
                 query_kind="issuer_catalyst", query_issuers=cn.catalyst_entities(title))
            for index, (title, publisher, stamp) in enumerate(entries)]


@pytest.mark.parametrize("per_category", [3, 5])
def test_recorded_feed_preserves_cash_burn_and_fortinet_before_category_cap(monkeypatch, per_category):
    from stock_lab_core.report_catalysts import post_close_brief
    feed = recorded_catalyst_feed()
    exposures = [{"Ticker": "CIBR"}, {"Ticker": "379810.KS"}]
    calls = []
    def retrieve(specs, *, use_cache):
        calls.append(specs)
        return {"rows": feed, "failures": {}, "complete": True}
    monkeypatch.setattr(today_news, "_retrieve_session_rss", retrieve)
    sessions = dict(SESSIONS, KR={"date": "2026-10-28", "previous_date": "2026-10-27"})
    result = today_news.fetch_session_market_news(sessions, now=NOW, held_exposures=exposures,
                                                  per_category=per_category)
    retained = result["next_session_news"]
    assert len(retained) <= per_category
    assert all(source["title"] in {item["title"] for item in retained} for source in feed[-2:])
    assert len(calls) == 1 and len(calls[0]) <= 16
    assert result["news_retrieval"]["catalyst_query_count"] <= 4
    catalysts = select(retained, exposures=exposures)
    assert all(source["link"] in {key for item in catalysts for key in item["source_keys"]} for source in feed[-2:])
    post = post_close_brief(dict(result, sessions={"US": "2026-10-28", "KR": "2026-10-28"}), [], exposures, NOW)
    assert all(source["link"] in post["article_keys"] for source in feed[-2:])
    assert "설비투자·현금흐름" in post["overview"]
    assert any("Fortinet" in line for line in post["lines"])
    assert "Fortinet" in " / ".join(item["summary"] for item in catalysts)


def test_verified_body_requires_subject_and_time():
    source = row(body_status="verified", body_published_at="2026-10-29T06:51:00+09:00",
                 body_modified_at="2026-10-29T07:00:00+09:00",
                 body_facts=[{"topic": "capex_cash_flow", "subject_ticker": "GOOGL"},
                             {"topic": "guidance", "subject_ticker": "FTNT"}])
    result = select([source])[0]
    assert result["evidence_level"] == "verified_body" and "guidance" not in result["topics"]
    source["body_modified_at"] = "2026-10-29T11:00:00+09:00"
    assert select([source])[0]["evidence_level"] == "headline_only"


def test_source_dedup_and_issuer_diversity_before_second_alphabet():
    rows = [row()]
    for index, title in enumerate(["Alphabet earnings miss", "F5 earnings guidance", "Fortinet earnings guidance"]):
        source = row(title)
        source["link"] = f"https://www.cnbc.com/{index}"
        rows.append(source)
    rows.append(dict(rows[0], link="https://www.cnbc.com/test.html?utm_source=other"))
    result = select(rows, exposures=["CIBR", "GOOGL"], limit=3)
    assert {issuer for item in result for issuer in item["issuers"]} == {"GOOGL", "FFIV", "FTNT"}
    assert not select(rows, limit=0)
    assert len(select(rows, limit=100)) <= 4


def test_korean_verification_day_and_expiry():
    links = cn.constituent_links("F5 earnings outlook", "CIBR", now=NOW,
                                 published_at="2026-10-28T17:00:00-04:00")
    assert links[0]["weight_pct"] == 3.50
    assert links[0]["holdings_as_of"] == "2026-10-27"
    assert links[0]["validity_timezone"] == "Asia/Seoul"
    assert not links[0]["price_contribution_verified"]
    for instant in ["2026-10-28T23:59:59+09:00", "2026-11-03T00:00:00+09:00"]:
        assert not cn.constituent_links("F5 earnings", "CIBR", now=instant)
    assert not cn.constituent_links("F5 earnings", "CIBR", now=NOW, published_at="2026-10-26T17:00:00-04:00")
    assert not cn.constituent_links("F5 earnings", "CIBR", now=NOW, published_at="2026-10-29")


@pytest.mark.parametrize("title", ["Stocks climb on earnings", "OPTION earnings outlook", "F5 tornado options", "Alphabetical earnings lists"])
def test_entity_boundary_and_short_symbol(title):
    assert not cn.catalyst_entities(title)


def test_explicit_on_and_market_collision_scope():
    assert cn.catalyst_entities("Alphabet FCF concerns") == ["GOOGL"]
    assert cn.catalyst_entities("onsemi earnings revenue grows") == ["ON"]
    assert cn.catalyst_entities("NASDAQ:ON earnings revenue grows") == ["ON"]
    assert cn.us_symbol_collision("(CIBR) Stock Evaluation Report (CIBR:CA)", "CIBR")
    assert not cn.us_symbol_collision("CIBR:CA stock earnings", "CIBR.TO")
    assert not cn.us_symbol_collision("Canadian cyber stocks outlook", "CIBR")


def test_narrow_banking_promo():
    assert cn.is_consumer_banking_promo("(게시판) Sh수협은행, 해양특화 예·적금 우대금리 확대")
    for title in ["은행 실적 순이자이익 증가", "은행 예금 이탈에 특판 경쟁", "한국은행 기준금리 인하", "은행 예금금리 경쟁 심화"]:
        assert not cn.is_consumer_banking_promo(title)


def test_specs_budget_priority_and_identical_cache_keys():
    exposures = [{"Ticker": t} for t in ["QQQ", "CIBR", "MSFT", "GOOGL", "ON"]]
    specs = cn.exposure_catalyst_specs(exposures, now=NOW)
    assert len(specs) == 4
    assert [s["query_issuers"][0] for s in specs[:2]] == ["FFIV", "FTNT"]
    windows, _ = today_news._session_news_windows(SESSIONS, NOW)
    report_specs = today_news._session_query_specs(windows, (), NOW, held_exposures=exposures)
    assert len(report_specs) <= 16 and len({s["url"] for s in report_specs}) == len(report_specs)
    assert [s for s in report_specs if s.get("query_kind") == "issuer_catalyst"] == specs
    expired = cn.exposure_catalyst_specs(["CIBR"], now="2026-11-03T00:00:00+09:00")
    assert [spec["query_issuers"] for spec in expired] == [["FFIV"], ["FTNT"]]


def test_extended_trading_is_not_close_recap():
    source = row("Nasdaq: Alphabet earnings miss, shares fall in extended trading", source="Google News RSS",
                 query_market="US", query_kind="issuer_catalyst", query_issuers=["GOOGL"])
    source["published_at"] = "2026-10-28T16:15:00-04:00"
    payload = today_news.partition_session_market_news([source], SESSIONS, now=NOW)
    assert not payload["session_news"]
    assert len(payload["next_session_news"]) == 1
    assert not payload["next_session_news"][0]["retrospective_close_wrap"]


def test_issuer_body_is_subject_bound_not_generic_optimism():
    paragraphs = ["Alphabet earnings grew, while Alphabet capex increased and free cash flow fell.",
                  "Fortinet raised revenue guidance for the year.", "Amazon free cash flow turned negative."]
    facts = cn.catalyst_body_facts(paragraphs, "Alphabet earnings")
    assert not any(f["subject_ticker"] == "GOOGL" and f["topic"] == "guidance" for f in facts)
    assert len([f for f in facts if f["topic"] == "capex_cash_flow"]) == 1
    meta = {"@type": "NewsArticle", "headline": "Alphabet earnings", "datePublished": "2026-10-28T20:30:00Z",
            "articleBody": "\n".join(paragraphs)}
    parsed = article_context.parse_article(('<script type="application/ld+json">' + json.dumps(meta) + '</script>').encode(),
                                            "https://www.cnbc.com/earnings.html", "Alphabet earnings")
    assert parsed["body_status"] == "verified"
    assert "기업 호실적" not in article_context.body_context_sentence(parsed)


def assess(title, ticker="CIBR", category=news.NEWS_CATEGORY_SECTOR, names=()):
    return news.assess_news_item(title, "Reuters", ticker, names, ["cybersecurity"], category,
                                 now=NOW, published_at="2026-10-28T17:00:00-04:00")


def test_precision_components_are_indirect_not_direct_or_etf_price_claim():
    result = assess("Fortinet earnings guidance raised, stock falls")
    assert result["ok"] and result["relation"] == "편입기업 간접" and result["sentiment"] == "중립"
    assert result["constituent_links"][0]["constituent"] == "FTNT"
    assert not assess("Fortinet earnings guidance", category=news.NEWS_CATEGORY_DIRECT)["ok"]
    assert not assess("CIBR:CA stock earnings", category=news.NEWS_CATEGORY_DIRECT, names=["CIBR"])["ok"]
    assert not assess("Stocks rise on earnings", ticker="ON", names=["ON", "onsemi"], category=news.NEWS_CATEGORY_DIRECT)["ok"]


@pytest.mark.parametrize("instant", [NOW.isoformat(), "2026-11-03T00:00:00+09:00", "2026-12-03T10:32:00+09:00"])
def test_shared_component_cache_one_fetch_per_spec_and_metadata(monkeypatch, instant):
    now = datetime.fromisoformat(instant)
    expired = now.date().isoformat() >= cn.CIBR_MEMBERSHIP["expires_at"]
    today_news._cached_session_rss.clear()
    news.get_ticker_news.clear()
    original_now = cn._now
    monkeypatch.setattr(cn, "_now", lambda value: now if value is None else original_now(value))
    monkeypatch.setattr(news, "get_yfinance_company_names", lambda _: pytest.fail("unexpected Yahoo lookup"))
    monkeypatch.setattr(news, "is_news_within_days", lambda stamp, days: now - timedelta(days=days) <= stamp <= now)
    calls = []
    def fetch(req, timeout):
        calls.append((req.full_url, timeout))
        title = "F5 earnings guidance" if "FFIV" in req.full_url else "Fortinet earnings guidance" if "FTNT" in req.full_url else "CIBR:CA stock earnings"
        data = (f"<rss><channel><item><title>{escape(title)}</title><source>Reuters</source>"
                f"<link>https://www.reuters.com/{title.split()[0]}</link><pubDate>{format_datetime(now - timedelta(hours=2))}</pubDate></item>"
                "<item><title>Other Company earnings</title><link>https://www.reuters.com/unrelated</link></item></channel></rss>")
        return BytesIO(data.encode())
    monkeypatch.setattr(news.urllib.request, "urlopen", fetch)
    try:
        specs = cn.exposure_catalyst_specs(["CIBR"], now=now)
        assert len(specs) == 2
        today_news._retrieve_session_rss(specs, use_cache=False)
        items, _ = news.get_ticker_news("CIBR", "First Trust Nasdaq Cybersecurity ETF")
        components = [item for item in items if item.get("constituent_links") or item.get("industry_issuers")]
        assert len(components) == 2
        if expired:
            assert {issuer for item in components for issuer in item["industry_issuers"]} == {"FFIV", "FTNT"}
            assert all(not item["constituent_links"] and item["relation"] == "보안업종 간접"
                       and item["sentiment"] == "중립" and "미확인" in item["reason"] for item in components)
            assert all("weight_pct" not in item for item in components)
        else:
            assert all(item["constituent_links"] and not item["industry_issuers"] for item in components)
        assert all(item["category"] == news.NEWS_CATEGORY_SECTOR and item["published_at"] for item in components)
        assert not any("CIBR:CA" in item["title"] for item in items)
        assert all(sum(url == spec["url"] for url, _ in calls) == 1 for spec in specs)
        assert len(calls) <= 16 and all(timeout <= 5 for _, timeout in calls)
        assert not any("Other Company" in item["title"] for item in items)
    finally:
        news.get_ticker_news.clear()
        today_news._cached_session_rss.clear()


@pytest.mark.parametrize("title,query_issuers,category", [
    ("F5 earnings guidance", (), news.NEWS_CATEGORY_SECTOR),
    ("F5 earnings guidance", ("FTNT",), news.NEWS_CATEGORY_SECTOR),
    ("F5 earnings guidance", ("FFIV",), news.NEWS_CATEGORY_DIRECT),
    ("Other Company earnings guidance", ("FFIV",), news.NEWS_CATEGORY_SECTOR),
    ("F5 keyboard refresh", ("FFIV",), news.NEWS_CATEGORY_SECTOR),
    ("CIBR:CA F5 earnings", ("FFIV",), news.NEWS_CATEGORY_SECTOR),
])
def test_expired_industry_fallback_requires_scoped_financial_entity(title, query_issuers, category):
    result = news.assess_news_item(title, "Reuters", "CIBR", [], [], category,
                                  now="2026-11-03T10:32:00+09:00", query_issuers=query_issuers)
    assert not result["ok"]
    assert not result.get("constituent_links")
