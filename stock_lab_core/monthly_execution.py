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
                    The MTF-damage exception for core DCA (D) is NOT active here; it waits for the step-4 comparison.
  long-term stock : C1 - only 실행가능.
  swing           : C1.
  leverage        : C1 (the leveraged safety conditions are already in the Today gate).
"""
import math
import re
from datetime import datetime, timedelta, timezone

POLICY_VERSION = "monthly_execution_v1_2026-11-26"
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


def monthly_gate(htype, gate_state, gate_reason):
    """(allowed, reason). allowed is None when the gate is unknown (no valid Today record)."""
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


def execution_key(*, account_scope, month_key, ticker, exec_date, signal_key):
    """Idempotency key: the same signal on the same day can be recorded once (duplicate insert is refused)."""
    return "|".join(str(v) for v in (account_scope, month_key, str(ticker).upper(), exec_date, signal_key or "-"))


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
