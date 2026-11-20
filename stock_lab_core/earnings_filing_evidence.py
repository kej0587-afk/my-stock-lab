"""Pure parsing of discovered filings. No issuer registry or score inputs."""

from datetime import date
import hashlib
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import stamp

register_loaded_source(__name__, __file__)


def sec_base(cik, accession):
    if not re.fullmatch(r"\d{1,10}", str(cik)) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(accession)):
        raise ValueError("invalid_filing_identity")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"


def sec_document(base, filename):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.html?", str(filename), re.I):
        raise ValueError("invalid_filing_document")
    return base + filename


def latest_sec_filing(data, ticker, cik, now):
    """Acceptance cutoff, not a guessed release hour. Do not skip newer errors."""
    if str(data.get("cik", "")).lstrip("0") != str(cik).lstrip("0"):
        raise ValueError("issuer_cik_mismatch")
    aliases = {str(t).replace(".", "-").upper() for t in data.get("tickers", [])}
    if ticker.replace(".", "-") not in aliases:
        raise ValueError("issuer_ticker_mismatch")
    recent = data.get("filings", {}).get("recent", {})
    fields = ("form", "items", "accessionNumber", "primaryDocument", "filingDate", "acceptanceDateTime")
    columns = [recent.get(key, []) for key in fields]
    if len({len(col) for col in columns}) != 1:
        raise ValueError("filing_columns_mismatch")
    rows = []
    for values in zip(*columns):
        row = dict(zip(fields, values))
        accepted = stamp(row["acceptanceDateTime"])
        if row["form"] not in {"8-K", "8-K/A"} or "2.02" not in {v.strip() for v in str(row["items"]).split(",")}:
            continue
        if accepted is None or not re.search(r"Z$|[+-]\d\d:\d\d$", row["acceptanceDateTime"]):
            continue
        if accepted > now or (now - accepted).days > 200:
            continue
        sec_document(sec_base(cik, row["accessionNumber"]), row["primaryDocument"])
        rows.append(row)
    if not rows:
        raise ValueError("recent_earnings_filing_unavailable")
    return max(rows, key=lambda row: row["acceptanceDateTime"])


def sec_release_link(data, base):
    root = html.fromstring(data, parser=html.HTMLParser(no_network=True))
    links = set()
    for row in root.xpath("//tr"):
        cells = [" ".join(cell.itertext()).strip() for cell in row.xpath("./td")]
        if not any(re.fullmatch(r"(?:Exhibit\s+)?99[.]1", cell, re.I) for cell in cells):
            continue
        for anchor in row.xpath(".//a[@href]"):
            target = urljoin(base, anchor.get("href"))
            parts = urlsplit(target)
            if target.startswith(base) and not parts.query and not parts.fragment:
                try:
                    links.add(sec_document(base, target[len(base):]))
                except ValueError:
                    pass
    if len(links) != 1:
        raise ValueError("unique_earnings_exhibit_unavailable")
    return links.pop()


def _fiscal_period(text):
    ordinal = r"(first|second|third|fourth|1st|2nd|3rd|4th)"
    number = {"first": "1", "second": "2", "third": "3", "fourth": "4", "1st": "1", "2nd": "2", "3rd": "3", "4th": "4"}
    patterns = [
        (rf"\b(?:fiscal\s+)?{ordinal}[- ]quarter\s+(?:(?:of\s+)?(?:fiscal(?:\s+year)?|FY)\s*)?(20\d{{2}})\b", False),
        (rf"\b(?:fiscal(?:\s+year)?\s+|FY\s*)?(20\d{{2}})\s+{ordinal}[- ]quarter\b", True),
        (r"\bQ([1-4])\s+(?:(?:fiscal(?:\s+year)?|FY)\s*)?(20\d{2})\b", False),
        (r"\b(?:fiscal(?:\s+year)?\s+|FY\s*)?(20\d{2})\s+Q([1-4])\b", True),
    ]
    found = set()
    for pattern, reverse in patterns:
        for match in re.finditer(pattern, text, re.I):
            a, b = match.groups()
            year, quarter = (a, b) if reverse else (b, a)
            found.add((year, number.get(quarter.lower(), quarter), bool(re.search(r"fiscal|\bFY", match[0], re.I))))
    if len({(year, quarter) for year, quarter, _ in found}) != 1:
        raise ValueError("explicit_fiscal_quarter_unavailable")
    year, quarter, _ = next(iter(found))
    return ("FY" if any(fiscal for _, _, fiscal in found) else "") + year + "Q" + quarter


def _release_metrics(root, body, spec):
    from stock_lab_core.earnings_result_sources import _prose_metrics, _text, _MONEY

    # A bullet under "we expect" need not repeat a forward-looking verb.
    # Exclude the entire outlook section from realized figures before parsing.
    boundary = re.search(r"\b(?:Financial|Business|Company) Outlook\b|"
                         r"\bFor (?:the )?(?:fiscal )?(?:first|second|third|fourth|next|full|20\d{2}).{0,60}\bwe expect\b", body, re.I)
    positions = [boundary.start()] if boundary else []
    for node in root.xpath("//h1|//h2|//h3|//p|//div[not(p or div or table)]"):
        value = _text(node)
        if len(value) <= 120 and re.fullmatch(r"(?:(?:fiscal|financial|business|company|first|second|third|fourth|quarter|full|year|and|20\d{2})\s+)*(?:outlook|guidance)", value, re.I):
            if body.find(value) >= 0:
                positions.append(body.find(value))
    boundary_at = min(positions) if positions else None
    actual = body[:boundary_at] if boundary_at is not None else body
    blocks = [_text(node) for node in root.xpath("//p|//li|//div[not(p or div or table)]")
              if not node.xpath("ancestor::table") and 10 <= len(_text(node)) <= 900]
    sentences = [s for block in blocks if block in actual
                 for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", block)]
    metrics = _prose_metrics(sentences, spec)
    if boundary_at is not None:
        outlook = body[boundary_at:boundary_at + 3000]
        intro = re.search(r"\bFor (?:the )?.{0,120}?\b(?:we|the company)\s+(?:expects?|forecasts?)\s*:", outlook, re.I)
        if intro:
            after = outlook[intro.end():]
            next_period = re.search(r"\bFor (?:the )?.{0,100}\b(?:expect|forecast)", after, re.I)
            if next_period:
                after = after[:next_period.start()]
            statement = re.search(r"\b(?:Total )?(?:revenue|net sales)\b.{0,350}?(?=\s*[•]|(?<=[.!?])\s+[A-Z]|$)", after, re.I)
            if statement and _MONEY.search(statement[0]):
                metrics["guidance"] = dict(status="reported", text=intro[0] + " " + statement[0],
                    source_url=spec["source_url"], period_scope="management_outlook",
                    extraction="explicit_outlook_context_and_statement")
        if metrics["guidance"]["status"] == "missing":
            candidates = _prose_metrics([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", outlook) if len(s) <= 900], spec)
            metrics["guidance"] = candidates["guidance"]
    return metrics


def parse_sec_release(data, ticker, cik, filing, url, now, *, issuer_name=None):
    from stock_lab_core.earnings_result_sources import _date_evidence, _text, _PROFILES, parse_earnings_result
    root = html.fromstring(data, parser=html.HTMLParser(no_network=True))
    for node in root.xpath("//script|//style|//nav|//footer"):
        node.drop_tree()
    body = _text(root)
    # The title must announce results, not an upcoming call or a forecast.
    headings = [_text(node) for node in root.xpath("//h1|//h2|//title|//p|//div|//b|//strong")
                if 20 <= len(_text(node)) <= 400]
    title = next((value for value in headings if re.search(r"\b(?:reports?|announces?)\b.{0,130}\bresults\b", value, re.I)
                  and not re.search(r"\b(?:will|to announce|to report)\b", value, re.I)), "")
    if not title:
        # SEC exhibits may split a headline across styled spans without h1/p.
        match = re.search(r"\b(?:reports?|announces?)\b.{0,130}?\bresults\b", body[:600], re.I)
        if match and not re.search(r"\b(?:will|to)\s*$", body[:match.start()], re.I):
            title = body[:match.end()]
    if not title:
        raise ValueError("result_heading_unavailable")
    name = re.sub(r"\b(?:incorporated|inc|corporation|corp|limited|ltd|plc)\b[.]?", "", issuer_name or ticker, flags=re.I)
    normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if not name.strip() or not re.search(r"\b" + re.escape(normalize(name)) + r"\b", normalize(title)):
        raise ValueError("release_issuer_mismatch")
    period = _fiscal_period(title)
    # Dateline appears before the first report sentence. A quarter-end date in
    # that sentence is not substituted for the announcement day.
    prefix = re.split(r"\b(?:today\s+)?(?:announced|reported)\b", body, maxsplit=1, flags=re.I)[0]
    dates = _date_evidence(prefix[-1800:])
    if len(dates) != 1:
        raise ValueError("release_dateline_unavailable")
    release_day = dates[0]
    filed_day = date.fromisoformat(filing["filingDate"])
    if not 0 <= (filed_day - date.fromisoformat(release_day)).days <= 10:
        raise ValueError("release_filing_date_mismatch")
    if release_day > now.astimezone(ZoneInfo("America/New_York")).date().isoformat():
        raise ValueError("future_result")
    spec = dict(ticker=ticker, fiscal_period=period, source_url=url)
    metrics = _release_metrics(root, body, spec)
    # Retain the already-tested, richer table readers when the discovered
    # source is the same verified quarter/date. Never carry them to a new Q.
    profile = _PROFILES.get(ticker, {})
    if (profile.get("fiscal_period", "").removeprefix("FY") == period.removeprefix("FY")
            and profile.get("release_date") == release_day):
        try:
            existing = parse_earnings_result(data, ticker, now)
        except ValueError:
            existing = {}
        for key, metric in existing.get("metrics", {}).items():
            if metric.get("status") in {"reported", "deferred"}:
                metrics[key] = {**metric, "source_url": url}
    guidance = metrics.get("guidance", {})
    if guidance.get("status") == "reported" and re.search(
            r"\bdefines?\s+(?:its\s+|our\s+)?(?:non-GAAP|adjusted|free cash flow|operating|net income)\b|"
            r"\b(?:is|are) defined as\b|\b(?:safe harbor|forward-looking statements)\b",
            guidance.get("text", ""), re.I):
        metrics["guidance"] = dict(status="missing", text="", source_url=url,
                                  reason="accounting_definition_or_disclaimer_not_outlook")
    proof = dict(provider="sec_discovered_release", cik=str(int(cik)), accession=filing["accessionNumber"],
                 filing_date=filing["filingDate"], accepted_at=filing["acceptanceDateTime"],
                 primary_url=sec_document(sec_base(cik, filing["accessionNumber"]), filing["primaryDocument"]),
                 title=title, content_sha256=hashlib.sha256(data).hexdigest(),
                 timing_basis="release_dateline_date_only", price_reaction_verified=False)
    result = dict(ticker=ticker, fiscal_period=period, release_date=release_day, release_at=None,
                  release_precision="date", source_url=url, checked_at=now.isoformat(), observed_at=now.isoformat(),
                  status="official_result", stale=False, collection_reason="sec_exhibit_99_1",
                  metrics=metrics, provenance=proof)
    event = dict(ticker=ticker, event=f"{ticker} earnings", indicator="COMPANY_EARNINGS", market="US",
                 date=release_day, release_at=None, release_precision="date", release_date_confirmed=True,
                 release_time_confirmed=False, timezone="America/New_York", fiscal_period=period,
                 event_kind="results", status="공식 실적 발표", event_status="released",
                 source="SEC · 회사 실적 발표문", source_url=url, source_kind="sec_discovered_release",
                 official_discovery=proof, source_verified_at=now.isoformat())
    return event, result


def valid_discovered_result(event, result):
    """Bind a result to the same verified issuer, accession and source event."""
    proof = result.get("provenance") or {}
    if proof.get("provider") != "sec_discovered_release" or proof != event.get("official_discovery"):
        return False
    if event.get("source_kind") != "sec_discovered_release" or result.get("source_url") != event.get("source_url"):
        return False
    try:
        base = sec_base(proof.get("cik"), proof.get("accession"))
        url = result["source_url"]
        return (url.startswith(base) and sec_document(base, url[len(base):]) == url
                and re.fullmatch(r"[a-f0-9]{64}", str(proof.get("content_sha256", ""))) is not None)
    except (ValueError, KeyError):
        return False


def latest_dart_report(payload, corp, ticker, now):
    """Report period/month is explicit; never infer fiscal Q from a month."""
    if payload.get("status") != "000":
        raise ValueError("dart_no_reports" if payload.get("status") == "013" else "dart_api_error")
    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    candidates = []
    for row in payload.get("list", []):
        title = str(row.get("report_nm", ""))
        match = re.fullmatch(r"(?:\[[^]]+\]\s*)*(사업|반기|분기)보고서\s*\((20\d{2})[.](\d{2})\)", title)
        if not match or row.get("corp_code") != corp or row.get("stock_code") != ticker.split(".")[0]:
            continue
        receipt, filed = str(row.get("rcept_no", "")), str(row.get("rcept_dt", ""))
        if not re.fullmatch(r"\d{14}", receipt) or not re.fullmatch(r"\d{8}", filed):
            continue
        day = date.fromisoformat(f"{filed[:4]}-{filed[4:6]}-{filed[6:]}")
        period = f"{match[2]}-{match[3]}"
        if not 1 <= int(match[3]) <= 12 or day > today or period > day.isoformat()[:7] or (today - day).days > 200:
            continue
        candidates.append((period, day.isoformat(), receipt, title, str(row.get("corp_name") or ticker).strip()))
    if not candidates:
        raise ValueError("dart_period_report_unavailable")
    period, day, receipt, title, name = max(candidates)
    return dict(ticker=ticker, name=name or ticker, event=title, indicator="COMPANY_EARNINGS", market="KR", date=day,
                fiscal_period=f"{period} 보고기간·회계분기 미확인", reporting_period_end_month=period,
                filing_receipt=receipt, filing_corp_code=corp,
                event_kind="regulatory_report", event_status="released", status="공식 정기보고서 확인",
                source="DART 정기보고서", source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
                source_kind="dart_discovered_report", date_basis="공시 접수일·실적 발표일 미확인",
                release_date_confirmed=False, release_time_confirmed=False, release_at=None,
                release_precision="unknown", timezone="Asia/Seoul", source_verified_at=now.isoformat())
