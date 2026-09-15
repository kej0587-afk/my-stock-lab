from stock_lab_core.asset_classifier import (
    infer_asset_class_for_ticker,
    is_domestic_kr_core_etf,
    is_fin_score_exempt_asset,
    is_known_etf_ticker,
    is_known_individual_stock_ticker,
    is_leveraged_or_inverse_product,
    is_tdf_or_fund_allocation_product,
    is_us_broad_index_core_etf,
    normalize_individual_stock_asset_class,
    resolve_effective_investment_bucket,
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


def test_leveraged_products_route_to_leverage_bucket():
    assert is_leveraged_or_inverse_product("2x Bitcoin ETF", "BITX", "us_etf_nasdaq")
    assert is_leveraged_or_inverse_product("TIGER 미국나스닥100레버리지", "418660.KS", "kr_etf")
    assert resolve_effective_investment_bucket("2x Bitcoin ETF", "BITX", "swing", "us_etf_nasdaq") == "leverage"


def test_individual_copper_stock_does_not_become_leverage_or_etf():
    assert not is_leveraged_or_inverse_product("프리포트 맥모란", "FCX", "us_stock")
    assert resolve_effective_investment_bucket("프리포트 맥모란", "FCX", "swing", "us_stock") == "swing"


def test_tdf_and_core_index_classifiers():
    assert is_tdf_or_fund_allocation_product("TDF 2045 적격 액티브", "TDF2045", "fund")
    assert is_us_broad_index_core_etf("SPY", "us_etf_sp", "S&P500")
    assert is_us_broad_index_core_etf("379810.KS", "us_etf_nasdaq", "TIGER 미국나스닥100")
    assert is_domestic_kr_core_etf("069500.KS", "kr_etf", "KOSPI200 ETF")
