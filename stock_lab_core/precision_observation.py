"""Four factual observation axes from captured inputs, without scoring or IO."""

from collections.abc import Mapping
from datetime import date
import math

import pandas as pd

from stock_lab_core.execution_readiness import precision_display_context
from stock_lab_core.formatters import clean_float, escape_html_value, format_currency


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip().lower() not in {
        "", "-", "nan", "none", "nat",
    } else "미확인"


def _date(value):
    if not isinstance(value, (str, date)):
        return "미확인"
    try:
        stamp = pd.Timestamp(value)
        return stamp.strftime("%Y-%m-%d") if pd.notna(stamp) else "미확인"
    except (TypeError, ValueError, OverflowError):
        return "미확인"


def _number(value, spec=".2f", suffix=""):
    number = clean_float(value, math.nan)
    return format(number, spec) + suffix if math.isfinite(number) else "미확인"


def _price(value, ticker):
    number = clean_float(value, math.nan)
    return format_currency(number, ticker) if math.isfinite(number) and number > 0 else "미확인"


def _channel_location(channel, ticker):
    if not channel:
        return "채널 미표시/자료 없음"
    if channel.get("ended_at") is not None:
        return f"과거 채널 · {_date(channel['ended_at'])} 종료 · 현재 가격 비교 제외"
    if not channel.get("execution_guide_eligible", True):
        return f"{_text(channel.get('display_state'))} · 현재 가격 비교 제외"
    levels = []
    for key, label in (("lower", "하단"), ("upper", "상단")):
        values = channel.get(key)
        value = values[-1] if isinstance(values, (list, tuple)) and values else None
        levels.append(f"{label} {_price(value, ticker)}")
    return f"채널 {_text(channel.get('state'))} · " + " / ".join(levels)


def _duration(chart, frame):
    events = chart.get("events")
    event = _mapping(events[-1]) if isinstance(events, list) and events else {}
    if event:
        start, end = _date(event.get("formation_start")), _date(event.get("formation_end"))
        count = "관측봉 수 미확인"
        # Count supplied observations, not calendar days or assumed sessions.
        if (isinstance(frame, pd.DataFrame) and isinstance(frame.index, pd.DatetimeIndex)
                and frame.index.is_monotonic_increasing and frame.index.is_unique and not frame.index.hasnans):
            dates = frame.index.strftime("%Y-%m-%d")
            if start in dates and end in dates and start <= end:
                count = f"{int(((dates >= start) & (dates <= end)).sum())}개 관측봉"
        observed = f"일봉 {_text(event.get('name'))} 형성 {start}~{end} · {count}"
        status = "미확정 관측" if event.get("provisional") else "확인봉"
        note = f"피벗 확인 {_date(event.get('known_at'))} · {status} {_date(event.get('time'))}"
        return observed, note
    patterns = chart.get("patterns")
    pattern = _mapping(patterns[0]) if isinstance(patterns, list) and patterns else {}
    if pattern:
        age = clean_float(pattern.get("age"), math.nan)
        elapsed = f"{int(age)}봉" if math.isfinite(age) and age >= 0 and age.is_integer() else "미확인"
        return (f"일봉 {_text(pattern.get('name'))} · 형성 말단 이후 {elapsed}",
                f"피벗 확인 {_date(pattern.get('known_at'))} · 돌파/이탈 확인봉 자료 없음")
    return "일봉 패턴 기간 미확인", "형성·확인 날짜 자료 없음"


def build_precision_observation_rows(decision, ticker, context):
    """Only format existing observations; missing evidence remains unknown."""
    decision, context = _mapping(decision), _mapping(context)
    pack = _mapping(context.get("multi_timeframe"))
    charts = _mapping(decision.get("chart_structure"))
    daily = _mapping(pack.get("일봉"))
    snapshot = _mapping(daily.get("snapshot"))
    chart = _mapping(charts.get("일봉"))
    basis = _mapping(context.get("signal_basis"))
    states, sources = [], []
    for label in ("월봉", "주봉", "일봉"):
        item = _mapping(pack.get(label))
        state = _text(_mapping(item.get("snapshot")).get("state"))
        if _mapping(charts.get(label)).get("provisional_last"):
            state += " (미확정 봉 포함)"
        states.append(f"{label} {state}")
        source = basis.get("가격자료기준일") if label == "일봉" or item.get("source_kind") == "daily_fallback" else item.get("source_asof")
        sources.append(f"{label} {_date(source)}")
    patterns = chart.get("patterns")
    if isinstance(patterns, list) and patterns:
        pattern = _mapping(patterns[0])
        states.append(f"일봉 {_text(pattern.get('name'))} · {_text(pattern.get('lifecycle'))}")

    location = (f"판정가 {_price(decision.get('cur_p'), ticker)} · "
                f"일봉 MA20 이격 {_number(snapshot.get('ma20_gap'), '+.1f', '%')} · "
                f"%B {_number(snapshot.get('pct_b'))}")
    location += " / " + _channel_location(_mapping(chart.get("channel")), ticker)
    duration, duration_note = _duration(chart, daily.get("df"))

    ratio = clean_float(decision.get("vol_ratio"), math.nan)
    count = clean_float(decision.get("vol_valid_count"), math.nan)
    ratio_text = _number(ratio, ".2f", "x") if ratio >= 0 else "미확인"
    count_text = f"{int(count)}개 유효봉" if math.isfinite(count) and count > 0 and count.is_integer() else "기준봉 수 미확인"
    mfi = clean_float(decision.get("mfi"), math.nan)
    mfi_text = _number(mfi, ".1f") if 0 <= mfi <= 100 else "미확인"
    liquidity = f"기존 거래량 기준비 {ratio_text} ({count_text}) · MFI {mfi_text}"
    profile = _mapping(context.get("liquidity_profile"))
    poc = _mapping(profile.get("poc")) if profile.get("ok") is True else {}
    low, high = clean_float(poc.get("low"), math.nan), clean_float(poc.get("high"), math.nan)
    liquidity += (f" · 추정 최대 매물대 {_price(low, ticker)}~{_price(high, ticker)}"
                  if math.isfinite(low) and math.isfinite(high) and 0 < low <= high
                  else " · 추정 매물대 미확인")
    quote = _mapping(decision.get("live_quote"))
    volume_basis = _text(basis.get("수급자료기준"))
    if quote.get("volume_status") == "missing_live_volume":
        volume_basis = f"최신 거래량 미확인 · MFI 기준 {_date(quote.get('mfi_asof'))}"
    return [
        {"축": "구조", "관측": " / ".join(states), "기준·제한": "원자료 " + " / ".join(sources)},
        {"축": "가격 위치", "관측": location, "기준·제한": _text(basis.get("가격반영"))},
        {"축": "기간", "관측": duration, "기준·제한": duration_note},
        {"축": "유동성 대용치", "관측": liquidity,
         "기준·제한": f"{volume_basis} · 봉 범위에 거래량을 배분한 추정 매물대; 실제 순유입·호가 잔량 아님"},
    ]


def render_precision_observation(decision, ticker, context):
    display = precision_display_context(dict(_mapping(decision)))
    workflow = _mapping(display.get("execution_workflow"))
    escape = escape_html_value
    rows = build_precision_observation_rows(decision, ticker, context)
    cells = "".join(
        f"<tr><th scope='row' style='width:72px;vertical-align:top;text-align:left;padding:8px;'>"
        f"{escape(row['축'])}</th><td style='padding:8px;'>"
        f"{escape(row['관측'])}<br><small>{escape(row['기준·제한'])}</small></td></tr>"
        for row in rows
    )
    return (
        "<section style='overflow-wrap:anywhere;line-height:1.6;'>"
        "<b>관측 요약</b>"
        f"<p><b>현재 실행</b>: {escape(_text(workflow.get('게이트상태')))} · "
        f"{escape(_text(workflow.get('게이트근거')))}<br>"
        f"<b>기술적 원신호</b>: {escape(_text(_mapping(decision).get('dec')))}</p>"
        f"<table style='width:100%;table-layout:fixed;border-collapse:collapse;'>{cells}</table>"
        "</section>"
    )
