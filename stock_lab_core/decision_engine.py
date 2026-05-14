"""Pure decision helpers for Stock Lab.

The Streamlit app still orchestrates data loading and rendering.  This module
keeps small judgement rules testable and independent from session state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from stock_lab_core.formatters import clean_float


@dataclass(frozen=True)
class CandidateGrade:
    t_score: float
    grade: str


@dataclass(frozen=True)
class DecisionOutcome:
    code: str
    label: str
    color: str
    group: str


def is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def ensure_min_price_rows_for_decision(df: pd.DataFrame) -> pd.DataFrame:
    """Return price data with at least two rows for previous/current checks."""
    if df is None or df.empty:
        raise ValueError("calc_scores_and_decision requires non-empty price data")
    if len(df) >= 2:
        return df
    return pd.concat([df, df.tail(1)], ignore_index=False)


def score_technical_components(
    rs_label: str,
    mfi_now: float,
    trend: str,
    macd_state: str,
    sqz_status: str,
) -> dict:
    rs_s = 2 if rs_label == "🚀강함" else (1 if rs_label == "➖보통" else 0)
    mfi_s = 2 if mfi_now < 30 else (-1 if mfi_now > 80 else 0)
    trend_s = 2 if trend == "🚀정배열(상승)" else 0
    macd_s = 2 if macd_state == "🔥매수신호(골든크로스)" else (
        1 if macd_state == "📈추세유지(상승중)" else (
            -2 if macd_state == "📉하락주의(데드크로스)" else 0
        )
    )
    sqz_s = 1 if (
        sqz_status == "🚀해제직후"
        and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]
    ) else 0
    tech_total = rs_s + mfi_s + trend_s + macd_s + sqz_s
    return {
        "rs_s": rs_s,
        "mfi_s": mfi_s,
        "trend_s": trend_s,
        "macd_s": macd_s,
        "sqz_s": sqz_s,
        "tech_total": tech_total,
    }


def score_main_entry(
    trend: str,
    macd_state: str,
    rsi_now: float,
    day_ret: float,
    vol_ratio: float,
) -> int:
    return (
        (2 if trend == "🚀정배열(상승)" else (1 if trend == "⏳혼조세" else 0)) +
        (2 if macd_state == "🔥매수신호(골든크로스)" else 0) +
        (2 if rsi_now < 35 else (1 if rsi_now < 45 else 0)) +
        (1 if day_ret >= 0 and vol_ratio > 1.2 else (-1 if day_ret < -0.02 and vol_ratio > 1.5 else 0))
    )


def classify_candidate_grade(is_etf: bool, tech_total: float, fin_score: int) -> CandidateGrade:
    if is_etf:
        t_score = tech_total
        if tech_total < 1:
            grade = "⏳ETF 관망"
        elif tech_total < 3:
            grade = "⚖️ETF 보통"
        elif tech_total < 5:
            grade = "✅ETF 양호"
        else:
            grade = "💎ETF 우수"
    else:
        t_score = tech_total + fin_score
        if fin_score == 1:
            grade = "🚨F급 (재무위험/처분)"
        elif t_score < 3:
            grade = "🚨F급 (기술/재무 부진)"
        elif t_score < 5:
            grade = "⏳C급 (주의/대기)"
        elif t_score < 7:
            grade = "⚖️B급 (신중/관망)"
        elif t_score < 9:
            grade = "✅A급 (분할 매수)"
        else:
            grade = "💎S급 (강력 매수)"
    return CandidateGrade(t_score=t_score, grade=grade)


def classify_core_dca_decision(prefix: str, core_dca_rate: float, dca_label: str) -> tuple[str, str]:
    if core_dca_rate <= 0.25:
        return f"{prefix} 과열: {dca_label}", "#d97706"
    if core_dca_rate <= 0.50:
        return f"{prefix} 중립: {dca_label}", "#3b82f6"
    return f"{prefix} 눌림: {dca_label}", "#16a34a"


def classify_decision_signal(decision_label: str) -> str:
    """Classify a visible decision label for dashboard counts.

    Keep this centralized so display wording can change without scattering
    string checks across the app.
    """
    text = str(decision_label or "")
    caution_keywords = [
        "차단", "금지", "위기", "패닉", "역배열", "구조훼손", "대피",
        "처분", "손절", "원인 점검", "하락추세", "추격금지", "보류",
        "극단과열", "단기과열", "과열확장", "밴드상단", "상단부근",
    ]
    if any(keyword in text for keyword in caution_keywords):
        return "caution"

    buyish_keywords = [
        "매수", "진입", "추매", "눌림", "대장주", "정찰", "적립",
        "가능", "허용", "분할", "줍줍", "투입", "돌파",
    ]
    if any(keyword in text for keyword in buyish_keywords):
        return "buyish"
    return "neutral"


DECISION_CODE_BY_LABEL = {
    "🚨하드차단: 재무F급(처분)": "HARD_BLOCK_FINANCIAL_F",
    "🛑하드차단: 비중 초과": "HARD_BLOCK_OVERWEIGHT",
    "⏸️하드차단: 비중 충족(관망)": "HARD_BLOCK_TARGET_FILLED",
    "🛑하드차단: 퍼펙트스톰(대피)": "HARD_BLOCK_MACRO_STORM",
    "💣패닉(-50%↓): 최종투입": "PANIC_FINAL_DEPLOY",
    "💣패닉(-40%↓): 현금 투입": "PANIC_CASH_DEPLOY",
    "🚨위기(-30%↓): 코어 집중": "CRISIS_CORE_FOCUS",
    "⚠️구조훼손: 신규진입 보류": "STRUCTURE_DAMAGE_NO_ENTRY",
    "⚠️고점대비 -20%: 추매금지/손절기준 점검": "DRAWDOWN_20_HOLDING_STOP_CHECK",
    "⚠️고점대비 -20%: 추매금지/원인점검": "DRAWDOWN_20_HOLDING_CAUSE_CHECK",
    "⚠️고점대비 -20%: 신규진입 보류": "DRAWDOWN_20_NO_ENTRY",
    "⚠️구조훼손: 추매금지/손절기준 점검": "STRUCTURE_DAMAGE_HOLDING_CHECK",
    "🟣예외승인: 정찰대 추매(MA5/FVG)": "EXCEPTION_ADD_ON",
    "🟣예외승인: 정찰대 진입(MA5/FVG)": "EXCEPTION_ENTRY",
    "🚫하드차단: MFI 극단 과열": "HARD_BLOCK_MFI_OVERHEAT",
    "⚠️과열확장: 추격금지, MA5 대기": "OVERHEAT_EXTENSION_WAIT_MA5",
    "🔥불뿜는 대장주: MA5 눌림 진입": "LEADER_MA5_PULLBACK_ENTRY",
    "🔥불뿜는 대장주: 초단기 눌림(MA5) 진입": "LEADER_MA5_FAST_PULLBACK_ENTRY",
    "🚫하드차단: 볼린상단 이탈": "HARD_BLOCK_BOLLINGER_UPPER",
    "✅ETF 비중부족 큼: 소액 적립 허용": "ETF_LARGE_GAP_DCA_OK",
    "✅ETF 목표비중 미달: 적립식 매수 가능": "ETF_DCA_OK",
    "✅상승확인: 2차 정찰 추매 가능": "STRENGTH_ADD_ON_OK",
    "⏸️S급이나 비중 충족: 눌림 오면 재진입": "TARGET_FILLED_S_GRADE_WAIT",
    "⏸️비중 충족: 보유 유지": "TARGET_FILLED_HOLD",
    "⏳S급 과열 구간: 식힌 뒤 추가": "S_GRADE_OVERHEAT_WAIT",
    "⏳과열: 눌림 대기": "OVERHEAT_WAIT",
    "✅S급 비중여유: 분할 추가 가능": "S_GRADE_ADD_ON_OK",
    "📈A급 비중여유: 소액 추가 검토": "A_GRADE_ADD_ON_REVIEW",
    "⏳평단이상: 추가 하락 대기": "ABOVE_COST_WAIT_PULLBACK",
    "⏳평단이상: 보유 유지": "ABOVE_COST_HOLD",
    "🔔익절 타이밍: 고평가+과열+수익20%↑ (분할 매도 검토)": "PROFIT_TAKE_REVIEW",
    "🎯S급 눌림목: 추매": "S_PULLBACK_ADD_ON",
    "⚠️단기과열: 추매 보류": "SHORT_OVERHEAT_NO_ADD",
    "🔥낙폭과대: 줍줍 찬스": "OVERSOLD_ADD_ON",
    "💎S급: 과매도(풀매수)": "S_GRADE_OVERSOLD_BUY",
    "🎯A급: 기술적 반등": "A_GRADE_TECH_REBOUND",
    "📈정배열: -3% 이상 눌림 분할매수": "UPTREND_PULLBACK_DCA",
    "⏳평단이상: 하락대기(보유)": "ABOVE_COST_WAIT",
    "⏸️평단이하: 비중 충족(추매 보류)": "BELOW_COST_TARGET_FILLED",
    "⏳평단근처: 추가 하락 대기": "NEAR_COST_WAIT",
    "✅평단 -3~-7%: 소액 분할매수": "COST_MINUS_3_7_DCA",
    "🎯평단 -7~-15%: 조건부 분할매수": "COST_MINUS_7_15_CONDITIONAL_DCA",
    "🚫평단 -15%↓/추세위험: 원인 점검": "COST_MINUS_15_TREND_RISK",
    "⏳보유중(신호대기)": "HOLD_WAIT_SIGNAL",
    "⚠️상단부근: 눌림 대기": "NEAR_UPPER_WAIT",
    "🚀52주 신고가 돌파: 모멘텀 진입 검토": "BREAKOUT_52W_ENTRY",
    "🎯S급 눌림목: 탑승 찬스": "S_PULLBACK_ENTRY",
    "⚠️단기과열: 진입 보류": "SHORT_OVERHEAT_NO_ENTRY",
    "🔥낙폭과대: 신규 진입": "OVERSOLD_NEW_ENTRY",
    "🟢선진입 가능: 반전 초입": "EARLY_REVERSAL_ENTRY",
    "🟢선진입 가능 구간": "EARLY_ENTRY",
    "🆕신규진입: 대장주 포착": "NEW_ENTRY_LEADER",
    "🎯낙폭과대: 분할매수": "OVERSOLD_DCA",
    "⚠️하락추세: 진입보류": "DOWNTREND_NO_ENTRY",
    "🚫진입보류: 역배열 대기": "REVERSE_TREND_NO_ENTRY",
    "🚫역배열: 진입 보류": "REVERSE_TREND_NO_ENTRY",
    "🎯우량주 눌림 구간: 정찰 진입 적합": "QUALITY_PULLBACK_ENTRY",
    "📈추세 눌림 구간: 소액 탐색 가능": "TREND_PULLBACK_EXPLORE",
    "🔍정배열 눌림: 신호 확인 후 접근": "UPTREND_PULLBACK_CONFIRM",
    "🔍S급 정배열: 눌림 구간 진입 대기": "S_UPTREND_WAIT_PULLBACK",
    "🔍A급 정배열: 타점 탐색 중": "A_UPTREND_SEARCH_ENTRY",
    "🔍대기: 신규 타점 탐색": "SEARCH_NEW_ENTRY",
    "🚫극단과열: 추격금지": "EXTREME_OVERHEAT_NO_CHASE",
    "⚠️밴드상단: 눌림 대기": "BAND_UPPER_WAIT",
    "🚨위기/패닉: 투매 포착": "CRISIS_PANIC_SELL_OFF",
    "🔍관망: 타점 대기": "WATCH_WAIT_ENTRY",
}


NEW_ENTRY_DECISION_CODES = {
    "NEW_ENTRY_LEADER",
    "EXCEPTION_ENTRY",
    "S_PULLBACK_ENTRY",
    "BREAKOUT_52W_ENTRY",
    "QUALITY_PULLBACK_ENTRY",
}


def infer_decision_code(decision_label: str) -> str:
    text = str(decision_label or "").strip()
    if not text:
        return "UNKNOWN"
    exact = DECISION_CODE_BY_LABEL.get(text)
    if exact:
        return exact

    if "신규ETF" in text:
        if "단기과열" in text:
            return "NEW_ETF_SHORT_OVERHEAT"
        if "상단권" in text:
            return "NEW_ETF_UPPER_WAIT"
        if "평단하회" in text:
            return "NEW_ETF_BELOW_COST_DCA"
        if "평단근처" in text:
            return "NEW_ETF_NEAR_COST_ADD"
        if "단기눌림" in text:
            return "NEW_ETF_PULLBACK_BUY"
        if "관찰매수" in text:
            return "NEW_ETF_WATCH_BUY"
        if "비중 충족" in text:
            return "NEW_ETF_TARGET_FILLED"
        if "최소 데이터" in text:
            return "NEW_ETF_MIN_DATA_WATCH"
        if "데이터 축적" in text:
            return "NEW_ETF_DATA_ACCUMULATION"
        return "NEW_ETF_WATCH"

    if "코어" in text:
        if "폭락" in text:
            return "CORE_CRASH_DCA"
        if "하락" in text:
            return "CORE_DRAWDOWN_DCA"
        if "과열" in text:
            return "CORE_OVERHEAT_DCA"
        if "중립" in text:
            return "CORE_NEUTRAL_DCA"
        if "눌림" in text:
            return "CORE_PULLBACK_DCA"
        return "CORE_DCA"

    group = classify_decision_signal(text)
    if group == "buyish":
        return "BUYISH_GENERIC"
    if group == "caution":
        return "CAUTION_GENERIC"
    return "NEUTRAL_GENERIC"


def build_decision_outcome(decision_label: str, color: str, code: Optional[str] = None) -> DecisionOutcome:
    label = str(decision_label or "")
    final_code = str(code or "").strip() or infer_decision_code(label)
    return DecisionOutcome(
        code=final_code,
        label=label,
        color=str(color or "#64748b"),
        group=classify_decision_signal(label),
    )


def is_new_entry_decision_code(decision_code: str) -> bool:
    return str(decision_code or "") in NEW_ENTRY_DECISION_CODES


def is_new_entry_decision_label(decision_label: str) -> bool:
    return is_new_entry_decision_code(infer_decision_code(decision_label))


def build_position_sizing_hint(
    is_new_entry_signal: bool,
    targ_w: float,
    eff_total: float,
    cur_p: float,
    is_etf: bool,
) -> str:
    if is_new_entry_signal and targ_w > 0 and eff_total > 0:
        first_buy_w = round(targ_w * 0.33, 2)
        first_buy_amt = round(eff_total * first_buy_w / 100, 0)
        cur_p_for_size = cur_p if cur_p > 0 else 1
        shares_hint = int(first_buy_amt / cur_p_for_size) if cur_p_for_size > 0 else 0
        return (
            f"1차 정찰대: 목표비중의 1/3 ({first_buy_w:.1f}%) "
            f"≈ {first_buy_amt:,.0f}원"
            + (f" / 약 {shares_hint}주" if not is_etf and shares_hint > 0 else "")
            + " | 상승 확인 후 2차·3차 분할"
        )
    if is_new_entry_signal and targ_w <= 0:
        return "목표비중 미설정 — 목표비중 먼저 설정 후 1/3씩 분할 진입 권장"
    return ""


def classify_core_etf_dca_rate(
    is_core_etf: bool,
    weight_gap: float,
    current_dd: float,
    rsi_now: float,
    mfi_now: float,
    pct_b_now: float,
    trend: str,
    *,
    is_leveraged_or_inverse: bool = False,
    final_macro_risk: float = 0.0,
) -> tuple[float, str]:
    if not is_core_etf or weight_gap <= 0:
        return 0.0, ""
    if is_leveraged_or_inverse:
        return 0.0, ""
    if final_macro_risk >= 4.5:
        return 0.0, ""

    if current_dd <= -0.30:
        return 2.0, "폭락장 200% 집중"
    if current_dd <= -0.20:
        return 1.5, "하락장 150% 분할"
    if current_dd <= -0.10 or (rsi_now <= 55 and mfi_now < 70 and pct_b_now <= 0.70):
        return 1.0, "눌림 100% 적립"
    if mfi_now >= 85 or rsi_now >= 80 or pct_b_now >= 1.00:
        return 0.25, "과열 25% 정기적립"
    if mfi_now >= 80 or rsi_now >= 75 or pct_b_now >= 0.90:
        return 0.25, "상단 25% 정기적립"
    if trend == "🌊역배열(하락)":
        return 0.25, "하락추세 25% 정기적립"
    return 0.5, "중립 50% 분할적립"


def build_core_dca_context_values(
    mode: str,
    rate: float,
    label: str,
    buy_amount: float,
    current_dd: float,
    cash_available: float,
    reserve_available: float,
) -> dict:
    if mode == "개인모드":
        pool = cash_available + (reserve_available if current_dd <= -0.20 else 0.0)
        pool_label = "예수금+파킹자산" if current_dd <= -0.20 else "예수금"
    else:
        pool = max(clean_float(buy_amount), 0.0)
        pool_label = "직접입력 부족분"

    amount = 0.0
    if rate > 0:
        base_amount = max(clean_float(buy_amount), 0.0) * rate
        amount = min(base_amount, max(pool, 0.0)) if pool > 0 else base_amount

    return {
        "core_dca_rate": rate,
        "core_dca_label": label,
        "core_dca_amt": round(amount, 0),
        "core_dca_cash": round(cash_available, 0),
        "core_dca_reserve": round(reserve_available, 0),
        "core_dca_pool": round(pool, 0),
        "core_dca_pool_label": pool_label,
    }


def classify_limited_history_etf_signal(
    history_days: int,
    has_pos: bool,
    my_price: float,
    cur_p: float,
    targ_w: float,
    curr_w: float,
    weight_gap: float,
    rsi_now: float,
    mfi_now: float,
    pct_b_now: float,
    price_vs_avg: float,
) -> tuple[str, str]:
    enough_short_data = (
        history_days >= 20
        and is_finite_number(rsi_now)
        and is_finite_number(mfi_now)
        and is_finite_number(pct_b_now)
    )
    if not enough_short_data:
        return "🆕신규ETF: 최소 데이터 관찰", "#64748b"

    has_target_gap = targ_w > 0 and weight_gap > 0
    overheat_extreme = mfi_now >= 85 or rsi_now >= 80 or pct_b_now >= 1.00
    overheat_zone = mfi_now >= 80 or rsi_now >= 75 or pct_b_now >= 0.95
    pullback_zone = (rsi_now <= 55 and mfi_now < 70 and pct_b_now <= 0.75) or pct_b_now <= 0.35

    if overheat_extreme:
        return "🆕신규ETF 단기과열: 추매 보류", "#d97706"
    if overheat_zone:
        return "🆕신규ETF 상단권: 눌림 대기", "#d97706"
    if has_pos and my_price > 0 and has_target_gap and cur_p <= my_price and mfi_now < 80 and pct_b_now < 0.95:
        if price_vs_avg <= -0.07:
            return "🆕신규ETF 평단하회: 소액 분할", "#16a34a"
        return "🆕신규ETF 평단근처: 제한적 추매", "#16a34a"
    if has_target_gap and pullback_zone:
        return "🆕신규ETF 단기눌림: 제한적 매수", "#16a34a"
    if has_pos and my_price > 0 and cur_p > my_price:
        return "🆕신규ETF 보유: 눌림 대기", "#64748b"
    if has_target_gap:
        return "🆕신규ETF 관찰매수: 정찰만", "#3b82f6"
    if targ_w > 0 and curr_w >= targ_w:
        return "🆕신규ETF: 비중 충족 관찰", "#64748b"
    return "🆕신규ETF: 데이터 축적 관찰", "#64748b"
