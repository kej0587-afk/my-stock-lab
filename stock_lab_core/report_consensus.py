"""Attach exact-release expectations without replacing official observations."""

from copy import deepcopy
import json
from pathlib import Path

from stock_lab_core.economic_consensus import consensus_key, load_economic_consensus
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import number, stamp

register_loaded_source(__name__, __file__)

VERIFIED_PATH = Path(__file__).with_name("data") / "verified_consensus_20261021.json"
FORECAST_FIELDS = ("forecast", "forecast_unit", "forecast_basis", "forecast_source", "forecast_source_url",
                   "forecast_kind", "forecast_verified_at", "forecast_period")


def _verified_events(rows, now):
    payload = json.loads(VERIFIED_PATH.read_text(encoding="utf-8"))
    if now.date().isoformat() < payload["verified_at"]:
        return [], 0
    events, revisions = [], 0
    for fact in payload["events"]:
        source = payload["sources"][fact["source_id"]]
        target = next((row for row in rows if all(row.get(key) == fact[key] for key in ("indicator", "period", "basis", "unit"))), None)
        if target is None or stamp(source["published_at"]) > now:
            continue
        actual = number(target.get("actual"))
        if actual is not None and abs(actual - fact["actual_at_release"]) > 1e-6:
            revisions += 1
            continue
        candidate = dict(fact)
        if not target.get("release_at"):
            # Verified report states this release date, not an invented time.
            target.update(release_at=fact["release_at"], release_precision="date",
                          release_source=source["name"] + " (publication-day verification)",
                          release_source_url=source["url"])
            target["missing_reason"] = ";".join(reason for reason in target.get("missing_reason", "").split(";")
                                                       if reason and reason != "release_date_unavailable")
        if consensus_key(target) != consensus_key(candidate):
            continue
        candidate.update(forecast_unit=fact["unit"], forecast_basis=fact["basis"],
                         forecast_period=fact["period"], forecast_source="Reuters 발표 당시 설문(기사 확인)",
                         forecast_source_url=source["url"], forecast_kind="verified_historical_survey",
                         forecast_verified_at=payload["verified_at"])
        events.append(candidate)
    return events, revisions


def attach_economic_consensus(release_rows, now, *, api_key="", fetch=None):
    rows = deepcopy(release_rows)
    historical, revisions = _verified_events(rows, now)
    live = load_economic_consensus(rows, now=now, api_key=api_key, fetch=fetch)
    # Prefer an explicitly supplied forecast; the dated survey is only a fallback.
    events = {consensus_key(event): event for event in historical}
    events.update({consensus_key(event): event for event in live["events"]})
    matched = 0
    for row in rows:
        event = events.get(consensus_key(row))
        if row.get("forecast") is not None or not event:
            continue
        row.update({field: event[field] for field in FORECAST_FIELDS if field in event})
        row["missing_reason"] = ";".join(reason for reason in row.get("missing_reason", "").split(";")
                                             if reason and reason not in {"forecast_not_supplied", "forecast_source_unavailable"})
        actual, forecast = number(row.get("actual")), number(row.get("forecast"))
        row["actual_minus_forecast"] = round(actual - forecast, 6) if actual is not None and forecast is not None else None
        matched += 1
    diagnostics = dict(live["diagnostics"], attached_count=matched, verified_survey_count=len(historical),
                       revised_actual_excluded=revisions, verified_survey_coverage="2026-09 발표 당시 설문 · 사후 기사 검증(10/21)")
    return rows, diagnostics
