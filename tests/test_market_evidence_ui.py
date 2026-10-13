from pathlib import Path

from streamlit.testing.v1 import AppTest

from stock_lab_core.browser_safety import TRANSLATION_GUARD_HTML


def test_translation_guard_does_not_modify_react_owned_children():
    assert "root.setAttribute('translate', 'no')" in TRANSLATION_GUARD_HTML
    assert "notranslate" in TRANSLATION_GUARD_HTML
    for unsafe in ["removeChild", "innerHTML", "outerHTML", "MutationObserver", "Node.prototype"]:
        assert unsafe not in TRANSLATION_GUARD_HTML


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
