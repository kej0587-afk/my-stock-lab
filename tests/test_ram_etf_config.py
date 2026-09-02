from stock_lab_core.constants import KNOWN_TICKER_DISPLAY_NAMES, KNOWN_US_OTHER_ETFS
from stock_lab_core.money_flow import ETF_TO_THEME, MONEY_FLOW_UNIVERSE
from stock_lab_core.news import GENERIC_TICKERS, NEWS_THEME_TERMS_BY_SYMBOL


def test_ram_etf_has_stable_display_and_classification():
    assert "RAM" in KNOWN_US_OTHER_ETFS
    assert KNOWN_TICKER_DISPLAY_NAMES["RAM"] == "Roundhill T-REX 2X Long DRAM Daily Target ETF"


def test_mrna_has_stable_korean_display_name():
    assert KNOWN_TICKER_DISPLAY_NAMES["MRNA"] == "모더나"


def test_known_stock_ignores_stale_etf_flags(app_module):
    contaminated = {
        "name": "Freeport-McMoRan ETF",
        "ticker": "FCX",
        "is_etf": True,
        "asset_class": "us_etf_nasdaq",
        "fin_score": 0,
    }

    normalized_item = app_module.sanitize_watchlist_item(contaminated)

    assert normalized_item["ticker"] == "FCX"
    assert normalized_item["name"] == "프리포트 맥모란"
    assert normalized_item["is_etf"] is False
    assert normalized_item["asset_class"] == "us_stock"
    assert app_module.is_known_etf_ticker("FCX") is False
    assert app_module.is_fin_score_exempt_asset("FCX", True, "us_etf_nasdaq", "프리포트 맥모란") is False
    assert app_module.infer_asset_class_for_ticker("FCX", "us_etf_nasdaq") == "us_stock"


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
    assert app_module.sanitize_asset_name("Aries I", "RAM") == (
        "Roundhill T-REX 2X Long DRAM Daily Target ETF"
    )
    normalized_item = app_module.sanitize_watchlist_item(
        {"name": "Aries I", "ticker": "RAM", "is_etf": False, "asset_class": "us_stock", "fin_score": 3}
    )
    assert normalized_item["ticker"] == "RAM"
    assert normalized_item["name"] == "Roundhill T-REX 2X Long DRAM Daily Target ETF"
    assert normalized_item["is_etf"] is True
    assert normalized_item["asset_class"] == "us_etf_nasdaq"
    assert normalized_item["fin_score"] == 0
    assert app_module.get_sector_benchmark_info("RAM", "us_etf_nasdaq") == ("SMH", "미국 반도체")

    profile = app_module.get_new_etf_manual_profile("RAM")
    assert profile["premium_unavailable_ok"] is True
    assert profile["composition_axis"] == "DRAM 기초/프록시 Top5"
    assert any(row[1] == "MU" for row in profile["composition"])
