"""DART reported amounts only: no quarter subtraction, FCF model or scores."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import re
from zoneinfo import ZoneInfo

from stock_lab_core.dart_evidence import canonical_bytes, validate_rows
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

ENDPOINT = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
_CODES = {3: ("11013", "분기", 1), 6: ("11012", "반기", 2),
          9: ("11014", "분기", 3), 0: ("11011", "사업", 4)}
_ACCOUNTS = {
    "revenue": ("매출", {"Revenue"}, {"매출액", "수익(매출액)", "매출", "영업수익"}, {"IS", "CIS"}),
    "operating_profit": ("영업이익", {"OperatingIncomeLoss"}, {"영업이익", "영업이익(손실)", "영업손익"}, {"IS", "CIS"}),
    "net_income": ("당기순이익", {"ProfitLoss"}, {"당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)"}, {"IS", "CIS"}),
    "operating_cash_flow": ("영업활동현금흐름", {"CashFlowsFromUsedInOperatingActivities"},
                            {"영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로부터의현금흐름"}, {"CF"}),
    "tangible_purchases": ("유형자산 취득 현금유출(전체 CAPEX 아님)", {"PurchaseOfPropertyPlantAndEquipment"},
                           {"유형자산의취득", "유형자산취득"}, {"CF"}),
    "capex": ("공시 CAPEX", set(), {"설비투자", "자본적지출"}, {"CF"}),
    "free_cash_flow": ("공시 FCF", set(), {"잉여현금흐름"}, {"CF"}),
}


def report_spec(event, company, corp):
    """Map official fiscal close month, then require the API to confirm the code."""
    if company.get("status") != "000":
        raise ValueError("dart_company_api_error")
    if (company.get("corp_code", corp) != corp
            or company.get("stock_code") != event["ticker"].split(".")[0]):
        raise ValueError("dart_company_identity_mismatch")
    close = str(company.get("acc_mt", ""))
    period = str(event.get("reporting_period_end_month", ""))
    if not re.fullmatch(r"(?:0[1-9]|1[0-2])", close) or not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", period):
        raise ValueError("dart_fiscal_calendar_unavailable")
    year, month = map(int, period.split("-"))
    offset = (month - int(close)) % 12
    if offset not in _CODES:
        raise ValueError("dart_fiscal_calendar_mismatch")
    code, kind, quarter = _CODES[offset]
    if not re.fullmatch(r"(?:\[[^]]+\]\s*)*" + kind + r"보고서\s*\(" + period.replace("-", r"\.") + r"\)", event["event"]):
        raise ValueError("dart_report_kind_mismatch")
    year += month > int(close)
    fiscal = f"FY{year}" + (f"Q{quarter}" if code != "11011" else " 연간·4분기값 아님")
    receipt = event.get("filing_receipt", "")
    if not re.fullmatch(r"\d{14}", receipt):
        raise ValueError("dart_receipt_unavailable")
    return dict(corp_code=corp, year=str(year), report_code=code, fiscal_period=fiscal,
                fiscal_close_month=close, reporting_period_end_month=period, receipt=receipt)


def _amount(value):
    raw = str(value if value is not None else "").strip().replace("−", "-")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
        return None
    try:
        amount = Decimal(raw.replace(",", ""))
        return format(amount, "f") if amount.is_finite() else None
    except InvalidOperation:
        return None


def _account(rows, key):
    _, ids, names, statements = _ACCOUNTS[key]
    candidates = []
    for row in rows:
        if row["sj_div"] not in statements or (row.get("account_detail") or "").strip() not in {"", "-"}:
            continue
        account = row["account_id"]
        standard = account.startswith(("ifrs-full_", "ifrs_", "dart_"))
        matched_id = standard and account.split("_", 1)[-1] in ids
        matched_name = not standard and re.sub(r"\s+", "", row["account_nm"]) in names
        if matched_id or matched_name:
            candidates.append((matched_id, row))
    if not candidates:
        return None, "account_not_reported"
    priority = max(level for level, _ in candidates)
    chosen = [row for level, row in candidates if level == priority]
    signatures = {(r.get("thstrm_amount"), r.get("thstrm_add_amount"), r.get("currency")) for r in chosen}
    if len(signatures) != 1:
        return None, "ambiguous_account"
    return chosen[0], ""


def _metric(rows, key, spec, fs_div, url):
    row, reason = _account(rows, key)
    empty = dict(status="missing", text="", source_url=url, reason=reason, label=_ACCOUNTS[key][0])
    if row is None:
        return empty
    currency = row.get("currency") or ""
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return {**empty, "reason": "currency_unavailable"}
    current, cumulative = _amount(row.get("thstrm_amount")), _amount(row.get("thstrm_add_amount"))
    annual = spec["report_code"] == "11011"
    income = row["sj_div"] in {"IS", "CIS"}
    quarter = current if income and not annual else None
    ytd = cumulative if income and not annual else current if not annual else None
    annual_value = current if annual else None
    parts = [("분기(3개월)", quarter), ("누적", ytd), ("연간(4분기값 아님)", annual_value)]
    parts = [f"{label} {Decimal(value):,} {currency}" for label, value in parts if value is not None]
    if not parts:
        return {**empty, "reason": "amount_unavailable"}
    basis = "연결" if fs_div == "CFS" else "별도"
    scope = "annual" if annual else "quarter_and_ytd" if quarter is not None else "year_to_date"
    return dict(status="reported", text=f"{_ACCOUNTS[key][0]} · {basis} · " + " / ".join(parts),
                label=_ACCOUNTS[key][0], source_url=url, period_scope=scope,
                quarter_value=quarter, cumulative_value=ytd, annual_value=annual_value,
                currency=currency, fs_div=fs_div, account_id=row["account_id"], account_name=row["account_nm"],
                raw_current=row.get("thstrm_amount"), raw_cumulative=row.get("thstrm_add_amount"),
                extraction="direct_dart_fields", fiscal_period=spec["fiscal_period"])


def parse_financials(payload, event, spec, fs_div, now):
    status = payload.get("status")
    if status != "000":
        raise ValueError("dart_financial_no_data" if status == "013" else "dart_financial_api_error")
    rows = payload.get("list")
    validate_rows(rows, corp_code=spec["corp_code"], year=spec["year"], report_code=spec["report_code"], fs_div=fs_div)
    if {row["rcept_no"] for row in rows} != {spec["receipt"]}:
        raise ValueError("dart_financial_receipt_mismatch")
    if date.fromisoformat(event["date"]) > now.astimezone(ZoneInfo("Asia/Seoul")).date():
        raise ValueError("dart_future_receipt")
    url = event["source_url"]
    if url != "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + spec["receipt"]:
        raise ValueError("dart_financial_source_mismatch")
    values = {key: _metric(rows, key, spec, fs_div, url) for key in _ACCOUNTS}
    if not any(metric["status"] == "reported" for metric in values.values()):
        raise ValueError("dart_supported_accounts_unavailable")
    metrics = {key: deepcopy(values[key]) for key in ("revenue", "capex", "free_cash_flow", "operating_cash_flow")}
    profits = [values[key] for key in ("operating_profit", "net_income") if values[key]["status"] == "reported"]
    metrics["profit"] = dict(status="reported" if profits else "missing", source_url=url,
                             text=" / ".join(item["text"] for item in profits), components=deepcopy(profits))
    metrics["guidance"] = dict(status="missing", text="", reason="outlook_not_in_financial_statements", source_url="")
    proof = dict(provider="dart_discovered_financials", **spec, fs_div=fs_div,
                 content_sha256=hashlib.sha256(canonical_bytes(payload)).hexdigest())
    enriched = {**deepcopy(event), "fiscal_period": spec["fiscal_period"], "financial_discovery": proof}
    result = dict(ticker=event["ticker"], fiscal_period=spec["fiscal_period"], status="official_filing_result",
                  filing_date=event["date"], release_date=None, release_at=None, release_precision="unknown",
                  source_url=url, checked_at=now.isoformat(), collection_reason="dart_report_accounts",
                  provenance=proof, metrics=metrics, financial_values=values)
    return enriched, result


def matched_financial_result(event, results, now):
    """Receipt identity, not a nearby announcement date, joins these records."""
    proof = event.get("financial_discovery") or {}
    for result in results:
        try:
            checked = datetime.fromisoformat(result["checked_at"])
            if (result.get("status") == "official_filing_result" and proof.get("provider") == "dart_discovered_financials"
                    and result.get("provenance") == proof and result.get("ticker") == event["ticker"]
                    and result.get("fiscal_period") == event["fiscal_period"]
                    and result.get("filing_date") == event["date"]
                    and event.get("filing_receipt") == proof.get("receipt")
                    and event.get("filing_corp_code") == proof.get("corp_code")
                    and result.get("source_url") == event.get("source_url")
                    and event["source_url"] == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + proof["receipt"]
                    and re.fullmatch(r"[a-f0-9]{64}", proof.get("content_sha256", ""))
                    and checked.tzinfo is not None and checked <= now
                    and date.fromisoformat(event["date"]) <= now.astimezone(ZoneInfo("Asia/Seoul")).date()):
                return deepcopy(result)
        except (ValueError, KeyError, TypeError):
            continue
    return None
