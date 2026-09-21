"""Chart pattern and trendline detection helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stock_lab_core.formatters import clean_float, finite_num

def _chart_pattern_source_df(df: pd.DataFrame, lookback: int = 140) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close"]
    if df is None or df.empty or any(col not in df.columns for col in required):
        return pd.DataFrame()
    view = df[required].copy().dropna().tail(lookback)
    if len(view) < 24:
        return pd.DataFrame()
    return view


def _chart_pattern_pivots(view: pd.DataFrame, left: int = 3, right: int = 3):
    highs, lows = [], []
    for i in range(left, len(view) - right):
        high_window = view["High"].iloc[i - left:i + right + 1]
        low_window = view["Low"].iloc[i - left:i + right + 1]
        high = float(view["High"].iloc[i])
        low = float(view["Low"].iloc[i])
        if high == float(high_window.max()):
            highs.append({"pos": i, "time": view.index[i], "price": high})
        if low == float(low_window.min()):
            lows.append({"pos": i, "time": view.index[i], "price": low})
    return highs, lows


def _chart_pattern_rel_diff(a, b) -> float:
    try:
        denom = (abs(float(a)) + abs(float(b))) / 2
        return abs(float(a) - float(b)) / denom if denom else 1.0
    except Exception:
        return 1.0


def _chart_pattern_line_value(points, last_pos: int) -> float:
    x = np.array([p["pos"] for p in points], dtype=float)
    y = np.array([p["price"] for p in points], dtype=float)
    if len(x) < 2:
        return float(y[-1]) if len(y) else np.nan
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope * last_pos + intercept)


def _chart_pattern_price_text(value) -> str:
    try:
        price = float(value)
        if not np.isfinite(price) or price <= 0:
            return "-"
        return f"{price:,.2f}"
    except Exception:
        return "-"


def _chart_pattern_timeframe_profile(view: pd.DataFrame) -> dict:
    """일/주/月 봉마다 패턴 유효 기간과 과도 이격 기준을 다르게 둡니다."""
    profile = {
        "valid_age": 35,
        "watch_age": 12,
        "max_trigger_extension": 0.32,
        "max_trigger_breakdown": 0.32,
    }
    if view is None or len(view.index) < 3:
        return profile
    try:
        idx = pd.to_datetime(view.index)
        median_days = pd.Series(idx).diff().dt.days.dropna().median()
    except Exception:
        median_days = np.nan
    if finite_num(median_days) and median_days >= 20:
        return {
            "valid_age": 8,
            "watch_age": 4,
            "max_trigger_extension": 0.45,
            "max_trigger_breakdown": 0.45,
        }
    if finite_num(median_days) and median_days >= 5:
        return {
            "valid_age": 16,
            "watch_age": 7,
            "max_trigger_extension": 0.38,
            "max_trigger_breakdown": 0.38,
        }
    return profile


def _chart_pattern_lifecycle(pattern: dict, view: pd.DataFrame) -> dict:
    close = float(view["Close"].iloc[-1])
    last_pos = len(view) - 1
    created_pos = int(pattern.get("created_pos", last_pos))
    age = max(0, last_pos - created_pos)
    direction = pattern.get("direction", "neutral")
    raw_status = str(pattern.get("status", "관찰"))
    trigger = clean_float(pattern.get("trigger_price"), 0.0)
    invalid = clean_float(pattern.get("invalid_price"), 0.0)
    profile = _chart_pattern_timeframe_profile(view)
    valid_age = int(profile.get("valid_age", 35))
    watch_age = int(profile.get("watch_age", 12))
    bullish_trigger_extension = (close / trigger - 1.0) if trigger > 0 else 0.0
    bearish_trigger_breakdown = (trigger / close - 1.0) if trigger > 0 and close > 0 else 0.0
    bullish_still_near_trigger = (
        trigger <= 0
        or (
            close >= trigger * 0.985
            and bullish_trigger_extension <= clean_float(profile.get("max_trigger_extension"), 0.32)
        )
    )
    bearish_still_near_trigger = (
        trigger <= 0
        or (
            close <= trigger * 1.015
            and bearish_trigger_breakdown <= clean_float(profile.get("max_trigger_breakdown"), 0.32)
        )
    )

    lifecycle = "관찰"
    priority = 2
    if direction == "bullish":
        if invalid > 0 and close < invalid:
            lifecycle, priority = "무효", 0
        elif raw_status in {"돌파", "상방돌파"} and age <= valid_age and bullish_still_near_trigger:
            lifecycle, priority = "현재유효", 4
        elif age <= watch_age:
            lifecycle, priority = "관찰", 2
        else:
            lifecycle, priority = "과거", 1
    elif direction == "bearish":
        if invalid > 0 and close > invalid:
            lifecycle, priority = "무효", 0
        elif raw_status in {"이탈", "하방이탈"} and age <= valid_age and bearish_still_near_trigger:
            lifecycle, priority = "현재유효", 4
        elif age <= watch_age:
            lifecycle, priority = "관찰", 2
        else:
            lifecycle, priority = "과거", 1
    else:
        if age <= max(3, watch_age - 2):
            lifecycle, priority = "관찰", 2
        else:
            lifecycle, priority = "과거", 1

    pattern = pattern.copy()
    pattern["age"] = age
    pattern["lifecycle"] = lifecycle
    pattern["priority"] = priority
    prefix = "현재유효" if lifecycle == "현재유효" else ("관찰" if lifecycle == "관찰" else lifecycle)
    pattern_name = pattern.get("name", "패턴")
    if lifecycle == "관찰":
        pattern["display_label"] = f"{prefix}: {pattern_name} 후보"
    else:
        pattern["display_label"] = f"{prefix}: {pattern_name}"
    if raw_status and raw_status not in {"관찰", lifecycle}:
        pattern["display_label"] += f" {raw_status}"
    pattern["summary"] = (
        f"{prefix} · {pattern_name}{' 후보' if lifecycle == '관찰' else ''} "
        f"(기준 { _chart_pattern_price_text(trigger) } / 무효 { _chart_pattern_price_text(invalid) })"
    )
    return pattern


def _finalize_chart_pattern_candidates(view: pd.DataFrame, patterns: list, max_patterns: int = 1) -> list:
    enriched = [_chart_pattern_lifecycle(pattern, view) for pattern in patterns]
    active = [p for p in enriched if p.get("lifecycle") in {"현재유효", "관찰"}]
    if not active:
        return []
    active.sort(
        key=lambda item: (
            item.get("priority", 0),
            -item.get("age", 999),
            item.get("confidence", 0),
        ),
        reverse=True,
    )
    selected = []
    seen_direction = set()
    for pattern in active:
        direction = pattern.get("direction", "neutral")
        if direction in seen_direction and len(selected) >= 1:
            continue
        selected.append(pattern)
        seen_direction.add(direction)
        if len(selected) >= max_patterns:
            break
    return selected


def _detect_double_pattern(view: pd.DataFrame, highs, lows, kind: str):
    points = lows if kind == "bottom" else highs
    if len(points) < 2:
        return None
    close = float(view["Close"].iloc[-1])
    best = None
    recent_points = points[-7:]
    for left_idx in range(len(recent_points) - 1):
        for right_idx in range(left_idx + 1, len(recent_points)):
            a = recent_points[left_idx]
            b = recent_points[right_idx]
            gap = b["pos"] - a["pos"]
            if gap < 5 or gap > 70:
                continue
            if _chart_pattern_rel_diff(a["price"], b["price"]) > 0.045:
                continue
            segment = view.iloc[a["pos"]:b["pos"] + 1]
            if kind == "bottom":
                neckline = float(segment["High"].max())
                base = (a["price"] + b["price"]) / 2
                height = (neckline - base) / base if base else 0
                if height < 0.035 or close < base * (1 + min(height * 0.25, 0.03)):
                    continue
                status = "돌파" if close >= neckline * 0.997 else "관찰"
                direction = "bullish"
                label = f"쌍바닥 {status}"
                label_y = b["price"]
            else:
                neckline = float(segment["Low"].min())
                top = (a["price"] + b["price"]) / 2
                height = (top - neckline) / top if top else 0
                if height < 0.035 or close > top * (1 - min(height * 0.25, 0.03)):
                    continue
                status = "이탈" if close <= neckline * 1.003 else "관찰"
                direction = "bearish"
                label = f"쌍봉 {status}"
                label_y = b["price"]
            confidence = height + (0.02 if status in {"돌파", "이탈"} else 0)
            candidate = {
                "name": "쌍바닥" if kind == "bottom" else "쌍봉",
                "label": label,
                "direction": direction,
                "status": status,
                "confidence": confidence,
                "created_pos": b["pos"],
                "trigger_price": neckline,
                "invalid_price": (min(a["price"], b["price"]) * 0.985) if kind == "bottom" else (max(a["price"], b["price"]) * 1.015),
                "label_x": b["time"],
                "label_y": label_y,
                "line_points": [
                    ((a["time"], a["price"]), (b["time"], b["price"])),
                    ((a["time"], neckline), (view.index[-1], neckline)),
                ],
            }
            if best is None or candidate["confidence"] > best["confidence"]:
                best = candidate
    return best


def _detect_head_shoulders_pattern(view: pd.DataFrame, highs, lows, inverse: bool = False):
    points = lows if inverse else highs
    opposite = highs if inverse else lows
    if len(points) < 3 or len(opposite) < 2:
        return None
    close = float(view["Close"].iloc[-1])
    best = None
    recent = points[-7:]
    for i in range(len(recent) - 2):
        left, head, right = recent[i], recent[i + 1], recent[i + 2]
        if min(head["pos"] - left["pos"], right["pos"] - head["pos"]) < 4:
            continue
        shoulders_ok = _chart_pattern_rel_diff(left["price"], right["price"]) <= 0.075
        if not shoulders_ok:
            continue
        if inverse:
            head_ok = head["price"] < left["price"] * 0.96 and head["price"] < right["price"] * 0.96
        else:
            head_ok = head["price"] > left["price"] * 1.04 and head["price"] > right["price"] * 1.04
        if not head_ok:
            continue
        mids = [p for p in opposite if left["pos"] < p["pos"] < right["pos"]]
        if len(mids) < 2:
            continue
        neckline = (mids[0]["price"] + mids[-1]["price"]) / 2
        if inverse:
            status = "돌파" if close >= neckline * 0.997 else "관찰"
            label = f"역헤드앤숄더 {status}"
            direction = "bullish"
        else:
            status = "이탈" if close <= neckline * 1.003 else "관찰"
            label = f"헤드앤숄더 {status}"
            direction = "bearish"
        spread = abs(head["price"] - neckline) / abs(neckline) if neckline else 0
        candidate = {
            "name": "역헤드앤숄더" if inverse else "헤드앤숄더",
            "label": label,
            "direction": direction,
            "status": status,
            "confidence": spread + (0.02 if status in {"돌파", "이탈"} else 0),
            "created_pos": right["pos"],
            "trigger_price": neckline,
            "invalid_price": head["price"] * 0.985 if inverse else head["price"] * 1.015,
            "label_x": right["time"],
            "label_y": right["price"],
            "line_points": [
                ((left["time"], left["price"]), (head["time"], head["price"])),
                ((head["time"], head["price"]), (right["time"], right["price"])),
                ((mids[0]["time"], neckline), (view.index[-1], neckline)),
            ],
        }
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate
    return best


def _detect_triangle_pattern(view: pd.DataFrame, highs, lows):
    if len(highs) < 3 or len(lows) < 3:
        return None
    recent_highs = highs[-4:]
    recent_lows = lows[-4:]
    price = float(view["Close"].iloc[-1])
    last_pos = len(view) - 1
    xh = np.array([p["pos"] for p in recent_highs], dtype=float)
    yh = np.array([p["price"] for p in recent_highs], dtype=float)
    xl = np.array([p["pos"] for p in recent_lows], dtype=float)
    yl = np.array([p["price"] for p in recent_lows], dtype=float)
    high_slope, high_intercept = np.polyfit(xh, yh, 1)
    low_slope, low_intercept = np.polyfit(xl, yl, 1)
    slope_floor = max(price * 0.00035, 1e-9)
    if not (high_slope < -slope_floor and low_slope > slope_floor):
        return None
    first_gap = (high_slope * min(xh[0], xl[0]) + high_intercept) - (low_slope * min(xh[0], xl[0]) + low_intercept)
    last_upper = high_slope * last_pos + high_intercept
    last_lower = low_slope * last_pos + low_intercept
    last_gap = last_upper - last_lower
    if first_gap <= 0 or last_gap <= 0 or last_gap > first_gap * 0.8:
        return None
    close = float(view["Close"].iloc[-1])
    if close > last_upper * 1.005:
        status, direction = "상방돌파", "bullish"
    elif close < last_lower * 0.995:
        status, direction = "하방이탈", "bearish"
    else:
        status, direction = "수렴", "neutral"
    return {
        "name": "삼각수렴",
        "label": f"삼각수렴 {status}",
        "direction": direction,
        "status": status,
        "confidence": (first_gap - last_gap) / first_gap,
        "created_pos": last_pos,
        "trigger_price": last_upper if direction == "bullish" else (last_lower if direction == "bearish" else (last_upper + last_lower) / 2),
        "invalid_price": last_lower if direction == "bullish" else (last_upper if direction == "bearish" else 0.0),
        "label_x": view.index[-1],
        "label_y": close,
        "line_points": [
            ((recent_highs[0]["time"], high_slope * recent_highs[0]["pos"] + high_intercept),
             (view.index[-1], last_upper)),
            ((recent_lows[0]["time"], low_slope * recent_lows[0]["pos"] + low_intercept),
             (view.index[-1], last_lower)),
        ],
    }


def _detect_flag_pattern(view: pd.DataFrame, bullish: bool = True):
    if len(view) < 45:
        return None
    impulse = view.iloc[-45:-18]
    flag = view.iloc[-18:]
    if len(impulse) < 12 or len(flag) < 10:
        return None
    impulse_ret = float(impulse["Close"].iloc[-1] / impulse["Close"].iloc[0] - 1)
    x = np.arange(len(flag), dtype=float)
    close_slope, _ = np.polyfit(x, flag["Close"].astype(float).to_numpy(), 1)
    high_slope, high_intercept = np.polyfit(x, flag["High"].astype(float).to_numpy(), 1)
    low_slope, low_intercept = np.polyfit(x, flag["Low"].astype(float).to_numpy(), 1)
    price = float(view["Close"].iloc[-1])
    recent_range = (float(flag["High"].max()) - float(flag["Low"].min())) / price if price else 1
    slope_limit = price * 0.004
    if bullish:
        if impulse_ret < 0.12 or close_slope >= slope_limit or recent_range > 0.22:
            return None
        upper_line = high_slope * (len(flag) - 1) + high_intercept
        lower_line = low_slope * (len(flag) - 1) + low_intercept
        status = "돌파" if price > upper_line * 1.005 else "관찰"
        label, direction = f"상승 깃발형 {status}", "bullish"
        trigger_price, invalid_price = upper_line, lower_line * 0.985
    else:
        if impulse_ret > -0.12 or close_slope <= -slope_limit or recent_range > 0.22:
            return None
        upper_line = high_slope * (len(flag) - 1) + high_intercept
        lower_line = low_slope * (len(flag) - 1) + low_intercept
        status = "이탈" if price < lower_line * 0.995 else "관찰"
        label, direction = f"하락 깃발형 {status}", "bearish"
        trigger_price, invalid_price = lower_line, upper_line * 1.015
    start_time, end_time = flag.index[0], flag.index[-1]
    return {
        "name": "상승 깃발형" if bullish else "하락 깃발형",
        "label": label,
        "direction": direction,
        "status": status,
        "confidence": abs(impulse_ret) * 0.5 + (0.02 if status in {"돌파", "이탈"} else 0),
        "created_pos": len(view) - 1,
        "trigger_price": trigger_price,
        "invalid_price": invalid_price,
        "label_x": end_time,
        "label_y": price,
        "line_points": [
            ((start_time, high_intercept), (end_time, high_slope * (len(flag) - 1) + high_intercept)),
            ((start_time, low_intercept), (end_time, low_slope * (len(flag) - 1) + low_intercept)),
        ],
    }


def detect_chart_pattern_candidates(df: pd.DataFrame, lookback: int = 140, max_patterns: int = 1) -> list:
    """최근 OHLC 피벗으로 차트 패턴 후보를 보수적으로 탐지합니다."""
    view = _chart_pattern_source_df(df, lookback=lookback)
    if view.empty:
        return []
    highs, lows = _chart_pattern_pivots(view)
    candidates = [
        _detect_double_pattern(view, highs, lows, "bottom"),
        _detect_double_pattern(view, highs, lows, "top"),
        _detect_head_shoulders_pattern(view, highs, lows, inverse=True),
        _detect_head_shoulders_pattern(view, highs, lows, inverse=False),
        _detect_triangle_pattern(view, highs, lows),
        _detect_flag_pattern(view, bullish=True),
        _detect_flag_pattern(view, bullish=False),
    ]
    patterns = [p for p in candidates if p and p.get("confidence", 0) >= 0.035]
    patterns.sort(key=lambda item: item.get("confidence", 0), reverse=True)
    unique = []
    seen = set()
    for pattern in patterns:
        name = pattern.get("name")
        if name in seen:
            continue
        unique.append(pattern)
        seen.add(name)
    return _finalize_chart_pattern_candidates(view, unique, max_patterns=max_patterns)


def _build_recent_trendline_guides(df: pd.DataFrame, lookback: int = 140) -> list:
    view = _chart_pattern_source_df(df, lookback=lookback)
    if view.empty:
        return []
    highs, lows = _chart_pattern_pivots(view)
    last_pos = len(view) - 1
    current = clean_float(view["Close"].iloc[-1], np.nan)
    if not finite_num(current) or current <= 0:
        return []

    def _fit_line(points, label, color, kind):
        recent = [p for p in points if p["pos"] >= max(0, last_pos - 90)][-5:]
        if len(recent) < 2:
            recent = points[-3:]
        if len(recent) < 2:
            return None
        x = np.array([p["pos"] for p in recent], dtype=float)
        y = np.array([p["price"] for p in recent], dtype=float)
        try:
            slope, intercept = np.polyfit(x, y, 1)
        except Exception:
            return None
        y0 = float(slope * x[0] + intercept)
        y1 = float(slope * last_pos + intercept)
        if not finite_num(y0) or not finite_num(y1) or y0 <= 0 or y1 <= 0:
            return None
        if abs(y1 / current - 1.0) > 0.55:
            return None
        slope_pct = (y1 / y0 - 1.0) if y0 > 0 else 0.0
        if abs(slope_pct) < 0.015:
            direction = "횡보"
        elif slope_pct > 0:
            direction = "상승"
        else:
            direction = "하락"
        return {
            "label": f"{label} {direction}",
            "kind": kind,
            "color": color,
            "x0": view.index[int(x[0])],
            "x1": view.index[-1],
            "y0": y0,
            "y1": y1,
            "direction": direction,
        }

    guides = []
    resistance = _fit_line(highs, "고점선", "#ef4444", "resistance")
    support = _fit_line(lows, "저점선", "#22c55e", "support")
    if resistance:
        guides.append(resistance)
    if support:
        guides.append(support)
    return guides

chart_pattern_price_text = _chart_pattern_price_text
build_recent_trendline_guides = _build_recent_trendline_guides
