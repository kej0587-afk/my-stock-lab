"""Display an already calculated precision plan without changing execution policy."""

import pandas as pd

from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE
from stock_lab_core.formatters import escape_html_value, format_currency
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def entry_plan_display(plan, workflow):
    """One presentation result for both the panel and its review export."""
    gate = (workflow or {}).get("게이트상태")
    return {
        "display_status": plan["status"] if gate == GATE_EXECUTABLE else "실행 보류",
        "display_note": plan["status_note"] if gate == GATE_EXECUTABLE else (
            (workflow or {}).get("게이트근거") or "실행 게이트 재확인 필요"
        ),
        "execution_gate": gate or "미확인",
    }


def _amount_split_html(plan):
    rows = plan.get("amount_split") or []
    if not rows:
        return ""
    return " · ".join(
        f"{escape_html_value(row['구분'])} {escape_html_value(row['값'])}" for row in rows
    ) + "<br>"


def render_entry_plan_panel(st, plan, *, workflow, status_color, target_is_projection, entry_rr):
    """Keep the raw plan intact; the gate owns the prominent execution headline."""
    display = entry_plan_display(plan, workflow)
    gate = display["execution_gate"]
    status, note = display["display_status"], display["display_note"]
    raw_plan_note = ""
    if gate != GATE_EXECUTABLE:
        status_color = "#ef4444" if gate in {GATE_DEFENSE, GATE_DATA_CHECK} else "#d97706"
        raw_plan_note = (
            "<span style='color:#94a3b8;'>조건 해소 후 참고할 원계획 등급: "
            f"{escape_html_value(plan['status'])} (실행 허용 아님)</span><br>"
        )

    ticker = plan["ticker"]
    target_label = "강세 시나리오 상단" if target_is_projection else "목표가"
    rr_label = "투영 상단 기준 R/R" if target_is_projection else "현재가 기준 R/R"
    st.markdown(
        f"<div class='info-panel' style='border-left:5px solid {status_color}; line-height:1.8;'>"
        f"<b>🎯 {escape_html_value(plan['title'])}</b><br>"
        f"<span class='highlight'>{escape_html_value(status)}</span> · {escape_html_value(note)}<br>"
        f"{raw_plan_note}"
        f"{target_label} {format_currency(plan['target'], ticker)} <span style='color:#94a3b8;'>({escape_html_value(plan['target_source'])})</span> / "
        f"손절 {format_currency(plan['stop'], ticker)} <span style='color:#94a3b8;'>({escape_html_value(plan['stop_source'])})</span><br>"
        "신규·추가매수 계획 무효선 · 보유분 매도 판단은 별도<br>"
        f"기준가 {format_currency(plan['current_price'], ticker)} / {rr_label} {plan['rr_now']}<br>"
        f"{_amount_split_html(plan)}"
        "R/R은 목표·손절 고정 시의 가격 비율이며 승률이 아닙니다. 낮은 진입가만으로 비율이 커져도 회복 근거가 늘지는 않습니다.<br>"
        "<details><summary>배분 기준·계획 주의사항</summary>"
        f"{escape_html_value(plan['amount_note'])}<br>"
        "손절 참고선은 신규·추가매수 계획의 무효선입니다. 보유분 전량매도 권고나 실제 체결가가 아니며, 보유 위험관리는 별도로 확인합니다.<br>"
        "비중 항목 통과는 목표비중까지 여유가 있다는 뜻이지 매수 근거가 아닙니다.<br>"
        "투자 권유가 아니라, 현재 앱 지표를 주문 전 체크리스트로 풀어쓴 값입니다.</details>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.dataframe(pd.DataFrame(plan["rows"]), width="stretch", hide_index=True, row_height=64,
                 height=min(900, 50 + len(plan["rows"]) * 64))
    return display
