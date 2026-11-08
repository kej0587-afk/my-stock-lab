from copy import deepcopy
import socket

import pytest

from stock_lab_core.company_cash_reading import prior_year_cash_row
from stock_lab_core.company_cash_comparison import build_cash_comparison
from tests.test_sec_cash_recovery import held_packet,collect,release


def year_pair():
    p=held_packet();current=p['quarter'][-1];prior=deepcopy(current)
    for key in ('start','end','fiscal_year_start'):
        prior[key]=prior[key].replace('2026','2025')
    for key,value in (('ocf',20e6),('cash_capex',8e6)):
        prior[key]=value
        for i,fact in enumerate(prior['provenance'][key]['facts']):
            for date_key in ('start','end'):
                fact[date_key]=fact[date_key].replace('2026','2025')
            fact['value']=value*(2-i)
    p['quarter']=[prior,current]
    return p


def direct_pair():
    p=year_pair()
    for row in p['quarter']:
        for key in ('ocf','cash_capex'):
            fact=row['provenance'][key]['facts'][0]
            fact.update(start=row['start'],end=row['end'],value=row[key])
            row['provenance'][key]=dict(method='reported',facts=[fact])
    return p


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**kw:pytest.fail('offline only'))


def test_prior_uses_same_download_no_extra_calls_and_preserves_raws():
    p=year_pair();original=deepcopy(p);r,calls=collect(p)
    assert len(calls)==3 and r['prior_year']['status']=='verified_release'
    c=build_cash_comparison(p,r)
    assert c['status']=='verified_comparison' and c['eligible_for_scoring'] is False
    assert '40.00% → 40.00%' in c['headline']
    assert any(row['항목'].startswith('회사 공시 FCF') and row['이번 분기']=='16.0' for row in c['table'])
    assert c['periods']['prior']['values']['software']==1e6
    assert p==original


def test_direct_comparison_without_release_or_network():
    c=build_cash_comparison(direct_pair())
    assert c['status']=='verified_comparison' and len(c['table'])==4


def test_prior_conflict_does_not_disable_verified_current_release():
    p=year_pair();r,calls=collect(p,body=release().replace(b'(8)',b'(9)'))
    assert len(calls)==3 and r['status']=='verified_release'
    assert r['prior_year']['status']=='held'
    c=build_cash_comparison(p,r)
    assert c['status']=='held' and c['table']==[]


@pytest.mark.parametrize('mutation',[
    lambda p:p['quarter'][0].update(start='2025-01-01'),
    lambda p:p['quarter'][0].update(fiscal_quarter=3),
    lambda p:p['quarter'].insert(0,deepcopy(p['quarter'][0])),
    lambda p:p['quarter'][0].update(end='2024-06-30'),
])
def test_unmatched_or_ambiguous_periods_hold(mutation):
    p=year_pair();mutation(p)
    assert prior_year_cash_row(p) is None
    assert build_cash_comparison(p)['status']=='held'


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(eligible_for_scoring=True),lambda p:p.update(cik='bad'),
    lambda p:p.update(currency='KRW'),lambda p:p.update(as_of='2026-05-01'),
    lambda p:p['quarter'][0].update(is_single_quarter=False),
    lambda p:p['quarter'][0].update(cash_capex_scope='AI capital expenditure'),
    lambda p:p['quarter'][0]['provenance']['ocf']['facts'][0].update(value=999),
    lambda p:p['quarter'][0]['provenance']['ocf']['facts'][0].update(filed='2027-01-01'),
    lambda p:p['quarter'][0]['provenance']['ocf']['facts'][0].update(accession='0000000123-26-000009'),
])
def test_source_scope_and_eligibility_guards(mutation):
    p=direct_pair();mutation(p)
    assert build_cash_comparison(p)['status']=='held'


@pytest.mark.parametrize('field,value',[('ocf',0),('ocf',-20e6),('cash_capex',0)])
def test_no_misleading_growth_or_ratio_with_nonpositive_base(field,value):
    p=direct_pair();row=p['quarter'][0];row[field]=row['provenance'][field]['facts'][0]['value']=value
    c=build_cash_comparison(p)
    assert c['status']=='verified_comparison'
    if field=='ocf':
        assert not any(r['항목']=='투자지출 / 영업현금흐름' for r in c['table'])
        assert '0 이하' in c['headline']
    assert '이전값 0 이하' in str(c['table'])


def test_ratio_and_residual_can_move_in_opposite_directions():
    p=direct_pair()
    for key,value in [('ocf',10e6),('cash_capex',1e6)]:
        row=p['quarter'][-1];row[key]=row['provenance'][key]['facts'][0]['value']=value
    c=build_cash_comparison(p)
    assert '비중이 줄었습니다' in c['headline']
    assert '단순차액은 전년 동기보다 줄었습니다' in c['interpretation']


def test_pair_cannot_mix_release_documents():
    p=year_pair();r,_=collect(p)
    r['prior_year']['document_sha256']='a'*64
    assert build_cash_comparison(p,r)['status']=='held'


def test_partial_software_does_not_invent_combined_comparison():
    p=year_pair();r,_=collect(p)
    r['prior_year']['values'].pop('software')
    c=build_cash_comparison(p,r)
    assert c['status']=='verified_comparison'
    assert not any('개발비 /' in row['항목'] for row in c['table'])
    assert '개발비의 양쪽 기간 근거가 없어' in c['interpretation']


def test_52_week_calendar_matches_fiscal_quarter_with_shifted_dates():
    p=year_pair();p['quarter'][0].update(start='2025-04-02',end='2025-07-01')
    assert prior_year_cash_row(p) is not None


def test_app_entry_and_decision_reader_unchanged():
    import subprocess
    from pathlib import Path
    assert Path('app.py').read_text(encoding='utf-8-sig')==subprocess.check_output(
        ['git','show','08b2ac4e:app.py'],encoding='utf-8-sig')


def test_overflow_never_becomes_verified_infinity():
    p=direct_pair();row=p['quarter'][0]
    row['ocf']=row['provenance']['ocf']['facts'][0]['value']=1e-300
    row=p['quarter'][-1];row['ocf']=row['provenance']['ocf']['facts'][0]['value']=1e100
    c=build_cash_comparison(p)
    assert c['status']=='held' and c['table']==[]


def test_operational_view_queries_once_and_shows_comparison_table(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import stock_lab_core.company_deep_dive as view
    monkeypatch.setattr(view,'load_quarter_evidence',view.load_quarter_evidence)
    script='''
import streamlit as st
from datetime import datetime, timezone
import stock_lab_core.company_deep_dive as view
from tests.test_company_cash_comparison import year_pair
from tests.test_sec_cash_recovery import collect
view.load_quarter_evidence=lambda *a,**kw:year_pair()
if 'calls' not in st.session_state:st.session_state.calls=[]
def release(p):
 st.session_state.calls.append('release')
 return collect(p)[0]
view.render_company_deep_dive(st,universe=[dict(ticker='ACME',name='ACME',source='관심',is_etf=False)],
 owner='a',configured=True,resolve_cik=None,fetch_facts=None,load_kr=None,cash_release_loader=release,
 now=datetime(2026,11,8,tzinfo=timezone.utc))
'''
    a=AppTest.from_string(script).run();a.selectbox[0].select('ACME').run()
    assert not a.exception and a.session_state.calls==[]
    a.button[0].click().run()
    assert not a.exception and a.session_state.calls==['release']
    tables=[x.value for x in a.dataframe if '전년 동기' in x.value.columns]
    assert len(tables)==1 and len(tables[0])==7
    a.run();assert a.session_state.calls==['release']
