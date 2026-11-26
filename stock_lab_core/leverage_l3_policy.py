"""C-3 leveraged L3 policy (2026-11-25, user decision after the C-3 comparison).

Leveraged DCA is not "it fell a lot, so buy". It is:
L2 = the drawdown makes the position a DCA candidate (avg-cost loss reached -12% / -25% / -35% once in this cycle),
L3 = that candidate confirms recovery, and one tranche of a pre-set budget is executed.

One drawdown/DCA cycle holds the state (``LeverageDcaCycle``). It is rebuilt from completed daily bars, so the
same history always gives the same state (no hidden memory).

Cycle rules
- Start: the first completed bar with drawdown from the 52-week high <= -10% while no cycle is open.
- L2 qualification: any bar in the cycle with close / average cost - 1 <= -12%. It stays recorded after the
  price recovers; L3 does not ask for the current loss to still be -12%.
- Panic latch: a bar with drawdown from the 52-week high <= -50% sets ``panic_latched``. The 52-week high only
  triggers the latch. A lower 52-week high (old peak leaving the window) never releases it. Release needs, on one
  bar: underlying regime 상승 (close > 200-day average, 200-day average up over 20 days), underlying and leveraged
  ETF both above MA50, recovery check >= 4/6.
- End (state cleared): the position is closed (quantity 0), or the cycle is over: a close at a new 52-week high
  (above every close of the past year) while the panic latch is released. Target weight filled or zero does not
  end the cycle; it only blocks L3 while it lasts (tranches used stay counted).

L3 rule (every condition on the same completed bar)
- not market defense, underlying above MA50, leveraged ETF above MA50, recovery check >= 4/6,
- L2 qualified in this cycle, panic latch released, no current panic (-50%),
- existing blocks clear: daily drop, overheat, macro, data, weight (target zero/filled),
- tranches used < 3, at least 20 completed trading days after the last recorded tranche (user decision, option A),
- a pre-set leveraged DCA budget exists. Without one the row is an L3 candidate, never executable.
Tranche amount = min(budget / 3, budget - invested, target shortfall - this month's monthly plan amount for the
same ticker). The monthly plan amount is subtracted so the regular monthly contribution and the crisis budget
never fill the same shortfall twice.

Stored state (Supabase ``leverage_dca_cycles`` / ``leverage_dca_tranches``, see ``db_schema``)
- The budget and the tranches actually executed live in the store; everything else is rebuilt from bars.
- A tranche is counted only when the user records it in the app (insert-only audit row, unique per
  cycle_id + tranche_no). Showing the signal, reruns, refreshes or viewing the panel never consume a tranche.
- A record applies only to the cycle it was written for (``cycle_id`` = ticker + cycle start). A cycle that
  ends normally (new 52-week closing high with the latch released, or position closed) starts the next one
  with no tranches and no cooldown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

CYCLE_START_DD = -0.10
L2_PNL_STAGES = ((-0.35, "강하락"), (-0.25, "중하락"), (-0.12, "약하락"))
PANIC_DD = -0.50
RECOVERY_MIN = 4
MAX_TRANCHES = 3
TRANCHE_FRACTION = 1.0 / 3.0
MIN_BARS_BETWEEN = 20  # user decision 2026-11-25 (option A): >= 20 completed trading days after the last recorded tranche
POLICY_VERSION = "C3-2026-11-25"

STATUS_NO_CYCLE = "사이클 없음"
STATUS_EXECUTABLE = "L3 실행가능"
STATUS_CANDIDATE = "L3 후보"
STATUS_WAIT = "L3 대기"


@dataclass
class Bar:
    """One completed daily bar. Missing values stay None (미확인), never 0."""
    date: str
    close: float | None
    dd52: float | None              # close / 52-week high close - 1
    new_52w_high: bool = False      # close above every close of the previous 252 bars
    pnl: float | None = None        # close / average cost - 1
    market_defense: bool | None = None
    underlying_above_ma50: bool | None = None
    leveraged_above_ma50: bool | None = None
    recovery_passed: int | None = None
    underlying_regime: str = "미확인"
    has_pos: bool = True
    blocks: tuple[str, ...] = ()    # existing blocks on this bar (daily drop, overheat, macro, data, weight)


@dataclass
class LeverageDcaCycle:
    active: bool = False
    start: str = ""
    l2_qualified: bool = False
    l2_date: str = ""
    l2_stage: str = ""
    panic_latched: bool = False
    latch_date: str = ""
    unlatch_date: str = ""
    tranches_used: int = 0
    invested: float = 0.0
    last_tranche_bar: int = -10 ** 9
    tranche_dates: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("last_tranche_bar", None)
        return d


def _finite(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def l2_stage_for(pnl) -> str:
    if not _finite(pnl):
        return ""
    for limit, label in L2_PNL_STAGES:
        if pnl <= limit:
            return label
    return ""


def recovery_confirmed(bar: Bar) -> bool:
    return (bar.market_defense is False and bar.underlying_above_ma50 is True
            and bar.leveraged_above_ma50 is True and _finite(bar.recovery_passed)
            and int(bar.recovery_passed) >= RECOVERY_MIN)


def latch_release_ok(bar: Bar) -> bool:
    return (bar.underlying_regime == "상승" and bar.underlying_above_ma50 is True
            and bar.leveraged_above_ma50 is True and _finite(bar.recovery_passed)
            and int(bar.recovery_passed) >= RECOVERY_MIN)


def tranche_amount(budget, invested, shortfall, monthly_planned=0.0):
    """Amount for one tranche, or None when it cannot be known (missing budget or shortfall)."""
    if not _finite(budget) or float(budget) <= 0 or not _finite(shortfall):
        return None
    monthly = float(monthly_planned) if _finite(monthly_planned) else 0.0
    room = float(shortfall) - max(monthly, 0.0)
    amt = min(float(budget) * TRANCHE_FRACTION, float(budget) - float(invested or 0.0), room)
    return max(amt, 0.0)


def step(cycle: LeverageDcaCycle, bar: Bar, i: int, *, budget=None, shortfall=None, monthly_planned=0.0,
         execute: bool = False) -> dict:
    """Advance the cycle by one completed bar and return the L3 read for that bar.

    ``execute`` is only used by replays: when True an executable tranche is counted as bought."""
    events = []
    if not bar.has_pos:
        if cycle.active:
            events.append("포지션 종료: 사이클 초기화")
        cycle.__init__()
        return {"status": STATUS_NO_CYCLE, "reasons": ["미보유"], "events": events, "amount": None}
    if not cycle.active:
        if _finite(bar.dd52) and bar.dd52 <= CYCLE_START_DD:
            cycle.__init__()
            cycle.active = True; cycle.start = bar.date
            events.append(f"사이클 시작 (52주 고점 대비 {bar.dd52*100:.1f}%)")
        else:
            return {"status": STATUS_NO_CYCLE, "reasons": ["낙폭 -10% 미만"], "events": events, "amount": None}
    elif bar.new_52w_high and not cycle.panic_latched:
        events.append("사이클 종료: 52주 신고가 종가 (패닉 latch 해제 상태)")
        cycle.__init__()
        return {"status": STATUS_NO_CYCLE, "reasons": ["사이클 종료"], "events": events, "amount": None}

    stage = l2_stage_for(bar.pnl)
    if stage:
        if not cycle.l2_qualified:
            cycle.l2_qualified = True; cycle.l2_date = bar.date; cycle.l2_stage = stage
            events.append(f"L2 자격 ({stage}, 평단 대비 {bar.pnl*100:.1f}%)")
        elif _rank(stage) > _rank(cycle.l2_stage):
            cycle.l2_stage = stage
    if _finite(bar.dd52) and bar.dd52 <= PANIC_DD and not cycle.panic_latched:
        cycle.panic_latched = True; cycle.latch_date = bar.date; cycle.unlatch_date = ""
        events.append(f"패닉 latch (52주 고점 대비 {bar.dd52*100:.1f}%)")
    elif cycle.panic_latched and latch_release_ok(bar) and not (_finite(bar.dd52) and bar.dd52 <= PANIC_DD):
        cycle.panic_latched = False; cycle.unlatch_date = bar.date
        events.append("패닉 latch 해제 (기초 상승장 + MA50 둘 다 + 회복 4/6)")

    reasons = []
    if bar.market_defense is not False:
        reasons.append("시장방어" if bar.market_defense else "시장상태 미확인")
    if bar.underlying_above_ma50 is not True:
        reasons.append("기초 MA50 아래" if bar.underlying_above_ma50 is False else "기초 MA50 미확인")
    if bar.leveraged_above_ma50 is not True:
        reasons.append("레버리지 MA50 아래" if bar.leveraged_above_ma50 is False else "레버리지 MA50 미확인")
    if not (_finite(bar.recovery_passed) and int(bar.recovery_passed) >= RECOVERY_MIN):
        reasons.append(f"회복 {bar.recovery_passed if _finite(bar.recovery_passed) else '미확인'}/6")
    if not cycle.l2_qualified:
        reasons.append("L2 자격 없음")
    if cycle.panic_latched:
        reasons.append("패닉 latch")
    reasons.extend(bar.blocks)
    if cycle.tranches_used >= MAX_TRANCHES:
        reasons.append("3회차 소진")
    gap = i - cycle.last_tranche_bar
    if gap < 1:
        reasons.append("같은 완료봉")
    elif gap < MIN_BARS_BETWEEN:
        reasons.append(f"마지막 실행 후 {gap}거래일 (20거래일 미만)")
    if reasons:
        return {"status": STATUS_WAIT, "reasons": reasons, "events": events, "amount": None}

    amt = tranche_amount(budget, cycle.invested, shortfall, monthly_planned)
    if amt is None:
        why = "레버리지 DCA 예산 미설정" if not (_finite(budget) and float(budget) > 0) else "목표비중 부족분 미확인"
        return {"status": STATUS_CANDIDATE, "reasons": [why], "events": events, "amount": None}
    if amt <= 0:
        why = "사전 예산 소진" if float(budget) - cycle.invested <= 0 else "목표비중 부족분 없음"
        return {"status": STATUS_CANDIDATE, "reasons": [why], "events": events, "amount": 0.0}
    out = {"status": STATUS_EXECUTABLE, "reasons": [], "events": events, "amount": amt,
           "tranche": cycle.tranches_used + 1}
    if execute:
        cycle.tranches_used += 1; cycle.invested += amt; cycle.last_tranche_bar = i
        cycle.tranche_dates.append(bar.date)
        events.append(f"L3 {cycle.tranches_used}회차 실행 {amt:,.1f}")
    return out


def _rank(stage: str) -> int:
    return {"약하락": 1, "중하락": 2, "강하락": 3}.get(stage, 0)


def replay(bars: list[Bar], *, budget=None, shortfall_fn=None, monthly_planned=0.0, execute=False):
    """Run the cycle over completed bars. Returns (final cycle, per-bar reads)."""
    cycle = LeverageDcaCycle(); reads = []
    for i, bar in enumerate(bars):
        shortfall = shortfall_fn(cycle) if callable(shortfall_fn) else shortfall_fn
        r = step(cycle, bar, i, budget=budget, shortfall=shortfall, monthly_planned=monthly_planned,
                 execute=execute)
        r["date"] = bar.date; r["cycle"] = cycle.to_dict()
        reads.append(r)
    return cycle, reads


# --- history -> bars (used by the app; past bars only rebuild the cycle state) ---------------------------------

def build_history_bars(lev_close, axis_close, bench_close=None, *, avg_cost=None):
    """Completed daily bars from close series. Past bars carry no market state (None = 미확인), so they can
    only move the cycle (start, L2, latch, release, end); the app overrides the last bar with live values.

    Recovery check n/6 on past bars is an approximation of the app's checks (MA20, MA50, MA120, MACD above
    signal, RS vs benchmark not falling over 10 days, underlying 1W >= 0); the last bar uses the app's own count."""
    import numpy as np
    import pandas as pd

    p = pd.to_numeric(pd.Series(lev_close), errors="coerce").dropna()
    p = p[p > 0]
    if len(p) < 60:
        return []
    u = pd.to_numeric(pd.Series(axis_close), errors="coerce").reindex(p.index).ffill() if axis_close is not None else None
    hi = p.rolling(252, min_periods=60).max()
    prev_hi = p.shift(1).rolling(252, min_periods=60).max()
    ma20, ma50, ma120 = (p.rolling(n).mean() for n in (20, 50, 120))
    ema12, ema26 = p.ewm(span=12, adjust=False).mean(), p.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_up = macd > macd.ewm(span=9, adjust=False).mean()
    if bench_close is not None:
        b = pd.to_numeric(pd.Series(bench_close), errors="coerce").reindex(p.index).ffill()
        rs = (p / b).rolling(10).mean()
        rs_ok = rs >= rs.shift(10)
    else:
        rs_ok = pd.Series(False, index=p.index)
    if u is not None:
        u_ma50, u_ma200 = u.rolling(50).mean(), u.rolling(200).mean()
        u_1w = u / u.shift(5) - 1
        u_above = (u > u_ma50).where(u_ma50.notna())
        regime = np.where(u_ma200.isna() | u_ma200.shift(20).isna(), "미확인",
                          np.where((u > u_ma200) & (u_ma200 > u_ma200.shift(20)), "상승",
                                   np.where((u < u_ma200) & (u_ma200 < u_ma200.shift(20)), "하락", "횡보")))
    else:
        u_above = pd.Series(np.nan, index=p.index); u_1w = pd.Series(np.nan, index=p.index)
        regime = np.array(["미확인"] * len(p))
    n6 = ((p > ma20).astype(int) + (p > ma50).astype(int) + (p > ma120).astype(int) + macd_up.astype(int)
          + rs_ok.astype(int) + (u_1w >= 0).astype(int))
    bars = []
    for i, (d, close) in enumerate(p.items()):
        ua = u_above.iloc[i]
        bars.append(Bar(
            date=pd.Timestamp(d).date().isoformat(), close=float(close),
            dd52=float(close / hi.iloc[i] - 1) if np.isfinite(hi.iloc[i]) else None,
            new_52w_high=bool(np.isfinite(prev_hi.iloc[i]) and close > prev_hi.iloc[i]),
            pnl=(float(close) / float(avg_cost) - 1) if _finite(avg_cost) and float(avg_cost) > 0 else None,
            market_defense=None,
            underlying_above_ma50=None if pd.isna(ua) else bool(ua),
            leveraged_above_ma50=None if pd.isna(ma50.iloc[i]) else bool(close > ma50.iloc[i]),
            recovery_passed=int(n6.iloc[i]) if pd.notna(ma120.iloc[i]) else None,
            underlying_regime=str(regime[i]),
        ))
    return bars


def cycle_id_for(ticker: str, start: str) -> str:
    return f"{str(ticker or '').upper()}-{start}"


def apply_record(cycle: LeverageDcaCycle, bars: list[Bar], record: dict | None) -> None:
    """Load the user's recorded tranches into the rebuilt cycle (only explicit records count, never views)."""
    tranches = sorted((record or {}).get("tranches") or [], key=lambda t: int(t.get("tranche_no", 0)))
    if not tranches:
        return
    cycle.tranches_used = len(tranches)
    cycle.invested = float(sum(float(t.get("actual_krw") or 0.0) for t in tranches))
    cycle.tranche_dates = [str(t.get("exec_date")) for t in tranches]
    last_date = cycle.tranche_dates[-1]
    dates = [b.date for b in bars]
    import bisect
    # index of the recorded completed trading day (or the last bar on/before it)
    cycle.last_tranche_bar = bisect.bisect_right(dates, last_date) - 1


def read_current(bars: list[Bar], last_overrides: dict | None = None, *, ticker: str = "", record: dict | None = None,
                 shortfall=None, monthly_planned=None, history_complete=True) -> dict:
    """Rebuild the cycle from past bars, apply the user's recorded tranches for this cycle, then read the last bar.

    ``record`` = {"cycle_id", "budget_krw", "tranches": [{"tranche_no", "exec_date", "actual_krw"}]} from storage.
    Executable needs: a stored budget for this cycle, this month's monthly plan amount, a complete price history,
    and every L3 condition. Reading never records anything."""
    if not bars:
        return {"status": STATUS_NO_CYCLE, "reasons": ["가격 이력 부족"], "events": [], "amount": None, "cycle": {}}
    cycle = LeverageDcaCycle()
    for i, bar in enumerate(bars[:-1]):
        step(cycle, bar, i)
    last = bars[-1]
    if last_overrides:
        last = Bar(**{**last.__dict__, **{k: v for k, v in last_overrides.items() if k in last.__dict__}})
    # A cycle can start on the last bar itself; peek with a copy to know its id.
    probe = LeverageDcaCycle(**{k: (list(v) if isinstance(v, list) else v) for k, v in cycle.__dict__.items()})
    step(probe, last, len(bars) - 1)
    cid = cycle_id_for(ticker, probe.start) if probe.active else ""
    rec = record if record and cid and str(record.get("cycle_id", "")) == cid else None
    if rec:
        apply_record(cycle, bars, rec)
    budget = rec.get("budget_krw") if rec else None
    if _finite(budget) and monthly_planned is None:
        res = step(cycle, last, len(bars) - 1, budget=None, shortfall=shortfall)
        if res["status"] == STATUS_CANDIDATE:
            res["reasons"] = ["이번 달 확정 월적립 계획 없음·미확인 (월 적립 계산기에서 계획 확정)"]
    else:
        res = step(cycle, last, len(bars) - 1, budget=budget, shortfall=shortfall,
                   monthly_planned=monthly_planned or 0.0)
    if cycle.active and not history_complete:
        if res["status"] == STATUS_EXECUTABLE:
            res = {**res, "status": STATUS_CANDIDATE}
            res["reasons"] = []
        res["reasons"] = list(res.get("reasons", [])) + ["사이클 시작이 가격 이력보다 앞설 수 있음"]
    res["cycle"] = cycle.to_dict()
    res["cycle_id"] = cid
    res["record"] = rec or {}
    res["bar_date"] = last.date
    res["monthly_planned"] = monthly_planned
    res["shortfall"] = shortfall
    res["planned"] = tranche_amount(budget, cycle.invested, shortfall, monthly_planned) if _finite(budget) else None
    res["l3_ready"] = res["status"] in {STATUS_CANDIDATE, STATUS_EXECUTABLE}
    # C-5 (display only): the inputs the L3 rule just read, for the precision panel. Nothing reads these back.
    res["last_bar"] = {"underlying_above_ma50": last.underlying_above_ma50, "leveraged_above_ma50": last.leveraged_above_ma50,
                       "recovery_passed": last.recovery_passed}
    gap = (len(bars) - 1) - cycle.last_tranche_bar
    res["bars_since_last_tranche"] = gap if cycle.tranches_used and gap >= 0 else None
    return res


def tranche_record_payload(read: dict, actual_krw, *, ticker: str, account_mode: str = "total") -> tuple[dict | None, str]:
    """Validate a user's explicit 'I executed this tranche' record. Returns (payload, error)."""
    if (read or {}).get("status") != STATUS_EXECUTABLE:
        return None, "L3 실행가능 상태가 아니라 기록할 수 없습니다."
    planned = read.get("amount")
    if not _finite(actual_krw) or float(actual_krw) <= 0:
        return None, "실제 실행 금액을 입력하세요."
    if not _finite(planned) or float(actual_krw) > float(planned) + 1e-6:
        return None, f"실제 금액이 이번 회차 실행가능액({planned:,.0f}원)을 넘습니다."
    cyc = read.get("cycle") or {}
    conditions = {"reasons_clear": True, "bar_date": read.get("bar_date"), "l2_date": cyc.get("l2_date"),
                  "l2_stage": cyc.get("l2_stage"), "panic_latched": cyc.get("panic_latched"),
                  "unlatch_date": cyc.get("unlatch_date"), "summary": summary_text(read)}
    return {
        "account_mode": account_mode, "ticker": str(ticker).upper(), "cycle_id": read.get("cycle_id"),
        "tranche_no": int(read.get("tranche") or (cyc.get("tranches_used", 0) + 1)),
        "exec_date": read.get("bar_date"), "planned_krw": float(planned), "actual_krw": float(actual_krw),
        "shortfall_krw": float(read["shortfall"]) if _finite(read.get("shortfall")) else None,
        "monthly_plan_krw": float(read["monthly_planned"]) if _finite(read.get("monthly_planned")) else None,
        "conditions": conditions, "policy_version": POLICY_VERSION,
    }, ""


def summary_text(read: dict) -> str:
    """One line for the decision reasons and the precision panel."""
    if not read:
        return ""
    cyc = read.get("cycle") or {}
    status = read.get("status", "")
    if status == STATUS_NO_CYCLE:
        return "L3 사이클 없음 (52주 고점 대비 -10% 미만 또는 사이클 종료)"
    parts = [{STATUS_CANDIDATE: "L3 후보", STATUS_EXECUTABLE: "L3 실행가능"}.get(status, "L3 대기")]
    parts.append(f"사이클 {cyc.get('start') or '-'} 시작")
    parts.append(f"L2 자격 {cyc.get('l2_date')}({cyc.get('l2_stage')})" if cyc.get("l2_qualified") else "L2 자격 없음")
    if cyc.get("panic_latched"):
        parts.append(f"패닉 latch {cyc.get('latch_date')}")
    elif cyc.get("unlatch_date"):
        parts.append(f"latch 해제 {cyc.get('unlatch_date')}")
    reasons = read.get("reasons") or []
    if reasons:
        parts.append(("실행 안 함: " if status == STATUS_CANDIDATE else "남은 조건: ") + ", ".join(reasons[:4]))
    if status == STATUS_EXECUTABLE and _finite(read.get("amount")):
        parts.append(f"{read.get('tranche')}회차 실행가능액 {read['amount']:,.0f}원")
    return " · ".join(parts)


def l3_panel_rows(read: dict) -> list[dict]:
    cyc = read.get("cycle") or {}
    status = read.get("status", "")
    rows = [
        ("L3 판독", status or "-"),
        ("기초축", read.get("axis") or "-"),
        ("사이클", f"{cyc.get('start')} 시작" if cyc.get("active") else "열린 사이클 없음"),
        ("L2 자격", f"{cyc.get('l2_date')} ({cyc.get('l2_stage')})" if cyc.get("l2_qualified") else "없음"),
        ("패닉 latch", f"유지 ({cyc.get('latch_date')} 발동)" if cyc.get("panic_latched")
         else (f"해제 ({cyc.get('unlatch_date')})" if cyc.get("unlatch_date") else "없음")),
        ("회차", f"{cyc.get('tranches_used', 0)}/{MAX_TRANCHES} 사용"
                 + (f" · 마지막 {cyc['tranche_dates'][-1]}" if cyc.get("tranche_dates") else "")),
        ("사전 예산", f"{float((read.get('record') or {}).get('budget_krw')):,.0f}원"
                    if _finite((read.get('record') or {}).get('budget_krw')) else "미설정"),
        ("이번 회차 실행가능액", f"{read['planned']:,.0f}원" if _finite(read.get("planned")) else "-"),
        ("실행 조건", "시장방어 아님 · 기초 MA50 위 · 레버리지 MA50 위 · 회복 4/6 이상 · 기존 차단 없음 · "
                      "마지막 실행 후 20거래일 이상 · 월적립 배분 확인"),
        ("남은 조건 / 실행 안 하는 이유", ", ".join(read.get("reasons") or []) or "-"),
    ]
    return [{"항목": k, "내용": v} for k, v in rows]
