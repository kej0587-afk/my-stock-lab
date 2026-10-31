"""Auditable parallel channels and causal chart events, without trade scoring."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from stock_lab_core.chart_execution import chart_volume_ratio
from stock_lab_core.chart_patterns import (
    _chart_pattern_source_df, build_recent_trendline_guides, detect_chart_pattern_candidates,
)
from stock_lab_core.execution_gate import GATE_EXECUTABLE


def build_parallel_channel(frame, lookback=140):
    view = _chart_pattern_source_df(frame, lookback)
    if view.empty:
        return {}
    if "enforce_price_proximity" not in inspect.signature(build_recent_trendline_guides).parameters:
        return {}
    guides = build_recent_trendline_guides(view, lookback, enforce_price_proximity=False)
    # Rising channels start at reaction lows; falling channels at reaction highs.
    anchors = [g for g in guides if (g["kind"], g["direction"]) in
               {("support", "상승"), ("resistance", "하락")} and len(g.get("pivots", [])) == 2]
    anchors.sort(key=lambda g: g["pivots"][-1]["pos"], reverse=True)
    for guide in anchors:
        a, b = guide["pivots"]
        if b["pos"] - a["pos"] < 6 or b["pos"] + 3 >= len(view):
            continue
        slope = (b["price"] - a["price"]) / (b["pos"] - a["pos"])
        x = np.arange(a["pos"], len(view))
        main = a["price"] + slope * (x - a["pos"])
        inside = view.iloc[a["pos"] + 1:b["pos"]]
        inside_x = np.arange(a["pos"] + 1, b["pos"])
        rail = a["price"] + slope * (inside_x - a["pos"])
        if guide["kind"] == "support":
            residuals = inside["High"].to_numpy() - rail
            offset = float(residuals.max())
            touch = int(residuals.argmax())
            lower, upper = main, main + offset
            opposite = float(inside["High"].iloc[touch])
            if offset <= 0:
                continue
        else:
            residuals = inside["Low"].to_numpy() - rail
            offset = float(residuals.min())
            touch = int(residuals.argmin())
            lower, upper = main + offset, main
            opposite = float(inside["Low"].iloc[touch])
            if offset >= 0:
                continue
        if not np.isfinite(offset) or abs(offset) <= 0 or np.min(lower) <= 0:
            continue
        close = float(view.Close.iloc[-1])
        state = "상단 돌파" if close > upper[-1] else "하단 이탈" if close < lower[-1] else "채널 내부"
        return {"direction": guide["direction"], "state": state, "x": view.index[a["pos"]:].tolist(),
                "lower": lower.tolist(), "upper": upper.tolist(), "middle": ((upper + lower) / 2).tolist(),
                "slope": float(slope), "width": abs(offset),
                "known_at": view.index[b["pos"] + 3],
                "anchors": [dict(a), dict(b), {"time": inside.index[touch], "price": opposite}],
                "formation_id": (guide["kind"], a["time"], b["time"])}
    return {}


def _previous_trigger(pattern):
    paths = pattern.get("line_paths") or []
    if not paths:
        return float(pattern["trigger_price"])
    path = paths[1 if pattern.get("direction") == "bearish" and len(paths) == 2 else 0]
    return float(path["y"][-2]) if len(path["y"]) > 1 else float(pattern["trigger_price"])


def build_chart_structure(frame, *, history_bars=80, lookback=140):
    """Each event is computed from its own prefix, never from future pivots.

    Stored event times are observation times. A pivot needing three right-hand
    bars can produce a delayed confirmation, never an arrow back on its peak.
    """
    if frame is None or frame.empty:
        return {"channel": {}, "events": [], "patterns": []}
    if ("distinct_directions" not in inspect.signature(detect_chart_pattern_candidates).parameters or
            "enforce_price_proximity" not in inspect.signature(build_recent_trendline_guides).parameters):
        return {"channel": {}, "events": [], "patterns": [], "issue": "차트 모듈 버전 불일치 · Cloud 앱 재시작 필요"}
    source = frame.tail(lookback + history_bars).copy()
    valid = _chart_pattern_source_df(source, len(source))
    if valid.empty or not isinstance(source.index, pd.DatetimeIndex) or source.index.hasnans:
        return {"channel": {}, "events": [], "patterns": [], "issue": "OHLC 결측·중복·순서 확인"}
    if ((valid.Low > valid[["Open", "Close"]].min(axis=1)) | (valid.High < valid[["Open", "Close"]].max(axis=1))).any():
        return {"channel": {}, "events": [], "patterns": [], "issue": "OHLC 고가·저가 범위 확인"}
    events, seen, last_pattern_event = [], set(), {}
    first = max(24, len(source) - history_bars + 1)
    previous_channel = build_parallel_channel(source.iloc[:first-1], lookback)
    for stop in range(first, len(source) + 1):
        prefix = source.iloc[:stop]
        now, previous = prefix.index[-1], float(prefix.Close.iloc[-2])
        close = float(prefix.Close.iloc[-1])
        quote_only = "LiveQuoteOnly" in prefix and pd.notna(prefix.LiveQuoteOnly.iloc[-1]) and bool(prefix.LiveQuoteOnly.iloc[-1])
        ratio = chart_volume_ratio(prefix)
        volume = float(ratio) if np.isfinite(ratio) else None
        for pattern in detect_chart_pattern_candidates(prefix, lookback, 7, distinct_directions=False):
            direction = pattern.get("direction")
            if direction not in {"bullish", "bearish"} or pattern.get("lifecycle") != "현재유효":
                continue
            multiplier = (1.005 if direction == "bullish" else .995) if pattern["name"] in {"삼각수렴", "상승 깃발형", "하락 깃발형"} else 1.0
            level = float(pattern["trigger_price"]) * multiplier
            beyond = close > level if direction == "bullish" else close < level
            previous_level = _previous_trigger(pattern) * multiplier
            crossed = previous <= previous_level if direction == "bullish" else previous >= previous_level
            delayed = pattern.get("known_at") == now and beyond
            key = tuple(pattern.get("formation_id") or (pattern["name"], pattern.get("label_x")))
            if not beyond or not (crossed or delayed) or key in seen:
                continue
            # Rolling flag windows must not print the same break every day.
            last = last_pattern_event.get((pattern["name"], direction), -99)
            if stop - last < 5:
                continue
            seen.add(key)
            last_pattern_event[(pattern["name"], direction)] = stop
            starts = [line[0][0] for line in pattern.get("line_points", [])]
            events.append({"time": now, "price": close, "level": level, "side": "buy" if direction == "bullish" else "sell",
                           "name": pattern["name"], "source": "pattern", "known_at": pattern.get("known_at"),
                           "formation_start": min(starts) if starts else now,
                           "formation_end": pattern.get("formation_end", pattern.get("label_x")),
                           "confirmation": "종가 돌파" if direction == "bullish" else "종가 이탈",
                           "provisional": quote_only,
                           "delayed_pivot_confirmation": not crossed, "volume_ratio": volume})
        channel = previous_channel
        if channel and channel["known_at"] < now:
            for side, rail in (("buy", "upper"), ("sell", "lower")):
                before = channel[rail][-1]
                current_rail = before + channel["slope"]
                crossed = (previous <= before and close > current_rail) if side == "buy" else (previous >= before and close < current_rail)
                key = ("channel", side, *channel["formation_id"])
                if crossed and key not in seen:
                    seen.add(key)
                    events.append({"time": now, "price": close, "level": current_rail, "side": side,
                                   "name": "평행 채널", "source": "channel", "known_at": channel["known_at"],
                                   "formation_start": channel["anchors"][0]["time"],
                                   "formation_end": channel["anchors"][1]["time"],
                                   "confirmation": "상단 종가 돌파" if side == "buy" else "하단 종가 이탈",
                                   "provisional": quote_only,
                                   "delayed_pivot_confirmation": False, "volume_ratio": volume})
        previous_channel = build_parallel_channel(prefix, lookback)
    events.sort(key=lambda event: event["time"])
    return {"channel": build_parallel_channel(source, lookback), "events": events[-24:],
            "patterns": detect_chart_pattern_candidates(source, lookback),
            "last_bar": source.index[-1], "history_bars": min(history_bars, len(source)),
            "basis": "각 봉까지 수집된 가격·거래량, 피벗 우측 3봉 확인 후"}


def last_bar_is_provisional(frame, ticker="", timeframe="daily", *, now=None):
    if frame is None or frame.empty:
        return True
    if "LiveQuoteOnly" in frame and pd.notna(frame.LiveQuoteOnly.iloc[-1]) and bool(frame.LiveQuoteOnly.iloc[-1]):
        return True
    if not isinstance(frame.index, pd.DatetimeIndex):
        return True
    completed = latest_completed_chart_session(ticker, now=now)
    if completed is None:
        return True
    last_day = frame.index[-1].date().isoformat()
    return last_day > completed


def latest_completed_chart_session(ticker, *, now=None):
    from stock_lab_core.report_eventstudy import _exchange_schedule
    clock = pd.Timestamp(now or datetime.now(timezone.utc))
    clock = clock.tz_localize("UTC") if clock.tzinfo is None else clock.tz_convert("UTC")
    market = "KR" if str(ticker).endswith((".KS", ".KQ")) else "US"
    try:
        schedule = _exchange_schedule(market, (clock-pd.Timedelta(days=14)).date().isoformat(), clock.date().isoformat())
        completed = schedule.loc[pd.to_datetime(schedule.market_close, utc=True) <= clock]
        return completed.index[-1].date().isoformat() if not completed.empty else None
    except (ImportError, KeyError, ValueError, OSError):
        return None


def chart_date_breaks(frame, ticker=""):
    """Compress real daily market closures, never missing trading-session data."""
    if not isinstance(frame.index, pd.DatetimeIndex) or len(frame) < 3:
        return []
    index = frame.index.tz_localize(None).normalize()
    if index.to_series().diff().median() >= pd.Timedelta(days=3) or (index.dayofweek >= 5).any():
        return []
    from stock_lab_core.report_eventstudy import _exchange_schedule
    market = "KR" if str(ticker).endswith((".KS", ".KQ")) else "US"
    try:
        schedule = _exchange_schedule(market, index[0].date().isoformat(), index[-1].date().isoformat())
        sessions = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
        closures = pd.bdate_range(index[0], index[-1]).difference(sessions).difference(index)
        breaks = [{"bounds": ["sat", "mon"]}]
        if len(closures):
            breaks.append({"values": closures.strftime("%Y-%m-%d").tolist()})
        return breaks
    except (ImportError, KeyError, ValueError, OSError):
        return []


def qualify_chart_events(structure, decision=None, *, timeframe="daily", provisional_last=False):
    decision = decision or {}
    workflow = decision.get("execution_workflow") or {}
    final = decision.get("chart_final_check") or {}
    result = []
    for original in structure.get("events", []):
        event = dict(original)
        event_date = pd.Timestamp(event["time"]).date().isoformat()
        current = (event["time"] == structure.get("last_bar") and timeframe == "daily"
                   and event_date == decision.get("chart_price_asof") == decision.get("chart_expected_close"))
        pending = event.get("provisional", False) or (event["time"] == structure.get("last_bar") and provisional_last)
        volume_ok = event.get("volume_ratio") is not None and event["volume_ratio"] >= 1.2
        permitted = event["side"] == "buy" and current and not pending and volume_ok and workflow.get("게이트상태") == GATE_EXECUTABLE and final.get("execution_allowed") is True
        event.update(execution_allowed=permitted, provisional=pending)
        event["label"] = "매도형" if event["side"] == "sell" else "매수 검토" if permitted else "매수형·보류" if current else "매수형"
        if pending:
            event["label"] += "·미확정"
        elif event.get("delayed_pivot_confirmation"):
            event["label"] += "·지연확인"
        if pending:
            event["execution"] = "미확정 봉 · 종가 확인 전"
        elif event["side"] == "sell":
            event["execution"] = "보유분 방어 검토 · 자동매도 아님"
        elif permitted:
            event["execution"] = "현재 게이트·최종 체크 통과, 수동 검토"
        elif current:
            event["execution"] = workflow.get("게이트근거") or "최종 체크·거래량 확인"
        else:
            event["execution"] = "과거 품질·시장·계좌 제한 미검증" if timeframe == "daily" else "상위 시간대 구조 확인용"
        result.append(event)
    return result


def add_channel_overlay(fig, channel):
    if not channel:
        return
    for key, label, dash in (("lower", "채널 하단", "solid"), ("middle", "채널 중심", "dot"), ("upper", "채널 상단", "solid")):
        fig.add_trace(go.Scatter(x=channel["x"], y=channel[key], mode="lines", name=label,
                                legendgroup="channel", line=dict(color="#60a5fa", width=1.7 if key != "middle" else 1, dash=dash),
                                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f}<extra>" + label + "</extra>"))
    for fraction in (.25, .75):
        values = np.array(channel["lower"]) + channel["width"] * fraction
        fig.add_trace(go.Scatter(x=channel["x"], y=values, mode="lines", showlegend=False, hoverinfo="skip",
                                line=dict(color="#60a5fa", width=.7, dash="dot"), opacity=.45))
    anchors = channel["anchors"]
    fig.add_trace(go.Scatter(x=[p["time"] for p in anchors], y=[p["price"] for p in anchors], mode="markers",
                            marker=dict(size=6, color="#60a5fa", symbol="circle-open"), name="채널 작도점", showlegend=False,
                            hovertemplate="%{x|%Y-%m-%d}<br>작도점 %{y:,.2f}<extra></extra>"))


def add_event_overlays(fig, events):
    for side, name, color, symbol in (("buy", "매수형 패턴", "#fb7185", "triangle-up"), ("sell", "매도형 패턴", "#38bdf8", "triangle-down")):
        selected = [e for e in events if e["side"] == side]
        if not selected:
            continue
        custom = [[e["name"], e["label"], e["confirmation"], e["level"], e["execution"],
                   f"{e['volume_ratio']:.2f}x" if e.get("volume_ratio") is not None else "미확인"] for e in selected]
        pattern_events = [e for e in selected if e["source"] == "pattern"]
        latest_pattern = pattern_events[-1] if pattern_events else None
        fig.add_trace(go.Scatter(x=[e["time"] for e in selected], y=[e["price"] for e in selected], mode="markers+text",
                                text=[e["label"] if e is latest_pattern else "" for e in selected],
                                textposition="bottom center" if side == "buy" else "top center", textfont=dict(size=10, color=color),
                                name=name, marker=dict(size=12, color=["#f59e0b" if e["label"].startswith("매수형·보류") else color for e in selected],
                                                       symbol=[symbol + "-open" if e["provisional"] else symbol for e in selected], line=dict(width=1)),
                                customdata=custom, hovertemplate="%{x|%Y-%m-%d}<br>%{customdata[0]} · %{customdata[1]}<br>%{customdata[2]} · 기준 %{customdata[3]:,.2f}<br>거래량 %{customdata[5]}<br>%{customdata[4]}<extra></extra>"))


def chart_structure_rows(structure, events, decision=None):
    rows = []
    for event in events[-6:][::-1]:
        rows.append({"확인봉": pd.Timestamp(event["time"]).strftime("%Y-%m-%d"), "구조": event["name"],
                     "신호": event["label"], "기준선": round(event["level"], 2),
                     "형성 구간": f"{pd.Timestamp(event['formation_start']):%m/%d}~{pd.Timestamp(event['formation_end']):%m/%d}",
                     "검토 상태": event["execution"]})
    return rows


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
