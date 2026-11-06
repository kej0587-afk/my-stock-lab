"""Bounded, report-only Npay daily investor history. Not decision inputs.

Provider page/JS contract inspected 2026-11-06 at FLOW_SOURCE: diffValue,
buyPrice and sellPrice are KRW. Foreign includes 9000+9001; institutions
are the eight non-overlapping groups below, as on the provider's daily table.
The endpoint ignores bizdate for its cutoff; consumers enforce completed
XKRX sessions. These are retrospectively fetched, revisable public data,
not historical point-in-time observations or official KRX final figures.
"""

from datetime import datetime, timedelta

import requests

from stock_lab_core.public_market_data import (
    FLOW_SOURCE, KST, MARKETS, REASONS, SOURCE, _day, _get_json, _integer, _timestamp,
)
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.result_cache import cache_result

register_loaded_source(__name__, __file__)

DAILY_URL = "https://stock.naver.com/api/domestic/market/trend/daily"
MAX_ROWS = 60
GROUPS = {
    "foreign": ("9000", "9001"),
    "institution": ("1000", "2000", "3000", "3100", "4000", "5000", "6000", "7000"),
}
LABELS = {"foreign": "외국인", "institution": "기관"}


def completed_sessions(now):
    """A 20-minute publication buffer is not a claim of official finality."""
    at = _timestamp(now)
    if at is None:
        raise ValueError("aware collection clock required")
    schedule = _exchange_schedule("KR", (at.date() - timedelta(days=120)).isoformat(), at.date().isoformat())
    days = [day.date().isoformat() for day, close in schedule["market_close"].items()
            if (closed := _timestamp(close.isoformat())) is not None
            and closed + timedelta(minutes=20) <= at]
    if not days or len(set(days)) != len(days):
        raise ValueError("completed calendar unavailable")
    return sorted(days)


def request_params(market, end_date):
    return {"tradeType": "KRX", "marketType": market, "bizdate": end_date.replace("-", ""),
            "startIdx": 0, "pageSize": MAX_ROWS}


def _net_amounts(row):
    items = row.get("netAmounts")
    if not isinstance(items, list) or len(items) > 32:
        return {}
    values, seen = {}, set()
    for item in items:
        if not isinstance(item, dict):
            return {}
        code = item.get("investorGubun")
        if not isinstance(code, str) or code in seen:
            return {}
        seen.add(code)
        net, buy, sell = (_integer(item.get(key)) for key in ("diffValue", "buyPrice", "sellPrice"))
        if None not in (net, buy, sell) and buy >= 0 and sell >= 0 and buy - sell == net:
            values[code] = net
    return values


def parse_daily_history(payload, *, end_date):
    """Missing groups/dates remain missing. Never synthesize an institution total."""
    rows = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        return {}, "invalid_response"
    parsed, seen = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _day(row.get("bizdate"), compact=True)
        if day is None or day.isoformat() > end_date or row.get("time") != "":
            continue
        key = day.isoformat()
        if key in seen:
            parsed.pop(key, None)
            continue
        seen.add(key)
        components = _net_amounts(row)
        parsed[key] = {identity: sum(components[code] for code in codes)
                       for identity, codes in GROUPS.items() if all(code in components for code in codes)}
    return parsed, "" if any(parsed.values()) else "no_data"


def read_public_flow_backfill(end_date, *, request=None, now=None):
    """Two GETs, no credentials, retries or unbounded pagination."""
    if _day(end_date) is None:
        raise ValueError("end_date must be ISO date")
    clock = now or (lambda: datetime.now(KST))
    session = requests.Session() if request is None else None
    if session is not None:
        session.trust_env = False
    get = session.get if session is not None else request
    output = {"ok": False, "end_date": end_date, "source": SOURCE, "source_url": FLOW_SOURCE,
              "data_url": DAILY_URL, "unit": "KRW", "is_mock": False, "markets": {}}
    try:
        for market in MARKETS:
            params = request_params(market, end_date)
            payload, failure, status = _get_json(get, DAILY_URL, params)
            rows, problem = parse_daily_history(payload, end_date=end_date)
            at = clock()
            if at.tzinfo is None:
                raise ValueError("aware collection clock required")
            reason = failure or problem
            output["markets"][market] = {
                "rows": {} if failure else rows, "status": reason or "available",
                "reason": REASONS.get(reason, ""), "http_status": status,
                "request_params": params, "fetched_at": at.astimezone(KST).isoformat(),
            }
    finally:
        if session is not None:
            session.close()
    output["ok"] = all(group["status"] == "available" for group in output["markets"].values())
    return output


@cache_result(ttl=600, failure_ttl=60)
def load_public_flow_backfill(end_date):
    return read_public_flow_backfill(end_date)


def collect_public_flow_backfill():
    # Key by completed session as well as TTL, so crossing the close cannot
    # reuse a previous session's cache. No network request from render functions.
    try:
        end_date = completed_sessions(datetime.now(KST).isoformat())[-1]
    except Exception:
        return {"ok": False, "reason": "거래소 달력 미확보: 수급 이력 조회 보류"}
    return load_public_flow_backfill(end_date)


def summarize_backfill(backfill, *, checked_at):
    from stock_lab_core.public_market_flow_history import summarize_daily_values

    try:
        days = completed_sessions(checked_at)
    except Exception:
        return [], "거래소 달력 미확보: 수급 이력 계산 보류"
    if not isinstance(backfill, dict):
        return [], "수급 이력 미수집"
    if (backfill.get("source") != SOURCE or backfill.get("source_url") != FLOW_SOURCE
            or backfill.get("data_url") != DAILY_URL or backfill.get("unit") != "KRW"
            or backfill.get("is_mock") is not False or backfill.get("end_date") != days[-1]):
        return [], backfill.get("reason") or "수급 이력 출처/완료 거래일 불일치: 재조회 필요"
    checked = _timestamp(checked_at)
    output = []
    groups = backfill.get("markets")
    for market in MARKETS:
        group = groups.get(market, {}) if isinstance(groups, dict) else {}
        group = group if isinstance(group, dict) else {}
        fetched = _timestamp(group.get("fetched_at"))
        reason = group.get("reason") or ""
        rows = group.get("rows")
        if (group.get("request_params") != request_params(market, days[-1]) or fetched is None
                or not 0 <= (checked - fetched).total_seconds() <= 660
                or group.get("status") != "available" or not isinstance(rows, dict)
                or len(rows) > MAX_ROWS):
            rows = {}
            reason = reason or "수급 이력 조회시각/응답 확인 필요"
        for identity, label in LABELS.items():
            values = {day: _integer(rows.get(day, {}).get(identity))
                      if isinstance(rows.get(day), dict) else None for day in days}
            stats = summarize_daily_values(values, days)
            output.append(dict(stats, market=market, label=label, asof=days[-1], reason=reason,
                               fetched_at=group.get("fetched_at", "")))
    return output, ""


def backfill_lines(backfill, *, checked_at):
    rows, failure = summarize_backfill(backfill, checked_at=checked_at)
    if not rows:
        return ["", "한국 투자자 수급 이력: " + failure + " · 추정/0 대체 안 함."]
    lines = ["", "**한국 투자자 수급 이력 · 완료 거래일 기준(억원)**",
             "시장 | 투자자 | 연속 순매수·순매도 | 5거래일 누적 | 20거래일 누적 | 기준일",
             "--- | --- | --- | --- | --- | ---"]
    for row in rows:
        count = row["streak_days"]
        streak = ("자료 부족(시작 미확인)" if count is None else "중립(0일)" if count == 0 else
                  ("순매수" if row["streak_direction"] == "buy" else "순매도") + f" {count}거래일")
        amounts = [f"{row[f'sum_{n}']:+,.2f}" if row[f"sum_{n}"] is not None else
                   f"자료 부족({len(row['missing_dates'][str(n)])}/{n}일 미확보)" for n in (5, 20)]
        lines.append(" | ".join((row["market"], row["label"], streak, *amounts, row["asof"])))
    lines.append(f"[Npay 일자별 투자자 매매동향]({FLOW_SOURCE}) · KRX 시장·NXT 제외 · 최대 60개 일별 원자료 조회 · "
                 "오늘 장중 순매수와 별도이며 장 마감 후 20분까지 당일 이력은 제외합니다. "
                 "외국인은 기타외국인 포함, 기관은 제공자 분류별 합계. 잠정/정정 가능·과거 시점에 알 수 있었던 값은 아닙니다. "
                 "누락일은 0으로 채우지 않으며, 연속 구간의 시작을 확인하지 못하면 일수를 확정하지 않습니다.")
    for market in MARKETS:
        row = next(row for row in rows if row["market"] == market)
        if row["reason"]:
            lines.append(f"{market} 이력 조회: {row['reason']}")
    from stock_lab_core.report_presentation import kst_time
    times = list(dict.fromkeys(kst_time(row["fetched_at"]) for row in rows if row["fetched_at"]))
    if times:
        lines.append("이력 조회 시각: " + " / ".join(times))
    return lines
