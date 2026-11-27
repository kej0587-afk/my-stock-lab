"""Read-only presentation of existing short-plan outputs; no signal calculation."""

import math


def price(value):
    try:
        number = float(value)
        return f"{number:,.2f} USD" if math.isfinite(number) and number > 0 else "미확인"
    except (ValueError, TypeError):
        return "미확인"


def observation_rows(context, readiness, plan, price_time):
    plan = plan or {}
    hold = []
    if not context.get("session_active"):
        hold.append("정규장 외: 다음 정규장 재확인")
    if not context.get("signal"):
        hold.append(context.get("reason") or "SOXX 확인 조건 미충족")
    hold.append(str(readiness.get("reason") or "기존 시장방어·실행 조건 재확인"))
    if not plan:
        hold.append("유효한 SOXL 진입·손절 가격 쌍 없음")
    return [
        {"항목": "현재 관찰 상태", "내용": ("지지 반응 관찰" if context.get("signal") else "조건 대기")
         + " · 기존 판정: " + str(readiness.get("label") or "미확인")},
        {"항목": "진입 기준가와 근거", "내용": price(plan.get("entry")) + " · " + price_time
         + " · 가정 가격, 실제 주문가 아님"},
        {"항목": "진입 확인 조건", "내용": "SOXX 동일 1시간 완료봉 지지 반응 + 기존 실행 제한 별도 확인; 5분은 조기 경고"},
        {"항목": "손절·무효화", "내용": price(plan.get("stop"))
         + " SOXL 가격 참고선 / SOXX 1시간 지지 실패는 별도 무효 조건; 갭 시 초과손실 가능"},
        {"항목": "익절 후보", "내용": price(plan.get("target"))
         + " · 기존 SOXL 1R 시나리오; -20%/+10·20% 연구 목표와 다른 규칙"},
        {"항목": "최대 보유기간", "내용": "운영값 미설정 · 기존 비교연구는 당일 청산 vs 최대 18개 1시간봉; 새 -20% 연구는 최대 10거래일"},
        {"항목": "오늘 보류 사유", "내용": " / ".join(dict.fromkeys(hold))},
    ]


def render_brief(st, context, readiness, plan, price_time):
    st.markdown("**SOXL 관찰 요약 · 읽기 전용 시안**")
    st.table(observation_rows(context, readiness, plan, price_time))
    with st.expander("세 가지 관찰 유형과 검증 범위", expanded=False):
        st.table([
            {"유형": "급락 후 반등", "기준": "직전 20일 최고 종가 -20%; +10/+20 비교",
             "검증 상태": "일봉 후보 연구만 있음. 2차 5분 대조 16건 모두 미확인; 현재 가격 승률 없음"},
            {"유형": "상승 추세 눌림", "기준": "기존 SOXX 1시간 지지 반응 + SOXL 자체 손절/1R",
             "검증 상태": "위 표는 이 관찰안. 실제 상승 추세 성립은 별도 확인; 과거 빈도를 현재 확률로 사용 안 함"},
            {"유형": "거래량 돌파", "기준": "기존 거래량·패턴·매물대 관찰을 재사용할 후보",
             "검증 상태": "진입/청산 규칙 미고정·미검증. 매수 신호 없음"},
        ])
        st.caption("이 요약은 저장 판정·시장방어·비중·월적립·L3를 바꾸지 않습니다. "
                   "시장방어 해제나 단타 매수 승인으로 해석하지 않습니다.")
