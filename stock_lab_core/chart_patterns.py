"""Chart pattern and trendline detection helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stock_lab_core.formatters import clean_float, finite_num
from stock_lab_core.today_queue import is_today_queue_defense_signal


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


def chart_pattern_caption(patterns: list) -> str:
    if not patterns:
        return ""
    pattern = patterns[0]
    direction = pattern.get("direction", "neutral")
    lifecycle = pattern.get("lifecycle", "관찰")
    name = pattern.get("name", "패턴")
    trigger = _chart_pattern_price_text(pattern.get("trigger_price"))
    invalid = _chart_pattern_price_text(pattern.get("invalid_price"))
    if lifecycle == "관찰" and direction == "bullish":
        plain = f"{name} 후보: 기준선 돌파 전, 추세 회복 미확정"
        guide = f"기준 {trigger} 위 안착 전까지 추격보다 확인 우선 / 무효 {invalid}"
    elif lifecycle == "현재유효" and direction == "bullish":
        plain = f"{name}: 돌파 후 유효, 추세 회복 확인 구간"
        guide = f"기준 {trigger} 위 유지가 핵심 / 무효 {invalid} 이탈 시 폐기"
    elif lifecycle == "관찰" and direction == "bearish":
        plain = f"{name} 후보: 기준선 이탈 전, 하락 확정 아님"
        guide = f"기준 {trigger} 아래 이탈 전까지 경고만 반영 / 무효 {invalid} 회복 시 폐기"
    elif lifecycle == "현재유효" and direction == "bearish":
        plain = f"{name}: 이탈 후 유효, 반등 실패 확인 구간"
        guide = f"기준 {trigger} 아래 유지가 핵심 / 무효 {invalid} 회복 시 폐기"
    else:
        plain = f"{name} 후보: 방향 확인 전"
        guide = f"기준 {trigger} 돌파/이탈 방향 확인 전까지 관찰"
    return f"핵심 패턴: {plain} · {guide}"


def build_chart_pattern_timing_note(patterns: list, c: dict | None = None) -> dict | None:
    if not patterns:
        return None
    pattern = patterns[0]
    name = pattern.get("name", "패턴")
    direction = pattern.get("direction", "neutral")
    lifecycle = pattern.get("lifecycle", "관찰")
    trigger = _chart_pattern_price_text(pattern.get("trigger_price"))
    invalid = _chart_pattern_price_text(pattern.get("invalid_price"))
    invalid_price = clean_float(pattern.get("invalid_price"), np.nan)
    c = c or {}
    cur_p = clean_float(c.get("cur_p"), np.nan)

    if direction == "bearish" and finite_num(cur_p) and finite_num(invalid_price) and cur_p > invalid_price:
        return {
            "color": "#64748b",
            "title": "ℹ️ 하락 패턴 경고 해제 확인",
            "body": (
                f"현재가 {_chart_pattern_price_text(cur_p)}가 {name} 무효선 {invalid} 위에 있습니다. "
                "수동보정/실시간가 기준으로는 하락 패턴 경고를 낮추고, 다음 봉에서 그 가격대 위에 안착하는지 확인하세요."
            ),
        }

    rsi = clean_float(c.get("rsi"), np.nan)
    mfi = clean_float(c.get("mfi"), np.nan)
    pct_b = clean_float(c.get("pct_b"), np.nan)
    overheat_flags = []
    if finite_num(rsi) and rsi >= 70:
        overheat_flags.append(f"RSI {rsi:.0f}")
    if finite_num(mfi) and mfi >= 80:
        overheat_flags.append(f"MFI {mfi:.0f}")
    if finite_num(pct_b) and pct_b >= 0.95:
        overheat_flags.append(f"%B {pct_b:.2f}")
    overheat_text = " · ".join(overheat_flags)
    defense_priority = direction == "bullish" and is_today_queue_defense_signal(c)
    if defense_priority:
        return {
            "color": "#d97706",
            "title": "👀 패턴은 보조, 방어 신호 우선",
            "body": (
                f"{name} 패턴은 보이지만 현재 기술/가격 판정은 방어 쪽이 우선입니다. "
                f"기준선 {trigger} 위 안착과 거래량, MA20·MA50 회복을 확인하기 전까지는 매수 신호가 아니라 관찰 신호로만 봅니다. "
                f"무효선 {invalid} 이탈 시 패턴을 폐기합니다."
            ),
        }

    if direction == "bullish" and lifecycle == "관찰":
        return {
            "color": "#3b82f6",
            "title": "👀 패턴 선행관찰",
            "body": (
                f"{name} 후보가 생겼지만 기준선 {trigger} 돌파 전입니다. "
                "이 구간은 매수 확정이 아니라 관심 전환/알림 단계입니다. "
                f"기준선 돌파와 거래량 확인, 또는 돌파 후 첫 눌림이 오면 1차 검토로 넘기고 무효선 {invalid} 이탈 시 폐기합니다."
            ),
        }
    if direction == "bullish" and lifecycle == "현재유효":
        if overheat_flags:
            return {
                "color": "#d97706",
                "title": "🚦 패턴 성공 후 과열",
                "body": (
                    f"{name}는 기준선 {trigger} 위에서 유효하지만 현재가는 {overheat_text} 과열권입니다. "
                    "그래서 앱의 '눌림 대기'는 매수 신호가 아니라 선행 타점이 지나간 뒤 추격을 막는 경고입니다. "
                    f"기준선 재확인, MA5/MA20 눌림, FVG 지지 확인 전까지는 정찰 이상을 보류하고 무효선 {invalid} 이탈 시 패턴을 폐기합니다."
                ),
            }
        return {
            "color": "#16a34a",
            "title": "✅ 패턴 돌파 유효",
            "body": (
                f"{name}가 기준선 {trigger} 위에서 유효합니다. "
                "다만 실제 매수 강도는 위 타점 문구, R/R, 상위 시간대 보정까지 같이 봅니다. "
                f"무효선 {invalid} 이탈 시 패턴을 폐기합니다."
            ),
        }
    if direction == "bearish" and lifecycle == "관찰":
        return {
            "color": "#f59e0b",
            "title": "⚠️ 하락 패턴 관찰",
            "body": (
                f"{name} 후보가 있지만 기준선 {trigger} 이탈 전이라 하락 확정은 아닙니다. "
                f"무효선 {invalid} 회복 시 경고를 낮춥니다."
            ),
        }
    if direction == "bearish" and lifecycle == "현재유효":
        return {
            "color": "#dc2626",
            "title": "🛑 하락 패턴 유효",
            "body": (
                f"{name}가 기준선 {trigger} 아래에서 유효합니다. "
                f"반등 매수보다 구조 회복 확인이 우선이고, 무효선 {invalid} 회복 전까지 보수적으로 봅니다."
            ),
        }
    return None


def summarize_chart_pattern_for_dashboard(patterns: list, c: dict | None = None) -> tuple[str, str, str]:
    if not patterns:
        return "-", "", ""
    pattern = patterns[0]
    name = pattern.get("name", "패턴")
    direction = pattern.get("direction", "neutral")
    lifecycle = pattern.get("lifecycle", "관찰")
    trigger = _chart_pattern_price_text(pattern.get("trigger_price"))
    invalid = _chart_pattern_price_text(pattern.get("invalid_price"))
    c = c or {}

    rsi = clean_float(c.get("rsi"), np.nan)
    mfi = clean_float(c.get("mfi"), np.nan)
    pct_b = clean_float(c.get("pct_b"), np.nan)
    overheat = (
        (finite_num(rsi) and rsi >= 70)
        or (finite_num(mfi) and mfi >= 80)
        or (finite_num(pct_b) and pct_b >= 0.95)
    )
    overheat_bits = []
    if finite_num(rsi) and rsi >= 70:
        overheat_bits.append(f"RSI {rsi:.0f}")
    if finite_num(mfi) and mfi >= 80:
        overheat_bits.append(f"MFI {mfi:.0f}")
    if finite_num(pct_b) and pct_b >= 0.95:
        overheat_bits.append(f"%B {pct_b:.2f}")
    overheat_text = " · ".join(overheat_bits) if overheat_bits else "과열 낮음"
    defense_priority = direction == "bullish" and is_today_queue_defense_signal(c)
    if defense_priority:
        return (
            "👀패턴관찰(방어우선)",
            f"{name} 패턴 감지 · 기술/가격 방어 우선 · 기준 {trigger} 안착 확인 전 관찰",
            "risk",
        )

    if direction == "bullish" and lifecycle == "관찰":
        return (
            "👀패턴관찰: 돌파대기",
            f"{name} 후보 · 기준 {trigger} 돌파 전 · 무효 {invalid}",
            "interest",
        )
    if direction == "bullish" and lifecycle == "현재유효":
        if overheat:
            return (
                "🚦패턴성공: 눌림대기",
                f"{name} 유효 · {overheat_text} · 기준 {trigger} 재확인/첫 눌림 대기",
                "wait",
            )
        return (
            "✅패턴유효: 정밀확인",
            f"{name} 유효 · 기준 {trigger} 위 유지 · 무효 {invalid}",
            "interest",
        )
    if direction == "bearish" and lifecycle == "관찰":
        return (
            "⚠️하락패턴 관찰",
            f"{name} 후보 · 기준 {trigger} 이탈 전 · 무효 {invalid}",
            "risk",
        )
    if direction == "bearish" and lifecycle == "현재유효":
        return (
            "🛑하락패턴 유효",
            f"{name} 유효 · 기준 {trigger} 아래 · 회복 전 보수",
            "risk",
        )
    return "-", "", ""


def chart_pattern_annotation_text(pattern: dict) -> str:
    direction = pattern.get("direction", "neutral")
    lifecycle = pattern.get("lifecycle", "관찰")
    name = pattern.get("name", "패턴")
    if lifecycle == "관찰" and direction == "bullish":
        return f"{name} 후보"
    if lifecycle == "현재유효" and direction == "bullish":
        return f"{name} 유효"
    if lifecycle == "관찰" and direction == "bearish":
        return f"{name} 후보"
    if lifecycle == "현재유효" and direction == "bearish":
        return f"{name} 유효"
    return f"{name} 후보<br>방향 확인 전"


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


def trendline_guides_caption(guides: list) -> str:
    if not guides:
        return ""
    parts = []
    for guide in guides:
        side = "저항" if guide.get("kind") == "resistance" else "지지"
        parts.append(f"{side} {guide.get('direction', '-')}")
    return "추세선: " + " · ".join(parts) + " · 가격이 두 선 사이에서 위/아래 어느 쪽을 돌파하는지 봅니다."


chart_pattern_price_text = _chart_pattern_price_text
build_recent_trendline_guides = _build_recent_trendline_guides
