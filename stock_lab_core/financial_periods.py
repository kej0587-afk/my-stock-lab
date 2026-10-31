"""Strict, offline matching of FMP income and companion statements.

Both rows need an ISO end date, a four-digit fiscalYear/calendarYear and an
explicit FY or Q1-Q4 period. Missing or contradictory metadata is held back.
Exact end dates take priority, but cannot override year/period conflicts.

For nearby dates, matching fiscal labels plus the same calendar year/quarter
and at most seven days of drift are required. Seven days is a conservative
local tolerance for week-based reporting, not a provider guarantee. Calendar
quarter/year boundaries remain excluded even when the dates are one day apart.
"""

from __future__ import annotations

from datetime import date
import math


MAX_END_DATE_DRIFT_DAYS = 7
_PERIODS = frozenset({"FY", "Q1", "Q2", "Q3", "Q4"})


def missing_scoring_inputs(fin, *, financial_business=False):
    """Do not turn missing core statement facts into bearish score evidence."""
    required = ("net_income", "equity") if financial_business else (
        "revenue", "op_income", "net_income", "ocf", "equity", "liabilities")
    missing = []
    for kind in ("annual", "quarter"):
        records = fin.get(kind) or []
        if not records:
            missing.append(f"{kind}: report missing")
            continue
        for field in required:
            value = records[-1].get(field)
            try:
                usable = value is not None and not isinstance(value, bool) and math.isfinite(float(value))
            except (TypeError, ValueError, OverflowError):
                usable = False
            if not usable:
                missing.append(f"{kind}: {field}")
    return missing


def adjacent_quarters(previous, current):
    """Require consecutive fiscal quarters, not merely neighboring list rows."""
    if isinstance(previous, dict) and isinstance(current, dict):
        before_start, after_start = previous.get("fiscal_year_start"), current.get("fiscal_year_start")
        before_q, after_q = previous.get("fiscal_quarter"), current.get("fiscal_quarter")
        if before_start and after_start and before_q in (1, 2, 3, 4) and after_q in (1, 2, 3, 4):
            try:
                first, second = date.fromisoformat(before_start), date.fromisoformat(after_start)
                consecutive_dates = (date.fromisoformat(current["start"]) - date.fromisoformat(previous["date"])).days == 1
                if first == second:
                    return after_q - before_q == 1 and consecutive_dates
                return (before_q == 4 and after_q == 1 and 330 <= (second - first).days <= 385
                        and (second - date.fromisoformat(previous["date"])).days == 1
                        and current["start"] == after_start)
            except (TypeError, ValueError, KeyError):
                return False
    def ordinal(row):
        if not isinstance(row, dict):
            return None
        try:
            year = int(row.get("fiscal_year"))
            quarter = row.get("fiscal_quarter")
            if quarter is None:
                code = str(row.get("report_code", "")).upper()
                quarter = int(code[1:]) if code in {"Q1", "Q2", "Q3", "Q4"} else None
            quarter = int(quarter)
            return year * 4 + quarter if 1900 <= year <= 2200 and 1 <= quarter <= 4 else None
        except (ValueError, TypeError):
            return None
    before, after = ordinal(previous), ordinal(current)
    return before is not None and after is not None and after - before == 1


def _period_key(row: dict) -> tuple[date, int, str] | None:
    if not isinstance(row, dict):
        return None
    raw_date = row.get("date")
    if not isinstance(raw_date, str):
        return None
    text = raw_date.strip()
    try:
        end = date.fromisoformat(text)
    except ValueError:
        return None
    if end.isoformat() != text:
        return None

    years = []
    for key in ("fiscalYear", "calendarYear"):
        value = row.get(key)
        if value is None or isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return None
        year = str(value).strip()
        if len(year) != 4 or not year.isascii() or not year.isdigit() or int(year) == 0:
            return None
        years.append(int(year))
    if not years or len(set(years)) != 1:
        return None

    raw_period = row.get("period")
    period = raw_period.strip().upper() if isinstance(raw_period, str) else ""
    if period not in _PERIODS:
        return None
    return end, years[0], period


def _unambiguous_row(rows: list[dict]) -> dict:
    if not rows:
        return {}
    first = rows[0]
    return first if all(row == first for row in rows[1:]) else {}


def match_statement_period(records: list[dict], income_row: dict) -> dict:
    """Return the unique best compatible original row, or {} without guessing.

    Candidates must match the explicit fiscal year and FY/Q period. Among
    compatible dates, exact dates win, then the nearest date within the local
    tolerance. Conflicting rows at the best distance are ambiguous; identical
    duplicate rows are harmless. Inputs are never modified, and list order
    cannot resolve conflicting candidates.
    """
    income_key = _period_key(income_row)
    if income_key is None or not isinstance(records, list):
        return {}
    income_end, income_year, income_period = income_key
    exact, nearby = [], []
    for row in records:
        key = _period_key(row)
        if key is None:
            continue
        end, year, period = key
        if (year, period) != (income_year, income_period):
            continue
        if end == income_end:
            exact.append(row)
            continue
        distance = abs((end - income_end).days)
        if (end.year == income_end.year
                and (end.month - 1) // 3 == (income_end.month - 1) // 3
                and distance <= MAX_END_DATE_DRIFT_DAYS):
            nearby.append((distance, row))
    if exact:
        return _unambiguous_row(exact)
    if not nearby:
        return {}
    nearest = min(distance for distance, _ in nearby)
    return _unambiguous_row([row for distance, row in nearby if distance == nearest])
