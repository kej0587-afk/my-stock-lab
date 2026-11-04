"""Final-check presentation aligned with the existing execution restriction."""

from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.formatters import escape_html_value
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def render_final_check_heading(st, name, summary, workflow):
    """Keep the computed summary intact; show account restrictions before timing."""
    ready = build_execution_readiness(workflow, summary)
    restricted = not ready["execution_allowed"]
    if restricted:
        st.markdown("**현재 실행: " + escape_html_value(ready["label"]) + "** · " + escape_html_value(ready["reason"]))
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("개별 점검 판정" if restricted else "최종 판정", summary["final_label"])
    k2.metric("통과", f"{summary['pass_count']}개")
    k3.metric("주의", f"{summary['caution_count']}개")
    k4.metric("차단", f"{summary['block_count']}개")
    st.caption(f"독립 근거 기준 · 중복 제외 {summary.get('duplicate_count', 0)}건 · 미확인 {summary.get('unknown_count', 0)}건 · 핵심자료 미확인 {len(summary.get('core_missing_ids', []))}종류")

    st.markdown(
        f"<div class='info-panel' style='border-left: 5px solid {summary['final_color']};'>"
        f"<b>{escape_html_value(name)} {'개별 점검 해석 (실행 제한 우선)' if restricted else '최종 액션'}</b><br>"
        f"<span class='highlight' style='font-size:1.08em;'>{summary['final_label']}</span><br>"
        f"{escape_html_value(summary['action'])}<br>"
        f"<span style='color:#cbd5e1;'>투자 권유가 아니라, 현재 앱 지표를 한 번에 묶은 의사결정 보조 체크입니다.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

