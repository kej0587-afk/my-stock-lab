"""Pure policy selection, preserving the original condition order and wording."""

from stock_lab_core.decision_engine import (
    DecisionOutcome,
    build_core_dca_outcome,
    build_decision_outcome,
    build_leveraged_dca_outcome,
    build_limited_history_etf_outcome,
)
from stock_lab_core.formatters import finite_num


def _set_decision(label, color, code=None, reasons=()):
    outcome = build_decision_outcome(label, color, code, reasons=reasons)
    return outcome.label, outcome.color, outcome


def select_free_mode_decision(
    *,
    _entry_risk_code,
    _entry_risk_label,
    _sd_reasons_t,
    adj_tech_score,
    core_dca_context,
    core_dca_rate,
    cur_p,
    curr_w,
    current_dd,
    fin_score,
    has_pos,
    history_days,
    is_52w_breakout,
    is_breakout_extreme,
    is_breakout_normal,
    is_capitulation_selloff,
    is_clean_leader_entry,
    is_core_dca_allowed,
    is_early_entry,
    is_etf,
    is_leveraged_daily_drop,
    is_leveraged_dca_conditional,
    is_leveraged_dca_wait_high,
    is_live_gap_shock,
    is_quality_recovery_candidate,
    is_quality_recovery_scout,
    is_quality_recovery_watch,
    is_structure_damage_entry_risk,
    leveraged_drop_ret,
    live_gap_move,
    mfi_now,
    my_price,
    pct_b_now,
    price_vs_avg,
    ret_1m,
    ret_3m,
    rs_label,
    rsi_now,
    short_history,
    targ_w,
    trend,
    weight_gap,
) -> DecisionOutcome:
    if is_core_dca_allowed:
        dca_label = core_dca_context["core_dca_label"]
        prefix = "🧱신규 코어 ETF" if short_history else "🧱코어 ETF"
        decision_outcome = build_core_dca_outcome(prefix, core_dca_rate, dca_label)
        dec, col = decision_outcome.label, decision_outcome.color
    elif is_etf and short_history:
        decision_outcome = build_limited_history_etf_outcome(
            history_days, has_pos, my_price, cur_p, targ_w, curr_w, weight_gap,
            rsi_now, mfi_now, pct_b_now, price_vs_avg
        )
        dec, col = decision_outcome.label, decision_outcome.color
    elif mfi_now >= 85:
        dec, col, decision_outcome = _set_decision(
            "🚫극단과열: 추격금지", "#dc2626", "EXTREME_OVERHEAT_NO_CHASE",
            reasons=(
                f"MFI {mfi_now:.0f} (기준: 85 초과) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "극단 과열 — 추격 매수 금지, 눌림 후 재접근",
            ),
        )
    elif is_breakout_extreme:
        dec, col, decision_outcome = _set_decision(
            "⚠️과열확장: 추격금지, MA5 대기", "#d97706", "OVERHEAT_EXTENSION_WAIT_MA5",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                "과열 확장 구간 — MA5 눌림 확인 후 진입",
            ),
        )
    elif is_breakout_normal:
        dec, col, decision_outcome = _set_decision(
            "🔥불뿜는 대장주: 초단기 눌림(MA5) 진입", "#ec4899", "LEADER_MA5_FAST_PULLBACK_ENTRY",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / MFI {mfi_now:.0f}",
                "불뿜는 대장주 포착 — MA5 눌림 초단기 진입 기회",
            ),
        )
    elif pct_b_now >= 0.95:
        dec, col, decision_outcome = _set_decision(
            "⚠️밴드상단: 눌림 대기", "#d97706", "BAND_UPPER_WAIT",
            reasons=(
                f"%B {pct_b_now:.2f} (기준: 0.95 이상) / RSI {rsi_now:.0f}",
                "볼린저 밴드 상단 근접 — 눌림 대기 후 진입",
            ),
        )
    elif is_quality_recovery_candidate:
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
    elif is_capitulation_selloff:
        dec, col, decision_outcome = _set_decision(
            "🚨위기/패닉: 투매 포착", "#dc2626", "CRISIS_PANIC_SELL_OFF",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% 하락",
                "급락/투매 포착 (미보유) — 추세 회복 전까지 극단 분할매수만 검토",
            ),
        )
    elif is_live_gap_shock:
        dec, col, decision_outcome = _set_decision(
            "⚠️실시간 급락: 정규장 확인대기", "#d97706", "LIVE_GAP_SHOCK_WAIT",
            reasons=(
                f"현재/전거래일 대비 {live_gap_move*100:.1f}% (프리/실시간 가격 반영)",
                "정규장 종가와 거래량 확정 전 — 신규진입은 보류하고 MA5/FVG 지지 확인",
            ),
        )
    elif is_structure_damage_entry_risk:
        dec, col, decision_outcome = _set_decision(
            _entry_risk_label, "#d97706", _entry_risk_code,
            reasons=_sd_reasons_t,
        )
    elif is_leveraged_daily_drop:
        dec, col, decision_outcome = _set_decision(
            "⚡레버리지 급락: 신규/추매 보류", "#dc2626", "LEVERAGED_DAILY_DROP_NO_ADD",
            reasons=(
                f"위험 기준 등락 {leveraged_drop_ret*100:.1f}% 급락",
                "레버리지/인버스 상품은 하락폭이 커질 때 복리 손실이 빨라 종가와 기초지수 회복 확인 전 매수 보류",
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
    elif is_52w_breakout and mfi_now < 80 and pct_b_now < 0.95:
        dec, col, decision_outcome = _set_decision(
            "🚀52주 신고가 돌파: 모멘텀 진입 검토", "#7c3aed", "BREAKOUT_52W_ENTRY",
            reasons=(
                f"52주 신고가 돌파 / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                "모멘텀 돌파 신호 — 소액 정찰 진입 검토",
            ),
        )
    elif trend == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
        dec, col, decision_outcome = _set_decision(
            "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
            reasons=(
                f"정배열 + RS강함 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "S급 눌림목 최적 구간 — 탑승 찬스",
            ),
        )
    elif rsi_now <= 30:
        dec, col, decision_outcome = _set_decision(
            "🔥낙폭과대: 신규 진입", "#16a34a", "OVERSOLD_NEW_ENTRY",
            reasons=(
                f"RSI {rsi_now:.0f} (기준: 30 이하) / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                f"고점대비 {current_dd*100:.1f}% / 재무점수 {fin_score}점 / 추세 {trend}",
                "과매도 구간 신규 진입 — 소액 분할 매수",
            ),
        )
    elif is_early_entry:
        dec, col, decision_outcome = _set_decision(
            "🟢선진입 가능 구간", "#16a34a", "EARLY_ENTRY",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                "선진입 조건 충족 — 반전 초입 소액 진입 가능",
            ),
        )
    elif is_clean_leader_entry:
        dec, col, decision_outcome = _set_decision(
            "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
            reasons=(
                f"기술점수 {adj_tech_score:.1f} / 추세 {trend} / RS {rs_label}",
                f"고점대비 {current_dd*100:.1f}% (추세훼손 없음) / 재무점수 {fin_score}점",
                "대장주 조건 충족 — 1차 정찰 진입 가능",
            ),
        )
    elif trend == "🌊역배열(하락)" and adj_tech_score >= 5:
        dec, col, decision_outcome = _set_decision(
            "🎯낙폭과대: 분할매수", "#8b5cf6", "OVERSOLD_DCA",
            reasons=(
                f"역배열 + 기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "역배열 낙폭과대 — 소량 분할매수 검토",
            ),
        )
    elif ret_3m < 0 and trend in ["🌊역배열(하락)", "⏳혼조세"]:
        dec, col, decision_outcome = _set_decision(
            "⚠️하락추세: 진입보류", "#dc2626", "DOWNTREND_NO_ENTRY",
            reasons=(
                f"추세 {trend} / 3개월 수익률 {ret_3m*100:.1f}%",
                "하락추세 + 마이너스 수익 — 진입 보류",
            ),
        )
    elif trend == "🌊역배열(하락)":
        dec, col, decision_outcome = _set_decision(
            "🚫역배열: 진입 보류", "#dc2626", "REVERSE_TREND_NO_ENTRY",
            reasons=(
                f"추세 {trend} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "역배열 상태 — 추세 전환 확인 후 진입",
            ),
        )
    else:
        dec, col, decision_outcome = _set_decision(
            "🔍관망: 타점 대기", "#64748b", "WATCH_WAIT_ENTRY",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                "특별 진입 신호 없음 — 타점 대기",
            ),
        )
    return decision_outcome


def select_profitable_holding_decision(
    *,
    _fmr,
    curr_w,
    fin_score,
    grade,
    mfi_now,
    pct_b_now,
    rs_label,
    rs_slope_label,
    rsi_now,
    targ_w,
    trend,
    weight_gap,
) -> DecisionOutcome:
    if targ_w > 0 and curr_w >= targ_w * 0.97:
        if grade.startswith("💎") or grade.startswith("✅"):
            dec, col, decision_outcome = _set_decision(
                "⏸️S급이나 비중 충족: 눌림 오면 재진입", "#8b5cf6", "TARGET_FILLED_S_GRADE_WAIT",
                reasons=(
                    f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}% ({grade[:3]})",
                    "비중 충족 + S급 - 눌림 오면 재진입",
                ),
            )
        else:
            dec, col, decision_outcome = _set_decision(
                "⏸️비중 충족: 보유 유지", "#64748b", "TARGET_FILLED_HOLD",
                reasons=(
                    f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}%",
                    "비중 충족 - 보유 유지",
                ),
            )

    # 케이스 2: 비중 여유 있는데 과열
    elif weight_gap >= 3 and (mfi_now >= 80 or rsi_now >= 72 or pct_b_now >= 0.90):
        if grade.startswith("💎") or grade.startswith("✅"):
            dec, col, decision_outcome = _set_decision(
                "⏳S급 과열 구간: 식힌 뒤 추가", "#d97706", "S_GRADE_OVERHEAT_WAIT",
                reasons=(
                    f"MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f} ({grade[:3]} 과열)",
                    "S급이나 과열 — 식힌 뒤 추가",
                ),
            )
        else:
            dec, col, decision_outcome = _set_decision(
                "⏳과열: 눌림 대기", "#d97706", "OVERHEAT_WAIT",
                reasons=(
                    f"MFI {mfi_now:.0f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                    "과열 구간 — 눌림 대기 후 추가",
                ),
            )

    # 케이스 3: 비중 여유 있고 과열 아님 → 추가 허용 조건
    elif weight_gap >= 3 and mfi_now < 75 and rsi_now < 68 and pct_b_now < 0.88:
        if (grade.startswith("💎") and
            rs_label == "🚀강함" and
            trend == "🚀정배열(상승)" and
            fin_score >= 4 and
            (_fmr < 4.0 if rs_slope_label == "📈RS상승중" else _fmr < 3.5)):
            dec, col, decision_outcome = _set_decision(
                "✅S급 비중여유: 분할 추가 가능", "#16a34a", "S_GRADE_ADD_ON_OK",
                reasons=(
                    f"S급 / 비중여유 {weight_gap:.1f}%p / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                    "S급 비중여유 분할 추가 조건 충족",
                ),
            )
        elif grade.startswith("✅") and trend == "🚀정배열(상승)":
            dec, col, decision_outcome = _set_decision(
                "📈A급 비중여유: 소액 추가 검토", "#22c55e", "A_GRADE_ADD_ON_REVIEW",
                reasons=(
                    f"A급 정배열 / 비중여유 {weight_gap:.1f}%p / MFI {mfi_now:.0f}",
                    "A급 정배열 + 비중여유 — 소액 추가 검토",
                ),
            )
        else:
            dec, col, decision_outcome = _set_decision(
                "⏳평단이상: 추가 하락 대기", "#64748b", "ABOVE_COST_WAIT_PULLBACK",
                reasons=(
                    f"비중여유 {weight_gap:.1f}%p / MFI {mfi_now:.0f} / RSI {rsi_now:.0f}",
                    "추가 조건 미달 — 추가 하락 대기",
                ),
            )

    # 케이스 4: 그 외 모든 상황 (비중 여유 없거나 조건 미달 등)
    else:
        dec, col, decision_outcome = _set_decision(
            "⏳평단이상: 보유 유지", "#64748b", "ABOVE_COST_HOLD",
            reasons=(
                f"평단 이상 / 비중여유 {weight_gap:.1f}%p",
                "추가 조건 미달 — 보유 유지",
            ),
        )
    return decision_outcome


def select_holding_decision(
    *,
    _fmr,
    adj_tech_score,
    cur_p,
    curr_w,
    current_dd,
    day_ret,
    day_ret_label,
    fin_score,
    is_concentrated_upper_wait,
    is_core_etf,
    is_holding_upper_pullback_wait,
    is_tdf_or_fund,
    live_ref_ret,
    ma20_now,
    ma5_now,
    mfi_now,
    my_price,
    pct_b_now,
    price_vs_avg,
    rs_label,
    rsi_now,
    targ_w,
    trend,
    weight_gap,
) -> DecisionOutcome:
    if (not is_core_etf) and mfi_now >= 80 and pct_b_now > 0.9 and price_vs_avg > 0.20:
        dec, col, decision_outcome = _set_decision(
            "🔔익절 타이밍: 고평가+과열+수익20%↑ (분할 매도 검토)", "#dc2626", "PROFIT_TAKE_REVIEW",
            reasons=(
                f"MFI {mfi_now:.0f} / %B {pct_b_now:.2f} / 수익률 {price_vs_avg*100:.1f}%",
                "고평가+과열+수익 20%↑ — 분할 매도 검토",
            ),
        )
    elif trend == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
        dec, col, decision_outcome = _set_decision(
            "🎯S급 눌림목: 추매", "#8b5cf6", "S_PULLBACK_ADD_ON",
            reasons=(
                f"정배열 + RS강함 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "S급 눌림목 — 추매 타이밍",
            ),
        )
    elif mfi_now >= 80:
        dec, col, decision_outcome = _set_decision(
            "⚠️단기과열: 추매 보류", "#d97706", "SHORT_OVERHEAT_NO_ADD",
            reasons=(
                f"MFI {mfi_now:.0f} (기준: 80 이상) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "단기 과열 — 추매 보류, 눌림 대기",
            ),
        )
    elif rsi_now <= 30:
        if is_tdf_or_fund:
            dec, col, decision_outcome = _set_decision(
                "⏳TDF/펀드 낙폭과대: 소액 리밸런싱 검토", "#d97706", "FUND_OVERSOLD_REBALANCE_REVIEW",
                reasons=(
                    f"RSI {rsi_now:.0f} (기준: 30 이하) / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                    f"고점대비 {current_dd*100:.1f}% / 비중차이 {weight_gap:.1f}%p",
                    "TDF/펀드형 상품 — 줍줍 신호가 아니라 정해둔 목표비중 안에서 소액 리밸런싱만 검토",
                ),
            )
        else:
            dec, col, decision_outcome = _set_decision(
                "🔥낙폭과대: 줍줍 찬스", "#16a34a", "OVERSOLD_ADD_ON",
                reasons=(
                    f"RSI {rsi_now:.0f} (기준: 30 이하) / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                    f"고점대비 {current_dd*100:.1f}% / 재무점수 {fin_score}점",
                    "과매도 구간 — 분할 추가 매수 기회",
                ),
            )
    elif rs_label == "🚀강함" and mfi_now < 35:
        dec, col, decision_outcome = _set_decision(
            "💎S급 과매도: 강한 분할추매", "#16a34a", "S_GRADE_OVERSOLD_BUY",
            reasons=(
                f"RS강함 / MFI {mfi_now:.0f} (기준: 35 이하) / RSI {rsi_now:.0f}",
                "S급 과매도 — 강한 분할추매 후보",
            ),
        )
    elif is_holding_upper_pullback_wait:
        dec, col, decision_outcome = _set_decision(
            "🟡보유주 단기하락: 추매는 종가 확인", "#d97706", "HOLDING_PULLBACK_WAIT_CLOSE",
            reasons=(
                f"{day_ret_label} {day_ret*100:.1f}% / 최신가-종가 {live_ref_ret*100:.1f}%" if finite_num(live_ref_ret) else f"{day_ret_label} {day_ret*100:.1f}%",
                f"MA5 대비 {(cur_p/ma5_now-1)*100:.1f}% / %B {pct_b_now:.2f} / 고점대비 {current_dd*100:.1f}%",
                "추세와 RS는 강하지만 상단권에서 단기 하락 중이라 기술적 반등 확정보다 종가·MA5 회복 확인이 우선",
            ),
        )
    elif is_concentrated_upper_wait and adj_tech_score >= 4 and cur_p <= my_price:
        dec, col, decision_outcome = _set_decision(
            "🟡집중 ETF 상단권: 눌림대기", "#d97706", "CONCENTRATED_ETF_UPPER_WAIT",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                f"MA20 대비 {(cur_p/ma20_now-1)*100:.1f}%" if ma20_now > 0 else "MA20 기준 확인 불가",
                "품질·기술점수는 양호하지만 집중 ETF가 상단권이라 A급 반등 매수보다 눌림·재돌파 확인이 우선",
            ),
        )
    elif adj_tech_score >= 4 and cur_p <= my_price:
        dec, col, decision_outcome = _set_decision(
            "🎯A급: 기술적 반등", "#16a34a", "A_GRADE_TECH_REBOUND",
            reasons=(
                f"기술점수 {adj_tech_score:.1f} / 추세 {trend} / 평단이하",
                "A급 기술적 반등 신호 — 분할매수",
            ),
        )
    elif (trend == "🚀정배열(상승)" and pct_b_now < 0.8 and rsi_now < 60 and price_vs_avg <= -0.03 and price_vs_avg > -0.15 and curr_w < targ_w):
        dec, col, decision_outcome = _set_decision(
            "📈정배열: -3% 이상 눌림 분할매수", "#16a34a", "UPTREND_PULLBACK_DCA",
            reasons=(
                f"정배열 / %B {pct_b_now:.2f} / 평단대비 {price_vs_avg*100:.1f}%",
                "정배열 눌림 분할매수 조건 충족",
            ),
        )
    elif cur_p > my_price:
        dec, col, decision_outcome = _set_decision(
            "⏳평단이상: 하락대기(보유)", "#d97706", "ABOVE_COST_WAIT",
            reasons=(
                f"평단대비 +{price_vs_avg*100:.1f}% / MFI {mfi_now:.0f}",
                "평단 이상 — 추가 하락 대기 후 매수",
            ),
        )
    elif cur_p <= my_price:
        if curr_w >= targ_w and targ_w > 0:
            dec, col, decision_outcome = _set_decision(
                "⏸️평단이하: 비중 충족(추매 보류)", "#d97706", "BELOW_COST_TARGET_FILLED",
                reasons=(
                    f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}%",
                    "평단이하지만 비중 충족 - 추매 보류",
                ),
            )
        elif price_vs_avg > -0.03:
            dec, col, decision_outcome = _set_decision(
                "⏳평단근처: 추가 하락 대기", "#64748b", "NEAR_COST_WAIT",
                reasons=(
                    f"평단대비 {price_vs_avg*100:.1f}% (기준: -3% 미만)",
                    "평단 근처 — 추가 하락 대기",
                ),
            )
        elif price_vs_avg >= -0.07 and trend != "🌊역배열(하락)" and mfi_now < 80:
            dec, col, decision_outcome = _set_decision(
                "✅평단 -3~-7%: 소액 분할매수", "#16a34a", "COST_MINUS_3_7_DCA",
                reasons=(
                    f"평단대비 {price_vs_avg*100:.1f}% / 추세 {trend} / MFI {mfi_now:.0f}",
                    "평단 -3~7% 구간 소액 분할매수 조건 충족",
                ),
            )
        elif price_vs_avg >= -0.15 and fin_score >= 3 and _fmr < 4.5:
            dec, col, decision_outcome = _set_decision(
                "🎯평단 -7~-15%: 조건부 분할매수", "#8b5cf6", "COST_MINUS_7_15_CONDITIONAL_DCA",
                reasons=(
                    f"평단대비 {price_vs_avg*100:.1f}% / 재무점수 {fin_score}점 / FMR {_fmr:.1f}",
                    "평단 -7~15% 조건부 분할매수 조건 충족",
                ),
            )
        else:
            is_cost_deep_loss = price_vs_avg <= -0.15
            is_reverse_trend_loss = trend == "🌊역배열(하락)"
            if is_cost_deep_loss and is_reverse_trend_loss:
                hold_label = "🚫평단 -15%↓+추세위험: 원인 점검"
                hold_code = "COST_MINUS_15_TREND_RISK"
                hold_reason = "평단 -15% 이하와 하락추세 동시 발생 — 원인 점검 필요"
            elif is_cost_deep_loss:
                hold_label = "🚫평단 -15%↓: 원인 점검"
                hold_code = "COST_MINUS_15_CAUSE_CHECK"
                hold_reason = "평단 -15% 이하 — 손실 원인 점검 필요"
            elif is_reverse_trend_loss:
                hold_label = "🚫추세위험: 원인 점검"
                hold_code = "TREND_RISK_CAUSE_CHECK"
                hold_reason = "평단 손실은 -15% 이내지만 하락추세라 추매보다 회복 확인 우선"
            else:
                hold_label = "⏸️조건미달: 추매 보류"
                hold_code = "HOLDING_DCA_CONDITION_MISS"
                hold_color = "#d97706"
                hold_reason = "평단 손실은 -15% 이내지만 재무·매크로·ETF 검증 조건이 부족해 추매 보류"
            if hold_code != "HOLDING_DCA_CONDITION_MISS":
                hold_color = "#dc2626"
            dec, col, decision_outcome = _set_decision(
                hold_label, hold_color, hold_code,
                reasons=(
                    f"평단대비 {price_vs_avg*100:.1f}% / 추세 {trend} / 재무점수 {fin_score}점",
                    hold_reason,
                ),
            )
    else:
        dec, col, decision_outcome = _set_decision(
            "⏳보유중(신호대기)", "#64748b", "HOLD_WAIT_SIGNAL",
            reasons=(
                f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                "보유 중 — 매수 신호 대기",
            ),
        )
    return decision_outcome


def select_new_entry_decision(
    *,
    _fmr,
    adj_tech_score,
    cur_p,
    current_dd,
    fin_score,
    grade,
    is_52w_breakout,
    is_clean_leader_entry,
    is_concentrated_upper_wait,
    is_early_entry,
    is_quality_recovery_candidate,
    is_quality_recovery_scout,
    is_quality_recovery_watch,
    ma20_now,
    mfi_now,
    pct_b_now,
    ret_1m,
    ret_3m,
    rs_label,
    rsi_now,
    trend,
) -> DecisionOutcome:
    if is_concentrated_upper_wait:
        dec, col, decision_outcome = _set_decision(
            "🟡집중 ETF 상단권: 눌림대기", "#d97706", "CONCENTRATED_ETF_UPPER_WAIT",
            reasons=(
                f"고점대비 {current_dd*100:.1f}% / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                f"MA20 대비 {(cur_p/ma20_now-1)*100:.1f}%" if ma20_now > 0 else "MA20 기준 확인 불가",
                "집중 ETF가 상단권이라 신규 진입은 돌파 유지나 MA5/FVG 눌림 확인 후 소액 정찰",
            ),
        )
    elif 0.85 <= pct_b_now < 0.95:
        dec, col, decision_outcome = _set_decision(
            "⚠️상단부근: 눌림 대기", "#d97706", "NEAR_UPPER_WAIT",
            reasons=(
                f"%B {pct_b_now:.2f} (기준: 0.85~0.95) / RSI {rsi_now:.0f}",
                "밴드 상단 근처 — 눌림 대기 후 진입",
            ),
        )
    elif is_52w_breakout and mfi_now < 80 and pct_b_now < 0.95:
        dec, col, decision_outcome = _set_decision(
            "🚀52주 신고가 돌파: 모멘텀 진입 검토", "#7c3aed", "BREAKOUT_52W_ENTRY",
            reasons=(
                f"52주 신고가 돌파 / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                "모멘텀 돌파 신호 — 소액 정찰 진입 검토",
            ),
        )
    elif trend == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
        dec, col, decision_outcome = _set_decision(
            "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
            reasons=(
                f"정배열 + RS강함 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "S급 눌림목 최적 구간 — 탑승 찬스",
            ),
        )
    elif mfi_now >= 80:
        dec, col, decision_outcome = _set_decision(
            "⚠️단기과열: 진입 보류", "#d97706", "SHORT_OVERHEAT_NO_ENTRY",
            reasons=(
                f"MFI {mfi_now:.0f} (기준: 80 이상) / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "단기 과열 — 신규 진입 보류, 눌림 대기",
            ),
        )
    elif is_quality_recovery_candidate:
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
    elif rsi_now <= 30:
        dec, col, decision_outcome = _set_decision(
            "🔥낙폭과대: 신규 진입", "#16a34a", "OVERSOLD_NEW_ENTRY",
            reasons=(
                f"RSI {rsi_now:.0f} (기준: 30 이하) / MFI {mfi_now:.0f} / %B {pct_b_now:.2f}",
                f"고점대비 {current_dd*100:.1f}% / 재무점수 {fin_score}점 / 추세 {trend}",
                "과매도 구간 신규 진입 — 소액 분할매수",
            ),
        )
    elif is_early_entry:
        dec, col, decision_outcome = _set_decision(
            "🟢선진입 가능: 반전 초입", "#16a34a", "EARLY_REVERSAL_ENTRY",
            reasons=(
                f"RSI {rsi_now:.0f} / 추세 {trend}",
                "반전 초입 신호 — 소액 선진입 가능",
            ),
        )
    elif is_clean_leader_entry:
        dec, col, decision_outcome = _set_decision(
            "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
            reasons=(
                f"기술점수 {adj_tech_score:.1f} / 추세 {trend} / RS {rs_label}",
                f"고점대비 {current_dd*100:.1f}% (추세훼손 없음) / 재무점수 {fin_score}점",
                "대장주 조건 충족 — 1차 정찰 진입 가능",
            ),
        )
    elif trend == "🌊역배열(하락)" and adj_tech_score >= 5:
        dec, col, decision_outcome = _set_decision(
            "🎯낙폭과대: 분할매수", "#8b5cf6", "OVERSOLD_DCA",
            reasons=(
                f"역배열 + 기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "역배열 낙폭과대 — 소량 분할매수 검토",
            ),
        )
    elif ret_3m < 0 and trend in ["🌊역배열(하락)", "⏳혼조세"]:
        dec, col, decision_outcome = _set_decision(
            "⚠️하락추세: 진입보류", "#dc2626", "DOWNTREND_NO_ENTRY",
            reasons=(
                f"추세 {trend} / 3개월 수익률 {ret_3m*100:.1f}%",
                "하락추세 + 마이너스 수익 — 진입 보류",
            ),
        )
    elif trend == "🌊역배열(하락)":
        dec, col, decision_outcome = _set_decision(
            "🚫진입보류: 역배열 대기", "#dc2626", "REVERSE_TREND_NO_ENTRY",
            reasons=(
                f"추세 {trend} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                "역배열 상태 — 추세 전환 확인 후 진입",
            ),
        )
    else:
        # 상승 추세에서 중립 구간 진입 신호
        if (
            trend == "🚀정배열(상승)" and
            rs_label == "🚀강함" and
            45 <= rsi_now <= 65 and
            0.35 <= pct_b_now <= 0.75 and
            mfi_now < 75 and
            _fmr < 3.5
        ):
            if fin_score >= 4:
                dec, col, decision_outcome = _set_decision(
                    "🎯우량주 눌림 구간: 정찰 진입 적합", "#8b5cf6", "QUALITY_PULLBACK_ENTRY",
                    reasons=(
                        f"재무점수 {fin_score}점 / 기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f}",
                        f"정배열 + RS강함 + %B {pct_b_now:.2f} — 우량주 눌림 정찰 진입 적합",
                    ),
                )
            else:
                dec, col, decision_outcome = _set_decision(
                    "📈추세 눌림 구간: 소액 탐색 가능", "#3b82f6", "TREND_PULLBACK_EXPLORE",
                    reasons=(
                        f"기술점수 {adj_tech_score:.1f} / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        f"정배열 + RS강함 — 추세 눌림 소액 탐색 (재무점수 {fin_score}점)",
                    ),
                )

        elif (
            trend == "🚀정배열(상승)" and
            rs_label == "➖보통" and
            rsi_now < 55 and pct_b_now < 0.65
        ):
            dec, col, decision_outcome = _set_decision(
                "🔍정배열 눌림: 신호 확인 후 접근", "#64748b", "UPTREND_PULLBACK_CONFIRM",
                reasons=(
                    f"정배열 + RS보통 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                    "정배열 눌림이나 RS 보통 — 추가 신호 확인 후 접근",
                ),
            )

        else:
            if grade.startswith("💎") and trend == "🚀정배열(상승)":
                dec, col, decision_outcome = _set_decision(
                    "🔍S급 정배열: 눌림 구간 진입 대기", "#8b5cf6", "S_UPTREND_WAIT_PULLBACK",
                    reasons=(
                        f"S급 정배열 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "S급 정배열 확인 — 눌림 구간 진입 대기",
                    ),
                )
            elif grade.startswith("✅") and trend == "🚀정배열(상승)":
                dec, col, decision_outcome = _set_decision(
                    "🔍A급 정배열: 타점 탐색 중", "#3b82f6", "A_UPTREND_SEARCH_ENTRY",
                    reasons=(
                        f"A급 정배열 / RSI {rsi_now:.0f} / %B {pct_b_now:.2f}",
                        "A급 정배열 — 타점 탐색 중",
                    ),
                )
            else:
                dec, col, decision_outcome = _set_decision(
                    "🔍대기: 신규 타점 탐색", "#64748b", "SEARCH_NEW_ENTRY",
                    reasons=(
                        f"RSI {rsi_now:.0f} / %B {pct_b_now:.2f} / 추세 {trend}",
                        "진입 조건 미충족 — 타점 탐색",
                    ),
                )
    return decision_outcome


def select_portfolio_guard_decision(
    *,
    _fmr,
    core_dca_context,
    core_dca_rate,
    curr_w,
    fin_score,
    is_core_dca_allowed,
    is_etf,
    is_zero_target_holding,
    short_history,
    targ_w,
) -> DecisionOutcome | None:
    if not is_etf and fin_score <= 1:
        dec, col, decision_outcome = _set_decision(
            "🚨하드차단: 재무F급(처분)", "#dc2626", "HARD_BLOCK_FINANCIAL_F",
            reasons=(f"재무점수 {fin_score}점 (기준: 2점 이상 필요)", "재무 F급 종목 — 보유 지속 시 손실 위험 높음"),
        )
    elif is_zero_target_holding:
        dec, col, decision_outcome = _set_decision(
            "🛑목표비중 0%: 추매금지/정리대상", "#dc2626", "TARGET_ZERO_NO_ADD",
            reasons=(
                f"목표비중 {targ_w:.1f}% / 현재비중 {curr_w:.1f}%",
                "목표비중이 0인 보유 종목은 눌림 신호가 있어도 추가매수 대상이 아니라 축소/정리 관리 대상",
            ),
        )
    elif curr_w > targ_w and targ_w > 0:
        dec, col, decision_outcome = _set_decision(
            "🛑하드차단: 비중 초과", "#dc2626", "HARD_BLOCK_OVERWEIGHT",
            reasons=(
                f"현재비중 {curr_w:.1f}% > 목표비중 {targ_w:.1f}% (+{curr_w-targ_w:.1f}%p 초과)",
                "비중 초과 상태 — 신규 매수 불가, 리밸런싱 또는 익절 검토",
            ),
        )
    elif curr_w >= targ_w and targ_w > 0:
        dec, col, decision_outcome = _set_decision(
            "⏸️하드차단: 비중 충족(관망)", "#d97706", "HARD_BLOCK_TARGET_FILLED",
            reasons=(
                f"현재비중 {curr_w:.1f}% >= 목표비중 {targ_w:.1f}%",
                "비중 충족 - 추가 매수 불필요, 눌림 시 재검토",
            ),
        )
    elif is_core_dca_allowed and _fmr >= 4.5:
        dca_label = core_dca_context["core_dca_label"]
        prefix = "🧱신규 코어 ETF" if short_history else "🧱코어"
        if core_dca_rate >= 1.0:
            storm_color = "#16a34a"
            storm_reasons = (
                "퍼펙트스톰 구간이지만 미국 대표지수 코어 ETF 목표비중 미달 - 거치식 원칙 유지",
                f"적립 비율 {int(core_dca_rate * 100)}% 적용 - 장기 우상향 코어는 매크로 타이밍보다 시장 노출 우선",
            )
        else:
            storm_color = "#d97706" if core_dca_rate <= 0.25 else "#3b82f6"
            storm_reasons = (
                "퍼펙트스톰 구간이지만 코어 ETF 목표비중 미달 - 전면 차단 대신 감속 적립",
                f"적립 비율 {int(core_dca_rate * 100)}% 로 제한 - 변동성 확대 구간 방어적 접근",
            )
        dec, col, decision_outcome = _set_decision(
            f"{prefix} 방어: {dca_label}",
            storm_color,
            "CORE_STORM_DCA",
            reasons=storm_reasons,
        )
    elif _fmr >= 4.5:
        dec, col, decision_outcome = _set_decision(
            "🛡️시장위험: 추매중단/보유점검", "#d97706", "MACRO_STORM_HOLDING_CAUTION",
            reasons=(
                f"퍼펙트스톰 지수 {_fmr:.1f} (기준: 4.5 이상)",
                "보유 종목 전량 매도 신호가 아니라 신규/추매를 멈추고 손절선·비중·하락 원인을 점검하는 구간",
            ),
        )
    else:
        return None
    return decision_outcome
