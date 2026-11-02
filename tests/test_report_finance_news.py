"""Finance topic regressions; public RSS titles observed on 2026-11-02."""

from datetime import datetime
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape

import pytest

from stock_lab_core import today_news
from stock_lab_core.report_news_selection import matching_categories, selected_category_lines


NOW = datetime.fromisoformat("2026-11-02T23:00:00+09:00")
FINANCE = "금융·은행"
REGULATION = "금융지주 회장 연임 시 주총 의결요건 강화…3연임 땐 75% 찬성"


@pytest.mark.parametrize("title", [
    REGULATION,  # Yonhap RSS, Mon, 02 Nov 2026 12:21:47 GMT; old matcher returned [].
    "IBK기업은행, 한국금융지주 보유 지분 전량 매각",
    "기업銀, 한국금융지주 지분…20년 만에 전량 매각 완료",
    "KB금융, 3분기 순이익 증가·주주환원 확대",
    "신한지주, 분기 배당 확대", "신한금융, 자사주 소각",
    "하나금융지주, 자본비율 개선", "우리금융, 충당금 부담 확대",
    "BNK금융, 순익 증가", "JB금융, 배당 확대", "iM금융, CET1 개선",
    "카카오뱅크, 순이익 증가", "JPMorgan earnings beat estimates",
    "J.P. Morgan raises dividend", "Goldman Sachs reports higher profit",
    "Morgan Stanley earnings rise", "Wells Fargo provisions increase",
    "Citigroup raises dividend", "은행주 강세", "Bank stocks gain",
    "한국은행 금리 동결에도 KB금융 순이자마진 개선",
    "Bank of Japan raises rates; bank stocks gain",
    "은행 특판 경쟁에 순이자마진 악화", "은행 캐시백 과열 규제 강화",
])
def test_finance_matches_listed_issuers_sector_and_material_reporting(title):
    assert matching_categories(title, [FINANCE]) == [FINANCE]


@pytest.mark.parametrize("title", [
    "한국은행 기준금리 동결", "일본은행 금리 인상", "중국인민은행 유동성 공급",
    "유럽중앙은행 기준금리 인하", "Bank of Japan raises rates",
    "Bank of Korea holds rates", "European Central Bank policy update",
    "People's Bank of China adds liquidity", "Federal Reserve Bank of New York report",
    "World Bank cuts growth outlook", "Central bank financial stability report",
    "우리금융, 겨울철 취약계층 연탄 지원",
    "[게시판] 우리금융, 자립준비 청년에 금융특강",
    "IBK기업은행, 강원도와 관광·금융 상생협력 '맞손'",
    "강원 겨울관광 알리고 소비 늘리고…도·기업은행 맞손",
    "IBK기업은행, 강원특별자치도와 관광·금융 상생협력 협약",
    "KB금융, 지역아동 금융교육 실시", "기업은행 적금 특판 우대금리 이벤트",
    "카카오뱅크 계좌 개설 이벤트", "JPMorgan sign-up bonus offers cashback",
    "Local food bank opens", "Samsung chip earnings rise", "강변 은행나무 축제",
])
def test_finance_does_not_label_macro_promotions_or_unrelated_subjects(title):
    assert matching_categories(title, [FINANCE]) == []


def test_macro_exclusion_only_affects_finance_category():
    assert matching_categories("한국은행 금리 동결", [FINANCE, "외환/금리"]) == ["외환/금리"]


def test_expanded_query_keeps_all_topics_and_request_limit():
    sessions = {"KR": {"date": "2026-11-02", "previous_date": "2026-10-30"},
                "US": {"date": "2026-10-30", "previous_date": "2026-10-29"}}
    windows, _ = today_news._session_news_windows(sessions, NOW)
    categories = [plan["category"] for plan in today_news.TODAY_MARKET_STORY_RSS_PLAN]
    specs = today_news._session_query_specs(windows, categories, NOW,
        held_exposures=[{"Ticker": ticker} for ticker in ("SOXL", "RAM", "CIBR", "XLK", "XLE")])
    assert len(specs) <= 16
    assert today_news._SESSION_QUERY_LIMIT == 16
    assert {c for spec in specs for c in spec.get("selected_categories", [])} == set(categories)
    finance = next(spec for spec in specs if FINANCE in spec.get("selected_categories", []))
    query = parse_qs(urlsplit(finance["url"]).query)["q"][0]
    for term in ("금융지주", "KB금융", "신한지주", "기업은행", "bank stocks", "JPMorgan"):
        assert '"' + term + '"' in query


def test_rss_parser_accepts_real_regulation_title_but_not_publisher_or_marketing(monkeypatch):
    titles = [REGULATION, "IBK기업은행, 한국금융지주 보유 지분 전량 매각",
              "우리금융, 겨울철 취약계층 연탄 지원", "한국은행 금리 동결", "반도체 수출 증가"]
    items = []
    for index, title in enumerate(titles):
        # Finance words in a publisher name must not count as title evidence.
        publisher = "KB금융" if index == 4 else "연합뉴스"
        items.append(f"<item><title>{escape(title)} - {publisher}</title>"
                     f"<source>{publisher}</source><link>https://www.yna.co.kr/view/{index}</link>"
                     "<pubDate>Mon, 02 Nov 2026 12:21:47 GMT</pubDate></item>")
    payload = ("<rss><channel>" + "".join(items) + "</channel></rss>").encode()
    monkeypatch.setattr(today_news.urllib.request, "urlopen", lambda *a, **k: BytesIO(payload))
    rows, error = today_news._fetch_session_rss({"url": "https://news.google.com/rss/search?q=fixture",
        "market": "GLOBAL", "category": "선택 분야", "selected_categories": [FINANCE]})
    assert not error
    assert len(rows) == 2
    assert all(row["market_category"] == FINANCE for row in rows)
    assert rows[0]["title"].startswith(REGULATION)


def article(title="KB금융 실적 발표", **changes):
    row = dict(title=title, publisher="연합뉴스", link="https://www.yna.co.kr/view/finance",
               published_at="2026-11-02T21:21:47+09:00", market="GLOBAL", session_date="",
               news_bucket="other_market_news")
    row.update(changes)
    return row


def render(rows, per_category=1):
    return "\n".join(selected_category_lines({"news_retrieval": {
        "requested_categories": [FINANCE], "per_category": per_category}, "other_market_news": rows}, NOW))


def test_finance_table_prefers_earnings_over_newer_routine_or_promotional_news():
    rows = [article("KB금융 투자 행사 개최", published_at="2026-11-02T22:00:00+09:00", link="https://www.yna.co.kr/view/event"),
            article("우리금융, 경제교육·연탄 지원", published_at="2026-11-02T22:30:00+09:00", link="https://www.yna.co.kr/view/promo"),
            article()]
    output = render(rows)
    assert "KB금융 실적 발표" in output
    assert "투자 행사" not in output and "연탄 지원" not in output


def test_finance_table_keeps_newest_material_story_and_per_category_cap():
    output = render([article("KB금융 실적 발표", published_at="2026-11-02T20:00:00+09:00"),
                     article("IBK기업은행 지분 매각", link="https://www.yna.co.kr/view/sale")])
    assert "IBK기업은행 지분 매각" in output and "KB금융 실적 발표" not in output
    assert output.count(FINANCE + " |") == 1


def checked_article(**changes):
    row = article(body_status="no_supported_context", body_facts=[],
                  body_published_at="2026-11-02T21:21:47+09:00",
                  body_modified_at="2026-11-02T21:21:47+09:00",
                  body_source_url="https://www.yna.co.kr/view/finance")
    row.update(changes)
    return row


def test_checked_body_without_supported_context_is_not_labelled_title_only():
    output = render([checked_article(body_facts=[{"summary": "unverified", "implication": "unverified"}])])
    assert "본문 확인·자동 해석 근거 부족" in output
    assert "제목 확인·본문 원인 해석 보류" not in output
    assert "사실(본문)" not in output
    assert "unverified" not in output


@pytest.mark.parametrize("changes", [
    {"body_status": "headline_mismatch"}, {"body_status": "article_version_after_report"},
    {"body_status": "article_timestamp_mismatch"}, {"body_modified_at": "2026-11-03T00:00:00+09:00"},
    {"body_published_at": ""}, {"body_source_url": "https://www.yna.co.kr/view/different"},
    {"body_published_at": "2026-10-30T12:00:00+09:00", "body_modified_at": "2026-10-30T12:00:00+09:00"},
])
def test_unverified_or_future_body_does_not_claim_checked_context(changes):
    output = render([checked_article(**changes)])
    assert "본문 확인·자동 해석 근거 부족" not in output
    assert "제목 확인·본문 원인 해석 보류" in output


def test_future_article_is_not_selected_as_finance_evidence():
    output = render([article(published_at="2026-11-03T00:00:00+09:00")])
    assert "날짜·출처·주제 검증을 통과한 기사 없음" in output
