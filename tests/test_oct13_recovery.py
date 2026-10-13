import pytest

from stock_lab_core import prices


def test_chart_metadata_requires_matching_symbol(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_yahoo_chart", lambda *args: (1.0, {"symbol": "OTHER", "longName": "Wrong company"}))
    assert prices.fetch_yahoo_display_metadata("TEST") == {}
    monkeypatch.setattr(prices, "_fetch_yahoo_chart", lambda *args: (1.0, {"symbol": "TEST", "longName": "Full company name", "instrumentType": "ETF"}))
    result = prices.fetch_yahoo_display_metadata("TEST")
    assert result["longName"] == "Full company name" and result["quoteType"] == "ETF"
    assert "sector" not in result


def test_yfinance_none_response_uses_metadata_fallback(app_module, monkeypatch, caplog):
    def broken_ticker(*args, **kwargs):
        raise TypeError("argument of type 'NoneType' is not iterable")

    app_module.lookup_yfinance_info.clear()
    monkeypatch.setattr(app_module.yf, "Ticker", broken_ticker)
    monkeypatch.setattr(app_module, "fetch_yahoo_display_metadata", lambda ticker: {
        "longName": "Full company name", "shortName": "Full company", "quoteType": "ETF",
    })
    try:
        assert app_module.lookup_yfinance_display_name("TEST_METADATA") == "Full company name"
        assert all(record.exc_info is None for record in caplog.records if "YFinance info" in record.message)
    finally:
        app_module.lookup_yfinance_info.clear()


def test_failed_metadata_returns_empty_not_fabricated_info(app_module, monkeypatch):
    app_module.lookup_yfinance_info.clear()
    monkeypatch.setattr(app_module.yf, "Ticker", lambda *args, **kwargs: type("EmptyTicker", (), {"info": None})())
    monkeypatch.setattr(app_module, "fetch_yahoo_display_metadata", lambda ticker: {})
    try:
        assert app_module.lookup_yfinance_info("MISSING_METADATA") == {}
    finally:
        app_module.lookup_yfinance_info.clear()


def test_biotech_card_rejects_chip_and_summary_only_news(app_module):
    card = {"title": "바이오·헬스", "market": "미국", "verdict": "후보권", "action": "눌림대기",
            "anchor_representatives": "모더나 · 일라이릴리 · 유나이티드헬스"}
    unrelated = {"제목": "CXMT 차세대 DRAM 출시, 삼성전자 하락", "읽기분류": "반도체/AI", "초보요약": "바이오 눌림대기"}
    assert app_module._sector_research_card_news_text(card, [unrelated]) == "-"
    direct = {"제목": "Moderna clinical trial vaccine results", "읽기분류": "바이오·헬스케어"}
    assert "Moderna" in app_module._sector_research_card_news_text(card, [unrelated, direct])


@pytest.mark.parametrize("text,term,expected", [
    ("retail sales", "AI", False), ("revenue rises", "EV", False), ("human study", "MU", False),
    ("AI사이버보안 ETF", "AI", True), ("MU earnings", "MU", True), ("삼성전자 반도체", "반도체", True),
])
def test_short_news_terms_do_not_match_inside_other_words(app_module, text, term, expected):
    assert app_module._news_term_matches(text, term) is expected


def test_card_wait_state_is_not_a_news_entity(app_module):
    row = {"name": "바이오·헬스", "state": "WAIT RECOVERY", "source": "리서치", "representatives": "Moderna"}
    terms = app_module._brief_axis_news_terms(row)
    assert "WAIT" not in terms and "RECOVERY" not in terms
    assert "AI" not in app_module._brief_axis_news_categories(row)
