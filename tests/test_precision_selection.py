import ast
from copy import deepcopy
import io
import json
from pathlib import Path
import zipfile

import pytest

from stock_lab_core.precision_selection import resolve_precision_selection, remember_precision_selection


def test_preserve_precision_target_keeps_free_ticker_for_next_rerun(app_module):
    option_map = {
        app_module.FREE_SEARCH_OPTION: {"type": "free"},
        "MSFT": {"type": "preset"},
    }
    for key in [
        app_module.PRECISION_SELECTED_OPTION_KEY,
        app_module.PRECISION_PENDING_SELECTED_OPTION_KEY,
        app_module.PRECISION_PENDING_FREE_TICKER_KEY,
        app_module.PRECISION_PENDING_FREE_MARKET_KEY,
    ]:
        app_module.st.session_state.pop(key, None)

    label = app_module.preserve_precision_target_for_next_rerun("AEHR", option_map)

    assert label == app_module.FREE_SEARCH_OPTION
    assert app_module.st.session_state[app_module.PRECISION_SELECTED_OPTION_KEY] == app_module.FREE_SEARCH_OPTION
    assert app_module.st.session_state[app_module.PRECISION_PENDING_SELECTED_OPTION_KEY] == app_module.FREE_SEARCH_OPTION
    assert app_module.st.session_state[app_module.PRECISION_PENDING_FREE_TICKER_KEY] == "AEHR"
    assert app_module.st.session_state[app_module.PRECISION_PENDING_FREE_MARKET_KEY] == app_module.PRECISION_US_MARKET_OPTION


def test_preserve_precision_target_uses_existing_watchlist_label(app_module):
    option_map = {
        app_module.FREE_SEARCH_OPTION: {"type": "free"},
        "⭐ Microsoft (MSFT)": {
            "type": "watchlist",
            "item": {"ticker": "MSFT", "name": "Microsoft", "is_etf": False, "asset_class": "us_stock"},
        },
    }
    app_module.st.session_state.pop(app_module.PRECISION_SELECTED_OPTION_KEY, None)
    app_module.st.session_state.pop(app_module.PRECISION_PENDING_SELECTED_OPTION_KEY, None)

    label = app_module.preserve_precision_target_for_next_rerun("MSFT", option_map)

    assert label == "⭐ Microsoft (MSFT)"
    assert app_module.st.session_state[app_module.PRECISION_SELECTED_OPTION_KEY] == "⭐ Microsoft (MSFT)"
    assert app_module.st.session_state[app_module.PRECISION_PENDING_SELECTED_OPTION_KEY] == "⭐ Microsoft (MSFT)"


FREE = "free"
OLD_MAGS = "📦 MAGS (MAGS)"
MAGS = "⭐ MAGS (MAGS)"
BITX = "📦 BITX (BITX)"


@pytest.mark.parametrize("state,expected", [
    ({"current_option": OLD_MAGS, "widget_option": BITX}, (BITX, False)),
    ({"current_option": MAGS, "widget_option": BITX}, (BITX, False)),
    ({"current_option": OLD_MAGS, "widget_option": FREE}, (FREE, False)),
    ({"current_option": OLD_MAGS, "widget_option": OLD_MAGS}, (FREE, True)),
    ({"current_option": OLD_MAGS}, (FREE, True)),
    ({"current_option": MAGS, "widget_option": "removed"}, (MAGS, True)),
    ({"current_option": MAGS}, (MAGS, False)),
    ({"current_option": FREE, "widget_option": "removed"}, (FREE, True)),
    ({"widget_option": BITX, "pending_option": MAGS, "force_free": True}, (MAGS, True)),
    ({"widget_option": BITX, "pending_option": "removed", "force_free": True}, (FREE, True)),
    ({"widget_option": BITX, "pending_option": "removed"}, (BITX, False)),
    ({"widget_option": BITX, "pending_option": FREE}, (FREE, True)),
])
def test_selection_precedence_keeps_widget_before_stale_current(state, expected):
    options = [FREE, MAGS, BITX]
    before = deepcopy((options, state))
    assert resolve_precision_selection(options, free_option=FREE, **state) == expected
    assert (options, state) == before


def test_missing_identity_falls_back_to_free_without_guessing_a_label():
    assert resolve_precision_selection([FREE, BITX], free_option=FREE,
                                       current_option=OLD_MAGS, widget_option=OLD_MAGS) == (FREE, True)
    assert resolve_precision_selection([], free_option="") == ("", True)


def _selection_screen_source():
    """Exercise the actual app selection block without price/account services."""
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    constants = [node for node in tree.body if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and (target.id.startswith("PRECISION_") or target.id == "FREE_SEARCH_OPTION")
        for target in node.targets
    )]
    branch = next(node for node in tree.body if isinstance(node, ast.If)
                  and ast.unparse(node.test) == "main_page == 'precision'")
    end = next(index for index, node in enumerate(branch.body) if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "is_free" for target in node.targets))
    prefix = '''
import streamlit as st
from stock_lab_core.precision_selection import resolve_precision_selection, remember_precision_selection
from stock_lab_core.precision_review_export import build_precision_review_export_zip
render_app_notice = lambda *args: None
TICKER_MAP = {}
def _queue_precision_selected_option(label):
    st.session_state[PRECISION_PENDING_SELECTED_OPTION_KEY] = label
def set_precision_target_ticker(ticker, option_map):
    label = next(key for key, value in option_map.items() if (value.get("item") or {}).get("ticker") == ticker)
    _queue_precision_selected_option(label)
'''
    options_source = f'''
def build_precision_select_options():
    mags = {MAGS!r} if st.session_state.get("synced") else {OLD_MAGS!r}
    return [FREE_SEARCH_OPTION, mags, {BITX!r}], {{
        FREE_SEARCH_OPTION: {{"type": "free"}},
        mags: {{"type": "watchlist", "item": {{"ticker": "MAGS"}}}},
        {BITX!r}: {{"type": "watchlist", "item": {{"ticker": "BITX"}}}},
    }}
'''
    return (prefix + ast.unparse(ast.Module(body=constants, type_ignores=[]))
            + options_source + ast.unparse(ast.Module(body=branch.body[:end + 1], type_ignores=[])) + '''
tkr = selected_option.get("item", {}).get("ticker", "GOOGL")
st.text(tkr)
st.session_state["review_zip"] = build_precision_review_export_zip(
    selected_ticker=tkr, result_ticker=tkr, decision={"ticker": tkr}, completion="complete",
)
if tkr == "MAGS":
    st.session_state["synced"] = True
''')


def _assert_selected_body_and_zip(app, label, ticker):
    assert not app.exception
    assert app.selectbox[0].value == label
    assert app.text[0].value == ticker
    with zipfile.ZipFile(io.BytesIO(app.session_state["review_zip"])) as archive:
        snapshot = json.loads(archive.read("snapshot.json"))
    assert snapshot["manifest"]["selected_ticker"] == ticker
    assert snapshot["manifest"]["result_ticker"] == ticker


def test_holding_watchlist_relabel_then_bitx_keeps_widget_body_and_zip_together():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(_selection_screen_source()).run()
    app.selectbox[0].select(OLD_MAGS).run()
    _assert_selected_body_and_zip(app, OLD_MAGS, "MAGS")
    app.selectbox[0].select(BITX).run()
    _assert_selected_body_and_zip(app, BITX, "BITX")


@pytest.mark.parametrize("label,expected", [
    (BITX, {"ticker": "BITX"}),
    (FREE, {"free": True}),
    ("KR", {"ticker": "000660.KQ"}),
])
def test_callback_captures_identity_not_label_or_position(label, expected):
    state = {"widget": label}
    remember_precision_selection(state, "widget", "pending", {
        BITX: {"type": "watchlist", "item": {"ticker": "BITX"}}, FREE: {"type": "free"},
    }, {"KR": ("000660.KQ", False, "kr_stock")})
    assert state["pending"] == expected


def test_callback_survives_widget_state_lost_during_option_rebuild():
    from streamlit.testing.v1 import AppTest

    source = _selection_screen_source().replace(
        "def build_precision_select_options():",
        "def build_precision_select_options():\n    if st.session_state.get(PRECISION_PENDING_IDENTITY_KEY):\n        st.session_state.pop(PRECISION_SELECTED_WIDGET_KEY, None)",
    )
    app = AppTest.from_string(source).run()
    app.selectbox[0].select(OLD_MAGS).run()
    _assert_selected_body_and_zip(app, OLD_MAGS, "MAGS")
    app.selectbox[0].select(BITX).run()
    _assert_selected_body_and_zip(app, BITX, "BITX")
    app.selectbox[0].select(app.selectbox[0].options[0]).run()
    _assert_selected_body_and_zip(app, app.selectbox[0].options[0], "GOOGL")


def test_app_import_refreshes_old_selection_module_after_cloud_deploy(monkeypatch):
    import stock_lab_core.precision_selection as selection

    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    start = next(index for index, node in enumerate(tree.body) if isinstance(node, ast.Import)
                 and any(alias.asname == "_precision_selection" for alias in node.names))
    import_block = ast.Module(body=tree.body[start:start + 3], type_ignores=[])
    monkeypatch.delattr(selection, "remember_precision_selection")
    namespace = {}
    exec(compile(import_block, "app_selection_import", "exec"), namespace)
    state = {"widget": BITX}
    namespace["remember_precision_selection"](state, "widget", "pending", {
        BITX: {"type": "watchlist", "item": {"ticker": "BITX"}},
    }, {})
    assert state["pending"] == {"ticker": "BITX"}
    assert namespace["resolve_precision_selection"]([FREE, BITX], free_option=FREE,
                                                   widget_option=BITX) == (BITX, False)
