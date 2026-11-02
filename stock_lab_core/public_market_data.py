"""Read-only Npay public market snapshots, independent of broker credentials.

Provider contracts inspected on 2026-11-02, not a documented/stable public API:
https://stock.naver.com/market/stock/kr/trend/trader
https://stock.naver.com/market/stock/kr/deposit
https://stock.naver.com/domestic/index/KOSPI/price
The trader page converts monetary values from KRW by 1e8; deposit's creditLoan
is already in 100m KRW. Never use the trader page's SSR example chart data.
Breadth has no independent timestamp: retain that limitation, no percentages
or new-high/new-low counts inferred from its five reported categories.
"""

from datetime import date, datetime, timedelta, timezone
import json
import re
import time

import requests
from urllib3.exceptions import HTTPError as TransportError

from stock_lab_core.http_body import read_response_body
from stock_lab_core.result_cache import cache_result
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

KST = timezone(timedelta(hours=9))
MARKETS = ("KOSPI", "KOSDAQ")
INDICATORS_URL = "https://stock.naver.com/api/securityService/integration/v1/indicators"
TURNOVER_URL = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ"
DEPOSIT_URL = "https://stock.naver.com/api/domestic/market/trendDeposit"
FLOW_SOURCE = "https://stock.naver.com/market/stock/kr/trend/trader"
DEPOSIT_SOURCE = "https://stock.naver.com/market/stock/kr/deposit"
SOURCE = "Npay 증권 공개 데이터"
REASONS = {
    "no_data": "공개 제공자 유효 필드 미제공",
    "invalid_response": "공개 제공자 응답 형식 미확인",
    "invalid_scope": "시장·거래소·통화 범위 불일치",
    "invalid_unit": "제공 단위/원금액 대조 불일치",
    "invalid_date": "자료 기준일/시각 미확인",
    "future_data": "요청 기준일 또는 조회시각 이후 자료 제외",
    "stale_data": "자료 기준일 7일 초과 지연",
    "timeout": "공개 데이터 조회 시간 초과",
    "network_error": "공개 데이터 연결 실패",
    "http_error": "공개 데이터 HTTP 요청 거절",
    "public_demo": "체험모드: 공개 시장자료 조회 안 함",
}


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return int(text) if re.fullmatch(r"[+-]?[0-9]{1,18}", text) else None


def _day(value, *, compact=False):
    pattern = r"[0-9]{8}" if compact else r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date() if compact else date.fromisoformat(value)
    except ValueError:
        return None


def _timestamp(value):
    try:
        at = datetime.fromisoformat(value)
        return at.astimezone(KST) if at.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _date_status(day, as_of, fetched_at):
    if day is None:
        return "invalid_date"
    if day > as_of or day > fetched_at.date():
        return "future_data"
    if (fetched_at.date() - day).days > 7:
        return "stale_data"
    return ""


def _observation(source_url, data_url, fetched_at, *, status="no_data", **fields):
    return {"ok": status == "available", "status": status,
            "reason": "" if status == "available" else REASONS[status],
            "source": SOURCE, "source_url": source_url, "data_url": data_url,
            "fetched_at": fetched_at.isoformat(), "asof": "", "unit": "",
            "is_mock": False, **fields}


def parse_indicators(payload, as_of, fetched_at):
    """Use explicit net totals, never sum overlapping sectors/investor groups."""
    output = {"flows": {}, "breadth": {}}
    root = payload.get("domesticIndex") if isinstance(payload, dict) else None
    for market in MARKETS:
        item = root.get(market) if isinstance(root, dict) else None
        item = item if isinstance(item, dict) else {}
        meta = item.get("meta")
        scope_ok = (isinstance(meta, dict) and item.get("itemCode") == market
                    and meta.get("marketCode") == market and meta.get("exchangeCode") == "KRX"
                    and meta.get("currencyCode") == "KRW")
        day = _day(item.get("investorTrendBaseDate"))
        status = ("invalid_scope" if not scope_ok or item.get("investorTrendExchangeType") != "KRX"
                  else _date_status(day, as_of, fetched_at))
        trends = item.get("investorTrends")
        output["flows"][market] = {}
        investors = [("foreign", "foreigner"), ("institution", "organization")]
        # Optional identity: never derive individuals as the residual of other groups.
        if isinstance(trends, list) and any(isinstance(row, dict) and row.get("investorType") == "individual" for row in trends):
            investors.append(("individual", "individual"))
        for investor, provider in investors:
            matches = [row for row in trends if isinstance(row, dict) and row.get("investorType") == provider] if isinstance(trends, list) else []
            value = _integer(matches[0].get("netBuyAmount")) if len(matches) == 1 else None
            result_status = status or ("available" if value is not None else "no_data")
            output["flows"][market][investor] = _observation(
                FLOW_SOURCE, INDICATORS_URL, fetched_at, status=result_status,
                market=market, exchange="KRX", asof=day.isoformat() if day else "",
                unit="억원", raw_unit="KRW", raw_value=value if result_status == "available" else None,
                value=value / 100_000_000 if result_status == "available" else None,
                date_basis="investorTrendBaseDate", provisional=True,
                limitation="KRX 시장 전체 순매수·NXT 제외·제공자 잠정/정정 가능·확정 종가 아님·반도체 등 업종별 수급/원인 근거 아님")

        if "programTrend" in item:
            program = item.get("programTrend")
            program = program if isinstance(program, dict) else {}
            arb, nonarb, total = (_integer(program.get(key)) for key in
                                 ("arbitrageNetBuyAmount", "nonArbitrageNetBuyAmount", "totalNetBuyAmount"))
            program_status = status or ("no_data" if None in (arb, nonarb, total) else
                                       "invalid_response" if arb + nonarb != total else "available")
            valid = program_status == "available"
            output.setdefault("programs", {})[market] = _observation(
                FLOW_SOURCE, INDICATORS_URL, fetched_at, status=program_status,
                market=market, exchange="KRX", asof=day.isoformat() if day else "",
                unit="억원", raw_unit="KRW", raw_arbitrage=arb if valid else None,
                raw_non_arbitrage=nonarb if valid else None, raw_value=total if valid else None,
                arbitrage=arb / 100_000_000 if valid else None,
                non_arbitrage=nonarb / 100_000_000 if valid else None,
                value=total / 100_000_000 if valid else None,
                date_basis="investorTrendBaseDate", provisional=True,
                limitation="같은 응답 investorTrendBaseDate 사용·프로그램 자체 기준시각 미제공·KRX 시장/NXT 제외·잠정/정정 가능·거래 방식별 집계로 투자자별 순매수와 합산 불가·기관 매수액/매수 동기 아님")

        price, breadth = item.get("price"), item.get("breadth")
        at = _timestamp(price.get("localTradedAt")) if isinstance(price, dict) else None
        counts = {key: _integer(breadth.get(key)) for key in (
            "upperLimitCount", "risingCount", "unchangedCount", "fallingCount", "lowerLimitCount"
        )} if isinstance(breadth, dict) else {}
        status = ("invalid_scope" if not scope_ok or not isinstance(breadth, dict) or breadth.get("exchangeType") != "KRX"
                  else _date_status(at.date() if at else None, as_of, fetched_at))
        if not status and at > fetched_at:
            status = "future_data"
        if not status and (not counts or any(v is None or not 0 <= v <= 10000 for v in counts.values())):
            status = "no_data"
        output["breadth"][market] = _observation(
            "https://stock.naver.com/market/stock/kr", INDICATORS_URL, fetched_at,
            status=status or "available", market=market, exchange="KRX", unit="종목",
            asof=at.date().isoformat() if at else "", counts=counts if not status else {},
            observed_at=at.isoformat() if at else "", date_basis="index_quote_timestamp",
            limitation="동일 응답 지수시각 기준·등락수 자체 기준시각 미제공·상하한가 중복 여부 미확인·신고가/신저가 미연결")
    return output


def parse_turnover(payload, as_of, fetched_at):
    items = payload.get("datas") if isinstance(payload, dict) else None
    output = {}
    for market in MARKETS:
        matches = [v for v in items if isinstance(v, dict) and v.get("itemCode") == market] if isinstance(items, list) else []
        item = matches[0] if len(matches) == 1 else {}
        exchange = item.get("stockExchangeType")
        at = _timestamp(item.get("localTradedAt"))
        status = ("invalid_scope" if not isinstance(exchange, dict) or
                  exchange.get("code") != {"KOSPI": "KS", "KOSDAQ": "KQ"}[market] or
                  exchange.get("nationCode") != "KOR" else
                  _date_status(at.date() if at else None, as_of, fetched_at))
        if not status and at > fetched_at:
            status = "future_data"
        raw = _integer(item.get("accumulatedTradingValueRaw"))
        formatted = item.get("accumulatedTradingValue")
        match = re.fullmatch(r"([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)백만", formatted) if isinstance(formatted, str) else None
        # Cross-check the explicit million-KRW display against the raw KRW field.
        if not status and (raw is None or raw < 0 or not match or
                           raw // 1_000_000 != int(match[1].replace(",", ""))):
            status = "invalid_unit"
        output[market] = _observation(
            f"https://stock.naver.com/domestic/index/{market}/price", TURNOVER_URL, fetched_at,
            status=status or "available", market=market, exchange="KRX", unit="억원",
            raw_unit="KRW", raw_value=raw if not status else None,
            value=raw / 100_000_000 if not status else None,
            asof=at.date().isoformat() if at else "", observed_at=at.isoformat() if at else "",
            date_basis="localTradedAt", provisional=True,
            limitation="KRX 지수 제공 범위 누적 거래대금·NXT/ETF 전체 포함 여부 미확인·상위종목 합산 아님")
    return output


def parse_margin_debt(payload, as_of, fetched_at):
    rows = payload.get("content") if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else []
    dates = [_day(row.get("bizdate"), compact=True) if isinstance(row, dict) else None for row in rows]
    status = ""
    if not rows:
        status = "no_data"
    elif None in dates or len(set(dates)) != len(dates):
        status = "invalid_date"
    row = rows[dates.index(max(dates))] if not status else {}
    day = max(dates) if not status else None
    status = status or _date_status(day, as_of, fetched_at)
    value = _integer(row.get("creditLoan"))
    if not status and (value is None or value < 0):
        status = "no_data"
    return _observation(
        DEPOSIT_SOURCE, DEPOSIT_URL, fetched_at, status=status or "available",
        unit="억원", raw_unit="100m KRW", value=value if not status else None,
        raw_value=value if not status else None, asof=day.isoformat() if day else "",
        date_basis="bizdate", scope="provider_creditLoan",
        limitation="Npay 증시자금 신용잔고·제공자 공시 지연·공식 원장 직접 조회 아님·시장별 분리 미제공")


def _get_json(request, url, params):
    response = None
    try:
        deadline = time.monotonic() + 10
        response = request(url, params=params, timeout=(3, 6), stream=True,
                           allow_redirects=False, headers={"User-Agent": "StockLab/1.0", "Accept": "application/json"})
        if response.status_code != 200:
            return None, "http_error", response.status_code
        if "json" not in response.headers.get("Content-Type", "").lower():
            return None, "invalid_response", 200
        body = read_response_body(response, deadline, time.monotonic, max_bytes=256 * 1024)
        return json.loads(body), "", 200
    except requests.Timeout:
        return None, "timeout", None
    except (requests.RequestException, TransportError, OSError):
        return None, "network_error", None
    except (ValueError, TypeError):
        return None, "invalid_response", None
    finally:
        if response is not None:
            response.close()


def read_public_market_evidence(as_of, *, request=None, now=None):
    """Three bounded GETs, no credentials, retries, pagination or secret access.

    Inject request/now for offline tests. All dates are provider dates, never
    replaced with the request date. Live latest snapshots are not historical
    point-in-time data. Consumers must set their checked-at clock AFTER this call.
    """
    target = _day(as_of)
    if target is None:
        raise ValueError("as_of must be an ISO date")
    clock = now or (lambda: datetime.now(KST))
    output = {}
    # A clean session cannot read .netrc credentials or environment proxy auth.
    session = requests.Session() if request is None else None
    if session is not None:
        session.trust_env = False
    get = session.get if session is not None else request
    try:
        for kind, url, params in (
            ("indicators", INDICATORS_URL, {"domesticIndexCodes": "KOSPI,KOSDAQ", "includeBreadth": "true", "includeTrend": "true"}),
            ("turnover", TURNOVER_URL, {}),
            ("margin_debt", DEPOSIT_URL, {"startIdx": 0, "pageSize": 3}),
        ):
            payload, failure, http_status = _get_json(get, url, params)
            fetched_at = clock()
            if fetched_at.tzinfo is None:
                raise ValueError("now must be timezone-aware")
            fetched_at = fetched_at.astimezone(KST)
            if kind == "indicators":
                parsed = parse_indicators(payload, target, fetched_at)
                observations = [obs for market in MARKETS for obs in parsed["flows"][market].values()] + list(parsed["breadth"].values())
                observations += list(parsed.get("programs", {}).values())
                output.update(parsed)
            elif kind == "turnover":
                output[kind] = parse_turnover(payload, target, fetched_at)
                observations = list(output[kind].values())
            else:
                output[kind] = parse_margin_debt(payload, target, fetched_at)
                observations = [output[kind]]
            for obs in observations:
                obs["http_status"] = http_status
                obs["request_params"] = dict(params)
                if failure:
                    obs.update(ok=False, status=failure, reason=REASONS[failure])
    finally:
        if session is not None:
            session.close()
    output["checked_at"] = clock().isoformat()
    observations = [obs for m in MARKETS for obs in output["flows"][m].values()]
    observations += list(output["breadth"].values()) + list(output["turnover"].values()) + [output["margin_debt"]]
    output["ok"] = all(obs["ok"] for obs in observations)
    return output


@cache_result(ttl=180, failure_ttl=60)
def load_public_market_evidence(as_of):
    """Collect on report generation, never rendering; incomplete results retry in 60s."""
    return read_public_market_evidence(as_of)


def observation_reason(obs, checked_at):
    """Recheck saved/cached observations against the report's own collection clock."""
    if not isinstance(obs, dict):
        return REASONS["no_data"]
    if obs.get("is_mock") is not False or obs.get("source") != SOURCE:
        return "공개 실자료 출처 미확인"
    if obs.get("ok") is not True:
        status = obs.get("status")
        return REASONS.get(status, REASONS["invalid_response"]) if isinstance(status, str) else REASONS["invalid_response"]
    checked, fetched = _timestamp(checked_at), _timestamp(obs.get("fetched_at"))
    if not checked or not fetched:
        return REASONS["invalid_date"]
    if fetched > checked:
        return REASONS["future_data"]
    if (checked - fetched).total_seconds() > 300:
        return "조회 후 5분 초과: 공개 시장자료 재조회 필요"
    status = _date_status(_day(obs.get("asof")), checked.date(), checked)
    return REASONS.get(status, "")


def validated_investor_flows(evidence, *, session_date, checked_at):
    """Same-session identities for prose; program trading is not an identity.

    Validate each observation independently so missing optional individuals or
    another market cannot hide valid totals. Preserve source and provisionality.
    """
    if not isinstance(evidence, dict) or _day(session_date) is None:
        return []
    flows = evidence.get("flows")
    if not isinstance(flows, dict):
        return []
    from stock_lab_core.report_evidence import number, safe_link

    result = []
    for market in MARKETS:
        observations = flows.get(market)
        if not isinstance(observations, dict):
            continue
        for identity, label in (("foreign", "외국인"), ("institution", "기관"), ("individual", "개인")):
            obs = observations.get(identity)
            if (observation_reason(obs, checked_at) or obs.get("asof") != session_date
                    or obs.get("unit") != "억원" or obs.get("market") != market
                    or obs.get("exchange") != "KRX" or not safe_link(obs.get("source_url"))):
                continue
            value = number(obs.get("value"))
            if value is not None:
                result.append(dict(obs, identity=identity, label=label, value=value))
    return result


def validated_program_flows(evidence, *, session_date, checked_at):
    """Optional method totals, independent of required investor evidence."""
    from stock_lab_core.report_evidence import safe_link

    programs = evidence.get("programs") if isinstance(evidence, dict) else None
    if not isinstance(programs, dict) or _day(session_date) is None:
        return []
    result = []
    for market in MARKETS:
        obs = programs.get(market)
        if (observation_reason(obs, checked_at) or obs.get("asof") != session_date
                or obs.get("unit") != "억원" or obs.get("raw_unit") != "KRW"
                or obs.get("market") != market or obs.get("exchange") != "KRX"
                or obs.get("date_basis") != "investorTrendBaseDate" or not safe_link(obs.get("source_url"))):
            continue
        arb, nonarb, total = (_integer(obs.get(key)) for key in ("raw_arbitrage", "raw_non_arbitrage", "raw_value"))
        if None in (arb, nonarb, total) or arb + nonarb != total:
            continue
        if any(obs.get(key) != raw / 100_000_000 for key, raw in
               (("arbitrage", arb), ("non_arbitrage", nonarb), ("value", total))):
            continue
        result.append(dict(obs))
    return result
