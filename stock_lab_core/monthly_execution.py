"""Monthly DCA: plan, executed, today executable, remaining (C-6/C-11 step 3, 2026-11-26, user decisions 1, 6, 7).

Pure functions, no Streamlit and no database. Four amounts per ticker and KST month:
  ① plan       : the confirmed plan if one exists for the same account scope and month, else the shared calculation
  ② executed   : sum of this month's execution records (same scope)
  ③ executable : today's amount, within ①−②, the target shortfall, the monthly gate, the sizing cap and cash
  ④ remaining  : ①−②−③ (waits for a later day this month)
Showing ③ never changes ②; only an explicit execution record does. Missing inputs stay None (미확인), never 0.

Monthly gate per holding type (decision 1):
  core ETF        : C2 - the Today gate is 실행가능, or 대기/관찰 for timing reasons only (R/R, overheat, pattern,
                    condition wait, flow). Safety blocks (방어우선, 데이터확인) and leveraged conditional waits block.
                    D (user decision 11-26 12:59 KST, after the step-4 comparison): weekly/monthly trend damage alone
                    does not block core regular DCA for CORE_PULLBACK/NEUTRAL/OVERHEAT/DRAWDOWN/CRASH_DCA. The gate is
                    re-evaluated from the same row with only the damage label removed, so every other block (market
                    defense, macro hard block, macro unknown, data check, weight over/filled, target 0, hard blocks,
                    defense prose) still applies. CORE_STORM_DCA and PANIC_* keep the damage block (C-8/C-9).
                    The Today and precision gates themselves are unchanged; this only feeds the monthly ③.
  long-term stock : C1 - only 실행가능.
  swing           : C1.
  leverage        : C1 (the leveraged safety conditions are already in the Today gate).
"""
import math
import re
from datetime import datetime, timedelta, timezone

POLICY_VERSION = "monthly_execution_v2_core_mtf_exception_2026-11-26"
KST = timezone(timedelta(hours=9))

TYPE_CORE_ETF = "core_etf"
TYPE_STOCK = "long_term_stock"
TYPE_SWING = "swing"
TYPE_LEVERAGE = "leverage"
TYPE_LABELS = {TYPE_CORE_ETF: "코어 ETF", TYPE_STOCK: "장기보유 개별주", TYPE_SWING: "스윙", TYPE_LEVERAGE: "레버리지"}

GATE_EXECUTABLE = "실행가능"
GATE_WAIT = "대기/관찰"
_TIMING_PART = re.compile(r"^(R/R [^·]*|과열/추격금지|조건 확인 대기|하락/저항 패턴 확인 필요|주의 판정은 실행 전 조건 확인|돈흐름 [^·]*)$")
_SCOUT = re.compile(r"1/3|정찰")
MTF_DAMAGE_LABEL = "상위 시간대 경고"
CORE_MTF_EXCEPTION_CODES = frozenset({"CORE_PULLBACK_DCA", "CORE_NEUTRAL_DCA", "CORE_OVERHEAT_DCA",
                                      "CORE_DRAWDOWN_DCA", "CORE_CRASH_DCA"})
CORE_MTF_EXCEPTION_TEXT = "상위 시간대 추세훼손 · 코어 정기적립 정책에 따른 예외 허용"


def kst_month_key(now=None):
    now = now or datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    return now.astimezone(KST).strftime("%Y-%m")


def holding_type(bucket, is_etf):
    bucket = str(bucket or "").strip().lower()
    if bucket == "leverage":
        return TYPE_LEVERAGE
    if bucket == "swing":
        return TYPE_SWING
    if bucket == "core" and bool(is_etf):
        return TYPE_CORE_ETF
    return TYPE_STOCK


def _finite(value):
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def timing_only(reason):
    parts = [p.strip() for p in str(reason or "").split("·") if p.strip()]
    return bool(parts) and all(_TIMING_PART.match(p) for p in parts)


def core_dca_gate_without_mtf_damage(row):
    """D: the Today gate re-evaluated with only the trend-damage label removed (None when D does not apply).

    row is the final Today workflow row (after the market guard). Applies only when the row shows weekly/monthly
    trend damage and its decision code is one of CORE_MTF_EXCEPTION_CODES. Every other gate input is kept, so
    any other safety block present at the same time still decides the result.
    """
    if not isinstance(row, dict) or str(row.get("상위시간대상태") or "") != MTF_DAMAGE_LABEL:
        return None
    if str(row.get("판정코드") or "").upper() not in CORE_MTF_EXCEPTION_CODES:
        return None
    from stock_lab_core.execution_gate import build_execution_gate
    probe = dict(row)
    probe["상위시간대상태"] = ""
    gate = build_execution_gate(probe)
    return {"state": gate.get("게이트상태"), "reason": gate.get("게이트근거"), "mtf_exception": True}


def monthly_gate(htype, gate_state, gate_reason, core_exception=None):
    """(allowed, reason). allowed is None when the gate is unknown (no valid Today record).

    core_exception: the D gate from core_dca_gate_without_mtf_damage, used for core ETFs only.
    """
    if htype == TYPE_CORE_ETF and isinstance(core_exception, dict) and core_exception.get("state"):
        allowed, text = monthly_gate(htype, core_exception.get("state"), core_exception.get("reason"))
        if allowed:
            return True, f"{CORE_MTF_EXCEPTION_TEXT} · {text}"
        return False, f"상위 시간대 추세훼손(코어 예외 대상) · 다른 차단 유지: {text}"
    if not gate_state:
        return None, "게이트 미확인(오늘 점검 기록 없음·계좌/기준일 불일치)"
    if gate_state == GATE_EXECUTABLE:
        return True, "실행가능"
    if htype == TYPE_CORE_ETF and gate_state == GATE_WAIT and timing_only(gate_reason) \
            and "레버리지 조건부" not in str(gate_reason or ""):
        return True, f"타이밍 대기({gate_reason}) · 코어 정기적립은 배율로 반영"
    return False, f"{gate_state}: {gate_reason or '-'}"


def is_scout(sizing):
    return bool(_SCOUT.search(str(sizing or "")))


def four_amounts(*, plan_krw, executed_krw, shortfall_krw, gate_allowed, sizing=None, cash_krw=None):
    """Return ① plan ② executed ③ executable ④ remaining (KRW) and the limiting reason.

    Missing plan or executed -> executable None. The gate, target shortfall and cash only lower ③.
    A scout sizing (1/3) caps the month's executed total at plan/3, so reruns or repeated execution of the
    same signal never pass it. ③ uses min(), so holdings that already include a recorded execution (lower
    shortfall) and the execution log (higher ②) are never subtracted twice.
    """
    out = {"plan": plan_krw if _finite(plan_krw) else None,
           "executed": executed_krw if _finite(executed_krw) else None,
           "executable": None, "remaining": None, "limit": None}
    if out["plan"] is None:
        out["limit"] = "계획 미확인"
        return out
    if out["executed"] is None:
        out["limit"] = "집행 기록 미확인"
        return out
    open_amt = max(0.0, float(out["plan"]) - float(out["executed"]))
    if gate_allowed is None:
        out["limit"] = "게이트 미확인"
        out["remaining"] = open_amt
        return out
    caps = [("월 계획 잔액", open_amt)]
    if not gate_allowed:
        caps.append(("게이트", 0.0))
    if _finite(shortfall_krw):
        caps.append(("목표비중 부족분", max(0.0, float(shortfall_krw))))
    else:
        out["limit"] = "목표비중 부족분 미확인"
        out["remaining"] = open_amt
        return out
    if is_scout(sizing):
        caps.append(("1차 정찰 1/3", max(0.0, float(out["plan"]) / 3.0 - float(out["executed"]))))
    if _finite(cash_krw):
        caps.append(("가용 현금", max(0.0, float(cash_krw))))
    else:
        out["limit"] = "가용 현금 미확인"
        out["remaining"] = open_amt
        return out
    label, value = min(caps, key=lambda kv: kv[1])
    out["executable"] = value
    out["remaining"] = open_amt - value
    out["limit"] = label
    return out


# Standard names (user decision 2026-11-26 16:37 KST), shared by the monthly screen and the execution-rate study.
# Unit: one account scope · ticker · plan month at one reference time.
#   월계획액        plan valid at the reference time (임시 계획 before confirmation)
#   누적 집행기록액  sum of execution records the user saved after buying (never raised by viewing or by ③)
#   남은 계획액      max(0, 월계획액 − 누적 집행기록액); an excess over the plan is shown separately
#   오늘 추가 가능액 the executable amount (four_amounts ③)
#   현재 대기액      남은 계획액 − 오늘 추가 가능액
STD_PLAN = "월계획액"
STD_EXECUTED = "누적 집행기록액"
STD_OPEN = "남은 계획액"
STD_EXCESS = "계획 초과 집행액"
STD_TODAY = "오늘 추가 가능액"
STD_WAIT = "현재 대기액"
STD_APP_RATE = "앱 기록 기준 실제 집행률"
STD_REPLAY_RATE = "재생상 집행 가능률"
NO_TARGET = "대상 없음"


def _won(value):
    return f"{float(value):,.0f}원"


def plan_source_label(plan_src):
    src = str(plan_src or "")
    if src.startswith("확정"):
        return src.replace("확정", "확정 계획", 1)
    if src == "신호 미확인":
        return "미확인 (신호 미확인)"
    return "임시 계획"


def execution_rate(numerator, plan):
    """Share of 월계획액 as text. 대상 없음 when the plan is 0, 미확인 when an input is missing."""
    if not _finite(plan) or not _finite(numerator):
        return "미확인"
    if float(plan) <= 0:
        return NO_TARGET
    return f"{float(numerator) / float(plan) * 100:.1f}%"


def standard_amounts(row, *, executed_status):
    """Display strings in the standard names for one row of build_execution_rows (pure, tested).

    Gate checked and blocked -> "0원 · 차단: …"; a missing input -> "미확인 · …". Records read with none for the
    ticker -> "0원 · 기록 없음"; storage unreadable -> "미확인". Plan 0 -> both rates 대상 없음.
    """
    plan, executed, today = row.get("plan"), row.get("executed"), row.get("executable")
    limit = row.get("limit") or ""
    plan_txt = "미확인" if plan is None else f"{_won(plan)} · {plan_source_label(row.get('plan_src'))}"
    if executed_status != "ok" or executed is None:
        exec_txt = "미확인 (집행 저장소를 읽지 못함)" if executed_status in ("error", "table_missing") else "미확인"
    elif float(executed) == 0:
        exec_txt = "0원 · 기록 없음"
    else:
        exec_txt = _won(executed)
    open_amt = excess = None
    if plan is not None and executed is not None:
        open_amt = max(0.0, float(plan) - float(executed))
        excess = max(0.0, float(executed) - float(plan))
    if plan is not None and float(plan) <= 0:
        today_txt = "0원 · 이번 달 계획 0원(적립 대상 아님)"
    elif today is None:
        today_txt = f"미확인 · {limit}" if limit else "미확인"
    elif float(today) > 0:
        today_txt = f"{_won(today)} (상한: {limit})"
    elif limit == "게이트":
        today_txt = f"0원 · 차단: {row.get('gate_text') or '-'}"
    else:
        today_txt = f"0원 · {limit}" if limit else "0원"
    wait = None if (open_amt is None or today is None) else max(0.0, open_amt - float(today))
    return {STD_PLAN: plan_txt, STD_EXECUTED: exec_txt,
            STD_OPEN: "미확인" if open_amt is None else _won(open_amt),
            STD_EXCESS: _won(excess) if excess else "-",
            STD_TODAY: today_txt, STD_WAIT: "미확인" if wait is None else _won(wait),
            STD_APP_RATE: execution_rate(executed if executed_status == "ok" else None, plan),
            "_open": open_amt, "_wait": wait}


def monthly_totals(rows, *, executed_status):
    """Account-level totals in the standard names for the top-of-screen line (pure, tested).

    A column with any missing value is 미확인 (never a partial sum shown as the total).
    """
    rows = list(rows or [])
    if not rows:
        return {}

    def total(values, missing_reason):
        values = list(values)
        unknown = sum(v is None for v in values)
        if unknown:
            return f"미확인({unknown}종목 {missing_reason})"
        return _won(sum(float(v) for v in values))

    plans = [r.get("plan") for r in rows]
    executed_ok = executed_status == "ok"
    executed = [r.get("executed") for r in rows] if executed_ok else [None] * len(rows)
    opened = [None if p is None or e is None else max(0.0, float(p) - float(e)) for p, e in zip(plans, executed)]
    today = [0.0 if (p is not None and float(p) <= 0) else r.get("executable") for p, r in zip(plans, rows)]
    return {STD_PLAN: total(plans, "계획 미확인"),
            STD_EXECUTED: total(executed, "기록 미확인") if executed_ok else "미확인(집행 기록을 읽지 못함)",
            STD_OPEN: total(opened, "계산 불가"),
            STD_TODAY: total(today, "자료 부족")}


def executed_by_ticker(executions, *, account_scope, month_key):
    """Sum execution records of the same scope and month. Rows of another scope or month are ignored."""
    totals = {}
    for row in executions or []:
        if str(row.get("account_scope")) != str(account_scope) or str(row.get("month_key")) != str(month_key):
            continue
        if not _finite(row.get("amount_krw")):
            continue
        key = str(row.get("ticker", "")).upper()
        totals[key] = totals.get(key, 0.0) + float(row["amount_krw"])
    return totals


def active_confirmed_plan(rows, *, account_scope, month_key):
    """Latest confirmed version per ticker for this scope and month: {TICKER: row}. Older versions stay as history."""
    best = {}
    for row in rows or []:
        if str(row.get("account_scope")) != str(account_scope) or str(row.get("month_key")) != str(month_key):
            continue
        key = str(row.get("ticker", "")).upper()
        if key not in best or int(row.get("plan_version") or 0) > int(best[key].get("plan_version") or 0):
            best[key] = row
    return best


def confirmed_plan_remaining(plans, plan_status, executions, exec_status, *, account_scope, month_key, ticker):
    """Step 5 (L3 link): plan − executed of the latest confirmed plan for the ticker in this scope and month.

    None when storage was not read ("ok" needed for both) or no plan was confirmed this month (L3 stays a
    candidate). 0.0 when the month is confirmed but the ticker got no plan. Never negative.
    """
    if plan_status != "ok" or exec_status != "ok":
        return None
    confirmed = active_confirmed_plan(plans, account_scope=account_scope, month_key=month_key)
    if not confirmed:
        return None
    row = confirmed.get(str(ticker).upper())
    if row is None:
        return 0.0
    if not _finite(row.get("plan_krw")):
        return None
    done = executed_by_ticker(executions, account_scope=account_scope, month_key=month_key).get(str(ticker).upper(), 0.0)
    return max(0.0, float(row["plan_krw"]) - float(done))


def execution_key(*, account_scope, month_key, ticker, exec_date, signal_key):
    """Idempotency key: the same signal on the same day can be recorded once (duplicate insert is refused)."""
    return "|".join(str(v) for v in (account_scope, month_key, str(ticker).upper(), exec_date, signal_key or "-"))


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
