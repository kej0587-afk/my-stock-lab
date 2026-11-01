"""Source-session checks for reusing radar data; no prices, scores or I/O."""

import re

import pandas as pd

from stock_lab_core.data_freshness import session_date
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _market(ticker):
    symbol = ticker.strip().upper() if isinstance(ticker, str) else ""
    if symbol.endswith((".KS", ".KQ")):
        return "한국"
    return "미국" if re.fullmatch(r"[A-Z][A-Z0-9-]*", symbol) and not symbol.endswith("-USD") else ""


def source_sessions(frame):
    """Keep exchange-day labels; crypto/foreign exchanges are not US sessions."""
    result = {}
    if not isinstance(frame, pd.DataFrame) or not {"Ticker", "기준일"}.issubset(frame.columns):
        return result
    for ticker, value in frame[["Ticker", "기준일"]].itertuples(index=False, name=None):
        market = _market(ticker)
        day = session_date(value)
        if market and day:
            result[market] = max(result.get(market, ""), day)
    return result


def can_reuse_theme_snapshot(snapshot, flow_df):
    """An old theme must not inherit the timestamp of newly refreshed ETFs."""
    theme = snapshot.get("theme_flow_df") if isinstance(snapshot, dict) else None
    reference = source_sessions(flow_df)
    if not isinstance(theme, pd.DataFrame) or not {"Ticker", "기준일"}.issubset(theme.columns) or not reference:
        return False
    eligible = theme
    if "돈흐름점수" in eligible:
        eligible = eligible.loc[pd.to_numeric(eligible["돈흐름점수"], errors="coerce").notna()]
    checked = 0
    for ticker, value in eligible[["Ticker", "기준일"]].itertuples(index=False, name=None):
        market = _market(ticker)
        if not market:
            continue
        checked += 1
        if not session_date(value) or session_date(value) != reference.get(market):
            return False
    return checked > 0


def flow_source_date_rows(snapshot):
    rows = []
    for label, key in (("ETF·섹터", "flow_df"), ("테마·개별주", "theme_flow_df")):
        frame = snapshot.get(key) if isinstance(snapshot, dict) else None
        for market, day in source_sessions(frame).items():
            values = [session_date(value) for ticker, value in frame[["Ticker", "기준일"]].itertuples(index=False, name=None)
                      if _market(ticker) == market]
            known = sorted({value for value in values if value})
            rows.append({"원자료": label, "시장": market,
                "가격 기준일": day if len(known) == 1 else f"{known[0]} ~ {known[-1]}",
                "이전일 자료": sum(bool(value) and value < day for value in values),
                "기준일 미확인": sum(not value for value in values)})
    return rows
