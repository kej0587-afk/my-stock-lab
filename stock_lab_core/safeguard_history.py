"""Retain evidenced market halts in existing owner-bound report snapshots."""

from copy import deepcopy
from datetime import date

import pandas as pd

from stock_lab_core.report_evidence import KST, number, safe_link
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.release_calendar import _clock

register_loaded_source(__name__, __file__)


def observed_kr_sessions(context):
    """Use observed index sessions, not weekdays pretending to be trading days."""
    days = set()
    for ticker in ("^KS11", "^KQ11"):
        frame = context.get("price_frames", {}).get(ticker)
        if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.DatetimeIndex):
            continue
        values = frame.get("Close")
        if not isinstance(values, pd.Series):
            continue
        valid = values.map(lambda value: number(value) is not None and number(value) > 0)
        index = frame.index[valid]
        if index.tz is not None:
            index = index.tz_convert("Asia/Seoul")
        days.update(index.strftime("%Y-%m-%d"))
    active = context.get("current_news_sessions", {}).get("KR", {})
    if active.get("is_active") and active.get("date"):
        days.add(active["date"])
    return sorted(days)


def _valid(event, today):
    if not isinstance(event, dict):
        return False
    try:
        day = date.fromisoformat(event.get("date", ""))
    except (ValueError, TypeError):
        return False
    return (day <= today and event.get("market") in {"KOSPI", "KOSDAQ"}
            and event.get("kind") in {"sidecar", "circuit_breaker"}
            and event.get("direction") in {"buy", "sell", "down", "unknown"}
            and event.get("status") in {"official", "reported"}
            and bool(safe_link(event.get("source_url"))))


def _sources(event):
    values = event.get("sources")
    if not isinstance(values, list):
        values = [event]
    return [{key: row.get(key, "") for key in ("source", "source_url", "published_at", "status")}
            for row in values[:8] if isinstance(row, dict) and safe_link(row.get("source_url"))] or [
                {key: event.get(key, "") for key in ("source", "source_url", "published_at", "status")}]


def merge_safeguard_history(current, saved, session_days, now, *, retain_without_calendar=False):
    """Keep the latest five observed KR sessions, retaining evidence provenance."""
    today = _clock(now).astimezone(KST).date()
    days = []
    for value in session_days or []:
        try:
            day = date.fromisoformat(value)
        except (ValueError, TypeError):
            continue
        if day <= today:
            days.append(day.isoformat())
    recent = set(sorted(set(days))[-5:])
    preserve_unverified = retain_without_calendar and len(recent) < 5
    fresh = [row for row in current or [] if _valid(row, today)]
    # Partial session data cannot establish that an older event has expired.
    old = [row for row in saved or [] if _valid(row, today) and
           (row["date"] in recent or preserve_unverified)]
    grouped = {}
    for retained, rows in ((True, old), (False, fresh)):
        for event in rows:
            if recent and event["date"] not in recent and not preserve_unverified:
                continue
            key = tuple(event[k] for k in ("market", "kind", "direction", "date"))
            prior = grouped.get(key)
            item = deepcopy(event)
            item["sources"] = _sources(event)
            item["retained_from_history"] = retained
            if prior:
                if prior.get("status") == "official" and item.get("status") != "official":
                    item = deepcopy(prior)
                    item["retained_from_history"] = retained
                sources = _sources(prior) + _sources(event)
                item["sources"] = list({s.get("source_url"): {k: s.get(k, "") for k in ("source", "source_url")}
                                        for s in sources if isinstance(s, dict) and safe_link(s.get("source_url"))}.values())[:8]
            grouped[key] = item
    return sorted(grouped.values(), key=lambda row: (row["date"], row["market"]), reverse=True)[:32]
