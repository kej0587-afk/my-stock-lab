"""Timestamp-aligned observations, never a fabricated return attribution."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, first, number, text

register_loaded_source(__name__, __file__)
SYMBOLS = ("NQ=F", "ES=F", "USDKRW=X")
FUTURES = {"379810": "NQ=F", "418660": "NQ=F", "379800": "ES=F"}


def interval_observation(frame, start, end):
    """Both endpoints need completed, timezone-aware 5m bars within ten minutes."""
    if not isinstance(frame, pd.DataFrame) or frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        return {}
    if "Close" not in frame or not isinstance(frame["Close"], pd.Series) or end <= start:
        return {}
    close = pd.to_numeric(frame["Close"], errors="coerce").sort_index()
    close = close.loc[~close.index.duplicated(keep="last")]
    ends = close.index + pd.Timedelta(minutes=5)
    points = []
    for cutoff in (start, end):
        mask = (ends <= cutoff) & (ends >= cutoff - timedelta(minutes=10))
        eligible = close.loc[mask]
        if eligible.empty:
            return {}
        value = number(eligible.iloc[-1])
        if value is None or value <= 0:
            return {}
        points.append((value, (eligible.index[-1] + pd.Timedelta(minutes=5)).isoformat()))
    return {"return": points[1][0] / points[0][0] - 1, "base_at": points[0][1], "as_of": points[1][1],
            "source": "Yahoo 5분봉 · 지연 가능"}


def build_scenario_context(frames, sessions, now):
    us = text(sessions.get("US"))
    if not us:
        return {}
    base = datetime.combine(datetime.fromisoformat(us).date(), time(16), ZoneInfo("America/New_York"))
    kr = text(sessions.get("KR"))
    close = datetime.combine(now.date(), time(15, 30), KST)
    current = {symbol: interval_observation(frames.get(symbol), base, now) for symbol in SYMBOLS}
    closed = ({symbol: interval_observation(frames.get(symbol), base, close) for symbol in SYMBOLS}
              if kr == now.date().isoformat() and now >= close else {})
    return {"latest": current, "kr_close": closed}


def scenario_observation_line(row, evidence):
    code = text(first(row, "티커", "ticker")).upper().split(".")[0]
    symbol = FUTURES.get(code)
    if not symbol:
        return ""
    closed = (evidence or {}).get("kr_close", {})
    parts = []
    for key, label in ((symbol, "미국 선물"), ("USDKRW=X", "원/달러")):
        item = closed.get(key, {})
        value = number(item.get("return"))
        if value is None:
            parts.append(f"{label}: 동일 시간대 자료 미수집")
        else:
            start = pd.Timestamp(item["base_at"]).tz_convert("Asia/Seoul").strftime("%m/%d %H:%M")
            end = pd.Timestamp(item["as_of"]).tz_convert("Asia/Seoul").strftime("%m/%d %H:%M")
            parts.append(f"{label} {key} {value * 100:+.2f}% ({start}→{end} KST)")
    return (" · 비교 구간 관측: " + " / ".join(parts)
            + " / 괴리율: 같은 시각 NAV·iNAV 미연결. 관측 등락이며 차이의 기여도 분해·합산은 아님."
            + (" 레버리지·환헤지 효과를 동일 배수로 추정하지 않음." if code == "418660" else ""))


def latest_futures_line(evidence):
    parts = []
    for symbol in SYMBOLS[:2]:
        item = (evidence or {}).get("latest", {}).get(symbol, {})
        move = number(item.get("return"))
        if move is not None:
            at = pd.Timestamp(item["as_of"]).tz_convert("Asia/Seoul").strftime("%m/%d %H:%M KST")
            parts.append(f"{symbol} {move * 100:+.2f}% ({at})")
    return ("현재 선물 관측(미국 기준일 16:00 ET 대비, 지연 가능): " + " / ".join(parts)
            if parts else "현재 선물: 같은 기준 시각의 자료 미수집, 방향 추정 안 함")
