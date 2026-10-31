"""Separate quality, timing and execution; count economic evidence once."""

from collections import defaultdict
from collections.abc import Mapping
import math

from stock_lab_core.financial_freshness import financial_basis


POLICY_VERSION = "independent-evidence-v1"
_CHECK_IDS = {
    "재무/상품": "quality", "레버리지": "leverage", "레버리지 타점": "leverage",
    "레버리지 DCA": "leverage", "데이터": "data.history", "현재가": "price",
    "신규ETF 2차검증": "product.verification", "밸류/가격": "valuation",
    "구조/추세": "structure", "상위 시간대": "mtf", "과열": "overheat",
    "횡보/눌림 품질": "sideways", "손익비": "rr", "비중": "weight",
    "매크로": "macro", "보유상태": "holding",
}
_RANK = {"통과": 0, "주의": 1, "미확인": 2, "차단": 3}
_CORE_DATA = {"price", "data", "data.history", "mtf", "overheat", "macro", "rr", "market", "gate.local"}


def quality_label(fin_score, fin_meta=None, *, is_etf=False):
    if is_etf:
        return "기업재무 해당없음"
    meta = fin_meta if isinstance(fin_meta, Mapping) else {}
    label = f"{fin_score}/4"
    if meta.get("manual_score") is not None:
        return label + " · 수동 지정"
    try:
        known = meta.get("auto_score") is not None and math.isfinite(float(meta["auto_score"]))
    except (TypeError, ValueError, OverflowError):
        known = False
    return label if known else label + " · 임시/미계산"


def independent_check_summary(rows, workflow):
    """Keep all display rows, but summarize distinct structured evidence IDs.

    A successful system gate is a summary, not another positive vote. A failed
    legacy gate without IDs stays independent: prose is never guessed away.
    Specific rows win ties over aggregate rows, and worst known status wins.
    """
    workflow = workflow if isinstance(workflow, Mapping) else {}
    out, buckets = [dict(row) for row in rows], defaultdict(list)
    for index, row in enumerate(out):
        category = row.get("점검항목", "")
        aggregate = category == "시스템 타점"
        if aggregate and workflow.get("게이트상태") == "실행가능":
            # A saved gate must not erase a newer local veto or unknown state.
            ids = [] if row.get("상태") == "통과" else ["gate.local"]
        elif aggregate:
            raw = workflow.get("게이트근거ID")
            ids = list(dict.fromkeys(x for x in str(raw or "").split("|") if x)) or ["gate.unresolved"]
        else:
            ids = [_CHECK_IDS.get(category, "check." + str(category))]
        row["근거ID"] = "|".join(ids)
        row["집계"] = "요약" if aggregate else ""
        for evidence_id in ids:
            buckets[evidence_id].append((index, row, aggregate))

    counts = {status: 0 for status in _RANK}
    evidence, chosen = [], set()
    for evidence_id, members in buckets.items():
        index, row, _ = max(members, key=lambda member: (
            _RANK.get(member[1].get("상태"), 2), not member[2], -member[0]))
        status = row.get("상태") if row.get("상태") in _RANK else "미확인"
        counts[status] += 1
        chosen.add(index)
        evidence.append({"근거ID": evidence_id, "상태": status,
                         "대표항목": row.get("점검항목", ""),
                         "연결항목": " · ".join(dict.fromkeys(m[1].get("점검항목", "") for m in members))})
    for index, row in enumerate(out):
        if index in chosen:
            row["집계"] = "독립근거"
        elif row["근거ID"]:
            row["집계"] = "중복 제외"
    missing = [item["근거ID"] for item in evidence if item["상태"] == "미확인" and item["근거ID"] in _CORE_DATA]
    return out, {
        "status_counts": counts, "evidence": evidence,
        "core_missing_ids": missing, "duplicate_count": sum(max(0, len(members) - 1) for members in buckets.values()),
        "policy_version": POLICY_VERSION,
    }


def role_rows(decision, workflow, fin_score, fin_meta=None, *, is_etf=False):
    """Display independent responsibilities; do not score or permit a trade."""
    decision = decision if isinstance(decision, Mapping) else {}
    workflow = workflow if isinstance(workflow, Mapping) else {}
    fin_meta = fin_meta if isinstance(fin_meta, Mapping) else {}
    basis = financial_basis(fin_meta, is_etf=is_etf)
    quality = ("레버리지/인버스 상품" if decision.get("is_leveraged_or_inverse") else "ETF/ETN · 기업재무 해당없음") if is_etf else quality_label(fin_score, fin_meta)
    return [
        {"구분": "상품 구조" if is_etf else "기업 품질", "평가": quality, "근거": basis["재무자료기간"], "자료상태": basis["재무자료상태"]},
        {"구분": "기술 타점", "평가": workflow.get("🔥기술적 타점") or decision.get("dec", "미확인"),
         "근거": decision.get("mtf_bias_label") or "상위 시간대 미확인", "자료상태": workflow.get("데이터상태") or "미확인"},
        {"구분": "계좌 실행 제한", "평가": workflow.get("게이트상태", "데이터확인"),
         "근거": workflow.get("게이트근거", "실행 근거 미확인"), "자료상태": workflow.get("게이트근거ID", "기존 결과") or "정상 조건"},
    ]
