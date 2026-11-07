"""Read-only MSFT business review; reuse the user's existing SEC review snapshot."""

from hashlib import sha256
import json

from stock_lab_core.msft_ir_review import business_reading, reconcile_sec
from stock_lab_core.msft_ir_source import load_msft_business_evidence


SCOPE_LABELS = {
    "company_total": "회사 전체", "reported_segment": "공시 보고 부문",
    "overlapping_cloud_metric": "부문과 중복되는 Cloud 지표", "product_metric": "제품 매출 증가율",
    "includes_finance_lease_principal": "리스 개시 시 원금 포함 · 현금 지출 아님",
    "unverified_capex_scope": "CAPEX 범위 확인 필요", "finance_leases": "금융리스",
    "cash_ppe": "현금 유형자산 지출", "company_defined_fcf": "회사 정의 FCF",
    "company_reported_capex_not_cash_ppe": "회사 CAPEX 전망 · 현금 지출 전망 아님",
}


def existing_sec_review(state, owner, ticker):
    # Read-only contract with sec_quarter_review_view's owner/ticker scope.
    # Never scan another user's session keys or trigger a second SEC request.
    key = "sec_quarter_review_" + sha256(f"{owner}|{ticker}".encode()).hexdigest()[:20]
    bundle = state.get(key) or {}
    if state.get(key + "_symbols", bundle.get("selected")) != bundle.get("selected"):
        return None
    return next((r for r in bundle.get("results", []) if r.get("ticker") == "MSFT"), None)


def metric_rows(packet, kind):
    result = []
    for m in packet["metrics"]:
        if m["kind"] != kind:
            continue
        value = (f"{m['value']:g}십억 USD" if m["unit"] == "USD_billion" else
                 f"{m['value']:g}% YoY" if m["unit"] == "percent_yoy" else str(m["value"]))
        if m["operator"] == "gt":
            value += " 초과"
        result.append({"항목": m["label"], "값": value, "기간": m["period"],
            "범위": SCOPE_LABELS[m["scope"]], "출처": m["source_url"]})
    return result


def render_msft_business_review(st, *, ticker, owner, is_demo=False, loader=load_msft_business_evidence):
    if ticker != "MSFT" or not owner or is_demo:
        return
    key = "msft_business_review_" + sha256(f"{owner}|{ticker}".encode()).hexdigest()[:20]
    st.caption("공식 실적·콜에서 회사 전체/보고 부문/Cloud 지표와 회사 전망을 구분합니다. 기존 재무점수·판정에 반영하지 않습니다.")
    if st.button("MSFT 공식 사업 실적·투자 전망 조회", key=key + "_load"):
        st.session_state.pop(key, None)
        try:
            with st.spinner("Microsoft 공식 IR 발표와 콜 확인 중..."):
                st.session_state[key] = loader()
        except Exception:
            st.warning("공식 발표의 기간·출처를 확인하지 못했습니다. 이전 전망을 최신 자료로 대신 표시하지 않습니다.")
    packet = st.session_state.get(key)
    if not packet:
        return
    st.caption(f"발표일 {packet['release_date']} · 실제 실적 {packet['period_start']}~{packet['period_end']} · 조회 {packet['checked_at']}")
    if packet["status"] == "partial":
        st.info("공식 발표는 연결됐지만 실적·전망 중 일부 항목은 미확인입니다. 검증된 항목만 표시합니다.")
    for label, text, url in business_reading(packet):
        st.markdown(f"**{label}** · {text} [공식 근거]({url})")
    st.caption("Microsoft Cloud와 Azure는 보고 부문에 겹치는 지표입니다. 부문 매출과 합산하지 않으며 AI 전용 매출로 간주하지 않습니다. 회사 전망은 컨센서스가 아닙니다.")
    if packet["segment_recast"]:
        st.info("보고 부문이 개편되고 비교 기간이 재작성됐습니다. 과거 Intelligent Cloud 등 이전 분류와 단순 연결하지 않습니다.")
    actual_tab, outlook_tab, source_tab = st.tabs(["확인된 실적", "회사 전망", "SEC 대조·출처"])
    with actual_tab:
        st.dataframe(metric_rows(packet, "reported_actual"), hide_index=True, width="stretch",
                     column_config={"출처":st.column_config.LinkColumn(display_text="공식 원문")})
    with outlook_tab:
        outlook = metric_rows(packet, "management_outlook")
        if outlook:
            st.dataframe(outlook, hide_index=True, width="stretch",
                         column_config={"출처":st.column_config.LinkColumn(display_text="공식 원문")})
        else:
            st.info("숫자로 검증된 회사 전망 없음 · 실적이나 이전 전망으로 대체하지 않음")
    comparison = reconcile_sec(packet, existing_sec_review(st.session_state, owner, ticker))
    with source_tab:
        st.dataframe(comparison, hide_index=True, width="stretch")
        st.caption("위 8분기 패널에서 MSFT를 조회하면 같은 기간의 SEC 자료와 대조합니다. 회사 CAPEX에서 리스를 단순 차감해 현금 지출을 만들지 않습니다. 반올림 범위 일치는 정의의 동일성을 보증하지 않습니다.")
        st.dataframe([{"항목": m["label"], "원문 수치 구절": m["source_excerpt"], "출처": m["source_url"]}
                      for m in packet["metrics"]], hide_index=True, width="stretch",
                     column_config={"출처":st.column_config.LinkColumn(display_text="공식 원문")})
    st.download_button("MSFT 사업·투자 근거 파일 받기", json.dumps({"evidence":packet,"sec_comparison":comparison},ensure_ascii=False,indent=2),
        file_name="msft_business_review.json", mime="application/json", key=key + "_download")
