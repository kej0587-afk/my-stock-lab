"""Monthly-screen panels for C-8 (crisis fund tranches) and C-13 (macro missing log), 2026-11-26.

Writes happen only on explicit button clicks (fund setting, tranche record). Showing the panel writes nothing.
"""
from datetime import datetime, timedelta

import pandas as pd

from stock_lab_core import crisis_fund as cf
from stock_lab_core import crisis_fund_store as store
from stock_lab_core import macro_status_log as mlog
from stock_lab_core.monthly_execution import KST, TYPE_CORE_ETF, kst_month_key
from stock_lab_core.monthly_store import storage_scope


def build_crisis_rows(exec_rows, *, price_loader, gate_reader, funds, tranche_rows, today, cash_available=None):
    """Pure assembly (tests): one row per core ETF in the monthly rows.

    cash_available: account cash left after today's monthly executable amounts (None = 미확인). Each executable
    tranche reduces it, so two ETFs on the same day cannot use the same cash.
    """
    out = []
    cash_left = cash_available
    for r in exec_rows or []:
        if r.get("type") != TYPE_CORE_ETF:
            continue
        ticker = str(r.get("ticker", "")).upper()
        shortfall = r.get("shortfall")
        eligible = shortfall is not None and shortfall > 0
        try:
            df = price_loader(ticker) if price_loader else None
        except Exception:
            df = None
        start = cf.latest_episode_start(df) if isinstance(df, pd.DataFrame) else None
        if start is not None and isinstance(df, pd.DataFrame):
            schedule = cf.tranche_schedule(df.index, start)
        else:
            schedule = []
        fund = (funds or {}).get(ticker)
        executed_nos = store.executed_tranches(tranche_rows, ticker=ticker, episode_start=start) if start else []
        gate = (gate_reader(ticker) if gate_reader else None) or {}
        status = cf.crisis_status(eligible=eligible, episode_start=start, schedule=schedule, today=today,
                                  fund_total=(fund or {}).get("total_krw"), executed_nos=executed_nos,
                                  guard_market=gate.get("market"),
                                  executed_today=store.executed_on(tranche_rows, ticker=ticker, exec_date=today),
                                  cash_available=cash_left)
        if status["state"] == "executable" and cash_left is not None:
            cash_left = max(0.0, cash_left - status["amount"])
        price_note = "가격 미확인" if not isinstance(df, pd.DataFrame) or df.empty else ""
        if not eligible and start is not None:
            status = {**status, "text": "해당 없음 · 목표비중 충족 또는 비중 미확인"}
        out.append({"ticker": ticker, "name": r.get("name", ticker), "episode_start": start, "schedule": schedule,
                    "fund": fund, "executed_nos": executed_nos, "status": status, "price_note": price_note})
    return out


def _fmt(v):
    return "미설정" if v is None else f"{float(v):,.0f}원"


def render_crisis_fund_panel(st, exec_rows, *, store_ctx, gate_reader, price_loader, cash_krw=None):
    client = (store_ctx or {}).get("client")
    owner = (store_ctx or {}).get("owner_email")
    scope = storage_scope((store_ctx or {}).get("accounts"))
    st.markdown("#### 🧯 코어 위기자금 (−40% 도달 후 6회 분할)")
    st.caption("목표비중 미달 코어 ETF가 자기 52주 고가 대비 종가 −40%에 처음 닿으면, 미리 정한 위기자금을 1/6씩 "
               "도달일과 이후 5개월의 첫 거래일에 나눕니다. 시장 가드가 위험·비상이거나 확인되지 않는 날은 회차를 미루고 "
               "풀리는 첫 거래일에 집행합니다. 한 종목은 하루 최대 1회차이며, 밀린 회차가 겹치면 가장 오래된 회차 하나만 "
               "집행하고 나머지는 다음 거래일부터 다시 확인합니다. 종목별 위기자금과 계좌 가용 현금(오늘 월적립 실행가능액 차감 후)을 "
               "함께 확인합니다. 위기자금을 정하지 않은 종목은 후보로만 표시하며 기본 금액은 없습니다. "
               "월적립(PANIC 날 0.5배 포함)과는 별개이며 월적립 게이트를 따로 따릅니다.")
    if client is not None and owner:
        fund_rows, f_status = store.load_scope(client, store.FUNDS, owner_email=owner, account_scope=scope)
        tr_rows, t_status = store.load_scope(client, store.TRANCHES, owner_email=owner, account_scope=scope)
    else:
        fund_rows, f_status, tr_rows, t_status = [], "no_client", [], "no_client"
    if "table_missing" in (f_status, t_status):
        st.warning("위기자금 저장 테이블이 아직 없습니다. 설정·회차 기록은 테이블 생성 후 사용할 수 있습니다.")
        with st.expander("위기자금·매크로 결측 기록 테이블 SQL (Supabase SQL Editor에서 한 번 실행)"):
            from stock_lab_core.db_schema import get_crisis_macro_log_create_sql
            st.code(get_crisis_macro_log_create_sql(), language="sql")
    elif "error" in (f_status, t_status):
        st.warning("위기자금 설정·회차 기록을 읽지 못했습니다. 회차는 미확인으로 표시합니다.")
    funds = store.active_funds(fund_rows) if f_status == "ok" else {}
    today = datetime.now(KST).date()
    monthly_today = sum(float(r.get("executable") or 0.0) for r in exec_rows or [])
    cash_after = None if cash_krw is None else max(0.0, float(cash_krw) - monthly_today)
    rows = build_crisis_rows(exec_rows, price_loader=price_loader, gate_reader=gate_reader, funds=funds,
                             tranche_rows=tr_rows if t_status == "ok" else [], today=today, cash_available=cash_after)
    if not rows:
        st.caption("월적립 대상에 코어 ETF가 없습니다.")
        return rows
    total = sum(float((r["fund"] or {}).get("total_krw") or 0) for r in rows)
    st.dataframe(pd.DataFrame([{
        "자산명": r["name"], "위기자금(종목별)": _fmt((r["fund"] or {}).get("total_krw")),
        "회차당": _fmt(r["status"].get("tranche_amount")) if r["fund"] else "-",
        "집행 회차": f"{len(r['executed_nos'])}/6" if r["episode_start"] is not None else "-",
        "상태": r["price_note"] or r["status"]["text"],
    } for r in rows]), width='stretch', hide_index=True)
    st.caption(f"계좌 위기자금 합계 {total:,.0f}원 (종목별 금액의 합. 한 종목은 자기 금액의 1/6씩만 꺼내므로 여러 종목이 "
               "같은 날 회차를 받아도 합계를 넘지 않습니다.)")
    if client is None or not owner or f_status != "ok" or t_status != "ok":
        return rows
    c1, c2 = st.columns(2)
    with c1.expander("위기자금 설정 (종목별, 새 버전으로 저장)"):
        names = {r["ticker"]: r for r in rows}
        pick = st.selectbox("종목", list(names), format_func=lambda t: f"{names[t]['name']} ({t})",
                            key="crisis_fund_pick")
        amount = st.number_input("위기자금 총액(원)", min_value=0.0, step=100000.0, key=f"crisis_fund_amt_{pick}")
        if st.button("위기자금 저장", key=f"crisis_fund_save_{pick}"):
            status = store.save_fund(client, owner_email=owner, account_scope=scope, ticker=pick, total_krw=amount,
                                     existing=fund_rows)
            msg = {"ok": "위기자금을 저장했습니다.", "invalid": "0보다 큰 금액을 입력하세요."}
            st.session_state["_monthly_execution_flash"] = (status, msg.get(status, f"저장하지 못했습니다: {status}"))
            st.rerun()
    with c2.expander("위기자금 회차 집행 기록 (실제로 매수한 회차만)"):
        due = [r for r in rows if r["status"]["state"] == "executable"]
        if not due:
            st.caption("오늘 실행가능한 회차가 없습니다.")
            return rows
        names = {r["ticker"]: r for r in due}
        pick = st.selectbox("종목", list(names), format_func=lambda t: f"{names[t]['name']} ({t})",
                            key="crisis_exec_pick")
        chosen = names[pick]
        st.caption(chosen["status"]["text"])
        if st.button("회차 집행 기록", key=f"crisis_exec_save_{pick}"):
            status = store.record_tranches(
                client, owner_email=owner, account_scope=scope, ticker=pick, episode_start=chosen["episode_start"].date(),
                tranche_nos=chosen["status"]["due_nos"], exec_date=today.isoformat(),
                amount_per_tranche=chosen["status"]["tranche_amount"],
                fund_version=(chosen["fund"] or {}).get("fund_version"),
                conditions={"status": chosen["status"]["text"]})
            msg = {"ok": "회차 집행을 기록했습니다.", "duplicate": "이미 기록된 회차가 있어 저장하지 않았습니다."}
            st.session_state["_monthly_execution_flash"] = (status, msg.get(status, f"저장하지 못했습니다: {status}"))
            st.rerun()
    return rows


def render_macro_missing_caption(st, exec_rows, *, store_ctx):
    """C-13: this month's recorded macro outages and whether core ETFs still executed this month."""
    client = (store_ctx or {}).get("client")
    owner = (store_ctx or {}).get("owner_email")
    if client is None or not owner:
        return None
    month_key = kst_month_key()
    since = (datetime.now(KST) - timedelta(days=62)).isoformat()
    rows, status = mlog.load_since(client, owner_email=owner, since_iso=since)
    if status != "ok":
        if status == "table_missing":
            st.caption("매크로 결측 기록 테이블이 아직 없어 결측 이력을 표시하지 못합니다.")
        return None
    outages = mlog.month_outages(rows, month_key)
    core_exec = {str(r.get("ticker")): r.get("executed") for r in exec_rows or [] if r.get("type") == TYPE_CORE_ETF}
    text = mlog.outage_summary_text(outages, core_exec)
    st.caption(f"🛰️ {text} (결측·복구 시각은 앱이 상태 변화를 처음 확인한 시각입니다.)")
    return text


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
