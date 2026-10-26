"""Pure, conditional readings of normalized economic-release rows.

No collection, clocks, ranking, trading rules or market-reaction attribution.
The caller owns freshness/background labels and story eligibility. PCE/GDP/JOLTS
identifiers below are accepted for supplied rows, not added to the collector.
"""

import re

from stock_lab_core.report_evidence import number, text
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


_INFLATION = {
    "US_CPI": "소비자물가", "US_CORE_CPI": "근원 소비자물가",
    "US_PPI": "생산자물가", "US_CORE_PPI": "근원 생산자물가",
    "US_PCE": "PCE 물가", "US_CORE_PCE": "근원 PCE 물가",
    "US_PCE_PRICE_INDEX": "PCE 물가", "US_CORE_PCE_PRICE_INDEX": "근원 PCE 물가",
    "KR_CPI": "한국 소비자물가", "KR_CORE_CPI": "한국 근원 소비자물가",
}
_GROWTH = {
    "US_GDP": "GDP", "US_REAL_GDP": "실질 GDP",
    "US_RETAIL_SALES": "소매판매액", "US_CORE_RETAIL_SALES": "근원 소매판매액",
    "KR_EXPORTS": "한국 수출액",
}
_OPENINGS = {"US_JOLTS", "US_JOLTS_JOB_OPENINGS", "US_JOB_OPENINGS"}
_POLICY = {"US_FED_TARGET_UPPER", "US_FED_RATE_DECISION", "KR_BASE_RATE"}
_BASIS = {"MoM": "전월비", "YoY": "전년비", "QoQ": "전분기비",
          "QoQ annualized": "전분기비 연율"}
_PERSON_UNITS = {"persons", "thousand persons"}


def _comparison(row, field, actual):
    label = "이전값" if field == "previous" else "예상치"
    value = number(row.get(field))
    if value is None:
        return None, None, ("이전값 미확인으로 변화 판단 보류" if field == "previous"
                            else "예상치 미연결로 서프라이즈 판단 보류")
    # Omitted metadata inherits the normalized row, as in comparison_metrics.
    # Explicitly different or unknown metadata must never be silently coerced.
    compatible = all(row.get(f"{field}_{key}") in (None, "", row.get(key))
                     for key in ("unit", "basis", "seasonal_adjustment"))
    period, other_period = text(row.get("period")), text(row.get(f"{field}_period"))
    if period and other_period:
        compatible = compatible and (other_period < period if field == "previous" else other_period == period)
    if not compatible:
        return None, None, f"{label} 비교기준·단위 불일치로 비교 보류"
    if field == "forecast" and text(row.get("forecast_source")) in {"", "unknown", "미확인"}:
        return None, None, "예상치 출처 미확인으로 서프라이즈 판단 보류"
    direction = (actual > value) - (actual < value)
    note = ""
    if field == "forecast":
        note = "예상치 " + {1: "상회", -1: "하회", 0: "부합"}[direction] + "(이전값 비교와 별도)"
    return value, direction, note


def _change_reading(subject, basis, actual, previous, *, prices=False, jobs=False):
    up, down = ("상승", "하락") if prices else ("증가", "감소")
    direction = up if actual > 0 else down if actual < 0 else "보합"
    if previous is None:
        return f"{basis} {subject} {direction} 관측"
    prior_direction = up if previous > 0 else down if previous < 0 else "보합"
    if direction != prior_direction:
        return f"{basis} {subject} {prior_direction}에서 {direction} 전환"
    if actual == 0:
        return f"{basis} {subject} 보합 유지"
    magnitude = (abs(actual) > abs(previous)) - (abs(actual) < abs(previous))
    measure = "폭" if jobs else "률" if prices else "율"
    change = {1: "확대", -1: "축소", 0: "동일"}[magnitude]
    return f"{basis} {subject} {direction} 지속, 이전보다 {direction}{measure} {change}"


def _level_reading(subject, direction):
    if direction is None:
        return f"{subject} 수준 관측"
    return f"{subject} 수준: " + {1: "이전 관측보다 높아짐", -1: "이전 관측보다 낮아짐",
                                0: "이전 관측과 같음"}[direction]


def _conditional_effect(family, direction):
    if direction is None:
        return "비교 근거 부족으로 금리·실적 영향 판단 보류"
    if direction == 0:
        return "동일 수치만으로 금리·실적 영향이 중립이라고 단정할 수 없음"
    if family == "inflation":
        return ("물가 압력 확대와 금리·할인율 부담 증가 가능성" if direction > 0 else
                "물가 압력 완화와 금리·할인율 부담 경감 가능성")
    if family == "policy":
        return ("자금조달·할인율 부담이 커질 수 있음" if direction > 0 else
                "자금조달·할인율 부담이 줄어들 수 있으나 경기 위험은 별도")
    if family == "unemployment":
        direction = -direction
    if family in {"jobs", "unemployment", "openings"}:
        return ("노동수요 지지와 금리 인하 지연 가능성이 공존" if direction > 0 else
                "노동시장 둔화 우려와 금리 부담 완화 가능성이 공존")
    return ("수요·실적 개선 여지와 금리 부담 확대 가능성이 공존" if direction > 0 else
            "수요·실적 둔화 우려와 금리 부담 완화 가능성이 공존")


def economic_implication(row) -> str:
    """Return a concise Korean reading without mutating a normalized row.

    Reads indicator/actual/previous/forecast/unit/basis/status and optional
    comparison metadata (including forecast_source). Finite zero is an actual
    observation. Missing comparisons never imply neutrality or a surprise;
    supplied precomputed deltas/history are not substitutes for comparisons.
    Missing comparison units/basis inherit the row; explicit mismatches block
    that comparison. US_PCE/US_CORE_PCE mean price indexes, not spending.
    No release date or reaction is inferred; callers label stale/old context.
    """
    actual = number(row.get("actual"))
    if text(row.get("status")) in {"pending", "scheduled", "예정"}:
        return "발표 예정 상태: 확정 발표치 확인 전 해석 보류(중립 판단 아님)"
    if actual is None:
        return "발표치 미확인: 해석 보류(중립 판단 아님, 미발표를 뜻하지 않음)"

    indicator, basis, unit = text(row.get("indicator")).upper(), text(row.get("basis")), text(row.get("unit"))
    subject = _INFLATION.get(indicator) or _GROWTH.get(indicator)
    if indicator in _INFLATION:
        family, valid = "inflation", unit == "%" and basis in {"MoM", "YoY"}
    elif indicator in _GROWTH:
        allowed = {"YoY", "QoQ", "QoQ annualized"} if "GDP" in indicator else {"MoM", "YoY"}
        family, valid = "growth", unit == "%" and basis in allowed
    elif indicator == "US_NONFARM_PAYROLLS":
        family, valid = "jobs", unit in _PERSON_UNITS and basis == "MoM"
    elif indicator == "US_UNEMPLOYMENT":
        family, valid = "unemployment", unit == "%" and basis == "level"
    elif indicator in _OPENINGS:
        family, valid = "openings", unit in _PERSON_UNITS and basis == "level"
    elif indicator in _POLICY:
        family, valid = "policy", unit == "%" and basis == "level"
    else:
        return "지표 정의 미확인: 수치만으로 경제적 의미 판단 보류"
    if not valid:
        return "비교기준·단위 미확인 또는 지원 범위 밖: 수준값과 증감률을 구분할 수 없어 해석 보류"

    previous, prior_direction, prior_note = _comparison(row, "previous", actual)
    _, forecast_direction, forecast_note = _comparison(row, "forecast", actual)
    caution = ""
    if family in {"inflation", "growth", "jobs"}:
        observation = _change_reading(subject or "비농업고용", _BASIS[basis], actual, previous,
                                      prices=family == "inflation", jobs=family == "jobs")
        if indicator == "KR_EXPORTS":
            caution = "수출금액 변화만으로 물량·기업이익·원화 방향은 확정 불가"
        elif "RETAIL" in indicator:
            caution = "명목 판매액으로 실질 소비 증가를 확정할 수 없음"
        elif "PPI" in indicator:
            caution = "생산단계 가격 변화의 소비자물가 전가는 미확정"
    elif family == "unemployment":
        observation = _level_reading("실업률", prior_direction)
        caution = "노동참가율 변화는 별도 확인 필요"
    elif family == "openings":
        observation = _level_reading("JOLTS 구인건수", prior_direction)
        caution = "구인건수 수준이며 실제 신규 채용 증감은 아님"
    elif indicator == "US_FED_TARGET_UPPER":
        observation = _level_reading("연준 목표금리 상단", prior_direction)
        caution = "일별 목표상단 관측값이며 새로운 FOMC 결정 확인은 아님"
    else:
        observation = "정책금리 " + {1: "인상", -1: "인하", 0: "동결"}.get(prior_direction, "수준") + " 관측"
        if prior_direction is None:
            caution = "이전 결정값 없이 인상·인하·동결 판단 불가"

    # Expected-vs-actual and prior-vs-actual may disagree. Do not select one
    # silently or turn a revised prior comparison into a market surprise.
    opposite = (prior_direction is not None and forecast_direction is not None
                and prior_direction * forecast_direction < 0)
    if opposite:
        effect = "이전값·예상치 대비 방향이 엇갈려 금리·실적 영향은 단정 불가"
    else:
        direction = forecast_direction if forecast_direction is not None else prior_direction
        effect = _conditional_effect(family, direction)
        if forecast_direction is not None:
            effect = "예상치 대비 해석: " + effect
    parts = [observation, prior_note, forecast_note, effect, caution]
    return ". ".join(part for part in parts if part)


def economic_reading_with_reaction(row):
    """Keep the pure reading intact, then contrast a verified same-day reaction."""
    reading = economic_implication(row)
    indicator, actual = text(row.get("indicator")), number(row.get("actual"))
    if (indicator not in _INFLATION or not indicator.startswith("US_") or actual is None
            or row.get("unit") != "%" or row.get("basis") not in {"MoM", "YoY"}
            or row.get("status") in {"pending", "scheduled", "stale", "예정"}
            or not row.get("release_at") or not row.get("reaction_source")):
        return reading
    _, prior, _ = _comparison(row, "previous", actual)
    _, forecast, _ = _comparison(row, "forecast", actual)
    if prior is not None and forecast is not None and prior * forecast < 0:
        return reading
    direction = forecast if forecast is not None else prior
    reaction = re.search(r"10Y\s+([+-]?\d+(?:\.\d+)?)bp", text(row.get("reaction")))
    rate = float(reaction[1]) if reaction else None
    if direction and rate is not None and abs(rate) >= 5 and direction * rate < 0:
        reading += ". 동일일 움직임이 단순 해석과 어긋남: 발표일 10Y " + f"{rate:+.2f}bp" + ". 기대 선반영·다른 재료의 기여는 미확인(인과 아님)"
    return reading
