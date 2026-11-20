"""Completed-bar observations and conditional price references, without trade scoring."""

from collections.abc import Mapping
from datetime import date
import math

import numpy as np
import pandas as pd

from stock_lab_core.chart_patterns import _chart_pattern_pivots
from stock_lab_core.formatters import format_currency
from stock_lab_core.report_build import register_loaded_source


def _number(value):
    if pd.api.types.is_bool(value):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def completed_scenario_frame(frame, expected_close):
    """Use an explicit exchange-session cutoff, never local date or a quote timestamp."""
    empty = pd.DataFrame()
    if not isinstance(expected_close, (str, date, pd.Timestamp)):
        return empty, "완료 거래일 미확인"
    try:
        cutoff = pd.Timestamp(expected_close)
        if pd.isna(cutoff):
            return empty, "완료 거래일 미확인"
    except (TypeError, ValueError):
        return empty, "완료 거래일 미확인"
    if (not isinstance(frame, pd.DataFrame) or frame.empty
            or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans
            or not frame.index.is_unique or not frame.index.is_monotonic_increasing):
        return empty, "일봉 날짜·순서 자료 부족"
    view = frame.loc[frame.index.date <= cutoff.date()].copy()
    if "LiveQuoteOnly" in view:
        view = view.loc[~view.LiveQuoteOnly.fillna(False).astype(bool)].copy()
    columns = ["Open", "High", "Low", "Close"]
    if view.empty or any(col not in view for col in columns):
        return empty, "완료 OHLC 자료 부족"
    values = view[columns].apply(pd.to_numeric, errors="coerce")
    if (any(pd.api.types.is_bool_dtype(view[col]) for col in columns)
            or not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any()
            or (values.High < values[["Open", "Close", "Low"]].max(axis=1)).any()
            or (values.Low > values[["Open", "Close", "High"]].min(axis=1)).any()):
        return empty, "OHLC 범위·결측 확인 필요"
    view[columns] = values
    status = "완료 일봉" if view.index[-1].date() == cutoff.date() else "이전 자료 · 최신 완료 거래일 미도달"
    return view, status


def _levels(frame):
    """Retain causal pivot confirmation dates and explicit rolling-range provenance."""
    view = frame.tail(140)
    highs, lows = _chart_pattern_pivots(view)
    levels = []
    for group, label in ((highs, "확인 고점"), (lows, "확인 저점")):
        for pivot in group[-6:]:
            known = view.index[pivot["pos"] + 3]
            levels.append({"price": pivot["price"], "source": label,
                           "at": pivot["time"].strftime("%Y-%m-%d"),
                           "known_at": known.strftime("%Y-%m-%d")})
    if len(frame) >= 21:
        prior = frame.iloc[-21:-1]
        for column, label, operation in (("Low", "직전 20봉 저가", "idxmin"), ("High", "직전 20봉 고가", "idxmax")):
            at = getattr(prior[column], operation)()
            levels.append({"price": float(prior.loc[at, column]), "source": label,
                           "at": at.strftime("%Y-%m-%d"), "known_at": frame.index[-2].strftime("%Y-%m-%d")})
    return levels


def _time_and_volume(frame):
    close = float(frame.Close.iloc[-1])
    tr = pd.concat([frame.High - frame.Low, (frame.High-frame.Close.shift()).abs(),
                    (frame.Low-frame.Close.shift()).abs()], axis=1).max(axis=1)
    short, prior = tr.tail(5), tr.iloc[-25:-5]
    range_ratio = float(short.mean()/prior.mean()) if len(frame) >= 26 and prior.mean() > 0 else None
    raw_volume = frame.get("Volume", pd.Series(index=frame.index, dtype=float))
    vol = (pd.Series(index=frame.index, dtype=float) if pd.api.types.is_bool_dtype(raw_volume)
           else pd.to_numeric(raw_volume, errors="coerce"))
    vol = vol.where(np.isfinite(vol) & (vol >= 0))
    last, base = _number(vol.iloc[-1]), vol.iloc[-21:-1]
    volume_ratio = last / float(base.mean()) if last is not None and len(base) == 20 and base.notna().all() and base.mean() > 0 else None
    v5, v20 = vol.tail(5), vol.iloc[-25:-5]
    volume_contraction = (float(v5.mean()/v20.mean()) if len(v5) == 5 and len(v20) == 20
                          and v5.notna().all() and v20.notna().all() and v20.mean() > 0 else None)
    mfi = _number(frame["MFI"].iloc[-1]) if "MFI" in frame else None
    mfi = mfi if mfi is not None and 0 <= mfi <= 100 else None
    ma20 = frame.Close.rolling(20, min_periods=20).mean()
    below = 0
    for c, ma in zip(frame.Close.iloc[::-1], ma20.iloc[::-1]):
        if not math.isfinite(ma) or c >= ma:
            break
        below += 1
    return {"range_ratio": range_ratio, "volume_ratio": volume_ratio, "volume_contraction": volume_contraction,
            "mfi": mfi, "below_ma20_bars": below, "ma20": _number(ma20.iloc[-1]),
            "close": close, "rows": len(frame)}


def build_scenario_evidence(frame, expected_close, *, profile=None):
    view, status = completed_scenario_frame(frame, expected_close)
    result = {"available": False, "status": status, "fresh": False, "levels": []}
    if view.empty:
        return result
    at, close = view.index[-1].strftime("%Y-%m-%d"), float(view.Close.iloc[-1])
    levels = _levels(view)
    # Above-price old lows are recovery barriers, never surviving support.
    below = sorted((x for x in levels if x["price"] < close), key=lambda x: x["price"], reverse=True)
    above = sorted((x for x in levels if x["price"] > close), key=lambda x: x["price"])
    unique = lambda rows: list({x["price"]: x for x in reversed(rows)}.values())[::-1]
    below, above = unique(below), unique(above)
    support, recovery = (below[0] if below else None), (above[0] if above else None)
    target = above[1] if len(above) > 1 else None
    rr = ((target["price"]-recovery["price"])/(recovery["price"]-support["price"])
          if support and recovery and target else None)
    measures = _time_and_volume(view)
    bounds = {"low": float(view.Low.tail(20).min()), "high": float(view.High.tail(20).max()), "bars": min(20, len(view))}
    profile = profile if isinstance(profile, Mapping) else {}
    poc = profile.get("poc") if profile.get("ok") is True and profile.get("asof") == at else None
    if not isinstance(poc, Mapping) or not all(_number(poc.get(k)) is not None for k in ("low", "high")):
        poc = None
    elif not 0 < float(poc["low"]) <= float(poc["high"]):
        poc = None
    result.update(available=True, fresh=status == "완료 일봉", asof=at, close=close, levels=levels,
                  support=support, recovery=recovery, target=target, next_lower=below[1] if len(below) > 1 else None,
                  rr=rr, range=bounds, measures=measures, poc=dict(poc) if poc else None)
    return result


def scenario_evidence_rows(evidence, ticker):
    """Observation numbers stay separate from claims about accumulation or intent."""
    if not evidence.get("available"):
        return []
    e, m = evidence, evidence["measures"]
    price = lambda n: format_currency(n, ticker) if n is not None else "미확인"
    ratio = lambda n: f"{n:.2f}배" if n is not None else "자료 부족"
    level = lambda row: f"{price(row['price'])} ({row['source']} {row['at']}, 확인 {row['known_at']})" if row else "관측 가격대 없음"
    rng, poc = e["range"], e["poc"]
    time = f"5봉 평균 진폭 / 직전 20봉 {ratio(m['range_ratio'])} · 거래량 {ratio(m['volume_contraction'])}"
    if m["ma20"] is not None:
        time += f" · MA20 {price(m['ma20'])} 아래 {m['below_ma20_bars']}개 연속 관측봉"
    else:
        time += " · MA20 기간 부족"
    if m["range_ratio"] is None or m["volume_contraction"] is None:
        interpretation = "수축 여부를 비교할 기간 또는 거래량이 부족합니다."
    elif m["range_ratio"] < 1 and m["volume_contraction"] < 1:
        interpretation = "진폭과 거래량이 함께 줄었습니다. 수축 관측이며 매집·상승 에너지 확정은 아닙니다."
    else:
        interpretation = "진폭·거래량 동반 수축이 아닙니다. 에너지 축적으로 단정할 근거가 부족합니다."
    basis = f"{e['asof']} · {e['status']} · 시세 전용 봉 제외"
    return [
        {"축": "구조", "관측": f"회복 장벽 {level(e['recovery'])} / 하방 관찰 {level(e['support'])}",
         "해석": "상위 추세훼손과 별개로 실제 고저점은 남습니다. 이탈한 저점이 현재가 위에 있으면 지지가 아닌 회복 장벽입니다.", "기준·제한": basis},
        {"축": "가격 위치", "관측": f"종가 {price(e['close'])} · 최근 {rng['bars']}봉 실측 범위 {price(rng['low'])}~{price(rng['high'])}",
         "해석": "범위는 횡보 확정이나 저평가 판정이 아닙니다. 조건 가격과 현재 시세를 구분합니다.", "기준·제한": basis},
        {"축": "기간", "관측": time, "해석": interpretation, "기준·제한": basis + " · 거래일 관측봉, 달력일 아님"},
        {"축": "유동성 대용치", "관측": f"최근 완료봉 거래량 / 직전 20봉 평균 {ratio(m['volume_ratio'])} · MFI {m['mfi']:.1f}" if m['mfi'] is not None else f"최근 완료봉 거래량 / 직전 20봉 평균 {ratio(m['volume_ratio'])} · MFI 미수집",
         "해석": (f"추정 최대 매물대 {price(poc['low'])}~{price(poc['high'])}. " if poc else "동일 기준 매물대 미확보. ") + "현재 시간외 거래량·실제 자금유입·호가 잔량을 뜻하지 않습니다.", "기준·제한": basis},
    ]


def conditional_price_rows(evidence, ticker):
    if not evidence.get("available") or not evidence.get("fresh"):
        return []
    def label(row):
        return (f"{format_currency(row['price'], ticker)} · {row['source']} {row['at']}" if row else "관측 가격대 없음")
    support, recovery, target = (label(evidence[key]) for key in ("support", "recovery", "target"))
    rr = evidence.get("rr")
    return [
        {"안": "A", "확인 가격": recovery + " 종가 회복 후 재확인", "다음 가격": target,
         "실패·전환": support + " 종가 이탈 시 재검토", "가격비율": f"{rr:.2f}R · 관찰 기준, 승률 아님" if rr is not None else "가격쌍 부족 · R/R 미산출"},
        {"안": "B", "확인 가격": support + " 종가 이탈", "다음 가격": label(evidence.get("next_lower")),
         "실패·전환": recovery + " 회복 시 B 재검토", "가격비율": "보유 위험 관찰 · 공매도/자동 매도 계획 아님"},
        {"안": "C", "확인 가격": support + " ~ " + recovery, "다음 가격": "상단 회복 시 A / 하단 이탈 시 B",
         "실패·전환": "범위 안 체류만으로 추가매수하지 않음", "가격비율": "관찰 범위 · 횡보/매집 확정 아님"},
    ]


register_loaded_source(__name__, __file__)
