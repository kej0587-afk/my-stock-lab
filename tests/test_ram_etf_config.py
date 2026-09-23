from stock_lab_core.constants import (
    CONCENTRATED_NON_CORE_ETFS,
    KNOWN_KR_ETF_SYMBOLS,
    KNOWN_TICKER_DISPLAY_NAMES,
    KNOWN_US_OTHER_ETFS,
)
from stock_lab_core.money_flow import ETF_TO_THEME, MONEY_FLOW_UNIVERSE
from stock_lab_core.news import GENERIC_TICKERS, NEWS_THEME_TERMS_BY_SYMBOL
from stock_lab_core.decision_engine import DECISION_CODE_BY_LABEL, classify_decision_signal


def test_ram_etf_has_stable_display_and_classification():
    assert "RAM" in KNOWN_US_OTHER_ETFS
    assert KNOWN_TICKER_DISPLAY_NAMES["RAM"] == "Roundhill T-REX 2X Long DRAM Daily Target ETF"
    assert "MAGS" in KNOWN_US_OTHER_ETFS
    assert KNOWN_TICKER_DISPLAY_NAMES["MAGS"] == "Roundhill Magnificent Seven ETF"
    assert "0227L0" in KNOWN_KR_ETF_SYMBOLS
    assert "0227L0" in CONCENTRATED_NON_CORE_ETFS
    assert KNOWN_TICKER_DISPLAY_NAMES["0227L0"] == "HANARO 미국에이전틱AI TOP2+"


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
    assert "MAGS" in tickers
    assert "0227L0.KS" in tickers
    assert ETF_TO_THEME["RAM"] == "국내 AI 반도체·소부장"
    assert ETF_TO_THEME["MAGS"] == "미국 AI·빅테크"
    assert ETF_TO_THEME["0227L0.KS"] == "미국 AI·빅테크"
    assert "RAM" in NEWS_THEME_TERMS_BY_SYMBOL
    assert "MAGS" in NEWS_THEME_TERMS_BY_SYMBOL
    assert "0227L0" in NEWS_THEME_TERMS_BY_SYMBOL
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


def test_ai_bigtech_etf_profiles_are_concentrated_satellites(app_module):
    assert app_module.TICKER_MAP["MAGS"] == ("MAGS", True, "us_etf_nasdaq")
    assert app_module.TICKER_MAP["0227L0"] == ("0227L0.KS", True, "us_etf_nasdaq")
    assert app_module.resolve_display_name_for_ticker("0227L0.KS", "0227L0") == "HANARO 미국에이전틱AI TOP2+"
    assert app_module.resolve_display_name_for_ticker("0227LO.KS", "0227LO") == "HANARO 미국에이전틱AI TOP2+"
    assert app_module.sanitize_asset_name("0227L0", "0227L0.KS") == "HANARO 미국에이전틱AI TOP2+"
    assert app_module.sanitize_asset_name("0227LO.KS", "0227LO.KS") == "HANARO 미국에이전틱AI TOP2+"

    mags_item = app_module.sanitize_watchlist_item(
        {"name": "MAGS", "ticker": "MAGS", "is_etf": False, "asset_class": "us_stock", "fin_score": 3}
    )
    assert mags_item["name"] == "Roundhill Magnificent Seven ETF"
    assert mags_item["is_etf"] is True
    assert mags_item["asset_class"] == "us_etf_nasdaq"
    assert mags_item["fin_score"] == 0

    agentic_item = app_module.sanitize_watchlist_item(
        {"name": "0227L0", "ticker": "0227L0.KS", "is_etf": False, "asset_class": "kr_etf", "fin_score": 3}
    )
    assert agentic_item["name"] == "HANARO 미국에이전틱AI TOP2+"
    assert agentic_item["is_etf"] is True
    assert agentic_item["asset_class"] == "us_etf_nasdaq"
    assert agentic_item["fin_score"] == 0

    assert app_module.get_rs_benchmark("MAGS", "us_etf_nasdaq") == "SPY"
    assert app_module.get_rs_benchmark("0227L0.KS", "us_etf_nasdaq") == "379800.KS"
    assert app_module.get_sector_benchmark_info("MAGS", "us_etf_nasdaq") == ("QQQM", "미국 AI·빅테크")
    assert app_module.get_sector_benchmark_info("0227L0.KS", "us_etf_nasdaq") == ("QQQM", "미국 AI·빅테크")
    assert app_module.UNDERLYING_BENCHMARK_MAP["MAGS"] == ("QQQM", "Magnificent 7/나스닥100")
    assert app_module.UNDERLYING_BENCHMARK_MAP["0227L0"] == ("QQQM", "미국 에이전틱 AI")

    mags_profile = app_module.get_new_etf_manual_profile("MAGS")
    assert mags_profile["composition_axis"] == "Magnificent 7 동일가중 Top7"
    assert any(row[1] == "META" for row in mags_profile["composition"])

    agentic_profile = app_module.get_new_etf_manual_profile("0227L0.KS")
    assert agentic_profile["composition_axis"] == "Agentic AI 실제 구성 Top10"
    assert dict((ticker, weight) for _, ticker, weight in agentic_profile["composition"])["MSFT"] > 20
    assert dict((ticker, weight) for _, ticker, weight in agentic_profile["composition"])["GOOGL"] > 20
    assert any(row[1] == "DELL" for row in agentic_profile["composition"])
    assert any(row[1] == "CRWD" for row in agentic_profile["composition"])
    assert any(row[1] == "DDOG" for row in agentic_profile["composition"])


def test_concentrated_etf_upper_wait_is_caution():
    label = "🟡집중 ETF 상단권: 눌림대기"

    assert DECISION_CODE_BY_LABEL[label] == "CONCENTRATED_ETF_UPPER_WAIT"
    assert classify_decision_signal(label) == "caution"
