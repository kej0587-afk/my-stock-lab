"""Verified issuer PDF layouts only; no inferred financial values or forecasts."""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import re
from zoneinfo import ZoneInfo

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

MAX_BYTES = 8_000_000
MAX_PAGES = 24
_NUMBER = r"\(?-?\d[\d,]*(?:\.\d+)?\)?"
_COVERAGE = {
    "GOOGL": ("2026Q3", "2026-10-28", (0, 7)),
    "005930.KS": ("2026Q3", "2026-10-29", (0, 4, 14)),
}


def _read_pdf(data, indices, now, zone):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES or not data.startswith(b"%PDF-"):
        raise ValueError("invalid_document_size")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pdf_reader_unavailable") from exc
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted or not max(indices) < len(reader.pages) <= MAX_PAGES:
            raise ValueError("invalid_pdf_pages")
        metadata = reader.metadata
        versions = [getattr(metadata, name, None) for name in ("creation_date", "modification_date")]
        for version in versions:
            # PDF authoring times are cutoff checks only, never release timestamps.
            checked = max(version.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc) for fold in (0, 1)) if version and version.tzinfo is None else version
            if checked and checked > now:
                raise ValueError("page_version_after_cutoff")
        pages = {i + 1: "\n".join(" ".join(line.split()) for line in
                                 reader.pages[i].extract_text(extraction_mode="layout").splitlines())
                 for i in indices}
        modified = next((v.isoformat() for v in reversed(versions) if v and v.tzinfo), None)
        return pages, modified
    except ValueError as exc:
        if str(exc) in {"invalid_pdf_pages", "page_version_after_cutoff"}:
            raise
        raise ValueError("invalid_pdf_document") from exc
    except Exception as exc:
        # Malformed supplier PDFs must not abort report generation; expose no raw bytes.
        raise ValueError("invalid_pdf_document") from exc


def _metric(spec, label, value, unit, page, *, column, qualifier=""):
    return dict(status="reported", text=f"{column} | {label}: {value} {unit}" + (f" · {qualifier}" if qualifier else ""),
                source_url=spec["source_url"], source_page=page, source_label=label,
                source_value=value, unit=unit, column=column, period_scope=spec["fiscal_period"],
                extraction="explicit_pdf_quarter_table")


def _row_value(text, label, count, index):
    rows = re.findall(r"^" + label + r"\s+(.+)$", text, re.M | re.I)
    matches = []
    for row in rows:
        # A following bullet belongs to the commentary panel, not this table.
        tail = row.split("•", 1)[0].strip()
        values = re.findall(_NUMBER, tail)
        remainder = re.sub(_NUMBER, "", tail).replace("$", "").strip()
        if len(values) == count and not remainder:
            matches.append(values[index])
    return matches[0] if len(matches) == 1 else None


def _table_after(text, header):
    """A verified period header cannot authorize a later, differently scoped table."""
    matches = list(re.finditer(header, text, re.I))
    if len(matches) != 1:
        return ""
    body = text[matches[0].end():]
    boundary = re.search(r"^.*(?:\b(?:Quarter|Months?|Year) Ended\b|\bReconciliation from\b|\b[1-4]Q 20\d{2} (?:Results|Outlook)\b).*$", body, re.M | re.I)
    return body[:boundary.start()] if boundary else body


def _alphabet(pages, spec, metrics):
    first = pages[1]
    flat = " ".join(first.split())
    if not re.search(r"^Alphabet Announces Third Quarter 2026 Results\b", flat, re.I):
        raise ValueError("result_identity_or_period_mismatch")
    if not re.search(r"October 28,? 2026", flat[:600]):
        raise ValueError("release_date_not_in_body")
    if not re.search(r"today announced financial results for the quarter ended September 30, 2026", flat[:900], re.I):
        raise ValueError("result_publication_unconfirmed")
    table = _table_after(first, r"Quarter Ended September 30,\s*2025\s+2026")
    if table and "in millions, except for per share information and percentages" in flat:
        for key, label in (("revenue", "Revenues"), ("profit", "Operating income")):
            value = _row_value(table, label, 2, 1)
            if value is not None:
                metrics[key] = _metric(spec, label, value, "USD million", 1, column="Q3 2026", qualifier="unaudited")
    cash = pages[8]
    flat_cash = " ".join(cash.split())
    table = _table_after(cash, r"Quarter Ended\s+TTM\s+Q4 2025\s+Q1 2026\s+Q2 2026\s+Q3 2026\s+Q3 2026")
    if not (re.search(r"Reconciliation from GAAP Net Cash Provided by Operating Activities to Non-GAAP Free Cash Flow \(in millions; unaudited\)", flat_cash, re.I)
            and table):
        return
    for key, label in (("capex", "Less: purchases of property and equipment"), ("free_cash_flow", "Free cash flow")):
        value = _row_value(table, re.escape(label), 5, 3)
        if value is not None:
            metrics[key] = _metric(spec, label, value, "USD million", 8, column="Q3 2026",
                                   qualifier="unaudited · 분기값, TTM 아님")


def _samsung(pages, spec, metrics):
    first = " ".join(pages[1].split())
    if not re.search(r"SAMSUNG ELECTRONICS.*3Q 2026 Earnings Call", first, re.I):
        raise ValueError("result_identity_or_period_mismatch")
    summary = " ".join(pages[5].split())
    if not summary.startswith("3Q 2026 Results Based on consolidated financial statements"):
        raise ValueError("result_identity_or_period_mismatch")
    metrics["free_cash_flow"]["reason"] = "not_reported_in_supported_pdf"
    values = re.findall(r"Revenue Operating Profit R&D Investment KRW (\d+(?:\.\d+)?)T KRW (\d+(?:\.\d+)?)T KRW (\d+(?:\.\d+)?)T\b", summary)
    if len(values) == 1:
        for key, label, value in zip(("revenue", "profit"), ("연결 매출", "연결 영업이익"), values[0][:2]):
            metrics[key] = _metric(spec, label, value, "조원", 5, column="2026년 3분기")
    cash = pages[15]
    if not (cash.startswith("Appendix 4: Cash Flow (Summary)")
            and re.search(r"KRW trillion\s+3Q 25\s+2Q 26\s+3Q 26\s+Current State of Net Cash", cash)):
        return
    value = _row_value(cash, "Purchase of PP&E", 3, 2)
    if value is not None:
        metrics["capex"] = _metric(spec, "현금흐름표 유형자산 취득", value, "조원", 15,
                                    column="2026년 3분기", qualifier="현금 유출 표기 · 회사 총 CAPEX와 별도")
    # No FCF value is directly disclosed in this presentation. Do not calculate it.


def parse_official_result_pdf(data, ticker, spec, now):
    coverage = _COVERAGE.get(ticker)
    if (not coverage or not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() is None or (spec.get("fiscal_period"), spec.get("release_date")) != coverage[:2]):
        raise ValueError("unsupported_result_or_timestamp")
    if now.astimezone(ZoneInfo(spec["timezone"])).date().isoformat() < spec["release_date"]:
        raise ValueError("future_result")
    now = now.astimezone(timezone.utc)
    pages, modified = _read_pdf(data, coverage[2], now, ZoneInfo(spec["timezone"]))
    metrics = {key: dict(text="", status="missing", reason="supported_pdf_field_unavailable", source_url=spec["source_url"])
               for key in ("revenue", "profit", "capex", "free_cash_flow", "guidance")}
    (_alphabet if ticker == "GOOGL" else _samsung)(pages, spec, metrics)
    return dict(ticker=ticker, fiscal_period=spec["fiscal_period"], release_date=spec["release_date"],
                release_precision="date", release_at=None, source_url=spec["source_url"],
                checked_at=now.isoformat(), observed_at=now.isoformat(), status="official_result", stale=False,
                collection_reason="official_pdf", metrics=metrics,
                provenance=dict(provider="official_ir_pdf", coverage="verified_url_and_period_only",
                                content_sha256=hashlib.sha256(data).hexdigest(), page_modified_at=modified,
                                publication_time_status="date_only", timing_basis="date_only_observed_at",
                                release_date_basis="source_body" if ticker == "GOOGL" else "verified_issuer_calendar",
                                observed_at=now.isoformat(), price_reaction_verified=False))
