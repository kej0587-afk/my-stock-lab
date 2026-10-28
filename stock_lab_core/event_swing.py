"""Manual event-trade journal. No brokerage, order, or execution-gate calls."""

from datetime import datetime
import re
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4

import pandas as pd

from stock_lab_core.report_evidence import number


def slot_check(entry, stop, quantity, fx, loss_budget, catalyst_confirmed):
    values = [number(v) for v in (entry, stop, quantity, fx)]
    if any(v is None or v <= 0 for v in values) or values[1] >= values[0]:
        return {"status": "입력 확인", "loss_krw": None}
    loss = (values[0] - values[1]) * values[2] * values[3]
    budget = number(loss_budget)
    return {"loss_krw": loss, "status": "건별 손실한도 미설정" if budget is None or budget <= 0 else
            "촉매 확인 미완료" if not catalyst_confirmed else "입력 손실한도 초과" if loss > budget else
            "입력 조건 충족 기록 · 매수 허용 아님"}


class EventSwingLedger:
    def __init__(self, client, owner):
        self.client, self.owner = client, str(owner or "").strip().lower()

    def load(self):
        if not self.client or not self.owner:
            return [], "로그인/영구 장부 연결 미확인"
        try:
            rows = self.client.table("event_swing_ledger").select("trade_id,payload,created_at").eq("owner_email", self.owner).order("created_at", desc=True).limit(200).execute().data
            if not isinstance(rows, list):
                raise ValueError("invalid response")
            return rows, ""
        except Exception:
            return [], "영구 장부 미연결: 전용 테이블·권한·연결 확인 필요"

    def save(self, trade_id, payload):
        UUID(trade_id)
        if not self.client or not self.owner:
            return False
        try:
            result = self.client.table("event_swing_ledger").upsert({"trade_id": trade_id, "owner_email": self.owner, "payload": dict(payload)}, on_conflict="owner_email,trade_id").execute().data
            return isinstance(result, list) and len(result) == 1 and result[0].get("trade_id") == trade_id and result[0].get("owner_email") == self.owner
        except Exception:
            return False


def render_event_swing_panel(st, summary, *, client=None, owner=""):
    st.subheader("단기 이벤트 스윙 기록")
    st.caption("장기 편입·적립 게이트는 오늘점검의 현행 판정 그대로입니다. 이 영역은 입력 조건·실제 체결 기록만 다루며 매수 허용이나 자동주문 기능이 없습니다.")
    rows, error = EventSwingLedger(client, owner).load()
    if error:
        st.warning(error + ". 입력을 저장했다고 표시하지 않습니다.")
        from pathlib import Path
        sql = Path(__file__).parents[1] / "docs" / "20261028_event_swing_ledger.sql"
        with st.expander("장부 테이블 설정"):
            st.code(sql.read_text(encoding="utf-8"), language="sql")
    if rows:
        frame = pd.DataFrame([dict(r["payload"], 거래ID=r["trade_id"]) for r in rows])
        st.dataframe(frame, hide_index=True, width="stretch")
        from stock_lab_core.precision_review_export import _csv_safe
        st.download_button("장부 CSV", _csv_safe(frame).to_csv(index=False).encode("utf-8-sig"), "event_swing_ledger.csv", "text/csv")
        st.caption("최근 200건 · 다른 신호 검증 장부와 분리")
    trade_key = f"event_swing_trade_id:{owner}"
    saved_key = f"event_swing_saved:{owner}"
    if trade_key not in st.session_state:
        st.session_state[trade_key] = str(uuid4())
    if st.session_state.get(saved_key):
        st.info("현재 거래는 저장되었습니다.")
        if st.button("새 거래 기록"):
            st.session_state[trade_key] = str(uuid4())
            st.session_state[saved_key] = False
    # Keep one ID across retries; only an explicit new trade gets a new form/ID.
    with st.form(f"event_swing_manual_record:{st.session_state[trade_key]}"):
        ticker = st.text_input("실제 체결 종목 티커").strip().upper()
        day = st.date_input("체결일", value=datetime.now(ZoneInfo("Asia/Seoul")).date())
        currency = st.selectbox("체결 통화", ["KRW", "USD"])
        entry = st.number_input("평균 체결가", min_value=0.0)
        quantity = st.number_input("체결 수량", min_value=0.0)
        stop = st.number_input("기록할 손절 기준가", min_value=0.0)
        usdkrw = st.number_input("USD 체결의 원화 환산환율", min_value=0.0, value=0.0)
        budget = st.number_input("건별 최대손실금액(원, 0=미설정)", min_value=0.0, value=0.0)
        catalyst = st.text_input("촉매·확인 출처")
        confirmed = st.checkbox("촉매의 발표일·출처를 직접 확인함")
        actual = st.checkbox("실제로 체결한 거래를 기록함")
        submitted = st.form_submit_button("체결 기록 저장", disabled=bool(error or st.session_state.get(saved_key)))
    if submitted and not st.session_state.get(saved_key):
        check = slot_check(entry, stop, quantity, 1 if currency == "KRW" else usdkrw, budget, confirmed)
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,23}", ticker) or not actual or check["loss_krw"] is None or not catalyst:
            st.error("티커·실제 체결 여부·가격·수량·환율·촉매를 확인해 주세요.")
            return
        payload = {"티커": ticker, "체결일": day.isoformat(), "통화": currency, "체결가": entry, "수량": quantity,
                   "손절기준": stop, "환산환율": 1 if currency == "KRW" else usdkrw, "건별손실한도(원)": budget or None,
                   "손절기준손실(원)": check["loss_krw"], "촉매": catalyst, "촉매확인": confirmed, "조건상태": check["status"]}
        if EventSwingLedger(client, owner).save(st.session_state[trade_key], payload):
            st.session_state[saved_key] = True
            st.success("실제 체결 기록을 영구 장부에 저장했습니다. 시장 게이트는 변경하지 않았습니다.")
        else:
            st.error("영구 저장 실패: 저장 완료가 아닙니다. 입력은 유지됩니다.")
    st.caption("손절기준 손실은 가격 공백·수수료·환율 변화가 없는 가정입니다. 실제 최대손실을 보장하지 않습니다.")
