"""Pure, source-bound MSFT segment/outlook evidence. No scoring or forecasts."""

from datetime import date, datetime
import hashlib
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)

ROOT = "https://www.microsoft.com"
HOME = ROOT + "/en-us/investor/default"
_RELEASE = r"/en-us/investor/earnings/fy-(\d{4})-q([1-4])/press-release-webcast"
_CALL = r"/en-us/investor/events/fy-(\d{4})/earnings-fy-\1-q([1-4])"
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_DAY = _MONTH + r" \d{1,2}, \d{4}"
_NUMBER = r"\d+(?:\.\d+)?"
_ORDINALS = ("first", "second", "third", "fourth")


def source_identity(url):
    """Exact public issuer paths, no redirects, alternate hosts or credentials."""
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname != "www.microsoft.com" or p.port
                or p.username or p.password or p.query or p.fragment):
            return None
        path = p.path.lower()
        if path == "/en-us/investor/default":
            return ("home", None, None)
        for kind, pattern in (("release", _RELEASE), ("call", _CALL)):
            m = re.fullmatch(pattern, path)
            if m:
                return (kind, int(m[1]), int(m[2]))
    except (ValueError, TypeError):
        pass
    return None


def discover_msft_release(content):
    tree = html.fromstring(content)
    found = {}
    for a in tree.xpath('//a[@href]'):
        url = urljoin(HOME, a.get("href")).lower()
        identity = source_identity(url)
        if identity and identity[0] != "home":
            kind, year, quarter = identity
            found.setdefault((year, quarter), {})[kind] = url
    candidates = [(period, urls) for period, urls in found.items() if "release" in urls]
    if not candidates:
        raise ValueError("release_link_missing")
    (year, quarter), urls = max(candidates)
    return dict(fiscal_year=year, fiscal_quarter=quarter, **urls)


def _body(content):
    tree = html.fromstring(content)
    main = tree.xpath('//main')
    if len(main) != 1:
        raise ValueError("ir_layout_changed")
    main = main[0]
    for node in main.xpath('.//script|.//style|.//nav|.//footer'):
        node.drop_tree()
    return " ".join(main.text_content().split())


def _day(text):
    return datetime.strptime(text, "%B %d, %Y").date()


def _quarter_end(year, quarter):
    return date(year - 1, 9, 30) if quarter == 1 else date(year - 1, 12, 31) if quarter == 2 else date(year, 3, 31) if quarter == 3 else date(year, 6, 30)


def _unique(pattern, text):
    found = list(re.finditer(pattern, text, re.I))
    return found[0] if found and len({m.groups() for m in found}) == 1 else None


def _metric(key, label, value, *, unit, kind, scope, period, url, match, operator="eq", decimals=None):
    # Numeric facts only in excerpts; full matching text is identified by hash.
    fragment = re.search(rf"{_NUMBER}%" if unit == "percent_yoy" else rf"\${_NUMBER} billion", match[0])
    return dict(key=key, label=label, value=value, unit=unit, kind=kind, scope=scope,
        period=period, source_url=url, operator=operator, decimals=decimals,
        source_excerpt=fragment[0] if fragment else "free cash flow positive" if "free cash flow positive" in match[0] else "",
        match_sha256=hashlib.sha256(match[0].encode()).hexdigest(), status="confirmed")


def parse_msft_release(content, candidate, now):
    year, quarter = candidate["fiscal_year"], candidate["fiscal_quarter"]
    if source_identity(candidate.get("release")) != ("release", year, quarter):
        raise ValueError("untrusted_ir_url")
    text = _body(content)
    expected = _quarter_end(year, quarter)
    heading = re.search(rf"Earnings Release FY(?:{year}|{str(year)[-2:]}) Q{quarter}\b", text, re.I)
    lead = re.search(rf"REDMOND, Wash\.\s*[—–-]\s*({_DAY})\s*[—–-]\s*Microsoft Corp\. today announced.*?quarter ended ({_DAY})", text, re.I)
    if (not heading or not lead or _day(lead[2]) != expected
            or not expected <= _day(lead[1]) <= now.astimezone(ZoneInfo("America/New_York")).date()):
        raise ValueError("release_period_mismatch")
    actual = text[lead.end():].split("Business Outlook", 1)[0]
    period = f"FY{year}Q{quarter} · {expected.isoformat()} 종료"
    metrics = []
    def add_money(key, label, pattern, scope):
        m = _unique(pattern, actual)
        if m:
            metrics.append(_metric(key, label, float(m[1]), unit="USD_billion", kind="reported_actual",
                scope=scope, period=period, url=candidate["release"], match=m,
                decimals=len(m[1].split(".")[1]) if "." in m[1] else 0))
    add_money("company_revenue", "회사 전체 매출", rf"(?:^|[·•])\s*Revenue was \$({_NUMBER}) billion", "company_total")
    add_money("cloud_revenue", "Microsoft Cloud 매출", rf"Microsoft Cloud revenue was \$({_NUMBER}) billion", "overlapping_cloud_metric")
    # Keep current names; do not splice older Intelligent Cloud/PBP definitions.
    segment_matches = list(re.finditer(rf"Revenue in ([A-Za-z &-]{{2,70}}) was \$({_NUMBER}) billion and (increased|decreased) ({_NUMBER})%", actual))
    by_name = {}
    for m in segment_matches:
        by_name.setdefault(m[1], []).append(m)
    for name, matches in by_name.items():
        if len({m.groups() for m in matches}) != 1:
            continue
        m = matches[0]
        metric = _metric("segment:" + name, name + " 매출", float(m[2]), unit="USD_billion",
            kind="reported_actual", scope="reported_segment", period=period, url=candidate["release"], match=m)
        metric["growth_yoy_pct"] = float(m[4]) * (-1 if m[3] == "decreased" else 1)
        metrics.append(metric)
    for key, label, pattern in (
        ("azure_growth", "Azure 매출 증가율", rf"Azure(?: and other cloud services)? revenue increased ({_NUMBER})%"),
        ("cloud_growth", "Microsoft Cloud 매출 증가율", rf"Microsoft Cloud revenue was \${_NUMBER} billion and increased ({_NUMBER})%")):
        m = _unique(pattern, actual)
        if m:
            metrics.append(_metric(key, label, float(m[1]), unit="percent_yoy", kind="reported_actual",
                scope="product_metric" if key == "azure_growth" else "overlapping_cloud_metric",
                period=period, url=candidate["release"], match=m))
    return dict(ticker="MSFT", cik="0000789019", fiscal_year=year, fiscal_quarter=quarter,
        period_start=date(expected.year, expected.month-2, 1).isoformat(),
        period_end=expected.isoformat(), release_date=_day(lead[1]).isoformat(),
        checked_at=now.isoformat(), source_url=candidate["release"], metrics=metrics,
        segment_recast=bool(re.search(r"recast.*?changes to our segments", text, re.I)),
        review_only=True, eligible_for_scoring=False, consensus_status="not_connected",
        source_hashes={"release": hashlib.sha256(content).hexdigest()}, issues=[])


def attach_msft_call(packet, content, candidate):
    year, q = packet["fiscal_year"], packet["fiscal_quarter"]
    if source_identity(candidate.get("call")) != ("call", year, q):
        raise ValueError("untrusted_ir_url")
    text = _body(content)
    if not re.search(rf"Microsoft Fiscal Year {year} {_ORDINALS[q-1]} Quarter Earnings Conference Call", text, re.I):
        raise ValueError("call_period_mismatch")
    dates = re.findall(_DAY, text[:1000])
    if not dates or any(_day(d).isoformat() != packet["release_date"] for d in dates):
        raise ValueError("call_date_mismatch")
    # Only prepared remarks: Q&A can mix analyst estimates and other periods.
    prepared = re.split(r"With that, let[’']s go to Q&A", text, maxsplit=1, flags=re.I)
    if len(prepared) != 2:
        raise ValueError("prepared_remarks_boundary_missing")
    sections = re.split(r"Now, moving to the outlook for our (first|second|third|fourth) quarter", prepared[0], maxsplit=1, flags=re.I)
    if len(sections) != 3:
        raise ValueError("outlook_boundary_missing")
    actual, ordinal, outlook = sections
    if not re.search(r"US dollar basis", outlook[:250], re.I):
        raise ValueError("guidance_currency_unverified")
    next_q = _ORDINALS.index(ordinal.lower()) + 1
    if next_q != q % 4 + 1:
        raise ValueError("guidance_period_mismatch")
    next_year = year + (q == 4)
    period = f"FY{year}Q{q} · {packet['period_end']} 종료"
    forward_period = f"FY{next_year}Q{next_q} · {_quarter_end(next_year,next_q).isoformat()} 종료 예상"
    metric_rows = []
    leases_included = bool(re.search(r"recognize the full principal value of finance leases in capex at the time of lease commencement", actual, re.I))
    for key, label, pattern, scope in (
        ("reported_capex", "회사 발표 CAPEX", rf"Capital expenditures were \$({_NUMBER}) billion", "includes_finance_lease_principal" if leases_included else "unverified_capex_scope"),
        ("finance_leases", "당분기 금융리스", rf"This quarter, finance leases were \$({_NUMBER}) billion", "finance_leases"),
        ("cash_ppe", "현금 유형자산 지출", rf"cash paid for P, P, and E was \$({_NUMBER}) billion", "cash_ppe"),
        ("ocf", "영업현금흐름", rf"Cash flow from operations was \$({_NUMBER}) billion", "company_total"),
        ("reported_fcf", "회사 발표 FCF", rf"free cash flow was \$({_NUMBER}) billion", "company_defined_fcf")):
        m = _unique(pattern, actual)
        if m:
            metric_rows.append(_metric(key, label, float(m[1]), unit="USD_billion", kind="reported_actual",
                scope=scope, period=period, url=candidate["call"], match=m,
                decimals=len(m[1].split(".")[1]) if "." in m[1] else 0))
    m = _unique(rf"In Q{next_q}, we expect CapEx spend will be over \$({_NUMBER}) billion\.", outlook)
    if m:
        metric_rows.append(_metric("next_capex", "다음 분기 CAPEX 전망", float(m[1]), unit="USD_billion",
            kind="management_outlook", scope="company_reported_capex_not_cash_ppe", period=forward_period,
            url=candidate["call"], match=m, operator="gt"))
    m = _unique(r"expect to continue to remain free cash flow positive in FY(\d{2})", outlook)
    if m:
        metric_rows.append(_metric("fy_fcf", "회계연도 FCF 전망", "흑자 유지 예상", unit="qualitative",
            kind="management_outlook", scope="company_defined_fcf", period="FY20" + m[1], url=candidate["call"], match=m))
    packet["metrics"].extend(metric_rows)
    packet["source_hashes"]["call"] = hashlib.sha256(content).hexdigest()
    packet["call_url"] = candidate["call"]
    return packet


def reconcile_sec(packet, sec_result):
    """Compare rounded disclosure only to same-period/scope review evidence."""
    rows = (sec_result or {}).get("quarter", [])
    matching = [r for r in rows if r.get("end") == packet["period_end"] and r.get("start") == packet["period_start"] and r.get("unit") == "USD"
                and r.get("is_single_quarter") is True]
    if (not sec_result or sec_result.get("ticker") != "MSFT" or sec_result.get("cik") != "0000789019"
            or sec_result.get("currency") != "USD" or len(matching) != 1):
        return [{"항목": "SEC 대조", "상태": "동일 종목·분기 8분기 자료를 먼저 조회", "IR(십억$)": None, "SEC(십억$)": None}]
    record = matching[0]
    output = []
    for metric in packet["metrics"]:
        field = {"company_revenue": "revenue", "cash_ppe": "cash_capex", "ocf": "ocf", "reported_fcf": "fcf_cash"}.get(metric["key"])
        if not field:
            continue
        value = record.get(field)
        scope_ok = field not in {"cash_capex", "fcf_cash"} or record.get("cash_capex_scope") == "유형자산"
        tolerance = .5 * 10 ** -(metric["decimals"] or 0)
        if value is None or not scope_ok:
            status = "SEC 값·범위 확인 필요"
        elif abs(metric["value"] - value / 1e9) <= tolerance + 1e-9:
            status = "표시 반올림 범위 내 일치" + (" · FCF 정의 동일성은 별도 확인" if field == "fcf_cash" else "")
        else:
            status = "불일치 · 원공시 확인 필요"
        output.append({"항목": metric["label"], "상태": status, "IR(십억$)": metric["value"],
                       "SEC(십억$)": None if value is None else value / 1e9})
    return output


def business_reading(packet):
    """Limited business implications, never a claim about share-price causality."""
    by_key = {m["key"]: m for m in packet["metrics"]}
    lines = []
    if "cloud_growth" in by_key and "azure_growth" in by_key:
        lines.append(("사실", f"Microsoft Cloud 매출은 전년 동기 대비 {by_key['cloud_growth']['value']:g}%, Azure 매출은 {by_key['azure_growth']['value']:g}% 증가했습니다.", packet["source_url"]))
        lines.append(("해석(추정)", "클라우드 수요 확대를 뒷받침하지만, 이 성장률만으로 AI 단독 매출·수익성이나 주가 상승 원인을 확정할 수 없습니다.", packet["source_url"]))
    if "next_capex" in by_key:
        m = by_key["next_capex"]
        lines.append(("회사 전망", f"{m['period']} CAPEX는 {m['value']:g}십억 USD 초과를 예상했습니다. 현금 유형자산 지출 전망으로 대체하지 않습니다.", m["source_url"]))
        lines.append(("다음 확인", "다음 실적에서 Azure 성장 지속 여부와 현금 투자지출·영업현금흐름을 함께 비교합니다. 리스 포함 CAPEX, 현금 지출, 납품 일정은 각각 확인합니다.", m["source_url"]))
    else:
        lines.append(("미확인", "다음 분기 투자 전망을 검증하지 못했습니다. 기존 분기 실적을 미래 예상치로 사용하지 않습니다.", packet["source_url"]))
    return lines
