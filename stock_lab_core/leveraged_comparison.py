"""Completed-session inputs for leveraged watch rows; no live quote substitution."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from stock_lab_core.formatters import format_currency
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_eventstudy import _exchange_schedule


VERSION = "completed-session-v1"
PRODUCTS = {"SOXL": "SOXL", "RAM": "RAM", "BITX": "BITX",
            "NASDAQ100_2X_KR": "418660.KS"}
HORIZONS = (("1D", "_1d", 1), ("1W", "_1w", 5), ("1M", "_1m", 21))


def exact_profile(profile, ticker):
    # Several other products share these watchlists, not their mandates.
    return profile if PRODUCTS.get(profile) == str(ticker).strip().upper() else ""


def comparison_entries(watch, profile):
    rows = list(watch)
    product = PRODUCTS.get(profile)
    if product and not any(row[0] == product for row in rows):
        rows.insert(0, (product, "비교 상품", product))
    return rows


def comparison_context(profile, *, now=None, schedule_loader=_exchange_schedule):
    if profile not in PRODUCTS:
        return None
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if clock.tzinfo is None:
        raise ValueError("comparison clock must include timezone")
    clock = clock.tz_convert("UTC")
    context = {"clock": clock, "sessions": {}, "errors": {}}
    for market in ("US", "KR"):
        try:
            frame = schedule_loader(market, (clock - pd.Timedelta(days=90)).date().isoformat(),
                                    clock.date().isoformat())
            closes = pd.to_datetime(frame["market_close"], utc=True)
            # A grace period prevents a just-closing, unfinished daily bar entering
            # the comparison. Calendar closes also handle DST and early closes.
            closed = frame.loc[closes + pd.Timedelta(minutes=15) <= clock].copy()
            closed["market_close"] = closes.loc[closed.index]
            if closed.empty:
                raise ValueError("no completed sessions")
            context["sessions"][market] = closed.sort_index()
        except (ImportError, KeyError, ValueError, OSError) as exc:
            context["errors"][market] = type(exc).__name__
    return context


def _stamp(value):
    return pd.Timestamp(value).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M KST")


def completed_comparison_row(entry, history, *, context, pct_text, judge):
    ticker, role, label = entry
    market = "CRYPTO" if ticker.endswith("-USD") else "KR" if ticker.endswith((".KS", ".KQ")) else "US"
    row = {"구분": role, "확인축": label, "Ticker": ticker, "현재가": "-",
           "_comparison_version": VERSION, "_comparison_market": market,
           "_comparison_windows": {}, "_comparison_asof": context["clock"].isoformat()}
    returns = [np.nan] * 3
    windows = row["_comparison_windows"]
    notes = []
    sessions = context["sessions"].get(market)
    row["비교 기준"] = {"US": "미국 정규장 종가", "KR": "한국 정규장 종가 · 미국과 시각 다름",
                        "CRYPTO": "UTC 일봉 · 미국 종가 동시각 미확보"}[market]
    row["종료 시각"] = "미연결"
    if market == "CRYPTO":
        notes.append("24시간 현물 일봉을 미국 ETF 정규장 수익률과 혼합하지 않음")
    elif sessions is None:
        notes.append("거래소 달력 미연결: " + context["errors"].get(market, "unknown"))
    else:
        end_day = sessions.index[-1].strftime("%Y-%m-%d")
        row["종료 시각"] = _stamp(sessions["market_close"].iloc[-1])
        close = pd.Series(dtype=float)
        if isinstance(history, pd.DataFrame) and "Close" in history and isinstance(history.index, pd.DatetimeIndex):
            # Daily labels are exchange dates, not instants to shift across zones.
            close = pd.Series(pd.to_numeric(history["Close"], errors="coerce").to_numpy(dtype=float, na_value=np.nan),
                              index=history.index.strftime("%Y-%m-%d"))
            close = close.loc[~close.index.duplicated(keep=False)]
            pending = history.attrs.get("report_close_pending_date")
            close = close.drop(pending, errors="ignore") if pending else close
        end = close.get(end_day, np.nan)
        if np.isfinite(end) and end > 0:
            row["현재가"] = format_currency(end, ticker)
        for i, (public, _, bars) in enumerate(HORIZONS):
            if len(sessions) <= bars:
                notes.append(public + " 달력 부족")
                continue
            start_day = sessions.index[-bars - 1].strftime("%Y-%m-%d")
            windows[public] = {"start": _stamp(sessions["market_close"].iloc[-bars - 1]),
                               "end": row["종료 시각"], "start_day": start_day, "end_day": end_day}
            base = close.get(start_day, np.nan)
            if np.isfinite(end) and np.isfinite(base) and end > 0 and base > 0:
                returns[i] = (end / base - 1) * 100
            else:
                notes.append(f"{public} 종가 미확보({start_day}~{end_day})")
    for (public, internal, _), value in zip(HORIZONS, returns):
        row[public], row[internal] = pct_text(value), value
    row["판정"] = judge(*returns)
    row["자료 상태"] = " / ".join(notes) if notes else "동일 시장 완료 세션 연결"
    return row


register_loaded_source(__name__, __file__)
