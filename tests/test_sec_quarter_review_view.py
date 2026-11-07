from datetime import datetime, timezone
import socket

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_sec_quarter_review import payload


SCRIPT = '''
import streamlit as st
from datetime import datetime, timezone
from stock_lab_core.sec_quarter_review_view import render_sec_quarter_evidence
def resolve(symbol):
    st.session_state.calls.append('identity:' + symbol)
    return '0000000123', {'ticker': symbol, 'cik_str': 123}
def fetch(cik):
    st.session_state.calls.append('facts')
    if st.session_state.fault:
        raise RuntimeError(st.session_state.fault)
    return st.session_state.fixture
render_sec_quarter_evidence(st, ticker=st.session_state.ticker, owner=st.session_state.owner,
    configured=st.session_state.configured, is_demo=st.session_state.demo,
    resolve_cik=resolve, fetch_facts=fetch, now=datetime(2026,11,8,tzinfo=timezone.utc))
'''


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*a, **k):
        pytest.fail("UI test must be offline")
    monkeypatch.setattr(socket.socket, "connect", fail)


def app():
    at = AppTest.from_string(SCRIPT)
    for key, value in dict(ticker="MSFT", owner="test@example.invalid", configured=True, demo=False,
                           calls=[], fault="", fixture=payload(), saved_score=3,
                           saved_decision="existing").items():
        at.session_state[key] = value
    return at.run()


def test_only_explicit_load_requests_rerun_and_selection_isolated_scores_unchanged():
    at = app()
    assert not at.exception and not at.session_state.calls
    at.button[0].click().run()
    assert not at.exception and len(at.dataframe) == 5 and len(at.get("download_button")) == 1
    assert at.session_state.calls == ["identity:MSFT", "facts"]
    at.run()
    assert len(at.session_state.calls) == 2
    at.multiselect[0].set_value(["NVDA"]).run()
    assert not at.dataframe and len(at.session_state.calls) == 2
    at.button[0].click().run()
    assert len(at.session_state.calls) == 4
    assert at.session_state.saved_score == 3 and at.session_state.saved_decision == "existing"


def test_refresh_failure_clears_old_result_and_sanitizes():
    at = app()
    at.button[0].click().run()
    at.session_state.fault = "SEC HTTP 403 secret@example.invalid"
    at.button[0].click().run()
    assert len(at.dataframe) == 1
    assert "403" in at.dataframe[0].value.to_string() and "secret@" not in at.dataframe[0].value.to_string()


@pytest.mark.parametrize("key,value", [("owner", "other@example.invalid"), ("ticker", "NVDA")])
def test_account_and_symbol_isolation(key, value):
    at = app()
    at.button[0].click().run()
    at.session_state[key] = value
    at.run()
    assert not at.dataframe and len(at.session_state.calls) == 2


@pytest.mark.parametrize("key,value", [("owner", ""), ("configured", False), ("demo", True)])
def test_disabled_no_request(key, value):
    at = app()
    at.session_state[key] = value
    at.run()
    assert not at.button and not at.session_state.calls
