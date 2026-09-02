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
    reasons: tuple = ()   # 판단근거 목록 — 기본값 빈 튜플 (기존 호출부 영향 없음)


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
            # 재무 3~4점이면 기술이 나빠도 "기술/재무 부진" F는 부적절 → C로 완충
            # ("F급 기술/재무 부진"은 재무도 좋지 않을 때 쓰는 라벨)
            if fin_score >= 3:
                grade = "⏳C급 (기술부진 관망)"
            else:
                grade = "🚨F급 (기술/재무 부진)"
        elif t_score < 5:
            grade = "⏳C급 (주의/대기)"
        elif t_score < 7:
            grade = "⚖️B급 (신중/관망)"
        elif t_score < 9:
            grade = "✅A급 (분할 매수)"
        else:
            grade = "💎S급 (최우선 후보)"
    return CandidateGrade(t_score=t_score, grade=grade)


def classify_safety_state(tech_total: float) -> str:
    """안전관리자 상태 — tech_total(RS+MFI+추세+MACD+SQZ) 기반.

    이 상태는 "전면 중지" 권한이 아니라 "작업 종류별 허가권자" 역할이다.

    - RED:    개별주 신규진입/추격매수/대장주 포착 등 공격적 진입 차단.
              단, 코어 ETF 정기적립(core_dca)·낙폭과대 분할매수 등은
              asset_policy(core_dca, classify_core_etf_dca_rate 등)가
              별도로 판단하므로 RED여도 막히지 않을 수 있다.
    - YELLOW: 소액/분할/정찰(스카우트) 진입만 허용.
    - GREEN:  main_score(현장소장)가 정상적으로 실행 강도를 결정한다.

    임계값은 classify_candidate_grade의 ETF 등급 경계(<1, <3)와 동일하게
    맞춰 기존 grade 체계와 일관성을 유지한다.
    """
    if not is_finite_number(tech_total):
        return "RED"
    tech_total = float(tech_total)
    if tech_total < 1:
        return "RED"
    if tech_total < 3:
        return "YELLOW"
    return "GREEN"


def classify_macro_state(final_macro_risk: float) -> str:
    """매크로/재난 상태 — final_macro_risk 기반.

    - STORM:   퍼펙트스톰 (final_macro_risk >= 4.5).
               대부분의 신규 진입은 중단되지만, 미국 대표지수 코어 ETF 등은
               정책상 예외로 정기 적립이 허용된다 (classify_core_etf_dca_rate 참고).
    - CAUTION: 매크로 리스크 상승 구간 (macro_penalty가 0보다 큰 구간, >= 1.5).
               main_score 기반 진입 강도를 한 단계 보수적으로 조정.
    - NORMAL:  매크로 리스크 낮음. 정상 판단.
    - UNKNOWN: 매크로 리스크 값이 없거나 비정상. 낙관적으로 NORMAL 처리하지 않는다.

    임계값은 get_macro_analysis()의 macro_penalty 분기(>=4, >=2.5, >=1.5)
    및 app.py 전역에서 쓰이는 퍼펙트스톰 기준(>=4.5)과 정합성을 맞췄다.
    """
    if not is_finite_number(final_macro_risk):
        return "UNKNOWN"
    final_macro_risk = float(final_macro_risk)
    if final_macro_risk >= 4.5:
        return "STORM"
    if final_macro_risk >= 1.5:
        return "CAUTION"
    return "NORMAL"


def classify_core_dca_decision(prefix: str, core_dca_rate: float, dca_label: str) -> tuple[str, str]:
    if "퍼펙트스톰" in str(dca_label or ""):
        color = "#16a34a" if core_dca_rate >= 1.0 else ("#d97706" if core_dca_rate <= 0.25 else "#3b82f6")
        return f"{prefix} 방어: {dca_label}", color
    if core_dca_rate <= 0.25:
        return f"{prefix} 과열: {dca_label}", "#d97706"
    if core_dca_rate <= 0.50:
        return f"{prefix} 중립: {dca_label}", "#3b82f6"
    return f"{prefix} 눌림: {dca_label}", "#16a34a"


def build_core_dca_outcome(prefix: str, core_dca_rate: float, dca_label: str) -> DecisionOutcome:
    label, color = classify_core_dca_decision(prefix, core_dca_rate, dca_label)
    if "퍼펙트스톰" in str(dca_label or ""):
        code = "CORE_STORM_DCA"
        if core_dca_rate >= 1.0:
            reasons: tuple = (
                "퍼펙트스톰 구간이지만 미국 대표지수 코어 ETF 목표비중 미달 - 거치식 원칙 유지",
                f"적립 비율 {int(core_dca_rate * 100)}% 적용 - 장기 우상향 코어는 매크로 타이밍보다 시장 노출 우선",
            )
        else:
            reasons = (
                "퍼펙트스톰 구간이지만 코어 ETF 목표비중 미달 - 전면 차단 대신 감속 적립",
                f"적립 비율 {int(core_dca_rate * 100)}% 로 제한 - 변동성 확대 구간 방어적 접근",
            )
    elif core_dca_rate <= 0.25:
        code = "CORE_OVERHEAT_DCA"
        reasons = (
            "코어 ETF 과열 구간 감지 (MFI>=80 또는 RSI>=75 또는 볼린저 상단 근접)",
            f"적립 비율 {int(core_dca_rate * 100)}% 로 축소 - 고점 추격 억제",
        )
    elif core_dca_rate <= 0.50:
        code = "CORE_NEUTRAL_DCA"
        reasons = (
            "코어 ETF 중립 구간 - 과열/하락 모두 아님",
            f"적립 비율 {int(core_dca_rate * 100)}% 유지",
        )
    elif core_dca_rate <= 1.0:
        code = "CORE_PULLBACK_DCA"
        reasons = (
            "코어 ETF 눌림 구간 (RSI<=55 / MFI<70 / %B<=0.70 또는 고점대비 -10% 이상)",
            f"적립 비율 {int(core_dca_rate * 100)}% 상향 - 저가 분할 기회",
        )
    elif core_dca_rate <= 1.5:
        code = "CORE_DRAWDOWN_DCA"
        reasons = (
            "코어 ETF 하락장 구간 (고점대비 -20% 이상)",
            f"적립 비율 {int(core_dca_rate * 100)}% 상향 - 분할 매수 강화",
        )
    else:
        code = "CORE_CRASH_DCA"
        reasons = (
            "코어 ETF 폭락장 구간 (고점대비 -30% 이상)",
            f"적립 비율 {int(core_dca_rate * 100)}% 최대 - 집중 분할 매수",
        )
    return build_decision_outcome(label, color, code, reasons=reasons)


def classify_decision_signal(decision_label: str) -> str:
    """Classify a visible decision label for dashboard counts.

    Keep this centralized so display wording can change without scattering
    string checks across the app.
    """
    text = str(decision_label or "")
    caution_keywords = [
        "차단", "금지", "위기", "패닉", "역배열", "구조훼손", "추세훼손", "가격위험",
        "가격방어", "급락방어", "단기급락", "추세방어", "대피",
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
    "🛑목표비중 0%: 추매금지/정리대상": "TARGET_ZERO_NO_ADD",
    "🛑하드차단: 비중 초과": "HARD_BLOCK_OVERWEIGHT",
    "⏸️하드차단: 비중 충족(관망)": "HARD_BLOCK_TARGET_FILLED",
    "🛑하드차단: 퍼펙트스톰(대피)": "HARD_BLOCK_MACRO_STORM",
    "💣패닉(-50%↓): 최종투입": "PANIC_FINAL_DEPLOY",
    "💣패닉(-40%↓): 현금 투입": "PANIC_CASH_DEPLOY",
    "🚨위기(-30%↓): 코어 집중": "CRISIS_CORE_FOCUS",
    "⚠️구조훼손: 신규진입 보류": "STRUCTURE_DAMAGE_NO_ENTRY",
    "⚠️추세훼손: 신규진입 보류": "STRUCTURE_DAMAGE_NO_ENTRY",
    "⚠️가격위험: 신규진입 보류": "PRICE_DRAWDOWN_NO_ENTRY",
    "⚠️단기급락: 신규진입 보류": "SINGLE_DAY_BREAKDOWN_NO_ENTRY",
    "⚡레버리지 급락: 신규/추매 보류": "LEVERAGED_DAILY_DROP_NO_ADD",
    "⚡레버리지 급락: 추매금지/종가 확인": "LEVERAGED_DAILY_DROP_NO_ADD",
    "⚠️고점대비 -20%: 추매금지/손절기준 점검": "DRAWDOWN_20_HOLDING_STOP_CHECK",
    "⚠️고점대비 -20%: 추매금지/원인점검": "DRAWDOWN_20_HOLDING_CAUSE_CHECK",
    "⚠️고점대비 -20%: 신규진입 보류": "DRAWDOWN_20_NO_ENTRY",
    "⚠️구조훼손: 추매금지/손절기준 점검": "STRUCTURE_DAMAGE_HOLDING_CHECK",
    "⚠️추세훼손: 추매금지/손절기준 점검": "STRUCTURE_DAMAGE_HOLDING_CHECK",
    "⚠️가격위험: 추매금지/원인점검": "PRICE_DRAWDOWN_HOLDING_CHECK",
    "⚠️단기급락: 추매금지/종가확인": "SINGLE_DAY_BREAKDOWN_HOLDING_CHECK",
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
    "💎S급 과매도: 강한 분할추매": "S_GRADE_OVERSOLD_BUY",
    "🟡보유주 단기하락: 추매는 종가 확인": "HOLDING_PULLBACK_WAIT_CLOSE",
    "🎯A급: 기술적 반등": "A_GRADE_TECH_REBOUND",
    "📈정배열: -3% 이상 눌림 분할매수": "UPTREND_PULLBACK_DCA",
    "⏳평단이상: 하락대기(보유)": "ABOVE_COST_WAIT",
    "⏸️평단이하: 비중 충족(추매 보류)": "BELOW_COST_TARGET_FILLED",
    "⏳평단근처: 추가 하락 대기": "NEAR_COST_WAIT",
    "✅평단 -3~-7%: 소액 분할매수": "COST_MINUS_3_7_DCA",
    "🎯평단 -7~-15%: 조건부 분할매수": "COST_MINUS_7_15_CONDITIONAL_DCA",
    "🚫평단 -15%↓/추세위험: 원인 점검": "COST_MINUS_15_TREND_RISK",
    "🚫평단 -15%↓+추세위험: 원인 점검": "COST_MINUS_15_TREND_RISK",
    "🚫평단 -15%↓: 원인 점검": "COST_MINUS_15_CAUSE_CHECK",
    "🚫추세위험: 원인 점검": "TREND_RISK_CAUSE_CHECK",
    "⏸️조건미달: 추매 보류": "HOLDING_DCA_CONDITION_MISS",
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
    "🔎우량주 회복관찰: 바닥 확인": "QUALITY_RECOVERY_WATCH",
    "🟢우량주 회복초입: 1차 정찰": "QUALITY_RECOVERY_SCOUT",
    "✅우량주 회복 후보: 분할 검토": "QUALITY_RECOVERY_CANDIDATE",
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
    "QUALITY_RECOVERY_SCOUT",
    "QUALITY_RECOVERY_CANDIDATE",
}


DECISION_GROUP_BY_CODE = {
    "DATA_UNAVAILABLE": "caution",
    "DATA_ERROR": "caution",
    "SAFETY_RED_NO_NEW_ENTRY": "caution",
    "TARGET_ZERO_NO_ADD": "caution",
    "LEVERAGED_DAILY_DROP_NO_ADD": "caution",
    "PRICE_DRAWDOWN_NO_ENTRY": "caution",
    "PRICE_DRAWDOWN_HOLDING_CHECK": "caution",
    "SINGLE_DAY_BREAKDOWN_NO_ENTRY": "caution",
    "SINGLE_DAY_BREAKDOWN_HOLDING_CHECK": "caution",
    "STRUCTURE_DAMAGE_NO_ENTRY": "caution",
    "STRUCTURE_DAMAGE_HOLDING_CHECK": "caution",
    "COST_MINUS_15_TREND_RISK": "caution",
    "COST_MINUS_15_CAUSE_CHECK": "caution",
    "TREND_RISK_CAUSE_CHECK": "caution",
    "HOLDING_DCA_CONDITION_MISS": "caution",
    "CORE_STORM_DCA": "buyish",
    "CORE_CRASH_DCA": "buyish",
    "CORE_DRAWDOWN_DCA": "buyish",
    "CORE_PULLBACK_DCA": "buyish",
    "CORE_NEUTRAL_DCA": "buyish",
    "CORE_OVERHEAT_DCA": "caution",
    "QUALITY_RECOVERY_WATCH": "neutral",
    "QUALITY_RECOVERY_SCOUT": "buyish",
    "QUALITY_RECOVERY_CANDIDATE": "buyish",
    "NEW_ETF_BELOW_COST_DCA": "buyish",
    "NEW_ETF_NEAR_COST_ADD": "buyish",
    "NEW_ETF_PULLBACK_BUY": "buyish",
    "NEW_ETF_WATCH_BUY": "buyish",
    "NEW_ETF_SHORT_OVERHEAT": "caution",
    "NEW_ETF_UPPER_WAIT": "caution",
    "NEW_ETF_TARGET_FILLED": "neutral",
    "NEW_ETF_MIN_DATA_WATCH": "neutral",
    "NEW_ETF_DATA_ACCUMULATION": "neutral",
    "HOLDING_LEADER_ADD_REVIEW": "caution",
    "HOLDING_BREAKOUT_TRAIL": "caution",
    "HOLDING_S_PULLBACK_ADD_REVIEW": "buyish",
    "HOLDING_OVERSOLD_ADD_REVIEW": "buyish",
    "HOLDING_EARLY_ADD_REVIEW": "caution",
    "HOLDING_EARLY_REVERSAL_ADD_REVIEW": "caution",
    "HOLDING_QUALITY_PULLBACK_ADD_REVIEW": "buyish",
    "HOLDING_QUALITY_RECOVERY_SCOUT": "buyish",
    "HOLDING_QUALITY_RECOVERY_CANDIDATE": "buyish",
    "HOLDING_TREND_PULLBACK_ADD_REVIEW": "caution",
    "HOLDING_EXCEPTION_ADD_REVIEW": "buyish",
    "HOLDING_PULLBACK_WAIT_CLOSE": "caution",
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


def build_decision_outcome(
    decision_label: str,
    color: str,
    code: Optional[str] = None,
    reasons: tuple = (),
) -> DecisionOutcome:
    label = str(decision_label or "")
    final_code = str(code or "").strip() or infer_decision_code(label)
    return DecisionOutcome(
        code=final_code,
        label=label,
        color=str(color or "#64748b"),
        group=DECISION_GROUP_BY_CODE.get(final_code) or classify_decision_signal(label),
        reasons=tuple(reasons),
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
            f"~{first_buy_amt:,.0f}원"
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
    is_us_broad_index_core_etf: bool = False,
    is_kr_listed_core_etf: bool = False,
    final_macro_risk: float = 0.0,
) -> tuple[float, str]:
    if not is_core_etf or weight_gap <= 0:
        return 0.0, ""
    if is_leveraged_or_inverse:
        return 0.0, ""

    is_extreme_overheat = mfi_now >= 85 or rsi_now >= 80 or pct_b_now >= 1.00
    is_upper_overheat = mfi_now >= 80 or rsi_now >= 75 or pct_b_now >= 0.90
    if final_macro_risk >= 4.5:
        if is_us_broad_index_core_etf:
            return 1.0, "미국지수 퍼펙트스톰 100% 거치 적립"
        if is_extreme_overheat:
            return 0.0, ""
        if is_kr_listed_core_etf:
            if current_dd <= -0.20 and not is_upper_overheat:
                return 0.50, "국장 퍼펙트스톰 50% 제한적 적립"
            return 0.25, "국장 퍼펙트스톰 25% 방어적 적립"
        if current_dd <= -0.20 and not is_upper_overheat:
            return 0.50, "퍼펙트스톰 50% 감속 적립"
        return 0.25, "퍼펙트스톰 25% 방어적 적립"

    if current_dd <= -0.30:
        return 2.0, "폭락장 200% 집중"
    if current_dd <= -0.20:
        return 1.5, "하락장 150% 분할"
    if current_dd <= -0.10 or (rsi_now <= 55 and mfi_now < 70 and pct_b_now <= 0.70):
        return 1.0, "눌림 100% 적립"
    if is_extreme_overheat:
        return 0.25, "과열 25% 정기적립"
    if is_upper_overheat:
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


def build_limited_history_etf_outcome(
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
) -> DecisionOutcome:
    label, color = classify_limited_history_etf_signal(
        history_days, has_pos, my_price, cur_p, targ_w, curr_w, weight_gap,
        rsi_now, mfi_now, pct_b_now, price_vs_avg
    )

    r: list = []

    # 데이터 이력
    if history_days < 20:
        r.append(f"가격 데이터 {history_days}일 — 최소 20일 미만, 기술 신호 신뢰도 낮음")
    else:
        r.append(f"가격 데이터 {history_days}일 (단기 이력 — 신규 ETF 판정 적용)")

    # 과열 상태
    if is_finite_number(mfi_now) and is_finite_number(rsi_now) and is_finite_number(pct_b_now):
        if mfi_now >= 85 or rsi_now >= 80 or pct_b_now >= 1.00:
            r.append(f"과열 극단 구간 (MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f})")
        elif mfi_now >= 80 or rsi_now >= 75 or pct_b_now >= 0.95:
            r.append(f"과열 상단 구간 (MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f})")
        else:
            r.append(f"과열 아님 (MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f})")

    # 보유 및 평단 비교
    if has_pos and my_price > 0:
        pct = price_vs_avg * 100
        if cur_p <= my_price:
            r.append(f"현재가({cur_p:,.0f}원) <= 평단({my_price:,.0f}원) - 평단 하회 {pct:.1f}%")
        else:
            r.append(f"현재가({cur_p:,.0f}원) > 평단({my_price:,.0f}원) - 평단 이상 +{pct:.1f}%")
    elif not has_pos:
        r.append("미보유 — 신규 진입 여부 판단")

    # 목표비중
    if targ_w > 0:
        if weight_gap > 0:
            r.append(f"목표비중 {targ_w:.1f}% 대비 {weight_gap:.1f}%p 부족")
        else:
            r.append(f"목표비중 {targ_w:.1f}% 달성 (초과 없음)")
    else:
        r.append("목표비중 미설정")

    return build_decision_outcome(label, color, reasons=tuple(r))
