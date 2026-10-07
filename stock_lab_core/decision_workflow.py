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
    if any(word in grade for word in ("후보제외", "매수금지", "방어", "신규금지", "추매금지", "손절점검", "원인점검")):
        group = "caution"
    elif is_dashboard_block_or_wait_label(timing):
        group = "caution"
    elif is_dashboard_actionable_signal(c) or "R/R<1" in grade or "🟡정찰" in grade:
        group = "buyish"
    else:
        group = c.get("decision_group") or classify_decision_signal(timing)

    code = str(c.get("decision_code", "") or "")
    defensive_pattern = code.startswith("HARD_BLOCK") or code == "TARGET_ZERO_NO_ADD" or is_today_queue_defense_signal(c, pattern_timing)
    if pattern_bucket in {"interest", "wait"} and not defensive_pattern:
        group = "buyish"
    final_read = build_dashboard_final_read(c, timing, grade, pattern_timing, pattern_bucket)
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
        "데이터상태": "OK",
        **build_today_queue_execution_snapshot(
            name, ticker, c, has_pos=has_pos, usdkrw_value=usdkrw_value,
            is_leveraged_product_fn=is_leveraged_product_fn,
        ),
    }
    row.update(build_execution_gate(row))
    return row


def partition_today_queue(df: pd.DataFrame, reason_bucket: pd.Series) -> dict[str, pd.Series]:
    """Route each row once; an executable gate always enters the execution tab."""
    index = df.index
    state = df.get("게이트상태", pd.Series("", index=index)).fillna("")
    reason = reason_bucket.reindex(index).fillna("일반")
    assigned = pd.Series(False, index=index)
    masks = {}
    rules = {
        "execution": state.eq(GATE_EXECUTABLE),
        "overweight": state.eq(GATE_DEFENSE) & reason.eq("비중초과 방어"),
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
    guard = market_guard or {}
    defensive = {"비상", "위험", "방어", "위험장 반등", "전시장 비상", "국장 비상", "미장 비상"}
    whole = str(guard.get("mode", ""))
    states = []
    for _, row in out.iterrows():
        ticker = str(row.get("티커", ""))
        region = "kr_stats" if is_kr_listed(ticker) else "us_stats"
        local = str((guard.get(region) or {}).get("mode", ""))
        relevant_whole = whole in {"전시장 비상", "비상", "위험", "방어", "위험장 반등"} or whole == ("국장 비상" if region == "kr_stats" else "미장 비상")
        leveraged = is_leveraged_or_inverse_product(str(row.get("종목명", "")), ticker, str(row.get("asset_class", "")))
        timing = str(row.get("🔥기술적 타점", ""))
        leveraged = leveraged or "레버리지" in timing or "인버스" in timing
        states.append("레버리지 시장방어" if leveraged and (local in defensive or relevant_whole) else "정상")
    out["시장실행상태"] = states
    return out
