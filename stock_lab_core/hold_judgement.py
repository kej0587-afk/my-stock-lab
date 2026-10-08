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


def _is_leveraged_or_inverse_etf(ticker, name) -> bool:
    text = f"{ticker or ''} {name or ''}".upper()
    markers = (
        "2X", "3X", "LEVERAGE", "LEVERAGED", "ULTRA", "ULTRAPRO",
        "BULL 2X", "BULL 3X", "BEAR 2X", "BEAR 3X", "INVERSE",
        "TQQQ", "SOXL", "SOXS", "BITX", "RAM", "QLD", "SQQQ",
        "레버리지", "인버스",
    )
    return any(marker in text for marker in markers)


def build_hold_decision(ticker, name, is_etf, fin_score, c, my_price, has_pos) -> HoldJudgement:
    score = 0
    r_hold, r_caution, r_exit = [], [], []

    cur_p = clean_float(c.get("cur_p"), 0.0)
    dd = clean_float(c.get("dd"), math.nan)
    trend = str(c.get("trend", ""))
    rs_label = str(c.get("rs_label", ""))
    structure_risk = bool(c.get("structure_risk"))
    live_gap_shock = bool(c.get("live_gap_shock"))
    avg_price = clean_float(my_price, math.nan)
    price_vs_avg = (cur_p / avg_price - 1) if has_pos and finite_num(avg_price) and avg_price > 0 else math.nan
    fin = clean_float(fin_score, math.nan)
    fin_valid = finite_num(fin)
    leveraged_etf = bool(is_etf and _is_leveraged_or_inverse_etf(ticker, name))

    fund_score = 0
    if is_etf:
        if leveraged_etf:
            fund_score = 0
            r_caution.append("레버리지/인버스 ETF: 장기보유 판정은 별도 관리")
        else:
            fund_score = 2
            r_hold.append("ETF: 개별기업 부도 리스크 없음")
    else:
        if not fin_valid:
            fund_score = 0
            r_caution.append("재무 데이터 확인 필요")
        elif fin >= 4:
            fund_score = 4
            r_hold.append("재무 4점: 펀더멘털 우수")
        elif fin == 3:
            fund_score = 1
            r_hold.append("재무 3점: 펀더멘털 양호")
        elif fin == 2:
            fund_score = -2
            r_caution.append("재무 2점: 재무 훼손 주의")
        elif fin <= 0:
            fund_score = -4
            r_exit.append("재무 0점: 펀더멘털 위험 수준 (처분 검토)")
        else:
            fund_score = -2
            r_caution.append("재무 1점: 펀더멘털 위험 수준")
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

    if finite_num(dd) and dd <= -0.30:
        tech_score -= 3
        r_exit.append(f"고점대비 {dd*100:.1f}% 하락 (구조적 손상)")
    elif finite_num(dd) and dd <= -0.20:
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
        (not is_etf and fin_valid and fin <= 0) or
        (has_pos and finite_num(price_vs_avg) and price_vs_avg <= -0.25 and finite_num(dd) and dd <= -0.25)
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
    if leveraged_etf and decision == HoldDecision.STRONG_HOLD:
        decision = HoldDecision.CONDITIONAL_HOLD

    action_plan = (
        "즉시 비중 대폭 축소 또는 매도 검토"
        if decision in [HoldDecision.EMERGENCY_EXIT, HoldDecision.STOP_LOSS]
        else ("비중 축소 검토" if decision == HoldDecision.REDUCE else "현재 포지션 유지 가능")
    )
    if decision == HoldDecision.STRONG_HOLD:
        action_plan = "장기 보유 유효 (목표 비중까지 분할 매수 가능)"
    elif leveraged_etf and decision in [HoldDecision.CONDITIONAL_HOLD, HoldDecision.WATCH]:
        action_plan = "레버리지/인버스 ETF는 장기 코어가 아니라 회복 조건과 비중 한도 안에서만 관리"

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
