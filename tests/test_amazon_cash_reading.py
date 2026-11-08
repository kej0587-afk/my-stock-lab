"""Public original figures; selected-company narrative cannot affect scoring."""
from copy import deepcopy
import json
import socket

import pytest
from streamlit.testing.v1 import AppTest
from tests.test_bigtech_cash_comparison import comparable
from stock_lab_core.amazon_cash_reading import amazon_cash_reading
from stock_lab_core.company_cash_reading import company_cash_reading


def amazon_packet():
    p = comparable('AMZN', productive=True)
    p.update(cik='0001018724', source_url='https://data.sec.gov/api/xbrl/companyfacts/CIK0001018724.json')
    p['quarter'] = [deepcopy(p['quarter'][-1]) for _ in range(2)]
    for r, year, ocf, capex in zip(p['quarter'], [2025, 2026], [35525, 42422], [35095, 77259]):
        r.update(start=f'{year}-07-01', end=f'{year}-09-30', fiscal_year_start=f'{year}-01-01', fiscal_quarter=3)
        for f in r['provenance'].values():
            for fact in f['facts']:
                fact.update(start=r['start'], end=r['end'], accession='0001018724-26-000040', filed='2026-10-30')
        for field, value, tag in [('ocf', ocf, 'NetCashProvidedByUsedInOperatingActivities'),
                                   ('cash_capex', capex, 'PaymentsToAcquireProductiveAssets')]:
            r[field] = value*1e6
            r['provenance'][field] = {'method': 'reported', 'facts': [dict(start=r['start'], end=r['end'],
                value=r[field], tag=tag, unit='USD', form='10-Q', accession='0001018724-26-000040', filed='2026-10-30')]}
    return p


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('unexpected request'))


def test_source_amounts_and_distinct_cash_segment_definitions():
    p = amazon_packet(); before = deepcopy(p); old = company_cash_reading(p)
    r = amazon_cash_reading(p)
    assert r and p == before and company_cash_reading(p) == old
    assert r['review_only'] and not r['eligible_for_scoring'] and r['previous_verified']
    assert r['changes'] == dict(ocf_yoy_pct=19.4, net_capex_yoy_pct=121.7, aws_revenue_yoy_pct=39.3)
    assert [x['2026년 3분기'] for x in r['cash_rows']] == [42422, 77259, 1381, 75878, -34837, -33456, 23986]
    assert r['net_capex_ratio_pct'] == 178.9
    assert [x['2026년 3분기'] for x in r['additions']] == [57116, 14530, 6068, 548, 78262]
    assert sum(x['2026년 3분기'] for x in r['additions'][:-1]) == r['additions'][-1]['2026년 3분기']
    assert '비현금' in r['limits'] and 'AWS 내 AI 비중' in r['limits']
    assert '38.7%' in r['aws_reading'] and len(r['checks']) == 3
    assert json.loads(json.dumps(r, ensure_ascii=False)) == r


@pytest.mark.parametrize('fault', ['issuer','cik','source','cutoff','checked','naive','date','scope','currency',
    'amount','new_value','accession','tag','status','score','duplicate','newer'])
def test_mismatched_or_newer_sources_never_inherit_review(fault):
    p = amazon_packet(); r = p['quarter'][-1]
    if fault == 'issuer': p['ticker'] = 'MSFT'
    if fault == 'cik': p['cik'] = '0001652044'
    if fault == 'source': p['source_url'] = 'https://example.com'
    if fault == 'cutoff': p['as_of'] = '2026-10-29'
    if fault == 'checked': p['checked_at'] = '2026-11-07T00:00:00+00:00'
    if fault == 'naive': p['checked_at'] = '2026-11-08T00:00:00'
    if fault == 'date': r['start'] = '2026-01-01'
    if fault == 'scope': r['cash_capex_scope'] = '유형자산'
    if fault == 'currency': r['unit'] = 'KRW'
    if fault == 'amount': r['ocf'] += 1
    if fault == 'new_value':
        r['ocf'] += 1; r['provenance']['ocf']['facts'][0]['value'] += 1
    if fault == 'accession': r['provenance']['ocf']['facts'][0]['accession'] = '0001018724-26-000041'
    if fault == 'tag': r['provenance']['cash_capex']['facts'][0]['tag'] = 'PaymentsToAcquirePropertyPlantAndEquipment'
    if fault == 'status': r['provenance']['ocf']['status'] = 'cross_filing_difference_review'
    if fault == 'score': p['eligible_for_scoring'] = True
    if fault == 'duplicate': p['quarter'].append(deepcopy(r))
    if fault == 'newer':
        n=deepcopy(r); n.update(start='2026-10-01',end='2026-12-31');p['quarter'].append(n)
        p.update(as_of='2027-02-01',checked_at='2027-02-01T00:00:00+00:00')
    assert amazon_cash_reading(p) is None


def test_prior_hold_keeps_current_but_never_fills_comparison():
    p = amazon_packet(); p['quarter'][0]['ocf'] += 1
    r = amazon_cash_reading(p)
    assert r and not r['previous_verified'] and not r['changes']
    assert all(x['2025년 3분기'] is None for x in r['cash_rows'] + r['additions'])
    assert '전년 근거 보류' in r['summary'] and '전년 동기' not in r['aws_reading']
    assert '성장' not in r['drivers'][1]['왜 중요한가'] and '확대' not in r['drivers'][1]['왜 중요한가']


SCRIPT = '''
import streamlit as st
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from tests.test_amazon_cash_reading import amazon_packet
from stock_lab_core.company_deep_dive import render_company_deep_dive
if 'calls' not in st.session_state: st.session_state.calls=[]
def load(symbol,**kwargs):
 st.session_state.calls.append(symbol)
 if st.session_state.get('fail'): raise RuntimeError('private-provider-error')
 p=amazon_packet(); p['ticker']=symbol;return p
now=datetime(2026,11,8,tzinfo=timezone.utc)+timedelta(hours=st.session_state.get('hours',0))
with patch('stock_lab_core.company_deep_dive.load_quarter_evidence',load),patch.object(st,'download_button',lambda label,data,**kw:st.session_state.update(download=data)):
 render_company_deep_dive(st,universe=[dict(ticker=t,name=t,source='관심') for t in ['AMZN','NVDA']],
  owner=st.session_state.get('owner','test'),configured=True,resolve_cik=None,fetch_facts=None,load_kr=None,now=now)
'''


def test_ui_is_on_demand_readable_isolated_and_download_keeps_original():
    a=AppTest.from_string(SCRIPT).run(); assert not a.exception and a.session_state.calls==[]
    a.selectbox[0].select('AMZN').run(); assert a.session_state.calls==[]
    a.button[0].click().run(); assert not a.exception and len(a.table)==2
    text='\n'.join(x.value for x in a.markdown)
    assert '178.9%' in text and '비현금 포함' in text and '다음 실적에서 확인할 조건' in text
    bundle=json.loads(a.session_state.download)
    assert bundle['packet']==amazon_packet()
    assert bundle['amazon_cash_review']==amazon_cash_reading(bundle['packet'])
    a.session_state['hours']=7;a.run();assert not a.dataframe and not a.table
    a.session_state['hours']=0;a.session_state['fail']=True;a.button[0].click().run()
    assert a.warning and not a.dataframe and not a.table
    a.session_state['fail']=False;a.selectbox[0].select('NVDA').run();a.button[0].click().run()
    assert not a.exception and not a.table and 'amazon_cash_review' not in json.loads(a.session_state.download)
    a.session_state['owner']='other';a.run();assert a.selectbox[0].value=='' and not a.dataframe
