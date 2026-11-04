"""Missing-field enrichment after issuer, release and fiscal-period validation."""

import re


_FORWARD = re.compile(r"\b(?:expects?|expected|anticipates?|projects?|projected|plans?|will|aims?|intends?)\b", re.I)
_SUBJECT = re.compile(r"\b(?:we|our|company|business|division|it|management)\b", re.I)
_TOPIC = re.compile(r"\b(?:demand|supply|revenue|sales|margin|profit|growth|production|capacity|investment|capital expenditure|cash flow)\b", re.I)
_DISCLAIMER = re.compile(r"risks? and uncertainties|may differ|forward.looking statements|no obligation|not guarantees|conference call|webcast|share repurchase|dividend", re.I)


def qualitative_outlook(blocks, spec):
    """Retain company prose, including its segment and horizon, not a forecast value."""
    accepted = [b for b in blocks if _FORWARD.search(b) and _SUBJECT.search(b)
                and _TOPIC.search(b) and not _DISCLAIMER.search(b)
                and not re.search(r"\b(?:previously|last year|last quarter|had expected)\b", b, re.I)]
    if not accepted:
        return None
    return dict(status="reported", text=" / ".join(accepted[:2]), source_url=spec["source_url"],
                period_scope="management_outlook", extraction="source_qualitative_outlook",
                evidence_kind="qualitative", scope_note="회사 정성 전망 · 사업부/대상기간은 원문 기준, 수치 가이던스 아님")


def explicit_quarter_fcf(content, spec, table_grid):
    """Read only a named FCF row under one explicit quarter-end date and unit.

    A fiscal period is not a calendar date: the verified period_end is required.
    Ambiguous columns, annual/YTD tables and adjusted FCF are not substitutes.
    """
    end = spec.get("period_end_label")
    if not end:
        return None
    found = []
    for table in content.xpath(".//table"):
        if table.xpath(".//table"):
            continue
        grid = table_grid(table)
        hits = [(i, row) for i, row in enumerate(grid)
                if row and row[0].strip().lower() == "free cash flow"]
        if not hits:
            continue
        # Relevant units must be in this table, not a preceding unrelated table.
        caption = " ".join(" ".join(node.itertext()) for node in table.xpath("./caption"))
        before = caption + " " + " ".join(" ".join(row) for row in grid[:hits[0][0]])
        if (not re.search(r"Three Months Ended|Quarter Ended", before, re.I)
                or not re.search(r"\bin millions\b", before, re.I)
                or re.search(r"Nine Months|Six Months|Year Ended|TTM|trailing|outlook", before, re.I)):
            continue
        headers = [(i, row) for i, row in enumerate(grid[:hits[0][0]]) if end in row]
        if len(headers) != 1:
            continue
        columns = [i for i, cell in enumerate(headers[0][1]) if cell == end]
        if len(columns) != 1:
            continue
        col = columns[0]
        for _, row in hits:
            raw = row[col].strip()
            if not re.fullmatch(r"\$?\s*(?:-?\d[\d,]*(?:\.\d+)?|\(\d[\d,]*(?:\.\d+)?\))", raw):
                continue
            found.append(raw)
    if len(found) != 1:
        return None
    # USD is verified in the issuer profile; 'millions' alone cannot imply currency.
    if spec.get("reporting_currency") != "USD":
        return None
    value = found[0]
    return dict(status="reported", text=f"{spec['fiscal_period']} / quarter ended {end} | Free cash flow: {value} USD millions (company-defined, not adjusted FCF)",
                source_url=spec["source_url"], source_value=value, source_label="Free cash flow",
                unit="USD millions", column=end, period_scope=spec["fiscal_period"],
                extraction="explicit_quarter_fcf_table")


def pdf_outlook_column(layout, spec, *, heading, horizon, next_horizon, page):
    """Read a verified side-by-side PDF outlook column, never the results column."""
    lines = layout.splitlines()
    if not lines or next((line.strip() for line in lines if line.strip()), "") != heading:
        return None
    headers = [(i, line.index("Outlook")) for i, line in enumerate(lines) if re.search(r"\bOutlook\b", line)]
    if len(headers) != 1 or headers[0][1] < 30:
        return None
    starts = [(i, line.index(horizon)) for i, line in enumerate(lines) if horizon in line and i > headers[0][0]]
    if len(starts) != 1 or abs(starts[0][1] - headers[0][1]) > 4:
        return None
    start, col = starts[0]
    right = [line[col:].strip() for line in lines[start + 1:]]
    if next_horizon not in right:
        return None
    body = " ".join(right[:right.index(next_horizon)])
    body = " ".join(re.sub(r"[\ue000-\uf8ff]", "-", body).split())
    if not 20 <= len(body) <= 1400 or not _TOPIC.search(body):
        return None
    return dict(status="reported", text=f"{heading} / {horizon} Outlook: {body}",
                source_url=spec["source_url"], source_page=page, source_label=f"{heading} Outlook",
                period_scope="management_outlook", extraction="explicit_pdf_outlook_column",
                evidence_kind="qualitative", scope_note="회사 정성 전망 · 메모리 사업부, 연결 수치 가이던스 아님")


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
