"""Protect saved statement periods during an explicit financial-score refresh."""

from collections.abc import Mapping
from datetime import date


def _latest(metrics, kind):
    if not isinstance(metrics, Mapping):
        return {}
    record = metrics.get(f"{kind}_latest")
    if isinstance(record, Mapping) and record:
        return record
    records = metrics.get(f"{kind}_records")
    if isinstance(records, list) and records and isinstance(records[-1], Mapping):
        return records[-1]
    return {}


def _period(record, kind, source):
    raw_date = record.get("date")
    if isinstance(raw_date, str):
        try:
            end = date.fromisoformat(raw_date)
            if end.isoformat() == raw_date:
                return "end_date", end, raw_date
        except ValueError:
            pass

    # DART emits fiscal labels, not calendar end dates. Never map SEC/FMP's
    # fiscal year labels onto these ordinals or infer a calendar quarter.
    if not str(source).startswith("dart"):
        return None
    year = str(record.get("fiscal_year", ""))
    if len(year) != 4 or not year.isascii() or not year.isdigit():
        return None
    if not 1900 <= int(year) <= 2200:
        return None
    if kind == "annual":
        if raw_date not in (None, "", year):
            return None
        return "dart_fiscal", (int(year), 0), f"FY{year}"
    code = str(record.get("report_code", ""))
    quarter = record.get("fiscal_quarter")
    if quarter is None and code in {"Q1", "Q2", "Q3", "Q4"}:
        quarter = code[1:]
    if isinstance(quarter, bool) or str(quarter) not in {"1", "2", "3", "4"}:
        return None
    quarter = int(quarter)
    report_code = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}[quarter]
    if code and code not in (f"Q{quarter}", report_code):
        return None
    if raw_date not in (None, "", f"{year}-Q{quarter}", f"{year}-{report_code}"):
        return None
    return "dart_fiscal", (int(year), quarter), f"FY{year} Q{quarter}"


def financial_refresh_period_issues(candidate, baseline, *, candidate_source="", baseline_source=""):
    """Return regressions/unknown replacements of known saved periods.

    Annual and quarterly evidence are independent. Unknown legacy baseline
    periods cannot establish a regression; known periods must not be erased.
    This is a monotonicity guard, not proof of latest-release completeness.
    """
    issues = []
    for kind in ("annual", "quarter"):
        before = _period(_latest(baseline, kind), kind, baseline_source)
        if before is None:
            continue
        after = _period(_latest(candidate, kind), kind, candidate_source)
        if after is None or after[0] != before[0]:
            issues.append(f"{kind}: incoming period unverified; existing {before[2]}")
        elif after[1] < before[1]:
            issues.append(f"{kind}: incoming {after[2]} older than existing {before[2]}")
    return issues


def financial_refresh_is_newer(candidate, baseline, *, candidate_source="", baseline_source=""):
    """Require two comparable periods, neither older, and at least one newer.

    Provider retrieval times and fiscal labels without verified end dates do
    not establish newer SEC/FMP statements. Equal periods keep the incumbent.
    """
    newer = False
    for kind in ("annual", "quarter"):
        before = _period(_latest(baseline, kind), kind, baseline_source)
        after = _period(_latest(candidate, kind), kind, candidate_source)
        if before is None or after is None or before[0] != after[0] or after[1] < before[1]:
            return False
        newer = newer or after[1] > before[1]
    return newer
