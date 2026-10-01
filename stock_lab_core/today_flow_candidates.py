"""Pure helpers for money-flow candidates shown in Today Queue."""

from __future__ import annotations

import math
import re
from typing import Any


BAD_FLOW_STATES = {"약세 전환", "소외 지속", "급락 경보"}
NON_ACTIONABLE_FLOW_GROUPS = {"매크로"}
NON_TRADABLE_FLOW_TICKERS = {"^VIX", "VIX", "^MOVE", "MOVE"}
CASHLIKE_FLOW_SCOPE_RE = re.compile(r"(금리|단기채|머니마켓|CD\s*금리|CD금리|현금|파킹|SHV)", re.I)


def _row_get(row: Any, key: str, default=None):
    try:
        return row.get(key, default)
    except AttributeError:
        return default


def _num(value, default=math.nan) -> float:
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except Exception:
        return default


def _first_num(row: Any, keys: tuple[str, ...], default=math.nan) -> float:
    for key in keys:
        num = _num(_row_get(row, key, math.nan), math.nan)
        if math.isfinite(num):
            return num
    return default


def normalize_money_flow_state(value) -> str:
    text = str(value or "")
    for mark in ["🔴", "💥", "💚", "🔥", "🚀", "🟡", "⚪", "〰️", "⚡", "🟢", "⬛"]:
        text = text.replace(mark, "")
    return re.sub(r"\s+", " ", text).strip()


def classify_money_flow_candidate_scope(row: Any) -> str:
    """Return whether a money-flow row can become a stock/ETF candidate.

    Macro gauges and cash-like instruments are useful context, but they should
    not appear as "buyable candidates" beside sector/theme ideas.
    """
    ticker = str(_row_get(row, "Ticker", _row_get(row, "ticker", "")) or "").strip().upper()
    group = str(_row_get(row, "구분", "") or "").strip()
    sector = str(_row_get(row, "섹터", "") or "").strip()
    name = str(_row_get(row, "ETF 이름", _row_get(row, "name", "")) or "").strip()
    scope_text = " ".join([ticker, group, sector, name])

    if group in NON_ACTIONABLE_FLOW_GROUPS or ticker in NON_TRADABLE_FLOW_TICKERS:
        return "매크로게이지"
    if CASHLIKE_FLOW_SCOPE_RE.search(scope_text):
        return "현금성게이지"
    return "후보"


def classify_money_flow_radar_label(row: Any, swing_min: float = 5.0) -> str:
    """Compact label for money-flow radar rows.

    This deliberately avoids order-like wording. The radar is a source finder;
    final action is decided later by Today Queue with market mode, R/R, weight,
    and hard-block rules.
    """
    scope = classify_money_flow_candidate_scope(row)
    if scope == "매크로게이지":
        return "📍 매크로게이지"
    if scope == "현금성게이지":
        return "💵 현금성게이지"

    swing = _first_num(row, ("스윙점수",))
    price_level = _first_num(row, ("가격수준",), default=1.0)
    state = normalize_money_flow_state(_row_get(row, "상태", ""))
    if not math.isfinite(swing):
        return "-"
    if swing <= 0 or state in BAD_FLOW_STATES:
        return "❌ 제외"
    if swing < swing_min:
        return "💤 약모멘텀"
    if price_level >= 0.85:
        return "⚠️ 고점관찰"
    return "👀 관심후보"


def classify_flow_candidate_type(row: Any) -> str:
    """Classify a money-flow row for the compact Today Queue shortlist.

    Medium-term bad states should usually be excluded, but a sharp fresh
    rebound still deserves a "recovery tracking" row so the app does not look
    blind on hot semiconductor/crypto reversal days.
    """
    state = normalize_money_flow_state(_row_get(row, "상태", ""))
    accel = _first_num(row, ("가속도", "RS모멘텀"))
    short_accel = _first_num(row, ("단기가속도",))
    ret_1d = _first_num(row, ("1일수익률", "1D"))
    ret_1w = _first_num(row, ("1주수익률", "1W", "5D"))
    ret_2w = _first_num(row, ("2주수익률", "2W"))
    ret_1m = _first_num(row, ("1개월수익률", "1M"))
    ret_3m = _first_num(row, ("3개월수익률", "3M"))
    price_level = _first_num(row, ("가격수준", "고점근접도"))
    flow = _first_num(row, ("돈흐름점수", "테마돈흐름점수"))

    near_high = math.isfinite(price_level) and price_level > 0.90
    safe_zone = math.isfinite(price_level) and 0.30 <= price_level <= 0.90
    accel_ok = math.isfinite(accel) and accel >= 0.05
    ret1m_ok = math.isfinite(ret_1m) and ret_1m > 0
    ret3m_ok = math.isfinite(ret_3m) and ret_3m > 0.05
    flow_swing = math.isfinite(flow) and flow >= 20
    flow_long = math.isfinite(flow) and flow >= 10
    recent_hot = (
        (math.isfinite(ret_1d) and ret_1d >= 0.04)
        or (math.isfinite(ret_1w) and ret_1w >= 0.06)
        or (math.isfinite(ret_2w) and ret_2w >= 0.08)
    )
    fresh_turn = (
        (math.isfinite(short_accel) and short_accel >= 0.03)
        or accel_ok
        or (math.isfinite(ret_1m) and ret_1m >= -0.03 and recent_hot)
    )

    if state in BAD_FLOW_STATES:
        if recent_hot and fresh_turn:
            return "회복추적"
        return "제외"
    if not math.isfinite(accel):
        if recent_hot and (flow_long or math.isfinite(flow)):
            return "회복추적"
        return "관망"
    if near_high:
        return "고점주의"
    if accel_ok and ret1m_ok and flow_swing:
        return "스윙후보"
    if ret3m_ok and safe_zone and flow_long and accel > -0.5:
        return "장기후보"
    if recent_hot and fresh_turn:
        return "회복추적"
    return "관망"
