"""B-4 (2026-11-24): technical review layer, computed as a shadow only.

It reads the final decision and the chart evidence already on the precision page and
returns CONFIRM / NEUTRAL / CAUTION / BLOCK / DATA_CHECK with the reasons.

It never writes back: decision_code, 판정분류, the execution gate and sizing are not
touched (the user's rule; CONFIRM never promotes a decision). The thresholds below are
observation thresholds for this shadow view only, not trading rules. They are not tuned;
C-stage validation decides whether any of this ever feeds the decision.
"""

from __future__ import annotations

import math
from typing import Any

CONFIRM, NEUTRAL, CAUTION, BLOCK, DATA_CHECK = "CONFIRM", "NEUTRAL", "CAUTION", "BLOCK", "DATA_CHECK"
VERDICT_LABELS = {
    CONFIRM: "확인(동의)",
    NEUTRAL: "중립",
    CAUTION: "주의",
    BLOCK: "차단 근거",
    DATA_CHECK: "데이터 확인",
}
SHADOW_NOTE = "그림자 계산: 기존 판정·판정분류·실행게이트·사이징에 반영하지 않음"
MIN_CONFIRM_SIGNALS = 3
SHORT_FORMATION_DAYS = 15


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return math.nan
    return out if math.isfinite(out) else math.nan


def _ok(value: float) -> bool:
    return isinstance(value, float) and math.isfinite(value)


def _formation_days(pattern: dict) -> float:
    times = [t for t in (pattern.get("formation_id") or ()) if hasattr(t, "to_pydatetime") or hasattr(t, "toordinal")]
    if len(times) < 2:
        return math.nan
    try:
        return float(abs((max(times) - min(times)).days))
    except Exception:
        return math.nan


def build_tech_review_shadow(decision: dict | None, *, pattern_candidates=None, liquidity_profile=None) -> dict:
    """Return {"verdict", "label", "reasons": [(kind, area, text)], "note", ...}; kind is +, -, !, ?."""
    d = decision if isinstance(decision, dict) else {}
    reasons: list[tuple[str, str, str]] = []

    def add(kind, area, text):
        reasons.append((kind, area, text))

    cur = _num(d.get("cur_p"))
    pct_b, rsi = _num(d.get("pct_b")), _num(d.get("rsi"))
    ma20, ma50 = _num(d.get("ma20")), _num(d.get("ma50"))
    vol_ratio = _num(d.get("vol_ratio"))
    history = _num(d.get("history_days"))

    # 1) Data: the shadow does not guess around missing inputs.
    missing = [name for name, v in (("현재가", cur), ("%B", pct_b), ("RSI", rsi), ("MA20", ma20), ("MA50", ma50)) if not _ok(v)]
    if not d:
        add("?", "데이터", "판정 결과 없음")
    if missing:
        add("?", "데이터", "미확인: " + ", ".join(missing))
    if _ok(history) and history < 60:
        add("?", "데이터", f"일봉 {int(history)}개: 구조 판단에 부족")
    data_state = str(d.get("data_state", "OK") or "OK")
    if data_state != "OK":
        add("?", "데이터", f"데이터 상태: {data_state}")

    # 2) Price structure and current position
    if _ok(cur) and _ok(ma20) and _ok(ma50):
        if cur > ma20 > ma50:
            add("+", "가격구조", "현재가 > MA20 > MA50 (정배열 위)")
        elif cur < ma50:
            add("-", "가격구조", "현재가가 MA50 아래")
    if bool(d.get("structure_risk")):
        add("-", "가격구조", "엔진 구조훼손 진입위험 표시")
    ext = str(d.get("ext_structure", "") or "")
    if ext == "Bearish":
        add("-", "가격구조", "외부구조 하락(역배열)")
    if _ok(pct_b) and pct_b >= 0.95:
        add("-", "현재 위치", f"%B {pct_b:.2f}: 밴드 상단 과열권")
    if _ok(rsi) and rsi >= 75:
        add("-", "현재 위치", f"RSI {rsi:.0f}: 과열")
    if bool(d.get("is_52w_breakout")):
        add("+", "현재 위치", "52주 신고가 돌파")

    # 3) FVG / PD zone
    pd_zone = str(d.get("pd_zone", "") or "")
    if "Premium" in pd_zone and _ok(pct_b) and pct_b >= 0.78:
        add("-", "FVG/PD", "Premium 구간 상단")
    elif "Discount" in pd_zone:
        add("+", "FVG/PD", "Discount 구간")
    fvg_type = str(d.get("fvg_type", "") or "").lower()
    if bool(d.get("fvg_active")):
        if "bull" in fvg_type or "상승" in fvg_type:
            add("+", "FVG/PD", "활성 상승 FVG 지지")
        elif "bear" in fvg_type or "하락" in fvg_type:
            add("-", "FVG/PD", "활성 하락 FVG 저항")

    # 4) Volume
    if _ok(vol_ratio):
        day_ret = _num(d.get("day_ret"))
        if vol_ratio >= 1.5 and _ok(day_ret):
            add("+" if day_ret > 0 else "-", "거래량", f"거래량 {vol_ratio:.1f}배 ({'상승일' if day_ret > 0 else '하락일'})")
        elif vol_ratio >= 1.5:
            add("?", "거래량", f"거래량 {vol_ratio:.1f}배 (등락 미확인)")
        elif vol_ratio < 0.5:
            add("-", "거래량", f"거래량 {vol_ratio:.1f}배: 얇음")
    else:
        add("?", "거래량", "거래량 비율 미확인")

    # 5) Estimated volume-at-price (liquidity proxy)
    liq = liquidity_profile if isinstance(liquidity_profile, dict) else {}
    if liq.get("ok"):
        status = str(liq.get("status", "") or "")
        if status in {"상단 매물 근접", "상단 매물 부담"}:
            add("-", "매물대", f"추정 매물대: {status}")
        elif status in {"하단 유동성 지지 확인", "하단 유동성 우세"}:
            add("+", "매물대", f"추정 매물대: {status}")
    elif liquidity_profile is not None:
        add("?", "매물대", f"추정 매물대 미확인: {liq.get('reason', '자료 부족')}")

    # 6) Chart pattern, formation period, scenario (invalid line)
    pattern = next((p for p in (pattern_candidates or []) if isinstance(p, dict)), None)
    if pattern:
        name, status = pattern.get("name", "패턴"), str(pattern.get("status", "") or "")
        direction = pattern.get("direction", "neutral")
        invalid = _num(pattern.get("invalid_price"))
        days = _formation_days(pattern)
        if direction == "bullish" and _ok(invalid) and _ok(cur) and cur < invalid:
            add("!", "시나리오", f"{name} 무효선 이탈: 회복 시나리오 훼손")
        elif direction == "bullish" and status in {"돌파", "상방돌파"}:
            add("+", "패턴", f"{name} {status}")
        elif direction == "bearish" and status in {"이탈", "하방이탈"}:
            add("-", "패턴", f"{name} {status}")
        if _ok(days) and days < SHORT_FORMATION_DAYS:
            add("-", "형성기간", f"{name} 형성 {int(days)}일: 짧아 신뢰 낮음")
        elif _ok(days):
            add("·", "형성기간", f"{name} 형성 {int(days)}일")

    # 7) Higher timeframe (already computed by the MTF guard)
    mtf = str(d.get("mtf_bias_label", "") or "")
    if mtf == "상위 시간대 우호":
        add("+", "상위시간대", mtf)
    elif mtf in {"상위 시간대 경고", "정찰만 적합"}:
        add("-", "상위시간대", mtf)
    elif mtf in {"", "자료부족"}:
        add("?", "상위시간대", "상위 시간대 미확인")

    kinds = [k for k, _, _ in reasons]
    hard_missing = bool(missing) or not d
    if hard_missing:
        verdict = DATA_CHECK
    elif "!" in kinds:
        verdict = BLOCK
    elif (kinds.count("-") >= 2 and kinds.count("-") > kinds.count("+")) or (kinds.count("-") >= 1 and kinds.count("+") == 0):
        verdict = CAUTION
    elif kinds.count("+") >= MIN_CONFIRM_SIGNALS and kinds.count("+") - kinds.count("-") >= MIN_CONFIRM_SIGNALS:
        verdict = CONFIRM
    else:
        verdict = NEUTRAL
    return {
        "verdict": verdict,
        "label": VERDICT_LABELS[verdict],
        "reasons": reasons,
        "positives": kinds.count("+"),
        "cautions": kinds.count("-"),
        "unchecked": kinds.count("?"),
        "note": SHADOW_NOTE,
    }


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
