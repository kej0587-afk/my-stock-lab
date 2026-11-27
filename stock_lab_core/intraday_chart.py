"""Quick price chart data: 1/5/30/60/120-minute and daily bars with user moving averages.

Display only. Nothing here feeds scores, decisions, gates or amounts.

Source: Yahoo Finance chart API through yfinance (regular session only, ``prepost=False``).
Yahoo has no 120-minute bar, so 120분 pairs consecutive 60-minute bars of the same session
(the session's last bar may be shorter, e.g. US 15:30-16:00, KR 15:00-15:30).
The last bar during a session is the provider's in-progress bar: its price and volume change
until it closes and is labelled 미확정. Missing data stays missing; nothing is filled or estimated.
"""

from __future__ import annotations

import math
import time

import pandas as pd

INTERVALS = ("1분", "5분", "30분", "60분", "120분", "일봉", "주봉", "월봉")

# period = what one request asks Yahoo for (also the history the chart can show).
SPEC = {
    "1분": {"yahoo": "1m", "period": "8d", "minutes": 1, "visible": 390, "tail": "1d"},
    "5분": {"yahoo": "5m", "period": "60d", "minutes": 5, "visible": 390, "tail": "1d"},
    "30분": {"yahoo": "30m", "period": "60d", "minutes": 30, "visible": 260, "tail": "1d"},
    "60분": {"yahoo": "60m", "period": "730d", "minutes": 60, "visible": 280, "tail": "1d"},
    "120분": {"yahoo": "60m", "period": "730d", "minutes": 120, "visible": 240, "tail": "1d", "pair": True},
    "일봉": {"yahoo": "1d", "period": "max", "minutes": None, "visible": 250, "tail": "5d"},
    "주봉": {"yahoo": "1wk", "period": "max", "minutes": None, "visible": 104, "tail": "1mo"},
    "월봉": {"yahoo": "1mo", "period": "max", "minutes": None, "visible": 60, "tail": "3mo"},
}

# Requested window per interval, shown to the user as "조회 범위 한도" (what this app asks for).
REQUEST_LIMIT_TEXT = {
    "1분": "요청당 최근 8거래일", "5분": "최근 60일", "30분": "최근 60일",
    "60분": "최근 730일", "120분": "최근 730일(60분봉 2개 묶음)", "일봉": "상장 이후 전체",
    "주봉": "기존 장기 이력", "월봉": "기존 장기 이력",
}

DEFAULT_MA_PERIODS = (5, 20, 120, 240, 1000)
MIN_MA, MAX_MA = 2, 5000


def market_of(ticker: str) -> str:
    text = str(ticker or "").upper()
    return "KR" if text.endswith((".KS", ".KQ")) else "US"


def parse_ma_periods(text) -> tuple[list[int], list[str]]:
    """'5, 20 120/1000' -> [5, 20, 120, 1000]; invalid tokens are reported, never guessed."""
    tokens = [t for t in str(text or "").replace("/", ",").replace(" ", ",").split(",") if t.strip()]
    periods, rejected = [], []
    for token in tokens:
        token = token.strip()
        if token.isdigit() and MIN_MA <= int(token) <= MAX_MA:
            if int(token) not in periods:
                periods.append(int(token))
        else:
            rejected.append(token)
    return sorted(periods), rejected


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in frame.columns]
    out = frame[cols].apply(pd.to_numeric, errors="coerce")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.loc[out["Close"].map(lambda v: pd.notna(v) and math.isfinite(v) and v > 0)]
    if "Volume" not in out.columns:
        out["Volume"] = float("nan")
    return out


def fetch_yahoo(ticker: str, interval: str, period: str) -> pd.DataFrame:
    """One Yahoo request. Waits at most 5 s for the shared Yahoo lock so a running
    Today scan cannot freeze the chart; the wait is recorded in ``attrs``."""
    import yfinance as yf
    from stock_lab_core.yahoo_transport import YAHOO_HISTORY_LOCK, yahoo_session_kwargs

    started = time.perf_counter()
    locked = YAHOO_HISTORY_LOCK.acquire(timeout=5)
    waited = time.perf_counter() - started
    try:
        frame = yf.Ticker(ticker, **yahoo_session_kwargs()).history(
            period=period, interval=interval, auto_adjust=True, prepost=False, actions=False, timeout=8)
    finally:
        if locked:
            YAHOO_HISTORY_LOCK.release()
    out = _clean(frame)
    out.attrs.update(lock_wait=waited, fetch_seconds=time.perf_counter() - started)
    return out


def merge_tail(history: pd.DataFrame, tail: pd.DataFrame) -> pd.DataFrame:
    """Newer request wins for the same bar start (the live bar keeps updating)."""
    if tail is None or tail.empty:
        return history
    if history is None or history.empty:
        return tail
    if history.index.tz is not None and tail.index.tz is not None:
        tail = tail.tz_convert(history.index.tz)
    merged = pd.concat([history.loc[~history.index.isin(tail.index)], tail]).sort_index()
    return merged[~merged.index.duplicated(keep="last")]


def pair_sixty_minute_bars(frame: pd.DataFrame, market="US", *, schedule=None) -> pd.DataFrame:
    """Anchor to exchange open, not row number; preserve short and incomplete buckets."""
    if frame is None or frame.empty:
        return frame
    from stock_lab_core.report_eventstudy import _exchange_schedule
    zone = "Asia/Seoul" if market == "KR" else "America/New_York"
    local = frame.index.tz_localize(zone) if frame.index.tz is None else frame.index.tz_convert(zone)
    if schedule is None:
        schedule = _exchange_schedule(market, str((local[0] - pd.Timedelta(days=1)).date()),
                                      str((local[-1] + pd.Timedelta(days=1)).date()))
    dates = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    days = local.tz_localize(None).normalize()
    opens = pd.Series(pd.to_datetime(schedule.market_open, utc=True).to_numpy(), index=dates).reindex(days)
    closes = pd.Series(pd.to_datetime(schedule.market_close, utc=True).to_numpy(), index=dates).reindex(days)
    start = pd.DatetimeIndex(opens.to_numpy())
    end = pd.DatetimeIndex(closes.to_numpy())
    utc = local.tz_convert("UTC")
    valid = start.notna() & (utc >= start) & (utc < end)
    source = frame.loc[valid].copy()
    if source.empty:
        source.attrs["aggregation"] = {"received_60": len(frame), "generated_120": 0,
                                       "excluded": len(frame), "incomplete": 0}
        return source
    elapsed = (utc[valid] - start[valid]).total_seconds() / 60
    anchors = start[valid] + pd.to_timedelta((elapsed // 120) * 120, unit="min")
    ends = pd.DatetimeIndex([min(a + pd.Timedelta(minutes=120), b) for a, b in zip(anchors, end[valid])])
    source["_bucket_end"] = ends
    grouped = source.groupby(anchors, sort=True)
    out = pd.DataFrame({
        "Open": grouped["Open"].first(), "High": grouped["High"].max(), "Low": grouped["Low"].min(),
        "Close": grouped["Close"].last(), "Volume": grouped["Volume"].sum(min_count=1),
    })
    # An absent volume or hourly source is not a zero-volume, complete candle.
    out.loc[grouped["Volume"].count() != grouped.size(), "Volume"] = float("nan")
    bucket_ends = pd.DatetimeIndex(grouped["_bucket_end"].first())
    expected = ((bucket_ends - out.index).total_seconds() / 3600)
    incomplete = int((grouped.size().to_numpy() < [math.ceil(n) for n in expected]).sum())
    out.index = out.index.tz_convert(zone)
    out.attrs["aggregation"] = {"received_60": len(frame), "generated_120": len(out),
                               "excluded": int((~valid).sum()), "incomplete": incomplete,
                               "short_buckets": int((expected < 2).sum())}
    return out


def moving_averages(frame: pd.DataFrame, periods) -> tuple[dict, dict]:
    """Simple moving averages on the chart's own bars. A period longer than the
    available bars gives no line and an explicit shortage note (no shorter-window stand-in)."""
    lines, status = {}, {}
    count = 0 if frame is None else len(frame)
    for period in periods:
        if count < period:
            status[period] = {"ok": False, "have": count, "need": period}
            continue
        lines[period] = frame["Close"].rolling(period, min_periods=period).mean()
        status[period] = {"ok": True, "have": count, "need": period}
    return lines, status


def daily_overlay(daily: pd.DataFrame, bars: pd.DataFrame, periods) -> tuple[dict, dict]:
    """Daily N-day SMA drawn on intraday bars: each bar on day D shows the SMA through the
    previous completed daily close (what was known when that bar traded), never today's
    unfinished close."""
    lines, status = {}, {}
    if daily is None or daily.empty or bars is None or bars.empty:
        return lines, {p: {"ok": False, "have": 0 if daily is None else len(daily), "need": p} for p in periods}
    daily_index = daily.index.tz_localize(None).normalize() if daily.index.tz is not None else daily.index.normalize()
    closes = pd.Series(daily["Close"].to_numpy(), index=daily_index)
    bar_days = bars.index.tz_localize(None).normalize() if bars.index.tz is not None else bars.index.normalize()
    for period in periods:
        previous = closes.index.searchsorted(bar_days, side="left") - 1
        if len(closes) < period or not (previous >= period - 1).any():
            status[period] = {"ok": False, "have": len(closes), "need": period}
            continue
        sma = closes.rolling(period, min_periods=period).mean()
        # Strictly earlier dates also work when today's daily row is not published yet.
        mapped = [sma.iloc[i] if i >= 0 else float("nan") for i in previous]
        lines[period] = pd.Series(mapped, index=bars.index)
        status[period] = {"ok": True, "have": len(closes), "need": period}
    return lines, status


def _naive_days(index):
    index = pd.DatetimeIndex(index)
    return index.tz_localize(None).normalize() if index.tz is not None else index.normalize()


def daily_basis_lines(daily: pd.DataFrame, bars: pd.DataFrame, periods, *, label: str) -> tuple[dict, dict]:
    """Trading-day N-day SMA on daily, weekly or monthly bars (2026-11-27, user request).

    The SMA is computed on the full daily history first, then mapped to the displayed bars: a daily bar takes
    its own date, a weekly/monthly bar takes the last daily close on or before its label date (an unfinished
    week/month therefore shows the value through the latest daily bar). ``bars`` closes override the daily
    history on the same dates so the daily chart keeps its own last (possibly live) bar. No shorter window
    stands in for a missing one; status carries have/need and the last value with its daily date."""
    lines, status = {}, {}
    if daily is None or daily.empty or "Close" not in daily or bars is None or bars.empty:
        have = 0 if daily is None or getattr(daily, "empty", True) else len(daily)
        return lines, {p: {"ok": False, "have": have, "need": p} for p in periods}
    closes = pd.Series(pd.to_numeric(daily["Close"], errors="coerce").to_numpy(), index=_naive_days(daily.index))
    closes = closes[~closes.index.duplicated(keep="last")].dropna()
    bar_days = _naive_days(bars.index)
    if label == "일봉":
        own = pd.Series(pd.to_numeric(bars["Close"], errors="coerce").to_numpy(), index=bar_days).dropna()
        own = own[~own.index.duplicated(keep="last")]
        closes = own.combine_first(closes) if not own.empty else closes
    closes = closes.sort_index()
    for period in periods:
        if len(closes) < period:
            status[period] = {"ok": False, "have": len(closes), "need": period}
            continue
        sma = closes.rolling(period, min_periods=period).mean()
        pos = closes.index.searchsorted(bar_days, side="right") - 1
        values = [sma.iloc[i] if i >= 0 else float("nan") for i in pos]
        series = pd.Series(values, index=bars.index, dtype="float64")
        if not series.notna().any():
            status[period] = {"ok": False, "have": len(closes), "need": period}
            continue
        last_pos = int(pos[-1])
        lines[period] = series
        status[period] = {"ok": True, "have": len(closes), "need": period,
                          "last_value": float(sma.iloc[last_pos]) if last_pos >= 0 else float("nan"),
                          "last_date": str(closes.index[last_pos].date()) if last_pos >= 0 else "",
                          "first_date": str(sma.first_valid_index().date())}
    return lines, status


def last_bar_state(frame: pd.DataFrame, label: str, now: pd.Timestamp, session: dict | None) -> dict:
    """Describe the newest bar: start, close, volume, whether still in progress, and how far it
    lags the clock. ``session`` is report_exchange_clock.exchange_clock output (or None)."""
    if frame is None or frame.empty:
        return {"available": False}
    start = frame.index[-1]
    row = frame.iloc[-1]
    minutes = SPEC[label]["minutes"]
    clock = pd.Timestamp(now)
    intraday = bool(session) and session.get("phase") == "intraday"
    local_today = clock.tz_convert(start.tz).date() if start.tz is not None else clock.date()
    # During a session Yahoo's newest bar is its in-progress bar, even when the feed is delayed
    # (KR: about 20 minutes behind, volume often 0 until the provider closes it).
    provisional = intraday and start.date() == local_today
    lag = None if minutes is None or not intraday else (clock - start).total_seconds() / 60.0
    volume = row.get("Volume")
    return {"available": True, "start": start, "close": float(row["Close"]),
            "volume": None if volume is None or pd.isna(volume) else float(volume),
            "provisional": provisional, "lag_minutes": lag, "intraday": intraday}


def build_frame(history: pd.DataFrame, tail: pd.DataFrame | None, label: str, market="US") -> pd.DataFrame:
    frame = merge_tail(history, tail)
    if SPEC[label].get("pair"):
        frame = pair_sixty_minute_bars(frame, market)
    return frame
