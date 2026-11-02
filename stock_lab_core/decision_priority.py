"""Personal-mode priority selection; no price, UI or persistence operations."""

from stock_lab_core.decision_engine import DecisionOutcome, build_leveraged_dca_outcome
from stock_lab_core.decision_policies import _set_decision, select_portfolio_guard_decision
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _select_leverage_and_core_priority(
    *,
    core_dca_context,
    current_dd,
    is_core_dca_allowed,
    is_leveraged_daily_drop,
    is_leveraged_dca_conditional,
    is_leveraged_dca_wait_high,
    is_leveraged_or_inverse,
    leveraged_drop_ret,
    pct_b_now,
    price_vs_avg,
    short_history,
    targ_w,
    weight_gap,
) -> DecisionOutcome | None:
    if is_leveraged_daily_drop:
        dec, col, decision_outcome = _set_decision(
            "⚡레버리지 급락: 추매금지/종가 확인", "#dc2626", "LEVERAGED_DAILY_DROP_NO_ADD",
            reasons=(
                f"위험 기준 등락 {leveraged_drop_ret*100:.1f}% 급락",
                "레버리지/인버스 상품은 큰 하루 급락 뒤 반등 실패 시 손실 속도가 빨라 추가매수보다 종가·기초지수 회복 확인이 우선",
            ),
        )
    elif is_leveraged_dca_wait_high:
        decision_outcome = build_leveraged_dca_outcome(
            wait_high=True,
            target_weight=targ_w,
            weight_gap=weight_gap,
            current_dd=current_dd,
            price_vs_avg=price_vs_avg,
            pct_b_now=pct_b_now,
        )
        dec, col = decision_outcome.label, decision_outcome.color
    elif is_leveraged_dca_conditional:
        decision_outcome = build_leveraged_dca_outcome(
            wait_high=False,
            target_weight=targ_w,
            weight_gap=weight_gap,
            current_dd=current_dd,
            price_vs_avg=price_vs_avg,
            pct_b_now=pct_b_now,
        )
        dec, col = decision_outcome.label, decision_outcome.color
    elif is_core_dca_allowed and current_dd <= -0.5:
        dec, col, decision_outcome = _set_decision(
            "💣코어 패닉(-50%↓): 최종투입", "#7f1d1d", "PANIC_FINAL_DEPLOY",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (코어 ETF 패닉 최심 구간)",
                f"예비 현금 최종투입 — {core_dca_context['core_dca_label']} 기준으로 분할 매수 완료 단계",
                "이 규칙은 목표비중이 부족한 코어 ETF에만 적용합니다.",
            ),
        )
    elif is_core_dca_allowed and current_dd <= -0.4:
        dec, col, decision_outcome = _set_decision(
            "💣코어 패닉(-40%↓): 현금 투입", "#991b1b", "PANIC_CASH_DEPLOY",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (코어 ETF 패닉 구간)",
                f"현금 비중 투입 타이밍 — {core_dca_context['core_dca_label']} 기준 분할 매수 2~3회차",
                "이 규칙은 목표비중이 부족한 코어 ETF에만 적용합니다.",
            ),
        )
    elif is_core_dca_allowed and current_dd <= -0.3:
        prefix = "🧱신규 코어 ETF" if short_history else "🧱코어"
        dec, col, decision_outcome = _set_decision(
            f"{prefix} 폭락: {core_dca_context['core_dca_label']}", "#b91c1c", "CORE_CRASH_DCA",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 폭락 (코어 DCA 구간)",
                f"코어 ETF 폭락 매수 타이밍 — {core_dca_context['core_dca_label']} 적립",
            ),
        )
    elif is_leveraged_or_inverse and current_dd <= -0.5:
        dec, col, decision_outcome = _set_decision(
            "⚡레버리지 패닉권: DCA 보류", "#d97706", "LEVERAGED_RECOVERY_DCA_BLOCK",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락",
                "레버리지 ETF는 -50% 패닉권이어도 최종투입 대상이 아니라 MA50·기초축·회복 체크 확인 전 DCA를 보류합니다.",
            ),
        )
    elif is_leveraged_or_inverse and current_dd <= -0.3:
        dec, col, decision_outcome = _set_decision(
            "⚡레버리지 급락권: 회복조건 확인", "#d97706", "LEVERAGED_RECOVERY_DCA_BLOCK",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락",
                "레버리지 ETF는 가격 하락률만 보고 현금 투입하지 않고 기초지수 동행, MA20/MA50, 회차 규칙을 먼저 확인합니다.",
            ),
        )
    else:
        return None
    return decision_outcome


def _select_recovery_and_drawdown_priority(
    *,
    core_dca_context,
    current_dd,
    fin_score,
    is_core_dca_allowed,
    is_etf,
    is_quality_recovery_candidate,
    is_quality_recovery_scout,
    is_quality_recovery_watch,
    ret_1m,
    rs_label,
    short_history,
    trend,
) -> DecisionOutcome | None:
    if is_quality_recovery_candidate:
        dec, col, decision_outcome = _set_decision(
            "✅우량주 회복 후보: 분할 검토", "#22c55e", "QUALITY_RECOVERY_CANDIDATE",
            reasons=(
                f"재무점수 {fin_score}점 / 고점대비 {current_dd*100:.1f}% / 1M {ret_1m*100:.1f}%",
                f"MA20·MA50 회복 + RS {rs_label} + MACD 회복 — 정배열 복귀 전 회복 후보",
                "풀진입보다 1차 정찰 후 저점상향·MA50 지지 확인",
            ),
        )
    elif is_quality_recovery_scout:
        dec, col, decision_outcome = _set_decision(
            "🟢우량주 회복초입: 1차 정찰", "#16a34a", "QUALITY_RECOVERY_SCOUT",
            reasons=(
                f"재무점수 {fin_score}점 / 추세 {trend} / 고점대비 {current_dd*100:.1f}%",
                f"MA20·MA50 회복 시도 + RS/MACD 회복 조짐",
                "신저점 매수가 아니라 회복 초입 확인용 소액 정찰 구간",
            ),
        )
    elif is_quality_recovery_watch:
        dec, col, decision_outcome = _set_decision(
            "🔎우량주 회복관찰: 바닥 확인", "#38bdf8", "QUALITY_RECOVERY_WATCH",
            reasons=(
                f"재무점수 {fin_score}점 / 추세 {trend} / 고점대비 {current_dd*100:.1f}%",
                "MA20 회복과 RS/MACD 개선 조짐은 있지만 MA50·저점상향 확인 전",
                "매수 신호가 아니라 전광판 관심등록 후 회복 지속성 관찰",
            ),
        )
    elif current_dd <= -0.5:
        panic_label = "🚫비코어 ETF 패닉: 원인점검" if is_etf else "🚫개별주 패닉: 원인점검"
        panic_code = "NON_CORE_ETF_PANIC_CAUSE_CHECK" if is_etf else "STOCK_PANIC_CAUSE_CHECK"
        dec, col, decision_outcome = _set_decision(
            panic_label, "#dc2626", panic_code,
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (패닉 최심 구간)",
                "예비 현금 최종투입은 목표비중이 부족한 코어 ETF 전용 규칙입니다.",
                "개별주/비코어 상품은 재무·뉴스·섹터 수급·일봉/주봉 회복 확인 전 신규/추매를 보류합니다.",
            ),
        )
    elif current_dd <= -0.4:
        panic_label = "🚫비코어 ETF 급락: 원인점검" if is_etf else "🚫개별주 급락: 원인점검"
        panic_code = "NON_CORE_ETF_DRAWDOWN_CAUSE_CHECK" if is_etf else "STOCK_DRAWDOWN_CAUSE_CHECK"
        dec, col, decision_outcome = _set_decision(
            panic_label, "#d97706", panic_code,
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (급락 구간)",
                "코어 ETF가 아니므로 현금 투입 문구를 쓰지 않고 하락 원인과 회복 조건을 먼저 확인합니다.",
            ),
        )
    elif current_dd <= -0.3:
        panic_label = "🚫비코어 ETF 위기: 원인점검" if is_etf else "🚫개별주 위기: 원인점검"
        panic_code = "NON_CORE_ETF_CRISIS_CAUSE_CHECK" if is_etf else "STOCK_CRISIS_CAUSE_CHECK"
        dec, col, decision_outcome = _set_decision(
            panic_label, "#b91c1c", panic_code,
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (위기 구간)",
                "코어 ETF 중심 분할매수 규칙을 개별주/비코어 상품에 적용하지 않습니다.",
            ),
        )
    elif is_core_dca_allowed and current_dd <= -0.2:
        prefix = "🧱신규 코어 ETF" if short_history else "🧱코어"
        dec, col, decision_outcome = _set_decision(
            f"{prefix} 하락: {core_dca_context['core_dca_label']}", "#16a34a", "CORE_DRAWDOWN_DCA",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (코어 DCA 구간)",
                f"코어 하락 매수 타이밍 — {core_dca_context['core_dca_label']} 적립",
            ),
        )
    else:
        return None
    return decision_outcome


def _select_structure_and_exception_priority(
    *,
    _entry_risk_code,
    _entry_risk_label,
    _holding_risk_code,
    _holding_risk_label,
    _sd_reasons_t,
    _single_day_only_entry_risk,
    cur_p,
    curr_w,
    current_dd,
    day_ret,
    has_pos,
    is_exception_entry,
    is_live_gap_shock,
    is_structure_damage_entry_risk,
    live_gap_move,
    live_price_used,
    live_rebound_holding_label,
    live_rebound_holding_note,
    live_rebound_label,
    live_rebound_note,
    mfi_now,
    my_price,
    rsi_now,
    targ_w,
) -> DecisionOutcome | None:
    if is_live_gap_shock and not has_pos:
        dec, col, decision_outcome = _set_decision(
            "⚠️실시간 급락: 정규장 확인대기", "#d97706", "LIVE_GAP_SHOCK_WAIT",
            reasons=(
                f"현재/전거래일 대비 {live_gap_move*100:.1f}% (프리/실시간 가격 반영)",
                "정규장 종가와 거래량 확정 전 — 신규진입은 보류하고 MA5/FVG 지지 확인",
            ),
        )
    elif is_structure_damage_entry_risk and not has_pos:
        dec, col, decision_outcome = _set_decision(
            _entry_risk_label, "#d97706", _entry_risk_code,
            reasons=_sd_reasons_t,
        )
    elif current_dd <= -0.2 and has_pos and is_structure_damage_entry_risk and not _single_day_only_entry_risk:
        dec, col, decision_outcome = _set_decision(
            "⚠️고점대비 -20%: 추매금지/손절기준 점검", "#d97706", "DRAWDOWN_20_HOLDING_STOP_CHECK",
            reasons=(f"고점대비 {current_dd*100:.1f}% 하락",) + _sd_reasons_t,
        )
    elif current_dd <= -0.2 and has_pos:
        dec, col, decision_outcome = _set_decision(
            "⚠️고점대비 -20%: 추매금지/원인점검", "#d97706", "DRAWDOWN_20_HOLDING_CAUSE_CHECK",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (기준: -20%)",
                "추세훼손 신호 없음 — 하락 원인(매크로/실적) 점검 후 판단",
            ),
        )
    elif current_dd <= -0.2:
        dec, col, decision_outcome = _set_decision(
            "⚠️고점대비 -20%: 신규진입 보류", "#d97706", "DRAWDOWN_20_NO_ENTRY",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락 (기준: -20%)",
                "미보유 종목 — 하락 안정 확인 후 재검토",
            ),
        )


    elif is_live_gap_shock and has_pos:
        dec, col, decision_outcome = _set_decision(
            "⚠️실시간 급락: 추매금지/정규장 확인", "#d97706", "LIVE_GAP_SHOCK_HOLDING_CHECK",
            reasons=(
                f"현재/전거래일 대비 {live_gap_move*100:.1f}% (프리/실시간 가격 반영)",
                "정규장 종가와 거래량 확정 전 — 추매 금지, 손절선/MA5/FVG 지지 확인",
            ),
        )
    elif is_structure_damage_entry_risk and has_pos:
        dec, col, decision_outcome = _set_decision(
            _holding_risk_label, "#d97706", _holding_risk_code,
            reasons=_sd_reasons_t,
        )
    elif is_live_gap_shock:
        dec, col, decision_outcome = _set_decision(
            "⚠️실시간 급락: 정규장 확인대기", "#d97706", "LIVE_GAP_SHOCK_WAIT",
            reasons=(
                f"현재/전거래일 대비 {live_gap_move*100:.1f}% (프리/실시간 가격 반영)",
                "정규장 종가와 거래량 확정 전 — 신규/추매 보류",
            ),
        )
    elif is_structure_damage_entry_risk:
        dec, col, decision_outcome = _set_decision(
            _entry_risk_label, "#d97706", _entry_risk_code,
            reasons=_sd_reasons_t,
        )
    elif live_price_used and is_exception_entry and has_pos:
        dec, col, decision_outcome = _set_decision(
            live_rebound_holding_label, "#d97706", "PREMARKET_REBOUND_HOLDING_WAIT",
            reasons=(
                f"실시간등락 {day_ret*100:.1f}% / MA5·FVG 구간 반등",
                live_rebound_holding_note,
            ),
        )
    elif live_price_used and is_exception_entry:
        dec, col, decision_outcome = _set_decision(
            live_rebound_label, "#d97706", "PREMARKET_REBOUND_WAIT",
            reasons=(
                f"실시간등락 {day_ret*100:.1f}% / MA5·FVG 구간 반등",
                live_rebound_note,
            ),
        )
    elif (
        is_exception_entry and
        has_pos and
        my_price > 0 and
        cur_p <= my_price * 1.02 and
        targ_w > 0 and
        curr_w < targ_w
    ):
        dec, col, decision_outcome = _set_decision(
            "🟣예외승인: 정찰대 추매(MA5/FVG)", "#7c3aed", "EXCEPTION_ADD_ON",
            reasons=(
                f"MA5 눌림 또는 FVG 구간 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                f"예외 승인 — 정찰대 추매 조건 충족 (평단 {my_price:,.0f}원 근처)",
            ),
        )
    elif is_exception_entry and (not has_pos):
        dec, col, decision_outcome = _set_decision(
            "🟣예외승인: 정찰대 진입(MA5/FVG)", "#7c3aed", "EXCEPTION_ENTRY",
            reasons=(
                f"MA5 눌림 또는 FVG 구간 / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                "예외 승인 — 정찰대 신규 진입 조건 충족",
            ),
        )
    else:
        return None
    return decision_outcome


def select_portfolio_priority_decision(
    *,
    _entry_risk_code,
    _entry_risk_label,
    _fmr,
    _holding_risk_code,
    _holding_risk_label,
    _sd_reasons_t,
    _single_day_only_entry_risk,
    core_dca_context,
    core_dca_rate,
    cur_p,
    curr_w,
    current_dd,
    day_ret,
    fin_score,
    has_pos,
    is_core_dca_allowed,
    is_etf,
    is_exception_entry,
    is_leveraged_daily_drop,
    is_leveraged_dca_conditional,
    is_leveraged_dca_wait_high,
    is_leveraged_or_inverse,
    is_live_gap_shock,
    is_quality_recovery_candidate,
    is_quality_recovery_scout,
    is_quality_recovery_watch,
    is_structure_damage_entry_risk,
    is_zero_target_holding,
    leveraged_drop_ret,
    live_gap_move,
    live_price_used,
    live_rebound_holding_label,
    live_rebound_holding_note,
    live_rebound_label,
    live_rebound_note,
    mfi_now,
    my_price,
    pct_b_now,
    price_vs_avg,
    ret_1m,
    rs_label,
    rsi_now,
    short_history,
    targ_w,
    trend,
    weight_gap,
) -> DecisionOutcome | None:
    """Return the first matching priority outcome, or defer to normal entry rules."""
    guard_outcome = select_portfolio_guard_decision(
        _fmr=_fmr,
        core_dca_context=core_dca_context,
        core_dca_rate=core_dca_rate,
        curr_w=curr_w,
        fin_score=fin_score,
        is_core_dca_allowed=is_core_dca_allowed,
        is_etf=is_etf,
        is_zero_target_holding=is_zero_target_holding,
        short_history=short_history,
        targ_w=targ_w,
    )
    if guard_outcome is not None:
        decision_outcome = guard_outcome
        dec, col = decision_outcome.label, decision_outcome.color
        return decision_outcome

    # Keep short-circuit priority: later stages run only after no match.
    decision_outcome = _select_leverage_and_core_priority(
        core_dca_context=core_dca_context,
        current_dd=current_dd,
        is_core_dca_allowed=is_core_dca_allowed,
        is_leveraged_daily_drop=is_leveraged_daily_drop,
        is_leveraged_dca_conditional=is_leveraged_dca_conditional,
        is_leveraged_dca_wait_high=is_leveraged_dca_wait_high,
        is_leveraged_or_inverse=is_leveraged_or_inverse,
        leveraged_drop_ret=leveraged_drop_ret,
        pct_b_now=pct_b_now,
        price_vs_avg=price_vs_avg,
        short_history=short_history,
        targ_w=targ_w,
        weight_gap=weight_gap,
    )
    if decision_outcome is not None:
        return decision_outcome
    decision_outcome = _select_recovery_and_drawdown_priority(
        core_dca_context=core_dca_context,
        current_dd=current_dd,
        fin_score=fin_score,
        is_core_dca_allowed=is_core_dca_allowed,
        is_etf=is_etf,
        is_quality_recovery_candidate=is_quality_recovery_candidate,
        is_quality_recovery_scout=is_quality_recovery_scout,
        is_quality_recovery_watch=is_quality_recovery_watch,
        ret_1m=ret_1m,
        rs_label=rs_label,
        short_history=short_history,
        trend=trend,
    )
    if decision_outcome is not None:
        return decision_outcome
    decision_outcome = _select_structure_and_exception_priority(
        _entry_risk_code=_entry_risk_code,
        _entry_risk_label=_entry_risk_label,
        _holding_risk_code=_holding_risk_code,
        _holding_risk_label=_holding_risk_label,
        _sd_reasons_t=_sd_reasons_t,
        _single_day_only_entry_risk=_single_day_only_entry_risk,
        cur_p=cur_p,
        curr_w=curr_w,
        current_dd=current_dd,
        day_ret=day_ret,
        has_pos=has_pos,
        is_exception_entry=is_exception_entry,
        is_live_gap_shock=is_live_gap_shock,
        is_structure_damage_entry_risk=is_structure_damage_entry_risk,
        live_gap_move=live_gap_move,
        live_price_used=live_price_used,
        live_rebound_holding_label=live_rebound_holding_label,
        live_rebound_holding_note=live_rebound_holding_note,
        live_rebound_label=live_rebound_label,
        live_rebound_note=live_rebound_note,
        mfi_now=mfi_now,
        my_price=my_price,
        rsi_now=rsi_now,
        targ_w=targ_w,
    )
    if decision_outcome is not None:
        return decision_outcome
    return None
