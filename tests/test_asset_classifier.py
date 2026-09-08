from stock_lab_core.asset_classifier import (
    infer_asset_class_for_ticker,
    is_fin_score_exempt_asset,
    is_known_etf_ticker,
    is_known_individual_stock_ticker,
    normalize_individual_stock_asset_class,
)


def test_known_individual_stocks_ignore_stale_etf_metadata():
    for ticker in ("FCX", "NEM", "MRNA"):
        assert is_known_individual_stock_ticker(ticker)
        assert not is_known_etf_ticker(ticker)
        assert not is_fin_score_exempt_asset(ticker, True, "us_etf_nasdaq", f"{ticker} ETF")
        assert infer_asset_class_for_ticker(ticker, "us_etf_nasdaq") == "us_stock"


def test_known_etfs_remain_fin_score_exempt():
    assert is_known_etf_ticker("RAM")
    assert is_known_etf_ticker("BITX")
    assert is_fin_score_exempt_asset("RAM", False, "us_stock", "Roundhill T-REX 2X Long DRAM Daily Target ETF")
    assert is_fin_score_exempt_asset("BITX", False, "us_stock", "2x Bitcoin ETF")
    assert infer_asset_class_for_ticker("RAM", "us_stock") == "us_etf_nasdaq"


def test_kr_etf_name_keyword_detects_new_fund_like_asset():
    assert is_fin_score_exempt_asset("123456.KS", False, "", "TIGER 신규 테마 ETF")
    assert infer_asset_class_for_ticker("123456.KS", "kr_etf") == "kr_etf"


def test_individual_asset_class_normalization_keeps_valid_stock_class():
    assert normalize_individual_stock_asset_class("FCX", "swing") == "swing"
    assert normalize_individual_stock_asset_class("FCX", "us_etf_nasdaq") == "us_stock"
