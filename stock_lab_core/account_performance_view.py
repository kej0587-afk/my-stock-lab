"""On-demand account performance workspace, with no broker or database writes."""

from hashlib import sha256

import pandas as pd

from stock_lab_core.account_performance import calculate_account_performance
from stock_lab_core.account_performance_io import decode_ledger, empty_ledger, encode_ledger, ledger_accounts
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _result_table(st, result):
    for issue in result["issues"]:
        st.warning(issue)
    if result["status"] != "ready":
        return
    summary = result["summary"]
    left, middle, right = st.columns(3)
    left.metric("연결 수익률", f"{summary['return_pct']:+.2f}%")
    middle.metric("입출금 제외 투자손익", f"{summary['investment_pnl_krw']:+,.0f}원")
    right.metric("외부 순입금", f"{summary['net_flow_krw']:+,.0f}원")
    st.caption(f"{summary['start']:%Y-%m-%d} ~ {summary['end']:%Y-%m-%d} · {summary['method']} · 일말 입출금 가정 · 원화 평가액 기준")
    if "추정" in summary["method"]:
        st.warning("입출금 당시 평가액이 없는 구간은 Modified Dietz 추정입니다. 큰 입출금과 급격한 등락이 겹치면 오차가 커질 수 있습니다. 엄밀한 일별 TWR가 아닙니다.")
    if summary.get("outside_flow_count", 0):
        st.caption(f"평가기간 밖 입출금 {summary['outside_flow_count']}건은 이번 계산에서 제외했습니다.")
    table = result["periods"].rename(columns={
        "start": "시작일", "end": "종료일", "opening_value_krw": "기초 평가액(원)",
        "closing_value_krw": "기말 평가액(원)", "net_flow_krw": "순입금(원)",
        "investment_pnl_krw": "투자손익(원)", "return_pct": "수익률(%)", "method": "산식", "status": "상태",
    }).drop(columns=["weighted_flow_krw"], errors="ignore")
    display = table.copy()
    for col in ("기초 평가액(원)", "기말 평가액(원)", "순입금(원)", "투자손익(원)"):
        display[col] = display[col].map(lambda value: f"{value:,.0f}")
    display["수익률(%)"] = display["수익률(%)"].map(lambda value: f"{value:+.2f}")
    display["상태"] = display["상태"].map({"ready": "계산됨", "invalid": "계산보류"}).fillna("미확인")
    st.dataframe(display, width="stretch", hide_index=True)
    st.download_button("성과 계산표 CSV", table.to_csv(index=False).encode("utf-8-sig"),
                       file_name="stock_lab_account_performance_results.csv", mime="text/csv", key="account_performance_result_csv")


def render_account_performance(st, *, owner_scope, monthly_logs_df=None):
    scope = sha256(str(owner_scope or "").strip().lower().encode()).hexdigest()[:20]
    prefix = f"account_performance_v1_{scope}"
    draft_key, revision_key, result_key = prefix + "_draft", prefix + "_revision", prefix + "_result"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = empty_ledger()
        st.session_state[revision_key] = 0
    with st.expander("계좌 성과 원장", expanded=False):
        st.caption("평가액: 현금·배당 잔액과 당시 환율을 포함한 원화 총자산. 외부 입출금은 선택 계좌 밖에서 들어오거나 나간 금액입니다. 계좌 안 배당·매매·환전, 전체계좌 분석의 계좌간 이체는 외부 입출금이 아닙니다.")
        st.caption("저장 위치: 현재 접속의 개인 초안 · 서버 영구저장 안 함 · 기존 보유자산·월별 기록은 변경하지 않음")
        old_count = len(monthly_logs_df) if isinstance(monthly_logs_df, pd.DataFrame) else 0
        if old_count:
            st.caption(f"기존 월별 기록 {old_count}개: 실제 평가일·입출금 날짜가 미저장되어 원장으로 자동 변환하지 않았습니다.")

        uploaded = st.file_uploader("성과 원장 JSON", type=["json"], max_upload_size=1, key=prefix + "_upload")
        if uploaded is not None and st.button("원장 불러오기", key=prefix + "_import"):
            try:
                imported = decode_ledger(uploaded.getvalue())
            except (ValueError, TypeError) as exc:
                st.error(str(exc))
            else:
                st.session_state[draft_key] = imported
                st.session_state[revision_key] += 1
                st.session_state.pop(result_key, None)
                st.success("원장 초안을 불러왔습니다. 입출금 누락 여부는 다시 확인해야 합니다.")
        draft = st.session_state[draft_key]
        revision = st.session_state[revision_key]
        with st.form(prefix + "_edit_" + str(revision)):
            st.markdown("**평가 기록**")
            valuations = st.data_editor(draft["valuations"], num_rows="dynamic", width="stretch", hide_index=True,
                key=prefix + "_nav_" + str(revision), column_config={
                    "date": st.column_config.DateColumn("평가일", format="YYYY-MM-DD"),
                    "account": st.column_config.TextColumn("계좌"),
                    "value_krw": st.column_config.NumberColumn("원화 총자산", min_value=0., format="%.0f"),
                })
            st.markdown("**외부 입출금**")
            flows = st.data_editor(draft["flows"], num_rows="dynamic", width="stretch", hide_index=True,
                key=prefix + "_flows_" + str(revision), column_config={
                    "id": st.column_config.TextColumn("거래ID"),
                    "date": st.column_config.DateColumn("입출금일", format="YYYY-MM-DD"),
                    "account": st.column_config.TextColumn("계좌"),
                    "amount": st.column_config.NumberColumn("입금(+)/출금(-)", format="%.2f"),
                    "currency": st.column_config.SelectboxColumn("통화", options=["KRW", "USD"]),
                    "fx_rate": st.column_config.NumberColumn("당일 원/통화 환율", min_value=0., format="%.4f"),
                })
            applied = st.form_submit_button("원장 초안 적용")
        if applied:
            candidate = {"valuations": valuations.copy(), "flows": flows.copy()}
            try:
                encode_ledger(candidate)
            except (TypeError, ValueError) as exc:
                st.error("초안 적용 보류: " + str(exc))
            else:
                st.session_state[draft_key] = candidate
                st.session_state[revision_key] += 1
                st.session_state.pop(result_key, None)
                st.rerun()

        try:
            raw = encode_ledger(draft)
        except (TypeError, ValueError):
            st.warning("원장에 저장할 수 없는 값이 있습니다. 날짜와 수치를 확인해 주세요.")
        else:
            st.download_button("원장 JSON 다운로드", raw, file_name="stock_lab_account_performance.json",
                               mime="application/json", key=prefix + "_download")

        accounts = ledger_accounts(draft)
        if not accounts:
            st.info("계좌 성과 미산출 · 계좌별 평가 기록과 외부 입출금 확인이 필요합니다.")
            return
        account = st.selectbox("성과 분석 계좌", accounts, key=prefix + "_account_" + str(revision))
        complete = st.checkbox("이 계좌의 평가기간 입출금을 모두 확인했습니다(입출금이 없었던 경우 포함)",
                               value=False, key=prefix + "_complete_" + str(revision) + "_" + sha256(account.encode()).hexdigest()[:12])
        token = (revision, account, complete)
        if st.button("계좌 성과 계산", key=prefix + "_calculate"):
            result = calculate_account_performance(draft["valuations"], draft["flows"], account, flows_complete=complete)
            st.session_state[result_key] = {"token": token, "result": result}
        saved = st.session_state.get(result_key, {})
        if saved.get("token") == token:
            _result_table(st, saved["result"])
