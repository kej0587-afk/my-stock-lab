"""Isolated five-minute observation and scenario sizing display."""

from stock_lab_core.soxl_five_observation import build_five_observation, budget_weight
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def render_budget_table(st):
    st.markdown("**거래당 손실 예산별 비중 · 가정 비교**")
    rows = []
    for loss in (5, 10, 15, 20):
        row = {"SOXL 손실률 가정": f"-{loss}%"}
        for budget in (.25, .5, 1.):
            row[f"계좌 손실 예산 {budget:g}%"] = f"{budget_weight(budget, loss):.2f}%"
        rows.append(row)
    st.table(rows)
    st.caption("표의 값은 계좌 대비 SOXL 비중입니다. 비중 = 계좌 손실 예산 ÷ SOXL 손실률 가정. "
               "예: 예산 0.25%, 손실률 10% 가정이면 비중 2.50%. 권장 비중·현재 계좌 설정이 아닙니다.")
    st.caption("손실률에는 갭·청산 지연·비용을 포함해 별도로 가정해야 합니다. 실제 손실은 가정을 넘을 수 있으며 "
               "SOXX 손절거리 ×3이나 과거 소수 사례로 손실률을 추정하지 않습니다. 기존 배분·시장방어는 변경하지 않습니다.")


def render_five_result(st, result, format_time):
    st.markdown("**SOXX 5분 이탈 관찰 · 기존 1시간 기준 유지**")
    st.markdown(result["status"])
    st.caption("고정 참고선 기준: " + format_time(result["reference_end"])
               + " · 5분 기대 완료봉: " + format_time(result["expected_end"]))
    if result["issue"]:
        st.info(result["issue"])
    if result["end"] is not None:
        st.table([
            {"확인 항목": "1시간 손절 참고선 (SOXX USD)", "관찰값": f"{result['stop']:,.2f}"},
            {"확인 항목": "최근 5분 종가 (SOXX USD)", "관찰값": f"{result['close']:,.2f} · {format_time(result['end'])}"},
            {"확인 항목": "최초 저가 이탈 봉 종료", "관찰값": format_time(result["first_low_end"]) if result["first_low_end"] is not None else "조회 구간 미관찰"},
            {"확인 항목": "최초 종가 이탈 봉 종료", "관찰값": format_time(result["first_close_end"]) if result["first_close_end"] is not None else "조회 구간 미관찰"},
        ])
    st.caption("정규장 완료 5분봉만 비교하며 시간외·데이마켓은 제외합니다. 최초 이탈 시각은 해당 5분봉의 종료시각으로, "
               "정확한 체결 시각·실제 청산가는 아닙니다. 조회 때 갱신된 1시간 참고선 이후 구간만 관찰합니다. "
               "5분 이탈·복귀는 매매 승인이나 1시간 손절 확정이 아닙니다.")


def render_five_observation(st, payload, hourly, schedule, now, format_time):
    if payload.get("issue"):
        st.warning(payload["issue"])
    if payload.get("captured_at"):
        st.caption("5분 자료 수집: " + format_time(payload["captured_at"]) + " · 조회 캐시 최대 60초")
    result = build_five_observation(payload.get("frame"), hourly, schedule, now)
    render_five_result(st, result, format_time)
