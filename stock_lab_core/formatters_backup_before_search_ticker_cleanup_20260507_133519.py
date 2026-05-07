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


def normalize_ticker(t):
    return str(t).strip().lower().replace(".ks", "").replace(".kq", "")


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

