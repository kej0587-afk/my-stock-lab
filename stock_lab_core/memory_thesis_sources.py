"""Read-only memory-company evidence. Never supplies decision-engine inputs."""

from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

from stock_lab_core.earnings_result_pdf import _read_pdf
from stock_lab_core.result_cache import cache_result
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

COMPANIES = {
    "005930": {
        "name": "삼성전자", "release": "2026-10-29", "period": "2026Q3",
        "pdf": "https://images.samsung.com/is/content/samsung/assets/global/ir/docs/2026_3Q_conference_eng.pdf",
        "ir": "https://news.samsung.com/global/samsung-electronics-announces-third-quarter-2026-results",
    },
    "000660": {
        "name": "SK하이닉스", "release": "2026-10-28", "period": "2026Q3",
        "pdf": "https://mis-prod-koce-homepage-cdn-01-blob-ep.azureedge.net/web/attach/21435786328187801.pdf",
        "ir": "https://news.skhynix.com/en/q3-2026-business-results/",
    },
}


def number(value):
    try:
        result = float(str(value).strip().replace(",", "").replace("(", "-").replace(")", ""))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def parse_consensus(html, code, now):
    """Decode provider JSON, not executable JS; annual estimates are not TTM."""
    soup = BeautifulSoup(html, "html.parser")
    identity = soup.find("input", id="cmp_cd")
    heading = soup.find("h1", id="giName")
    if not identity or identity.get("value") != code or not heading:
        raise ValueError("consensus_identity_mismatch")
    expected = COMPANIES[code]["name"].replace(" ", "").casefold()
    if heading.get_text(strip=True).replace(" ", "").casefold() != expected:
        raise ValueError("consensus_name_mismatch")
    quote_heading = soup.find("h2", string=lambda s: s and s.strip() == "시세현황")
    date_node = quote_heading.parent.find("span", class_="date") if quote_heading else None
    match = re.search(r"20\d{2}/\d{2}/\d{2}", date_node.get_text() if date_node else "")
    if not match:
        raise ValueError("quote_date_missing")
    asof = datetime.strptime(match[0], "%Y/%m/%d").date()
    if asof > now.astimezone(ZoneInfo("Asia/Seoul")).date():
        raise ValueError("future_quote")
    caption = soup.find("caption", string="시세현황")
    close = None
    for th in caption.parent.find_all("th") if caption else []:
        if re.sub(r"\s", "", th.get_text()).startswith("종가/전일대비/수익률"):
            cell = th.find_next_sibling("td")
            close = number(cell.get_text().split("/")[0]) if cell else None
    if close is None or close <= 0:
        raise ValueError("regular_close_missing")
    table = soup.find("table", id="snpFinancial")
    if table is None or not re.search(r"단위\s*:\s*억원", table.parent.parent.get_text()):
        raise ValueError("financial_unit_unverified")
    blocks = []
    for script in soup.find_all("script"):
        text = script.get_text()
        for found in re.finditer(r"\bsnpFinancial\s*:\s*", text):
            blocks.append(json.JSONDecoder().raw_decode(text[found.end():])[0])
    if len(blocks) != 1:
        raise ValueError("financial_payload_ambiguous")
    block = blocks[0]
    if (not isinstance(block, dict) or not isinstance(block.get("header"), list)
            or not isinstance(block.get("data"), list)
            or not all(isinstance(h, dict) and isinstance(h.get("YYMM"), str) for h in block["header"])
            or not all(isinstance(r, dict) and isinstance(r.get("NAME"), str) for r in block["data"])):
        raise ValueError("financial_payload_schema_changed")
    headers = block["header"][:4]
    years = []
    for i, h in enumerate(headers):
        if (h.get("CD") != f"VAL{i + 1}" or h.get("CONSOL_TYPE") != "연결"
                or not re.fullmatch(r"20\d{2}/12", h.get("YYMM", ""))):
            raise ValueError("annual_consolidated_layout_changed")
        years.append(int(h["YYMM"][:4]))
    if len(years) != 4 or any(b != a + 1 for a, b in zip(years, years[1:])):
        raise ValueError("annual_periods_unverified")
    estimates = [h for h in headers if h.get("EP_CHK") == "E"]
    if not estimates:
        raise ValueError("annual_estimate_missing")
    estimate = estimates[-1]
    rows = block["data"]

    def value(label):
        matches = [r for r in rows if r.get("NAME", "").strip() == label]
        return number(matches[0].get(estimate["CD"])) if len(matches) == 1 else None

    return {
        "ok": True, "close": close, "price_asof": asof.isoformat(),
        "estimate_period": estimate["YYMM"], "estimate_asof": None,
        "revenue_100m": value("매출액"), "operating_profit_100m": value("영업이익(발표기준)"),
        "net_profit_100m": value("당기순이익(지배)"), "eps": value("EPS"), "bps": value("BPS"),
    }


def parse_cash_pages(pages, code):
    """Only known issuer/quarter/unit layouts; adjacent chart numbers are excluded."""
    first = " ".join(pages[1].split())
    if code == "005930":
        if not re.search(r"SAMSUNG ELECTRONICS.*3Q 2026 Earnings Call", first):
            raise ValueError("cash_identity_mismatch")
        cash = pages[15]
        if not (cash.startswith("Appendix 4: Cash Flow (Summary)") and
                re.search(r"KRW trillion\s+3Q 25\s+2Q 26\s+3Q 26", cash)):
            raise ValueError("cash_period_or_unit_mismatch")
        ocf_label, capex_label = "Cash flows from operating activities", "Purchase of PP&E"
        index, previous, scale = 2, 1, 1.0
        suffixes = r"(?:Net Cash\b.*)?", r"(?:•.*)?"
    else:
        if not ("FY2026" in first and "2026.10.28" in first and
                "SK hynix" in pages[2] and "FY2026 Q3" in pages[2]):
            raise ValueError("cash_identity_mismatch")
        cash = pages[16]
        if not re.search(r"Unit : KRW Billion\).*?26 Q3.*?26 Q2.*?25 Q3", cash):
            raise ValueError("cash_period_or_unit_mismatch")
        ocf_label, capex_label = "CF from Operating Activities", "Acquisition of PP&E"
        index, previous, scale = 0, 1, 0.001
        suffixes = r"(?:D&A\b.*)?", r"(?:F/X Effect, etc\..*)?"

    def row(label, suffix):
        n = r"(\(?-?\d[\d,]*(?:\.\d+)?\)?)"
        matches = re.findall(r"^" + re.escape(label) + r"[ \t]+" + n + r"[ \t]+" + n + r"[ \t]+" + n + r"[ \t]*" + suffix + r"$", cash, re.M)
        if len(matches) != 1:
            raise ValueError("cash_row_missing_or_ambiguous")
        return [number(v) * scale for v in matches[0]]

    ocf, pp = row(ocf_label, suffixes[0]), row(capex_label, suffixes[1])
    if pp[index] > 0:
        raise ValueError("capex_cash_outflow_sign_unverified")
    return {"ok": True, "period": "2026Q3", "ocf_trillion": ocf[index],
            "prior_ocf_trillion": ocf[previous], "cash_ppe_trillion": -pp[index],
            "cash_surplus_trillion": ocf[index] + pp[index], "reported_fcf": None,
            "page": 15 if code == "005930" else 16}


def _download(url, limit):
    # Fixed public URLs only, bounded payload and network time, no credentials.
    with requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(3, 10), stream=True) as response:
        response.raise_for_status()
        if urlsplit(response.url).hostname != urlsplit(url).hostname:
            raise ValueError("unexpected_source_redirect")
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > limit:
                raise ValueError("source_size_limit")
            chunks.append(chunk)
        return b"".join(chunks)


@cache_result(ttl=21600, failure_ttl=60)
def fetch_memory_evidence(code, kind):
    spec = COMPANIES[code]
    now = datetime.now(timezone.utc)
    url = f"https://wcomp.fnguide.com/CompanyInfo/Snapshot?cmp_cd={code}" if kind == "consensus" else spec["pdf"]
    try:
        if kind == "consensus":
            result = parse_consensus(_download(url, 3_000_000).decode("utf-8-sig"), code, now)
        elif kind == "cash":
            if now.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat() < spec["release"]:
                raise ValueError("future_result")
            indices = (0, 14) if code == "005930" else (0, 1, 15)
            pages, _ = _read_pdf(_download(url, 8_000_000), indices, now, ZoneInfo("Asia/Seoul"))
            result = parse_cash_pages(pages, code)
        else:
            raise ValueError("unsupported_evidence")
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as exc:
        reason = f"HTTP {exc.response.status_code}" if isinstance(exc, requests.HTTPError) and exc.response is not None else type(exc).__name__
        if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc)):
            reason += ": " + str(exc)
        result = {"ok": False, "reason": reason}
    return dict(result, source_url=url, fetched_at=now.isoformat())
