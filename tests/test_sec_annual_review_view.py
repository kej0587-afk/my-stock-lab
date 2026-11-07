"""Streamlit lifecycle for official annual evidence, with no scoring/DB dependencies."""

import ast
import json
from pathlib import Path
import socket
import subprocess

import pytest
from streamlit.testing.v1 import AppTest

SCRIPT = '''
import streamlit as st
from datetime import datetime, timezone
from stock_lab_core.sec_annual_review_view import render_sec_annual_evidence
def resolve(symbol):
    st.session_state.calls.append('identity')
    return '0001513845', {'ticker': st.session_state.identity_ticker, 'cik_str': 1513845}
def fetch(cik):
    st.session_state.calls.append('facts')
    if st.session_state.fault:
        raise RuntimeError(st.session_state.fault)
    return st.session_state.fixture['company_facts']
render_sec_annual_evidence(st, ticker=st.session_state.ticker, owner=st.session_state.owner,
    configured=st.session_state.configured, resolve_cik=resolve, fetch_facts=fetch,
    tags=st.session_state.fixture['tags'], flow_fields=st.session_state.fixture['flow_fields'],
    is_demo=st.session_state.demo, now=datetime(2026, 11, 7, 12, tzinfo=timezone.utc))
'''


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('UI test must not contact providers')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def app():
    fixture = json.loads((Path(__file__).parent / 'fixtures/nbis_20f_annual_20261107.json').read_text(encoding='utf-8'))
    result = AppTest.from_string(SCRIPT)
    for k, v in dict(fixture=fixture, calls=[], ticker='NBIS', identity_ticker='NBIS',
                     owner='test@example.invalid', configured=True, fault='', demo=False,
                     saved_score=3, saved_decision='existing').items():
        result.session_state[k] = v
    return result.run()


def test_explicit_button_three_tables_rerun_no_fetch_and_scores_unchanged():
    at = app()
    assert not at.exception and not at.session_state.calls and not at.dataframe
    at.button[0].click().run()
    assert not at.exception and at.session_state.calls == ['identity', 'facts']
    assert len(at.dataframe) == 3 and len(at.get('download_button')) == 1
    table = at.dataframe[0].value
    assert table['매출'].tolist() == [9800000, 91500000, 529800000]
    assert table['영업현금흐름(계속사업)'].tolist() == [-222000000, -269900000, 401900000]
    at.run()
    assert at.session_state.calls == ['identity', 'facts']
    assert at.session_state.saved_score == 3 and at.session_state.saved_decision == 'existing'


def test_failed_refresh_clears_old_display_and_sanitizes_exception():
    at = app()
    at.button[0].click().run()
    at.session_state.fault = 'SEC HTTP 403: secret-contact@example.invalid'
    at.button[0].click().run()
    assert not at.exception and not at.dataframe
    assert any('403' in x.value for x in at.warning)
    assert all('secret-contact' not in x.value for x in at.warning)


@pytest.mark.parametrize('key,value', [('owner','another@example.invalid'), ('ticker','MSFT')])
def test_account_or_symbol_switch_hides_previous_result_without_request(key, value):
    at = app()
    at.button[0].click().run()
    at.session_state[key] = value
    at.run()
    assert not at.dataframe and at.session_state.calls == ['identity', 'facts']


@pytest.mark.parametrize('key,value', [('configured',False), ('demo',True), ('owner','')])
def test_missing_config_demo_or_owner_never_requests(key, value):
    at = app()
    at.session_state[key] = value
    at.run()
    assert not at.button and not at.session_state.calls and not at.exception


def test_wrong_ticker_identity_blocks_fetch():
    at = app()
    at.session_state.identity_ticker = 'MSFT'
    at.button[0].click().run()
    assert at.session_state.calls == ['identity'] and not at.dataframe and at.warning


def test_wrong_response_cik_blocks_display():
    at = app()
    at.session_state.fixture['company_facts']['cik'] = 1
    at.button[0].click().run()
    assert not at.exception and not at.dataframe and at.warning


def test_unsupported_10k_displays_no_20f_evidence():
    at = app()
    at.session_state.fixture['company_facts']['facts'] = {}
    at.button[0].click().run()
    assert not at.exception and not at.dataframe
    assert any('20-F' in x.value and '없습니다' in x.value for x in at.info)


def test_existing_app_functions_are_identical_to_before_ui_wiring():
    source = Path('app.py').read_text(encoding='utf-8-sig')
    old = subprocess.check_output(['git', 'show', '5c83e217:app.py']).decode('utf-8-sig')
    def functions(text):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(text).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert functions(source) == functions(old)
    assert 'SEC 20-F 연간 근거 · 점수 유지' in source
