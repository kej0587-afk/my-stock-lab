"""Explain the existing scorecard without adding another trading vote."""

from collections.abc import Mapping
import math


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def build_scorecard_review(rows, factors, *, is_etf=False):
    """Coverage describes source completeness, never company quality."""
    factors = [item for item in factors if isinstance(item, Mapping)]
    axes = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = row.get("축", "")
        members = [item for item in factors if item.get("축") == name]
        if is_etf and name != "모멘텀":
            continue
        known = sum(_number(item.get("점수")) is not None for item in members)
        total = len(members)
        score = _number(row.get("점수")) if known else None
        axes.append({"축": name, "점수": score, "확인": known, "전체": total,
                     "자료상태": "미수집" if not known else "부분자료" if known < total else "충족",
                     "근거": row.get("근거", "")})
    comparable = [item for item in axes if item["축"] != "모멘텀" and item["점수"] is not None
                  and item["확인"] >= 2 and item["확인"] * 2 >= item["전체"]]
    ranked = sorted(comparable, key=lambda item: item["점수"], reverse=True)
    strongest = ranked[0] if len(ranked) >= 2 else None
    weakest = ranked[-1] if len(ranked) >= 2 and ranked[0]["점수"] != ranked[-1]["점수"] else None
    warnings = []
    for item in factors:
        value = _number(item.get("값"))
        if value is not None and value < 0 and item.get("항목") in {
            "ROE", "ROA", "영업이익률", "순이익률", "매출 성장", "이익 성장", "영업현금흐름", "잉여현금흐름",
        }:
            warnings.append(f"{item['항목']} 음수")
        if value is not None and value <= 0 and item.get("항목") in {"후행 PER", "선행 PER"}:
            warnings.append(f"{item['항목']} 0 이하: 저평가로 간주하지 않음")
    return {"version": "scorecard-review-v1", "mode": "evidence_only", "axes": axes,
            "strongest": strongest, "weakest": weakest,
            "warnings": warnings, "missing_axes": [item["축"] for item in axes if not item["확인"]],
            "partial_axes": [item["축"] for item in axes if item["자료상태"] == "부분자료"],
            "score_added": 0, "thresholds_changed": False}


def scorecard_decision_context(scorecard, workflow, fin_score, *, is_etf=False):
    """Relate source scores to the authoritative gate, not a new verdict."""
    scorecard = scorecard if isinstance(scorecard, Mapping) else {}
    workflow = workflow if isinstance(workflow, Mapping) else {}
    review = scorecard.get("review")
    if not isinstance(review, Mapping):
        return {"status": "unavailable", "summary": "성적표 자료 미연결", "score_added": 0}
    parts = []
    for key, label in (("strongest", "상대적으로 높은 축"), ("weakest", "상대적으로 낮은 축")):
        axis = review.get(key)
        if isinstance(axis, Mapping):
            parts.append(f"{label}: {axis['축']} {axis['점수']:.1f}점({axis['확인']}/{axis['전체']}항목)")
    momentum = next((item for item in review.get("axes", []) if item.get("축") == "모멘텀"), {})
    if _number(momentum.get("점수")) is not None:
        parts.append(f"모멘텀 {momentum['점수']:.1f}점({momentum['확인']}/{momentum['전체']}항목)")
    if not parts:
        parts.append("축 간 비교에 필요한 자료 부족")
    state = str(workflow.get("게이트상태") or "데이터확인")
    restriction = "실행 조건을 별도로 확인합니다" if state == "실행가능" else "성적표가 좋아도 실행 제한을 해제하지 않습니다"
    return {"status": "linked", "summary": " · ".join(parts) + f". 현재 게이트 {state}: {restriction}.",
            "stored_financial_score": None if is_etf else _number(fin_score),
            "review": dict(review), "source": scorecard.get("source", ""),
            "price_asof": scorecard.get("price_asof", ""),
            "financial_basis": scorecard.get("financial_basis", {}),
            "score_added": 0, "thresholds_changed": False}


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
