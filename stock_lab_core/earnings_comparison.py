"""Period-bound earnings evidence for the observatory, never scoring inputs.

Yahoo's rolling 0q/+1q estimates are not announcement-time consensus. Only
the estimate and actual in the same earningsHistory row are paired. Stored
filing revenue is checked separately; it never supplies an EPS or consensus.
"""

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import math
import re
from urllib.parse import quote

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.yahoo_metadata import yahoo_metadata_reader

register_loaded_source(__name__, __file__)

TTL = 900
MAX_ROWS = 16
MODULES = "earningsHistory,earningsTrend,incomeStatementHistoryQuarterly,financialData,quoteType"
SOURCE = "Yahoo Finance 분기 실적·예상"
_STATUS = {"available": "연결", "no_data": "자료 미제공", "error": "조회 실패",
           "rate_limited": "조회 제한", "stale": "이전 자료 · 비교 보류",
           "invalid_ticker": "종목코드 확인 필요", "etf_excluded": "기업 실적 해당없음"}


def _map(value):
    return value if isinstance(value, Mapping) else {}


def _raw(value):
    return value.get("raw") if isinstance(value, Mapping) else value


def _number(value):
    value = _raw(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def _day(value):
    if isinstance(value, Mapping):
        formatted, raw = _day(value.get("fmt")), _number(value.get("raw"))
        if raw is not None:
            try:
                observed = datetime.fromtimestamp(raw, timezone.utc).date().isoformat()
            except (ValueError, OverflowError, OSError):
                return None
            return observed if formatted is None or formatted == observed else None
        return formatted
    try:
        return date.fromisoformat(value).isoformat() if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def _currency(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value) else None


def _rows(value):
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _unique_by_day(rows, key):
    # Conflicting or repeated periods are withheld, not resolved by input order.
    grouped = {}
    for row in rows:
        day = _day(row.get(key))
        if day:
            grouped.setdefault(day, []).append(row)
    return {day: items[0] for day, items in grouped.items() if len(items) == 1}


def _basis(value):
    return {"gaap": "GAAP", "non-gaap": "조정(Non-GAAP)", "nongaap": "조정(Non-GAAP)", "nonGaap": "조정(Non-GAAP)",
            "normalized": "조정(Normalized)"}.get(value if isinstance(value, str) else "", "회계기준 미제공")


def _fetch(symbol):
    import yfinance as yf
    from stock_lab_core.yahoo_transport import yahoo_session_kwargs

    # Preserve endDate/currency/methodology, which the public estimate DataFrames
    # omit in supported yfinance versions. Keep this private API in one adapter.
    ticker = yf.Ticker(symbol, **yahoo_session_kwargs())
    payload = ticker._data.get_raw_json(
        "https://query2.finance.yahoo.com/v10/finance/quoteSummary/" + quote(symbol, safe=""),
        params={"modules": MODULES, "formatted": "false", "symbol": symbol}, timeout=6,
    )
    results = _map(_map(payload).get("quoteSummary")).get("result")
    if not isinstance(results, list) or len(results) != 1:
        return {}
    result = _map(results[0])
    identity = _map(result.get("quoteType"))
    if identity.get("symbol") != symbol or identity.get("quoteType") != "EQUITY":
        return {}
    return dict(result)


def _has_data(data):
    data = _map(data)
    return (any(_day(row.get("quarter")) and any(_number(row.get(k)) is not None for k in ("epsActual", "epsEstimate"))
                for row in _rows(_map(data.get("earningsHistory")).get("history")))
            or any(_day(row.get("endDate")) and _number(row.get("totalRevenue")) is not None
                   for row in _rows(_map(data.get("incomeStatementHistoryQuarterly")).get("incomeStatementHistory")))
            or any(row.get("period") in ("0q", "+1q") and _day(row.get("endDate"))
                   and any(_number(_map(row.get(k)).get("avg")) is not None for k in ("earningsEstimate", "revenueEstimate"))
                   for row in _rows(_map(data.get("earningsTrend")).get("trend"))))


def get_earnings_comparison_snapshot(ticker, *, is_etf=False):
    symbol = str(ticker or "").strip().upper()
    if is_etf or not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol):
        return dict(ok=False, status="etf_excluded" if is_etf else "invalid_ticker", data={}, fetched_at="", stale=False)
    return yahoo_metadata_reader.read("quarterly_earnings", symbol, _fetch, ttl=TTL,
        is_success=_has_data, allow_stale=True)


def _stored_quarters(fin_meta):
    meta = _map(fin_meta)
    metrics = _map(meta.get("metrics")) or _map(_map(meta.get("notes")).get("metrics"))
    rows = _rows(metrics.get("quarter_records"))
    latest = _map(metrics.get("quarter_latest"))
    if latest and not any(dict(row) == dict(latest) for row in rows):
        rows = [*rows, latest]
    return meta, _unique_by_day(rows, "date")


def _filing_lineage(stored, provenance, currency, today):
    start, end = _day(stored.get("start")), _day(stored.get("end"))
    if not start or end != _day(stored.get("date")) or not end:
        return False
    if not 70 <= (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 <= 110:
        return False
    facts = _rows(provenance.get("facts"))
    tags = ("RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet")
    if not facts or not all(
        fact.get("form") in ("10-Q", "10-Q/A", "10-K", "10-K/A")
        and fact.get("tag") in tags and _day(fact.get("filed"))
        and _day(fact.get("end")) and fact["end"] <= fact["filed"] <= today
        and isinstance(fact.get("accession"), str) and re.fullmatch(r"\d{10}-\d{2}-\d{6}", fact["accession"])
        and fact.get("unit") == currency and _number(fact.get("value")) is not None
        for fact in facts):
        return False
    method = provenance.get("method")
    if method == "reported" and len(facts) == 1:
        fact = facts[0]
        value = _number(fact["value"]) if fact.get("start") == start and fact.get("end") == end else None
    elif method == "cumulative_difference" and len(facts) == 2:
        current, previous = facts
        prior_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        origin = _day(current.get("start"))
        valid = (origin and origin < start and previous.get("start") == origin
                 and current.get("end") == end and previous.get("end") == prior_end
                 and current.get("tag") == previous.get("tag"))
        value = _number(current["value"] - previous["value"]) if valid else None
    else:
        return False
    actual = _number(stored.get("revenue"))
    return actual is not None and value is not None and math.isclose(value, actual, rel_tol=1e-9, abs_tol=0.01)


def _filing_check(stored, meta, value, currency, today):
    if not stored:
        return "동일 분기 저장 공시 없음"
    if meta.get("source") != "sec_edgar":
        return "저장 재무 있음 · 공식 공시 대조 미완료"
    provenance = _map(_map(stored.get("provenance")).get("revenue"))
    if (stored.get("period") != "quarter" or stored.get("is_single_quarter") is not True
            or stored.get("is_cumulative_ytd") is not False
            or not currency or stored.get("unit") != currency):
        return "저장 공시 기간·통화 대조 보류"
    actual = _number(stored.get("revenue"))
    if value is None or actual is None:
        return "저장 공시 매출 미확인"
    if not _filing_lineage(stored, provenance, currency, today):
        return "저장 공시 기간·산출 근거 대조 보류"
    return "저장 SEC 공시 매출 일치" if math.isclose(value, actual, rel_tol=1e-9, abs_tol=0.01) else "저장 SEC 공시 매출 불일치 · 확인 필요"


def build_earnings_comparison(snapshot, *, fin_meta=None, now=None):
    """No I/O or mutation. Period end is never called a release/fetch date."""
    snapshot = _map(snapshot)
    now = now or datetime.now(timezone.utc)
    status = snapshot.get("status", "no_data")
    if snapshot.get("stale") is True:
        status = "stale"
    fetched = str(snapshot.get("fetched_at") or "")
    try:
        observed = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        age = (now - observed).total_seconds()
        current = observed.tzinfo is not None and 0 <= age < TTL
    except (ValueError, TypeError, OverflowError):
        current = False
    usable = snapshot.get("ok") is True and status == "available" and current
    if status == "available" and not usable:
        status = "stale"
    result = dict(status=status, fetched_at=fetched, source=SOURCE, actuals=[], forecasts=[],
                  diagnostics=[], stored_financial_status="", release_date="미제공",
                  consensus_asof="미제공", source_url="", comparison_used_for_scoring=False)
    if not usable:
        result["diagnostics"].append(_STATUS.get(status, "조회 상태 미확인") + " · 실적 비교 보류")
        return result
    data = _map(snapshot.get("data"))
    symbol = str(_map(data.get("quoteType")).get("symbol") or "")
    result["source_url"] = "https://finance.yahoo.com/quote/" + quote(symbol, safe="") + "/analysis/"
    currency = _currency(_map(data.get("financialData")).get("financialCurrency"))
    history = _map(data.get("earningsHistory"))
    for module, key in (("earningsHistory", "history"), ("earningsTrend", "trend"),
                        ("incomeStatementHistoryQuarterly", "incomeStatementHistory")):
        rows = _map(data.get(module)).get(key)
        if isinstance(rows, list) and len(rows) > MAX_ROWS:
            result["diagnostics"].append("공급자 분기 자료 한도 초과 · 해당 자료 비교 보류")
    historical = _unique_by_day(_rows(history.get("history")), "quarter")
    statement = _unique_by_day(_rows(_map(data.get("incomeStatementHistoryQuarterly")).get("incomeStatementHistory")), "endDate")
    meta, stored = _stored_quarters(fin_meta)
    for day in sorted(historical.keys() | statement.keys(), reverse=True):
        if day > now.date().isoformat():
            result["diagnostics"].append("미래 분기 실제값 제외")
            continue
        if day in historical:
            row = historical[day]
            actual, estimate = _number(row.get("epsActual")), _number(row.get("epsEstimate"))
            unit = _currency(row.get("currency"))
            basis = _basis(history.get("defaultMethodology"))
            comparable = actual is not None and estimate is not None and unit is not None and basis != "회계기준 미제공"
            result["actuals"].append(dict(period_end=day, metric="EPS", actual=actual, estimate=estimate,
                currency=unit, basis=basis, difference=_number(actual - estimate) if comparable else None,
                status="공급자 동일 분기 대응 · 공식 EPS 대조 미완료" if comparable else "통화·회계기준 또는 비교값 미제공",
                source=SOURCE, estimate_timing="과거 예상(공급자) · 산출시점 미제공"))
        if day in statement:
            actual = _number(statement[day].get("totalRevenue"))
            result["actuals"].append(dict(period_end=day, metric="매출", actual=actual, estimate=None,
                currency=currency, basis="공급자 보고 매출", difference=None,
                status=_filing_check(stored.get(day), meta, actual, currency, now.date().isoformat()), source=SOURCE,
                estimate_timing="발표 당시 매출 예상 미제공",
                stored_filing=deepcopy(dict(stored.get(day) or {})) if meta.get("source") == "sec_edgar" else {}))
    trend = _map(data.get("earningsTrend"))
    # Annual forecasts are not quarters. A rolling estimate cannot fill a
    # historical surprise even if its endDate still equals a released period.
    future = [row for row in _rows(trend.get("trend")) if row.get("period") in ("0q", "+1q")]
    future = _unique_by_day(future, "endDate")
    for day, row in sorted(future.items()):
        for key, metric, unit_key in (("earningsEstimate", "EPS", "earningsCurrency"),
                                     ("revenueEstimate", "매출", "revenueCurrency")):
            estimate = _map(row.get(key))
            value = _number(estimate.get("avg"))
            if value is None:
                continue
            count = _number(estimate.get("numberOfAnalysts"))
            result["forecasts"].append(dict(period_end=day, metric=metric, estimate=value,
                low=_number(estimate.get("low")), high=_number(estimate.get("high")),
                analyst_count=int(count) if count is not None and count > 0 and count.is_integer() else None,
                currency=_currency(estimate.get(unit_key)), basis=_basis(trend.get("defaultMethodology")),
                status="현재 예상 · 발표 당시 값 아님", source=SOURCE))
    provider_latest = max((row["period_end"] for row in result["actuals"]
                           if row["metric"] == "매출" and row["actual"] is not None), default="")
    saved_latest = max(stored, default="")
    if provider_latest and saved_latest:
        result["stored_financial_status"] = (f"저장 재무 갱신 확인 필요: {saved_latest} → 공급자 실적 {provider_latest}"
            if provider_latest > saved_latest else f"저장 재무 분기 {saved_latest} · 수치 대조는 매출 행 참조")
    elif provider_latest:
        result["stored_financial_status"] = "저장 재무 분기 미확인 · 공급자 실적으로 점수를 덮어쓰지 않음"
    if not result["actuals"] and not result["forecasts"]:
        result["diagnostics"].append("정확한 분기 종료일이 있는 실적·예상 미제공")
    return result


def _value(value, currency):
    if value is None:
        return "미제공"
    scale, suffix = next(((scale, suffix) for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"))
                          if abs(value) >= scale), (1, ""))
    return f"{value / scale:,.2f}{suffix} {currency or '(통화 미제공)'}"


def render_earnings_comparison(ui, comparison):
    import pandas as pd

    ui.caption("분기 실적·예상 대조 (등급·매매판정 미반영)")
    for note in comparison["diagnostics"]:
        ui.caption(note)
    if comparison["stored_financial_status"]:
        ui.caption(comparison["stored_financial_status"])
    if comparison["actuals"]:
        ui.dataframe(pd.DataFrame([{
            "분기 종료일": r["period_end"], "항목": r["metric"],
            "실제(공급자)": _value(r["actual"], r["currency"]),
            "과거 예상(공급자)": _value(r["estimate"], r["currency"]),
            "실제−예상": _value(r["difference"], r["currency"]) if r["difference"] is not None else "비교 보류",
            "근거·상태": r["basis"] + " · " + r["status"],
        } for r in comparison["actuals"]]), width="stretch", hide_index=True)
    if comparison["forecasts"]:
        ui.caption("현재 분기 예상 · 과거 발표 당시 예상치와 별도")
        ui.dataframe(pd.DataFrame([{
            "분기 종료일": r["period_end"], "항목": r["metric"],
            "현재 예상": _value(r["estimate"], r["currency"]),
            "예상 범위": _value(r["low"], r["currency"]) + " ~ " + _value(r["high"], r["currency"]),
            "참여수": str(r["analyst_count"]) if r["analyst_count"] is not None else "미제공",
            "기준": r["basis"] + " · " + r["status"],
        } for r in comparison["forecasts"]]), width="stretch", hide_index=True)
    if comparison["actuals"] or comparison["forecasts"]:
        ui.caption(f"출처: {comparison['source']} · 조회 {comparison['fetched_at']} · 캐시 최대 15분. "
                   "발표일·예상 산출시점 미제공. 실제−예상은 공급자 대응값의 단순 차이이며 공식 실적 서프라이즈 확정이 아닙니다.")
        ui.caption("금액 단위: M=백만, B=십억, T=조. 원수치는 검토 ZIP에 보존됩니다.")
