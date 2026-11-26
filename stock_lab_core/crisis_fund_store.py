"""Supabase storage for C-8 crisis fund settings and tranche records (2026-11-26).

Insert-only like the monthly store: a new fund amount adds fund_version + 1 (latest is active); a tranche record
is unique per exec_key (scope|ticker|episode start|tranche no), so the same tranche cannot be recorded twice.
Reads return (rows, status); on anything but "ok" the caller shows 미확인, never 0.
"""
import logging

from stock_lab_core.crisis_fund import POLICY_VERSION

FUNDS = "crisis_fund_plans"
TRANCHES = "crisis_fund_executions"


def _table_missing(exc):
    text = str(exc)
    return "crisis_fund" in text and ("does not exist" in text or "PGRST205" in text or "schema cache" in text)


def _duplicate(exc):
    text = str(exc)
    return "23505" in text or "duplicate key" in text


def load_scope(client, table, *, owner_email, account_scope):
    try:
        res = client.table(table).select("*").eq("owner_email", owner_email).eq("account_scope", account_scope).execute()
        return list(getattr(res, "data", None) or []), "ok"
    except Exception as exc:
        if _table_missing(exc):
            return [], "table_missing"
        logging.warning("crisis fund read failed (%s): %s", table, exc)
        return [], "error"


def active_funds(rows):
    """{TICKER: row} with the highest fund_version per ticker."""
    best = {}
    for row in rows or []:
        key = str(row.get("ticker", "")).upper()
        if key and int(row.get("fund_version") or 0) >= int((best.get(key) or {}).get("fund_version") or 0):
            best[key] = row
    return best


def executed_tranches(rows, *, ticker, episode_start):
    start = str(episode_start)[:10]
    return sorted({int(r.get("tranche_no")) for r in rows or []
                   if str(r.get("ticker", "")).upper() == str(ticker).upper() and str(r.get("episode_start"))[:10] == start})


def executed_on(rows, *, ticker, exec_date):
    """True when a tranche of this ticker was recorded on exec_date (one tranche per ticker per day)."""
    day = str(exec_date)[:10]
    return any(str(r.get("ticker", "")).upper() == str(ticker).upper() and str(r.get("exec_date"))[:10] == day
               for r in rows or [])


def tranche_key(account_scope, ticker, episode_start, tranche_no):
    return f"{account_scope}|{str(ticker).upper()}|{str(episode_start)[:10]}|{int(tranche_no)}"


def save_fund(client, *, owner_email, account_scope, ticker, total_krw, existing):
    try:
        total = float(total_krw)
    except (TypeError, ValueError):
        return "invalid"
    if not total > 0:
        return "invalid"
    version = int((active_funds(existing).get(str(ticker).upper()) or {}).get("fund_version") or 0) + 1
    try:
        client.table(FUNDS).insert({"owner_email": owner_email, "account_scope": account_scope,
                                    "ticker": str(ticker).upper(), "fund_version": version,
                                    "total_krw": round(total, 0), "policy_version": POLICY_VERSION}).execute()
        return "ok"
    except Exception as exc:
        if _table_missing(exc):
            return "table_missing"
        if _duplicate(exc):
            return "duplicate"
        logging.warning("crisis fund save failed: %s", exc)
        return "error"


def record_tranches(client, *, owner_email, account_scope, ticker, episode_start, tranche_nos, exec_date,
                    amount_per_tranche, fund_version, conditions=None):
    """One row per tranche number. Returns "ok", "duplicate" (some already recorded), "table_missing" or "error"."""
    if not tranche_nos or not (amount_per_tranche and float(amount_per_tranche) > 0):
        return "invalid"
    payload = [{"owner_email": owner_email, "account_scope": account_scope, "ticker": str(ticker).upper(),
                "episode_start": str(episode_start)[:10], "tranche_no": int(n), "exec_date": str(exec_date),
                "amount_krw": round(float(amount_per_tranche), 0), "fund_version": fund_version,
                "exec_key": tranche_key(account_scope, ticker, episode_start, n), "conditions": conditions or {},
                "policy_version": POLICY_VERSION} for n in tranche_nos]
    try:
        client.table(TRANCHES).insert(payload).execute()
        return "ok"
    except Exception as exc:
        if _table_missing(exc):
            return "table_missing"
        if _duplicate(exc):
            return "duplicate"
        logging.warning("crisis tranche record failed: %s", exc)
        return "error"


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
