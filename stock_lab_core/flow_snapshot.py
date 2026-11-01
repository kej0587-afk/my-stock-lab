"""Source-session checks for reusing radar data; no prices, scores or I/O."""

import re

import pandas as pd

from stock_lab_core.data_freshness import session_date
from stock_lab_core.flow_symbols import flow_listing_event, resolve_flow_symbol
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
    active = frame.loc[~frame.get("상장상태", pd.Series(index=frame.index, dtype=object)).eq("거래종료")]
    for ticker, value in active[["Ticker", "기준일"]].itertuples(index=False, name=None):
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
    for row in theme.to_dict("records"):
        ticker = row["Ticker"]
        if resolve_flow_symbol(ticker) != ticker:
            return False
        if flow_listing_event(ticker) and row.get("상장상태") != "거래종료":
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
        if not isinstance(frame, pd.DataFrame) or not {"Ticker", "기준일"}.issubset(frame):
            continue
        sessions = source_sessions(frame)
        for market in dict.fromkeys(frame["Ticker"].map(_market)):
            if not market:
                continue
            day = sessions.get(market, "")
            market_frame = frame.loc[frame["Ticker"].map(_market).eq(market)]
            ended = market_frame.get("상장상태", pd.Series(index=market_frame.index, dtype=object)).eq("거래종료")
            values = [session_date(value) for value in market_frame.loc[~ended, "기준일"]]
            known = sorted({value for value in values if value})
            rows.append({"원자료": label, "시장": market,
                "가격 기준일": day if len(known) == 1 else (f"{known[0]} ~ {known[-1]}" if known else "미확인"),
                "이전일 자료": sum(bool(value) and value < day for value in values),
                "기준일 미확인": sum(not value for value in values), "거래종료": int(ended.sum())})
    return rows


def flow_source_issue_rows(snapshot):
    """Expose missing-price and corporate-action evidence without normal scores."""
    rows = []
    for key in ("flow_df", "theme_flow_df"):
        frame = snapshot.get(key) if isinstance(snapshot, dict) else None
        if not isinstance(frame, pd.DataFrame) or not {"Ticker", "돈흐름점수"}.issubset(frame):
            continue
        for row in frame.to_dict("records"):
            ended = row.get("상장상태") == "거래종료"
            if not ended and pd.notna(row.get("돈흐름점수")):
                continue
            rows.append({"종목": row.get("종목명", row.get("ETF 이름", "")), "Ticker": row["Ticker"],
                "자료상태": "거래종료" if ended else "가격부족", "마지막거래일": session_date(row.get("마지막거래일")) or "",
                "사유": row.get("원자료사유") if isinstance(row.get("원자료사유"), str) and row.get("원자료사유")
                        else "조회 불가 또는 계산에 필요한 일봉 부족",
                "공식출처": row.get("공식출처", "") if ended else ""})
    return list({(row["Ticker"], row["자료상태"]): row for row in rows}.values())
