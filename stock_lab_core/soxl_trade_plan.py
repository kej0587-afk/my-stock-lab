"""Independent SOXL price scenarios. Never writes investment decisions or orders."""

import math

import pandas as pd

from stock_lab_core.soxl_short_observation import channel_plan, completed_hour_frame, completed_hour_grid
from stock_lab_core.soxl_five_observation import completed_five_grid, FIVE
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
RULE = "soxl-linked-v1"
OHLC = ["Open", "High", "Low", "Close"]


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def price_plan(entry, stop):
    entry, stop = positive(entry), positive(stop)
    if entry is None or stop is None or stop >= entry:
        return {}
    risk = entry - stop
    return dict(entry=entry, stop=stop, target=entry + risk, risk=risk,
                risk_pct=100 * risk / entry, reward_pct=100 * risk / entry)


def setup_from_channel(frame, channel):
    """Same SOXX support/1R conditions for current display and historical replay."""
    plan, reason = channel_plan(frame, channel)
    if not plan:
        return {}, reason
    if not plan["support_reaction"]:
        return {}, "SOXX 하단 접촉 후 회복 미확인"
    if not plan["one_r_before_target"]:
        return {}, "SOXX 채널 상단까지 1R 공간 부족"
    return plan, "SOXX 1시간 지지 반응 · 1R 공간 확인"


def paired_five(frames, schedule, now):
    grid = completed_five_grid(schedule, now)
    result = {"end": None, "rows": [], "issue": "완료 5분봉 없음"}
    if not len(grid):
        return result
    result["end"] = grid[-1] + FIVE
    for ticker in ("SOXX", "SOXL"):
        frame, issue = completed_hour_frame(frames.get(ticker), grid[-1:])
        close = None if issue or frame.empty else positive(frame.Close.iloc[-1])
        result["rows"].append({"ticker": ticker, "close": close, "issue": issue or ("" if close else "최신 완료 5분봉 결측/지연")})
    result["issue"] = "" if all(r["close"] is not None for r in result["rows"]) else "같은 시각 SOXX/SOXL 5분봉 미확보"
    return result


def build_price_context(frames, hourly, schedule, now):
    grid = completed_hour_grid(schedule, now)
    result = {"plan": {}, "signal": False, "reason": hourly["status"],
              "as_of": hourly.get("as_of"), "session_active": False, "soxl_frame": pd.DataFrame()}
    clock = pd.Timestamp(now)
    session = schedule.loc[(schedule.market_open <= clock) & (schedule.market_close > clock)]
    result["session_active"] = not session.empty
    if not len(grid) or hourly.get("as_of") != grid[-1] + pd.Timedelta(hours=1):
        result["reason"] = "동일 최신 1시간 기준 미확보"
        return result
    frame, issue = completed_hour_frame(frames.get("SOXL"), grid[-140:])
    if issue or frame.empty or frame.tail(1)[OHLC].isna().any().any():
        result["reason"] = "SOXL 동일 시각 1시간 OHLC 미확보"
        return result
    result["soxl_frame"] = frame
    bar = frame.iloc[-1]
    result["plan"] = price_plan(bar.Close, bar.Low)
    setup, reason = setup_from_channel(hourly["frame"], hourly["channel"])
    # New research uses 140 hours; do not silently compare a shorter live window.
    if len(hourly["frame"]) < 140 or hourly["frame"][OHLC].isna().any().any():
        setup, reason = {}, "동일 연구 규칙의 연속 140시간 자료 부족"
    result.update(signal=bool(setup and result["plan"]), reason=reason)
    if not result["plan"]:
        result["reason"] = "SOXL 종가와 신호봉 저가 사이 손절거리 미형성"
    if result["session_active"] and result["as_of"] <= session.market_open.iloc[0]:
        result.update(signal=False, reason="새 정규장의 첫 완료 1시간봉 대기 · 전일 계획 재사용 안 함")
    return result


def size_scenario(plan, equity_usd, cash_usd, budget_pct, allowance_pct, cost_bps=10):
    """Cash-only integer shares, with explicit extra loss assumptions, no hard cap claim."""
    try:
        equity, cash, budget, allowance, cost = map(float, (equity_usd, cash_usd, budget_pct, allowance_pct, cost_bps))
    except (TypeError, ValueError):
        return {}
    if (not plan or not all(math.isfinite(x) for x in (equity, cash, budget, allowance, cost))
            or equity <= 0 or cash < 0 or not 0 < budget <= 100 or not 0 <= allowance < 100
            or not 0 <= cost < 10000):
        return {}
    plan = price_plan(plan.get("entry"), plan.get("stop"))
    if not plan:
        return {}
    entry, stop = plan["entry"], plan["stop"]
    adverse_exit = max(0., stop - entry * allowance / 100)
    unit_cost = entry * (1 + cost / 10000)
    unit_loss = unit_cost - adverse_exit * (1 - cost / 10000)
    if unit_loss <= 0:
        return {}
    shares = max(0, min(math.floor(equity * budget / 100 / unit_loss), math.floor(cash / unit_cost), math.floor(equity / unit_cost)))
    return dict(shares=shares, amount=shares * unit_cost, loss=shares * unit_loss,
                weight_pct=shares * unit_cost / equity * 100, unit_loss=unit_loss)
