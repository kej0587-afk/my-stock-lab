"""Monthly log confirmation and explicit save/carryover actions."""

import math

import pandas as pd

from stock_lab_core.formatters import clean_float
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def render_monthly_log_panel(
    st, monthly_logs_df, _this_month, _done_key, monthly, carryover,
    total_invest, remainder_krw, *, CURRENT_USER_EMAIL, IS_PUBLIC_DEMO, save_monthly_logs_db,
):
    st.markdown("---")
    st.markdown("#### 📅 월별 로그 연동")

    prev_total_invested = 0.0
    prev_month_str = ""
    if monthly_logs_df is not None and not monthly_logs_df.empty:
        _logs = monthly_logs_df[monthly_logs_df["month"].astype(str) < _this_month].copy()
        if not _logs.empty:
            _latest = _logs.sort_values("month").iloc[-1]
            prev_total_invested = clean_float(_latest.get("total_invested"), 0.0)
            prev_month_str = str(_latest.get("month", ""))

    # 누적 투자금 = 이전달 누적 + 이번달 적립금
    # (이월 누적금은 "아직 투자 안 한 현금"이므로 누적 투자금에는 포함하지 않음)
    new_total_invested = prev_total_invested + monthly

    with st.container():
        if prev_month_str:
            st.info(
                f"직전 월 로그: **{prev_month_str}** · 누적 투자금 {prev_total_invested:,.0f}원  \n"
                f"→ 이번 달 계획 적립금 **{monthly:,.0f}원** 반영 시 예상 누적 **{new_total_invested:,.0f}원** (실제 입금 미확인)"
            )
        else:
            st.info("월별 로그 없음 · 최초 투자원금을 포함한 실제 누적 순입금액 확인이 필요합니다.")

        # 이월금 개념 설명
        if carryover > 0:
            st.caption(
                f"💡 **이월 누적금 {carryover:,.0f}원** 안내 — "
                "이월금은 지난달 미투자 잔여금으로, 현재 **원화 예수금에 포함**되어 있습니다. "
                "월별 누적 투자금에는 실제로 '입금한 적립금'만 더하고, "
                "이월금은 이번달 배분 가능 총액(=적립금+이월금)에만 반영합니다. "
                f"이번달 총 투자 가능금: **{total_invest:,.0f}원** (적립금 {monthly:,.0f} + 이월금 {carryover:,.0f})"
            )

    from hashlib import sha256

    log_scope = sha256(str(CURRENT_USER_EMAIL or "").lower().encode()).hexdigest()[:16]
    current_log = monthly_logs_df[monthly_logs_df["month"].astype(str).eq(_this_month)] if isinstance(monthly_logs_df, pd.DataFrame) and "month" in monthly_logs_df else pd.DataFrame()
    default_total = clean_float(current_log.iloc[-1].get("total_invested"), 0.0) if not current_log.empty else prev_total_invested
    confirmed_total = st.number_input("확인한 실제 누적 순입금액(원)", value=default_total, step=10000.,
                                      key=f"rebcalc_actual_total_{log_scope}_{_this_month}")
    default_value = clean_float(current_log.iloc[-1].get("evaluated_value"), 0.0) if not current_log.empty else None
    default_dividend = clean_float(current_log.iloc[-1].get("dividend"), 0.0) if not current_log.empty else None
    confirmed_value = st.number_input("배당을 뺀 평가금액(원)", min_value=0., value=default_value, step=10000.,
                                      key=f"rebcalc_ex_dividend_value_{log_scope}_{_this_month}")
    confirmed_dividend = st.number_input("해당 월 수령 배당금(원)", min_value=0., value=default_dividend, step=100.,
                                         key=f"rebcalc_month_dividend_{log_scope}_{_this_month}")
    st.caption("월별 기록은 배당 제외 평가금액에 기록 시작 이후 누적 배당을 한 번 더합니다. 배당금은 누적액이 아닌 해당 월 수령액이며, 없는 달은 0원을 입력합니다. 달러 배당은 수령일 환율로 환산한 원화액입니다.")
    st.caption("현재 총자산에는 보유자산과 예수금이 포함됩니다. 배당 포함 여부가 달라 월별 평가금액으로 자동 대입하지 않습니다.")
    confirmed_log = st.checkbox("실제 누적 순입금액·배당 제외 평가금액·해당 월 배당과 전체 계좌 범위를 확인했습니다", value=False,
                                key=f"rebcalc_ex_dividend_confirm_{log_scope}_{_this_month}")
    valid_monthly_values = all(
        value is not None and not isinstance(value, bool) and math.isfinite(value)
        for value in (confirmed_total, confirmed_value, confirmed_dividend)
    ) and confirmed_value >= 0 and confirmed_dividend >= 0
    all_accounts = set(st.session_state.get("_app_all_holding_accounts", []))
    full_scope = bool(all_accounts) and all_accounts.issubset(set(st.session_state.get("acc_filter", [])))
    if not full_scope:
        st.warning("일부 계좌만 선택했거나 전체 계좌 범위를 확인하지 못해 공통 월별 로그 저장을 보류합니다.")
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("📝 이번달 로그 기록 (Supabase)", key="rebcalc_save_log", disabled=not (confirmed_log and full_scope and valid_monthly_values)):
            if not (confirmed_log and full_scope and valid_monthly_values):
                st.warning("실제 순입금·배당 제외 평가금액·해당 월 배당과 전체 계좌 범위 확인 전에는 기록하지 않습니다.")
            elif monthly_logs_df is None:
                st.error("monthly_logs_df가 전달되지 않았습니다.")
            elif IS_PUBLIC_DEMO:
                st.warning("데모 모드에서는 저장할 수 없습니다.")
            else:
                new_total_invested = confirmed_total
                logs_copy = monthly_logs_df.copy()
                existing_mask = logs_copy["month"].astype(str) == _this_month
                _cur_asset = confirmed_value
                if existing_mask.any():
                    logs_copy.loc[existing_mask, "total_invested"] = new_total_invested
                    logs_copy.loc[existing_mask, "evaluated_value"] = _cur_asset
                    logs_copy.loc[existing_mask, "dividend"] = confirmed_dividend
                else:
                    new_row = pd.DataFrame([{
                        "month": _this_month,
                        "total_invested": new_total_invested,
                        "evaluated_value": _cur_asset,
                        "dividend": confirmed_dividend,
                    }])
                    logs_copy = pd.concat([logs_copy, new_row], ignore_index=True)
                if save_monthly_logs_db(logs_copy.fillna("")):
                    st.success(
                        f"✅ {_this_month} 로그 저장 완료 — "
                        f"누적 순입금 {new_total_invested:,.0f}원 / 배당 제외 평가금액 {_cur_asset:,.0f}원 / 해당 월 배당 {confirmed_dividend:,.0f}원"
                    )
                    st.rerun()
    with b2:
        if st.button("➡️ 잔여금 다음달 이월", key="rebcalc_do_carryover"):
            _new_carry = int(st.session_state.get("rebcalc_carryover", 0) + remainder_krw)
            st.session_state["rebcalc_carryover"] = _new_carry
            st.success(
                f"잔여금 {remainder_krw:,.0f}원 이월 추가. "
                f"다음달 이월금: {_new_carry:,.0f}원 "
                f"(원화 예수금에 보관 중인 미투자 현금)"
            )
            st.rerun()
    with b3:
        if st.button("🔄 이번달 초기화", key="rebcalc_reset"):
            st.session_state[_done_key] = {}
            st.rerun()
