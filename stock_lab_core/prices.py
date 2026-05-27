"""Price loading and latest-price cache helpers for Stock Lab."""

import json
import re
import threading
import urllib.request

import pandas as pd
import streamlit as st
import yfinance as yf

# ── yfinance SQLite tz-cache 동시성 보호 ─────────────────────────────────────
# Streamlit Cloud 멀티스레드 환경에서 여러 스레드가 동시에 yfinance를 호출하면
# SQLite tz 캐시에 동시 쓰기 → "database is locked" 오류 발생.
# 모듈 레벨 Lock으로 yfinance 호출을 직렬화해 방지.
_YF_LOCK = threading.Lock()

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
    """
    일봉 OHLCV 다운로드 (TTL=5분).
    _YF_LOCK으로 yfinance 동시 호출 직렬화 — prefetch_price_data_parallel 같은
    멀티스레드 환경에서 SQLite tz-cache 충돌("database is locked") 방지.
    """
    with _YF_LOCK:
        df = yf.download(
            ticker, period=period, interval="1d",
            progress=False, threads=False,
        )
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.ffill().dropna()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_usdkrw_rate():
    try:
        with _YF_LOCK:
            df = yf.download(
                "USDKRW=X", period="5d", interval="1d",
                progress=False, auto_adjust=False, threads=False,
            )
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


_YQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}


def _last_candle_close(result: dict) -> float:
    """
    Yahoo v8 chart 응답에서 가장 최근 1분봉 Close 값을 꺼냅니다.
    meta.regularMarketPrice 는 종종 이전 세션 종가를 캐싱하므로 캔들이 더 정확합니다.
    """
    try:
        closes = result["indicators"]["quote"][0].get("close") or []
        # null(None) 제거 후 마지막 값
        valid = [c for c in closes if c is not None and float(c) > 0]
        if valid:
            return float(valid[-1])
    except Exception:
        pass
    return 0.0


def _fetch_yahoo_quote(ticker: str) -> float:
    """
    Yahoo Finance chart API 직접 호출 — yfinance SQLite lock 없음.

    우선순위:
      1) 최근 1분봉 캔들의 마지막 Close  ← 진짜 실시간 체결가
      2) meta.regularMarketPrice          ← Yahoo 캐시값(이전 종가일 수 있음)
      3) meta.currentPrice / chartPreviousClose

    query1 실패 시 query2 로 재시도.
    """
    for host in ("query1", "query2"):
        try:
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                f"{urllib.request.quote(ticker)}"
                "?interval=1m&range=1d&includePrePost=true"
            )
            req = urllib.request.Request(url, headers=_YQ_HEADERS)
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read())

            results = (data.get("chart") or {}).get("result") or []
            if not results:
                continue
            result = results[0]
            meta = result.get("meta", {})

            # 1) 최근 캔들 Close (가장 정확한 실시간 체결가)
            price = _last_candle_close(result)
            if price > 0:
                return price

            # 2) meta 필드 폴백
            for key in ("regularMarketPrice", "currentPrice", "chartPreviousClose"):
                val = meta.get(key)
                if val and float(val) > 0:
                    return float(val)

        except Exception:
            continue

    return 0.0


def _fetch_yf_fast_info_price(ticker: str) -> float:
    """
    yf.Ticker.fast_info — 프리마켓/애프터마켓 포함 최신가.
    우선순위: regular_market_price(정규장) → pre/post_market_price → last_price
    _YF_LOCK 으로 SQLite tz 캐시 동시 쓰기 방지.
    """
    try:
        with _YF_LOCK:
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
    """_YF_LOCK 으로 SQLite tz 캐시 동시 쓰기 방지. threads=False 로 내부 병렬 차단."""
    try:
        with _YF_LOCK:
            df = yf.download(
                ticker, period="1d", interval=interval,
                progress=False, prepost=prepost, auto_adjust=False,
                threads=False,
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

    # 공통 일봉 최종 폴백 (lock + threads=False)
    try:
        with _YF_LOCK:
            df = yf.download(
                ticker, period="5d", interval="1d",
                progress=False, auto_adjust=False, threads=False,
            )
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

        # 그래도 없으면 yfinance 5분봉 (lock + threads=False로 SQLite 충돌 방지)
        kr_still_missing = [t for t in kr_tickers if normalize_price_lookup_key(t) not in prices]
        if kr_still_missing:
            try:
                with _YF_LOCK:
                    data = yf.download(
                        kr_still_missing if len(kr_still_missing) > 1 else kr_still_missing[0],
                        period="1d", interval="5m", prepost=True,
                        progress=False, group_by="ticker", threads=False, auto_adjust=False,
                    )
                if data is not None and not data.empty:
                    for t in kr_still_missing:
                        p = get_latest_close_from_series(extract_download_close_series(data, t))
                        if p > 0:
                            prices[normalize_price_lookup_key(t)] = p
            except Exception:
                pass

    # ── 미국/기타: Yahoo 직접 API 우선 → yfinance 5분봉 폴백 ────────────
    if us_tickers:
        # 1차: Yahoo Finance 직접 API (캔들 기반 실시간가, SQLite lock 없음)
        for t in us_tickers:
            p = _fetch_yahoo_quote(t)
            if p > 0:
                prices[normalize_price_lookup_key(t)] = p

        # 2차: Yahoo 직접 실패 종목만 yfinance 5분봉으로 보완
        us_yf_needed = [t for t in us_tickers if normalize_price_lookup_key(t) not in prices]
        if us_yf_needed:
            try:
                with _YF_LOCK:
                    data = yf.download(
                        us_yf_needed if len(us_yf_needed) > 1 else us_yf_needed[0],
                        period="1d", interval="5m", prepost=True,
                        progress=False, group_by="ticker", threads=False, auto_adjust=False,
                    )
                if data is not None and not data.empty:
                    for t in us_yf_needed:
                        p = get_latest_close_from_series(extract_download_close_series(data, t))
                        if p > 0:
                            prices[normalize_price_lookup_key(t)] = p
            except Exception:
                pass

        # 3차: 여전히 없는 종목은 fast_info
        us_still_missing = [t for t in us_tickers if normalize_price_lookup_key(t) not in prices]
        for t in us_still_missing:
            p = _fetch_yf_fast_info_price(t)
            if p > 0:
                prices[normalize_price_lookup_key(t)] = p

    # ── 공통 일봉 최종 폴백 ────────────────────────────────────────────
    all_missing = [t for t in unique_tickers if normalize_price_lookup_key(t) not in prices]
    if all_missing:
        try:
            with _YF_LOCK:
                fallback = yf.download(
                    all_missing if len(all_missing) > 1 else all_missing[0],
                    period="5d", interval="1d",
                    progress=False, group_by="ticker", threads=False, auto_adjust=False,
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
