"""Dated observation-only sentiment evidence, never an execution score."""

from datetime import date
import logging

import requests

from stock_lab_core.report_evidence import number, records, stamp
from stock_lab_core.result_cache import cache_result
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

FRED_SERIES = "BAMLH0A0HYM2"
FRED_SOURCE = "https://fred.stlouisfed.org/series/" + FRED_SERIES


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
    # An industry net-buy table includes overlapping totals. Never add all rows.
    flows = context.get("market_observation_evidence", {}).get("sector_kospi", {})
    at, checked = stamp(flows.get("fetched_at")), stamp(context.get("quote_checked_at"))
    fresh = bool(at and checked and 0 <= (checked - at).total_seconds() <= 300)
    flow_rows = records(flows.get("rows")) if fresh and flows.get("ok") and not flows.get("is_mock") else []
    for label, column in (("외국인 순매수", "외국인 순매수(억원)"), ("기관 순매수", "기관 순매수(억원)")):
        usable = [r for r in flow_rows if number(r.get(column)) is not None]
        observation = " / ".join(f"{r.get('업종', '업종 미제공')} {r[column]:+,.1f}억원" for r in usable[:3])
        rows.append({"지표": label, "관측": observation or "미연결", "기준일": flows.get("fetched_at") or "-",
                     "범위·한계": "업종 표 첫 3행·전체 합산 아님·시세 기준시각 미제공" if observation else
                     "모의자료 제외" if flows.get("is_mock") else "조회시각 미확인/5분 초과: 키움 업종 수급 재조회 필요" if not fresh else flows.get("status", "키움 업종 수급 조회 필요")})
    for label, reason in (("시장 폭·신고가/신저가", "전체 시장 종목수·고저가 집계 미연결; ETF 표본으로 대체 안 함"),
                          ("전체 거래대금", "시장 전체 거래대금 미연결; 상위 순위 합으로 대체 안 함"),
                          ("신용융자잔고", "공식 잔고 시계열 미연결"),
                          ("레버리지 ETF 거래 쏠림", "전체 ETF 거래대금 분모·동일 기준일 자료 미연결")):
        rows.append({"지표": label, "관측": "미연결", "기준일": "-", "범위·한계": reason})
    direction = ("변동성 방향은 위험회피 쪽" if len(directions) == 2 and min(directions) > 0 else
                 "변동성 방향은 위험선호 쪽" if len(directions) == 2 and max(directions) < 0 else "변동성 방향 혼재/미확인")
    return {"rows": rows, "state": direction + "; 신용·수급·시장 폭의 시점과 연결 범위가 달라 종합 상태 확정 보류(매매 신호 아님)"}
