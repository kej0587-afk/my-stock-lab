"""Failure-only imported evidence with owner/identity/time and display contracts."""
import ast
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core.company_kr_evidence import load_company_kr_evidence
from tests.test_dart_evidence_store import bundle, NOW, MAP


def setup_review(**overrides):
    payload = bundle()
    calls = []
    def identity(t):
        calls.append(('identity', t))
        return dict(ticker=t, codes=MAP, checked_at=NOW.isoformat(), valid_until=(NOW+timedelta(minutes=10)).isoformat())
    def load(t, **kwargs):
        calls.append(('load', t, kwargs['owner_scope']))
        return {'payload': payload, 'imported_at': NOW.isoformat()}
    args = dict(owner='a', load_live=lambda t: {'ok':False, 'source':'dart', 'reason':'DART corp_code 매핑 실패'},
                identity_loader=identity, store_factory=lambda owner: SimpleNamespace(load_recent=load),
                extract_metrics=lambda df, y, r: {'revenue': 250000, 'ocf': None}, now=NOW)
    args.update(overrides)
    return args, calls, payload


def test_fallback_retains_scope_basis_missing_and_provenance_without_mutation():
    args, calls, payload = setup_review()
    old = deepcopy(payload)
    result = load_company_kr_evidence('005930.KS', **args)
    assert calls == [('identity','005930.KS'), ('load','005930.KS','a')]
    assert payload == old
    assert result['원자료'][0]['매출'] == 250000
    assert result['원자료'][0]['영업현금흐름'] is None
    assert '누적' in result['원자료'][0]['금액 기준']
    assert result['원자료'][0]['공시 원문'].endswith('20260814000001')
    assert '2026년 반기' == result['공급처 조회 기간']
    assert result['저장 근거']['corp_code'] == MAP['005930']
    assert '매핑 실패' in result['실패 사유'] and '원문 서명 미검증' in result['공급처']


def test_live_success_makes_no_identity_or_storage_requests():
    args, calls, _ = setup_review(load_live=lambda t: {'ok':True,'source':'dart','annual':[]})
    result = load_company_kr_evidence('005930.KS', **args)
    assert calls == [] and '저장 근거' not in result and result['실패 사유'] == ''


def test_live_exception_still_tries_fallback_and_never_leaks_exception():
    def broken(t): raise RuntimeError('secret-url-credential')
    args, calls, _ = setup_review(load_live=broken)
    result = load_company_kr_evidence('005930.KS', **args)
    assert '저장 근거' in result and 'secret' not in str(result)


@pytest.mark.parametrize('bad', ['wrong_ticker','wrong_corp','expired','partial','identity','store'])
def test_bad_import_is_not_promoted_to_success(bad):
    args, calls, payload = setup_review()
    if bad == 'wrong_ticker': payload['ticker'] = '000660.KS'
    if bad == 'wrong_corp': payload['corp_code'] = '99999999'
    if bad == 'expired': payload['collected_at'] = (NOW-timedelta(days=8)).isoformat()
    if bad == 'partial': payload['reports'].clear()
    if bad == 'identity': args['identity_loader'] = lambda t: {'ticker':'000660.KS'}
    if bad == 'store':
        def broken(owner): raise RuntimeError('secret-db-credential')
        args['store_factory'] = broken
    result = load_company_kr_evidence('005930.KS', **args)
    assert '저장 근거' not in result and not result['원자료']
    assert '검증되지 않은' in result['저장 근거 상태'] and 'secret' not in str(result)
    if bad == 'identity': assert calls == []


def test_missing_store_and_missing_owner_are_explicit():
    args, calls, _ = setup_review(owner='')
    assert '저장 근거' not in load_company_kr_evidence('005930.KS', **args) and not calls
    args, _, _ = setup_review(store_factory=lambda o:SimpleNamespace(load_recent=lambda *a, **k:None))
    result = load_company_kr_evidence('005930.KS', **args)
    assert '저장 근거 없음' in result['저장 근거 상태']


SCRIPT = '''
import streamlit as st
from datetime import timedelta
from tests.test_company_kr_evidence import setup_review, NOW
from stock_lab_core.company_deep_dive import render_company_deep_dive
args,calls,payload=setup_review()
payload['collected_at']=(NOW-timedelta(days=6,hours=23)).isoformat()
payload['attempts'][0]['retrieved_at']=payload['collected_at']
payload['reports'][0]['retrieved_at']=payload['collected_at']
def identity(t):
 st.session_state['requests']=st.session_state.get('requests',0)+1
 return args['identity_loader'](t)
render_company_deep_dive(st, universe=[dict(ticker=t,name=t,source='관심') for t in ('005930.KS','000660.KS')],
 owner=st.session_state.get('owner','a'), configured=False, resolve_cik=None, fetch_facts=None,
 load_kr=args['load_live'], kr_identity_loader=identity, kr_store_factory=args['store_factory'],
 kr_extract_metrics=args['extract_metrics'],now=st.session_state.get('now',NOW))
'''


def test_real_ui_on_demand_scoping_reuse_and_saved_evidence_expiry():
    app=AppTest.from_string(SCRIPT).run()
    app.selectbox[0].select('005930.KS').run()
    assert not app.dataframe
    app.button[0].click().run()
    assert not app.exception and len(app.dataframe)==2 and app.session_state['requests']==1
    assert any('낡은 자료' in c.value for c in app.caption)
    app.run()
    assert app.session_state['requests']==1
    app.selectbox[0].select('000660.KS').run()
    assert not app.dataframe
    app.selectbox[0].select('005930.KS').run()
    assert app.dataframe and app.session_state['requests']==1
    app.session_state['now']=NOW+timedelta(hours=2); app.run()
    assert not app.dataframe and any('유효기간' in x.value for x in app.info)
    app.session_state['owner']='b';app.run()
    assert app.selectbox[0].value=='' and not app.dataframe


def test_app_wires_existing_identity_store_and_parser_only_inside_company_view():
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='render_company_deep_dive')
    args={k.arg:ast.unparse(k.value) for k in call.keywords}
    assert args['kr_extract_metrics']=='extract_dart_metrics'
    assert 'resolve_dart_evidence_identity' in args['kr_identity_loader']
    assert 'owner_scope=owner' in args['kr_store_factory']
    module=Path('stock_lab_core/company_kr_evidence.py').read_text(encoding='utf-8')
    assert 'insert_bundle' not in module and 'calc_scores' not in module
