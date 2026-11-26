"""C-13 tracking (2026-11-26): when core macro data went missing and came back, and whether the month still
executed. Policy is unchanged (missing macro = 데이터확인). Rows are written only when the observed status
changes (missing <-> complete), so viewing or refreshing does not add rows while the status stays the same.
Times are when the app observed the change (an app run), not the data vendor's exact outage window.
"""
import logging
from datetime import datetime, timedelta, timezone

EVENTS = "macro_status_events"
KST = timezone(timedelta(hours=9))
MISSING, COMPLETE = "missing", "complete"


def observed_status(macro_status):
    status = str((macro_status or {}).get("macro_data_status") or "")
    if not status:
        return None
    return COMPLETE if status == "complete" else MISSING


def needs_record(last_status, current_status):
    """Record a change only. The very first observation is recorded only when it is missing."""
    if current_status not in (MISSING, COMPLETE):
        return False
    if last_status is None:
        return current_status == MISSING
    return last_status != current_status


def _table_missing(exc):
    text = str(exc)
    return EVENTS in text and ("does not exist" in text or "PGRST205" in text or "schema cache" in text)


def load_latest(client, *, owner_email):
    try:
        res = (client.table(EVENTS).select("status,observed_at").eq("owner_email", owner_email)
               .order("observed_at", desc=True).limit(1).execute())
        rows = list(getattr(res, "data", None) or [])
        return (rows[0].get("status") if rows else None), "ok"
    except Exception as exc:
        return None, ("table_missing" if _table_missing(exc) else "error")


def load_since(client, *, owner_email, since_iso):
    try:
        res = (client.table(EVENTS).select("*").eq("owner_email", owner_email).gte("observed_at", since_iso)
               .order("observed_at").execute())
        return list(getattr(res, "data", None) or []), "ok"
    except Exception as exc:
        if _table_missing(exc):
            return [], "table_missing"
        logging.warning("macro status log read failed: %s", exc)
        return [], "error"


def record(client, *, owner_email, status, missing_components, source="app"):
    try:
        client.table(EVENTS).insert({"owner_email": owner_email, "status": status,
                                     "missing_components": ", ".join(missing_components or ()),
                                     "source": source}).execute()
        return "ok"
    except Exception as exc:
        if _table_missing(exc):
            return "table_missing"
        logging.warning("macro status log write failed: %s", exc)
        return "error"


def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(KST)
    except Exception:
        return None


def month_outages(rows, month_key, now=None, prior_status=None):
    """Outages that overlap the KST month: [{"start", "end" (None = ongoing), "components", "hours"}].

    rows: events sorted or not (status, observed_at, missing_components). prior_status: status before the first row.
    """
    now = now or datetime.now(KST)
    events = sorted(((t, r) for r in rows or [] for t in [_ts(r.get("observed_at"))] if t), key=lambda x: x[0])
    out, cur = [], None
    if prior_status == MISSING:
        cur = {"start": None, "components": set()}
    for t, r in events:
        if r.get("status") == MISSING and cur is None:
            cur = {"start": t, "components": set()}
        if r.get("status") == MISSING and cur is not None:
            cur["components"].update(x.strip() for x in str(r.get("missing_components") or "").split(",") if x.strip())
        if r.get("status") == COMPLETE and cur is not None:
            out.append({**cur, "end": t}); cur = None
    if cur is not None:
        out.append({**cur, "end": None})
    result = []
    for o in out:
        start, end = o["start"], o["end"]
        key_start = (start or now).strftime("%Y-%m")
        key_end = (end or now).strftime("%Y-%m")
        if not (key_start <= month_key <= key_end):
            continue
        hours = ((end or now) - start).total_seconds() / 3600 if start else None
        result.append({"start": start, "end": end, "components": sorted(o["components"]), "hours": hours})
    return result


def outage_summary_text(outages, core_exec):
    """One caption line. core_exec: {ticker: executed amount or None (미확인)} for core ETFs this month."""
    if not outages:
        head = "이번 달 기록된 매크로 결측 없음"
    else:
        parts = []
        for o in outages:
            s = o["start"].strftime("%m-%d %H:%M") if o["start"] else "이전 달부터"
            e = o["end"].strftime("%m-%d %H:%M") if o["end"] else "진행 중"
            comp = ", ".join(o["components"]) or "항목 미확인"
            parts.append(f"{s}~{e} ({comp})")
        head = f"이번 달 매크로 결측 {len(outages)}회: " + "; ".join(parts)
    if core_exec:
        ex = ", ".join(f"{t} {'집행 있음' if (v or 0) > 0 else ('미확인' if v is None else '집행 없음')}"
                       for t, v in core_exec.items())
        head += f" · 코어 ETF 이번 달 집행: {ex}"
    return head


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
