"""Formatting and lightweight conversion helpers for Stock Lab.

This module is intentionally limited to pure helpers. It should not import
Streamlit, Supabase, yfinance, or scoring code.
"""

import html

import pandas as pd


def format_currency(val, ticker):
    if pd.isna(val):
        return "-"
    if str(ticker).endswith(".KS") or str(ticker).endswith(".KQ"):
        return f"₩{int(val):,}"
    return f"${val:,.2f}"


def escape_html_value(value):
    return html.escape(str(value or ""))


def normalize_text(x):
    return str(x).strip().lower()


SEARCH_TICKER_PREFIXES = ("탐색:", "탐색：", "탐색", "SEARCH:", "SEARCH：")


def strip_search_prefix(value):
    text = str(value or "").strip()
    upper = text.upper()
    for prefix in SEARCH_TICKER_PREFIXES:
        if upper.startswith(prefix.upper()):
            text = text[len(prefix):].strip()
            break
    return text.lstrip(":：").strip()


def sanitize_ticker_value(t):
    return strip_search_prefix(t).upper().replace(" ", "")


def normalize_ticker(t):
    return sanitize_ticker_value(t).lower().replace(".ks", "").replace(".kq", "")


def parse_num(v):
    if pd.isna(v):
        return 0.0
    s = str(v).replace(",", "").replace("%", "").replace("₩", "").replace("$", "").strip()
    return pd.to_numeric(s, errors="coerce") if s != "" else 0.0


def clean_float(value, default=0.0):
    try:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return float(default)
        return float(str(value).replace(",", ""))
    except Exception:
        return float(default)


def clean_int(value, default=None):
    try:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return default
        return int(float(value))
    except Exception:
        return default


def clean_bool(value):
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, str):
        return value.strip().lower() in ["true", "1", "yes", "y", "t"]
    return bool(value)


def dataframe_from_rows(rows, columns):
    if isinstance(rows, pd.DataFrame):
        df = rows.copy()
    else:
        df = pd.DataFrame(rows or [])
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def clean_symbol(ticker: str) -> str:
    """티커에서 .KS / .KQ 접미사를 제거하고 대문자로 반환. '005930.KS' → '005930'"""
    return sanitize_ticker_value(ticker).replace(".KS", "").replace(".KQ", "")


def is_ticker_like_text(value) -> bool:
    """문자열이 종목 코드처럼 생겼는지 판별 (6자리 숫자, .KS/.KQ 접미사, 영문 심볼 등)."""
    text = sanitize_ticker_value(value)
    symbol = text.replace(".KS", "").replace(".KQ", "")
    return bool(symbol) and (
        symbol.isdigit()
        or text.endswith((".KS", ".KQ"))
        or (symbol.isascii() and symbol.replace(".", "").isalnum() and " " not in str(value or ""))
    )


def is_kr_listed(ticker: str) -> bool:
    """KRX 상장 종목인지 확인 (.KS 또는 .KQ 접미사)."""
    return sanitize_ticker_value(ticker).endswith((".KS", ".KQ"))


def normalize_bucket(value) -> str:
    """포트폴리오 버킷값을 정규화. 알 수 없는 값은 'core'로 폴백."""
    raw = str(value or "").strip().lower()
    if raw in ["core", "swing", "reserve", "cash", "leverage"]:
        return raw
    return "core"

