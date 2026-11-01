"""Account returns from end-of-day NAV and external flows only; no market IO."""

from datetime import date, datetime
import math
from numbers import Number
import re

import numpy as np
import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

PRIMARY_METHOD_URL = (
    "https://www.gipsstandards.org/standards/gips-standards-for-firms/"
    "gips-standards-handbook-for-firms/"
)
PERIOD_COLUMNS = [
    "start", "end", "opening_value_krw", "closing_value_krw", "net_flow_krw",
    "weighted_flow_krw", "investment_pnl_krw", "return_pct", "method", "status",
]
_NAV_COLUMNS = ["date", "account", "value_krw"]
_FLOW_COLUMNS = ["id", "date", "account", "amount", "currency", "fx_rate"]


def _blank(value):
    if isinstance(value, str):
        return not value.strip()
    return pd.api.types.is_scalar(value) and bool(pd.isna(value))


def _number(value):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Number)
            or np.iscomplexobj(value)):
        raise ValueError("유한한 숫자(참/거짓 제외)가 필요합니다")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("유한한 숫자가 필요합니다") from None
    if not math.isfinite(result):
        raise ValueError("유한한 숫자가 필요합니다")
    return result


def _missing_number(value):
    return _blank(value) and not isinstance(value, Number)


def _day(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError("실제 존재하는 날짜가 필요합니다") from None
    if isinstance(value, datetime) and not pd.isna(value):
        if (value.tzinfo is None and value.hour == value.minute == value.second == 0
                and value.microsecond == 0 and getattr(value, "nanosecond", 0) == 0):
            return value.date()
    elif isinstance(value, date) and not pd.isna(value):
        return value
    raise ValueError("날짜는 YYYY-MM-DD 또는 시간대 없는 자정 날짜여야 합니다")


def _sum(values):
    try:
        return math.fsum(values)
    except (OverflowError, ValueError):
        return math.nan


def calculate_account_performance(valuations: pd.DataFrame, flows: pd.DataFrame,
                                  account: str, *, flows_complete=False) -> dict:
    """Use (start, end] flows; opening-day flows are already in the anchor NAV.

    Dates in results are datetime.date objects. Missing/invalid inputs suppress
    calculation; invalid intervals retain their row but suppress the summary.
    A literal True certifies the external-flow history, including an empty one.
    """
    result = {"status": "ready", "issues": [],
              "periods": pd.DataFrame(columns=PERIOD_COLUMNS), "summary": {}}

    def issue(status, message):
        result["issues"].append(message)
        if status == "invalid" or result["status"] == "ready":
            result["status"] = status

    if not isinstance(account, str) or not account.strip():
        issue("missing", "계좌를 지정해 주세요.")
        return result
    account = account.strip()
    if flows_complete is not True:
        issue("missing", "외부 입출금 내역의 완전성 확인이 필요합니다.")
        return result

    def rows(frame, columns, label):
        if not isinstance(frame, pd.DataFrame):
            issue("missing", f"{label}: 데이터프레임이 필요합니다.")
            return []
        if not frame.columns.is_unique:
            issue("invalid", f"{label}: 중복된 열 이름이 있습니다.")
            return []
        absent = [key for key in columns if key not in frame.columns]
        if absent:
            issue("missing", f"{label}: 필수 열 누락 ({', '.join(absent)}).")
            return []
        selected = []
        for index, row in enumerate(frame.to_dict("records"), 1):
            if all(_blank(value) for value in row.values()):
                continue
            if _blank(row["account"]):
                issue("missing", f"{label} {index}행: 계좌가 누락되었습니다.")
            elif isinstance(row["account"], str) and row["account"].strip() == account:
                selected.append((f"{label} {index}행", row))
        return selected

    navs, cashflows, nav_days, ids = [], [], set(), set()
    for label, row in rows(valuations, _NAV_COLUMNS, "평가액"):
        if _blank(row["date"]) or _missing_number(row["value_krw"]):
            issue("missing", f"{label}: 날짜 또는 평가액이 누락되었습니다.")
            continue
        try:
            day, value = _day(row["date"]), _number(row["value_krw"])
            if value < 0:
                raise ValueError("평가액은 0 이상이어야 합니다")
            if day in nav_days:
                raise ValueError("같은 계좌의 평가 날짜가 중복되었습니다")
            nav_days.add(day)
            navs.append((day, value))
        except ValueError as exc:
            issue("invalid", f"{label}: {exc}.")
    for label, row in rows(flows, _FLOW_COLUMNS, "입출금"):
        required = ("id", "date", "currency")
        if any(_blank(row[key]) for key in required) or _missing_number(row["amount"]):
            issue("missing", f"{label}: ID·날짜·금액·통화 중 누락된 값이 있습니다.")
            continue
        try:
            identity = row["id"]
            if isinstance(identity, str):
                identity = identity.strip()
            if not pd.api.types.is_scalar(identity) or isinstance(identity, (bool, np.bool_)):
                raise ValueError("입출금 ID가 올바르지 않습니다")
            if isinstance(identity, Number):
                _number(identity)
            if identity in ids:
                raise ValueError("같은 계좌의 입출금 ID가 중복되었습니다")
            ids.add(identity)
            day, amount = _day(row["date"]), _number(row["amount"])
            currency = row["currency"]
            if currency not in ("KRW", "USD"):
                raise ValueError("통화는 KRW 또는 USD여야 합니다")
            if _blank(row["fx_rate"]):
                if currency == "USD":
                    issue("missing", f"{label}: 해당 날짜의 USD 환율이 필요합니다.")
                    continue
                rate = 1.0
            else:
                rate = _number(row["fx_rate"])
            if rate <= 0 or (currency == "KRW" and rate != 1):
                raise ValueError("USD 환율은 양수, KRW 환율은 1이어야 합니다")
            converted = amount * rate
            if not math.isfinite(converted):
                raise ValueError("원화 환산 금액이 유한하지 않습니다")
            cashflows.append((day, converted))
        except (ValueError, TypeError) as exc:
            issue("invalid", f"{label}: {exc}.")

    navs.sort()
    if len(navs) < 2:
        issue("missing", "선택 계좌의 평가액이 서로 다른 날짜에 최소 2개 필요합니다.")
    if result["status"] != "ready":
        return result
    first, last = navs[0][0], navs[-1][0]
    outside = sum(day < first or day > last for day, _ in cashflows)
    if outside:
        result["issues"].append(f"평가 기간 밖 입출금 {outside}건을 계산에서 제외했습니다.")
    # Sort once, then consume each flow at most once; never synthesize daily NAV.
    cashflows = sorted((day, amount) for day, amount in cashflows if first < day <= last)
    position, periods, factors = 0, [], []
    for (start, opening), (end, closing) in zip(navs, navs[1:]):
        interval = []
        while position < len(cashflows) and cashflows[position][0] <= end:
            interval.append(cashflows[position])
            position += 1
        days = (end - start).days
        net = _sum(amount for _, amount in interval)
        weighted = _sum(amount * ((end - day).days / days) for day, amount in interval)
        pnl = _sum((closing, -opening, -net))
        denominator = _sum((opening, weighted))
        estimated = any(day < end for day, _ in interval)
        method = "Modified Dietz(추정)" if estimated else "구간수익률"
        valid = opening > 0 and denominator > 0 and all(
            math.isfinite(value) for value in (net, weighted, pnl, denominator))
        rate = pnl / denominator if valid else math.nan
        valid = valid and math.isfinite(rate) and rate >= -1 and math.isfinite(rate * 100)
        if not valid:
            issue("invalid", f"{start} ~ {end}: 시작 평가액·분모·수익률이 유효하지 않습니다.")
        else:
            factors.append(1 + rate)
        periods.append(dict(zip(PERIOD_COLUMNS, (
            start, end, opening, closing, net, weighted, pnl,
            rate * 100 if valid else math.nan, method, "ready" if valid else "invalid",
        ))))
    result["periods"] = pd.DataFrame(periods, columns=PERIOD_COLUMNS)
    if result["status"] != "ready":
        return result
    net = _sum(row["net_flow_krw"] for row in periods)
    pnl = _sum(row["investment_pnl_krw"] for row in periods)
    linked = (math.prod(factors) - 1) * 100
    if not all(math.isfinite(value) for value in (net, pnl, linked)):
        issue("invalid", "연결 수익률 또는 합계가 유한하지 않습니다.")
        return result
    result["summary"] = {
        "start": first, "end": last, "opening_value_krw": navs[0][1],
        "closing_value_krw": navs[-1][1], "net_flow_krw": net,
        "investment_pnl_krw": pnl, "return_pct": linked,
        "method": ("Modified Dietz 연결(추정)" if any(
            row["method"] == "Modified Dietz(추정)" for row in periods) else "구간 연결"),
        "outside_flow_count": outside, "period_count": len(periods),
    }
    return result
