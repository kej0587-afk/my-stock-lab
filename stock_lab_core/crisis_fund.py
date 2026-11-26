"""C-8 core crisis fund (user decision 2026-11-26 15:03 KST).

An under-target, non-leveraged core ETF whose close first falls 40% below its own 52-week high starts an episode.
The crisis fund the user set in advance for that ticker is split into 6 equal tranches: the trigger day, then the
first trading day of each of the next 5 months. A tranche is deferred while the market guard stops new buys
(위험·비상) or cannot be confirmed, and runs on the first allowed day. At most one tranche per ticker per exchange trading day (user rule 2026-11-26 15:13 KST): when a
deferred tranche and a scheduled one fall due together, only the oldest runs and the rest wait for the next allowed
day. Different ETFs may each run one tranche on the same day, within each ticker's own fund and the account cash.
Without a saved fund the ticker is only a candidate. There is no default amount. Regular monthly DCA on PANIC
days keeps its own gate; this module never touches it.

Pure functions only (no Streamlit, no network). Storage lives in crisis_fund_store.
"""
from __future__ import annotations

import math

import pandas as pd

POLICY_VERSION = "crisis_fund_v1_time_split_6_guard_2026-11-26"
TRIGGER_DD = -0.40
REARM_DD = -0.20
TRANCHES = 6
GUARD_OK = "정상"
GUARD_STOP = "시장방어: 신규매수 중단"


def drawdown_52w(df: pd.DataFrame) -> pd.Series:
    """Close vs the rolling 252-day High (the engine's current_dd definition), per day."""
    if not isinstance(df, pd.DataFrame) or df.empty or "Close" not in df or "High" not in df:
        return pd.Series(dtype=float)
    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce").rolling(252, min_periods=1).max()
    return (close / high - 1).dropna()


def latest_episode_start(df: pd.DataFrame):
    """Trigger date of the most recent episode (first close at or below -40%; re-armed above -20%), or None."""
    start, armed = None, True
    for day, dd in drawdown_52w(df).items():
        if armed and dd <= TRIGGER_DD:
            start, armed = pd.Timestamp(day).normalize(), False
        elif not armed and dd > REARM_DD:
            armed = True
    return start


def tranche_schedule(trading_days, start) -> list[dict]:
    """6 tranches: start, then the first trading day of each of the next 5 months.

    A month whose first trading day is not in ``trading_days`` yet is returned with date None (future).
    """
    days = pd.DatetimeIndex(pd.to_datetime(list(trading_days))).normalize().sort_values()
    start = pd.Timestamp(start).normalize()
    out = [{"no": 1, "date": start, "month": str(start.to_period("M"))}]
    for k in range(1, TRANCHES):
        period = start.to_period("M") + k
        in_month = days[days.to_period("M") == period]
        out.append({"no": k + 1, "date": in_month[0] if len(in_month) else None, "month": str(period)})
    return out


def _valid_amount(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def crisis_status(*, eligible: bool, episode_start, schedule, today, fund_total, executed_nos, guard_market,
                  executed_today=False, cash_available=None) -> dict:
    """State of one ticker's crisis fund today.

    eligible: under-target non-leveraged core ETF. fund_total: the user's saved amount (None = 미설정).
    executed_nos: tranche numbers already recorded. guard_market: the Today row's 시장실행상태 (None = 미확인).
    executed_today: a tranche of this ticker was already recorded today (one per day). cash_available: account cash
    left for this tranche (None = 미확인, which keeps it waiting).
    Returns {"state", "text", "due_nos", "amount", "tranche_amount", "next"}.
    """
    base = {"due_nos": [], "amount": 0.0, "tranche_amount": None, "next": None}
    if not eligible or episode_start is None:
        return {**base, "state": "none", "text": "해당 없음"}
    today = pd.Timestamp(today).normalize()
    done = {int(n) for n in (executed_nos or [])}
    due = [t for t in schedule if t["date"] is not None and t["date"] <= today and t["no"] not in done]
    upcoming = [t for t in schedule if t["no"] not in done and t not in due]
    nxt = upcoming[0] if upcoming else None
    next_text = (f"다음 {nxt['no']}/{TRANCHES}회차 {nxt['date'].date() if nxt['date'] is not None else nxt['month'] + ' 첫 거래일'}"
                 if nxt else "")
    start_text = f"−40% 도달 {pd.Timestamp(episode_start).date()}"
    total = _valid_amount(fund_total)
    if total is None:
        return {**base, "state": "candidate", "next": nxt,
                "text": f"후보 · 위기자금 미설정 ({start_text}, 설정하면 6회 분할)"}
    per = total / TRANCHES
    base["tranche_amount"] = per
    if len(done) >= TRANCHES:
        return {**base, "state": "done", "text": f"완료 · 6/6회차 집행 ({start_text})"}
    if not due:
        return {**base, "state": "waiting", "next": nxt, "text": f"대기 · {next_text} ({start_text})"}
    oldest = due[0]["no"]
    waiting = f", 대기 {len(due) - 1}회차" if len(due) > 1 else ""
    if executed_today:
        return {**base, "state": "deferred", "due_nos": [oldest], "next": nxt,
                "text": f"대기 · 오늘 이미 1회차 집행(하루 1회차) · 다음 거래일 {oldest}/{TRANCHES}회차{waiting} · {start_text}"}
    if guard_market != GUARD_OK:
        why = "시장 가드 위험·비상" if guard_market == GUARD_STOP else "시장 가드 미확인"
        return {**base, "state": "deferred", "due_nos": [oldest], "next": nxt,
                "text": f"이연 · {oldest}/{TRANCHES}회차{waiting} ({why}, 풀리는 첫 거래일에 한 회차씩) · {start_text}"}
    cash = _valid_amount(cash_available) if cash_available is not None else None
    if cash is None or cash + 1e-9 < per:
        why = "가용 현금 미확인" if cash_available is None else "가용 현금 부족"
        return {**base, "state": "deferred", "due_nos": [oldest], "next": nxt,
                "text": f"대기 · {oldest}/{TRANCHES}회차{waiting} ({why}) · {start_text}"}
    return {**base, "state": "executable", "due_nos": [oldest], "amount": per, "next": nxt,
            "text": f"실행가능 · {oldest}/{TRANCHES}회차 {per:,.0f}원{waiting} · {start_text}"}


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
