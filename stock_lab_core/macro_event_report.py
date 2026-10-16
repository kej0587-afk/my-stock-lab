"""Result-first economic release formatting, independent of trading gates."""

from decimal import Decimal, InvalidOperation
import re


REPORT_ONLY_EVENTS = {"미국 PCE 발표", "미국 JOLTS 발표", "미국 GDP 발표"}


def event_value(row, *keys):
    for key in keys:
        value = row.get(key)
        text = "" if value is None else str(value).strip()
        if text.lower() not in {"", "none", "nan", "<na>", "n/a", "-", "nat"}:
            return text
    return ""


def event_observations(event):
    stored = event.get("release_observations")
    if isinstance(stored, list) and stored:
        return [dict(item) for item in stored if isinstance(item, dict)]
    return [{
        "series": event_value(event, "raw_title", "event", "이벤트"),
        "actual": event_value(event, "actual", "실제"),
        "forecast": event_value(event, "forecast", "예상", "consensus"),
        "previous": event_value(event, "previous", "이전"),
        "source": event_value(event, "source", "출처"),
    }]


def merge_event_observations(primary, secondary):
    # Never merge Core/headline or MoM/YoY values into a single observation.
    result = {}
    for item in event_observations(primary) + event_observations(secondary):
        key = item["series"].lower()
        old = result.get(key)
        if old is None or (not old["actual"] and item["actual"]):
            result[key] = item
    observations = list(result.values())
    with_values = [item for item in observations if any(item[key] for key in ("actual", "forecast", "previous"))]
    return with_values or observations


def _number(text):
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(%|[KM])?", text.replace(",", ""), re.I)
    if not match:
        return None
    try:
        value = Decimal(match[1])
    except InvalidOperation:
        return None
    suffix = (match[2] or "").upper()
    value *= {"K": 1000, "M": 1000000}.get(suffix, 1)
    return value, "%" if suffix == "%" else "number"


def _delta(actual, other):
    a, b = _number(actual), _number(other)
    if a is None or b is None or a[1] != b[1]:
        return None
    return a[0] - b[0], "%p" if a[1] == "%" else ""


def release_market_meaning(series, actual, forecast):
    delta = _delta(actual, forecast)
    if delta is None:
        return "예상 대비 판단 불가. 발표 수치만으로 주가 방향을 단정하지 않습니다."
    difference = delta[0]
    if difference == 0:
        return "예상과 일치. 수치 자체의 서프라이즈는 없으며 금리·지수 반응은 별도 확인입니다."
    low = series.lower()
    if any(term in low for term in ("cpi", "ppi", "pce", "물가")):
        return ("예상 상회: 물가 부담과 금리 인하 기대 약화 가능성. 성장주에 부담이 될 수 있으나 실제 금리 반응은 미확인입니다."
                if difference > 0 else
                "예상 하회: 물가 부담 완화 가능성. 금리 하락이 동반되는지 확인해야 하며 주가 상승을 보장하지 않습니다.")
    if any(term in low for term in ("gdp", "jolts", "고용", "job openings")):
        return ("예상 상회: 경기·노동수요 지지와 금리 부담이 공존합니다. 지수 반응은 별도 확인입니다."
                if difference > 0 else
                "예상 하회: 금리 부담 완화와 경기 둔화 우려가 공존합니다. 지수 반응은 별도 확인입니다.")
    return "예상과 차이가 있습니다. 정책 성명·세부 구성과 금리 반응이 미연결이므로 방향 해석은 보류합니다."


def event_release_summary(row):
    """Return a display string only; never substitute forecast for actual."""
    name = event_value(row, "이벤트", "event")
    if not any(term in name.lower() for term in ("cpi", "ppi", "pce", "gdp", "jolts", "고용", "fomc")):
        return ""
    observations = row.get("발표항목")
    if not isinstance(observations, list) or not observations:
        observations = event_observations(row)
    # Preserve legacy result text when only a preformatted result is available.
    legacy = event_value(row, "결과")
    if not any(event_value(item, "actual") for item in observations) and "실제 " in legacy:
        meaning = event_value(row, "주식시장 해석", "해석")
        return legacy + (f" → {meaning}" if meaning else "")
    state = event_value(row, "상태")
    if state in {"대기", "임박"}:
        return ""
    if "fomc" in name.lower() and not any(event_value(item, "actual") for item in observations):
        return ""  # Keep the existing statement/news interpretation for FOMC.
    parts = []
    for item in observations[:4]:
        actual, forecast, previous = (event_value(item, key) for key in ("actual", "forecast", "previous"))
        label = event_value(item, "series") or name
        label = label.replace("m/m", "전월비").replace("y/y", "전년비").replace("q/q", "전분기비")
        if not actual:
            status = "발표일 경과·실제 결과 미수집" if state in {"잔여", "종료"} else "실제 결과 미수집·발표 전후 미확인"
            parts.append(f"{label}: {status} (예상 {forecast or '미수집'} / 이전 {previous or '미수집'}). 결과 방향 해석 보류")
            continue
        comparison = []
        for heading, other in (("예상", forecast), ("이전 발표", previous)):
            delta = _delta(actual, other)
            if delta is not None:
                comparison.append(f"{heading} 대비 {delta[0]:+g}{delta[1]}")
        values = f"실제 {actual} / 예상 {forecast or '미수집'} / 이전 {previous or '미수집'}"
        comparison_text = f" ({'; '.join(comparison)})" if comparison else ""
        source = event_value(item, "source") or event_value(row, "출처")
        source_text = f" · 출처 {source}" if source else ""
        parts.append(f"{label}: {values}{comparison_text} → {release_market_meaning(label, actual, forecast)}{source_text}")
    if len(observations) > 4:
        parts.append(f"세부 지표 {len(observations) - 4}개는 이벤트 표 참고")
    return " / ".join(parts)
