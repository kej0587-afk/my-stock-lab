"""Precision page panel for the B-4 tech review shadow (display only)."""

from __future__ import annotations

import pandas as pd

from stock_lab_core.decision_behavior_groups import behavior_group_label
from stock_lab_core.leverage_stage import resolve_leverage_stage
from stock_lab_core.tech_review import build_tech_review_shadow

_KIND_TEXT = {"+": "지지", "-": "부담", "!": "훼손", "?": "미확인", "·": "참고"}


def tech_review_rows(decision, workflow, *, pattern_candidates=None, liquidity_profile=None,
                     monthly_signal_decision=None, multiplier_fn=None) -> dict:
    """Build the panel model without touching ``decision`` (a copy is never written back)."""
    d = decision if isinstance(decision, dict) else {}
    wf = workflow if isinstance(workflow, dict) else {}
    review = build_tech_review_shadow(d, pattern_candidates=pattern_candidates, liquidity_profile=liquidity_profile)
    summary = [
        {"항목": "기존 판정", "값": str(d.get("dec", "-") or "-")},
        {"항목": "판정코드 · 행동그룹", "값": f"{d.get('decision_code', '-') or '-'} · {behavior_group_label(d.get('decision_code'))}"},
        {"항목": "판정분류 · 실행게이트", "값": f"{wf.get('판정분류', '-') or '-'} · {wf.get('게이트상태', '-') or '-'}"},
        {"항목": "기술검토(그림자)", "값": f"{review['verdict']} · {review['label']}"},
    ]
    mult = None
    if isinstance(monthly_signal_decision, dict) and callable(multiplier_fn):
        try:
            mult = multiplier_fn(monthly_signal_decision, "leverage", 0)
        except Exception:
            mult = None
    lev = resolve_leverage_stage(d, gate_state=wf.get("게이트상태"), market_state=wf.get("시장실행상태"),
                                 monthly_multiplier=mult)
    if lev:
        mult_text = "미확인(월간 신호 캐시 없음)" if lev["monthly_multiplier"] is None else f"×{lev['monthly_multiplier']:g}"
        summary.append({"항목": "레버리지 단계", "값": f"{lev['stage']} {lev['stage_label']} · 월간 배율 {mult_text}"
                        + (" · 계획금액≠실행게이트" if lev["plan_gate_mismatch"] else "")})
    reasons = [{"구분": area, "방향": _KIND_TEXT.get(kind, kind), "근거": text} for kind, area, text in review["reasons"]]
    return {"review": review, "leverage": lev, "summary": summary, "reasons": reasons}


def render_tech_review_shadow(st, decision, workflow, **kwargs) -> dict:
    model = tech_review_rows(decision, workflow, **kwargs)
    with st.expander(f"🔬 기술검토(그림자) · {model['review']['verdict']} {model['review']['label']}", expanded=False):
        st.caption(model["review"]["note"] + " · 관찰용 임계값(미검증)")
        st.dataframe(pd.DataFrame(model["summary"]), width="stretch", hide_index=True)
        if model["reasons"]:
            st.dataframe(pd.DataFrame(model["reasons"]), width="stretch", hide_index=True)
        else:
            st.caption("근거로 잡힌 항목이 없습니다.")
    return model


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
