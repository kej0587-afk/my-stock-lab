"""Dated observation-only sentiment evidence, never an execution score."""

from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime
import logging
import threading
import time

import requests

from stock_lab_core.report_evidence import number, records, stamp
from stock_lab_core.result_cache import cache_result
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

FRED_SERIES = "BAMLH0A0HYM2"
FRED_SOURCE = "https://fred.stlouisfed.org/series/" + FRED_SERIES
_INVESTOR_KINDS = ("sector_kospi", "sector_kosdaq")
_INVESTOR_CACHE_TTL = 180
_INVESTOR_FAILURE_TTL = 60
_INVESTOR_CACHE_MAX_ENTRIES = 32
_investor_cache = OrderedDict()
_investor_cache_lock = threading.Lock()
_INVESTOR_REASONS = {
    "public_demo": "체험모드: 키움 인증·수급 조회 안 함",
    "disabled": "키움 데이터 연결 비활성",
    "missing_configuration": "키움 연결 설정 미완료",
    "invalid_configuration": "키움 연결 설정 확인 필요",
    "mock_excluded": "모의자료 제외: 실전 수급으로 대체하지 않음",
    "unverified_environment": "실전 데이터 환경 미확인",
    "client_version_mismatch": "키움 읽기 전용 클라이언트 갱신 필요",
    "busy": "키움 조회 진행 중: 다음 보고서에서 재확인",
    "timeout": "키움 수급 조회 시간 초과",
    "network_error": "키움 수급 조회 연결 실패",
    "rate_limited": "키움 조회 한도 도달: 잠시 후 재확인",
    "auth_error": "키움 인증 실패: 연결 설정 확인 필요",
    "http_error": "키움 수급 요청 거절",
    "api_error": "키움 수급 API 오류",
    "invalid_response": "키움 수급 응답 형식 미확인",
    "no_data": "유효한 순매수 필드 미제공",
    "unavailable": "키움 수급 조회 실패",
}


def _investor_failure(status):
    status = status if isinstance(status, str) and status in _INVESTOR_REASONS else "unavailable"
    return {"ok": False, "status": status, "reason": _INVESTOR_REASONS[status], "rows": [],
            "source": "Kiwoom REST ka10051", "fetched_at": "", "asof": "", "has_more": False,
            "is_mock": status == "mock_excluded"}


def _read_investor_snapshot(client, kind):
    try:
        raw = client.get_market_snapshot(kind)
    except Exception:
        # Provider exception strings can contain credentials; never retain/log them.
        return _investor_failure("unavailable")
    if not isinstance(raw, dict):
        return _investor_failure("invalid_response")
    if raw.get("is_mock"):
        return _investor_failure("mock_excluded")
    if raw.get("is_mock") is not False:
        return _investor_failure("unverified_environment")
    if raw.get("ok") is not True:
        return _investor_failure(raw.get("status"))
    try:
        at = datetime.fromisoformat(str(raw.get("fetched_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return _investor_failure("invalid_response")
    if at.tzinfo is None or not isinstance(raw.get("rows"), list):
        return _investor_failure("invalid_response")
    rows = []
    for row in records(raw.get("rows"))[:200]:
        if not isinstance(row, dict) or not isinstance(row.get("업종"), str) or not row["업종"].strip():
            continue
        values = {key: number(row.get(key)) for key in ("외국인 순매수(억원)", "기관 순매수(억원)")}
        if any(value is not None for value in values.values()):
            rows.append({"업종": row["업종"].strip()[:80], **values})
    if not rows:
        return _investor_failure("no_data")
    return {"ok": True, "status": "available", "reason": "", "rows": rows,
            "source": "Kiwoom REST ka10051", "fetched_at": at.isoformat(), "asof": "",
            "has_more": raw.get("has_more") is True, "is_mock": False}


def _cached_investor_snapshot(client, kind):
    if not _investor_cache_lock.acquire(timeout=1):
        return _investor_failure("busy")
    try:
        now = time.monotonic()
        for key in list(_investor_cache):
            if _investor_cache[key][1] <= now:
                del _investor_cache[key]
        key = (id(client), kind)
        entry = _investor_cache.get(key)
        if entry is not None and entry[0] is client:
            _investor_cache.move_to_end(key)
            return deepcopy(entry[2])
        result = _read_investor_snapshot(client, kind)
        ttl = _INVESTOR_CACHE_TTL if result["ok"] else _INVESTOR_FAILURE_TTL
        # Hold the identity with the entry, so recycled object IDs cannot share data.
        _investor_cache[key] = (client, time.monotonic() + ttl, result)
        while len(_investor_cache) > _INVESTOR_CACHE_MAX_ENTRIES:
            _investor_cache.popitem(last=False)
        return deepcopy(result)
    finally:
        _investor_cache_lock.release()


def load_investor_flow_evidence(client, *, public_demo=False):
    """Collect the two live ka10051 first pages on report generation, not rendering.

    Pass the app's configured/cached KiwoomDataClient to reuse its token. No
    secrets, accounts, orders, retries or pagination are accessed here. Results
    fit context['market_observation_evidence']; set market_evidence_checked_at
    AFTER collection for the unchanged five-minute/future-evidence checks.
    Do not advance quote_checked_at, which controls independent price validity.
    Cache per client/market: success 180s, failure 60s, at most 32 entries; the
    client retains its existing finite HTTP timeouts. No mock request is made.
    """
    reason = ""
    if public_demo:
        reason = "public_demo"
    else:
        try:
            info = client.connection_info
            status, environment = info.get("status"), info.get("environment")
            if environment == "mock":
                reason = "mock_excluded"
            elif status != "ready":
                reason = status if isinstance(status, str) and status in _INVESTOR_REASONS else "invalid_configuration"
            elif environment != "real":
                reason = "unverified_environment"
            elif not callable(getattr(client, "get_market_snapshot", None)):
                reason = "client_version_mismatch"
        except Exception:
            reason = "invalid_configuration"
    return {kind: _investor_failure(reason) if reason else _cached_investor_snapshot(client, kind)
            for kind in _INVESTOR_KINDS}


def clear_investor_flow_cache():
    """Clear only report investor evidence on an explicit connection refresh."""
    with _investor_cache_lock:
        _investor_cache.clear()


load_investor_flow_evidence.clear = clear_investor_flow_cache


def parse_credit_spread(payload, as_of):
    rows = []
    raw_rows = payload.get("observations", []) if isinstance(payload, dict) else []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(raw, dict):
            continue
        value, day = number(raw.get("value")), str(raw.get("date", ""))
        if value is not None and value >= 0 and stamp(day) and day <= as_of:
            rows.append((day, value))
    rows = sorted(dict(rows).items())
    if len(rows) < 2:
        return {"ok": False, "reason": "유효한 신용 스프레드 관측 2개 미확보", "source_url": FRED_SOURCE}
    day, value = rows[-1]
    return {"ok": True, "date": day, "value": value, "unit": "%", "previous_date": rows[-2][0],
            "change_bp": (value - rows[-2][1]) * 100, "source_url": FRED_SOURCE,
            "source": "ICE BofA via FRED", "stale": (date.fromisoformat(as_of) - date.fromisoformat(day)).days > 7}


@cache_result(ttl=3600, failure_ttl=60)
def load_credit_spread(as_of, api_key):
    if not api_key:
        return {"ok": False, "reason": "FRED_API_KEY 미설정", "source_url": FRED_SOURCE}
    try:
        response = requests.get("https://api.stlouisfed.org/fred/series/observations", params={
            "series_id": FRED_SERIES, "api_key": api_key, "file_type": "json", "sort_order": "desc",
            "observation_end": as_of, "limit": 20,
        }, timeout=(3, 6))
        if response.status_code != 200:
            return {"ok": False, "reason": f"FRED HTTP {response.status_code}", "source_url": FRED_SOURCE}
        return parse_credit_spread(response.json(), as_of)
    except (requests.RequestException, ValueError, TypeError) as exc:
        logging.warning("Credit spread fetch failed: %s", type(exc).__name__)
        return {"ok": False, "reason": type(exc).__name__, "source_url": FRED_SOURCE}


def _sector_flow_evidence(context):
    evidence = context.get("market_observation_evidence") or {}
    checked = stamp(context.get("market_evidence_checked_at") or context.get("quote_checked_at"))
    rows = []
    for kind, market in (("sector_kospi", "KOSPI"), ("sector_kosdaq", "KOSDAQ")):
        flows = evidence.get(kind) or {}
        at = stamp(flows.get("fetched_at"))
        age = (checked - at).total_seconds() if at and checked else None
        if not flows:
            reason = "키움 업종 수급 조회 미실행"
        elif flows.get("is_mock"):
            reason = "모의자료 제외"
        elif not flows.get("ok"):
            reason = _INVESTOR_REASONS.get(flows.get("status"), "키움 업종 수급 조회 실패: 상태 미확인")
        elif age is None:
            reason = "조회시각/보고서 기준시각 미확인: 키움 업종 수급 재조회 필요"
        elif age < 0:
            reason = "보고서 기준시각 이후 조회 자료 제외"
        elif age > 300:
            reason = "조회 후 5분 초과: 키움 업종 수급 재조회 필요"
        else:
            reason = ""
        flow_rows = records(flows.get("rows")) if not reason else []
        # Sector totals overlap; keep markets and rows separate, never sum them.
        for label, column in (("외국인 순매수", "외국인 순매수(억원)"), ("기관 순매수", "기관 순매수(억원)")):
            usable = [(row, number(row.get(column))) for row in flow_rows]
            usable = [(row, value) for row, value in usable if value is not None]
            observation = " / ".join(f"{row.get('업종', '업종 미제공')} {value:+,.1f}억원" for row, value in usable[:3])
            rows.append({"지표": market + " " + label, "관측": observation or "미연결",
                         "기준일": flows.get("fetched_at") or "-",
                         "범위·한계": ("업종 표 유효 첫 3행·전체 합산 아님·조회시각 기준·시세 기준시각 미제공"
                                    + ("·추가 페이지 미조회" if flows.get("has_more") else "")) if observation else
                         reason or "유효한 순매수 필드 미제공"})
    return rows


def sentiment_evidence(context):
    """Keep different dates and partial coverage explicit; no synthetic risk score."""
    rows, directions = [], []
    for name in ("VIX", "MOVE"):
        obs = context.get("macro_data", {}).get(name, {})
        value, change = number(obs.get("val")), number(obs.get("chg"))
        if value is not None:
            rows.append({"지표": name, "관측": f"{value:.2f}" + (f" · 1M {change:+.2f}%" if change is not None else " · 1M 미연결"),
                         "기준일": obs.get("as_of") or "미제공", "범위·한계": "변동성 수준·방향, 매매 신호 아님"})
            if change is not None and obs.get("as_of") == context.get("sessions", {}).get("US"):
                directions.append(1 if change > 0 else -1 if change < 0 else 0)
        else:
            rows.append({"지표": name, "관측": "미연결", "기준일": "-", "범위·한계": "가격 수집 미확보"})
    credit = context.get("credit_spread", {})
    if credit.get("ok"):
        rows.append({"지표": "하이일드 신용 스프레드", "관측": f"{credit['value']:.2f}% · 전 관측 대비 {credit['change_bp']:+.1f}bp",
                     "기준일": credit["date"], "범위·한계": "7일 초과 지연" if credit.get("stale") else "ICE BofA/FRED · 종가·발표 지연 가능"})
    else:
        rows.append({"지표": "하이일드 신용 스프레드", "관측": "미연결", "기준일": "-", "범위·한계": credit.get("reason", "FRED 조회 미수행")})
    rows.extend(_sector_flow_evidence(context))
    for label, reason in (("시장 폭·신고가/신저가", "전체 시장 종목수·고저가 집계 미연결; ETF 표본으로 대체 안 함"),
                          ("전체 거래대금", "시장 전체 거래대금 미연결; 상위 순위 합으로 대체 안 함"),
                          ("신용융자잔고", "공식 잔고 시계열 미연결"),
                          ("레버리지 ETF 거래 쏠림", "전체 ETF 거래대금 분모·동일 기준일 자료 미연결")):
        rows.append({"지표": label, "관측": "미연결", "기준일": "-", "범위·한계": reason})
    direction = ("변동성 방향은 위험회피 쪽" if len(directions) == 2 and min(directions) > 0 else
                 "변동성 방향은 위험선호 쪽" if len(directions) == 2 and max(directions) < 0 else "변동성 방향 혼재/미확인")
    return {"rows": rows, "state": direction + "; 신용·수급·시장 폭의 시점과 연결 범위가 달라 종합 상태 확정 보류(매매 신호 아님)"}
