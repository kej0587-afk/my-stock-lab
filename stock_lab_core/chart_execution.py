"""Chart execution guide helpers for the precision watch panel."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stock_lab_core.formatters import (
    clean_float,
    escape_html_value,
    finite_num,
    format_currency,
)


def zone_price_text(low, high, ticker: str) -> str:
    if not finite_num(low) or not finite_num(high):
        return "-"
    return f"{format_currency(low, ticker)}~{format_currency(high, ticker)}"


def liquidity_zone_price_text(zone: dict | None, ticker: str) -> str:
    if not zone:
        return "-"
    return zone_price_text(zone.get("low"), zone.get("high"), ticker)


def chart_latest_close(df: pd.DataFrame) -> float:
    if df is None or df.empty or "Close" not in df.columns:
        return np.nan
    return clean_float(df["Close"].iloc[-1], np.nan)


def chart_volume_ratio(df: pd.DataFrame, lookback: int = 20) -> float:
    if df is None or df.empty or "Volume" not in df.columns:
        return np.nan
    vol = pd.to_numeric(df["Volume"], errors="coerce").dropna()
    if vol.empty:
        return np.nan
    current = clean_float(vol.iloc[-1], np.nan)
    avg = clean_float(vol.tail(max(3, lookback)).mean(), np.nan)
    if not finite_num(current) or not finite_num(avg) or avg <= 0:
        return np.nan
    return current / avg


def chart_zone_distance_state(close: float, low: float, high: float) -> tuple[str, str]:
    if not finite_num(close) or close <= 0 or not finite_num(low) or not finite_num(high):
        return "확인필요", "가격대 산출이 불완전합니다."
    zone_low, zone_high = sorted([float(low), float(high)])
    if zone_low <= close <= zone_high:
        return "확인필요", "지지 후보 가격대 안입니다. 여기서 하락이 멈추고 양봉·거래량이 붙는지 봅니다."
    if close > zone_high:
        gap = (close / zone_high - 1.0) * 100
        if gap <= 3.0:
            return "확인필요", f"지지 후보 위 {gap:.1f}%입니다. 가까운 눌림이라 반응 확인 구간입니다."
        return "대기", f"지지 후보가 현재가보다 {gap:.1f}% 아래라, 지금은 눌림 확인보다 돌파 확인이 먼저입니다."
    gap = (zone_low / close - 1.0) * 100
    return "주의", f"지지 후보를 {gap:.1f}%가량 밑돌고 있어 지지 실패 여부를 확인해야 합니다."


def pick_support_zone(
    trendline_guides: list,
    smc_features: dict | None,
    liquidity_profile: dict | None,
    ticker: str,
    close=None,
) -> dict:
    smc_features = smc_features or {}
    current = clean_float(close, np.nan)
    candidates = []

    def add_candidate(label: str, low, high, text: str, priority: int):
        low_v = clean_float(low, np.nan)
        high_v = clean_float(high, np.nan)
        if not finite_num(low_v) or not finite_num(high_v):
            return
        zone_low, zone_high = sorted([low_v, high_v])
        if finite_num(current) and current > 0:
            if zone_low <= current <= zone_high:
                distance = 0.0
            elif current > zone_high and zone_high > 0:
                distance = current / zone_high - 1.0
            else:
                distance = 10.0 + (zone_low / current - 1.0)
        else:
            distance = priority
        candidates.append({
            "label": label,
            "low": zone_low,
            "high": zone_high,
            "text": text,
            "_distance": distance,
            "_priority": priority,
        })

    fvg = smc_features.get("visible_fvg") or {}
    if fvg.get("type") == "Bullish FVG" and finite_num(fvg.get("bottom")) and finite_num(fvg.get("top")):
        add_candidate("FVG 지지", fvg.get("bottom"), fvg.get("top"), zone_price_text(fvg.get("bottom"), fvg.get("top"), ticker), 1)
    for zone in smc_features.get("visible_order_blocks") or []:
        if zone.get("direction") == "support" and finite_num(zone.get("low")) and finite_num(zone.get("high")):
            add_candidate("OB 지지", zone.get("low"), zone.get("high"), zone_price_text(zone.get("low"), zone.get("high"), ticker), 2)
            break
    if liquidity_profile and liquidity_profile.get("ok") and liquidity_profile.get("support"):
        zone = liquidity_profile.get("support")
        if finite_num(zone.get("low")) and finite_num(zone.get("high")):
            add_candidate("유동성 지지", zone.get("low"), zone.get("high"), liquidity_zone_price_text(zone, ticker), 3)
    support_guide = next((g for g in (trendline_guides or []) if g.get("kind") == "support"), None)
    if support_guide and finite_num(support_guide.get("y1")):
        y = clean_float(support_guide.get("y1"), np.nan)
        add_candidate("상승 저점선", y, y, format_currency(y, ticker), 4)
    if not candidates:
        return {}
    return sorted(candidates, key=lambda item: (abs(clean_float(item.get("_distance"), 999.0)), item.get("_priority", 99)))[0]


def build_chart_execution_guide(
    patterns: list,
    trendline_guides: list,
    smc_features: dict | None,
    liquidity_profile: dict | None,
    ticker: str,
    current_price=None,
) -> str:
    """차트 보조 신호를 실행 기준 문장으로 번역합니다."""
    pattern = patterns[0] if patterns else {}
    pattern_name = str(pattern.get("name") or "패턴")
    direction = str(pattern.get("direction") or "")
    lifecycle = str(pattern.get("lifecycle") or "")
    trigger = clean_float(pattern.get("trigger_price"), np.nan)
    invalid = clean_float(pattern.get("invalid_price"), np.nan)
    current = clean_float(current_price, np.nan)

    support_guide = next((g for g in (trendline_guides or []) if g.get("kind") == "support"), None)
    resistance_guide = next((g for g in (trendline_guides or []) if g.get("kind") == "resistance"), None)
    support_dir = str((support_guide or {}).get("direction") or "")
    resistance_dir = str((resistance_guide or {}).get("direction") or "")
    resistance_y = clean_float((resistance_guide or {}).get("y1"), np.nan)
    resistance_passed = finite_num(current) and finite_num(resistance_y) and current >= resistance_y * 1.003

    if support_dir == "상승" and resistance_dir == "하락" and resistance_passed:
        structure_text = "저점은 올라왔고 내려오던 고점선은 이미 넘었습니다. 지금은 추격보다 돌파 후 눌림과 손익비를 확인하는 구간입니다."
    elif support_dir == "상승" and resistance_dir == "하락":
        structure_text = "저점은 올라오고 고점은 내려오는 수렴입니다. 어느 쪽으로 돌파되는지 확인하는 구간입니다."
    elif support_dir == "상승":
        structure_text = "아래 저점선이 올라오는 회복 시도입니다. 단, 위 저항 돌파 전에는 확인 단계입니다."
    elif resistance_dir == "하락":
        structure_text = "위 고점선이 내려와 누르는 구간입니다. 저항선 돌파 전 추격은 불리합니다."
    else:
        structure_text = "명확한 한 방향보다 지지·저항 확인이 우선인 구간입니다."

    breakout_bits = []
    upper_target_text = ""
    if direction == "bullish" and finite_num(trigger) and trigger > 0:
        verb = "돌파 후 유지" if lifecycle == "현재유효" else "위 종가 안착"
        breakout_bits.append(f"{pattern_name} 기준선 {format_currency(trigger, ticker)} {verb}")
    if resistance_guide and finite_num(resistance_y):
        resistance_gap = (resistance_y / current - 1.0) if finite_num(current) and current > 0 else np.nan
        far_upper_resistance = finite_num(resistance_gap) and resistance_gap >= 0.08
        if resistance_passed:
            breakout_bits.append(f"고점선 돌파 완료: {format_currency(resistance_y, ticker)} 위 유지")
        elif far_upper_resistance:
            upper_target_text = (
                f"{format_currency(resistance_y, ticker)}는 1차 매수 조건이 아니라 "
                "상단 목표·큰 저항입니다. 그 근처에서는 추격보다 분할익절/재평가를 먼저 봅니다."
            )
        else:
            breakout_bits.append(f"고점선 저항 {format_currency(resistance_y, ticker)} 위 돌파")
    if breakout_bits:
        breakout_text = " / ".join(breakout_bits) + " + 거래량 증가가 확인될 때만 1차 정찰·분할 검토"
    else:
        breakout_text = "상단 저항을 종가로 넘기 전까지는 돌파 매수보다 관찰 우선"

    support_bits = []
    smc_features = smc_features or {}
    fvg = smc_features.get("visible_fvg") or {}
    if fvg.get("type") == "Bullish FVG":
        support_bits.append(f"FVG 지지 {zone_price_text(fvg.get('bottom'), fvg.get('top'), ticker)}")
    for zone in smc_features.get("visible_order_blocks") or []:
        if zone.get("direction") == "support":
            support_bits.append(f"OB 지지 {zone_price_text(zone.get('low'), zone.get('high'), ticker)}")
            break
    if liquidity_profile and liquidity_profile.get("ok") and liquidity_profile.get("support"):
        support_bits.append(f"유동성 지지 {liquidity_zone_price_text(liquidity_profile.get('support'), ticker)}")
    if support_guide and finite_num(support_guide.get("y1")):
        support_bits.append(f"상승 저점선 {format_currency(support_guide.get('y1'), ticker)} 부근")
    if support_bits:
        pullback_text = " / ".join(support_bits[:3]) + "에서 하락 멈춤·양봉 전환·거래량 회복이 보이면 눌림 정찰 후보"
    else:
        pullback_text = "가까운 지지대가 명확하지 않으면 눌림 매수보다 돌파 확인을 우선"

    invalid_bits = []
    if finite_num(invalid) and invalid > 0:
        invalid_bits.append(f"패턴 무효선 {format_currency(invalid, ticker)} 이탈 시 후보 폐기")
    if support_guide and finite_num(support_guide.get("y1")):
        invalid_bits.append(f"상승 저점선 {format_currency(support_guide.get('y1'), ticker)} 아래는 추가매수 중단·다음 봉 회복 확인")
    invalid_text = " / ".join(invalid_bits[:2]) if invalid_bits else "지지선 이탈 시 추가매수 중단·다음 봉 회복 확인"

    rows = [
        ("현재 의미", structure_text),
        ("돌파 기준", breakout_text),
        ("눌림 기준", pullback_text),
        ("폐기 기준", invalid_text),
    ]
    if upper_target_text:
        rows.insert(3, ("상단 목표", upper_target_text))
    body = "<br>".join(
        f"<b>{escape_html_value(title)}</b>: {escape_html_value(text)}"
        for title, text in rows
    )
    return (
        "<div class='info-panel' style='border-left: 5px solid #38bdf8; line-height:1.9;'>"
        "<b>🧭 차트 실행 기준</b><br>"
        f"{body}"
        "</div>"
    )


def build_chart_execution_check_rows(
    df: pd.DataFrame,
    patterns: list,
    trendline_guides: list,
    smc_features: dict | None,
    liquidity_profile: dict | None,
    ticker: str,
    decision_context: dict | None = None,
) -> list[dict]:
    """차트 보조 신호를 실행 전 체크리스트로 압축합니다."""
    close = chart_latest_close(df)
    pattern = patterns[0] if patterns else {}
    direction = str(pattern.get("direction") or "")
    trigger = clean_float(pattern.get("trigger_price"), np.nan)
    invalid = clean_float(pattern.get("invalid_price"), np.nan)
    support_guide = next((g for g in (trendline_guides or []) if g.get("kind") == "support"), None)
    resistance_guide = next((g for g in (trendline_guides or []) if g.get("kind") == "resistance"), None)
    rows = []

    def add_row(condition: str, state: str, standard: str, meaning: str, action: str):
        rows.append({
            "조건": condition,
            "상태": state,
            "기준": standard,
            "해석": meaning,
            "다음 행동": action,
        })

    if direction == "bullish" and finite_num(trigger) and trigger > 0:
        passed = finite_num(close) and close >= trigger * 0.997
        add_row(
            "기준선 돌파",
            "통과" if passed else "대기",
            f"{format_currency(trigger, ticker)} 위 종가",
            f"{str(pattern.get('name') or '회복 패턴')}이 실행 단계로 넘어가는 가격입니다.",
            "1차 정찰 가능" if passed else "이 가격 위에서 마감하는지 먼저 확인",
        )
    elif direction == "bearish" and finite_num(trigger) and trigger > 0:
        add_row(
            "하락 패턴",
            "주의",
            f"{format_currency(trigger, ticker)} 이탈 여부",
            "상승 진입보다 방어 기준을 먼저 볼 패턴입니다.",
            "신규 매수보다 이탈 여부 확인",
        )

    if resistance_guide and finite_num(resistance_guide.get("y1")):
        resistance = clean_float(resistance_guide.get("y1"), np.nan)
        resistance_dir = str(resistance_guide.get("direction") or "")
        passed = finite_num(close) and close >= resistance * 1.003
        resistance_gap = (resistance / close - 1.0) if finite_num(close) and close > 0 else np.nan
        far_upper_resistance = finite_num(resistance_gap) and resistance_gap >= 0.08
        if resistance_dir == "하락":
            resistance_meaning = "내려오는 고점선을 넘으면 매도 압력이 약해졌다는 뜻입니다."
        elif resistance_dir == "상승":
            resistance_meaning = "위쪽 상승 추세선은 다음 목표·저항입니다. 여기까지는 눌림과 손익비를 먼저 봅니다."
        else:
            resistance_meaning = "상단 저항을 넘으면 가격 회복 신뢰도가 올라갑니다."
        if not passed and far_upper_resistance:
            add_row(
                "상단 목표/큰 저항",
                "참고",
                f"{format_currency(resistance, ticker)} 부근",
                "현재가와 거리가 있어 1차 매수 조건이 아니라 목표·재평가 가격입니다.",
                "도달 전에는 지지·손익비 우선",
            )
        else:
            add_row(
                "고점선/저항 돌파",
                "통과" if passed else "대기",
                f"{format_currency(resistance, ticker)} 위 유지",
                resistance_meaning,
                "돌파 후 눌림 확인" if passed else "상단 저항 전 추격매수 보류",
            )

    support_zone = pick_support_zone(trendline_guides, smc_features, liquidity_profile, ticker, close)
    if support_zone:
        state, meaning = chart_zone_distance_state(close, support_zone.get("low"), support_zone.get("high"))
        add_row(
            "눌림 지지 확인",
            state,
            f"{support_zone.get('label')} {support_zone.get('text')}",
            meaning,
            "양봉 전환·거래량 회복 확인" if state == "확인필요" else ("현재가 추격보다 눌림 대기" if state == "대기" else "지지 실패 시 후보 낮추기"),
        )

    vol_ratio = chart_volume_ratio(df)
    if finite_num(vol_ratio):
        if vol_ratio >= 1.2:
            vol_state = "통과"
            vol_action = "돌파 신뢰도 보강"
        elif vol_ratio >= 0.8:
            vol_state = "보통"
            vol_action = "가격 조건과 함께 확인"
        else:
            vol_state = "부족"
            vol_action = "거래량 없이 오른 회복은 신뢰도 낮춤"
        add_row(
            "거래량 확인",
            vol_state,
            f"20봉 평균 대비 {vol_ratio:.1f}배",
            "돌파·지지 신호는 거래량이 붙을수록 신뢰도가 올라갑니다.",
            vol_action,
        )

    rr = clean_float((decision_context or {}).get("rr_ratio"), np.nan)
    rr_target = clean_float((decision_context or {}).get("rr_target"), np.nan)
    rr_stop = clean_float((decision_context or {}).get("rr_stop"), np.nan)
    if finite_num(rr):
        if rr < 1.0:
            rr_state = "차단"
            rr_action = "현재가 풀진입 보류"
        elif rr < 1.5:
            rr_state = "주의"
            rr_action = "소액 정찰만 검토"
        else:
            rr_state = "통과"
            rr_action = "다른 조건 통과 시 분할 검토"
        rr_basis = f"R/R {rr:.2f}"
        if finite_num(rr_target) and finite_num(rr_stop):
            rr_basis += f" · 목표 {format_currency(rr_target, ticker)} / 손절 {format_currency(rr_stop, ticker)}"
        add_row(
            "손익비 확인",
            rr_state,
            rr_basis,
            "현재가에서 기대수익이 손절폭보다 충분한지 보는 최종 안전장치입니다.",
            rr_action,
        )
    else:
        add_row(
            "손익비 확인",
            "확인필요",
            "R/R 산출 없음",
            "목표가와 손절가가 잡히지 않으면 매수 강도를 낮춰야 합니다.",
            "정밀관측소 R/R 재계산",
        )

    invalid_bits = []
    if finite_num(invalid) and invalid > 0:
        invalid_bits.append(f"패턴 무효선 {format_currency(invalid, ticker)}")
    if support_guide and finite_num(support_guide.get("y1")):
        invalid_bits.append(f"저점선 {format_currency(support_guide.get('y1'), ticker)}")
    if invalid_bits:
        pattern_broken = finite_num(invalid) and invalid > 0 and finite_num(close) and close < invalid
        support_broken = support_guide and finite_num(support_guide.get("y1")) and finite_num(close) and close < clean_float(support_guide.get("y1"), np.nan)
        if pattern_broken:
            invalid_state = "차단"
            invalid_meaning = "패턴 무효선까지 깨져 회복 시나리오가 훼손된 상태입니다."
            invalid_action = "후보 폐기 또는 비중축소 검토"
        elif support_broken:
            invalid_state = "주의"
            invalid_meaning = "단기 저점선은 이탈했지만 패턴 무효선은 아직 남아 있습니다. 추가매수보다 회복 확인이 먼저입니다."
            invalid_action = "추가매수 중단·다음 봉 회복 확인"
        else:
            invalid_state = "통과"
            invalid_meaning = "주요 방어선 위에 있어 회복 시나리오는 유지됩니다."
            invalid_action = "보유만 속도조절"
        add_row(
            "무효선 방어",
            invalid_state,
            " / ".join(invalid_bits[:2]),
            invalid_meaning,
            invalid_action,
        )

    return rows
