from stock_lab_core.formatters import (
    ensure_kr_suffix_if_code,
    format_currency,
    is_kr_code_like,
    is_kr_listed,
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
