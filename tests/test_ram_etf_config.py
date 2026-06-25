from stock_lab_core.constants import KNOWN_TICKER_DISPLAY_NAMES, KNOWN_US_OTHER_ETFS
from stock_lab_core.money_flow import ETF_TO_THEME, MONEY_FLOW_UNIVERSE
from stock_lab_core.news import GENERIC_TICKERS, NEWS_THEME_TERMS_BY_SYMBOL


def test_ram_etf_has_stable_display_and_classification():
    assert "RAM" in KNOWN_US_OTHER_ETFS
    assert KNOWN_TICKER_DISPLAY_NAMES["RAM"] == "Roundhill T-REX 2X Long DRAM Daily Target ETF"


def test_ram_etf_is_connected_to_money_flow_and_news_filters():
    tickers = {str(row.get("ticker", "")).upper() for row in MONEY_FLOW_UNIVERSE}

    assert "RAM" in tickers
    assert ETF_TO_THEME["RAM"] == "국내 AI 반도체·소부장"
    assert "RAM" in NEWS_THEME_TERMS_BY_SYMBOL
    assert "ram" in GENERIC_TICKERS


def test_ram_etf_app_profile_uses_dram_as_underlying(app_module):
    assert app_module.TICKER_MAP["RAM"] == ("RAM", True, "us_etf_nasdaq")
    assert app_module.UNDERLYING_BENCHMARK_MAP["RAM"] == ("DRAM", "DRAM 2배")
    assert app_module.resolve_display_name_for_ticker("RAM", "Aries I") == (
        "Roundhill T-REX 2X Long DRAM Daily Target ETF"
    )

    profile = app_module.get_new_etf_manual_profile("RAM")
    assert profile["premium_unavailable_ok"] is True
    assert profile["composition_axis"] == "DRAM 기초/프록시 Top5"
    assert any(row[1] == "MU" for row in profile["composition"])
