"""Evidence-led conditional responses, separate from investment permission."""

from collections.abc import Mapping
import math

import pandas as pd

from stock_lab_core.decision_brief import text
from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.formatters import escape_html_value, format_currency
from stock_lab_core.precision_observation import build_precision_observation_rows, duration_observation
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.scenario_evidence import build_scenario_evidence, scenario_evidence_rows, conditional_price_rows


def _map(value):
    return value if isinstance(value, Mapping) else {}


def _positive(value):
    if pd.api.types.is_bool(value):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def _flow_available(decision):
    count = _positive(decision.get("vol_valid_count"))
    ratio = _positive(decision.get("vol_ratio"))
    mfi = decision.get("mfi")
    try:
        return (count is not None and count.is_integer() and ratio is not None
                and not pd.api.types.is_bool(mfi) and 0 <= float(mfi) <= 100
                and _map(decision.get("live_quote")).get("volume_status") != "missing_live_volume")
    except (TypeError, ValueError):
        return False


def _channel_position(chart, frame, ticker):
    """Compare only the rail and candle at the same captured daily timestamp."""
    channel = _map(chart.get("channel"))
    unknown = {"available": False, "provisional": True, "inside": False,
               "location": "유효한 현재 일봉 채널 위치 미확인", "support": "미확인", "resistance": "미확인"}
    if channel.get("ended_at") is not None:
        return dict(unknown, location="과거 채널 종료 · 현재 지지선으로 재사용하지 않음")
    if channel.get("execution_guide_eligible") is False:
        return dict(unknown, location=text(channel.get("display_state")) + " · 현재 지지 확인 보류")
    if (not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame
            or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans
            or not frame.index.is_monotonic_increasing or not frame.index.is_unique):
        return unknown
    try:
        at = frame.index[-1]
        expected, decision_at = pd.Timestamp(chart.get("expected_close")), pd.Timestamp(chart.get("decision_asof"))
        if (pd.isna(expected) or pd.isna(decision_at) or at.date() != expected.date()
                or at.date() != decision_at.date()):
            return dict(unknown, location="완료 거래일·판정 기준일 정합성 미확인 · 현재 채널 가격 제시 보류")
        known_at = pd.Timestamp(channel["known_at"])
        if pd.isna(known_at) or pd.Timestamp(channel["x"][-1]) != at or known_at > at:
            return unknown
        lower, upper = _positive(channel["lower"][-1]), _positive(channel["upper"][-1])
        close = _positive(frame.iloc[-1]["Close"])
        if None in (lower, upper, close) or lower >= upper:
            return unknown
    except (KeyError, IndexError, TypeError, ValueError):
        return unknown
    provisional = chart.get("provisional_last") is not False
    if "LiveQuoteOnly" in frame:
        flag = frame.iloc[-1]["LiveQuoteOnly"]
        provisional = provisional or pd.isna(flag) or bool(flag)
    percent = (close - lower) / (upper - lower) * 100
    return {"available": True, "provisional": provisional, "inside": lower <= close <= upper,
            "support": format_currency(lower, ticker), "resistance": format_currency(upper, ticker),
            "location": f"{at:%Y-%m-%d} 일봉 {format_currency(close, ticker)} · 채널 내 위치 {percent:.1f}% "
                        f"(하단 0 / 상단 100) · {'미확정 봉' if provisional else '완료 봉'}"}


def _original_plan(plan, decision, ticker):
    plan = _map(plan)
    valid = str(plan.get("ticker", "")).upper() == str(ticker).upper() and plan.get("status") != "unavailable"
    numbers = [_positive(plan.get(key)) for key in ("stop", "current_price", "target")]
    valid = valid and all(n is not None for n in numbers)
    if valid:
        stop, current, target = numbers
        valid = stop < current < target and all(
            plan.get(key) == _positive(decision.get(source))
            for key, source in (("stop", "rr_stop"), ("current_price", "cur_p"), ("target", "rr_target"))
        )
    if not valid:
        return {"valid": False, "entry": "원계획 미확인/불일치 · 가격 제시 보류",
                "target": "미확인", "stop": "미확인"}
    rows = plan.get("rows") if isinstance(plan.get("rows"), list) else []
    entry = next((row for row in rows if isinstance(row, Mapping)
                  and str(row.get("단계", "")).startswith(("추가 1차", "1차 진입"))), {})
    return {"valid": True, "entry": text(entry.get("가격")) + " · " + text(entry.get("조건")),
            "target": ("강세 시나리오 상단(예상 확정값 아님): " if decision.get("rr_target_is_projection") is True else "구조 목표: ")
                      + format_currency(plan["target"], ticker) + " · " + text(plan.get("target_source")),
            "stop": format_currency(plan["stop"], ticker) + " · " + text(plan.get("stop_source"))}


def _current_sell_event(chart, frame):
    events = chart.get("events")
    if not isinstance(events, list) or not isinstance(frame, pd.DataFrame) or frame.empty:
        return ""
    if (not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans
            or not frame.index.is_unique or not frame.index.is_monotonic_increasing):
        return ""
    try:
        expected, decision_at = pd.Timestamp(chart.get("expected_close")), pd.Timestamp(chart.get("decision_asof"))
        if (pd.isna(expected) or pd.isna(decision_at) or frame.index[-1].date() != expected.date()
                or frame.index[-1].date() != decision_at.date()):
            return ""
    except (TypeError, ValueError):
        return ""
    for event in reversed(events):
        if not isinstance(event, Mapping) or event.get("side") != "sell" or event.get("provisional") is not False:
            continue
        try:
            at, known = pd.Timestamp(event.get("time")), pd.Timestamp(event.get("known_at"))
            if (pd.notna(at) and pd.notna(known) and known <= at == frame.index[-1]
                    and chart.get("provisional_last") is False):
                return f"{at:%Y-%m-%d} {text(event.get('name'))} · {text(event.get('confirmation'))}"
        except (TypeError, ValueError):
            continue
    return ""


def _attach_completed_observations(model, context, ticker):
    """Enrich conditional responses without changing the original focus or execution gate."""
    if "daily_source" not in context:
        return model
    evidence = build_scenario_evidence(context.get("daily_source"), context.get("expected_close"),
                                       profile=context.get("completed_profile"))
    model["completed_evidence"] = evidence
    rows = scenario_evidence_rows(evidence, ticker)
    model["price_rows"] = conditional_price_rows(evidence, ticker)
    if not rows:
        model["thesis"] += " 완료봉 관측: " + evidence["status"] + "."
        return model
    structure_note = model["axes"][0]["해석"]
    model["axes"] = rows
    # Current quote volume and last completed volume are different evidence sets.
    model["thesis"] = structure_note + (f" 아래 가격·진폭·거래량은 {evidence['asof']} {evidence['status']} 기준입니다. "
                         "현재 시세의 미확인 거래량과 구분하며, 관측 가격은 체결가나 매수 허가가 아닙니다.")
    model["price_basis"] = f"시나리오 종가 {format_currency(evidence['close'], ticker)} · {evidence['asof']} / 기존 판정 입력 {context.get('decision_price_label', '시각·세션 미확인')}"
    quote = _map(context.get("quote_evidence"))
    if quote.get("status") == "연결됨" and _positive(quote.get("price")):
        model["quote_basis"] = (f"별도 참고시세 {format_currency(quote['price'], ticker)} · {quote.get('session', '세션 미확인')} "
                                 f"· {quote.get('as_of', '시각 미확인')} · 완료봉/기존 판정 입력과 혼합하지 않음")
        support, recovery = evidence.get("support"), evidence.get("recovery")
        if evidence["fresh"] and support and recovery:
            position = ("하방 관찰선 아래 · 종가 이탈 확정 전" if quote["price"] < support["price"]
                        else "회복 장벽 위 · 종가 회복 확정 전" if quote["price"] > recovery["price"]
                        else "관찰 가격 범위 안 · 지지 확인/매집 확정 아님")
            model["quote_basis"] += " / " + position
    for item, prices in zip(model["scenarios"], model["price_rows"]):
        item["legacy_prices"] = item["prices"]
        item["price_observations"] = prices
        item["prices"] = " / ".join(f"{key}: {prices[key]}" for key in ("확인 가격", "다음 가격", "실패·전환", "가격비율"))
        if prices["안"] == "A":
            item["evidence"] = rows[0]["관측"] + " / " + rows[2]["해석"]
            item["condition"] = (prices["확인 가격"] + ". 같은 완료 일봉에서 회복 유지와 거래량 반응을 확인. "
                                  "상위 추세훼손은 반대 근거이며 기존 최종 체크를 우회하지 않음.")
        elif prices["안"] == "B":
            item["condition"] = (prices["확인 가격"] + ". 이 가격은 관측된 구조 이탈 기준이며 기존 계획 손절선과 별개. "
                                  "보유분 위험 재검토 조건이지 자동 전량매도 지시가 아님.")
        else:
            item["condition"] = (prices["확인 가격"] + ". 범위 내 반응과 다음 완료봉을 비교. "
                                  "진폭·거래량 수축 여부는 기간 축의 수치로 확인하며 매집으로 단정하지 않음.")
            item["evidence"] = rows[2]["관측"] + " / " + rows[3]["관측"]
    return model


def build_precision_scenarios(decision, ticker, context, plan, *, has_pos=False):
    """Synthesize captured facts, never recalculate scores, orders or target prices."""
    decision, context = _map(decision), _map(context)
    ready = build_execution_readiness(decision.get("execution_workflow"), decision.get("chart_final_check"))
    pack = _map(context.get("multi_timeframe"))
    daily = _map(pack.get("일봉"))
    chart = _map(_map(decision.get("chart_structure")).get("일봉"))
    states = {tf: text(_map(_map(pack.get(tf)).get("snapshot")).get("state")) for tf in ("월봉", "주봉", "일봉")}
    up = {"상승 유지", "상승 눌림권", "상승추세 내 조정", "상승 과열권"}
    higher_up = all(states[tf] in up for tf in ("월봉", "주봉"))
    higher_provisional = any(_map(_map(decision.get("chart_structure")).get(tf)).get("provisional_last") is not False
                             for tf in ("월봉", "주봉"))
    damaged = [tf for tf, state in states.items() if state == "추세훼손"]
    location = _channel_position(chart, daily.get("df"), ticker)
    refs = _original_plan(plan, decision, ticker)
    _, _, duration_known = duration_observation(chart, daily.get("df"))
    flow_known = _flow_available(decision)
    axes = build_precision_observation_rows(decision, ticker, context)
    current_sell = _current_sell_event(chart, daily.get("df"))
    structure = ("·".join(damaged) + " 추세훼손이 있어 일봉 반등만으로 회복을 확정하지 않습니다." if damaged
                 else "상위 두 시간대가 상승 계열입니다. 일봉 지지와 회복 반응을 별도로 확인합니다." if higher_up
                 else "상위 시간대의 상승 정렬이 확인되지 않아 일봉 신호만으로 방향을 단정하지 않습니다.")
    if higher_provisional:
        structure += " 주·월봉 미확정 또는 완료 여부 미확인: 상위 흐름은 잠정 해석입니다."
    if current_sell:
        structure += " 현재 완료봉의 반대 근거: " + current_sell
    # Do not repeat stale rails from the raw observation formatter as current support.
    current = _positive(decision.get("cur_p"))
    axes[1] = dict(axes[1], 관측="판정가 " + (format_currency(current, ticker) if current else "미확인") + " · " + location["location"])
    interpretations = [structure,
        "범위 내 위치는 기업 저평가나 반등 확률이 아닙니다.",
        "표시된 형성·지속 기간을 근거로 다음 일봉을 비교합니다. 기간만으로 조정 충분·에너지 축적을 확정할 수 없습니다.",
        "거래량·MFI·추정 매물대는 가격 반응의 보조 근거입니다. 손절 주문량·참가자 의도·유동성 사냥 완료는 미확인입니다."]
    axes = [dict(row, 해석=interpretation) for row, interpretation in zip(axes, interpretations)]
    if damaged or current_sell:
        focus, thesis = "B안 · 보유 위험 우선 점검", structure
    elif (higher_up and location["available"] and location["inside"] and not location["provisional"]
          and refs["valid"] and duration_known and flow_known):
        focus, thesis = "A안 · 지지·회복 조건 관찰", "상위 상승 흐름과 완료 일봉의 채널 내부 위치는 회복 관찰 근거입니다. 반등 확정이나 진입 신호는 아닙니다."
        if higher_provisional:
            focus += " (상위 봉 잠정)"
            thesis += " 주·월봉은 미확정/확정 여부 미확인으로 상승 유지가 확정된 상태는 아닙니다."
    else:
        focus, thesis = "C안 · 방향·자료 확인 대기", "구조 정렬, 유효 채널, 완료봉 또는 원계획이 함께 확인되지 않아 A안 성립을 미리 가정하지 않습니다."
    if not duration_known or not flow_known:
        missing = [label for label, known in (("기간의 확인봉", duration_known), ("현재 거래량·MFI", flow_known)) if not known]
        thesis += " " + "·".join(missing) + " 근거가 부족해 네 축의 동행을 확정할 수 없습니다."
    else:
        thesis += " 형성 기간과 거래량·MFI는 관측됐지만, 조정의 충분성이나 반등 우위는 별도 검증이 필요합니다."
    execution = ("기존 최종 체크 통과 · 원계획 재검토" if ready["execution_allowed"]
                 else "신규·추가매수 보류 유지 · " + str(ready["reason"]))
    lower, upper = location["support"], location["resistance"]
    scenarios = [
        {"name": "A안 · 지지·회복", "evidence": structure + " " + location["location"] + (" 기간·거래량 근거 연결." if duration_known and flow_known else " 기간/거래량 근거 추가 확인 필요."),
         "condition": f"현재 일봉 채널 하단 {lower}. 같은 일봉 완료 후 하단 유지·회복 여부를 확인하고 주·월봉 흐름과 거래량을 다시 대조.",
         "holding": "보유 유지 조건을 점검하되 반등만으로 추가매수하지 않음" if has_pos else "미보유 · 조건 확인 전 진입 대기",
         "new_money": execution,
         "prices": "기존 1차 계획: " + refs["entry"] + " / 기존 목표: " + refs["target"],
         "invalidate": "일봉 지지 실패, 상위 추세훼손 또는 자료 미확인 시 A안 보류. B/C안으로 재점검."},
        {"name": "B안 · 이탈·악화", "evidence": (current_sell or "·".join(damaged) + " 추세훼손" if current_sell or damaged else "현재 완료봉의 이탈 신호 미확인 · 앞으로의 악화에 대비하는 조건부 계획"),
         "condition": f"기존 손절 참고선 {refs['stop']}. 신규·추가매수 계획 무효선이며 보유분 매도선과 별도. 원계획의 일봉 종가 이탈 조건과 갭·체결 위험을 확인. 종료된 채널을 새 지지로 사용하지 않음.",
         "holding": "보유분 축소·손절 조건 우선 점검 · 자동 전량매도 명령 아님" if has_pos else "미보유 · 하락만으로 신규진입하지 않음",
         "new_money": "추가매수로 손실을 덮지 않고 기존 제한과 현금 대기를 유지",
         "prices": "기존 손절 참고선: " + refs["stop"] + " · 실제 청산가격 보장 아님",
         "invalidate": "같은 시간봉의 지지 회복과 상위 구조 재확인 시 재평가. 한 번의 반등으로 시장방어를 해제하지 않음."},
        {"name": "C안 · 횡보·관망", "evidence": "기간: " + axes[2]["관측"] + " / 거래량·MFI: " + ("현재 자료 연결" if flow_known else "현재 근거 부족") + " · 횡보 확정 판정과는 별개",
         "condition": f"현재 유효 범위 {lower}~{upper}. 방향이 엇갈리거나 완료봉·기간·거래량 근거가 부족하면 관찰 유지.",
         "holding": "보유분은 원래 손절·익절 조건을 유지하며 다음 완료봉에서 A/B안 재검토" if has_pos else "미보유 · 현금 대기와 관찰 지속",
         "new_money": "목표비중 미달이나 가격 하락 자체를 추가매수 근거로 사용하지 않음",
         "prices": "범위 미확인 시 임의 지지·저항·매수가를 만들지 않음",
         "invalidate": "A의 지지·회복 또는 B의 이탈 조건을 확인하면 해당 안을 재점검."},
    ]
    return _attach_completed_observations({"ticker": ticker, "focus": focus, "thesis": thesis, "execution": execution,
            "axes": axes, "scenarios": scenarios, "location": location, "plan": refs,
            "ready": ready, "has_pos": bool(has_pos), "duration_known": duration_known, "flow_known": flow_known}, context, ticker)


def render_precision_scenarios(st, model):
    escape = escape_html_value
    st.subheader("4축 분석 · A/B/C 대응계획")
    st.markdown(f"<p><b>{escape(model['focus'])}</b><br>{escape(model['thesis'])}<br>"
                f"<b>현재 실행:</b> {escape(model['execution'])}</p>", unsafe_allow_html=True)
    st.caption("일봉 관리 시나리오 · 실시간 발동·승률 판정 아님 · 1시간/5분 단타 계획과 별도")
    if model.get("price_basis"):
        st.caption(model["price_basis"].replace("$", r"\$"))
    if model.get("quote_basis"):
        st.caption(model["quote_basis"].replace("$", r"\$"))
    from contextlib import nullcontext
    expanded_evidence = _map(model.get("completed_evidence")).get("available")
    with nullcontext() if expanded_evidence else st.expander("구조·가격·시간·유동성 근거", expanded=False):
        rows = "".join(f"<tr><th style='width:80px;vertical-align:top;text-align:left;padding:8px;'>{escape(row['축'])}</th>"
                       f"<td style='padding:8px;'><b>{escape(row['관측'])}</b><br>{escape(row['해석'])}"
                       f"<br><small>{escape(row['기준·제한'])}</small></td></tr>" for row in model["axes"])
        st.markdown("<table style='width:100%;table-layout:fixed;overflow-wrap:anywhere;line-height:1.6;'>" + rows + "</table>", unsafe_allow_html=True)
    # Open the scenario named by the summary first, without changing its analysis.
    scenarios = sorted(model["scenarios"], key=lambda row: not model["focus"].startswith(row["name"][:2]))
    for tab, item in zip(st.tabs([row["name"] for row in scenarios]), scenarios):
        with tab:
            if item.get("price_observations"):
                p = item["price_observations"]
                cells = "".join(f"<tr><th style='width:85px;padding:8px;text-align:left;vertical-align:top;'>{escape(key)}</th>"
                                f"<td style='padding:8px;'>{escape(p[key])}</td></tr>"
                                for key in ("확인 가격", "다음 가격", "실패·전환", "가격비율"))
                st.markdown("<table style='width:100%;table-layout:fixed;overflow-wrap:anywhere;'>" + cells + "</table>", unsafe_allow_html=True)
            rows = [("현재 근거·반대 근거", item["evidence"]), ("확인 조건", item["condition"]), ("보유분", item["holding"]),
                    ("신규·추가 자금", item["new_money"]),
                    ("무효화·전환", item["invalidate"])]
            if not item.get("price_observations"):
                rows.insert(-1, ("가격 기준", item["prices"]))
            st.markdown("".join(f"<p><b>{escape(label)}</b><br>{escape(value)}</p>" for label, value in rows), unsafe_allow_html=True)
            if item.get("legacy_prices"):
                with st.expander("기존 실행계획 가격과의 구분", expanded=False):
                    st.markdown(escape(item["legacy_prices"]) + "<br>관찰 가격은 기존 주문·배분·손절 계산을 대체하지 않습니다.", unsafe_allow_html=True)
    st.caption("네 축은 상관된 관측일 수 있습니다. 점수를 중복 가산하지 않으며 기존 시장방어·최종 체크·가격·주수를 바꾸지 않습니다.")


register_loaded_source(__name__, __file__)
