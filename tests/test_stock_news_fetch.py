from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from io import BytesIO
from urllib.error import URLError
from xml.sax.saxutils import escape

import pytest

from stock_lab_core import news


@pytest.fixture(autouse=True)
def no_external_lookup(monkeypatch):
    news.get_ticker_news.clear()
    monkeypatch.setattr(news, "get_yfinance_company_names", lambda _: pytest.fail("unnecessary Yahoo lookup"))
    monkeypatch.setattr(news, "get_news_theme_terms", lambda *args: [])
    yield
    news.get_ticker_news.clear()


def rss(*titles):
    published = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1))
    items = "".join(f"<item><title>{escape(title)}</title><link>https://example.com/{i}</link>"
                    f"<source>Reuters</source><pubDate>{published}</pubDate></item>" for i, title in enumerate(titles))
    return BytesIO(f"<rss><channel>{items}</channel></rss>".encode())


@pytest.mark.parametrize("ticker,name,title,alias", [
    ("005930", "삼성전자", "삼성전자 분기 실적 발표 매출 증가", "삼성전자"),
    ("NVDA", "NVIDIA CORP", "Nvidia earnings revenue rises as shares rally", "NVIDIA"),
])
def test_broad_query_still_filters_unrelated_news(monkeypatch, ticker, name, title, alias):
    calls, responses = [], []

    def fetch(req, timeout):
        calls.append(req.full_url)
        response = rss(title, "성시경도 극찬한 라면", "Other Company earnings shares rally")
        responses.append(response)
        return response

    monkeypatch.setattr(news.urllib.request, "urlopen", fetch)
    queries, names = news.build_stock_news_queries(ticker, name)
    assert queries[0] == f'"{alias}"' and names[0] == alias
    items, logs = news.get_ticker_news(ticker, name, False)
    direct = [item for item in items if item["category"] == news.NEWS_CATEGORY_DIRECT]
    assert [item["title"] for item in direct] == [title]
    assert 0 < len(calls) <= 16 and all(response.closed for response in responses)
    count = len(calls)
    assert news.get_ticker_news(ticker, name, False) == (items, logs)
    assert len(calls) == count


def test_failed_rss_can_be_retried_for_only_this_stock(monkeypatch):
    calls = []

    def fail(req, timeout):
        calls.append(req.full_url)
        raise URLError("offline")

    monkeypatch.setattr(news.urllib.request, "urlopen", fail)
    result = news.get_ticker_news("005930", "삼성전자", False)
    assert not result[0] and any("정상 RSS 응답 없음" in line for line in result[1])
    assert 0 < len(calls) <= 16
    count = len(calls)
    news.get_ticker_news("005930", "삼성전자", False)
    assert len(calls) == count
    news.get_ticker_news.clear("005930", "삼성전자", False)
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *args, **kwargs: rss("삼성전자 실적 발표 매출 증가"))
    assert news.get_ticker_news("005930", "삼성전자", False)[0]


def test_empty_feed_is_not_reported_as_connection_failure(monkeypatch):
    monkeypatch.setattr(news.urllib.request, "urlopen", lambda *args, **kwargs: rss())
    items, logs = news.get_ticker_news("005930", "삼성전자", False)
    assert not items
    assert any("필터 통과 기사 없음" in line for line in logs)
    assert not any("수집 실패" in line for line in logs)


def test_requests_stop_after_time_budget(monkeypatch):
    clock = [0.0]
    calls = []

    def fetch(req, timeout):
        calls.append(req.full_url)
        clock[0] += 21
        return rss()

    monkeypatch.setattr(news.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(news.urllib.request, "urlopen", fetch)
    items, logs = news.get_ticker_news("005930", "삼성전자", False)
    assert not items and len(calls) == 1
    assert any("시간/횟수 제한" in line for line in logs)
