"""Pure, latest-observed-quarter reading of a trusted SEC review packet.

No fetching, freshness policy, scoring or MSFT-specific Q4 recovery. Derived
packet values are not evidence: validate their operands before explaining them.
"""

from datetime import timedelta
import math
import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.sec_financial_periods import _date, _finite, _quarter_span
from stock_lab_core.sec_quarter_review import FORMS, LABELS, STATUS_LABELS, TAGS, _signature

register_loaded_source(__name__, __file__)

_FIELDS = ("revenue", "op_income", "net_income", "ocf", "cash_capex")
_CAPEX_SCOPES = dict(zip(TAGS["cash_capex"], ("유형자산", "유형·소프트웨어·무형자산")))


def prior_year_cash_row(packet):
    """Select one fiscal-matched prior quarter, including 52/53-week calendars."""
    try:
        current = packet['quarter'][-1]
        start, end = _date(current['start']), _date(current['end'])
        if not start or not end or current.get('fiscal_quarter') not in (1,2,3,4):
            return None
        candidates = []
        for row in packet['quarter'][:-1]:
            a, b = _date(row.get('start')), _date(row.get('end'))
            if (a and b and a <= b and row.get('fiscal_quarter') == current['fiscal_quarter']
                    and 350 <= (start-a).days <= 380 and 350 <= (end-b).days <= 380
                    and abs((end-start).days-(b-a).days) <= 7):
                candidates.append(row)
        return candidates[0] if len(candidates)==1 else None
    except (KeyError,TypeError,IndexError):
        return None


def _checked_field(row, field, start, end, cutoff):
    """Return an amount and its exact period/filing signature, or a hold reason.

    Mirrors the cash-trend provenance guard with the review reader's general
    tags and fiscal periods; neither its MSFT calendar nor Q4 exceptions apply.
    """
    evidence = row.get("provenance", {}).get(field, {})
    status = evidence.get("status")
    if status:
        return None, None, STATUS_LABELS.get(status, "공시 근거 확인 필요")
    if not _finite(row.get(field)):
        return None, None, "미수집·유효 금액 확인 필요"
    try:
        facts, method = evidence["facts"], evidence.get("method")
        if not ((method == "reported" and len(facts) == 1)
                or (method == "cumulative_difference" and len(facts) == 2)):
            raise ValueError("계산 방법 확인 필요")
        tags = {fact["tag"] for fact in facts}
        if len(tags) != 1 or not tags.issubset(TAGS[field]):
            raise ValueError("항목 정의 확인 필요")
        for fact in facts:
            first, last, filed = (_date(fact.get(key)) for key in ("start", "end", "filed"))
            if (not first or not last or not filed or not first <= last <= filed <= cutoff
                    or fact.get("unit") != "USD" or fact.get("form") not in FORMS
                    or not _finite(fact.get("value"))
                    or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(fact.get("accession", "")))):
                raise ValueError("기간·통화·공시 근거 확인 필요")
        if method == "reported":
            fact = facts[0]
            if (fact["start"], fact["end"]) != (start.isoformat(), end.isoformat()):
                raise ValueError("분기와 원자료 기간 불일치")
            value = fact["value"]
        else:
            a, b = facts
            origin = _date(a["start"])
            if (a["end"] != end.isoformat()
                    or b["end"] != (start - timedelta(days=1)).isoformat()
                    or a["start"] != b["start"] or origin >= start
                    or a["start"] != row.get("fiscal_year_start")
                    or _quarter_span(origin, end) != row.get("fiscal_quarter")
                    or _quarter_span(origin, _date(b["end"])) != row["fiscal_quarter"] - 1):
                raise ValueError("누적차감 기간 확인 필요")
            if (a["accession"], a["filed"], a["form"]) != (b["accession"], b["filed"], b["form"]):
                raise ValueError("서로 다른 제출본 누적차감")
            value = a["value"] - b["value"]
        if not _finite(value) or not math.isclose(row[field], value, rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError("금액과 원자료 불일치")
        if field == "cash_capex":
            if value < 0:
                raise ValueError("투자지출 음수값 확인 필요")
            if row.get("cash_capex_scope") != _CAPEX_SCOPES[next(iter(tags))]:
                raise ValueError("투자지출 범위 확인 필요")
        return value, tuple(_signature(evidence)), ""
    except ValueError as error:
        return None, None, str(error)
    except (KeyError, TypeError, IndexError):
        return None, None, "필드별 공시 근거 부족"


def _amount(value):
    return f"{value / 1e6:,.1f}백만 USD"


def _amounts(fields, checked):
    present = sum(checked[field][0] is not None for field in fields)
    prefix = "확인 보류 · " if not present else "부분 확인 · " if present < len(fields) else ""
    return prefix + "; ".join(
        LABELS[field] + " " + (_amount(checked[field][0]) if checked[field][0] is not None
                                else f"보류({checked[field][2]})")
        for field in fields)


def _same_basis(checked, *fields):
    return (all(checked[field][0] is not None for field in fields)
            and len({checked[field][1] for field in fields}) == 1)


def _unsupported(reason):
    return [{"검토축": "자료 범위", "확인된 사실": reason,
             "왜 중요한가": "분기 근거 부족을 매출·이익·현금흐름 0으로 해석할 수 없습니다.",
             "다음 확인": "US-GAAP 10-K/10-Q USD 분기 근거와 기간을 확인. 20-F 기업은 별도 연간 근거를 확인"}]


def company_cash_reading(packet) -> list[dict[str, str]]:
    """Explain the latest observed quarter from ``load_quarter_evidence``.

    Returns Korean string rows with exactly 검토축/확인된 사실/왜 중요한가/다음 확인.
    Valid fields survive partial evidence; comparisons require matching source
    signatures. Missing/unsupported data produce explicit holds, never zero or
    an older-quarter fallback. The packet is not mutated and no I/O occurs here.
    """
    if not isinstance(packet, dict) or not packet.get("quarter"):
        return _unsupported("지원하는 US-GAAP 10-K/10-Q USD 분기 근거 없음 · 해석 보류")
    if (packet.get("currency") != "USD" or packet.get("review_only") is not True
            or packet.get("eligible_for_scoring") is not False
            or packet.get("status") != "quarter_evidence_only"):
        return _unsupported("지원하는 분기 검토 패킷·통화 확인 전 해석 보류")
    # The trusted loader returns chronological observed periods. Do not search
    # backward for a complete row and relabel that as the latest quarter.
    row = packet["quarter"][-1]
    start, end, cutoff = _date(row.get("start")), _date(row.get("end")), _date(packet.get("as_of"))
    if (not start or not end or not cutoff or end > cutoff
            or _quarter_span(start, end) != 1 or row.get("is_single_quarter") is not True
            or row.get("unit") != "USD"):
        return _unsupported("최신 관측 분기의 기간·통화 확인 전 해석 보류")
    checked = {field: _checked_field(row, field, start, end, cutoff) for field in _FIELDS}
    basis = f"{start.isoformat()} ~ {end.isoformat()} · "

    income = _amounts(_FIELDS[:3], checked)
    revenue, operating = checked["revenue"][0], checked["op_income"][0]
    if _same_basis(checked, "revenue", "op_income") and revenue > 0:
        margin = operating / revenue * 100
        income += (f"; 영업이익률 {margin:.1f}%" if _finite(margin)
                   else "; 영업이익률 보류(계산 범위 확인 필요)")
    else:
        income += "; 영업이익률 보류(동일 기간·제출본의 매출·영업이익과 양의 매출 필요)"

    cash = _amounts(_FIELDS[3:], checked)
    ocf, capex = checked["ocf"][0], checked["cash_capex"][0]
    if capex is not None:
        cash += f"; 투자지출 범위: {row['cash_capex_scope']}"
    cash_why = "영업현금흐름은 영업에서 유입·유출된 현금이고, 현금 투자지출은 공시된 자산 취득 지출입니다. "
    if _same_basis(checked, "ocf", "cash_capex"):
        residual = ocf - capex
        if _finite(residual):
            cash += f"; 단순차액(영업현금흐름 − 현금 투자지출) {_amount(residual)}"
            if ocf <= 0:
                cash_why += "영업현금흐름이 0 이하이므로 투자지출/영업현금흐름을 부담률로 해석하지 않습니다. "
            elif residual < 0:
                cash_why += "이 분기의 현금 투자지출이 영업에서 창출한 현금을 초과합니다. "
            else:
                cash_why += "이 분기의 영업현금흐름에서 해당 투자지출을 차감한 금액을 보여줍니다. "
        else:
            cash += "; 단순차액 보류(계산 범위 확인 필요)"
        ratio = capex / ocf * 100 if ocf > 0 else None
        cash += (f"; 투자지출/영업현금흐름 {ratio:.1f}%" if _finite(ratio)
                 else "; 투자지출/영업현금흐름 보류(양의 영업현금흐름·계산 범위 확인 필요)")
    else:
        cash += "; 단순차액·투자지출 비율 보류(동일 기간·제출본의 두 항목 필요)"
        cash_why += "개별 금액만으로 같은 기준의 현금 창출과 투자지출을 연결할 수 없습니다. "
    cash_why += "단순차액은 회사의 조정 FCF와 다를 수 있고 비현금 리스·구매약정·인수대금을 포함하지 않습니다."

    count = sum(checked[field][0] is not None for field in _FIELDS)
    coverage = (f"{packet.get('ticker', '')} · {packet['as_of']} 조회 기준, 관측 {len(packet['quarter'])}분기. "
                f"최신 관측 분기 {row['end']}: 매출·이익·현금 5개 항목 중 {count}개 확인. "
                "최근 실적발표 전체 반영 미확인.")
    if count < len(_FIELDS):
        coverage += " 부분 근거 · 보류 항목은 추정하지 않음."
    if packet.get("gaps"):
        coverage += " 관측 분기 사이 누락 구간 있음."
    return [
        {"검토축": "자료 범위", "확인된 사실": coverage,
         "왜 중요한가": "공시 기준일·사업 범위가 다를 수 있어 회사 전체 수치를 AI 매출이나 주가 변동 원인으로 연결할 수 없습니다.",
         "다음 확인": "최근 실적발표·정정공시·사업부 정의와 누락 항목의 원자료를 확인"},
        {"검토축": "매출·이익", "확인된 사실": basis + income,
         "왜 중요한가": "매출은 사업 규모, 영업이익은 영업 비용 차감 후 결과입니다. 순이익에는 영업 외 손익과 세금도 반영되며 현금 유입과 같지 않습니다.",
         "다음 확인": "원가·영업비용·일회성 손익을 확인하고 회사 전체 매출과 부문 매출, 다음 실적의 수주·가이던스를 구분"},
        {"검토축": "현금 창출·투자", "확인된 사실": basis + cash, "왜 중요한가": cash_why,
         "다음 확인": "운전자본·비현금 비용과 투자지출 정의를 확인. 리스·구매약정·현금잔고·차입 만기를 함께 확인하며 이 차액만으로 현금 고갈 시점이나 적정가를 계산하지 않음"},
    ]
