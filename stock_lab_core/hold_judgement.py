"""Long-term hold judgement helpers for Stock Lab."""

from dataclasses import dataclass, field
from enum import Enum
import math

from stock_lab_core.formatters import clean_float, finite_num


class HoldDecision(Enum):
    STRONG_HOLD = "💎 강력 장기보유"
    CONDITIONAL_HOLD = "✅ 조건부 장기보유"
    WATCH = "⚠️ 모니터링 강화"
    REDUCE = "📉 비중 축소 검토"
    STOP_LOSS = "🚨 손절 검토"
    EMERGENCY_EXIT = "❌ 긴급 매도"


@dataclass
class HoldJudgement:
    decision: HoldDecision
    score: int
    fundamental_score: int = 0
    technical_score: int = 0
    thesis_score: int = 0
    risk_score: int = 0
    reasons_hold: list = field(default_factory=list)
    reasons_caution: list = field(default_factory=list)
    reasons_exit: list = field(default_factory=list)
    action_plan: str = ""


def build_hold_decision(ticker, name, is_etf, fin_score, c, my_price, has_pos) -> HoldJudgement:
    score = 0
    r_hold, r_caution, r_exit = [], [], []

    cur_p = clean_float(c.get("cur_p"), 0.0)
    dd = clean_float(c.get("dd"), 0.0)
    trend = str(c.get("trend", ""))
    rs_label = str(c.get("rs_label", ""))
    structure_risk = bool(c.get("structure_risk"))
    live_gap_shock = bool(c.get("live_gap_shock"))
    price_vs_avg = (cur_p / my_price - 1) if has_pos and my_price > 0 else math.nan

    fund_score = 0
    if is_etf:
        fund_score = 2
        r_hold.append("ETF: 개별기업 부도 리스크 없음")
    else:
        if fin_score >= 4:
            fund_score = 4
            r_hold.append("재무 4점: 펀더멘털 우수")
        elif fin_score == 3:
            fund_score = 1
            r_hold.append("재무 3점: 펀더멘털 양호")
        elif fin_score == 2:
            fund_score = -2
            r_caution.append("재무 2점: 재무 훼손 주의")
        else:
            fund_score = -4
            r_exit.append("재무 1점: 펀더멘털 위험 수준 (처분 검토)")
    score += fund_score

    tech_score = 0
    if "정배열" in trend:
        tech_score += 2
        r_hold.append("이동평균선 정배열 유지")
    elif "역배열" in trend:
        tech_score -= 2
        r_caution.append("이동평균선 역배열 (추세 꺾임)")

    rs_slope_label = str(c.get("rs_slope_label", ""))
    if "🚀" in rs_label:
        if "📉" in rs_slope_label:
            tech_score += 1
            r_caution.append("RS 강함이나 기울기 하락 중 — 상대강도 약화 진행")
        else:
            tech_score += 2
            r_hold.append("시장/섹터 대비 강한 상대강도")
    elif "🐢" in rs_label:
        if "📈" in rs_slope_label:
            tech_score -= 1
            r_caution.append("RS 약하나 기울기 개선 중 — 반전 여부 관찰")
        else:
            tech_score -= 2
            r_caution.append("시장/섹터 대비 약한 상대강도")

    if dd <= -0.30:
        tech_score -= 3
        r_exit.append(f"고점대비 {dd*100:.1f}% 하락 (구조적 손상)")
    elif dd <= -0.20:
        tech_score -= 1
        r_caution.append(f"고점대비 {dd*100:.1f}% 하락")

    if structure_risk:
        tech_score -= 2
        r_caution.append("구조 훼손 신호 포착")
    elif live_gap_shock:
        tech_score -= 1
        r_caution.append("프리/실시간 급락 — 정규장 종가와 거래량 확인 필요")
    score += tech_score

    risk_score = 0
    if has_pos and finite_num(price_vs_avg):
        if price_vs_avg <= -0.15:
            risk_score -= 3
            r_exit.append(f"내 평단 대비 {price_vs_avg*100:.1f}% 손실")
        elif price_vs_avg > 0.20:
            risk_score += 2
            r_hold.append("충분한 안전마진 확보")
    score += risk_score

    thesis_score = 0
    score += thesis_score

    hard_exit = (
        (not is_etf and fin_score <= 1) or
        (has_pos and finite_num(price_vs_avg) and price_vs_avg <= -0.25 and dd <= -0.25)
    )

    if hard_exit:
        decision = HoldDecision.EMERGENCY_EXIT
    elif score >= 6:
        decision = HoldDecision.STRONG_HOLD
    elif score >= 3:
        decision = HoldDecision.CONDITIONAL_HOLD
    elif score >= 0:
        decision = HoldDecision.WATCH
    elif score >= -3:
        decision = HoldDecision.REDUCE
    else:
        decision = HoldDecision.STOP_LOSS

    action_plan = (
        "즉시 비중 대폭 축소 또는 매도 검토"
        if decision in [HoldDecision.EMERGENCY_EXIT, HoldDecision.STOP_LOSS]
        else ("비중 축소 검토" if decision == HoldDecision.REDUCE else "현재 포지션 유지 가능")
    )
    if decision == HoldDecision.STRONG_HOLD:
        action_plan = "장기 보유 유효 (목표 비중까지 분할 매수 가능)"

    return HoldJudgement(
        decision,
        score,
        fund_score,
        tech_score,
        thesis_score,
        risk_score,
        r_hold,
        r_caution,
        r_exit,
        action_plan,
    )
