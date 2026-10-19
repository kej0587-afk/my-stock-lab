"""Display-only report checks; no score, threshold or execution overrides."""

import re

from stock_lab_core.report_evidence import KST, first, macro_stress, number, stamp, text


def kst_time(value):
    dt = stamp(value)
    return dt.strftime("%Y-%m-%d %H:%M KST") if dt else "시각 미제공"


def oil_explanation(macro_data):
    oil = next((row for row in macro_stress(macro_data)["rows"] if row["name"] == "유가"), None)
    if not oil:
        return "유가 자료 미수집: 스트레스 기여도 확인 보류."
    value, points = oil["value"], oil["contribution"]
    if value >= 100:
        reason = "100달러 이상 수준 경고"
    elif value >= 90 and oil["direction"] == "하락" and points == 0:
        reason = "90~100달러 고수준 부담 유지, 하락 완화점수 미적용"
    else:
        reason = oil["state"] + " · " + oil["direction"]
    return f"현재 WTI {value:.2f}달러: {reason} → 유가 기여 {points:+d}점. 기존 산식·매매 임계값 유지."


def macro_change(previous, current):
    if not previous:
        return "스트레스 변화: 이전 매크로 스냅샷 없음(변화 원인 추정 안 함)."
    before, after = macro_stress(previous), macro_stress(current)
    old = {row["name"]: row for row in before["rows"]}
    if set(old) != {row["name"] for row in after["rows"]}:
        return "스트레스 변화: 수집 지표 구성이 달라 동일 기준 비교 보류."
    parts = []
    for row in after["rows"]:
        prev = old[row["name"]]
        delta = row["contribution"] - prev["contribution"]
        if delta:
            detail = f"{row['name']} {prev['value']:.2f}→{row['value']:.2f}, 기여 {delta:+d}점"
            if prev["as_of"] == row["as_of"]:
                detail += " (동일 기준일 자료 변경, 시장의 하루 변화로 해석 금지)"
            parts.append(detail)
    return f"스트레스 {before['score']}→{after['score']}: " + (" / ".join(parts) or "구성요소 기여 변화 없음")


def candidate_line(row):
    ticker = text(first(row, "티커", "ticker"))
    name = text(first(row, "종목명", "name", "자산명")) or "종목명 미연결"
    raw_grade = text(first(row, "📌후보등급", "후보등급"))
    grade = re.search(r"[SABCF]급", raw_grade)
    quality = grade.group() if grade else "등급 미제공"
    gate = text(first(row, "게이트상태", "gate_state")) or "판단자료 미제공"
    reason = text(first(row, "게이트근거", "시장실행근거", "최종읽기"))
    code = " ".join(text(row.get(key)) for key in ("판정코드", "최종읽기", "게이트근거", "시장실행상태", "상위시간대상태"))
    checks = []
    if any(word in code for word in ("시장", "MARKET", "MACRO")):
        checks.append("해당 시장 신규매수 중단 해제 후 종목 게이트 재통과")
    if any(word in code for word in ("추세", "MTF", "STRUCTURE", "TREND", "상위 시간대 경고")):
        checks.append("일봉·주봉 추세훼손 해제 및 상위 시간대 경고 해소")
    if any(word in code for word in ("가격방어", "DRAWDOWN", "BREAKDOWN")):
        checks.append("가격 급락·지지 이탈 조건 해소 후 가격방어 게이트 재계산")
    if any(word in code for word in ("R/R", "손익비", "RR_")):
        checks.append("실제 목표·손절 재확인 후 손익비 게이트 통과")
    if any(word in code for word in ("비중", "OVERWEIGHT", "TARGET_FILLED")):
        checks.append("현재비중을 목표 범위 이내로 확인")
    if any(word in code for word in ("과열", "OVERHEAT")):
        checks.append("과열 조건 해소 및 종가 지지 확인")
    explicit = text(first(row, "해제조건", "다음확인"))
    condition = explicit or " / ".join(checks) or "구체 해제 조건 미제공: 상세 게이트 근거 재확인"
    action = "실행가능" if gate in {"실행가능", "EXECUTABLE"} else "게이트로 보류"
    return f"- {name}({ticker}) · 개별 신호 {quality}, {action}({gate}) · 근거: {reason or '미제공'} · 해제 조건: {condition}"


def account_estimate(held, observations, sessions):
    """Weight times actual asset return, never leverage an ETF's return twice."""
    from stock_lab_core.report_holdings import UNDERLYINGS
    from stock_lab_core.portfolio import infer_scenario_shock_multiplier

    daily, gap, coverage, gap_coverage = 0.0, 0.0, 0.0, 0.0
    seen = set()
    for row in held:
        ticker = text(first(row, "티커", "ticker")).upper()
        weight = number(first(row, "현재비중", "current_w"))
        if ticker in seen or weight is None or not 0 <= weight <= 100:
            return "계좌 합계(추정) 보류: 중복 종목 또는 비중 결측·범위 오류."
        seen.add(ticker)
        obs = observations.get(ticker, {})
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        move = number(obs.get("return"))
        if move is not None and obs.get("date") == sessions.get(region) and sessions.get(region):
            daily += weight * move
            coverage += weight
        if ticker.split(".")[0] in {"379800", "379810", "418660"}:
            for base in UNDERLYINGS[ticker.split(".")[0]]:
                proxy = observations.get(base, {})
                change = number(proxy.get("return"))
                if change is not None and sessions.get("US") and proxy.get("date") == sessions["US"] and sessions.get("KR", "") <= sessions["US"]:
                    mult = infer_scenario_shock_multiplier({"티커": ticker, "자산명": text(first(row, "종목명", "name"))})
                    gap += weight * change * mult
                    gap_coverage += weight
                    break
    if coverage > 100.01 or sum(number(first(row, "현재비중", "current_w")) or 0 for row in held) > 100.01:
        return "계좌 합계(추정) 보류: 현재비중 합계가 100% 초과."
    if not coverage:
        return "계좌 합계(추정) 보류: 비중과 같은 시장 기준일의 등락 미연결."
    note = f"계좌 일간 기여 합계(추정): {daily:+.2f}%p · 연결 비중 {coverage:.1f}%"
    if gap_coverage:
        note += f" / 한국 상장 미국자산 ETF 개장 전 갭 시나리오 기여(추정): {gap:+.2f}%p · 적용 비중 {gap_coverage:.1f}%"
    return note + " · 현재비중 가중, 현금·미연결분 제외, 환율·거래 미반영. 서로 다른 세션/시나리오이므로 두 값을 합산하지 않음."
