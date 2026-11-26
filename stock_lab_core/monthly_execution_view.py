"""Monthly plan / executed / executable panel (C-6/C-11 step 3, 2026-11-26).

Rendered under the monthly calculator. Nothing is written without an explicit click: "이번 달 계획 확정" inserts
a new plan version, "집행 기록" inserts one execution record. Showing ③ never changes ②.
"""
from datetime import datetime

import pandas as pd

from stock_lab_core.formatters import clean_float
from stock_lab_core.monthly_execution import (TYPE_LABELS, KST, active_confirmed_plan, execution_key,
                                              executed_by_ticker, four_amounts, holding_type, kst_month_key,
                                              monthly_gate)
from stock_lab_core import monthly_store


def _fmt(value):
    return "미확인" if value is None else f"{value:,.0f}원"


def _shortfall_krw(row, total_asset):
    target = clean_float(row.get("목표비중"), float("nan"))
    current = clean_float(row.get("현재비중"), float("nan"))
    total = clean_float(total_asset, float("nan"))
    if not all(map(lambda v: v == v, (target, current, total))) or total <= 0:
        return None
    return max(0.0, (target - current) / 100.0 * total)


def build_execution_rows(calc_rows, holdings_table, *, total_asset, cash_krw, gate_reader, decisions,
                         confirmed, executed, executed_status):
    """Pure assembly of the four amounts per ticker (also used by tests)."""
    by_ticker = {}
    if isinstance(holdings_table, pd.DataFrame) and "티커" in holdings_table:
        by_ticker = {str(r.get("티커", "")).upper(): r for _, r in holdings_table.iterrows()}
    cash_left = cash_krw
    out = []
    for r in calc_rows:
        ticker = str(r.get("ticker", "")).upper()
        htype = holding_type(r.get("bucket"), r.get("is_etf"))
        conf = confirmed.get(ticker)
        if conf is not None:
            plan_krw, plan_src, version = float(conf.get("plan_krw") or 0.0), f"확정 v{conf.get('plan_version')}", conf.get("plan_version")
        elif r.get("signal_unknown"):
            plan_krw, plan_src, version = None, "신호 미확인", None
        else:
            plan_krw, plan_src, version = float(r.get("final_alloc") or 0.0), "임시(미확정)", None
        gate = (gate_reader(ticker) if gate_reader else None) or {}
        allowed, gate_text = monthly_gate(htype, gate.get("state"), gate.get("reason"))
        if r.get("signal_unknown") and conf is not None:
            allowed, gate_text = False, "신호 미확인 · 데이터확인 (확정 계획은 보존, 신호 복구 후 재평가)"
        exec_amt = executed.get(ticker, 0.0) if executed_status == "ok" else None
        amounts = four_amounts(plan_krw=plan_krw, executed_krw=exec_amt,
                               shortfall_krw=_shortfall_krw(by_ticker.get(ticker, {}), total_asset),
                               gate_allowed=allowed, sizing=gate.get("sizing"), cash_krw=cash_left)
        if amounts["executable"] is not None and cash_left is not None:
            cash_left = max(0.0, cash_left - amounts["executable"])
        out.append({"ticker": ticker, "name": r.get("name", ticker), "type": htype, "plan_src": plan_src,
                    "plan_version": version, "gate_text": gate_text, "signal_key": gate.get("signal_key"),
                    "decision_code": (decisions.get(ticker) or {}).get("decision_code"), **amounts})
    return out


def render_monthly_execution_panel(st, plan, holdings_table, *, total_asset, cash_krw, gate_reader, decisions,
                                   store):
    """store: {"client", "owner_email", "accounts"} or None (demo / no client: plan 임시, executed 미확인)."""
    month_key = kst_month_key()
    scope = monthly_store.storage_scope((store or {}).get("accounts"))
    client = (store or {}).get("client")
    owner = (store or {}).get("owner_email")
    if client is not None and owner:
        plan_rows, plan_status = monthly_store.load_month(client, monthly_store.PLANS, owner_email=owner,
                                                          account_scope=scope, month_key=month_key)
        exec_rows, exec_status = monthly_store.load_month(client, monthly_store.EXECUTIONS, owner_email=owner,
                                                          account_scope=scope, month_key=month_key)
    else:
        plan_rows, plan_status, exec_rows, exec_status = [], "no_client", [], "no_client"
    confirmed = active_confirmed_plan(plan_rows, account_scope=scope, month_key=month_key) if plan_status == "ok" else {}
    executed = executed_by_ticker(exec_rows, account_scope=scope, month_key=month_key)
    rows = build_execution_rows(plan["rows"], holdings_table, total_asset=total_asset, cash_krw=cash_krw,
                                gate_reader=gate_reader, decisions=decisions, confirmed=confirmed,
                                executed=executed, executed_status=exec_status)

    st.markdown("#### 🧾 이번 달 계획 · 집행 · 오늘 실행가능")
    flash = st.session_state.pop("_monthly_execution_flash", None)
    if flash:
        (st.success if flash[0] == "ok" else st.warning)(flash[1])
    st.caption(f"{month_key} (KST) · 계좌 범위 {scope} · ① 계획 ② 이번 달 집행 ③ 오늘 실행가능 ④ 오늘 이후 남은 대기. "
               "③은 계획 잔액·목표비중 부족분·월적립 게이트·정찰 1/3·가용 현금 중 가장 작은 값이며, 표시만으로 ②가 늘지 않습니다. "
               "코어 ETF의 상위 시간대 추세훼손 예외는 비교 검토 후 적용 예정이라 아직 반영하지 않았습니다.")
    if plan_status == "table_missing" or exec_status == "table_missing":
        st.warning("월적립 계획·집행 저장 테이블이 아직 없습니다. 계획은 임시 계산이고 집행은 미확인입니다.")
        with st.expander("월적립 계획·집행 저장 테이블 SQL (Supabase SQL Editor에서 한 번 실행)"):
            from stock_lab_core.db_schema import get_monthly_dca_create_sql
            st.code(get_monthly_dca_create_sql(), language="sql")
    elif plan_status == "error" or exec_status == "error":
        st.warning("저장된 계획·집행 기록을 읽지 못했습니다. 집행은 미확인으로 표시합니다.")
    st.dataframe(pd.DataFrame([{
        "자산명": r["name"], "유형": TYPE_LABELS.get(r["type"], r["type"]), "① 계획": _fmt(r["plan"]),
        "계획 출처": r["plan_src"], "② 집행": _fmt(r["executed"]), "③ 오늘 실행가능": _fmt(r["executable"]),
        "④ 남은 대기": _fmt(r["remaining"]), "제한": r["limit"] or "-", "월적립 게이트": r["gate_text"],
    } for r in rows]), width='stretch', hide_index=True)

    if client is None or not owner or plan_status != "ok" or exec_status != "ok":
        return rows
    c1, c2 = st.columns(2)
    label = "이번 달 계획 확정" if not confirmed else "이번 달 계획 다시 확정(새 버전, 이전 버전은 기록으로 보존)"
    if c1.button(label, key=f"monthly_plan_confirm_{month_key}"):
        n, status = monthly_store.confirm_plan(client, owner_email=owner, account_scope=scope, month_key=month_key,
                                               rows=[dict(r, holding_type=holding_type(r.get("bucket"), r.get("is_etf")),
                                                          decision_code=(decisions.get(str(r.get("ticker", "")).upper()) or {}).get("decision_code"))
                                                     for r in plan["rows"]],
                                               existing=plan_rows)
        msg = {"ok": f"이번 달 계획을 확정했습니다({n}종목).", "nothing": "확정할 종목이 없습니다(신호 미확인 종목은 확정하지 않음)."}
        st.session_state["_monthly_execution_flash"] = (status, msg.get(status, f"계획을 확정하지 못했습니다: {status}"))
        st.rerun()
    with c2.expander("집행 기록 (실제로 매수한 금액만)"):
        options = [r for r in rows if r["plan"] is not None and r["executed"] is not None and r["plan"] - r["executed"] > 0]
        if not options:
            st.caption("기록할 수 있는 계획 잔액이 없습니다.")
            return rows
        names = {r["ticker"]: r for r in options}
        pick = st.selectbox("종목", list(names), format_func=lambda t: f"{names[t]['name']} ({t})",
                            key=f"monthly_exec_pick_{month_key}")
        chosen = names[pick]
        open_amt = chosen["plan"] - chosen["executed"]
        amount = st.number_input("집행 금액(원)", min_value=0.0, max_value=float(open_amt), step=10000.0,
                                 value=float(min(open_amt, chosen["executable"] or 0.0)),
                                 key=f"monthly_exec_amt_{month_key}_{pick}")
        if chosen["executable"] is not None and amount > chosen["executable"]:
            st.caption("오늘 실행가능 금액보다 큽니다. 실제로 매수한 금액만 기록하세요.")
        if st.button("집행 기록", key=f"monthly_exec_save_{month_key}_{pick}"):
            today = datetime.now(KST).date().isoformat()
            key = execution_key(account_scope=scope, month_key=month_key, ticker=pick, exec_date=today,
                                signal_key=chosen.get("signal_key"))
            status = monthly_store.record_execution(
                client, owner_email=owner, account_scope=scope, month_key=month_key, ticker=pick, exec_date=today,
                amount_krw=amount, plan_version=chosen.get("plan_version"), exec_key=key,
                conditions={"gate": chosen["gate_text"], "limit": chosen["limit"], "executable": chosen["executable"],
                            "decision_code": chosen.get("decision_code"), "plan_src": chosen["plan_src"]})
            msg = {"ok": "집행 기록을 저장했습니다.", "duplicate": "같은 신호의 오늘 집행 기록이 이미 있어 저장하지 않았습니다."}
            st.session_state["_monthly_execution_flash"] = (status, msg.get(status, f"저장하지 못했습니다: {status}"))
            st.rerun()
    return rows


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
