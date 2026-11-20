"""Report-only KRX regular closes, never after-market final trades or model bars."""

from concurrent.futures import ThreadPoolExecutor
import math
import re

import pandas as pd
import requests

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.performance import submit_with_context
from stock_lab_core.result_cache import cache_result

register_loaded_source(__name__, __file__)
SOURCE = "Npay KRX 정규장 종가(regularMarketClosingPrice)"


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


@cache_result(ttl=900, failure_ttl=30, is_success=lambda r: bool(r.get("items")), trace_name="kr_regular_history")
def load_regular_payload(ticker):
    code = str(ticker).split(".")[0]
    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        return {"reason": "invalid_symbol"}
    url = f"https://stock.naver.com/api/stockSecurity/items/v2/domestic/{code}/daily-prices/paged"
    try:
        with requests.get(url, params={"index": 0, "size": 100}, timeout=(2, 5),
                          headers={"User-Agent": "Mozilla/5.0"}) as response:
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            return {"reason": "daily_schema_unavailable"}
        return payload
    except (requests.RequestException, ValueError) as exc:
        return {"reason": type(exc).__name__}


def regular_close_frame(payload, now, *, schedule=None):
    """Preserve missing rows; do not splice final-price OHLC/volume into closes."""
    payload = payload if isinstance(payload, dict) else {"reason": "daily_schema_unavailable"}
    now = pd.Timestamp(now)
    now = now.tz_localize("Asia/Seoul") if now.tzinfo is None else now.tz_convert("Asia/Seoul")
    rows = []
    items = payload.get("items")
    for row in items if isinstance(items, list) else ():
        if not isinstance(row, dict):
            continue
        day = str(row.get("tradingDateKst", ""))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        close = _number(row.get("regularMarketClosingPrice"))
        # basePrice and change are the provider's regular-session endpoints.
        base, change = _number(row.get("basePrice")), _number(row.get("regularMarketChangePrice"))
        valid = close is not None and close > 0
        if valid and base is not None and change is not None:
            valid = base > 0 and math.isclose(close - base, change, abs_tol=.011, rel_tol=1e-6)
        rows.append((day, close if valid else float("nan"), base))
    frame = pd.DataFrame(rows, columns=["Date", "Close", "RegularBase"])
    frame.index = pd.to_datetime(frame.pop("Date"), errors="coerce")
    frame = frame.loc[~frame.index.isna()].sort_index()
    # Duplicate/conflicting days are not silently resolved using source order.
    frame = frame.loc[~frame.index.duplicated(keep=False)]
    try:
        if schedule is None and not frame.empty:
            schedule = _exchange_schedule("KR", str(frame.index[0].date()), str(now.date()))
        clocks = schedule["market_close"] if schedule is not None else pd.Series(dtype=object)
        clocks = {pd.Timestamp(day).date(): pd.Timestamp(at) for day, at in clocks.items()}
        completed = sorted(day for day, at in clocks.items() if at + pd.Timedelta(minutes=15) <= now)
        eligible = [day.date() in clocks and clocks[day.date()] + pd.Timedelta(minutes=15) <= now
                    for day in frame.index]
        frame = frame.loc[eligible]
    except (KeyError, TypeError, ValueError, ImportError):
        frame = frame.iloc[0:0]
        completed = []
    frame.attrs.update(source=SOURCE, price_basis="KRX_regular", report_close_verification="explicit_regular_field",
                       basis_reason=payload.get("reason", "regular_field_or_completed_session_unavailable") if frame.empty else "",
                       report_close_basis_note="정규장 종가끼리 비교 · 애프터마켓 최종가 제외")
    frame.attrs.update(report_regular_expected=str(completed[-1]) if completed else "",
                       report_regular_previous=str(completed[-2]) if len(completed) > 1 else "")
    return frame


def align_regular_frames(frames, tickers, now, *, loader=load_regular_payload):
    """Only replace report copies, with bounded workers and cached transport."""
    result = dict(frames)
    symbols = sorted({t for t in tickers if str(t).endswith((".KS", ".KQ"))
                      and getattr(frames.get(t), "attrs", {}).get("price_basis") != "KRX_regular"})
    def collect(ticker):
        return ticker, regular_close_frame(loader(ticker), now)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [submit_with_context(pool, collect, ticker) for ticker in symbols]
        result.update(future.result() for future in futures)
    return result
