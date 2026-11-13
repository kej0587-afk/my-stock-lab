"""Completed SOXX five-minute observations; never an execution decision."""

import math

import pandas as pd

from stock_lab_core.soxl_short_observation import completed_hour_frame
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

FIVE = pd.Timedelta(minutes=5)


def completed_five_grid(schedule, now):
    clock = pd.Timestamp(now)
    if clock.tzinfo is None:
        raise ValueError("timezone_required")
    starts = []
    for row in schedule.itertuples():
        opening, closing = pd.Timestamp(row.market_open), pd.Timestamp(row.market_close)
        if opening.tzinfo is None or closing.tzinfo is None or closing <= opening:
            raise ValueError("invalid_exchange_schedule")
        starts.extend(pd.date_range(opening, closing - FIVE, freq="5min").tolist())
    grid = pd.DatetimeIndex(starts, tz="UTC").sort_values().unique()
    return grid[grid + FIVE <= clock]


def build_five_observation(raw, hourly, schedule, now):
    result = {"status": "미연결", "issue": "", "reference_end": hourly.get("as_of"),
              "stop": None, "end": None, "expected_end": None, "close": None,
              "first_low_end": None, "first_close_end": None, "bars": 0}
    plan = hourly.get("plan") or {}
    base = hourly.get("as_of")
    try:
        stop = float(plan["stop"])
        base = pd.Timestamp(base)
        valid = (math.isfinite(stop) and stop > 0 and base.tzinfo is not None
                 and base == hourly.get("expected_end") and base <= pd.Timestamp(now))
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        result["issue"] = "유효한 최신 1시간 계획 미확보 · 5분 비교 보류"
        return result
    result["stop"] = stop
    grid = completed_five_grid(schedule, now)
    session = schedule.loc[(schedule.market_open < base) & (schedule.market_close >= base)]
    if session.empty:
        result["issue"] = "1시간 기준의 정규장 세션 미확인"
        return result
    closing = session.market_close.iloc[-1]
    if len(grid) and grid[-1] >= closing:
        result["issue"] = "다른 거래일 5분봉 · 1시간 기준 갱신 후 비교"
        return result
    # Only bars available AFTER the frozen hourly reference, never back-project a new line.
    grid = grid[(grid >= base) & (grid + FIVE <= closing)]
    if grid.empty:
        result.update(status="관찰 대기", issue="1시간 기준 이후 완료된 정규장 5분봉 없음")
        return result
    result["expected_end"] = grid[-1] + FIVE
    frame, issue = completed_hour_frame(raw, grid)
    frame = frame.reindex(grid)
    required = ["Open", "High", "Low", "Close"]
    if issue or not set(required).issubset(frame.columns) or frame[required].isna().any().any():
        result["issue"] = issue or "기준 이후 5분봉 결측/지연 · 이탈·회복 판단 보류"
        return result
    low_hits, close_hits = frame.Low.lt(stop), frame.Close.lt(stop)
    latest_below = bool(close_hits.iloc[-1])
    result.update(end=grid[-1] + FIVE, close=float(frame.Close.iloc[-1]), bars=len(frame),
                  first_low_end=frame.index[low_hits][0] + FIVE if low_hits.any() else None,
                  first_close_end=frame.index[close_hits][0] + FIVE if close_hits.any() else None)
    if latest_below:
        result["status"] = "5분 종가 이탈 관찰"
    elif close_hits.any():
        result["status"] = "5분 종가 이탈 후 기준선 이상 복귀 관찰"
    elif low_hits.any():
        result["status"] = "저가 이탈만 관찰 · 5분 종가 이탈 없음"
    else:
        result["status"] = "조회 구간 이탈 미관찰"
    return result


def budget_weight(budget_pct, loss_pct):
    """Account loss budget / assumed SOXL loss, capped at 100%; not a recommendation."""
    try:
        budget, loss = float(budget_pct), float(loss_pct)
    except (ValueError, TypeError):
        return None
    if not all(math.isfinite(x) for x in (budget, loss)) or not 0 <= budget <= 100 or not 0 < loss <= 100:
        return None
    return min(100., 100. * budget / loss)
