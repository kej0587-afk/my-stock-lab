"""Read-only eight-quarter evidence; never a scoring/valuation input.

Reuse the period parser, but restrict identity, publication cutoff, currency and
source scope before parsing. FCF here is OCF minus disclosed cash investment,
not a company's adjusted FCF or total AI investment. The investment scope is
explicit: physical PP&E alone or productive assets including intangibles.
"""

from datetime import timedelta
import re

from stock_lab_core.sec_financial_periods import (
    MAX_FACTS_PER_FIELD, _date, _finite, build_sec_statement_records,
)


TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "cash_capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    # Do not substitute restricted cash, investments or total liabilities.
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}
FLOW_FIELDS = frozenset(TAGS) - {"cash"}
LABELS = {"revenue": "매출", "op_income": "영업이익", "net_income": "순이익",
          "ocf": "영업현금흐름", "cash_capex": "현금 투자지출", "cash": "현금·현금성자산"}
FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})
STATUS_LABELS = {"missing_or_ambiguous": "미수집·기간 확인 필요",
    "later_revision_in_subtrahend": "후속 재작성값과 이전 공시의 차감 보류",
    "cross_filing_difference_review": "서로 다른 제출본 누적차감 · 비교 주의",
    "unexpected_negative_amount": "투자지출·현금 음수값 확인 필요",
    "direct_cumulative_conflict": "직접 분기값과 후속 누적값 불일치"}


def _cik(value):
    text = str(value)
    return text.zfill(10) if re.fullmatch(r"[0-9]{1,10}", text) else None


def _filter_facts(payload, cutoff):
    facts = payload.get("facts", {})
    namespace = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
    filtered, issues = {}, []
    if not isinstance(namespace, dict):
        return {}, [{"reason": "us_gaap_unavailable"}]
    for field, names in TAGS.items():
        count = 0
        for tag in names:
            concept = namespace.get(tag, {})
            units = concept.get("units", {}) if isinstance(concept, dict) else {}
            rows = units.get("USD", []) if isinstance(units, dict) else []
            if not isinstance(rows, list):
                rows = []
            count += len(rows)
            kept = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                end, filed = _date(row.get("end")), _date(row.get("filed"))
                if (row.get("form") in FORMS and end and filed and end <= filed <= cutoff
                        and _finite(row.get("val"))
                        and re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(row.get("accn", "")))):
                    kept.append(row)
            filtered[tag] = {"units": {"USD": kept}}
        if count > MAX_FACTS_PER_FIELD:
            for tag in names:
                filtered.pop(tag, None)
            issues.append({"field": field, "reason": "field_limit"})
    return {"facts": {"us-gaap": filtered}}, issues


def _signature(evidence):
    return [(f["start"], f["end"], f["accession"], f["filed"], f["unit"])
            for f in evidence.get("facts", [])]


def _direct_conflict(row, field, filtered):
    """Withhold an old direct quarter contradicted by newer cumulative facts."""
    evidence = row["provenance"][field]
    if field not in FLOW_FIELDS or evidence.get("method") != "reported" or row["fiscal_quarter"] == 1:
        return False
    direct = evidence["facts"][0]
    facts = filtered["facts"]["us-gaap"][direct["tag"]]["units"]["USD"]
    previous_end = (_date(row["start"]) - timedelta(days=1)).isoformat()
    operands = []
    for end in (row["end"], previous_end):
        candidates = [f for f in facts if f.get("start") == row["fiscal_year_start"] and f["end"] == end]
        if not candidates:
            return False
        latest = max(f["filed"] for f in candidates)
        candidates = [f for f in candidates if f["filed"] == latest]
        if len({f["val"] for f in candidates}) != 1:
            return False
        operands.append(candidates[0])
    current, previous = operands
    # The directly disclosed quarter wins within the same filing. A difference
    # using an older YTD may reflect presentation rounding or revisions.
    return (current["filed"] >= previous["filed"] and current["filed"] > direct["filed"]
            and abs((current["val"] - previous["val"]) - direct["value"]) > max(1e-6, abs(direct["value"]) * 1e-10))


def _decorate(row, filtered):
    flags = ["business_scope_unverified"]
    all_accessions = set()
    for field in TAGS:
        evidence = row["provenance"][field]
        facts = evidence.get("facts", [])
        all_accessions.update(f["accession"] for f in facts)
        if _direct_conflict(row, field, filtered):
            row[field] = None
            evidence["status"] = "direct_cumulative_conflict"
        if evidence.get("method") == "cumulative_difference":
            if facts[1]["filed"] > facts[0]["filed"]:
                # A later restated YTD cannot be subtracted from an earlier FY.
                row[field] = None
                evidence["status"] = "later_revision_in_subtrahend"
            elif len({f["accession"] for f in facts}) > 1:
                evidence["status"] = "cross_filing_difference_review"
                flags.append("cross_filing_difference_review")
        if field in {"cash_capex", "cash"} and row[field] is not None and row[field] < 0:
            row[field] = None
            evidence["status"] = "unexpected_negative_amount"
    if len(all_accessions) > 1:
        flags.append("mixed_filing_accessions")
    ocf, capex = row["ocf"], row["cash_capex"]
    compatible = (_signature(row["provenance"]["ocf"])
                  == _signature(row["provenance"]["cash_capex"]))
    row["fcf_cash"] = ocf - capex if ocf is not None and capex is not None and compatible else None
    row["fcf_status"] = "ocf_minus_cash_capex" if row["fcf_cash"] is not None else "missing_or_mixed_basis"
    capex_tags = {f["tag"] for f in row["provenance"]["cash_capex"].get("facts", [])}
    row["cash_capex_scope"] = ("유형자산" if capex_tags == {"PaymentsToAcquirePropertyPlantAndEquipment"}
        else "유형·소프트웨어·무형자산" if capex_tags == {"PaymentsToAcquireProductiveAssets"} else "미확인")
    row["comparability_flags"] = sorted(set(flags))
    row["missing_fields"] = [k for k in TAGS if row[k] is None]
    row["last_filed"] = max((f["filed"] for e in row["provenance"].values() for f in e.get("facts", [])), default=None)
    return row


def _yoy(row, history, field):
    end = _date(row["end"])
    matches = [old for old in history if old["fiscal_quarter"] == row["fiscal_quarter"]
               and 350 <= (end - _date(old["end"])).days <= 380
               and abs((_date(row["end"]) - _date(row["start"])).days
                       - (_date(old["end"]) - _date(old["start"])).days) <= 7]
    if len(matches) != 1:
        return None
    old = matches[0]
    current, base = row.get(field), old.get(field)
    if current is None or base is None or base <= 0:
        return None
    evidences = [x["provenance"][field] for x in (row, old)]
    if any(e.get("status") for e in evidences):
        return None
    if len({f["tag"] for e in evidences for f in e.get("facts", [])}) != 1:
        return None
    return (current / base - 1) * 100


def build_sec_quarter_review(company_facts, *, expected_cik, as_of):
    """Return up to eight observed quarters plus field provenance (USD only).

No estimates, ranking, score changes, stale fallback, debt proxy or price-based
valuation. Filing dates are not earnings-release dates. No claim that an 8-K
earnings release or company-specific XBRL extension has already been covered.
"""
    if (not isinstance(company_facts, dict) or not _cik(expected_cik)
            or _cik(company_facts.get("cik")) != _cik(expected_cik)):
        raise ValueError("cik_mismatch")
    cutoff = _date(as_of)
    if cutoff is None:
        raise ValueError("invalid_review_basis")
    filtered, issues = _filter_facts(company_facts, cutoff)
    _, records = build_sec_statement_records(filtered, TAGS, FLOW_FIELDS)
    history = [_decorate(row, filtered) for row in records]
    for row in history:
        row["yoy_pct"] = {field: _yoy(row, history, field) for field in ("revenue", "ocf", "cash_capex")}
        rev, op = row["revenue"], row["op_income"]
        row["op_margin_pct"] = (op / rev * 100 if rev and rev > 0 and op is not None
            and _signature(row["provenance"]["revenue"]) == _signature(row["provenance"]["op_income"]) else None)
    quarters = history[-8:]
    gaps = [{"after": a["end"], "before": b["start"]} for a, b in zip(quarters, quarters[1:])
            if _date(a["end"]) + timedelta(days=1) != _date(b["start"])]
    return {"review_only": True, "eligible_for_scoring": False, "latest_release_verified": False,
            "cik": _cik(expected_cik), "currency": "USD", "as_of": as_of,
            "quarter": quarters, "gaps": gaps, "issues": issues,
            "status": "quarter_evidence_only" if quarters else "no_supported_quarter_data",
            "definition": "fcf_cash = ocf - cash_capex; see cash_capex_scope/tag per quarter; excludes noncash leases, commitments and acquisitions"}


def quarter_tables(result):
    """Small human-readable table; the download retains unrounded base USD."""
    financial, quality, sources = [], [], []
    for r in result["quarter"]:
        amounts = {LABELS[k] + "(백만$)": None if r[k] is None else r[k] / 1e6 for k in TAGS}
        financial.append({"분기 시작": r["start"], "분기 종료": r["end"],
                          **amounts, "FCF(단순차감·백만$)": None if r["fcf_cash"] is None else r["fcf_cash"] / 1e6,
                          "투자지출 범위": r["cash_capex_scope"],
                          "매출 YoY(%)": r["yoy_pct"]["revenue"], "영업이익률(%)": r["op_margin_pct"]})
        withheld = [LABELS[k] + ": " + STATUS_LABELS.get(e["status"], e["status"])
                    for k, e in r["provenance"].items() if e.get("status")]
        derived = [LABELS[k] for k, e in r["provenance"].items()
                   if e.get("method") == "cumulative_difference" and not e.get("status")]
        if derived:
            withheld.append("누적차감 계산: " + ", ".join(derived))
        quality.append({"분기 시작": r["start"], "분기 종료": r["end"], "가장 최근 제출일": r["last_filed"],
                        "누락": ", ".join(LABELS[k] for k in r["missing_fields"]) or "없음",
                        "계산·공시 확인": "; ".join(withheld) or "직접 공시값",
                        "제출본 혼합": "예" if "mixed_filing_accessions" in r["comparability_flags"] else "아니오"})
        for field, e in r["provenance"].items():
            for f in e.get("facts", []):
                accession = f["accession"]
                sources.append({"분기 종료": r["end"], "항목": LABELS[field], "계산": e.get("method"),
                    "원기간 시작": f["start"], "원기간 종료": f["end"], "원금액(USD)": f["value"],
                    "태그": f["tag"], "제출일": f["filed"], "접수번호": accession,
                    "공시": f"https://www.sec.gov/Archives/edgar/data/{int(result['cik'])}/{accession.replace('-', '')}/{accession}-index.html"})
    return financial, quality, sources


def review_questions(result):
    """Facts and next checks, not a causal market narrative or recommendation."""
    if not result["quarter"]:
        return []
    r = result["quarter"][-1]
    basis = r["start"] + " ~ " + r["end"] + " · SEC 공시"
    yoy = r["yoy_pct"]["revenue"]
    revenue = f"매출 전년 동기 대비 {yoy:+.1f}%" if yoy is not None else "매출 전년 동기 비교 보류(기간·태그·양의 기준값 확인 필요)"
    rows = [{"검토축": "수요", "확인된 사실": revenue, "다음 확인": "회사 전체 매출과 AI·데이터센터 부문 매출을 구분하고, 다음 실적의 수주·가이던스를 확인", "기준": basis}]
    fcf = r["fcf_cash"]
    rows.append({"검토축": "투자와 현금", "확인된 사실": (
        f"영업현금흐름 {r['ocf']/1e6:,.1f} − 현금 투자지출 {r['cash_capex']/1e6:,.1f} = {fcf/1e6:,.1f}백만 USD ({r['cash_capex_scope']})"
        if fcf is not None else "동일 기준의 영업현금흐름·현금 투자지출 비교 보류"),
        "다음 확인": "리스·구매약정·현금잔고·차입 만기를 추가 확인. 이 차액만으로 현금 고갈 시점이나 적정가를 계산하지 않음", "기준": basis})
    return rows
