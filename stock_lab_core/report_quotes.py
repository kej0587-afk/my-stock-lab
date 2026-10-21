"""Timestamped report quotes. Never feed extended trading into decision bars."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import logging
import math
from urllib.parse import quote

import pandas as pd
import requests

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_session import NEW_YORK, KST, market_session_states
from stock_lab_core.result_cache import cache_result
from stock_lab_core.performance import timed_call

register_loaded_source(__name__, __file__)


class _QuoteScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.parts = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/json":
            self.parts = []

    def handle_data(self, data):
        if self.parts is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.parts is not None:
            self.scripts.append("".join(self.parts))
            self.parts = None


def raw_number(value):
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_us_quote_page(page, ticker):
    # Parse the embedded response as JSON; nearby symbols must not donate quotes.
    parser = _QuoteScripts()
    parser.feed(page)
    for script in parser.scripts:
        try:
            envelope = json.loads(script or "{}")
            if envelope.get("status") != 200:
                continue
            body = json.loads(envelope.get("body", "{}"))
            for row in (body.get("quoteResponse") or {}).get("result") or []:
                if isinstance(row, dict) and row.get("symbol") == ticker:
                    return row
        except (ValueError, TypeError, AttributeError):
            continue
    return {}


@cache_result(ttl=60, failure_ttl=15, is_success=bool)
def load_us_report_quote(ticker):
    try:
        response = requests.get(f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}/",
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        response.raise_for_status()
        result = parse_us_quote_page(response.text, ticker)
        if not result:
            logging.warning("Report quote %s: HTTP %s, embedded symbol quote missing", ticker, response.status_code)
        return result
    except (requests.RequestException, ValueError, TypeError) as exc:
        logging.warning("Report quote %s: %s", ticker, type(exc).__name__)
        return {}


@cache_result(ttl=30, failure_ttl=10, is_success=bool)
def load_kr_report_quotes(tickers=()):
    try:
        codes = sorted({ticker.split('.')[0] for ticker in tickers if ticker.endswith(('.KS', '.KQ'))})
        query = "SERVICE_INDEX:KOSPI,KOSDAQ" + ("|SERVICE_ITEM:" + ",".join(codes) if codes else "")
        response = requests.get("https://polling.finance.naver.com/api/realtime",
                                params={"query": query}, timeout=4)
        response.raise_for_status()
        return response.json().get("result") or {}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return {}


@timed_call("prices", "report_quote_snapshot")
def load_report_quotes(us_tickers, *, include_kr=False, kr_tickers=()):
    # Only held US symbols, once per report; no retry cascade or yfinance lock.
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {ticker: pool.submit(load_us_report_quote, ticker) for ticker in sorted(set(us_tickers))}
        kr = (load_kr_report_quotes(tuple(sorted(set(kr_tickers)))) if kr_tickers else load_kr_report_quotes()) if include_kr else {}
        us = {ticker: job.result() for ticker, job in pending.items()}
        return {"KR": kr, "US": us, "retrieved_at": datetime.now(timezone.utc).isoformat()}


def _epoch(value):
    value = raw_number(value)
    try:
        return pd.Timestamp(value, unit="s", tz="UTC") if value is not None else None
    except (ValueError, OverflowError):
        return None


def _previous_us_day(day):
    from stock_lab_core.prices import _us_equity_market_holidays
    day -= timedelta(days=1)
    while day.weekday() >= 5 or day in _us_equity_market_holidays(day.year):
        day -= timedelta(days=1)
    return day


def regular_quote_observation(quote_row, ticker, now):
    from stock_lab_core.prices import _us_equity_market_holidays
    if not isinstance(quote_row, dict):
        return {}
    local = pd.Timestamp(now).tz_convert(NEW_YORK)
    day = local.date()
    if local.hour * 60 + local.minute < 975 or day.weekday() >= 5 or day in _us_equity_market_holidays(day.year):
        day = _previous_us_day(day)
    at = _epoch(quote_row.get("regularMarketTime"))
    price, previous = (raw_number(quote_row.get(key)) for key in ("regularMarketPrice", "regularMarketPreviousClose"))
    if quote_row.get("symbol") != ticker or at is None or not price or not previous or min(price, previous) <= 0:
        return {}
    stamp = at.tz_convert(NEW_YORK)
    # A last trade near the regular close, never an extended-hours price.
    if stamp.date() != day or not 959 <= stamp.hour * 60 + stamp.minute <= 975 or at > pd.Timestamp(now):
        return {}
    return {"ticker": ticker, "date": day.isoformat(), "previous_date": _previous_us_day(day).isoformat(),
            "price": price, "previous_price": previous, "return": price / previous - 1,
            "as_of": at.isoformat(), "source": "Yahoo 정규장 시세(일봉 종가 누락 보완)"}


def repair_held_us_closes(frames, quotes, now):
    result = dict(frames)
    for ticker, quote_row in quotes.items():
        obs = regular_quote_observation(quote_row, ticker, now)
        old = frames.get(ticker)
        if not obs or old is None or old.empty:
            continue
        frame = old.copy(deep=True)
        frame.index = frame.index.tz_localize(None).normalize()
        previous = frame.loc[frame.index == pd.Timestamp(obs["previous_date"]), "Close"]
        if previous.empty or not math.isclose(float(previous.iloc[-1]), obs["previous_price"], rel_tol=1e-5):
            continue  # Split/adjustment mismatch: do not splice incompatible price bases.
        values = {col: raw_number(quote_row.get(key)) for col, key in
                  (("Open", "regularMarketOpen"), ("High", "regularMarketDayHigh"),
                   ("Low", "regularMarketDayLow"), ("Close", "regularMarketPrice"), ("Volume", "regularMarketVolume"))}
        if any(values[col] is None or values[col] <= 0 for col in ("Open", "High", "Low", "Close")):
            continue
        if not values["Low"] <= min(values["Open"], values["Close"]) <= max(values["Open"], values["Close"]) <= values["High"]:
            continue
        target = pd.Timestamp(obs["date"])
        if target in frame.index and pd.notna(frame.loc[target, "Close"]):
            continue
        for col, value in values.items():
            frame.loc[target, col] = value
        result[ticker] = frame.sort_index()
        result[ticker].attrs.update(source=obs["source"], quote_as_of=obs["as_of"])
    return result


def extended_quote_observation(quote_row, ticker, now):
    regular = regular_quote_observation(quote_row, ticker, now)
    if not regular:
        return {}
    found = []
    for field, label in (("overnight", "데이마켓(야간)"), ("pre", "프리마켓"), ("post", "애프터마켓")):
        at = _epoch(quote_row.get(field + "MarketTime"))
        price = raw_number(quote_row.get(field + "MarketPrice"))
        if at is None or not price or price <= 0 or not 0 <= (pd.Timestamp(now) - at).total_seconds() <= 1200:
            continue
        if at <= pd.Timestamp(regular["as_of"]):
            continue
        found.append({"ticker": ticker, "price": price, "return": price / regular["price"] - 1,
                      "date": at.tz_convert(NEW_YORK).date().isoformat(), "as_of": at.isoformat(),
                      "previous_date": regular["date"], "previous_price": regular["price"],
                      "kind": label, "source": "Yahoo 별도 세션 시세(증권사·거래장소별 차이 가능)"})
    return max(found, key=lambda row: row["as_of"]) if found else {}


def extended_quote_status(quote_row, ticker, now):
    """Explain rejection without persisting a raw provider payload or credentials."""
    if not quote_row:
        return "제공처 시세 응답 미수집/종목 시세 없음(HTTP·파싱 상세는 서버 로그)"
    if not regular_quote_observation(quote_row, ticker, now):
        return "비교 기준 정규장 종가·시각 검증 실패"
    if extended_quote_observation(quote_row, ticker, now):
        return "연결됨"
    times = [_epoch(quote_row.get(field + "MarketTime")) for field in ("overnight", "pre", "post")]
    times = [at for at in times if at is not None]
    if not times:
        return "제공처 데이마켓/시간외 시각 미제공"
    latest = max(times)
    age = (pd.Timestamp(now) - latest).total_seconds()
    stamp = latest.tz_convert(KST).strftime("%m/%d %H:%M KST")
    if age > 1200:
        return f"시간외 시세 지연: 마지막 {stamp}, {age / 60:.0f}분 경과(20분 초과)"
    return f"시간외 가격·비교 시각 검증 실패: 마지막 {stamp}"


def kr_index_observations(payload, now, *, tickers=()):
    if not isinstance(payload, dict):
        return {}
    state = market_session_states(now)["KR"]
    at = _epoch((raw_number(payload.get("time")) or 0) / 1000)
    if state["phase"] != "intraday" or at is None or not 0 <= (pd.Timestamp(now) - at).total_seconds() <= 120:
        return {}
    if at.tz_convert(KST).date().isoformat() != state["active_date"]:
        return {}
    result = {}
    by_code = {ticker.split('.')[0]: ticker for ticker in tickers if ticker.endswith(('.KS', '.KQ'))}
    for area in payload.get("areas") or []:
        if not isinstance(area, dict) or area.get("name") not in {"SERVICE_INDEX", "SERVICE_ITEM"}:
            continue
        index = area["name"] == "SERVICE_INDEX"
        for row in area.get("datas") or []:
            if not isinstance(row, dict):
                continue
            ticker = ({"KOSPI": "^KS11", "KOSDAQ": "^KQ11"} if index else by_code).get(row.get("cd"))
            price, change = raw_number(row.get("nv")), raw_number(row.get("cv"))
            if not ticker or not price or price <= 0 or change is None or row.get("ms") != "OPEN":
                continue
            sign = {"1": 1, "2": 1, "3": 0, "4": -1, "5": -1}.get(str(row.get("rf")))
            if sign is None:
                continue
            previous = price - abs(change) * sign
            if previous <= 0:
                continue
            supplied_previous = raw_number(row.get("pcv"))
            if supplied_previous is not None and abs(previous - supplied_previous) > .01:
                continue
            result[ticker] = {"ticker": ticker, "price": price / (100 if index else 1), "return": price / previous - 1,
                              "date": state["active_date"], "as_of": at.isoformat(),
                              "kind": "장중 진행·확정 아님", "source": "Naver 지수·보유종목(제공처 응답시각)"}
    return result
