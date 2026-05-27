"""Price loading and latest-price cache helpers for Stock Lab."""

import json
import re
import urllib.request

import pandas as pd
import streamlit as st
import yfinance as yf

_NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json, text/plain, */*",
}


def _is_kr_ticker(ticker: str) -> bool:
    t = str(ticker or "").strip().upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return True
    # 0117V0, 0022T0 같이 .KS 접미사 없는 6자리 영숫자 KR ETF 코드
    code = re.sub(r"\.(KS|KQ)$", "", t, flags=re.IGNORECASE)
    return len(code) == 6 and code[0].isdigit() and code.isalnum()


def _kr_code(ticker: str) -> str:
    """000660.KS → 000660"""
    return re.sub(r"\.(KS|KQ)$", "", str(ticker).strip().upper(), flags=re.IGNORECASE)


def _fetch_naver_price(ticker: str) -> float:
    """
    네이버 모바일 API로 한국 주식 현재가 조회.
    장중·동시호가 시 실시간에 가까운 가격을 반환.
    실패 시 0.0 반환.
    """
    code = _kr_code(ticker)
    if not code:
        return 0.0
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        req = urllib.request.Request(url, headers=_NAVER_HEADERS)
        raw = urllib.request.urlopen(req, timeout=5).read()
        text = raw.decode("utf-8", errors="ignore")
        # closePrice: "1,847,000" 형태 → 숫자 추출
        m = re.search(r'"closePrice"\s*:\s*"([\d,]+)"', text)
        if not m:
            # 장 시작 전/후 stockEndType 대비 fallback
            m = re.search(r'"stockEndPrice"\s*:\s*"([\d,]+)"', text)
        if m:
            return float(m.group(1).replace(",", ""))
    except Exception:
        pass
    return 0.0


def _fetch_naver_prices_bulk(kr_tickers: list) -> dict:
    """
    네이버 시세 bulk API: 한 번 요청으로 여러 종목 조회.
    반환: {NORMALIZED_TICKER: price}
    """
    if not kr_tickers:
        return {}
    codes = [_kr_code(t) for t in kr_tickers]
    try:
        query = "|".join(f"SERVICE_ITEM:{c}" for c in codes)
        url = f"https://polling.finance.naver.com/api/realtime?query={urllib.request.quote(query)}"
        req = urllib.request.Request(url, headers=_NAVER_HEADERS)
        raw = urllib.request.urlopen(req, timeout=6).read()
        text = raw.decode("utf-8", errors="ignore")
        # {"SERVICE_ITEM:000660":{"nv":"1847000", ...}, ...}
        prices = {}
        for code, ticker in zip(codes, kr_tickers):
            pattern = rf'"SERVICE_ITEM:{re.escape(code)}".*?"nv"\s*:\s*"(\d+)"'
            m = re.search(pattern, text)
            if m:
                prices[normalize_price_lookup_key(ticker)] = float(m.group(1))
        return prices
    except Exception:
        return {}


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


def _fetch_yahoo_quote(ticker: str) -> float:
    """
    Yahoo Finance chart API를 직접 호출해 현재가를 조회합니다.
    yfinance SQLite tz 캐시 lock 없이 동작 — Streamlit Cloud 병렬 환경에서도 안전.
    regularMarketPrice (정규장 현재가) → currentPrice 순으로 시도.
    """
    try:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}"
            "?interval=1m&range=1d&includePrePost=true"
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        meta = data["chart"]["result"][0]["meta"]
        for key in ("regularMarketPrice", "currentPrice", "chartPreviousClose"):
            val = meta.get(key)
            if val and float(val) > 0:
                return float(val)
    except Exception:
        pass
    return 0.0


def _fetch_yf_fast_info_price(ticker: str) -> float:
    """
    yf.Ticker.fast_info — 프리마켓/애프터마켓 포함 최신가.
    우선순위: regular_market_price(정규장) → pre/post_market_price → last_price
    """
    try:
        fi = yf.Ticker(ticker).fast_info
        for attr in ("regular_market_price", "last_price", "pre_market_price", "post_market_price"):
            try:
                val = getattr(fi, attr, None)
                if val is not None and float(val) > 0:
                    return float(val)
            except Exception:
                continue
    except Exception:
        pass
    return 0.0


def _fetch_yf_download_price(ticker: str, interval: str = "5m", prepost: bool = True) -> float:
    try:
        df = yf.download(
            ticker, period="1d", interval=interval,
            progress=False, prepost=prepost, auto_adjust=False,
        )
        price = get_latest_close_from_series(extract_download_close_series(df, ticker))
        return price if price > 0 else 0.0
    except Exception:
        return 0.0


def _fetch_price_uncached(ticker: str) -> float:
    """
    캐시 없는 현재가 조회 로직. load_latest_price 와 clear_latest_price_cache 가 공유.

    한국 주식 (.KS/.KQ):
        1차 - 네이버 모바일 API  (장중 실시간에 가까움)
        2차 - yfinance 5분봉 + prepost
        3차 - yfinance 일봉 폴백

    미국·기타 주식:
        1차 - Yahoo Finance API 직접 조회  (SQLite 없음, 스레드 안전)
        2차 - yf.fast_info.regular_market_price (정규장 현재가 우선)
        3차 - yfinance 1분봉 + prepost
        4차 - yfinance 5분봉 + prepost
        5차 - yfinance 일봉 폴백
    """
    if _is_kr_ticker(ticker):
        price = _fetch_naver_price(ticker)
        if price > 0:
            return price
        price = _fetch_yf_download_price(ticker, interval="5m", prepost=True)
        if price > 0:
            return price
    else:
        # Yahoo Finance 직접 API (SQLite lock 없음, 가장 신뢰성 높음)
        price = _fetch_yahoo_quote(ticker)
        if price > 0:
            return price
        price = _fetch_yf_fast_info_price(ticker)
        if price > 0:
            return price
        price = _fetch_yf_download_price(ticker, interval="1m", prepost=True)
        if price > 0:
            return price
        price = _fetch_yf_download_price(ticker, interval="5m", prepost=True)
        if price > 0:
            return price

    # 공통 일봉 최종 폴백
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
def _load_latest_price_cached(ticker: str) -> float:
    """TTL=60초 캐시 래퍼. 성공값(>0)만 캐시에 저장하기 위해 내부에서 검증."""
    return _fetch_price_uncached(ticker)


def load_latest_price(ticker: str) -> float:
    """
    단일 종목 현재가 조회 (공개 API, TTL=60초).
    캐시 결과가 0(조회 실패)이면 캐시를 거치지 않고 즉시 재시도.
    → '실패 결과 캐싱' 문제 방지.
    """
    price = _load_latest_price_cached(ticker)
    if price > 0:
        return price
    # 캐시된 0: 이 티커만 우회하고 바로 재시도 (다른 티커 캐시 보존)
    return _fetch_price_uncached(ticker)


@st.cache_data(ttl=60, show_spinner=False)
def load_latest_prices_batch(tickers) -> dict:
    """
    여러 종목 현재가 일괄 조회. TTL=60초.

    한국 (.KS/.KQ):  네이버 bulk API → 개별 네이버 → yfinance 5분봉
    미국/기타:       yfinance 5분봉 + prepost → 일봉 폴백
    """
    unique_tickers: list[str] = []
    seen: set[str] = set()
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
        t = unique_tickers[0]
        return {normalize_price_lookup_key(t): load_latest_price(t)}

    prices: dict[str, float] = {}

    kr_tickers  = [t for t in unique_tickers if _is_kr_ticker(t)]
    us_tickers  = [t for t in unique_tickers if not _is_kr_ticker(t)]

    # ── 한국 주식: 네이버 bulk API ──────────────────────────────────────
    if kr_tickers:
        naver_prices = _fetch_naver_prices_bulk(kr_tickers)
        prices.update(naver_prices)

        # bulk 실패 종목은 개별 네이버 조회
        kr_missing = [t for t in kr_tickers if normalize_price_lookup_key(t) not in prices]
        for t in kr_missing:
            p = _fetch_naver_price(t)
            if p > 0:
                prices[normalize_price_lookup_key(t)] = p

        # 그래도 없으면 yfinance 5분봉
        kr_still_missing = [t for t in kr_tickers if normalize_price_lookup_key(t) not in prices]
        if kr_still_missing:
            try:
                data = yf.download(
                    kr_still_missing if len(kr_still_missing) > 1 else kr_still_missing[0],
                    period="1d", interval="5m", prepost=True,
                    progress=False, group_by="ticker", threads=True, auto_adjust=False,
                )
                if data is not None and not data.empty:
                    for t in kr_still_missing:
                        p = get_latest_close_from_series(extract_download_close_series(data, t))
                        if p > 0:
                            prices[normalize_price_lookup_key(t)] = p
            except Exception:
                pass

    # ── 미국/기타: yfinance 5분봉 + prepost ────────────────────────────
    if us_tickers:
        try:
            data = yf.download(
                us_tickers if len(us_tickers) > 1 else us_tickers[0],
                period="1d", interval="5m", prepost=True,
                progress=False, group_by="ticker", threads=True, auto_adjust=False,
            )
            if data is not None and not data.empty:
                for t in us_tickers:
                    p = get_latest_close_from_series(extract_download_close_series(data, t))
                    if p > 0:
                        prices[normalize_price_lookup_key(t)] = p
        except Exception:
            pass

        # 실패 종목: fast_info → Yahoo 직접 API 순으로 개별 조회
        us_missing = [t for t in us_tickers if normalize_price_lookup_key(t) not in prices]
        for t in us_missing:
            p = _fetch_yf_fast_info_price(t)
            if p <= 0:
                p = _fetch_yahoo_quote(t)  # SQLite lock 없이 동작하는 직접 조회
            if p > 0:
                prices[normalize_price_lookup_key(t)] = p

    # ── 공통 일봉 최종 폴백 ────────────────────────────────────────────
    all_missing = [t for t in unique_tickers if normalize_price_lookup_key(t) not in prices]
    if all_missing:
        try:
            fallback = yf.download(
                all_missing if len(all_missing) > 1 else all_missing[0],
                period="5d", interval="1d",
                progress=False, group_by="ticker", threads=True, auto_adjust=False,
            )
            if fallback is not None and not fallback.empty:
                for t in all_missing:
                    p = get_latest_close_from_series(extract_download_close_series(fallback, t))
                    if p > 0:
                        prices[normalize_price_lookup_key(t)] = p
        except Exception:
            pass

    return prices


def clear_latest_price_cache():
    for fn in [_load_latest_price_cached, load_latest_prices_batch]:
        if hasattr(fn, "clear"):
            fn.clear()


def clear_selected_price_cache():
    clear_latest_price_cache()
