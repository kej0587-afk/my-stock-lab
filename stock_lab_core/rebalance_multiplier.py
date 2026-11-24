"""Monthly rebalance signal multiplier (B-3, 2026-11-24).

The multiplier used to be read from the decision label text. It now comes from the
decision code (and the core DCA stage), through a table generated from the old parser,
so every result is unchanged. The old parser stays only as a fallback for text that is
not an engine decision (cash rows, failures) or a label the table has never seen.
"""

from stock_lab_core.rebalance_multiplier_table import (
    KNOWN_LABELS_BY_CODE,
    MULTIPLIER_BY_CODE,
    MULTIPLIER_BY_CODE_LABEL,
    MULTIPLIER_BY_CORE_STAGE,
)

CORE_DCA_CODES = frozenset(code for code, _ in MULTIPLIER_BY_CORE_STAGE)
FALLBACK_COUNTER = {"table": 0, "legacy": 0}


def legacy_label_multiplier(tap: str, bucket: str, dip_level: int = 0) -> float:
    """기술적타점 문자열 → 배분 배율
    버킷별 로직:
      core    : 신호없음=1.0(DCA), 매수=1.0, 과열=0.25, 차단=0.0
      leverage: 가격/급락/추세방어=0.0, 과열=0.0, 신호없음=0.5(DCA유지),
                매수=1.5, 매수+약하락(dip1)=1.5, 매수+중하락(dip2)=1.75, 매수+강하락(dip3)=2.0
                대기/신호없음+약하락=0.75, +중하락=1.0, +강하락=1.25
      swing   : 명시적 매수 신호 없으면 0.0
    dip_level: 0=정상, 1=-5%~-10%(약하락), 2=-10%~-15%(중하락), 3=-15%↓(강하락)
    """
    tap = str(tap).strip()
    bucket = str(bucket).strip().lower()
    is_empty = tap in ("-", "", "nan", "none", "None")
    no_add_words = [
        "추매금지", "추매중단", "매수금지", "신규금지", "진입 보류", "진입보류", "DCA 보류",
        "회복 전", "원인점검", "원인 점검", "종가 확인", "정규장 확인",
    ]
    hard_words = [
        "하드", "차단", "구조", "추세훼손", "가격위험", "단기급락",
        "가격방어", "급락방어", "추세방어", "비중 초과", "비중초과",
        "비중 충족", "비중충족", "시장위험", "보유점검", "🔴", "⛔",
    ]
    is_no_add = any(k in tap for k in no_add_words)
    is_hard = is_no_add or any(k in tap for k in hard_words)
    is_hot = any(k in tap for k in ["과열", "주의", "⚠"])
    is_wait = any(k in tap for k in ["평단", "하락", "대기", "⏸"])
    is_buy = (
        not is_hard
        and (
            any(k in tap for k in ["매수", "분할", "🟢", "✅", "🟣"])
            or ("진입" in tap and "보류" not in tap and "금지" not in tap)
        )
    )

    # ── 레버리지 버킷 (QLD, TQQQ 등) ────────────────────────────────────────
    if bucket == "leverage":
        leverage_block = is_hard or any(k in tap for k in ["급락:", "패닉권", "패닉", "투매"])
        if leverage_block: return 0.0   # 가격/급락/추세 방어 → 완전 중단
        if is_hot:  return 0.0   # 과열 → 진입 금물
        if any(k in tap for k in ["DCA 대기", "타점 대기", "눌림 대기", "추격금지"]):
            return 0.0
        if any(k in tap for k in ["회복 DCA", "분할 가능"]):
            return 1.0
        if any(k in tap for k in ["조건부 DCA", "소액 1차", "신규 1차 정찰 가능", "타점 가능"]):
            return 0.5
        if is_buy:
            # 매수 신호: 하락 깊이에 따라 배율 상향
            if dip_level >= 3: return 2.0    # 매수 + 강하락(-15%↓) → 2배 집중
            if dip_level == 2: return 1.75   # 매수 + 중하락(-10%~-15%) → 1.75배
            return 1.5                       # 매수 + 약하락 or 정상 → 1.5배
        if is_wait:
            return 0.0
        if is_empty:
            # 신호없음/대기: 하락 깊이에 따라 DCA 강도 조절
            if dip_level >= 3: return 1.25   # 강하락 → 1.25배 DCA
            if dip_level == 2: return 1.0    # 중하락 → 1배 DCA
            if dip_level == 1: return 0.75   # 약하락 → 0.75배 DCA
        return 0.5                           # 그외 (정상 구간) → 0.5배 DCA

    # ── 코어 버킷 ────────────────────────────────────────────────────────────
    if tap in ("-", "", "nan", "none", "None"):
        return 1.0 if bucket == "core" else 0.0
    if is_hard: return 0.0
    if bucket == "core":
        if "200%" in tap:
            return 2.0
        if "150%" in tap:
            return 1.5
        if "100%" in tap:
            return 1.0
        if "50%" in tap:
            return 0.5
        if "25%" in tap:
            return 0.25
    if is_buy:  return 1.0
    if is_hot:  return 0.25
    if is_wait: return 0.0

    # 스윙은 명시적 매수 신호 없으면 0%
    if bucket == "swing":
        return 0.0

    # 코어: 보유/중립 → 50%
    return 0.5


def _dip_index(dip_level) -> int:
    try:
        level = int(dip_level or 0)
    except (TypeError, ValueError):
        level = 0
    return min(max(level, 0), 3)


def decision_signal_multiplier(decision, bucket: str, dip_level: int = 0) -> float:
    """Multiplier from decision_code / core DCA stage; legacy text parse only as fallback.

    ``decision`` is an engine result (dict with decision_code, dec, core_dca_label) or a
    plain signal string (cash rows, failures, older caches).
    """
    bucket_key = str(bucket).strip().lower()
    if not isinstance(decision, dict):
        FALLBACK_COUNTER["legacy"] += 1
        return legacy_label_multiplier(str(decision if decision is not None else "-"), bucket, dip_level=dip_level)
    code = str(decision.get("decision_code", "") or "").strip()
    label = str(decision.get("dec", "") or "").strip()
    row = None
    if code in CORE_DCA_CODES:
        row = MULTIPLIER_BY_CORE_STAGE.get((code, str(decision.get("core_dca_label", "") or "").strip()))
        if row is not None and not label.endswith(str(decision.get("core_dca_label", "")).strip()):
            row = None
    elif label in KNOWN_LABELS_BY_CODE.get(code, ()):
        row = MULTIPLIER_BY_CODE_LABEL.get((code, label)) or MULTIPLIER_BY_CODE.get(code)
    if row is None or bucket_key not in row:
        FALLBACK_COUNTER["legacy"] += 1
        return legacy_label_multiplier(label or "-", bucket, dip_level=dip_level)
    FALLBACK_COUNTER["table"] += 1
    return row[bucket_key][_dip_index(dip_level)]


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
