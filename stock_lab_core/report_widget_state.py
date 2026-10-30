"""Keep report data separate from widgets Streamlit cleans on tab navigation."""

import re

MEMO_KEY = "today_market_memo_text"
EDITOR_KEY = "_today_market_memo_editor"
VIEW_KEY = "today_briefing_workspace_view"
SAVED_VIEW_KEY = "_today_briefing_saved_view"
VIEWS = ("보유관리", "시장", "뉴스", "시황", "키움")


def restore_report_editor(state):
    state[EDITOR_KEY] = str(state.get(MEMO_KEY) or "")


def save_report_editor(state):
    state[MEMO_KEY] = str(state.get(EDITOR_KEY) or "")


def clear_report_editor(state):
    state[MEMO_KEY] = ""
    state[EDITOR_KEY] = ""


def restore_briefing_view(state):
    value = state.get(VIEW_KEY, state.get(SAVED_VIEW_KEY, VIEWS[0]))
    state[VIEW_KEY] = value if value in VIEWS else VIEWS[0]


def save_briefing_view(state):
    value = state.get(VIEW_KEY)
    state[SAVED_VIEW_KEY] = value if value in VIEWS else VIEWS[0]


def saved_report_label(report):
    match = re.search(r"(?m)^# Stock Lab 자동 뉴스픽 · (\d{4}-\d{2}-\d{2} \d{2}:\d{2} KST)", str(report))
    return f"저장된 리포트 · {match[1]} 생성 · 현재 시세와 별도" if match else "저장된 리포트 · 생성시각 미확보"
