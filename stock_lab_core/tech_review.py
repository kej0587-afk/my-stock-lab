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



# ── C-5 v2 (2026-11-25, user decision): display only ────────────────────────────────────────────
# Same five states and the same verdict shape as v1, counted on de-duplicated clusters instead of
# individual reasons. No new threshold. The verdict never feeds the decision, the gate, sizing, the
# monthly multiplier or any sell/stop (user rule). Individual reasons stay listed for the detail view.
TECH_REVIEW_POLICY_VERSION = "tech_review_v2_2026-11-25"
LEVERAGE_POLICY = "LEVERAGE_POLICY"
V2_LABELS = {**VERDICT_LABELS, LEVERAGE_POLICY: "레버리지 전용 정책 적용"}
V2_NOTE = "표시 전용(v2): 판정·판정분류·실행게이트·사이징·월적립 배율·매도/손절에 반영하지 않음"
BLOCK_UNREACHABLE_NOTE = (
    "BLOCK(상승 패턴 무효선 이탈)은 현재 구조상 거의 나오지 않음: 패턴 탐지가 종가 기준 무효선 이탈 패턴을 "
    "'무효'로 분류해 먼저 제외하므로, 실시간가와 종가가 다를 때만 가능함. BLOCK을 만들기 위한 조건은 추가하지 않음."
)
LEADER_TYPE_CODES = {"NEW_ENTRY_LEADER", "LEADER_MA5_PULLBACK_ENTRY", "LEADER_MA5_FAST_PULLBACK_ENTRY", "BREAKOUT_52W_ENTRY"}
SCOUT_TYPE_CODES = {"EXCEPTION_ENTRY", "EXCEPTION_ADD_ON"}
STRICT_SUPPLY_GAP = 0.025          # the liquidity profile's own "상단 매물 근접" distance
STRICT_SUPPLY_MIN_INTENSITY = 0.25  # the liquidity profile's own "strong zone" mark

def strategy_type(decision: dict | None, *, has_pos: bool = False, is_etf: bool = False, is_leveraged: bool = False) -> str:
    d = decision if isinstance(decision, dict) else {}
    code = str(d.get("decision_code", "") or "")
    if is_leveraged:
        return "레버리지 ETF"
    if is_etf:
        return "코어 ETF 적립"
    if code in LEADER_TYPE_CODES:
        return "대장주·상승장 진입"
    if code in SCOUT_TYPE_CODES:
        return "예외승인 1/3 정찰"
    if has_pos:
        return "보유 종목 추매"
    if code.startswith("QUALITY_RECOVERY") or code.startswith("HOLDING_QUALITY_RECOVERY"):
        return "우량주 회복"
    return "일반 눌림·기타"


def strict_overhead_supply(liquidity_profile, cur: float) -> tuple[bool | None, str]:
    """Only volume zones lying entirely above the current price count as overhead supply (estimated, not order book)."""
    liq = liquidity_profile if isinstance(liquidity_profile, dict) else {}
    if not liq.get("ok") or not _ok(cur) or cur <= 0:
        return None, ""
    zones = [r for r in (liq.get("rows") or []) if isinstance(r, dict)
             and _ok(_num(r.get("low"))) and _num(r.get("low")) > cur and _num(r.get("intensity")) >= STRICT_SUPPLY_MIN_INTENSITY]
    if not zones:
        return False, ""
    gap = min((_num(r["low"]) - cur) / cur for r in zones)
    return gap <= STRICT_SUPPLY_GAP, f"현재가 위 {gap * 100:.1f}%"


def build_tech_review_v2(decision: dict | None, *, pattern_candidates=None, liquidity_profile=None,
                         invalidated_patterns=None, has_pos: bool = False, is_etf: bool = False,
                         is_leveraged: bool = False) -> dict:
    """Return {"verdict", "label", "strategy_type", "clusters", "reasons", "policy_version", ...} (display only)."""
    from stock_lab_core.chart_patterns import BEARISH_STAGE_OBSERVED, classify_bearish_pattern_stage

    d = decision if isinstance(decision, dict) else {}
    reasons: list[tuple[str, str, str]] = []   # (kind, area, text); kind + - ! ? ·
    cluster_of: list[str] = []                 # cluster of each reason ('' when not counted)

    def add(kind, area, text, cluster=None):
        reasons.append((kind, area, text))
        cluster_of.append(cluster if (cluster and kind in "+-") else "")

    stype = strategy_type(d, has_pos=has_pos, is_etf=is_etf, is_leveraged=is_leveraged)
    momentum_type = stype in {"대장주·상승장 진입", "예외승인 1/3 정찰"}
    cur = _num(d.get("cur_p"))
    pct_b, rsi = _num(d.get("pct_b")), _num(d.get("rsi"))
    ma20, ma50 = _num(d.get("ma20")), _num(d.get("ma50"))
    vol_ratio = _num(d.get("vol_ratio"))
    history = _num(d.get("history_days"))

    # Essential inputs (without them no read is possible) vs auxiliary inputs (only "미확인").
    missing = [name for name, v in (("현재가", cur), ("%B", pct_b), ("RSI", rsi), ("MA20", ma20), ("MA50", ma50)) if not _ok(v)]
    if not d:
        add("?", "필수 데이터", "판정 결과 없음")
    if missing:
        add("?", "필수 데이터", "미확인: " + ", ".join(missing))
    if _ok(history) and history < 60:
        add("?", "보조 데이터", f"일봉 {int(history)}개: 구조 판단에 부족")

    # Trend-weakening cluster (one burden however many of these fire)
    if _ok(cur) and _ok(ma20) and _ok(ma50) and cur > ma20 > ma50:
        add("+", "가격구조", "현재가 > MA20 > MA50 (정배열 위)", "추세")
    if _ok(cur) and _ok(ma50) and cur < ma50:
        add("-", "가격구조", "현재가가 MA50 아래", "추세약화")
    if bool(d.get("structure_risk")):
        add("-", "가격구조", "엔진 구조훼손 표시(엔진이 이미 판정에 반영)", "추세약화")
    if str(d.get("ext_structure", "") or "") == "Bearish":
        add("-", "가격구조", "외부구조 하락(역배열)", "추세약화")
    mtf = str(d.get("mtf_bias_label", "") or "")
    if mtf == "상위 시간대 경고":
        add("-", "상위시간대", "상위 시간대 경고(게이트가 이미 방어우선 처리)", "추세약화")
    elif mtf == "상위 시간대 우호":
        add("+", "상위시간대", mtf, "추세")
    elif mtf in {"", "자료부족"}:
        add("?", "보조 데이터", "상위 시간대 미확인")

    # Overheat cluster: not a burden for leader / exception-scout entries (existing overheat blocks still apply)
    hot_kind = "·" if momentum_type else "-"
    pd_zone = str(d.get("pd_zone", "") or "")
    if _ok(pct_b) and pct_b >= 0.95:
        add(hot_kind, "현재 위치", f"%B {pct_b:.2f}: 밴드 상단 과열권", "과열")
    if _ok(rsi) and rsi >= 75:
        add(hot_kind, "현재 위치", f"RSI {rsi:.0f}: 과열", "과열")
    if "Premium" in pd_zone and _ok(pct_b) and pct_b >= 0.78:
        add(hot_kind, "FVG/PD", "Premium 구간 상단", "과열")
    if mtf == "정찰만 적합":
        add(hot_kind, "상위시간대", "주봉/월봉 과열(정찰만 적합)", "과열")

    # Position supports
    if bool(d.get("is_52w_breakout")):
        add("+", "현재 위치", "52주 신고가 돌파", "위치")
    if "Discount" in pd_zone:
        add("+", "FVG/PD", "Discount 구간", "위치")

    # FVG
    fvg_type = str(d.get("fvg_type", "") or "").lower()
    if bool(d.get("fvg_active")):
        if "bull" in fvg_type or "상승" in fvg_type:
            add("+", "FVG/PD", "활성 상승 FVG 지지", "지지")
        elif "bear" in fvg_type or "하락" in fvg_type:
            add("-", "FVG/PD", "활성 하락 FVG 저항", "저항·하락패턴")

    # Volume
    if _ok(vol_ratio):
        day_ret = _num(d.get("day_ret"))
        if vol_ratio >= 1.5 and _ok(day_ret):
            add("+" if day_ret > 0 else "-", "거래량", f"거래량 {vol_ratio:.1f}배 ({'상승일' if day_ret > 0 else '하락일'})", "거래량")
        elif vol_ratio >= 1.5:
            add("?", "보조 데이터", f"거래량 {vol_ratio:.1f}배 (등락 미확인)")
        elif vol_ratio < 0.5:
            add("-", "거래량", f"거래량 {vol_ratio:.1f}배: 얇음", "거래량")
    else:
        add("?", "보조 데이터", "거래량 비율 미확인")

    # Estimated volume-at-price: only zones entirely above the price count as overhead supply
    liq = liquidity_profile if isinstance(liquidity_profile, dict) else {}
    if liq.get("ok"):
        near, gap_text = strict_overhead_supply(liq, cur)
        if near:
            add("-", "매물대", f"추정 매물대: 상단 매물 근접({gap_text})", "매물")
        status = str(liq.get("status", "") or "")
        if status in {"하단 유동성 지지 확인", "하단 유동성 우세"}:
            add("+", "매물대", f"추정 매물대: {status}", "지지")
        elif status in {"상단 매물 근접", "상단 매물 부담"} and not near:
            add("·", "매물대", f"추정 매물대(기존 표시): {status} · 현재가 위 독립 매물 구간 기준으로는 근접 아님")
    elif liquidity_profile is not None:
        add("?", "보조 데이터", f"추정 매물대 미확인: {liq.get('reason', '자료 부족')}")

    # Chart pattern (C-4 stages), formation period as reliability reference only
    pattern = next((p for p in (pattern_candidates or []) if isinstance(p, dict)), None)
    if pattern:
        name, status = pattern.get("name", "패턴"), str(pattern.get("status", "") or "")
        direction = pattern.get("direction", "neutral")
        invalid = _num(pattern.get("invalid_price"))
        days = _formation_days(pattern)
        reliability = ("" if not _ok(days) else
                       f" · 형성 {int(days)}일" + (": 짧아 신뢰 낮음" if days < SHORT_FORMATION_DAYS else ""))
        if direction == "bullish" and _ok(invalid) and _ok(cur) and cur < invalid:
            add("!", "시나리오", f"{name} 무효선 이탈: 회복 시나리오 훼손")
        elif direction == "bullish" and status in {"돌파", "상방돌파"}:
            add("+", "패턴", f"{name} {status}{reliability}", "패턴")
        elif direction == "bearish":
            stage = classify_bearish_pattern_stage(pattern, d)
            if stage == BEARISH_STAGE_OBSERVED:
                add("·", "패턴", f"{name} 하락 패턴 {stage}{reliability} (판정 영향 없음)")
            else:
                add("-", "패턴", f"{name} 하락 패턴 {stage}{reliability}", "저항·하락패턴")
        elif reliability:
            add("·", "형성기간", f"{name}{reliability}")
    for inv in invalidated_patterns or []:
        if isinstance(inv, dict) and inv.get("direction") == "bearish":
            add("·", "패턴", f"{inv.get('name', '패턴')} 하락 패턴 무효화(무효선 회복) · 다른 안전장치는 그대로 적용")
            break

    neg = sorted({c for (k, _, _), c in zip(reasons, cluster_of) if c and k == "-"})
    pos = sorted({c for (k, _, _), c in zip(reasons, cluster_of) if c and k == "+"})
    kinds = [k for k, _, _ in reasons]
    if is_leveraged:
        verdict = LEVERAGE_POLICY
    elif missing or not d:
        verdict = DATA_CHECK
    elif "!" in kinds:
        verdict = BLOCK
    elif (len(neg) >= 2 and len(neg) > len(pos)) or (len(neg) >= 1 and not pos):
        verdict = CAUTION
    elif len(pos) >= MIN_CONFIRM_SIGNALS and len(pos) - len(neg) >= MIN_CONFIRM_SIGNALS:
        verdict = CONFIRM
    else:
        verdict = NEUTRAL
    clusters = []
    for sign, label in (("-", "부담"), ("+", "지지")):
        for name in (neg if sign == "-" else pos):
            items = [t for (k, _, t), c in zip(reasons, cluster_of) if k == sign and c == name]
            clusters.append({"구분": label, "묶음": name, "개별 근거": " / ".join(items)})
    type_note = ("대장주·예외승인: 과열은 부담으로 세지 않음(실제 추세훼손·기존 과열 차단 정책은 그대로)"
                 if momentum_type else "")
    return {
        "policy_version": TECH_REVIEW_POLICY_VERSION, "verdict": verdict, "label": V2_LABELS[verdict],
        "strategy_type": stype, "type_note": type_note, "clusters": clusters, "reasons": reasons,
        "burden_clusters": neg, "support_clusters": pos, "unchecked": kinds.count("?"),
        "note": V2_NOTE, "block_note": BLOCK_UNREACHABLE_NOTE,
    }


def tech_review_v2_record(review: dict) -> dict:
    """JSON-friendly record (policy version + state + clusters + individual reasons) for later operating checks."""
    return {
        "policy_version": review.get("policy_version"), "verdict": review.get("verdict"),
        "strategy_type": review.get("strategy_type"), "burden_clusters": list(review.get("burden_clusters") or []),
        "support_clusters": list(review.get("support_clusters") or []),
        "reasons": [{"kind": k, "area": a, "text": t} for k, a, t in review.get("reasons") or []],
    }


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
