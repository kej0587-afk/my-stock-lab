"""Use the queue's consensus contract in valuation and final checks too."""

from collections.abc import Mapping
from copy import deepcopy
import math

import pandas as pd

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.today_enrichment import attach_today_analyst_context


CONSENSUS_KEYS = (
    "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
    "numberOfAnalystOpinions", "recommendationKey", "recommendationMean",
)
_STATUS = {
    "available": "연결", "no_target": "목표가 미제공", "stale": "이전 자료 · 재조회 필요",
    "rate_limited": "조회 제한", "lookup_error": "조회 실패", "invalid_snapshot": "응답 형식 확인 필요",
    "no_price": "현재가 미확인", "etf_excluded": "ETF/ETN 목표가 해당없음",
    "invalid_ticker": "종목코드 확인 필요",
}


def resolve_valuation_inputs(snapshot, analyst_snapshot, ticker, current_price):
    """No I/O: reuse the same mean/median selection, price, and status as the queue."""
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    analyst = analyst_snapshot if isinstance(analyst_snapshot, Mapping) else {}
    raw = snapshot.get("data") if snapshot.get("ok") is True else {}
    data = deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}
    for key in CONSENSUS_KEYS:
        data.pop(key, None)
    context = attach_today_analyst_context(
        pd.DataFrame([{"티커": ticker, "현재가": current_price}]),
        get_analyst_snapshot=lambda _: analyst,
        load_latest_price=lambda _: math.nan,
        max_workers=1,
    ).iloc[0].to_dict()
    if context["애널목표상태"] == "available":
        # Only the selected mean/median and its associated provider may contribute.
        data[context["애널목표종류"]] = context["애널목표가"]
        count = context.get("애널참여수")
        if isinstance(count, (int, float)) and math.isfinite(count):
            data["numberOfAnalystOpinions"] = count
        data["currentPrice"] = context["애널가격기준"]
        data["regularMarketPrice"] = context["애널가격기준"]
    return data, context


def valuation_reference_price(current_price, context):
    """Keep a valid displayed price; otherwise use the shared resolved fallback."""
    for value in (current_price, context.get("애널가격기준")):
        if isinstance(value, bool):
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            return price
    return math.nan


def consensus_connection_rows(context):
    context = context if isinstance(context, Mapping) else {}
    return [{"자료": "애널리스트 주가 목표", "목표가": context.get("애널목표가표시") or "-",
             "현재가 대비": context.get("애널목표Upside") or "-",
             "출처": context.get("애널목표출처") or "미연결",
             "공급자 기준일": context.get("애널목표기준일") or "미제공",
             "조회시각": context.get("애널목표조회시각") or "미확인",
             "상태": _STATUS.get(context.get("애널목표상태"), "자료 미연결")}]


register_loaded_source(__name__, __file__)
