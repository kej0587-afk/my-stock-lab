"""Explain the existing guard inputs without granting or changing execution."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import number

register_loaded_source(__name__, __file__)


def compose_market_guard_score(regional, flow, macro, event):
    """Extracted unchanged from build_today_market_guard; return actual additions."""
    parts = {"regional": int(regional), "flow": int(flow) if flow > 0 else 0,
             "macro": int(macro) if macro >= 2 or (macro == 1 and regional < 5) else 0,
             "event": int(event) if event >= 2 or (event == 1 and regional < 5) else 0,
             "combined": 1 if regional >= 5 and macro + event >= 3 else 0}
    return sum(parts.values()), parts


def _score_release(score):
    if score is None:
        return "점수 미연결"
    for limit, label in ((8, "위험"), (5, "방어"), (2, "주의")):
        if score >= limit:
            return f"{label} 구간 이탈: {limit} 미만, 최소 {int(score)-limit+1}점 감소"
    return "점수상 정상 구간"


def _flow_release(value, *, breadth=False):
    if value is None:
        return "미연결"
    target = .35 if value < .35 else .50 if breadth and value < .50 else None
    points = (2 if value < .35 else 1 if value < .50 else 0) if breadth else int(value < .35)
    if target is None:
        return f"{value*100:.1f}%·+{points}점(가점 없음)"
    gap = (target-value)*100
    distance = f"+{gap:.1f}%p" if round(gap, 1) else "+0.1%p 미만"
    return f"{value*100:.1f}%·+{points}점 → {target*100:g}% 이상({distance})"


def _macro_release(guard):
    parts = []
    for key, label, high, low in (("macro_pressure", "부담", 4, 2), ("macro_risk", "리스크", 4.5, 3.5)):
        value = number(guard.get(key))
        if value is None:
            parts.append(label + " 미연결")
        elif value >= low:
            parts.append(f"{label} {value:g} → {high if value >= high else low:g} 미만")
        else:
            parts.append(f"{label} {value:g}(가점 없음)")
    return " / ".join(parts)


def _tactical_rebound_lines(guard):
    def value(key, percent=False):
        val = number(guard.get(key))
        return "미연결" if val is None else f"{val*100:.1f}%" if percent else f"{val:g}"

    def gap(key, target, percent=False):
        val = number(guard.get(key))
        if val is None:
            return "미연결·확인 필요"
        if val >= target:
            return "충족"
        if percent:
            remaining = (target-val)*100
            return f"+{remaining:.1f}%p 필요" if round(remaining, 1) else "+0.1%p 미만 필요"
        return f"{target-val:g}개 추가 필요"

    missing = []
    score = number(guard.get("score"))
    if score is None or score < 8:
        missing.append("통합 8 이상 조건 " + ("미연결" if score is None else "미충족"))
    for key, label in (("circuit_day", "-8% 급락"), ("panic_day", "-5% 급락")):
        val = number(guard.get(key))
        if val is None or val != 0:
            missing.append(f"{label} {value(key)}개 → 0개 필요")
    for alternatives in (
        (("flow_breadth", "확산", .55, True), ("flow_accel", "가속", .50, True)),
        (("strong_rebound_count", "+3% 반등 지수", 2, False), ("max_day_gain", "최대 상승", .05, True)),
    ):
        if not any(number(guard.get(key)) is not None and number(guard[key]) >= target
                   for key, _, target, _ in alternatives):
            missing.append(" 또는 ".join(f"{label} {value(key, percent)} ({gap(key, target, percent)})"
                                         for key, label, target, percent in alternatives))
    status = "미연결" if guard.get("tactical_rebound") is None else "충족" if guard["tactical_rebound"] else "미충족"
    return [f"전술 반등 예외 현재: {status} · 미달/미확인: " + (" / ".join(missing) or "없음(기존 판정 유지)"),
            f"전술 입력: 통합 {value('score')} / -8% 급락 {value('circuit_day')}개 / -5% 급락 {value('panic_day')}개 / "
            f"확산 {value('flow_breadth', True)} / 가속 {value('flow_accel', True)} / +3% 반등 {value('strong_rebound_count')}개 / 최대 상승 {value('max_day_gain', True)}. "
            "기존 조건: 통합 8 이상, -8%/-5% 급락 지수 0개, 확산 ≥55% 또는 가속 ≥50%, +3% 반등 지수 ≥2개 또는 최대 상승 ≥5%."]


def _guard_summary_lines(guard):
    score = number(guard.get("score"))
    parts = guard.get("mode_score_parts") or {}
    names = {"regional": "지역 최대", "flow": "흐름", "macro": "매크로", "event": "이벤트", "combined": "복합"}
    contributions = " + ".join(f"{label} {number(parts[key]):g}" if number(parts.get(key)) is not None
                                else label + " 미연결" for key, label in names.items()
                                if number(parts.get(key)) != 0) or "모든 구성 0"
    score_text = f"{score:g}점" if score is not None else "미연결"
    flow_options = [(target-value, label, value, target) for key, label, target in
                    (("flow_breadth", "확산", .55), ("flow_accel", "가속", .50))
                    if (value := number(guard.get(key))) is not None]
    tactical = "미연결" if guard.get("tactical_rebound") is None else "충족" if guard["tactical_rebound"] else "미충족"
    if flow_options and all(gap > 0 for gap, _, _, _ in flow_options):
        _, label, value, target = min(flow_options)
        tactical += f" · {label} {value*100:.1f}/{target*100:g}% 미달"
    elif not flow_options:
        tactical += " · 확산/가속 미연결"
    else:
        tactical += " · 나머지 조건은 아래 표"
    return [f"**핵심 요약** · 통합 {score_text} = {contributions} · {_score_release(score)}",
            "**다음 경계** · 확산 " + _flow_release(number(guard.get("flow_breadth")), breadth=True)
            + " / 매크로 " + _macro_release(guard) + "(조건부 재계산) · 전술 " + tactical]


def guard_explanation_lines(guard):
    from stock_lab_core.report_evidence import _cell, records
    guard = guard or {}
    lines = ["", "## 시장방어 게이트 근거"]
    if not guard:
        return lines + ["오늘점검 시장 게이트 입력 미연결. 스트레스 점수로 대체 계산하지 않습니다."]
    lines += [f"현재 {guard.get('scope_text', '')} · 통합 {guard.get('mode', '미확인')}"]
    lines += _guard_summary_lines(guard)
    lines += [
              "리포트 스트레스(0~100)는 설명용이며 아래 시장방어 점수와 다른 산식입니다. 값은 오늘점검 게이트 입력 스냅샷 기준이며 아래 표에서 판정을 바꾸지 않습니다.",
              "구성 요소 | 현재값 | 기존 기준 | 기준까지 남은 조건", "--- | --- | --- | ---"]

    def add(name, value, rule, remaining):
        lines.append(" | ".join(_cell(x) for x in (name, value, rule, remaining)))

    score = number(guard.get("score"))
    add("통합 시장 점수", score if score is not None else "미연결", "8 이상 위험 / 5 이상 방어 / 2 이상 주의",
        _score_release(score))
    for region, label in (("kr_stats", "한국"), ("us_stats", "미국")):
        stats = guard.get(region) or {}
        bench = [r for r in records(guard.get("bench_df")) if r.get("지역") == ("KR" if region == "kr_stats" else "US")]
        if bench:
            add(label + " 계산 기준", " / ".join(sorted({str(r.get("기준일") or "미확인") for r in bench})),
                "시장별 일봉 정렬 · 장중 지수판과 수신 시점이 다를 수 있음",
                ", ".join(str(r.get("티커", "")) for r in bench))
        if not stats or stats.get("mode") == "데이터부족":
            add(label + " 지수", "데이터부족", "숫자 0을 정상으로 해석하지 않음", "유효 기준 지수 조회")
            continue
        local = number(stats.get("score"))
        add(label + " 지수 점수", local, "8 이상 위험; -8% 지수 1개 또는 -5% 지수 2개 이상은 비상",
            _score_release(local) + " + 비상 조건 별도 확인")
        for key, name, limit, rule in (
            ("circuit_day", "하루 -8% 이하", 1, "1개 이상 비상·5점 (실제 서킷 발동과 별개)"),
            ("panic_day", "하루 -5% 이하", 2, "2개 이상 비상 / -8% 조건 없고 1개 이상이면 3점"),
            ("below20", "MA20 하회", 2, "2개 1점 / 3개 이상 2점"),
            ("below50", "MA50 하회", 2, "2개 이상 2점"),
            ("down3", "3일 연속하락", 2, "2개 이상 2점"),
            ("weak5", "5일 -3% 이하", 2, "2개 이상 2점"),
            ("sharp_day", "하루 -1.5% 이하", 2, "2개 이상 1점"),
        ):
            value = number(stats.get(key))
            if key == "below20" and value is not None and value >= 3:
                limit = 3
            if key == "panic_day" and value == 1:
                limit = 1
            add(label + " " + name, f"{value:g}개" if value is not None else "미연결", rule,
                (f"다음 완화: {limit}개 미만까지 {max(0, int(value)-limit+1)}개 회복"
                 if value is not None and value >= limit else "현재 가점/비상 경계 미만" if value is not None else "입력 확인"))
    for key, name, rule in (("flow_breadth", "돈흐름 3M 상승 비율", "35% 미만 +2 / 50% 미만 +1"),
                            ("flow_accel", "가속 ETF 비율", "35% 미만 +1")):
        val = number(guard.get(key))
        target = .5 if key == "flow_breadth" else .35
        add(name, f"{val*100:.1f}%" if val is not None else "미연결", rule,
            (_flow_release(val, breadth=key == "flow_breadth") + "; "
             f"가점 0까지 {max(0, (target-val)*100):.1f}%p 회복" if val is not None else "입력 확인"))
    parts = guard.get("mode_score_parts") or {}
    counts = guard.get("flow_input_counts") or {}
    if counts.get("rows"):
        add("돈흐름 유효 표본", f"3M {counts['breadth_valid']}/{counts['rows']}개 / 가속도 {counts['accel_valid']}/{counts['rows']}개",
            "각 지표의 유효 숫자만 분모에 포함(실제 0은 포함)",
            f"3M 결측 {counts['breadth_missing']}개 / 가속도 결측 {counts['accel_missing']}개 · 결측을 약세로 간주하지 않음")
    add("점수 구성", " / ".join(f"{k} {number(v):+g}" if number(v) is not None else f"{k} 미연결"
                               for k, v in parts.items()) or "구성 미연결",
        "지역 최대 + 흐름 + 조건부 매크로·이벤트 + 복합 가점", "각 입력 갱신 후 같은 함수로 재계산")
    add("매크로 가점", f"{guard.get('macro_score', '미연결')}점 · 부담 {guard.get('macro_pressure', '미연결')} / 리스크 {guard.get('macro_risk', '미연결')}",
        "부담 2/4 이상 +1/+2, 리스크 3.5/4.5 이상 +1/+2, 합계 최대 3",
        "다음 경계: " + _macro_release(guard) + "; 부담 <2 및 리스크 <3.5 시 매크로 가점 0")
    add("이벤트 가점", f"{guard.get('event_score', '미연결')}점 · 위험값 {guard.get('event_risk', '미연결')}",
        "위험값 >0이면 +1 / 2 이상 +2", "위험값 0 시 이벤트 가점 0")
    tactical = _tactical_rebound_lines(guard)
    add("전술 반등 예외", tactical[0], "기존 판정 유지·누락값은 미충족/충족으로 대체하지 않음", tactical[1])
    lines += ["", "일반 종목 신규매수 중단 해소는 통합·해당 지역의 위험/비상 조건이 모두 해소되어야 합니다. 레버리지는 방어(5점 이상)도 별도 제한합니다. 위 수치 회복만으로 매수 허용은 아니며 종목별 비중·추세·손익비 체크는 유지합니다."]
    return lines
