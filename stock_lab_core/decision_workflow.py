"""Candidate quality, timing display, and execution routing shared by views."""

from __future__ import annotations

import math

import pandas as pd

from stock_lab_core.decision_engine import classify_decision_signal
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK,
    GATE_DEFENSE,
    GATE_EXECUTABLE,
    GATE_WAIT,
    build_execution_gate,
)
from stock_lab_core.asset_classifier import is_leveraged_or_inverse_product
from stock_lab_core.formatters import clean_float, finite_num, is_kr_listed
from stock_lab_core.today_queue import (
    build_dashboard_final_read,
    build_today_queue_execution_snapshot,
    format_dashboard_candidate_grade,
    format_dashboard_reason,
    format_dashboard_timing_label,
    is_dashboard_actionable_signal,
    is_dashboard_block_or_wait_label,
    is_today_queue_defense_signal,
)


def build_decision_workflow(
    name: str,
    ticker: str,
    decision: dict,
    *,
    is_etf: bool = False,
    has_pos: bool = False,
    pattern_timing: str = "",
    pattern_bucket: str = "",
    pattern_reason: str = "",
    sector_rs: str = "-",
    usdkrw_value: float = 1400.0,
    is_leveraged_product_fn=None,
) -> dict:
    """Preserve existing labels while keeping raw quality separate from timing."""
    c = decision
    timing = format_dashboard_timing_label(c)
    grade = format_dashboard_candidate_grade(c)
    candidate_restricted = any(
        word in grade for word in ("후보제외", "매수금지", "방어", "신규금지", "추매금지", "손절점검", "원인점검")
    ) or c.get("decision_group") == "caution"
    if candidate_restricted:
        group = "caution"
    elif is_dashboard_block_or_wait_label(timing):
        group = "caution"
    elif is_dashboard_actionable_signal(c) or "R/R<1" in grade or "🟡정찰" in grade:
        group = "buyish"
    else:
        group = c.get("decision_group") or classify_decision_signal(timing)

    code = str(c.get("decision_code", "") or "")
    defensive_pattern = code.startswith("HARD_BLOCK") or code == "TARGET_ZERO_NO_ADD" or is_today_queue_defense_signal(c, pattern_timing)
    # A chart pattern can nominate a watch candidate, but cannot erase a restriction.
    if pattern_bucket in {"interest", "wait"} and not defensive_pattern and not candidate_restricted:
        group = "buyish"
    final_read = build_dashboard_final_read(c, timing, grade, pattern_timing, pattern_bucket)
    if candidate_restricted and final_read == "✅정밀확인":
        final_read = "🔍관망"
    if str(final_read).startswith(("🛡️", "🚫", "⚪")):
        group = "caution"
    rr = clean_float(c.get("rr_ratio"), math.nan)
    if ((finite_num(rr) and rr < 1.0) or pattern_bucket == "risk") and group == "buyish":
        group = "caution"

    row = {
        "티커": ticker,
        "유형": "ETF" if is_etf else "개별주",
        "후보품질": c.get("grade", ""),
        "후보점수": c.get("t_score", math.nan),
        "📌후보등급": grade,
        "🔥기술적 타점": timing,
        "최종읽기": final_read,
        "핵심근거": format_dashboard_reason(c),
        "판정코드": code,
        "판정분류": group,
        "패턴타점": pattern_timing,
        "패턴근거": pattern_reason,
        "섹터RS": sector_rs,
        "매크로상태": c.get("macro_state", ""),
        "상위시간대상태": c.get("mtf_bias_label", ""),
        "데이터상태": c.get("data_state", "OK"),
        "수급기준": ("최신 거래량 미확인 · MFI " + str(c.get("live_quote", {}).get("mfi_asof") or "미확인")[:10]) if c.get("live_quote", {}).get("volume_status") else "가격·거래량 원자료",
        **build_today_queue_execution_snapshot(
            name, ticker, c, has_pos=has_pos, usdkrw_value=usdkrw_value,
            is_leveraged_product_fn=is_leveraged_product_fn,
        ),
    }
    for key, source in (("RSI", "rsi"), ("MFI", "mfi"), ("볼린저 %B", "pct_b")):
        if source in c:
            row[key] = c[source]
    row.update(build_execution_gate(row))
    return row


def align_precision_final_check_rows(rows, workflow):
    """Keep check scores intact while qualifying entry prose with the gate."""
    out = [dict(row) for row in rows]
    if (workflow or {}).get("게이트상태") == GATE_EXECUTABLE:
        return out
    reason = (workflow or {}).get("게이트근거") or "실행 게이트 재확인 필요"
    for row in out:
        if row.get("점검항목") == "보유상태" and str(row.get("해석", "")).startswith("신규 진입."):
            row["해석"] = f"신규 진입 후보입니다. 실행 조건 해소 전 신규진입은 보류합니다. {reason}."
    return out


def align_precision_entry_plan_rows(rows, workflow):
    """Retain planned prices and sizes, but mark restricted entries conditional."""
    out = [dict(row) for row in rows]
    if (workflow or {}).get("게이트상태") == GATE_EXECUTABLE:
        return out
    reason = (workflow or {}).get("게이트근거") or "실행 게이트 재확인 필요"
    prefix = f"실행 보류 · {reason} · 조건 해소 후 재확인: "
    for row in out:
        if str(row.get("단계", "")).startswith(("1차 진입", "추가 1차", "2차 추가", "3차 예비")):
            detail = str(row.get("조건", ""))
            if not detail.startswith(prefix):
                row["조건"] = prefix + detail
    return out


def qualify_hold_action_plan(action, workflow):
    """Keep holding suitability distinct from today's entry permission."""
    if (workflow or {}).get("게이트상태") == GATE_EXECUTABLE:
        return action
    reason = (workflow or {}).get("게이트근거") or "실행 게이트 미확인"
    return (
        f"현재 신규·추가매수는 실행 보류 · {reason}. "
        f"아래는 개별 종목의 보유 평가이며 현재 매수 허가가 아닙니다: {action}"
    )


def format_precision_take_profit_condition(current_price, stop, target):
    """Describe the existing min(target, entry + risk) first exit accurately."""
    cur, stop, target = (clean_float(value, math.nan) for value in (current_price, stop, target))
    if all(finite_num(value) for value in (cur, stop, target)) and 0 < stop < cur < target < cur + (cur - stop):
        return "1R 미만의 구조 목표가 도달 시 일부 회수, 잔여 손절은 본전 근처로 상향"
    return "1R 도달 시 일부 회수, 잔여 손절은 본전 근처로 상향"


def partition_today_queue(df: pd.DataFrame, reason_bucket: pd.Series) -> dict[str, pd.Series]:
    """Route each row once; an executable gate always enters the execution tab."""
    index = df.index
    state = df.get("게이트상태", pd.Series("", index=index)).fillna("")
    gate_reason = df.get("게이트근거", pd.Series("", index=index)).fillna("")
    reason = reason_bucket.reindex(index).fillna("일반")
    assigned = pd.Series(False, index=index)
    masks = {}
    rules = {
        "execution": state.eq(GATE_EXECUTABLE),
        "overweight": state.eq(GATE_DEFENSE) & (
            reason.eq("비중초과 방어") | gate_reason.eq("목표비중/비중초과 우선")
        ),
        "market_defense": state.eq(GATE_DEFENSE) & (reason.eq("시장방어") | df.get("시장실행상태", pd.Series("", index=index)).str.contains("시장방어", na=False)),
        "price_defense": state.eq(GATE_DEFENSE) & reason.eq("가격방어"),
        "rapid_drop": state.eq(GATE_DEFENSE) & reason.eq("급락방어"),
        "structure": state.eq(GATE_DEFENSE) & (reason.eq("추세방어") | df.get("상위시간대상태", pd.Series("", index=index)).eq("상위 시간대 경고")),
        "overheat": state.eq(GATE_WAIT) & reason.eq("과열/타점대기"),
        "data_issue": state.eq(GATE_DATA_CHECK),
        "wait": state.eq(GATE_WAIT),
    }
    for key, rule in rules.items():
        masks[key] = rule & ~assigned
        assigned |= masks[key]
    masks["other_caution"] = ~assigned
    return masks


def attach_market_execution_context(df: pd.DataFrame, market_guard: dict | None) -> pd.DataFrame:
    """Apply the same regional market restrictions to queue and precision rows."""
    out = df.copy()
    guard = market_guard if isinstance(market_guard, dict) else {}
    defensive = {"비상", "위험", "방어", "위험장 반등", "전시장 비상", "국장 비상", "미장 비상"}
    known_local_modes = {"정상", "주의", "방어", "위험장 반등", "위험", "비상"}
    whole = str(guard.get("mode", ""))
    states = []
    for _, row in out.iterrows():
        ticker = str(row.get("티커", ""))
        region = "kr_stats" if is_kr_listed(ticker) else "us_stats"
        local_stats = guard.get(region)
        local = str(local_stats.get("mode", "")).strip() if isinstance(local_stats, dict) else ""
        relevant_whole = whole in {"전시장 비상", "비상", "위험", "방어", "위험장 반등"} or whole == ("국장 비상" if region == "kr_stats" else "미장 비상")
        leveraged = is_leveraged_or_inverse_product(str(row.get("종목명", "")), ticker, str(row.get("asset_class", "")))
        timing = str(row.get("🔥기술적 타점", ""))
        leveraged = leveraged or "레버리지" in timing or "인버스" in timing
        # A portfolio-wide stop applies to ordinary stocks too. Regional
        # emergencies remain local unless the guard explicitly stops all buys.
        stop_all = "신규매수 중단" in str(guard.get("action", ""))
        stop_local = local in {"비상", "위험"} or whole == (
            "국장 비상" if region == "kr_stats" else "미장 비상"
        ) or whole in {"전시장 비상", "비상", "위험"}
        if stop_all or stop_local:
            states.append("시장방어: 신규매수 중단")
        elif leveraged and (local in defensive or relevant_whole):
            states.append("레버리지 시장방어")
        elif local not in known_local_modes:
            # An aggregate/other-market mode cannot validate missing local data.
            market = "한국" if region == "kr_stats" else "미국"
            states.append(f"시장정보 확인 필요: {market} 지수 데이터 미확인")
        else:
            states.append("정상")
    out["시장실행상태"] = states
    return out
