from stock_lab_core.formatters import (
    clean_float,
    clean_symbol,
    ensure_kr_suffix_if_code,
    finite_num,
    format_report_money,
    format_report_pct,
    format_report_price,
    format_report_ratio,
    format_currency,
    is_kr_code_like,
    is_kr_listed,
    normalize_ticker,
    parse_num,
    report_num,
)


def test_kr_alphanumeric_etf_code_is_kr_listed():
    assert is_kr_code_like("0167A0")
    assert is_kr_listed("0167A0")
    assert is_kr_listed("0167A0.KS")


def test_kr_alphanumeric_etf_code_formats_as_krw():
    assert format_currency(12345, "0167A0") == "₩12,345"
    assert format_currency(12345, "0167A0.KS") == "₩12,345"


def test_kr_alphanumeric_etf_code_gets_default_ks_suffix():
    assert ensure_kr_suffix_if_code("0167A0") == "0167A0.KS"
    assert ensure_kr_suffix_if_code("0167A0", ".KQ") == "0167A0.KQ"
    assert ensure_kr_suffix_if_code("MRVL") == "MRVL"


def test_finite_num_accepts_scalar_numbers_and_numeric_strings():
    assert finite_num(1)
    assert finite_num(1.5)
    assert finite_num("2.5")


def test_finite_num_rejects_missing_infinite_and_non_numeric_values():
    assert not finite_num(None)
    assert not finite_num(float("nan"))
    assert not finite_num(float("inf"))
    assert not finite_num("N/A")


def test_clean_float_rejects_non_finite_strings():
    assert clean_float("nan", 7.0) == 7.0
    assert clean_float("inf", 7.0) == 7.0


def test_normalize_ticker_removes_kr_suffix_only_at_end():
    assert normalize_ticker("005930.KS") == "005930"
    assert clean_symbol("005930.KQ") == "005930"
    assert normalize_ticker("abc.ksx") == "abc.ksx"


def test_report_num_preserves_legacy_report_parsing():
    assert report_num("1,234") == 1234.0
    assert report_num("", 7.0) == 7.0
    assert report_num("N/A", -1.0) == -1.0


def test_parse_num_handles_non_scalar_values_without_crashing():
    parsed = parse_num(["1,234"])

    assert float(parsed) == 0.0


def test_report_formatters_match_print_report_display_rules():
    assert format_report_money(12345.6) == "12,346원"
    assert format_report_pct("3.456", 1) == "3.5%"
    assert format_report_ratio("1.2345", 2) == "1.23"
    assert format_report_price(1234) == "1,234.00"
    assert format_report_money(float("nan")) == "-"
