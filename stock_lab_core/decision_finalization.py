"""Final safety and sizing orchestration with explicit policy dependencies."""

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def finalize_decision_sizing(
    *, decision_outcome, dec, col, buy_amount, safety_state, has_pos,
    tech_total, main_score, adj_tech_score, weight_gap, is_core_dca_allowed,
    is_etf, current_dd, indicator_data_issue, targ_w, eff_total, cur_p, ticker,
    _apply_safety_state_override, _translate_new_entry_decision_for_holding,
    enforce_non_core_panic_scope, build_decision_outcome, _compute_sizing_hint,
):
    """Return the five final locals without changing policy order or amounts."""
    dec, col, decision_outcome = _apply_safety_state_override(
        decision_outcome, dec, col,
        safety_state=safety_state, has_pos=has_pos,
        tech_total=tech_total, main_score=main_score, adj_tech_score=adj_tech_score,
    )
    decision_outcome = _translate_new_entry_decision_for_holding(
        decision_outcome, has_pos=has_pos, weight_gap=weight_gap,
    )
    decision_outcome = enforce_non_core_panic_scope(
        decision_outcome,
        is_core_dca_allowed=is_core_dca_allowed,
        is_etf=is_etf,
        current_dd=current_dd,
    )
    if indicator_data_issue:
        decision_outcome = build_decision_outcome(
            "⚪데이터확인: 실시간 지표 재계산 필요", "#64748b", "DATA_ERROR",
            reasons=(indicator_data_issue, "새 가격과 이전 지표가 섞이지 않도록 직전 가격 이력으로 복원했습니다."),
        )
        buy_amount = 0.0
    dec, col = decision_outcome.label, decision_outcome.color
    sizing_hint = _compute_sizing_hint(
        decision_outcome,
        has_pos=has_pos, targ_w=targ_w, eff_total=eff_total, cur_p=cur_p, is_etf=is_etf,
        weight_gap=weight_gap, ticker=ticker,
    )
    return decision_outcome, dec, col, buy_amount, sizing_hint
