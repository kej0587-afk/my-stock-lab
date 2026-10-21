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
    # Batched symbols share an index: newer FX bars can be empty for futures.
    close = close.loc[close.map(lambda value: number(value) is not None and value > 0)]
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
    status = {}
    for symbol in SYMBOLS:
        frame = frames.get(symbol)
        if current.get(symbol):
            continue
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            status[symbol] = "수집 실패/미수집: 시세 프레임 없음"
        elif not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            status[symbol] = "수집 자료의 시간대 정보 미확인"
        else:
            values = frame.get("Close")
            if not isinstance(values, pd.Series):
                status[symbol] = "가격 열 미수집/중복"
                continue
            valid = values.map(lambda value: number(value) is not None and number(value) > 0)
            completed = frame.index[valid & (frame.index + pd.Timedelta(minutes=5) <= now)]
            last = completed.max() + pd.Timedelta(minutes=5) if len(completed) else None
            if last is None or last < now - timedelta(minutes=10):
                status[symbol] = "자료 지연: 현재 시점 10분 이내 유효 완료 봉 없음"
                if last is not None:
                    status[symbol] += " · 마지막 유효 시각 " + last.tz_convert("Asia/Seoul").strftime("%m/%d %H:%M KST")
            else:
                status[symbol] = "비교 기준 미국 종가 시각의 유효 가격 미수집(" + base.isoformat() + ")"
    return {"latest": current, "kr_close": closed, "latest_status": status}


def scenario_observation_line(row, evidence):
    code = text(first(row, "티커", "ticker")).upper().split(".")[0]
    symbol = FUTURES.get(code)
    if not symbol:
        return ""
    closed = (evidence or {}).get("kr_close") or (evidence or {}).get("latest", {})
    parts = []
    for key, label in ((symbol, "미국 선물"), ("USDKRW=X", "원/달러")):
        item = closed.get(key, {})
        value = number(item.get("return"))
        if value is None:
            reason = (evidence or {}).get("latest_status", {}).get(key, "동일 시간대 자료 미수집")
            parts.append(f"{label}: {reason}")
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
        else:
            reason = (evidence or {}).get("latest_status", {}).get(symbol, "수집 실패/지연 또는 비교 시각 자료 미수집")
            parts.append(f"{symbol} 미수집({reason})")
    return "현재 선물 관측(미국 기준일 16:00 ET 대비, 지연 가능): " + " / ".join(parts)
