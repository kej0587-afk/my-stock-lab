"""Pure official strategic-outlook evidence, never quarterly actuals or signals.

The schema is issuer-independent; the first deliberately narrow adapter is
Oracle's Investor Day release. Unrecognized wording stays missing, not guessed.
"""

from datetime import datetime
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

ORACLE_ROOT = "https://investor.oracle.com"
TOPICS = {"capex": "CAPEX 계획", "free_cash_flow": "FCF 목표", "funding": "추가 자금조달",
          "funding_scope": "조달 한도 범위", "cash_mechanism": "현금 지출 완화 방식"}


def official_oracle_url(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "investor.oracle.com"
                and parsed.port is None and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
                and re.fullmatch(r"/investor-news/news-details/\d{4}/[A-Za-z0-9-]+/default.aspx", parsed.path) is not None)
    except (ValueError, TypeError):
        return False


def discover_oracle_outlook(payload, now):
    """Latest Investor Day in a bounded official list, not an earnings release."""
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    items = payload.get("GetPressReleaseListResult")
    if not isinstance(items, list):
        raise ValueError("invalid_ir_list")
    candidates = []
    for item in items[:60]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("Headline") or "")
        if not re.search(r"\bOracle Investor Day\b", title, re.I) or re.search(
                r"\b(?:to be held|will host|announces date|save the date)\b", title, re.I):
            continue
        try:
            day = datetime.strptime(str(item.get("PressReleaseDate")), "%m/%d/%Y %H:%M:%S").date()
        except ValueError:
            continue
        url = urljoin(ORACLE_ROOT, str(item.get("LinkToDetailPage") or ""))
        if official_oracle_url(url) and 0 <= (today - day).days <= 90:
            candidates.append(dict(title=title, date=day.isoformat(), source_url=url))
    return max(candidates, key=lambda r: (r["date"], r["source_url"])) if candidates else None


def _text(node):
    return " ".join(node.text_content().split())


def parse_oracle_outlook(content, candidate, now):
    """Require issuer, completed event, and matching publication dates first."""
    if not official_oracle_url(candidate.get("source_url")):
        raise ValueError("untrusted_ir_url")
    tree = html.fromstring(content)
    def field(cls):
        nodes = tree.xpath('//*[contains(concat(" ", normalize-space(@class), " "), $cls)]', cls=" " + cls + " ")
        if len(nodes) != 1:
            raise ValueError("ir_layout_changed")
        return _text(nodes[0])
    title, day_text, body = (field(cls) for cls in ("evergreen-news-title", "evergreen-news-date-text", "evergreen-news-body"))
    day = datetime.strptime(day_text, "%B %d, %Y").date()
    if (title != candidate["title"] or not re.search(r"\bOracle Investor Day\b", title, re.I)
            or day.isoformat() != candidate["date"]
            or not 0 <= (now.astimezone(ZoneInfo("America/New_York")).date() - day).days <= 90
            or not re.search(r"Oracle Corporation.*?today hosted an Investor Day", body, re.I)):
        raise ValueError("announcement_mismatch")
    # Boilerplate discusses hypothetical risks, not the disclosed plan.
    body = re.split(r"Safe Harbor Statement|About Oracle", body, maxsplit=1, flags=re.I)[0]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", body)
    metrics = {key: dict(status="missing", text="공식 원문에서 확인하지 못함") for key in TOPICS}
    def put(key, pattern, render, *, candidates=None):
        # Match whole sentences: dropping a trailing condition changes a plan.
        matches = [m for sentence in (sentences if candidates is None else candidates)
                   if (m := re.fullmatch(pattern, sentence, re.I))]
        if len(matches) == 1:
            metrics[key] = dict(status="confirmed", text=render(matches[0]), evidence=matches[0][0],
                                evidence_kind="company_outlook", source_url=candidate["source_url"])

    put("capex", r"Following a period of peak capex in (FY\d{2})[-–](FY\d{2}), capital expenditures are expected to step-down in (FY\d{2})(?:, supporting positive free cash flow of at least \$\d+(?:\.\d+)? billion in FY\d{2})?\.",
        lambda m: f"{m[1]}~{m[2]} 투자 정점 후 {m[3]} CAPEX 감소 예상 · 회사 전망")
    put("free_cash_flow", r"Defined timeline to positive free cash flow during the second half of (FY\d{2}) and set free cash flow target of \$(\d+(?:\.\d+)?) billion\+ for (FY\d{2})\.",
        lambda m: f"{m[1]} 하반기 FCF 흑자 전환, {m[3]} USD {m[2]} billion 이상 목표 · 실현값 아님")
    funding_pattern = r"Oracle committed to limiting additional funding to be raised in the capital markets for its (FY\d{2})[-–](FY\d{2}) investment cycle to \$(\d+(?:\.\d+)?) billion, currently expected to be \$(\d+(?:\.\d+)?) billion in equity and \$(\d+(?:\.\d+)?) billion in gross debt\."
    put("funding", funding_pattern,
        lambda m: f"{m[1]}~{m[2]} 추가 조달 한도 USD {m[3]} billion · 주식 {m[4]} / 총부채 {m[5]} billion 계획")
    # The scope must immediately qualify this funding plan, not a prior cycle.
    funding_scopes = [" ".join(sentences[i + 1:i + 3]) for i, sentence in enumerate(sentences)
                      if re.fullmatch(funding_pattern, sentence, re.I)]
    put("funding_scope", r"This incremental funding requirement excludes refinancing of existing debt\. This is in addition to the \$(\d+(?:\.\d+)?) billion at-the-market equity raise completed in the first quarter of fiscal (\d{4})\.",
        lambda m: f"기존 부채 차환 제외 · FY{m[2]} 1분기 완료 ATM 증자 USD {m[1]} billion과 별도", candidates=funding_scopes)
    put("cash_mechanism", r"Vendor financing, customer-provided hardware and customer prepayments are expected to reduce upfront cash requirements(?: through the transition to positive free cash flow)?\.",
        lambda m: "공급업체 금융·고객 제공 하드웨어·고객 선수금으로 초기 현금 소요 완화 예상")
    # An amount without its exclusions is not a verified all-in funding ceiling.
    if metrics["funding_scope"]["status"] != "confirmed":
        metrics["funding"] = dict(status="missing", text="조달 한도 조건·기존 조달과의 관계 미확인")
    else:
        metrics["funding_scope"]["evidence_kind"] = "reported_scope_and_completed_funding"
    return dict(ticker="ORCL", issuer="Oracle", event_kind="investor_day", evidence_kind="company_outlook",
                title=title, published_date=day.isoformat(), published_precision="date", observed_at=now.isoformat(),
                source_url=candidate["source_url"], metrics=metrics,
                status="confirmed" if all(m["status"] == "confirmed" for m in metrics.values()) else "partial")
