"""Real Streamlit render/submit/scope tests without an app import or network."""

from hashlib import sha256

import pandas as pd
from streamlit.testing.v1 import AppTest

from tests.test_account_performance_io import ledger


SCRIPT = '''
import streamlit as st
from stock_lab_core.account_performance_view import render_account_performance
owner = st.radio("test owner", ["A", "B"], key="test_owner")
show = st.checkbox("test panel", value=True, key="test_show")
if show:
    render_account_performance(st, owner_scope=owner)
'''


def prefix(owner="A"):
    return "account_performance_v1_" + sha256(owner.lower().encode()).hexdigest()[:20]


def app_with_ledger():
    app = AppTest.from_string(SCRIPT)
    app.session_state[prefix() + "_draft"] = ledger()
    app.session_state[prefix() + "_revision"] = 0
    return app.run()


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


def complete_box(app):
    return next(widget for widget in app.checkbox if widget.label.startswith("이 계좌의 평가기간"))


def test_empty_panel_no_error_and_no_speculative_performance():
    app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    assert not app.metric
    assert len(app.dataframe) == 2
    assert any("미산출" in message.value for message in app.info)


def test_confirmation_required_and_calculated_profit_excludes_deposit():
    app = app_with_ledger()
    assert not app.exception
    button(app, "계좌 성과 계산").click().run()
    assert not app.metric
    assert any("완전성" in widget.value for widget in app.warning)
    complete_box(app).check().run()
    button(app, "계좌 성과 계산").click().run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["+10.00%", "+10,000원", "+50,000원"]
    table = app.dataframe[-1].value
    assert table.iloc[0]["수익률(%)"] == "+10.00"
    assert table.iloc[0]["투자손익(원)"] == "10,000"
    assert table.iloc[0]["상태"] == "계산됨"


def test_account_switch_does_not_reuse_result_or_completeness():
    app = app_with_ledger()
    draft = app.session_state[prefix() + "_draft"]
    extra = draft["valuations"].copy().assign(account="Other", value_krw=100.)
    draft["valuations"] = pd.concat([draft["valuations"], extra], ignore_index=True)
    app.run()
    complete_box(app).check().run()
    button(app, "계좌 성과 계산").click().run()
    assert app.metric
    app.selectbox[0].select("Other").run()
    assert not app.exception
    assert not complete_box(app).value
    assert not app.metric


def test_owner_switch_isolated_and_navigation_keeps_applied_draft():
    app = app_with_ledger()
    button(app, "원장 초안 적용").click().run()
    assert not app.exception
    assert app.session_state[prefix() + "_revision"] == 1
    expected = app.session_state[prefix() + "_draft"]["valuations"].copy()
    app.checkbox(key="test_show").uncheck().run()
    app.checkbox(key="test_show").check().run()
    pd.testing.assert_frame_equal(app.session_state[prefix() + "_draft"]["valuations"], expected)
    app.radio(key="test_owner").set_value("B").run()
    assert not app.exception
    assert not app.metric
    assert app.session_state[prefix("B") + "_draft"]["valuations"].empty
    assert len(app.session_state[prefix("A") + "_draft"]["valuations"]) == 2


def test_invalid_source_never_publishes_success_metrics():
    app = app_with_ledger()
    app.session_state[prefix() + "_draft"]["flows"].loc[0, "currency"] = "USD"
    app.run()
    complete_box(app).check().run()
    button(app, "계좌 성과 계산").click().run()
    assert not app.exception
    assert not app.metric
    assert any("환율" in warning.value for warning in app.warning)
