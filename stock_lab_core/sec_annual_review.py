"""Read-only US-GAAP 20-F annual evidence; no scoring, network or app imports.

Currency and cutoff are explicit. Dates identify periods, never filing fy/fp.
An exhibit-only amendment cannot remove earlier financial facts. Field-level
provenance and comparability warnings are retained; quarters are never inferred.
"""

import re

from stock_lab_core.sec_financial_periods import (
    MAX_FACTS_PER_FIELD, _Fact, _date, _finite, _pick, _source,
)

FORMS = frozenset({"20-F", "20-F/A"})
SCOPE_TAGS = {
    "ocf_continuing": ["NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "ocf_discontinued": ["CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations"],
    "net_income_continuing": ["IncomeLossFromContinuingOperations"],
    "net_income_discontinued": ["IncomeLossFromDiscontinuedOperationsNetOfTax"],
}


def _cik(value):
    text = str(value)
    return text.zfill(10) if re.fullmatch(r"[0-9]{1,10}", text) else None


def _index(namespace, names, *, currency, cutoff, flow):
    index, count = {}, 0
    for tag in dict.fromkeys(names):
        concept = namespace.get(tag, {})
        units = concept.get("units", {}) if isinstance(concept, dict) else {}
        if not isinstance(units, dict):
            continue
        rows = units.get(currency, [])
        if not isinstance(rows, list):
            continue
        count += len(rows)
        if count > MAX_FACTS_PER_FIELD:
            return {}, "field_limit"
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("form"), str) or row["form"] not in FORMS:
                continue
            start, end, filed = (_date(row.get(k)) for k in ("start", "end", "filed"))
            if end is None or filed is None or not end <= filed <= cutoff or not _finite(row.get("val")):
                continue
            if flow:
                if start is None or not 330 <= (end - start).days + 1 <= 385:
                    continue
            elif row.get("start") is not None:
                continue
            accession = row.get("accn")
            if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
                continue
            fact = _Fact(start, end, row["val"], tag, currency, filed, accession, row["form"])
            index.setdefault((start, end), []).append(fact)
    return index, None


def build_sec_20f_annual_review(company_facts, tags, flow_fields, *, expected_cik, currency, as_of):
    """Return evidence only. Caller owns ticker/CIK association and transport.

    tags maps monetary output fields to ordered US-GAAP concepts; revenue is
    required. Within each exact period, prefer the first concept then its latest
    filed facts. Conflicts are missing, not zero or a fallthrough to another tag.
    Scope totals are reported alongside continuing/discontinued facts when present.
    This does not certify equal business scope across years or latest earnings.
    """
    if not isinstance(company_facts, dict) or not _cik(expected_cik) or _cik(company_facts.get("cik")) != _cik(expected_cik):
        raise ValueError("cik_mismatch")
    cutoff = _date(as_of)
    if cutoff is None or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("invalid_review_basis")
    if (not isinstance(tags, dict) or "revenue" not in tags
            or any(not isinstance(k, str) or not isinstance(v, (list, tuple)) or not v
                   or any(not isinstance(t, str) or not t for t in v) for k, v in tags.items())):
        raise ValueError("invalid_tags")
    if (not isinstance(flow_fields, (set, frozenset, list, tuple))
            or any(not isinstance(field, str) or field not in tags for field in flow_fields)
            or "revenue" not in flow_fields):
        raise ValueError("invalid_flow_fields")
    # Keep metadata keys out of caller-defined metric names.
    reserved = {"period", "date", "start", "end", "fiscal_year", "unit", "report_code",
                "provenance", "missing_fields", "comparability_flags", "filed", "accession"}
    if reserved.intersection(tags) or set(SCOPE_TAGS).intersection(tags):
        raise ValueError("reserved_metric_name")
    result = {"review_only": True, "eligible_for_scoring": False, "latest_release_verified": False,
              "cik": _cik(expected_cik), "currency": currency, "as_of": as_of,
              "annual": [], "quarter": [], "issues": [], "status": "no_supported_annual_data"}
    facts = company_facts.get("facts", {})
    namespace = facts.get("us-gaap") if isinstance(facts, dict) else None
    if not isinstance(namespace, dict):
        result["issues"].append({"reason": "us_gaap_unavailable"})
        return result
    fields = {**tags, **SCOPE_TAGS}
    flows = set(flow_fields) | set(SCOPE_TAGS)
    indices = {}
    for field, names in fields.items():
        indices[field], error = _index(namespace, names, currency=currency, cutoff=cutoff, flow=field in flows)
        if error:
            result["issues"].append({"field": field, "reason": error})
    ends = {}
    for start, end in indices["revenue"]:
        ends.setdefault(end, []).append(start)
    for end, starts in sorted(ends.items()):
        if len(starts) != 1:
            result["issues"].append({"end": end.isoformat(), "reason": "ambiguous_annual_start"})
            continue
        start = starts[0]
        anchor = _pick(indices["revenue"][(start, end)])
        if anchor is None:
            result["issues"].append({"end": end.isoformat(), "reason": "ambiguous_revenue"})
            continue
        row = {"period": "annual", "date": end.isoformat(), "start": start.isoformat(),
               "end": end.isoformat(), "fiscal_year": str(end.year), "unit": currency,
               "report_code": anchor.form, "filed": anchor.filed.isoformat(), "accession": anchor.accession,
               "provenance": {}, "missing_fields": [], "comparability_flags": ["business_scope_unverified"]}
        accessions = set()
        for field, index in indices.items():
            selected = _pick(index.get((start if field in flows else None, end), []))
            row[field] = selected.value if selected else None
            row["provenance"][field] = ({"method": "reported", "facts": [_source(selected)]}
                                        if selected else {"status": "missing_or_ambiguous"})
            if selected:
                accessions.add(selected.accession)
            elif field in tags:
                row["missing_fields"].append(field)
        if len(accessions) > 1:
            row["comparability_flags"].append("mixed_filing_accessions")
        if any(row[k] is not None for k in ("ocf_discontinued", "net_income_discontinued")):
            row["comparability_flags"].append("continuing_and_discontinued_scope")
        result["annual"].append(row)
    if result["annual"]:
        result["status"] = "annual_evidence_only"
    return result
