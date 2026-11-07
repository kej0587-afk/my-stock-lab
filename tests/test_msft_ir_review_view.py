from hashlib import sha256
import socket

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_msft_ir_review import packet, sec_result

SCRIPT='''
import streamlit as st
from stock_lab_core.msft_ir_review_view import render_msft_business_review
def load():
    st.session_state.calls += 1
    if st.session_state.fault: raise ValueError(st.session_state.fault)
    return st.session_state.fixture
render_msft_business_review(st,ticker=st.session_state.ticker,owner=st.session_state.owner,
    is_demo=st.session_state.demo,loader=load)
'''

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*a,**k): pytest.fail('no implicit request')
    monkeypatch.setattr(socket.socket,'connect',fail)

def app():
    at=AppTest.from_string(SCRIPT)
    for k,v in dict(ticker='MSFT',owner='test@example.invalid',demo=False,fixture=packet(),calls=0,fault='',saved_score=3,saved_decision='existing').items():
        at.session_state[k]=v
    key='sec_quarter_review_'+sha256(b'test@example.invalid|MSFT').hexdigest()[:20]
    at.session_state[key]={'selected':['MSFT'],'results':[sec_result()]}
    return at.run()

def test_explicit_query_same_sec_snapshot_no_repeat_and_scores_unchanged():
    at=app()
    assert not at.exception and at.session_state.calls==0 and not at.dataframe
    at.button[0].click().run()
    assert not at.exception and at.session_state.calls==1 and len(at.dataframe)==4
    assert all('범위 내 일치' in x for x in at.dataframe[2].value['상태'])
    assert len(at.get('download_button'))==1
    at.run()
    assert at.session_state.calls==1 and at.session_state.saved_score==3 and at.session_state.saved_decision=='existing'

def test_failed_refresh_clears_old_evidence_and_sanitizes():
    at=app();at.button[0].click().run()
    at.session_state.fault='private-contact@example.invalid'
    at.button[0].click().run()
    assert not at.dataframe and at.warning
    assert 'private-contact' not in at.warning[0].value

@pytest.mark.parametrize('key,value',[('ticker','NVDA'),('owner',''),('demo',True)])
def test_disabled_paths_never_request(key,value):
    at=app();at.session_state[key]=value;at.run()
    assert not at.button and at.session_state.calls==0

def test_owner_and_selection_change_do_not_borrow_prior_evidence():
    at=app();at.button[0].click().run()
    key='sec_quarter_review_'+sha256(b'test@example.invalid|MSFT').hexdigest()[:20]
    at.session_state[key+'_symbols']=['AMZN'];at.run()
    assert '먼저 조회' in at.dataframe[2].value.iloc[0]['상태']
    at.session_state.owner='other@example.invalid';at.run()
    assert not at.dataframe and at.session_state.calls==1
