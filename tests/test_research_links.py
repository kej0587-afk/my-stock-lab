from stock_lab_core.research_links import (
    build_research_home_link_groups,
    build_research_links_for_ticker,
)


def _flatten(groups):
    return [link for group in groups for link in group["links"]]


def test_research_links_build_us_stock_sources():
    links = _flatten(build_research_links_for_ticker("AAPL", "Apple", is_etf=False))
    urls = {link["label"]: link["url"] for link in links}

    assert "TradingView" in urls
    assert urls["Yahoo Finance"].endswith("/AAPL")
    assert "sec.gov" in urls["SEC EDGAR"]
    assert urls["Stock Analysis"].endswith("/stocks/aapl/")


def test_research_links_build_kr_stock_sources():
    links = _flatten(build_research_links_for_ticker("005930.KS", "삼성전자", is_etf=False))
    urls = {link["label"]: link["url"] for link in links}

    assert "code=005930" in urls["네이버 증권"]
    assert "dart.fss.or.kr" in urls["DART"]
    assert "data.krx.co.kr" in urls["KRX"]


def test_research_home_links_include_macro_and_calendar():
    links = _flatten(build_research_home_link_groups())
    labels = {link["label"] for link in links}

    assert {"FRED", "한국은행 ECOS", "CME FedWatch", "Nasdaq Earnings"}.issubset(labels)
