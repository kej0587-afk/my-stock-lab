import ast
from pathlib import Path
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from stock_lab_core.browser_safety import TRANSLATION_GUARD_HTML, install_translation_guard


def test_translation_guard_does_not_modify_react_owned_children():
    assert "root.setAttribute('translate', 'no')" in TRANSLATION_GUARD_HTML
    assert "notranslate" in TRANSLATION_GUARD_HTML
    assert "document.body" in TRANSLATION_GUARD_HTML
    assert "document.getElementById('root')" in TRANSLATION_GUARD_HTML
    for unsafe in ["removeChild", "innerHTML", "outerHTML", "MutationObserver", "Node.prototype"]:
        assert unsafe not in TRANSLATION_GUARD_HTML


def test_translation_guard_is_early_and_not_skipped_on_rerun():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app.py").read_text(encoding="utf-8-sig"))
    guard = [node for node in tree.body if isinstance(node, ast.Expr)
             and isinstance(node.value, ast.Call)
             and isinstance(node.value.func, ast.Name)
             and node.value.func.id == "install_translation_guard"]
    configs = [node for node in tree.body if isinstance(node, ast.Expr)
               and isinstance(node.value, ast.Call)
               and ast.unparse(node.value.func) == "st.set_page_config"]
    assert len(guard) == len(configs) == 1
    assert configs[0].lineno < guard[0].lineno
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == "yfinance" for alias in node.names):
            assert guard[0].lineno < node.lineno
        if isinstance(node, ast.ImportFrom) and node.module == "stock_lab_core.result_cache":
            assert guard[0].lineno < node.lineno
    st = Mock()
    install_translation_guard(st)
    install_translation_guard(st)
    assert st.html.call_count == 2
    st.html.assert_called_with(TRANSLATION_GUARD_HTML, unsafe_allow_javascript=True)


def test_panel_empty_loaded_failure_and_changed_selection():
    app = AppTest.from_file(str(Path(__file__).with_name("ui_market_evidence_app.py"))).run()
    assert not app.exception
    assert len(app.dataframe) == 0
    app.button(key="test_refresh").click().run()
    assert not app.exception
    assert len(app.dataframe) == 2
    app.button(key="test_members").click().run()
    assert not app.exception and len(app.dataframe) == 3
    app.selectbox(key="test_theme").select("200").run()
    assert len(app.dataframe) == 2  # no stale constituents for the new theme
    app.button(key="test_flow").click().run()
    assert not app.exception and len(app.dataframe) == 3
    app.radio(key="test_market").set_value("KOSDAQ").run()
    assert len(app.dataframe) == 2  # no stale KOSPI result
    app.button(key="test_news").click().run()
    assert not app.exception
    assert any("등락 원인을 확정하지" in item.value for item in app.caption)
    app.checkbox[0].check().run()
    assert not app.exception
    assert any("응답 시간이 초과" in item.value for item in app.info)
    assert len(app.dataframe) == 1  # themes still available after turnover failure


def test_us_panel_is_demand_loaded_and_does_not_reuse_other_symbol():
    app = AppTest.from_file(str(Path(__file__).with_name("ui_market_evidence_app.py"))).run()
    app.radio(key="test_region").set_value("미국").run()
    assert not app.exception and len(app.dataframe) == 0
    assert "us_requests" not in app.session_state
    app.button(key="test_us_quote").click().run()
    assert not app.exception and len(app.dataframe) == 1
    assert app.dataframe[0].value.iloc[0]["코드"] == "NVDA"
    assert app.dataframe[0].value.iloc[0]["거래소"] == "NASDAQ"
    assert app.dataframe[0].value.iloc[0]["현재가(USD)"] == 123.45
    app.text_input(key="test_us_ticker").set_value("DELL").run()
    assert len(app.dataframe) == 0
    app.selectbox(key="test_us_exchange").select("NY").run()
    app.button(key="test_us_quote").click().run()
    assert app.dataframe[0].value.iloc[0]["코드"] == "DELL"
    assert app.dataframe[0].value.iloc[0]["거래소"] == "NYSE"
    app.button(key="test_us_refresh").click().run()
    assert not app.exception and len(app.dataframe) == 3


def test_news_failure_is_visible_and_button_actually_retries():
    app = AppTest.from_file(str(Path(__file__).with_name("ui_market_evidence_app.py"))).run()
    app.button(key="test_refresh").click().run()
    app.button(key="test_news").click().run()
    assert not app.exception
    assert any("뉴스 수집 중 연결 실패" in item.value for item in app.info)
    assert app.session_state["news_requests"] == 1
    assert app.session_state["news_clear_args"] == ("005930", "삼성전자", False)
    app.checkbox[1].check().run()
    assert app.session_state["news_requests"] == 1  # reruns don't re-fetch
    app.button(key="test_news").click().run()
    assert not app.exception and app.session_state["news_requests"] == 2
    assert any("관련 뉴스 1건" in item.value for item in app.caption)
    assert any("테스트 종목 실적 발표" in item.value for item in app.markdown)


def test_partial_deployment_shows_reboot_notice_not_traceback():
    app = AppTest.from_string('''
import streamlit as st
from stock_lab_core.market_evidence_panel import render_market_evidence_panel
def fetch(*args):
    return {"ok": False, "status": "client_version_mismatch", "rows": []}
fetch.clear = lambda *args: None
render_market_evidence_panel(st, status="ready", fetch_snapshot=fetch, fetch_us=fetch,
    get_news=lambda *args: ([], []), render_news=lambda items: None, key_prefix="upgrade")
''').run()
    app.radio(key="upgrade_region").set_value("미국").run()
    app.button(key="upgrade_us_refresh").click().run()
    assert not app.exception and len(app.dataframe) == 0
    assert any("Reboot app" in item.value for item in app.info)
