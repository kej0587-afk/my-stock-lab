"""Price loading and latest-price cache helpers for Stock Lab."""

import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st
import yfinance as yf

# ── yfinance SQLite tz-cache 동시성 보호 ─────────────────────────────────────
# Streamlit Cloud 멀티스레드 환경에서 여러 스레드가 동시에 yfinance를 호출하면
# SQLite tz 캐시에 동시 쓰기 → "database is locked" 오류 발생.
# 모듈 레벨 Lock으로 yfinance 호출을 직렬화해 방지.
_YF_LOCK = threading.Lock()
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)

_YAHOO_BLOCK_UNTIL = 0.0
_YAHOO_BLOCK_LOCK = threading.Lock()
_YAHOO_BLOCK_SECONDS = 180
_FORCE_LIVE_REFRESH_KEY = "_force_live_price_refresh_until"


def enable_force_live_price_refresh(seconds: int = 45) -> None:
    """Temporarily use slower live-price fallbacks after a manual refresh."""
    try:
        st.session_state[_FORCE_LIVE_REFRESH_KEY] = (
            pd.Timestamp.now().timestamp() + max(int(seconds), 1)
        )
    except Exception:
        pass


def _force_live_price_refresh_active() -> bool:
    try:
        return pd.Timestamp.now().timestamp() < float(st.session_state.get(_FORCE_LIVE_REFRESH_KEY, 0.0))
    except Exception:
        return False


def _is_yahoo_temporarily_blocked() -> bool:
    return (not _force_live_price_refresh_active()) and pd.Timestamp.now().timestamp() < _YAHOO_BLOCK_UNTIL

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


def _period_start_timestamp(period: str) -> pd.Timestamp:
    text = str(period or "1y").strip().lower()
    today = pd.Timestamp.today().normalize()
    if text == "ytd":
        return pd.Timestamp(year=today.year, month=1, day=1)
    if text == "max":
        return today - pd.DateOffset(years=10)
    try:
        if text.endswith("mo"):
            return today - pd.DateOffset(months=max(int(text[:-2]), 1))
        if text.endswith("y"):
            return today - pd.DateOffset(years=max(int(text[:-1]), 1))
        if text.endswith("d"):
            return today - pd.DateOffset(days=max(int(text[:-1]), 1) + 7)
    except Exception:
        pass
    return today - pd.DateOffset(years=1)


def _normalize_pykrx_ohlcv(df) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy().rename(columns={
        "시가": "Open",
        "고가": "High",
        "저가": "Low",
        "종가": "Close",
        "거래량": "Volume",
    })
    if "Close" not in out.columns:
        return pd.DataFrame()
    for col in ("Open", "High", "Low"):
        if col not in out.columns:
            out[col] = out["Close"]
    if "Volume" not in out.columns:
        out["Volume"] = 0
    cols = ["Open", "High", "Low", "Close", "Volume"]
    out = out[cols].apply(pd.to_numeric, errors="coerce")
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()].sort_index().ffill()
    return out.dropna(subset=["Close", "High", "Low"])


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_pykrx_ohlcv(ticker: str, period: str = "1y") -> pd.DataFrame:
    if not _is_kr_ticker(ticker):
        return pd.DataFrame()
    try:
        from pykrx import stock as _pykrx
    except Exception:
        return pd.DataFrame()

    code = _kr_code(ticker)
    if not code:
        return pd.DataFrame()
    start = _period_start_timestamp(period).strftime("%Y%m%d")
    end = pd.Timestamp.today().normalize().strftime("%Y%m%d")
    getters = []
    if hasattr(_pykrx, "get_market_ohlcv_by_date"):
        getters.append(lambda: _pykrx.get_market_ohlcv_by_date(start, end, code))
    if hasattr(_pykrx, "get_etf_ohlcv_by_date"):
        getters.append(lambda: _pykrx.get_etf_ohlcv_by_date(start, end, code))

    for getter in getters:
        try:
            out = _normalize_pykrx_ohlcv(getter())
            if not out.empty:
                return out
        except Exception:
            continue
    return pd.DataFrame()


def _fetch_pykrx_latest_close(ticker: str) -> float:
    df = _fetch_pykrx_ohlcv(ticker, "1mo")
    if df.empty or "Close" not in df.columns:
        return 0.0
    return get_latest_close_from_series(df["Close"])


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


def _fetch_naver_realtime_price(ticker: str) -> float:
    code = _kr_code(ticker)
    if not code:
        return 0.0
    try:
        query = urllib.parse.quote(f"SERVICE_ITEM:{code}")
        url = f"https://polling.finance.naver.com/api/realtime?query={query}"
        req = urllib.request.Request(url, headers=_NAVER_HEADERS)
        raw = urllib.request.urlopen(req, timeout=4).read()
        text = raw.decode("utf-8", errors="ignore")
        m = re.search(r'"nv"\s*:\s*"?([\d,]+)"?', text)
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
        url = f"https://polling.finance.naver.com/api/realtime?query={urllib.parse.quote(query)}"
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
    if _is_kr_ticker(ticker):
        return _fetch_pykrx_ohlcv(ticker, period)

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


_PYTH_BENCHMARKS_BASE_URL = "https://benchmarks.pyth.network/v1"
_PYTH_HERMES_BASE_URL = "https://hermes.pyth.network/v2"
_PYTH_PRICE_MAX_AGE_SECONDS = 180
_PYTH_CONFIDENCE_MAX_RATIO = 0.05
_LATEST_PRICE_CACHE_TTL_SECONDS = 15
_US_INTRADAY_QUOTE_MAX_AGE_SECONDS = 16 * 60 * 60


def _secret_or_env(*names: str) -> str:
    for name in names:
        for key in {name, name.upper(), name.lower()}:
            value = os.getenv(key, "")
            if value:
                return str(value).strip()
            try:
                value = st.secrets.get(key, "")
                if value:
                    return str(value).strip()
            except Exception:
                pass
    return ""


def _is_recent_epoch(ts, max_age: int = _US_INTRADAY_QUOTE_MAX_AGE_SECONDS) -> bool:
    try:
        epoch = int(float(ts))
    except Exception:
        return False
    age = time.time() - epoch
    return -300 <= age <= max_age


def _parse_epoch(value) -> int:
    if value in (None, ""):
        return 0
    try:
        text = str(value).strip()
        if re.fullmatch(r"\d{13,}", text):
            return int(float(text) / 1000)
        if re.fullmatch(r"\d{10}", text):
            return int(text)
        ts = pd.to_datetime(text, utc=True, errors="coerce")
        if pd.isna(ts):
            return 0
        return int(ts.timestamp())
    except Exception:
        return 0


def _latest_recent_close_from_series(series, max_age: int = _US_INTRADAY_QUOTE_MAX_AGE_SECONDS) -> float:
    if isinstance(series, pd.DataFrame):
        if series.empty:
            return 0.0
        series = series.iloc[:, 0]
    if series is None or series.empty:
        return 0.0
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return 0.0
    try:
        idx = values.index[-1]
        ts = pd.to_datetime(idx, utc=True, errors="coerce")
        if pd.isna(ts) or not _is_recent_epoch(int(ts.timestamp()), max_age=max_age):
            return 0.0
    except Exception:
        return 0.0
    return float(values.iloc[-1])


def _pyth_headers() -> dict:
    headers = dict(_YQ_HEADERS)
    headers["Referer"] = "https://app.pyth.network/"
    token = os.getenv("PYTH_API_KEY") or os.getenv("PYTH_HERMES_API_KEY")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _looks_like_us_equity_ticker(ticker: str) -> bool:
    t = normalize_price_lookup_key(ticker)
    if not t or _is_kr_ticker(t):
        return False
    if any(marker in t for marker in ("=", "^", "/")) or t.endswith("-USD"):
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", t))


def _pyth_ticker_variants(ticker: str) -> set[str]:
    t = normalize_price_lookup_key(ticker)
    variants = {t, t.replace("-", "."), t.replace(".", "-")}
    if t.endswith(".US"):
        base = t[:-3]
        variants.update({base, base.replace("-", "."), base.replace(".", "-")})
    return {v for v in variants if v}


def _pyth_symbol_matches_ticker(feed: dict, variants: set[str]) -> bool:
    attrs = feed.get("attributes") or {}
    symbol_values = [
        attrs.get("base"),
        attrs.get("cms_symbol"),
        attrs.get("cqs_symbol"),
        attrs.get("nasdaq_symbol"),
    ]
    display_symbol = str(attrs.get("display_symbol") or "")
    if "/" in display_symbol:
        symbol_values.append(display_symbol.split("/", 1)[0])

    normalized = {
        normalize_price_lookup_key(v)
        for v in symbol_values
        if str(v or "").strip()
    }
    normalized |= {v.replace("-", ".") for v in normalized}
    normalized |= {v.replace(".", "-") for v in normalized}
    return bool(normalized & variants)


def _pyth_session_rank(feed: dict) -> int:
    attrs = feed.get("attributes") or {}
    text = f"{attrs.get('symbol', '')} {attrs.get('display_symbol', '')}".upper()
    if ".ON" in text or "OVERNIGHT" in text:
        return 0
    if ".PRE" in text or "PRE MARKET" in text:
        return 1
    if ".POST" in text or "POST MARKET" in text:
        return 2
    return 3


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_pyth_us_feed_candidates(ticker: str) -> list:
    if not _looks_like_us_equity_ticker(ticker):
        return []

    queries: list[str] = []
    for q in _pyth_ticker_variants(ticker):
        if q not in queries:
            queries.append(q)

    feeds: list[dict] = []
    seen_ids: set[str] = set()
    for query in queries:
        try:
            params = urllib.parse.urlencode({"query": query, "asset_type": "equity"})
            url = f"{_PYTH_BENCHMARKS_BASE_URL}/price_feeds/?{params}"
            req = urllib.request.Request(url, headers=_pyth_headers())
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read())
            if not isinstance(data, list):
                continue
            for feed in data:
                feed_id = str((feed or {}).get("id") or "").lower().removeprefix("0x")
                if not feed_id or feed_id in seen_ids:
                    continue
                seen_ids.add(feed_id)
                feeds.append(feed)
        except Exception:
            continue
    return feeds


def _find_pyth_active_us_feed(ticker: str) -> dict:
    variants = _pyth_ticker_variants(ticker)
    matches = []
    for feed in _fetch_pyth_us_feed_candidates(ticker):
        if not _pyth_symbol_matches_ticker(feed, variants):
            continue
        market_hours = feed.get("market_hours") or {}
        if market_hours.get("is_open") is True:
            matches.append(feed)
    if not matches:
        return {}
    matches.sort(key=_pyth_session_rank)
    return matches[0]


def _parse_pyth_price(price_obj: dict) -> float:
    try:
        raw_price = float(price_obj.get("price"))
        expo = int(price_obj.get("expo", 0))
        price = raw_price * (10 ** expo)
        if price <= 0:
            return 0.0

        publish_time = int(price_obj.get("publish_time") or 0)
        if publish_time:
            age = time.time() - publish_time
            if age > _PYTH_PRICE_MAX_AGE_SECONDS or age < -300:
                return 0.0

        raw_conf = price_obj.get("conf")
        if raw_conf is not None:
            conf = abs(float(raw_conf)) * (10 ** expo)
            if conf > 0 and (conf / price) > _PYTH_CONFIDENCE_MAX_RATIO:
                return 0.0
        return float(price)
    except Exception:
        return 0.0


def _fetch_pyth_prices_by_feed_id(feed_ids: list[str]) -> dict:
    clean_ids = []
    for feed_id in feed_ids:
        fid = str(feed_id or "").strip().lower().removeprefix("0x")
        if re.fullmatch(r"[0-9a-f]{64}", fid) and fid not in clean_ids:
            clean_ids.append(fid)
    if not clean_ids:
        return {}

    try:
        params = urllib.parse.urlencode([("ids[]", f"0x{fid}") for fid in clean_ids])
        url = f"{_PYTH_HERMES_BASE_URL}/updates/price/latest?{params}"
        req = urllib.request.Request(url, headers=_pyth_headers())
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        out = {}
        for item in data.get("parsed") or []:
            feed_id = str((item or {}).get("id") or "").lower().removeprefix("0x")
            price = _parse_pyth_price((item or {}).get("price") or {})
            if feed_id and price > 0:
                out[feed_id] = price
        return out
    except Exception:
        return {}


def _fetch_pyth_us_live_prices_batch(tickers: list) -> dict:
    feed_by_ticker = {}
    for ticker in tickers or []:
        feed = _find_pyth_active_us_feed(ticker)
        feed_id = str((feed or {}).get("id") or "").lower().removeprefix("0x")
        if feed_id:
            feed_by_ticker[normalize_price_lookup_key(ticker)] = feed_id

    id_to_price = _fetch_pyth_prices_by_feed_id(list(feed_by_ticker.values()))
    return {
        ticker_key: id_to_price[feed_id]
        for ticker_key, feed_id in feed_by_ticker.items()
        if feed_id in id_to_price
    }


def _fetch_pyth_us_live_price(ticker: str) -> float:
    prices = _fetch_pyth_us_live_prices_batch([ticker])
    try:
        return float(prices.get(normalize_price_lookup_key(ticker), 0.0) or 0.0)
    except Exception:
        return 0.0


def _fetch_configured_us_quote_price(ticker: str) -> float:
    t = normalize_price_lookup_key(ticker)
    if not _looks_like_us_equity_ticker(t):
        return 0.0

    endpoints = []
    fmp_key = _secret_or_env("FMP_API_KEY", "fmp_api_key")
    if fmp_key:
        endpoints.append((
            f"https://financialmodelingprep.com/api/v3/quote-short/{urllib.parse.quote(t)}?apikey={urllib.parse.quote(fmp_key)}",
            lambda data: (data[0] if isinstance(data, list) and data else data or {}).get("price"),
        ))
        endpoints.append((
            f"https://financialmodelingprep.com/stable/quote-short?symbol={urllib.parse.quote(t)}&apikey={urllib.parse.quote(fmp_key)}",
            lambda data: (data[0] if isinstance(data, list) and data else data or {}).get("price"),
        ))

    finnhub_key = _secret_or_env("FINNHUB_API_KEY", "finnhub_api_key")
    if finnhub_key:
        endpoints.append((
            f"https://finnhub.io/api/v1/quote?symbol={urllib.parse.quote(t)}&token={urllib.parse.quote(finnhub_key)}",
            lambda data: (data or {}).get("c"),
        ))

    twelve_key = _secret_or_env("TWELVEDATA_API_KEY", "TWELVE_DATA_API_KEY", "twelvedata_api_key")
    if twelve_key:
        endpoints.append((
            f"https://api.twelvedata.com/price?symbol={urllib.parse.quote(t)}&apikey={urllib.parse.quote(twelve_key)}",
            lambda data: (data or {}).get("price"),
        ))

    av_key = _secret_or_env("AV_API_KEY", "ALPHAVANTAGE_API_KEY", "alpha_vantage_api_key")
    if av_key:
        endpoints.append((
            f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={urllib.parse.quote(t)}&apikey={urllib.parse.quote(av_key)}",
            lambda data: ((data or {}).get("Global Quote") or {}).get("05. price"),
        ))

    for url, extractor in endpoints:
        try:
            req = urllib.request.Request(url, headers=_YQ_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            price = float(str(extractor(data)).replace(",", ""))
            if price > 0:
                return price
        except Exception:
            continue
    return 0.0


def _fetch_robinhood_us_quote(ticker: str) -> float:
    t = normalize_price_lookup_key(ticker)
    if not _looks_like_us_equity_ticker(t):
        return 0.0
    try:
        url = f"https://api.robinhood.com/marketdata/quotes/{urllib.parse.quote(t)}/"
        headers = dict(_YQ_HEADERS)
        headers["Referer"] = "https://robinhood.com/"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        candidates = (
            ("last_non_reg_trade_price", "venue_last_non_reg_trade_time"),
            ("last_extended_hours_trade_price", "venue_last_non_reg_trade_time"),
            ("ask_price", "venue_ask_time"),
            ("bid_price", "venue_bid_time"),
            ("last_trade_price", "venue_last_trade_time"),
        )
        for price_key, time_key in candidates:
            price = data.get(price_key)
            ts = _parse_epoch(data.get(time_key))
            try:
                price = float(price)
            except Exception:
                price = 0.0
            if price > 0 and ts and _is_recent_epoch(ts):
                return price
    except Exception:
        pass
    return 0.0


def _fetch_yahoo_overnight_page_price(ticker: str) -> float:
    t = normalize_price_lookup_key(ticker)
    if not _looks_like_us_equity_ticker(t):
        return 0.0
    try:
        url = f"https://finance.yahoo.com/quote/{urllib.parse.quote(t)}/"
        headers = dict(_YQ_HEADERS)
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="ignore")

        symbol = re.escape(t)
        match = re.search(
            rf'\\"symbol\\":\\"{symbol}\\".*?\\"overnightMarketPrice\\":\{{\\"raw\\":([0-9.]+).*?\\"overnightMarketTime\\":\{{\\"raw\\":([0-9]+)',
            text,
            flags=re.DOTALL,
        )
        if not match:
            match = re.search(
                rf'\\"overnightMarketPrice\\":\{{\\"raw\\":([0-9.]+).*?\\"symbol\\":\\"{symbol}\\".*?\\"overnightMarketTime\\":\{{\\"raw\\":([0-9]+)',
                text,
                flags=re.DOTALL,
            )
        if not match:
            return 0.0
        price = float(match.group(1))
        ts = int(match.group(2))
        if price > 0 and _is_recent_epoch(ts):
            return price
    except Exception:
        pass
    return 0.0


def _last_candle_close(result: dict) -> float:
    """
    Yahoo v8 chart 응답에서 가장 최근 1분봉 Close 값을 꺼냅니다.
    meta.regularMarketPrice 는 종종 이전 세션 종가를 캐싱하므로 캔들이 더 정확합니다.
    """
    try:
        closes = result["indicators"]["quote"][0].get("close") or []
        # null(None) 제거 후 마지막 값
        stamps = result.get("timestamp") or []
        valid = []
        for idx, close in enumerate(closes):
            if close is None or float(close) <= 0:
                continue
            ts = stamps[idx] if idx < len(stamps) else 0
            if stamps and not _is_recent_epoch(ts):
                continue
            valid.append(close)
        if valid:
            return float(valid[-1])
    except Exception:
        pass
    return 0.0


def _fetch_yahoo_chart(ticker: str, interval: str, range_: str) -> tuple[float, dict]:
    """
    Yahoo v8 chart API 단일 호출 — (캔들 마지막 Close, meta 딕셔너리) 반환.
    실패 시 (0.0, {}) 반환. 401/Rate 에러면 (−1.0, {}) 로 블록 신호 전달.
    """
    global _YAHOO_BLOCK_UNTIL
    for host in ("query1", "query2"):
        try:
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                f"{urllib.parse.quote(ticker)}"
                f"?interval={interval}&range={range_}&includePrePost=true"
            )
            req = urllib.request.Request(url, headers=_YQ_HEADERS)
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read())
            results = (data.get("chart") or {}).get("result") or []
            if not results:
                continue
            result = results[0]
            meta = result.get("meta", {})
            return _last_candle_close(result), meta
        except Exception as exc:
            message = str(exc)
            if "401" in message or "Too Many Requests" in message or "Rate" in message:
                return -1.0, {}
            continue
    return 0.0, {}


def _meta_best_price(meta: dict) -> float:
    """meta 필드에서 timestamp 기준 가장 최근 가격을 뽑는다."""
    best_price, best_ts = 0.0, 0
    for price_key, time_key in (
        ("postMarketPrice",    "postMarketTime"),
        ("preMarketPrice",     "preMarketTime"),
        ("regularMarketPrice", "regularMarketTime"),
    ):
        val = meta.get(price_key)
        ts = meta.get(time_key) or 0
        try:
            ts = int(ts)
        except Exception:
            ts = 0
        if val and float(val) > 0 and ts > best_ts and _is_recent_epoch(ts):
            best_price, best_ts = float(val), ts
    if best_price > 0:
        return best_price
    for key in ("regularMarketPrice", "currentPrice", "chartPreviousClose"):
        val = meta.get(key)
        if val and float(val) > 0:
            return float(val)
    return 0.0


def _fetch_yahoo_quote(ticker: str) -> float:
    """
    Yahoo Finance chart API 직접 호출 — yfinance SQLite lock 없음.

    우선순위:
      1) 1분봉(range=1d) 캔들의 마지막 Close  ← 진짜 실시간 체결가
      2) 5분봉(range=2d) 캔들의 마지막 Close  ← 1분봉 데이터 없을 때 재시도
      3) meta.postMarket/preMarket/regularMarketPrice (timestamp 최신 기준)
      4) meta.currentPrice / chartPreviousClose

    query1 실패 시 query2 로 재시도. 401/Rate 에러 시 블록 설정.
    """
    global _YAHOO_BLOCK_UNTIL
    now_ts = pd.Timestamp.now().timestamp()
    if (not _force_live_price_refresh_active()) and now_ts < _YAHOO_BLOCK_UNTIL:
        return 0.0

    # 1) 1분봉 시도
    candle_price, meta = _fetch_yahoo_chart(ticker, "1m", "1d")
    if candle_price == -1.0:
        with _YAHOO_BLOCK_LOCK:
            _YAHOO_BLOCK_UNTIL = max(
                _YAHOO_BLOCK_UNTIL,
                pd.Timestamp.now().timestamp() + _YAHOO_BLOCK_SECONDS,
            )
        return 0.0
    if candle_price > 0:
        return candle_price

    # 2) 1분봉 캔들 없음 → 5분봉(2일치)으로 재시도 (prepost 포함, 추가 지연 없음)
    candle_5m, meta_5m = _fetch_yahoo_chart(ticker, "5m", "2d")
    if candle_5m == -1.0:
        with _YAHOO_BLOCK_LOCK:
            _YAHOO_BLOCK_UNTIL = max(
                _YAHOO_BLOCK_UNTIL,
                pd.Timestamp.now().timestamp() + _YAHOO_BLOCK_SECONDS,
            )
        return 0.0
    if candle_5m > 0:
        return candle_5m

    # 3/4) 캔들 데이터 없음 → meta 필드 폴백 (1분봉 meta 우선, 없으면 5분봉 meta)
    price = _meta_best_price(meta) or _meta_best_price(meta_5m)
    return price


def _fetch_yf_fast_info_price(ticker: str) -> float:
    """
    yf.Ticker.fast_info 폴백.

    일부 미국 종목은 fast_info.last_price/currentPrice가 프리마켓 체결가보다
    이전 정규가로 남는 경우가 있어 Yahoo chart 1분봉 뒤에서만 사용한다.
    _YF_LOCK 으로 SQLite tz 캐시 동시 쓰기 방지.
    """
    try:
        with _YF_LOCK:
            fi = yf.Ticker(ticker).fast_info
        # fast_info에는 timestamp가 없어 세션 판정이 불안정하다. 최종 폴백용.
        for attr in ("last_price", "post_market_price", "pre_market_price", "regular_market_price"):
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
        price = _latest_recent_close_from_series(extract_download_close_series(df, ticker))
        return price if price > 0 else 0.0
    except Exception:
        return 0.0


def _fetch_price_uncached(ticker: str) -> float:
    """
    캐시 없는 현재가 조회 로직. load_latest_price 와 clear_latest_price_cache 가 공유.

    한국 주식 (.KS/.KQ):
        1차 - 네이버 모바일 API  (장중 실시간에 가까움)
        2차 - pykrx 최근 종가
        3차 - 실패 시 0 반환 (yfinance 지연/오류 로그 방지)

    미국·기타 주식:
        1차 - Pyth 실시간 피드  (지원 종목)
        2차 - Yahoo Finance chart 1분봉 + prepost
        3차 - yfinance 1분봉 + prepost
        4차 - yfinance 5분봉 + prepost
        5차 - yf.fast_info 폴백
        6차 - yfinance 일봉 폴백
    """
    if _is_kr_ticker(ticker):
        price = _fetch_naver_realtime_price(ticker)
        if price > 0:
            return price
        price = _fetch_naver_price(ticker)
        if price > 0:
            return price
        if _force_live_price_refresh_active():
            price = _fetch_yf_download_price(ticker, interval="1m", prepost=True)
            if price > 0:
                return price
            price = _fetch_yf_download_price(ticker, interval="5m", prepost=True)
            if price > 0:
                return price
        price = _fetch_pykrx_latest_close(ticker)
        if price > 0:
            return price
        return 0.0
    else:
        price = _fetch_yahoo_overnight_page_price(ticker)
        if price > 0:
            return price
        price = _fetch_configured_us_quote_price(ticker)
        if price > 0:
            return price
        price = _fetch_pyth_us_live_price(ticker)
        if price > 0:
            return price
        # Yahoo Finance 직접 API (SQLite lock 없음, 가장 신뢰성 높음)
        price = _fetch_robinhood_us_quote(ticker)
        if price > 0:
            return price
        price = _fetch_yahoo_quote(ticker)
        if price > 0:
            return price
        price = _fetch_yf_download_price(ticker, interval="1m", prepost=True)
        if price > 0:
            return price
        price = _fetch_yf_download_price(ticker, interval="5m", prepost=True)
        if price > 0:
            return price
        price = _fetch_yf_fast_info_price(ticker)
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


@st.cache_data(ttl=_LATEST_PRICE_CACHE_TTL_SECONDS, show_spinner=False)
def _load_latest_price_cached(ticker: str) -> float:
    """Short TTL cache wrapper. Only successful prices (>0) are cached."""
    return _fetch_price_uncached(ticker)


def load_latest_price(ticker: str) -> float:
    """
    단일 종목 현재가 조회 (공개 API, 짧은 TTL).
    캐시 결과가 0(조회 실패)이면 캐시를 거치지 않고 즉시 재시도.
    → '실패 결과 캐싱' 문제 방지.
    """
    price = _load_latest_price_cached(ticker)
    if price > 0:
        return price
    # 캐시된 0: 이 티커만 우회하고 바로 재시도 (다른 티커 캐시 보존)
    return _fetch_price_uncached(ticker)


@st.cache_data(ttl=_LATEST_PRICE_CACHE_TTL_SECONDS, show_spinner=False)
def load_latest_prices_batch(tickers) -> dict:
    """
    여러 종목 현재가 일괄 조회. 짧은 TTL.

    한국 (.KS/.KQ):  네이버 bulk API → 개별 네이버 → pykrx 최근 종가
    미국/기타:       Pyth → Yahoo chart/prepost → yfinance 분봉 → fast_info → 일봉 폴백
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

        kr_still_missing = [t for t in kr_tickers if normalize_price_lookup_key(t) not in prices]
        if kr_still_missing and _force_live_price_refresh_active():
            try:
                with _YF_LOCK:
                    data = yf.download(
                        kr_still_missing if len(kr_still_missing) > 1 else kr_still_missing[0],
                        period="1d", interval="1m", prepost=True,
                        progress=False, group_by="ticker", threads=False, auto_adjust=False,
                    )
                if data is not None and not data.empty:
                    for t in kr_still_missing:
                        p = get_latest_close_from_series(extract_download_close_series(data, t))
                        if p > 0:
                            prices[normalize_price_lookup_key(t)] = p
            except Exception:
                pass

        # 그래도 없으면 pykrx 최근 종가로 보완한다.
        kr_still_missing = [t for t in kr_tickers if normalize_price_lookup_key(t) not in prices]
        for t in kr_still_missing:
            p = _fetch_pykrx_latest_close(t)
            if p > 0:
                prices[normalize_price_lookup_key(t)] = p

    # ── 미국/기타: Pyth → Yahoo chart → yfinance 분봉 → fast_info 폴백 ──
    if us_tickers:
        for t in us_tickers:
            p = _fetch_yahoo_overnight_page_price(t)
            if p > 0:
                prices[normalize_price_lookup_key(t)] = p

        us_live_needed = [t for t in us_tickers if normalize_price_lookup_key(t) not in prices]
        prices.update(_fetch_pyth_us_live_prices_batch(us_live_needed))

        # 1차: Yahoo Finance 직접 API (캔들 기반 실시간가, SQLite lock 없음)
        us_yahoo_needed = [t for t in us_tickers if normalize_price_lookup_key(t) not in prices]
        for t in us_yahoo_needed:
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
    all_missing = [
        t for t in unique_tickers
        if normalize_price_lookup_key(t) not in prices and not _is_kr_ticker(t)
    ]
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
