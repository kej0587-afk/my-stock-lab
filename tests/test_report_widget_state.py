from stock_lab_core.report_widget_state import (
    MEMO_KEY, EDITOR_KEY, VIEW_KEY, SAVED_VIEW_KEY, restore_report_editor,
    save_report_editor, clear_report_editor, restore_briefing_view, save_briefing_view, saved_report_label,
)


def test_navigation_cleanup_does_not_erase_generated_report_or_view():
    state = {MEMO_KEY: "# report", VIEW_KEY: "시황"}
    restore_report_editor(state)
    save_briefing_view(state)
    # Streamlit removes only the widgets not rendered on the money-flow tab.
    state.pop(EDITOR_KEY)
    state.pop(VIEW_KEY)
    restore_report_editor(state)
    restore_briefing_view(state)
    assert state[EDITOR_KEY] == "# report"
    assert state[VIEW_KEY] == "시황"


def test_edit_clear_and_new_generation_are_not_resurrected():
    state = {MEMO_KEY: "old", EDITOR_KEY: "manual"}
    save_report_editor(state)
    assert state[MEMO_KEY] == "manual"
    clear_report_editor(state)
    restore_report_editor(state)
    assert not state[EDITOR_KEY]
    state[MEMO_KEY] = "new generation"
    restore_report_editor(state)
    assert state[EDITOR_KEY] == "new generation"


def test_retired_view_cannot_return_and_label_never_renames_report_time():
    state = {SAVED_VIEW_KEY: "이벤트 장부"}
    restore_briefing_view(state)
    assert state[VIEW_KEY] == "보유관리"
    label = saved_report_label("# Stock Lab 자동 뉴스픽 · 2026-10-30 05:00 KST\n\nbody")
    assert "2026-10-30 05:00" in label and "현재 시세와 별도" in label


def test_streamlit_widget_cleanup_roundtrip():
    from streamlit.testing.v1 import AppTest
    code = '''
import streamlit as st
from stock_lab_core.report_widget_state import *
page = st.radio("page", ["report", "flow"], key="page")
if page == "report":
    restore_briefing_view(st.session_state)
    st.segmented_control("view", list(VIEWS), key=VIEW_KEY,
                         on_change=save_briefing_view, args=(st.session_state,))
    restore_report_editor(st.session_state)
    st.text_area("memo", key=EDITOR_KEY, on_change=save_report_editor, args=(st.session_state,))
'''
    app = AppTest.from_string(code).run()
    app.text_area[0].set_value("retained report").run()
    app.radio[0].set_value("flow").run()
    assert app.session_state[MEMO_KEY] == "retained report"
    app.radio[0].set_value("report").run()
    assert app.text_area[0].value == "retained report"
    assert not app.exception
