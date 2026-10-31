"""Conservative SEC companyfacts periods, without enrichment or I/O.

Only us-gaap 10-K/10-Q facts (including amendments) are supported. Fiscal
origins come from actual annual/6-/9-month revenue spans, or the day after an
observed annual end. Filing fy/fp labels never identify an economic period.
Inclusive duration windows allow ordinary 52/53-week years: quarters 70-110,
half-years 150-210, nine months 240-300, annual years 330-385 days. Transitional
or ambiguous periods are held back rather than relabelled.

Records retain actual dates, currency and per-field provenance. fiscal_year is
the observed annual end's calendar year, not the filing's fy label; it is None
until that annual end is observed. fiscal_year_start is the stable identifier.
No list slicing is used to select recent data; the caller may slice sorted
outputs. An oversized field is withheld in full, never truncated by row order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math


MAX_FACTS_PER_FIELD = 20_000
_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
_WINDOWS = ((70, 110), (150, 210), (240, 300), (330, 385))


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        result = date.fromisoformat(value)
        return result if result.isoformat() == value else None
    except ValueError:
        return None


def _finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _quarter_span(start, end):
    if start is None:
        return None
    days = (end - start).days + 1
    return next((q for q, (low, high) in enumerate(_WINDOWS, 1) if low <= days <= high), None)


@dataclass(frozen=True)
class _Fact:
    start: date | None
    end: date
    value: int | float
    tag: str
    unit: str
    filed: date | None
    accession: str
    form: str


def _field_index(namespace, names):
    index, count = {}, 0
    if not isinstance(names, (list, tuple)):
        return index
    # Candidate groups retain the caller's explicit concept preference order.
    for tag in dict.fromkeys(name for name in names if isinstance(name, str)):
        concept = namespace.get(tag, {})
        units = concept.get("units", {}) if isinstance(concept, dict) else {}
        if not isinstance(units, dict):
            continue
        for unit, rows in units.items():
            if not isinstance(unit, str) or not unit or not isinstance(rows, list):
                continue
            count += len(rows)
            if count > MAX_FACTS_PER_FIELD:
                return {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                form = row.get("form")
                if not isinstance(form, str) or form not in _FORMS:
                    continue
                end, start = _date(row.get("end")), _date(row.get("start"))
                if end is None or not _finite(row.get("val")):
                    continue
                if row.get("start") is not None and (start is None or start > end):
                    continue
                fact = _Fact(start, end, row["val"], tag, unit, _date(row.get("filed")),
                             str(row.get("accn") or ""), row["form"])
                index.setdefault((start, end), []).append(fact)
    return index


def _pick(candidates, required_tag=None):
    if not candidates:
        return None
    tag = required_tag if required_tag is not None else candidates[0].tag
    candidates = [fact for fact in candidates if fact.tag == tag]
    if not candidates or len({f.unit for f in candidates}) != 1:
        return None
    if all(f.filed is not None for f in candidates):
        latest = max(f.filed for f in candidates)
        candidates = [f for f in candidates if f.filed == latest]
    if len({f.value for f in candidates}) != 1:
        return None
    return min(candidates, key=lambda f: (str(f.filed or ""), f.accession, f.form))


def _source(fact):
    return {"start": fact.start.isoformat() if fact.start else None,
            "end": fact.end.isoformat(), "value": fact.value, "tag": fact.tag,
            "unit": fact.unit, "filed": fact.filed.isoformat() if fact.filed else None,
            "accession": fact.accession, "form": fact.form}


def _at(index, start, end, unit):
    return [fact for fact in index.get((start, end), ()) if fact.unit == unit]


def _record(indices, flow_fields, origin, end, quarter, ends, anchor, revenue_quarters, annual=False):
    previous_end = ends.get(quarter - 1) if quarter > 1 else None
    start = origin if annual or quarter == 1 else previous_end + timedelta(days=1) if previous_end else None
    if start is None:
        # A directly reported revenue quarter may prove its own start even
        # when the preceding cumulative revenue anchor is unavailable.
        starts = {s for s, facts in revenue_quarters.get(end, {}).items()
                  if s > origin
                  and _pick([f for f in facts if f.unit == anchor.unit]) is not None}
        if len(starts) != 1:
            return None
        start = starts.pop()
    if not annual and _quarter_span(start, end) != 1:
        return None
    annual_end = ends.get(4)
    record = {"period": "annual" if annual else "quarter", "date": end.isoformat(),
              "start": start.isoformat(), "end": end.isoformat(),
              "fiscal_year_start": origin.isoformat(),
              "fiscal_year": str(annual_end.year) if annual_end else None,
              "fiscal_quarter": quarter, "unit": anchor.unit,
              "is_cumulative_ytd": annual, "is_single_quarter": not annual, "provenance": {}}
    for field, index in indices.items():
        field_start = start if field in flow_fields else None
        direct = _at(index, field_start, end, anchor.unit)
        fact = _pick(direct)
        value = fact.value if fact else None
        provenance = {"method": "reported", "facts": [_source(fact)]} if fact else {"status": "missing_or_ambiguous"}
        if not direct and field in flow_fields and not annual and previous_end:
            current = _pick(_at(index, origin, end, anchor.unit))
            previous = (_pick(_at(index, origin, previous_end, anchor.unit), required_tag=current.tag)
                        if current else None)
            if (current and previous and current.tag == previous.tag
                    and _quarter_span(origin, previous_end) == quarter - 1
                    and _quarter_span(origin, end) == quarter):
                difference = current.value - previous.value
                if _finite(difference):
                    value = difference
                    provenance = {"method": "cumulative_difference",
                                  "facts": [_source(current), _source(previous)]}
        record[field] = value
        record["provenance"][field] = provenance
    return record


def _unique_ends(records):
    by_end = {}
    for record in records:
        by_end.setdefault(record["date"], []).append(record)
    return [rows[0] for _, rows in sorted(by_end.items()) if len(rows) == 1]


def build_sec_statement_records(company_facts, tags, flow_fields):
    """Return chronologically sorted (annual, quarter) RAW record lists.

    tags maps output field names to ordered SEC us-gaap concept preferences;
    revenue must be a flow field. The first present concept wins; conflicts in
    that concept do not fall through to another. Latest filings are considered
    only within that concept. A field is None if its exact period/currency is absent
    or ambiguous. Direct quarter facts take precedence over cumulative
    differences. Differences require adjacent observed revenue periods and the
    same fiscal start, account tag and unit. Instant facts are never subtracted.
    Inputs are not mutated. Parent code owns enrichment, scoring and caching.
    """
    if not isinstance(company_facts, dict) or not isinstance(tags, dict):
        return [], []
    flow_fields = set(flow_fields or ())
    if "revenue" not in tags or "revenue" not in flow_fields:
        return [], []
    facts = company_facts.get("facts", {})
    namespace = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
    if not isinstance(namespace, dict):
        return [], []
    indices = {field: _field_index(namespace, names) for field, names in tags.items()}
    spans, origins, revenue_quarters = {}, set(), {}
    for (start, end), candidates in indices["revenue"].items():
        quarter = _quarter_span(start, end)
        if quarter is None or quarter == 4 and not any(f.form.startswith("10-K") for f in candidates):
            continue
        if quarter == 1:
            revenue_quarters.setdefault(end, {})[start] = candidates
        spans.setdefault(start, {}).setdefault(quarter, set()).add(end)
        if quarter >= 2:
            origins.add(start)
    for start in list(origins):
        annual_ends = spans[start].get(4, set())
        if len(annual_ends) == 1:
            annual_end = next(iter(annual_ends))
            if annual_end < date.max:
                origins.add(annual_end + timedelta(days=1))
    annual_records, quarter_records = [], []
    for origin in sorted(origins):
        ends = {q: next(iter(values)) for q, values in spans.get(origin, {}).items() if len(values) == 1}
        for quarter, end in sorted(ends.items()):
            anchor = _pick(indices["revenue"][(origin, end)])
            if anchor is None:
                continue
            if quarter == 4:
                annual_records.append(_record(indices, flow_fields, origin, end, 4, ends, anchor, revenue_quarters, annual=True))
            record = _record(indices, flow_fields, origin, end, quarter, ends, anchor, revenue_quarters)
            if record is not None:
                quarter_records.append(record)
    return _unique_ends(annual_records), _unique_ends(quarter_records)
