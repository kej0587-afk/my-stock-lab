"""Pure helpers for Today Queue display decisions.

The Streamlit page builds full stock decisions, then this module compresses
them into the few execution fields that belong in the queue table.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from stock_lab_core.decision_engine import is_finite_number
from stock_lab_core.formatters import clean_float, format_currency, is_kr_listed, sanitize_ticker_value


TODAY_QUEUE_EXECUTION_BLOCK_CODES = {
    "REVERSE_TREND_NO_ENTRY", "STRONG_REVERSE_NO_ENTRY", "DOWNTREND_NO_ENTRY",
    "SHORT_OVERHEAT_NO_ENTRY", "NEAR_UPPER_WAIT", "COST_MINUS_15_TREND_RISK",
    "COST_MINUS_15_CAUSE_CHECK", "TREND_RISK_CAUSE_CHECK",
    "PRICE_DRAWDOWN_HOLDING_CHECK", "PRICE_DRAWDOWN_NO_ENTRY",
    "SINGLE_DAY_BREAKDOWN_HOLDING_CHECK", "SINGLE_DAY_BREAKDOWN_NO_ENTRY",
    "STRUCTURE_DAMAGE_HOLDING_CHECK", "STRUCTURE_DAMAGE_NO_ENTRY", "MTF_DAMAGE_NO_ADD",
    "TARGET_ZERO_NO_ADD", "LEVERAGED_DAILY_DROP_NO_ADD", "LEVERAGED_RECOVERY_DCA_BLOCK",
    "HARD_BLOCK_FINANCIAL_F", "HARD_BLOCK_OVERWEIGHT", "HARD_BLOCK_TARGET_FILLED",
    "HARD_BLOCK_MACRO_STORM",
}

TODAY_QUEUE_EXECUTION_WAIT_CODES = {
    "S_UPTREND_WAIT_PULLBACK", "A_UPTREND_SEARCH_ENTRY", "UPTREND_PULLBACK_CONFIRM",
    "OVERHEAT_EXTENSION_WAIT_MA5", "LEADER_MA5_PULLBACK_ENTRY",
    "LEADER_MA5_FAST_PULLBACK_ENTRY", "S_GRADE_OVERHEAT_WAIT",
    "PREMARKET_REBOUND_WAIT", "PREMARKET_REBOUND_HOLDING_WAIT",
    "MTF_OVERHEAT_SCOUT_ONLY", "LEVERAGED_DCA_WAIT_PULLBACK", "LEVERAGED_DCA_OVERHEAT_PASS",
    "LEVERAGED_DCA_CONDITIONAL", "LEVERAGED_RECOVERY_DCA_CONDITIONAL",
    "HOLDING_DCA_CONDITION_MISS", "FUND_OVERSOLD_REBALANCE_REVIEW",
}


def _finite_num(value: Any) -> bool:
    return is_finite_number(value)


def _amount_text(amount_krw: Any, ticker: str, usdkrw_value: Any = 1400.0) -> str:
    amount = clean_float(amount_krw, 0.0)
    if amount <= 0:
        return "-"
    if not is_kr_listed(ticker):
        fx = clean_float(usdkrw_value, 1400.0) or 1400.0
        return f"${amount / fx:,.0f} (≈{amount:,.0f}원)"
    return f"{amount:,.0f}원"


def _is_leveraged_from_callback(
    name: str,
    ticker: str,
    asset_class: str,
    callback: Callable[[str, str, str], bool] | None,
) -> bool:
    if callback is None:
        return False
    try:
        return bool(callback(name, ticker, asset_class))
    except Exception:
        return False


def _compact_action(decision_code: str, decision_label: str, *, is_weight_block: bool,
                    is_hard_blocked: bool, is_wait: bool, is_poor_rr: bool,
                    rr: float, target_is_projection: bool) -> str:
    if decision_code in {"LEVERAGED_DCA_CONDITIONAL", "LEVERAGED_RECOVERY_DCA_CONDITIONAL"}:
        return "조건부 소액 DCA"
    if decision_code in {"LEVERAGED_DCA_OVERHEAT_PASS", "LEVERAGED_RECOVERY_DCA_BLOCK"}:
        return "DCA 대기"
    if is_weight_block:
        return "추가매수 제외"
    if is_hard_blocked:
        return "방어/원인점검"
    if decision_code == "FUND_OVERSOLD_REBALANCE_REVIEW":
        return "소액 리밸런싱"
    if is_poor_rr:
        return "R/R 회복 대기"
    if is_wait:
        return "눌림/종가 확인"
    if _finite_num(rr) and rr < 1.5:
        return "소액 1차만"
    if target_is_projection:
        return "분할/추적"
    if "익절" in decision_label:
        return "익절/추적"
    return "분할 가능"


def _dedup_supports(candidates: list[tuple[str, float]], current_price: float) -> list[tuple[str, float]]:
    candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
    unique_candidates: list[tuple[str, float]] = []
    min_gap = max(current_price * 0.003, 1.0)
    for label, value in candidates:
        if all(abs(value - used_value) > min_gap for _, used_value in unique_candidates):
            unique_candidates.append((label, value))
    return unique_candidates


def _support_candidates(c: dict, current_price: float, stop: float, atr: float) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for label, value in [
        ("MA5", clean_float(c.get("ma5"), 0.0)),
        ("MA20", clean_float(c.get("ma20"), 0.0)),
        ("FVG 상단", clean_float(c.get("fvg_top"), 0.0)),
        ("FVG 하단", clean_float(c.get("fvg_bottom"), 0.0)),
        ("0.5ATR", current_price - atr * 0.5 if atr > 0 else 0.0),
        ("1ATR", current_price - atr if atr > 0 else 0.0),
    ]:
        if _finite_num(value) and stop < float(value) < current_price:
            candidates.append((label, float(value)))
    return _dedup_supports(candidates, current_price)


def build_today_queue_execution_snapshot(
    name: str,
    ticker: str,
    decision: dict | None,
    *,
    has_pos: bool = False,
    usdkrw_value: Any = 1400.0,
    is_leveraged_product_fn: Callable[[str, str, str], bool] | None = None,
) -> dict:
    """Return compact queue-table fields from an existing precision decision."""
    c = decision or {}
    tkr = sanitize_ticker_value(ticker)
    cur = clean_float(c.get("cur_p"), 0.0)
    atr = clean_float(c.get("atr"), 0.0)
    stop = clean_float(c.get("rr_stop"), 0.0)
    target = clean_float(c.get("rr_target"), 0.0)
    rr = clean_float(c.get("rr_ratio"), math.nan)
    if cur > 0 and stop > 0 and target > cur and stop < cur:
        rr = round((target - cur) / (cur - stop), 2)

    target_is_projection = bool(c.get("rr_target_is_projection", False))
    target_text = "-"
    if target > 0:
        target_prefix = "상단 " if target_is_projection else ""
        target_text = f"{target_prefix}{format_currency(target, tkr)}"
    stop_text = format_currency(stop, tkr) if stop > 0 else "-"
    rr_text = f"{rr:.2f}" if _finite_num(rr) and rr > 0 else "-"

    target_w = clean_float(c.get("target_w"), 0.0)
    current_w = clean_float(c.get("current_w"), 0.0)
    weight_gap = max(clean_float(c.get("weight_gap"), target_w - current_w), 0.0)
    buy_amt_krw = clean_float(c.get("buy_amt"), 0.0)
    effective_total_asset = clean_float(c.get("effective_total_asset"), 0.0)
    if buy_amt_krw <= 0 and effective_total_asset > 0 and weight_gap > 0:
        buy_amt_krw = round(effective_total_asset * weight_gap / 100.0, 0)
    amount_text = _amount_text(buy_amt_krw, tkr, usdkrw_value)

    decision_code = str(c.get("decision_code", "") or "")
    decision_label = str(c.get("dec", "") or "")
    pct_b = clean_float(c.get("pct_b"), math.nan)
    pd_zone = str(c.get("pd_zone", "") or "")
    asset_class = str(c.get("asset_class", "") or "")
    is_leveraged_product = bool(c.get("is_leveraged_or_inverse")) or _is_leveraged_from_callback(
        name, tkr, asset_class, is_leveraged_product_fn
    )
    leveraged_label_block = is_leveraged_product and any(
        word in decision_label
        for word in ["추매금지", "매수금지", "매수 금지", "DCA 보류", "회복 전", "원인점검", "원인 점검", "추격금지"]
    )
    is_weight_block = decision_code in {"TARGET_ZERO_NO_ADD", "HARD_BLOCK_OVERWEIGHT", "HARD_BLOCK_TARGET_FILLED"}
    is_hard_blocked = (
        decision_code in TODAY_QUEUE_EXECUTION_BLOCK_CODES
        or decision_code.startswith("HARD_BLOCK")
        or leveraged_label_block
        or any(word in decision_label for word in ["하드차단", "진입보류", "진입 보류", "추매금지", "매수금지", "원인점검", "손절기준"])
    )
    is_wait = (
        decision_code in TODAY_QUEUE_EXECUTION_WAIT_CODES
        or (_finite_num(pct_b) and pct_b >= 0.78 and "Premium" in pd_zone)
        or any(word in decision_label for word in ["대기", "관망", "추격금지"])
    )
    is_poor_rr = _finite_num(rr) and rr < 1.0
    action = _compact_action(
        decision_code,
        decision_label,
        is_weight_block=is_weight_block,
        is_hard_blocked=is_hard_blocked,
        is_wait=is_wait,
        is_poor_rr=is_poor_rr,
        rr=rr,
        target_is_projection=target_is_projection,
    )

    if is_weight_block or is_hard_blocked:
        if is_weight_block:
            entry_text = "추가매수 제외"
            entry_cond = "목표비중 기준 추가 필요 없음"
        else:
            entry_text = "회복 후 재계산"
            entry_cond = "차단 사유 해소 후 정밀관측소 확인"
        return {
            "R/R": rr_text,
            "차트목표": target_text,
            "손절가": stop_text,
            "1차기준": entry_text,
            "1차조건": entry_cond,
            "부족액": amount_text,
            "실행메모": action,
            "RR값": rr if _finite_num(rr) else math.nan,
        }

    if cur <= 0 or stop <= 0 or target <= 0 or stop >= cur:
        return {
            "R/R": rr_text,
            "차트목표": target_text,
            "손절가": stop_text,
            "1차기준": "데이터확인",
            "1차조건": "가격/ATR 재조회 필요",
            "부족액": amount_text,
            "실행메모": "데이터확인",
            "RR값": math.nan,
        }

    supports = _support_candidates(c, cur, stop, atr)
    if (is_wait or is_poor_rr) and supports:
        entry_label, entry_price = supports[0]
        entry_text = format_currency(entry_price, tkr)
        entry_cond = f"{entry_label} 눌림 후 R/R 재계산" if is_poor_rr else f"{entry_label} 눌림 확인 후 1차"
    else:
        entry_text = format_currency(cur, tkr)
        entry_cond = "현재 보유분 유지, 추가 1차는 소액만" if has_pos else "현재가 부근 1차 정찰"

    return {
        "R/R": rr_text,
        "차트목표": target_text,
        "손절가": stop_text,
        "1차기준": entry_text,
        "1차조건": entry_cond,
        "부족액": amount_text,
        "실행메모": action,
        "RR값": rr if _finite_num(rr) else math.nan,
    }
