"""Monthly rebalancing widgets; calculation and log actions are explicit dependencies."""

import pandas as pd

from stock_lab_core.formatters import clean_float
from stock_lab_core.monthly_rebalance import prepare_rebalance_holdings, build_rebalance_plan
from stock_lab_core.monthly_rebalance_log import render_monthly_log_panel
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _initialize_state(st, _done_key):
    if "rebcalc_monthly" not in st.session_state:
        st.session_state["rebcalc_monthly"] = 750000
    if "rebcalc_carryover" not in st.session_state:
        st.session_state["rebcalc_carryover"] = 0
    if "rebcalc_redistribute" not in st.session_state:
        st.session_state["rebcalc_redistribute"] = True
    if _done_key not in st.session_state:
        st.session_state[_done_key] = {}
    # 종목별 적립 누적금 (1주 미달 시 매달 쌓아두는 금액, 월 스코프 없이 영구 보관)
    if "rebcalc_accum" not in st.session_state:
        st.session_state["rebcalc_accum"] = {}   # {ticker: accumulated_krw}
    # 항상 투자 종목 (신호 무관 · 과열/차단 무시하고 배율 1.0 고정)
    if "rebcalc_always_invest" not in st.session_state:
        st.session_state["rebcalc_always_invest"] = []


def _render_inputs(st, _this_month, _has_signals):
    if not _has_signals:
        st.info(
            "⚠️ 기술적 타점 신호가 아직 로드되지 않았습니다. "
            "아래 포트폴리오 섹션의 **'분석 실행/새로고침'** 버튼을 눌러주세요. "
            "그 다음부터는 대시보드와 동일한 신호가 표시됩니다."
        )
    else:
        st.caption(
            f"**{_this_month}** 기준 · 신호는 대시보드 분석 기준과 동일 · "
            "🟢 투자=신호OK · ⚠️ 25%=과열주의 · ⛔ 차단 / ⏸ 대기·스윙 = 이번달 제외"
        )

    # ── 입력 영역 ──────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    monthly = c1.number_input(
        "이번 달 적립금 (원)", min_value=0, step=50000,
        value=st.session_state["rebcalc_monthly"], key="rebcalc_monthly_inp",
    )
    carryover = c2.number_input(
        "이월 누적금 (원)", min_value=0, step=10000,
        value=st.session_state["rebcalc_carryover"], key="rebcalc_carryover_inp",
    )
    st.session_state["rebcalc_monthly"] = monthly
    st.session_state["rebcalc_carryover"] = carryover
    total_invest = monthly + carryover
    c3.metric("총 투자 가능금", f"{total_invest:,.0f}원")
    redistribute_mode = c4.checkbox(
        "미투자금 자동 재분배", value=st.session_state["rebcalc_redistribute"],
        key="rebcalc_redist_chk",
        help="차단·대기 종목에 배분됐을 금액을 투자 가능 종목에 비중대로 추가 배분합니다.",
    )
    st.session_state["rebcalc_redistribute"] = redistribute_mode
    return monthly, carryover, total_invest, redistribute_mode


def _select_always_invest(st, eligible):
    _eligible_ticker_map = {
        str(row.get("티커", "")): str(row.get("자산명", row.get("티커", "")))
        for _, row in eligible.iterrows()
        if str(row.get("티커", ""))
    }
    _prev_always = [t for t in st.session_state["rebcalc_always_invest"] if t in _eligible_ticker_map]
    always_invest_list = st.multiselect(
        "📌 항상 투자 종목 — 신호 무관하게 매달 100% 배분 (나스닥·S&P500 등 지수 ETF 권장)",
        options=list(_eligible_ticker_map.keys()),
        default=_prev_always,
        format_func=lambda t: f"{_eligible_ticker_map.get(t, t)} ({t})",
        key="rebcalc_always_invest_sel",
    )
    st.session_state["rebcalc_always_invest"] = always_invest_list
    always_invest_set = set(always_invest_list)
    return always_invest_set


def _refresh_accumulated_state(st, calc_rows):
    _accum_refresh = dict(st.session_state["rebcalc_accum"])
    _accum_refresh_changed = False
    for r in calc_rows:
        if r.get("accumulated_krw", 0) > 0 and r.get("rec_shares", 0) > 0:
            leftover = max(0.0, r["effective_alloc"] - r["rec_krw"])
            _accum_refresh[r["ticker"]] = leftover
            _accum_refresh_changed = True
    if _accum_refresh_changed:
        st.session_state["rebcalc_accum"] = _accum_refresh


def _render_allocation_table(st, calc_rows):
    st.markdown("#### 📋 이번달 배분 계획")
    table_rows = []
    for r in calc_rows:
        shares_disp = (
            str(r["rec_shares"]) if r["multiplier"] > 0 and r["rec_shares"] > 0
            else ("-" if r["multiplier"] == 0 else "0주")
        )
        # 레버리지 배율 표시 추가
        if r["bucket"] == "leverage" and r["multiplier"] > 0:
            mult_badge = f" ×{r['multiplier']:.1f}"
        else:
            mult_badge = ""
        # 하락 감지 표시
        dip_badge = " 📉" if r.get("is_dip") else ""
        table_rows.append({
            "자산명":     r["name"] + dip_badge,
            "버킷":       r["bucket"],
            "목표비중":   f"{r['target_w']:.1f}%",
            "기술적타점": r["tap_disp"],
            "배분금액":   (r["alloc_disp"] + mult_badge) if r["multiplier"] > 0 else "-",
            "권장주수":   shares_disp,
            "상태":       r["status"],
        })
    # 정렬: 레버리지 투자 → 일반 투자 → 레버리지 패스 → 일반 차단
    def _sort_key(pair):
        _, r = pair
        if r["bucket"] == "leverage" and r["multiplier"] > 0: return 0
        if r["multiplier"] > 0:                                return 1
        if r["bucket"] == "leverage":                          return 2
        return 3
    sorted_pairs = sorted(zip(table_rows, calc_rows), key=_sort_key)
    st.dataframe(pd.DataFrame([t for t, _ in sorted_pairs]), width='stretch', hide_index=True)


def _render_budget_summary(st, active_rows, blocked_rows, total_invest, usdkrw, redistribute_mode):
    total_rec_krw     = sum(r["rec_krw"] for r in active_rows)
    total_blocked     = sum(r["base_alloc"] for r in blocked_rows)
    remainder_krw     = total_invest - total_rec_krw

    # 원화 vs 달러 환전 분리
    rec_krw_only  = sum(r["rec_krw"] for r in active_rows if not r["is_usd"])   # 원화 직접 투자
    rec_usd_krw   = sum(r["rec_krw"] for r in active_rows if r["is_usd"])        # 달러 환전 필요분(원화 기준)
    rec_usd_amt   = rec_usd_krw / usdkrw if usdkrw > 0 else 0                   # 달러 금액

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("총 투자 가능", f"{total_invest:,.0f}원")
    s2.metric("이번달 권장 투자금", f"{total_rec_krw:,.0f}원")
    s3.metric("잔여(이월 후보)", f"{remainder_krw:,.0f}원",
              help="반올림 차이 + 차단·대기로 미투자된 금액. '잔여금 이월' 버튼으로 다음달 적립금에 합산하세요.")
    if not redistribute_mode:
        s4.metric("차단·대기 금액", f"{total_blocked:,.0f}원",
                  help="재분배 체크 시 투자 가능 종목에 비중대로 추가 배분됩니다.")
    else:
        s4.metric("재분배", "✅ 적용됨")

    # 환전 필요금액 안내
    if rec_usd_krw > 0 or rec_krw_only > 0:
        fx1, fx2, fx3 = st.columns(3)
        fx1.metric("🇰🇷 원화 직접 투자", f"{rec_krw_only:,.0f}원",
                   help="국내 종목(KS/KQ) 매수에 필요한 원화")
        fx2.metric("🇺🇸 달러 환전 필요", f"${rec_usd_amt:,.2f}",
                   help=f"해외 종목 매수용 · 원화 기준 {rec_usd_krw:,.0f}원 (환율 {usdkrw:,.0f}원/달러 적용)")
        fx3.metric("원화+환전 합계", f"{(rec_krw_only + rec_usd_krw):,.0f}원",
                   help="이번달 실제 필요 원화 총액 (환전분 포함)")
    return remainder_krw


def _render_accumulation(st, underalloc_rows):
    if underalloc_rows:
        st.markdown("#### 🟡 1주 미달 종목 — 적립 누적 관리")
        st.caption(
            "투자 신호는 있지만 배분금액이 **1주 가격 미만**인 종목입니다. "
            "매달 이 금액을 누적하거나, 재분배 모드를 켜서 다른 종목에 배분할 수 있습니다."
        )
        ua_table = []
        for r in underalloc_rows:
            accum = r["accumulated_krw"]
            needed = max(0, r["unit_price_krw"] - accum)
            ua_table.append({
                "자산명":       r["name"],
                "1주 가격":     f"{r['unit_price_krw']:,.0f}원",
                "이번달 배분":  r["alloc_disp"],
                "현재 누적금":  f"{accum:,.0f}원",
                "추가 필요":    f"{needed:,.0f}원",
                "예상 구매":    f"~{r.get('months_to_buy', '?')}달 후",
                "상태":         r["status"],
            })
        st.dataframe(pd.DataFrame(ua_table), width='stretch', hide_index=True)

        ua_c1, ua_c2 = st.columns(2)
        with ua_c1:
            if st.button("💰 이번달 미달 배분금 누적에 추가", key="rebcalc_accum_add"):
                _accum_new = dict(st.session_state["rebcalc_accum"])
                added_total = 0
                for r in underalloc_rows:
                    prev = _accum_new.get(r["ticker"], 0.0)
                    _accum_new[r["ticker"]] = prev + r["final_alloc"]
                    added_total += r["final_alloc"]
                st.session_state["rebcalc_accum"] = _accum_new
                st.success(f"✅ {len(underalloc_rows)}개 종목 · 총 {added_total:,.0f}원 누적에 추가됐습니다.")
                st.rerun()
        with ua_c2:
            if st.button("🗑️ 누적금 전체 초기화", key="rebcalc_accum_reset"):
                st.session_state["rebcalc_accum"] = {}
                st.success("누적금이 초기화됐습니다.")
                st.rerun()

        st.info(
            "💡 **설계 가이드** — 1주 미달 상황 대처법:\n\n"
            "• **🟡 적립 이월 (권장·코어ETF)**: '이번달 배분금 누적에 추가' 클릭 → 다음달 자동 합산 → 1주 가격 모이면 구매\n"
            "• **⚠️ 재분배**: 상단 '미투자금 자동 재분배' 체크 → 미달 배분금이 다른 종목에 추가됨 (비중 왜곡 있음)\n"
            "• **⏸ 신호 해소 대기**: 과열 신호 → 차단·대기 종목으로 설정 → 신호가 🟢로 바뀔 때 100% 비중으로 구매\n"
            "• **📅 타이밍 결론**: 코어 ETF는 '적립 이월'이 가장 안전. "
            "과열 해소되면 배분금이 커지고 주수도 늘어납니다."
        )


def _render_leverage(st, leverage_rows, lev_active, lev_blocked):
    if leverage_rows:
        st.markdown("#### ⚡ 레버리지 전략 현황")
        st.caption(
            "**레버리지 배율 기준** — "
            "🚀 진입 ×1.5 · 📉 약하락 DCA ×0.75 · 📉📉 중하락 DCA ×1.0 · 📉📉 강하락 ×1.25 · "
            "📉📉🚀 매수+중하락 ×1.75 · 📉📉📉🚀 매수+강하락 ×2.0 · "
            "🌡️ 과열패스 ×0 · ⛔ 가격/급락/추세방어 ×0\n\n"
            "평단 대비 **-5% 이상** 하락 시 단계별 배율 상향 — "
            "약(-5%~-10%) → 중(-10%~-15%) → 강(-15%↓)"
        )
        _dip_labels = {0: "📈 정상", 1: "📉 약(-5~-10%)", 2: "📉📉 중(-10~-15%)", 3: "📉📉📉 강(-15%↓)"}
        lev_table = []
        for r in leverage_rows:
            pct_vs_avg = ((r["cur_p"] / r["avg_p"]) - 1) * 100 if r["avg_p"] > 0 else 0
            pct_disp   = f"{pct_vs_avg:+.1f}%" if r["avg_p"] > 0 else "-"
            lev_table.append({
                "자산명":     r["name"],
                "기술적타점": r["tap_disp"],
                "평단대비":   pct_disp,
                "하락단계":   _dip_labels.get(r.get("dip_level", 0), "📈 정상"),
                "배율":       f"×{r['multiplier']:.2f}",
                "배분금액":   r["alloc_disp"] if r["multiplier"] > 0 else "-",
                "권장주수":   str(r["rec_shares"]) if r["rec_shares"] > 0 else "-",
                "상태":       r["status"],
            })
        st.dataframe(pd.DataFrame(lev_table), width='stretch', hide_index=True)

        # 레버리지 전략 요약
        if lev_active:
            lev_alloc_total = sum(r["final_alloc"] for r in lev_active)
            lev_krw_total   = sum(r["rec_krw"] for r in lev_active)
            dip_cnt         = sum(1 for r in lev_active if r["is_dip"])
            la1, la2, la3 = st.columns(3)
            la1.metric("레버리지 배분 합계", f"{lev_alloc_total:,.0f}원")
            la2.metric("레버리지 권장 투자금", f"{lev_krw_total:,.0f}원")
            la3.metric("하락 감지 종목", f"{dip_cnt}개", help="평단 -5% 이상 하락 종목 수")

        if lev_blocked:
            blocked_names = ", ".join(r["name"] for r in lev_blocked)
            st.caption(f"⚠️ 이번달 패스 레버리지: {blocked_names}")


def _render_target_shares(st, calc_rows, portfolio_summary, usdkrw):
    st.markdown("#### 📊 총 필요 주수 (목표비중 대비)")
    portfolio_total = clean_float(
        portfolio_summary.get("current_asset") if portfolio_summary else None, 0.0
    )
    st.caption(
        f"현재 포트폴리오 총평가액 **{portfolio_total:,.0f}원** 기준 · "
        "목표비중을 달성하려면 각 종목을 몇 주 보유해야 하는지 표시합니다. "
        "매달 적립매수로 자연스럽게 수렴하는 목표치로 활용하세요."
    )
    need_rows = []
    for r in calc_rows:
        cur_p  = r["cur_p"]
        is_usd = r["is_usd"]
        target_w_pct = r["target_w"]
        qty_now = r["qty"]

        if cur_p <= 0 or portfolio_total <= 0:
            target_shares = 0.0
        else:
            target_krw = portfolio_total * (target_w_pct / 100.0)
            if is_usd:
                target_shares = target_krw / (cur_p * usdkrw) if usdkrw > 0 else 0.0
            else:
                target_shares = target_krw / cur_p

        diff = target_shares - qty_now
        diff_disp = f"+{diff:.2f}" if diff >= 0 else f"{diff:.2f}"
        need_rows.append({
            "자산명":   r["name"],
            "목표비중": f"{target_w_pct:.1f}%",
            "목표주수": f"{target_shares:.2f}",
            "현재보유": f"{qty_now:.4f}",
            "추가필요": diff_disp,
            "버킷":     r["bucket"],
            "상태":     ("✅ 완료" if abs(diff) < 0.5
                          else ("📈 매수필요" if diff > 0 else "📉 비중초과")),
        })
    st.dataframe(pd.DataFrame(need_rows), width='stretch', hide_index=True)


def _render_completion(st, swing_rows, buyable_rows, active_rows, _done_key, _this_month):
    if swing_rows:
        st.markdown("#### ⚡ 스윙 종목 (이번달 매수 여부)")
        st.caption(
            "스윙 종목은 자동 배분에서 제외되지만, 기회매수를 했다면 아래에서 체크하세요."
        )
        sw_cols = st.columns(min(len(swing_rows), 4))
        swing_done_map = dict(st.session_state[_done_key])
        for i, r in enumerate(swing_rows):
            with sw_cols[i % 4]:
                checked = st.checkbox(
                    f"⚡ {r['name']}",
                    value=swing_done_map.get(r["ticker"], False),
                    key=f"rebcalc_swing_{r['ticker']}_{_this_month}",
                )
                swing_done_map[r["ticker"]] = checked
        st.session_state[_done_key] = swing_done_map

    # ── ✅ 투자 완료 체크 (실제 매수 가능 종목만) ───────────────────────
    st.markdown("#### ✅ 이번달 투자 완료 체크")
    done_map = dict(st.session_state[_done_key])
    if buyable_rows:
        chk_cols = st.columns(min(len(buyable_rows), 4))
        for i, r in enumerate(buyable_rows):
            with chk_cols[i % 4]:
                checked = st.checkbox(
                    r["name"],
                    value=done_map.get(r["ticker"], False),
                    key=f"rebcalc_chk_{r['ticker']}_{_this_month}",
                )
                done_map[r["ticker"]] = checked
        st.session_state[_done_key] = done_map

        all_done = all(done_map.get(r["ticker"], False) for r in buyable_rows)
        if all_done and buyable_rows:
            st.success("🎉 이번 달 매수 가능 종목을 모두 완료했습니다!")
    elif active_rows and not buyable_rows:
        st.caption("이번 달 1주 이상 매수 가능한 종목이 없습니다. 위 적립 누적 섹션을 이용하세요.")
    else:
        st.caption("이번 달 투자 가능한 종목이 없습니다.")


def render_monthly_rebalancing_calculator(
    st, holdings_table, usdkrw, portfolio_summary, monthly_logs_df=None, *,
    signal_multiplier, CURRENT_USER_EMAIL, IS_PUBLIC_DEMO, save_monthly_logs_db,
):
    import datetime as _dt

    _this_month = _dt.date.today().strftime("%Y-%m")
    _done_key = f"rebcalc_done_{_this_month}"
    _initialize_state(st, _done_key)
    _signal_cache = st.session_state.get("_ticker_signal_cache", {})
    _has_signals = bool(_signal_cache)

    with st.expander("💰 월 적립 리밸런싱 계산기", expanded=False):
        monthly, carryover, total_invest, redistribute_mode = _render_inputs(st, _this_month, _has_signals)
        if holdings_table is None or holdings_table.empty or total_invest <= 0:
            st.info("적립금을 입력하면 계산이 시작됩니다.")
            return

        eligible = prepare_rebalance_holdings(holdings_table)
        if eligible.empty:
            st.info("리밸런싱 대상 종목이 없습니다. (목표비중 > 0, reserve/cash 제외)")
            return

        target_w_sum = float(eligible["목표비중"].sum())
        if target_w_sum <= 0:
            st.warning("목표비중 합계가 0입니다.")
            return

        always_invest_set = _select_always_invest(st, eligible)
        calc_rows = build_rebalance_plan(
            eligible, target_w_sum, total_invest, usdkrw, _signal_cache,
            always_invest_set, redistribute_mode, st.session_state["rebcalc_accum"], signal_multiplier,
        )
        _refresh_accumulated_state(st, calc_rows)

        active_rows      = [r for r in calc_rows if r["multiplier"] > 0]
        blocked_rows     = [r for r in calc_rows if r["multiplier"] == 0]
        swing_rows       = [r for r in blocked_rows if r["bucket"] == "swing"]
        leverage_rows    = [r for r in calc_rows if r["bucket"] == "leverage"]
        lev_active       = [r for r in leverage_rows if r["multiplier"] > 0]
        lev_blocked      = [r for r in leverage_rows if r["multiplier"] == 0]
        underalloc_rows  = [r for r in active_rows if r["is_underalloc"]]
        buyable_rows     = [r for r in active_rows if not r["is_underalloc"]]

        _render_allocation_table(st, calc_rows)
        remainder_krw = _render_budget_summary(
            st, active_rows, blocked_rows, total_invest, usdkrw, redistribute_mode,
        )
        _render_accumulation(st, underalloc_rows)
        _render_leverage(st, leverage_rows, lev_active, lev_blocked)
        _render_target_shares(st, calc_rows, portfolio_summary, usdkrw)
        _render_completion(st, swing_rows, buyable_rows, active_rows, _done_key, _this_month)
        render_monthly_log_panel(
            st, monthly_logs_df, _this_month, _done_key, monthly, carryover, total_invest, remainder_krw,
            CURRENT_USER_EMAIL=CURRENT_USER_EMAIL, IS_PUBLIC_DEMO=IS_PUBLIC_DEMO,
            save_monthly_logs_db=save_monthly_logs_db,
        )
