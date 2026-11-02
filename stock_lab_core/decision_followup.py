"""Personal-mode follow-up decisions after the existing priority guards."""

from stock_lab_core.decision_engine import (
    DecisionOutcome,
    build_core_dca_outcome,
    build_decision_outcome,
    build_limited_history_etf_outcome,
)
from stock_lab_core.decision_policies import (
    select_profitable_holding_decision,
    select_holding_decision,
    select_new_entry_decision,
)
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _select_core_or_technical_signal(
    *,
    core_dca_context, core_dca_rate, cur_p, curr_w, has_pos, history_days, is_breakout_extreme,
    is_breakout_normal, is_core_dca_allowed, is_etf, is_etf_accumulation_ok,
    is_stock_add_on_strength, mfi_now, my_price, pct_b_now, price_vs_avg, rsi_now,
    short_history, targ_w, trend, weight_gap,
) -> DecisionOutcome | None:
    """Preserve core/history/overheat/entry precedence; None defers to positions."""
    if is_core_dca_allowed:
        dca_label = core_dca_context["core_dca_label"]
        prefix = "🧱신규 코어 ETF" if short_history else "🧱코어"
        decision_outcome = build_core_dca_outcome(prefix, core_dca_rate, dca_label)
        return decision_outcome
    elif is_etf and short_history:
        decision_outcome = build_limited_history_etf_outcome(
            history_days, has_pos, my_price, cur_p, targ_w, curr_w, weight_gap,
            rsi_now, mfi_now, pct_b_now, price_vs_avg
        )
        return decision_outcome
    elif mfi_now >= 85:
        return build_decision_outcome(
            "🚫하드차단: MFI 극단 과열", "#dc2626", "HARD_BLOCK_MFI_OVERHEAT",
            reasons=(
                f"MFI {mfi_now:.0f} (기준: 85 초과) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "자금흐름 극단 과열 — 추격 매수 위험, 눌림 후 재진입",
            ),
        )
    elif is_breakout_extreme:
        return build_decision_outcome(
            "⚠️과열확장: 추격금지, MA5 대기", "#d97706", "OVERHEAT_EXTENSION_WAIT_MA5",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                "과열 확장 구간 — MA5 눌림 확인 후 추가",
            ),
        )
    elif is_breakout_normal:
        return build_decision_outcome(
            "🔥불뿜는 대장주: MA5 눌림 진입", "#ec4899", "LEADER_MA5_PULLBACK_ENTRY",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                "불뿜는 대장주 — MA5 눌림 진입 기회",
            ),
        )
    elif (not is_etf) and pct_b_now >= 0.95:
        return build_decision_outcome(
            "⏳볼린저 상단 초과: 추격대기" if pct_b_now > 1 else "⏳볼린저 상단권: 추격대기", "#dc2626", "HARD_BLOCK_BOLLINGER_UPPER",
            reasons=(
                f"%B {pct_b_now:.2f} (기준: 0.95 이상) / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                "볼린저 상단권: 신규 추격은 대기, 하락 예측이나 매도 확정 아님",
            ),
        )
    elif is_etf_accumulation_ok and weight_gap >= 10:
        return build_decision_outcome(
            "✅ETF 비중부족 큼: 소액 적립 허용", "#16a34a", "ETF_LARGE_GAP_DCA_OK",
            reasons=(
                f"목표비중 {targ_w:.1f}% 대비 {weight_gap:.1f}%p 부족 (큰 미달)",
                f"ETF 적립 허용 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / 추세 {trend}",
            ),
        )
    elif is_etf_accumulation_ok:
        return build_decision_outcome(
            "✅ETF 목표비중 미달: 적립식 매수 가능", "#16a34a", "ETF_DCA_OK",
            reasons=(
                f"목표비중 {targ_w:.1f}% 대비 {weight_gap:.1f}%p 부족",
                f"ETF 적립 가능 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / 추세 {trend}",
            ),
        )
    elif is_stock_add_on_strength:
        return build_decision_outcome(
            "✅상승확인: 2차 정찰 추매 가능", "#16a34a", "STRENGTH_ADD_ON_OK",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                "상승 확인 후 2차 정찰 추매 — 조건 충족",
            ),
        )
    return None


def select_portfolio_followup_decision(
    *,
    _fmr, adj_tech_score, core_dca_context, core_dca_rate, cur_p, curr_w, current_dd, day_ret,
    day_ret_label, fin_score, grade, has_pos, history_days, is_52w_breakout,
    is_breakout_extreme, is_breakout_normal, is_clean_leader_entry, is_concentrated_upper_wait,
    is_core_dca_allowed, is_core_etf, is_early_entry, is_etf, is_etf_accumulation_ok,
    is_holding_upper_pullback_wait, is_quality_recovery_candidate, is_quality_recovery_scout,
    is_quality_recovery_watch, is_stock_add_on_strength, is_tdf_or_fund, live_ref_ret,
    ma20_now, ma5_now, mfi_now, my_price, pct_b_now, price_vs_avg, ret_1m, ret_3m, rs_label,
    rs_slope_label, rsi_now, short_history, targ_w, trend, weight_gap,
) -> DecisionOutcome:
    """Select once after priority guards, then defer to existing holding policies."""
    signal_outcome = _select_core_or_technical_signal(
        core_dca_context=core_dca_context,
        core_dca_rate=core_dca_rate,
        cur_p=cur_p,
        curr_w=curr_w,
        has_pos=has_pos,
        history_days=history_days,
        is_breakout_extreme=is_breakout_extreme,
        is_breakout_normal=is_breakout_normal,
        is_core_dca_allowed=is_core_dca_allowed,
        is_etf=is_etf,
        is_etf_accumulation_ok=is_etf_accumulation_ok,
        is_stock_add_on_strength=is_stock_add_on_strength,
        mfi_now=mfi_now,
        my_price=my_price,
        pct_b_now=pct_b_now,
        price_vs_avg=price_vs_avg,
        rsi_now=rsi_now,
        short_history=short_history,
        targ_w=targ_w,
        trend=trend,
        weight_gap=weight_gap,
    )
    if signal_outcome is not None:
        return signal_outcome
    if has_pos and my_price > 0 and cur_p > my_price * 1.02:
        # 최종승인자가 막는 이유를 구체적으로 표시

        # 케이스 1: 비중이 꽉 참
        return select_profitable_holding_decision(
            _fmr=_fmr,
            curr_w=curr_w,
            fin_score=fin_score,
            grade=grade,
            mfi_now=mfi_now,
            pct_b_now=pct_b_now,
            rs_label=rs_label,
            rs_slope_label=rs_slope_label,
            rsi_now=rsi_now,
            targ_w=targ_w,
            trend=trend,
            weight_gap=weight_gap,
        )
    elif has_pos:
        return select_holding_decision(
            _fmr=_fmr,
            adj_tech_score=adj_tech_score,
            cur_p=cur_p,
            curr_w=curr_w,
            current_dd=current_dd,
            day_ret=day_ret,
            day_ret_label=day_ret_label,
            fin_score=fin_score,
            is_concentrated_upper_wait=is_concentrated_upper_wait,
            is_core_etf=is_core_etf,
            is_holding_upper_pullback_wait=is_holding_upper_pullback_wait,
            is_tdf_or_fund=is_tdf_or_fund,
            live_ref_ret=live_ref_ret,
            ma20_now=ma20_now,
            ma5_now=ma5_now,
            mfi_now=mfi_now,
            my_price=my_price,
            pct_b_now=pct_b_now,
            price_vs_avg=price_vs_avg,
            rs_label=rs_label,
            rsi_now=rsi_now,
            targ_w=targ_w,
            trend=trend,
            weight_gap=weight_gap,
        )
    else:
        return select_new_entry_decision(
            _fmr=_fmr,
            adj_tech_score=adj_tech_score,
            cur_p=cur_p,
            current_dd=current_dd,
            fin_score=fin_score,
            grade=grade,
            is_52w_breakout=is_52w_breakout,
            is_clean_leader_entry=is_clean_leader_entry,
            is_concentrated_upper_wait=is_concentrated_upper_wait,
            is_early_entry=is_early_entry,
            is_quality_recovery_candidate=is_quality_recovery_candidate,
            is_quality_recovery_scout=is_quality_recovery_scout,
            is_quality_recovery_watch=is_quality_recovery_watch,
            ma20_now=ma20_now,
            mfi_now=mfi_now,
            pct_b_now=pct_b_now,
            ret_1m=ret_1m,
            ret_3m=ret_3m,
            rs_label=rs_label,
            rsi_now=rsi_now,
            trend=trend,
        )
