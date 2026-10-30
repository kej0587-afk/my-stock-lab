"""Explain the existing guard inputs without granting or changing execution."""

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def compose_market_guard_score(regional, flow, macro, event):
    """Extracted unchanged from build_today_market_guard; return actual additions."""
    parts = {"regional": int(regional), "flow": int(flow) if flow > 0 else 0,
             "macro": int(macro) if macro >= 2 or (macro == 1 and regional < 5) else 0,
             "event": int(event) if event >= 2 or (event == 1 and regional < 5) else 0,
             "combined": 1 if regional >= 5 and macro + event >= 3 else 0}
    return sum(parts.values()), parts


def guard_explanation_lines(guard):
    from stock_lab_core.report_evidence import _cell, number, records
    guard = guard or {}
    lines = ["", "## 시장방어 게이트 근거"]
    if not guard:
        return lines + ["오늘점검 시장 게이트 입력 미연결. 스트레스 점수로 대체 계산하지 않습니다."]
    lines += [f"현재 {guard.get('scope_text', '')} · 통합 {guard.get('mode', '미확인')}",
              "리포트 스트레스(0~100)는 설명용이며 아래 시장방어 점수와 다른 산식입니다. 값은 오늘점검 게이트 입력 스냅샷 기준이며 아래 표에서 판정을 바꾸지 않습니다.",
              "구성 요소 | 현재값 | 기존 기준 | 기준까지 남은 조건", "--- | --- | --- | ---"]

    def add(name, value, rule, remaining):
        lines.append(" | ".join(_cell(x) for x in (name, value, rule, remaining)))

    score = number(guard.get("score"))
    add("통합 시장 점수", score if score is not None else "미연결", "8 이상 위험 / 5 이상 방어 / 2 이상 주의",
        f"위험 구간 이탈: 8 미만, 최소 {max(0, int(score)-7)}점 감소" if score is not None else "입력 확인")
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
            f"8 미만까지 {max(0, int(local)-7)}점 감소 + 비상 조건 해소" if local is not None else "입력 확인")
        for key, name, limit, rule in (
            ("circuit_day", "하루 -8% 이하", 1, "1개 이상 비상·5점 (실제 서킷 발동과 별개)"),
            ("panic_day", "하루 -5% 이하", 2, "2개 이상 비상 / -8% 조건 없고 1개 이상이면 3점"),
            ("below20", "MA20 하회", 2, "2개 1점 / 3개 이상 2점"),
            ("below50", "MA50 하회", 2, "2개 이상 2점"),
            ("down3", "3일 연속하락", 2, "2개 이상 2점"),
            ("weak5", "5일 -3% 이하", 2, "2개 이상 2점"),
            ("sharp_day", "하루 -1.5% 이하", 2, "2개 이상 1점"),
        ):
            value = int(stats.get(key, 0))
            add(label + " " + name, f"{value}개", rule,
                f"{limit}개 미만까지 {max(0, value-limit+1)}개 회복")
    for key, name, rule in (("flow_breadth", "돈흐름 3M 상승 비율", "35% 미만 +2 / 50% 미만 +1"),
                            ("flow_accel", "가속 ETF 비율", "35% 미만 +1")):
        val = number(guard.get(key))
        target = .5 if key == "flow_breadth" else .35
        add(name, f"{val*100:.1f}%" if val is not None else "미연결", rule,
            f"가점 0까지 {max(0, (target-val)*100):.1f}%p 회복" if val is not None else "입력 확인")
    parts = guard.get("mode_score_parts") or {}
    add("점수 구성", " / ".join(f"{k} {v:+d}" for k, v in parts.items()) or "구성 미연결",
        "지역 최대 + 흐름 + 조건부 매크로·이벤트 + 복합 가점", "각 입력 갱신 후 같은 함수로 재계산")
    add("매크로 가점", f"{guard.get('macro_score', '미연결')}점 · 부담 {guard.get('macro_pressure', '미연결')} / 리스크 {guard.get('macro_risk', '미연결')}",
        "부담 2/4 이상 +1/+2, 리스크 3.5/4.5 이상 +1/+2, 합계 최대 3", "부담 <2 및 리스크 <3.5 시 매크로 가점 0")
    add("이벤트 가점", f"{guard.get('event_score', '미연결')}점 · 위험값 {guard.get('event_risk', '미연결')}",
        "위험값 >0이면 +1 / 2 이상 +2", "위험값 0 시 이벤트 가점 0")
    lines += ["", "일반 종목 신규매수 중단 해소는 통합·해당 지역의 위험/비상 조건이 모두 해소되어야 합니다. 레버리지는 방어(5점 이상)도 별도 제한합니다. 위 수치 회복만으로 매수 허용은 아니며 종목별 비중·추세·손익비 체크는 유지합니다.",
              f"전술 반등 예외 현재: {'충족' if guard.get('tactical_rebound') else '미충족'} · 기존 조건: 통합 8 이상, -8%/-5% 급락 지수 0개, 확산 ≥55% 또는 가속 ≥50%, +3% 반등 지수 ≥2개 또는 최대 상승 ≥5%."]
    return lines
