"""Display-only separation of existing financial/valuation results; no scoring/I/O."""

from collections.abc import Mapping
from itertools import islice

from stock_lab_core.financial_score import optional_float


MAX_ROWS = 64
MAX_ATTEMPTS = 16
_GROUPS = (
    ("actual", "실제 실적·수익성", "실제 보고 실적 미연결"),
    ("consensus", "애널리스트 컨센서스", "목표가 미연결 · 동일 분기 실적 예상치와 별도"),
    ("guidance", "회사 가이던스", "회사 전망 원문 미연결 · 목표가·과거 성장률로 대체하지 않음"),
    ("valuation", "밸류에이션 배수", "가격 배수 미연결"),
)
_ACTUAL = {"연매출", "영업이익", "순이익", "매출 성장", "이익 성장", "순이익률", "영업이익률"}
_VALUATION = {"PER", "PBR", "PSR", "PEG"}
_STATUSES = {
    "available": "조회 성공", "no_target": "목표가 미제공", "no_data": "자료 미제공",
    "rate_limited": "조회 제한", "lookup_error": "조회 실패", "error": "조회 실패",
    "timeout": "조회 시간 초과", "stale": "이전 자료 · 재조회 필요",
    "disabled": "연결 비활성", "missing_configuration": "연결 설정 미완료",
    "invalid_configuration": "연결 설정 확인 필요", "etf_excluded": "ETF/ETN 목표가 해당없음",
    "unavailable": "자료 미연결", "cooldown": "재조회 대기",
}


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "<na>"} else text


def _lookup_notes(snapshot, label):
    if snapshot is None:
        return []
    snapshot = _mapping(snapshot)
    status = _text(snapshot.get("status"))
    notes = []
    if snapshot.get("stale") is True or status == "stale":
        notes.append(f"{label}: 이전 자료 · 재조회 필요")
    elif snapshot.get("ok") is not True or status in {"rate_limited", "lookup_error", "error", "timeout"}:
        notes.append(f"{label}: {_STATUSES.get(status, '조회 실패/자료 미연결')}")
    reason = _text(snapshot.get("reason"))
    if reason:
        # Never echo provider errors, URLs, request bodies or credential-bearing text.
        failed = any(word in reason.casefold() for word in ("실패", "제한", "error", "timeout", "rate_limit"))
        if failed:
            notes.append(f"{label}: 일부 조회 실패/제한 · 확보된 자료와 구분")
        elif snapshot.get("ok") is True:
            notes.append(f"{label}: 공급자 기준·제공 범위 제한사항 있음")
    attempts = snapshot.get("provider_attempts")
    for attempt in islice(attempts if isinstance(attempts, (list, tuple)) else (), MAX_ATTEMPTS):
        attempt = _mapping(attempt)
        state = _text(attempt.get("status"))
        if state not in ("", "available"):
            provider = _text(attempt.get("source"))
            provider = provider if provider in {"Yahoo Finance financialData", "yfinance.get_info",
                "yfinance.get_analyst_price_targets", "FnGuide", "FMP", "Naver/KRX", "Kiwoom REST ka10001"} else "공급자"
            notes.append(f"{label} / {provider}: {_STATUSES.get(state, '조회 상태 미확인')}")
    return notes


def build_valuation_presentation(valuation, *, snapshot=None, analyst_snapshot=None, fin_meta=None):
    """Group the existing rendered values without recalculation or new lookups.

    Inputs and score/headline/count fields remain untouched. Only exact duplicate
    rows are removed; conflicting rows remain visible with a diagnostic. Generic
    PER is labeled using the same finite-forward-first selection as the app.
    No guidance is inferred from targets, forward multiples or growth fields.
    Up to 64 input rows and 16 attempts per snapshot are inspected.
    """
    valuation = _mapping(valuation)
    forward, trailing = (optional_float(valuation.get(key)) for key in ("forward_pe", "trailing_pe"))
    per_label = "선행 PER(예상 이익)" if forward is not None else "후행 PER(과거 이익)" if trailing is not None else "PER(기준 미확인)"
    sections = [{"id": key, "title": title, "rows": [], "missing": missing} for key, title, missing in _GROUPS]
    buckets = {section["id"]: section["rows"] for section in sections}
    diagnostics = _lookup_notes(snapshot, "밸류 조회") + _lookup_notes(analyst_snapshot, "컨센서스 조회")
    notes = _mapping(_mapping(fin_meta).get("notes"))
    if _mapping(fin_meta).get("valuation_lookup_status") == "failed":
        diagnostics.append("밸류 보강용 재무 조회 실패 · 기존 점수·원자료 유지, 실적 부진 판정 아님")
    elif notes.get("ok") is False or _mapping(fin_meta).get("source") == "valuation_fin_fetch_failed":
        diagnostics.append("재무 원자료 조회 실패 · 기존 간이/임시 점수 유지, 실적 부진 판정 아님")
    rows = valuation.get("rows")
    rows = rows if isinstance(rows, (list, tuple)) else []
    if len(rows) > MAX_ROWS:
        diagnostics.append("표시 행 한도 초과 · 일부 상세 행 보류")
    seen, values_by_name, duplicates = set(), {}, 0
    for raw in rows[:MAX_ROWS]:
        if not isinstance(raw, Mapping):
            continue
        name, value, verdict = (_text(raw.get(key)) for key in ("항목", "값", "판정"))
        if not name:
            continue
        context = tuple((key, _text(raw.get(key))) for key in ("기준일", "기간", "출처", "통화", "회계기준") if _text(raw.get(key)))
        identity = (name, value, verdict, context)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        if (name, context) in values_by_name and values_by_name[(name, context)] != (value, verdict):
            diagnostics.append(f"{name}: 중복 항목의 표시값/판정 불일치 · 원자료 확인 필요")
        values_by_name[(name, context)] = (value, verdict)
        if name in _ACTUAL:
            group, basis = "actual", "과거 보고 수치 · 보고기간·통화·회계기준 확인 필요"
            if "성장" in name:
                basis = "과거 대비 성장률 · 컨센서스 상회/회사 전망 아님"
        elif name == "목표가 업사이드":
            group, basis = "consensus", "애널리스트 목표가 대비 · 적정가 보장/실적 예상치/회사 전망 아님"
        elif name in _VALUATION:
            group, basis = "valuation", "가격 배수 · 실제 실적/회사 전망과 별도"
            if name == "PER":
                basis = "공급자 예상 이익 기준 · 회사 가이던스 아님" if forward is not None else "과거 이익 기준 · 보고기간 확인 필요" if trailing is not None else "사용 이익 기준 미확인"
        else:
            group, basis = "unclassified", "기존 표시 항목 · 분류 미확인"
            if group not in buckets:
                buckets[group] = []
                sections.append({"id": group, "title": "기타 기존 지표", "rows": buckets[group], "missing": ""})
        buckets[group].append({"항목": per_label if name == "PER" else name,
                               "값": value or "미연결", "판정": verdict or "미확인", "구분·한계": basis, **dict(context)})
    return {"sections": sections, "diagnostics": list(dict.fromkeys(diagnostics)),
            "per_label": per_label, "duplicate_rows_removed": duplicates}


def render_valuation_details(ui, presentation):
    """Keep collection failures visible even when detail tables are collapsed."""
    import pandas as pd

    for note in presentation["diagnostics"]:
        ui.caption(note)
    with ui.expander("실적·컨센서스·밸류 세부 근거", expanded=False):
        for section in presentation["sections"]:
            ui.caption(section["title"])
            if section["rows"]:
                ui.dataframe(pd.DataFrame(section["rows"]), width="stretch", hide_index=True)
            else:
                ui.caption(section["missing"])


def financial_score_display_rows(fin_meta, weighted=None):
    """Keep genuine zero scores visible; never turn absent scores into zero."""
    fin_meta, weighted = _mapping(fin_meta), _mapping(weighted)
    def rows(source, fields):
        output = []
        for label, key in fields:
            value = source.get(key)
            display = _text(value) if key in {"source", "mode", "selected_mode"} or optional_float(value) is not None else ""
            output.append({"항목": label, "값": display or "-"})
        return output
    return {
        "meta_rows": rows(fin_meta, [(key, key) for key in ("source", "mode", "auto_score", "manual_score", "final_score")]),
        "weighted_rows": rows(weighted, [("weighted score", "weighted_net_score"), ("S_sum", "s_sum"),
            ("A_sum", "a_sum"), ("B_sum", "b_sum"), ("danger_count", "danger_count"),
            ("범용판단", "generic_score"), ("수주판단", "order_score"), ("중간형판단", "middle_score"),
            ("selected_mode", "selected_mode")]) if weighted else [],
    }
