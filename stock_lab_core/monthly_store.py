"""Supabase storage for confirmed monthly plans and execution records (C-6/C-11 step 3, 2026-11-26).

The client is passed in (no Streamlit here). Reads return (rows, status): status is "ok", "table_missing" or
"error"; on anything but "ok" the caller treats plan/executed as 미확인, never 0. Writes are insert-only:
re-confirming a plan adds a new plan_version; an execution with an existing exec_key is refused (duplicate).
"""
import logging

from stock_lab_core.monthly_execution import POLICY_VERSION

PLANS = "monthly_dca_plans"
EXECUTIONS = "monthly_dca_executions"


def storage_scope(accounts):
    """Stable account scope for storage: the selected account set (not holdings or cash, which change on a buy)."""
    names = sorted({str(a).strip() for a in (accounts or []) if str(a).strip()})
    return "|".join(names) if names else "미확인"


def _table_missing(exc):
    text = str(exc)
    return ("monthly_dca" in text and ("does not exist" in text or "PGRST205" in text or "schema cache" in text))


def _duplicate(exc):
    text = str(exc)
    return "23505" in text or "duplicate key" in text


def load_month(client, table, *, owner_email, account_scope, month_key):
    try:
        res = (client.table(table).select("*").eq("owner_email", owner_email).eq("account_scope", account_scope)
               .eq("month_key", month_key).execute())
        return list(getattr(res, "data", None) or []), "ok"
    except Exception as exc:
        if _table_missing(exc):
            return [], "table_missing"
        logging.warning("monthly store read failed (%s): %s", table, exc)
        return [], "error"


def confirm_plan(client, *, owner_email, account_scope, month_key, rows, existing):
    """Insert plan_version = latest + 1 for each known-signal row. Unknown-signal rows are not confirmed."""
    latest = {}
    for row in existing or []:
        key = str(row.get("ticker", "")).upper()
        latest[key] = max(latest.get(key, 0), int(row.get("plan_version") or 0))
    payload = []
    for r in rows:
        if r.get("signal_unknown"):
            continue
        ticker = str(r.get("ticker", "")).upper()
        payload.append({
            "owner_email": owner_email, "account_scope": account_scope, "account_label": account_scope,
            "month_key": month_key, "ticker": ticker, "holding_type": r.get("holding_type", ""),
            "plan_version": latest.get(ticker, 0) + 1, "plan_krw": round(float(r.get("final_alloc") or 0.0), 0),
            "multiplier": float(r.get("multiplier") or 0.0), "decision_code": r.get("decision_code"),
            "signal_label": str(r.get("tap_raw", ""))[:200], "policy_version": POLICY_VERSION,
        })
    if not payload:
        return 0, "nothing"
    try:
        client.table(PLANS).insert(payload).execute()
        return len(payload), "ok"
    except Exception as exc:
        if _table_missing(exc):
            return 0, "table_missing"
        if _duplicate(exc):
            return 0, "duplicate"
        logging.warning("monthly plan confirm failed: %s", exc)
        return 0, "error"


def record_execution(client, *, owner_email, account_scope, month_key, ticker, exec_date, amount_krw,
                     plan_version, exec_key, conditions):
    if not (amount_krw and float(amount_krw) > 0):
        return "invalid"
    try:
        client.table(EXECUTIONS).insert({
            "owner_email": owner_email, "account_scope": account_scope, "month_key": month_key,
            "ticker": str(ticker).upper(), "exec_date": str(exec_date), "amount_krw": round(float(amount_krw), 0),
            "plan_version": plan_version, "exec_key": exec_key, "conditions": conditions or {},
            "policy_version": POLICY_VERSION,
        }).execute()
        return "ok"
    except Exception as exc:
        if _table_missing(exc):
            return "table_missing"
        if _duplicate(exc):
            return "duplicate"
        logging.warning("monthly execution record failed: %s", exc)
        return "error"


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
