"""Price loading and latest-price cache helpers for Stock Lab."""

import pandas as pd
import streamlit as st
import yfinance as yf


@st.cache_data(ttl=300)
def load_price_df(ticker, period="1y"):
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.ffill().dropna()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_usdkrw_rate():
    try:
        df = yf.download("USDKRW=X", period="5d", interval="1d", progress=False, auto_adjust=False)
        if df is None or df.empty:
            return 0.0
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.ffill().dropna()
        if df.empty or "Close" not in df.columns:
            return 0.0
        return float(df["Close"].iloc[-1])
    except Exception:
        return 0.0


def normalize_price_lookup_key(ticker):
    return str(ticker or "").strip().upper()


def get_latest_close_from_series(series):
    if isinstance(series, pd.DataFrame):
        if series.empty:
            return 0.0
        series = series.iloc[:, 0]

    values = pd.to_numeric(series, errors="coerce").ffill().dropna()
    if values.empty:
        return 0.0
    return float(values.iloc[-1])


def find_matching_column_value(values, target):
    target = normalize_price_lookup_key(target)
    for value in values:
        if normalize_price_lookup_key(value) == target:
            return value
    return None


def extract_download_close_series(data, ticker):
    if data is None or data.empty:
        return pd.Series(dtype=float)

    if not isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns:
            return data["Close"]
        return pd.Series(dtype=float)

    for level_no in range(data.columns.nlevels):
        matched_ticker = find_matching_column_value(data.columns.get_level_values(level_no), ticker)
        if matched_ticker is None:
            continue

        sub = data.xs(matched_ticker, axis=1, level=level_no)
        if isinstance(sub, pd.Series):
            return sub
        if "Close" in sub.columns:
            return sub["Close"]

    for level_no in range(data.columns.nlevels):
        matched_close = find_matching_column_value(data.columns.get_level_values(level_no), "Close")
        if matched_close is None:
            continue

        sub = data.xs(matched_close, axis=1, level=level_no)
        matched_ticker = find_matching_column_value(sub.columns, ticker)
        if matched_ticker is not None:
            return sub[matched_ticker]

    return pd.Series(dtype=float)


@st.cache_data(ttl=60, show_spinner=False)
def load_latest_price(ticker):
    # 1차: 1분봉 + prepost → 장중/프리마켓/시간외 실시간
    try:
        df = yf.download(ticker, period="1d", interval="1m", progress=False, prepost=True, auto_adjust=False)
        price = get_latest_close_from_series(extract_download_close_series(df, ticker))
        if price > 0:
            return price
    except Exception:
        pass

    # 2차: 5분봉 + prepost (1분봉 실패 시 폴백)
    try:
        df = yf.download(ticker, period="1d", interval="5m", progress=False, prepost=True, auto_adjust=False)
        price = get_latest_close_from_series(extract_download_close_series(df, ticker))
        if price > 0:
            return price
    except Exception:
        pass

    # 3차: 일봉 폴백 (주말·데이터 없음)
    try:
        df = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=False)
        if df.empty:
            return 0.0
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.ffill().dropna()
        if df.empty or "Close" not in df.columns:
            return 0.0
        return float(df["Close"].iloc[-1])
    except Exception:
        return 0.0


@st.cache_data(ttl=60, show_spinner=False)
def load_latest_prices_batch(tickers):
    unique_tickers = []
    seen = set()
    for ticker in tickers or []:
        ticker_value = str(ticker or "").strip()
        key = normalize_price_lookup_key(ticker_value)
        if not key or key in seen:
            continue
        seen.add(key)
        unique_tickers.append(ticker_value)

    if not unique_tickers:
        return {}

    if len(unique_tickers) == 1:
        ticker = unique_tickers[0]
        return {normalize_price_lookup_key(ticker): load_latest_price(ticker)}

    prices = {}

    # 1차: 5분봉 intraday + prepost=True → 장중/프리마켓/시간외 실시간 반영
    try:
        data = yf.download(
            unique_tickers,
            period="1d",
            interval="5m",
            prepost=True,
            progress=False,
            group_by="ticker",
            threads=True,
            auto_adjust=False,
        )
        if data is not None and not data.empty:
            for ticker in unique_tickers:
                series = extract_download_close_series(data, ticker)
                price = get_latest_close_from_series(series)
                if price > 0:
                    prices[normalize_price_lookup_key(ticker)] = price
    except Exception:
        pass

    # 2차: 5분봉 실패 종목만 일봉 폴백 (주말·시장 닫힌 경우)
    missing = [t for t in unique_tickers if normalize_price_lookup_key(t) not in prices]
    if missing:
        try:
            fallback_data = yf.download(
                missing if len(missing) > 1 else missing[0],
                period="5d",
                interval="1d",
                progress=False,
                group_by="ticker",
                threads=True,
                auto_adjust=False,
            )
            if fallback_data is not None and not fallback_data.empty:
                for ticker in missing:
                    series = extract_download_close_series(fallback_data, ticker)
                    price = get_latest_close_from_series(series)
                    if price > 0:
                        prices[normalize_price_lookup_key(ticker)] = price
        except Exception:
            pass

    return prices


def clear_latest_price_cache():
    for fn in [load_latest_price, load_latest_prices_batch]:
        if hasattr(fn, "clear"):
            fn.clear()


def clear_selected_price_cache():
    clear_latest_price_cache()
