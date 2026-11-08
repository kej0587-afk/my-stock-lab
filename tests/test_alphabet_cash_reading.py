"""Source-bound narrative and on-demand UI; public facts, no network/account data."""
from copy import deepcopy
import json
import socket

import pytest
from streamlit.testing.v1 import AppTest
from tests.test_alphabet_cash_q3 import alphabet_packet
from stock_lab_core.alphabet_cash_reading import alphabet_cash_reading, CALL_URL
from stock_lab_core.company_cash_reading import company_cash_reading


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('unexpected request'))


def test_cash_recovery_reuses_exact_evidence_without_mutating_generic_reader():
    p = alphabet_packet(); before = deepcopy(p); generic = company_cash_reading(p)
    r = alphabet_cash_reading(p)
    assert p == before and company_cash_reading(p) == generic
    assert r['review_only'] and not r['eligible_for_scoring']
    assert len(r['recoveries']) == 2
    assert [x['영업현금(백만$)'] for x in r['rows']] == [48414, 42290]
    assert r['changes'] == {'ocf_yoy_pct': -12.6, 'capex_yoy_pct': 114.4, 'ratio_change_pp': 72}
    assert r['rows'][1]['단순차액(백만$)'] == -9065
    assert '121.4%' in r['summary'] and '부담이 커졌' in r['summary']
    assert '기술 인프라 투자 중' in r['drivers'][0]['확인된 근거']
    assert '52억 달러' in r['drivers'][2]['확인된 근거']
    assert r['sources']['management_call'] == CALL_URL and r['source_date'] == '2026-10-28'
    assert len(r['checks']) == 3 and '미연결' in r['limits']
    assert json.loads(json.dumps(r, ensure_ascii=False)) == r


@pytest.mark.parametrize('change', ['issuer', 'amount', 'provenance', 'duplicate', 'newer', 'date', 'flag'])
def test_never_apply_old_or_mismatched_narrative(change):
    p = alphabet_packet()
    if change == 'issuer': p['ticker'] = 'MSFT'
    if change == 'amount': p['quarter'][-1]['ocf'] += 1
    if change == 'provenance': p['quarter'][-1]['provenance']['ocf']['facts'][0]['accession'] = 'revised'
    if change == 'duplicate': p['quarter'].append(deepcopy(p['quarter'][-1]))
    if change == 'newer':
        row = deepcopy(p['quarter'][-1]); row.update(start='2026-10-01', end='2026-12-31')
        p['quarter'].append(row); p.update(as_of='2027-02-01', checked_at='2027-02-01T00:00:00+00:00')
    if change == 'date': p['as_of'] = '2026-11-07'
    if change == 'flag': p['eligible_for_scoring'] = True
    assert alphabet_cash_reading(p) is None


def test_missing_previous_holds_yoy_but_preserves_verified_current():
    p = alphabet_packet(); p['quarter'][0]['ocf'] += 1
    r = alphabet_cash_reading(p)
    assert not r['changes'] and len(r['recoveries']) == 1
    assert r['rows'][0]['영업현금(백만$)'] is None
    assert '늘었는지 비교하지 않습니다' in r['summary']
    p['ticker'] = 'GOOG'
    assert alphabet_cash_reading(p)['rows'] == r['rows']


SCRIPT = '''
import streamlit as st
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from tests.test_alphabet_cash_q3 import alphabet_packet
from stock_lab_core.company_deep_dive import render_company_deep_dive
if 'calls' not in st.session_state: st.session_state.calls=[]
def loader(symbol, **kwargs):
 st.session_state.calls.append(symbol)
 if st.session_state.get('fail'): raise RuntimeError('private-provider-error')
 p=alphabet_packet(); p['ticker']=symbol; return p
now=datetime(2026,11,8,tzinfo=timezone.utc)+timedelta(hours=st.session_state.get('hours',0))
with patch('stock_lab_core.company_deep_dive.load_quarter_evidence', loader), patch.object(st,'download_button',lambda label,data,**kw:st.session_state.update(download=data)):
 render_company_deep_dive(st,universe=[dict(ticker=t,name=t,source='관심') for t in ['GOOGL','MSFT']],
  owner='test',configured=True,resolve_cik=None,fetch_facts=None,load_kr=None,now=now)
'''


def test_selected_company_ui_download_and_expiry():
    a = AppTest.from_string(SCRIPT).run()
    assert not a.exception and a.session_state.calls == []
    a.selectbox[0].select('GOOGL').run()
    assert a.session_state.calls == []
    a.button[0].click().run()
    assert not a.exception and a.session_state.calls == ['GOOGL']
    text = '\n'.join(x.value for x in a.markdown)
    assert '121.4%' in text and '다음 실적에서 확인할 조건' in text
    assert '5개 항목 중 3개 확인' not in text and '단순차액·투자지출 비율 보류' not in text
    bundle = json.loads(a.session_state.download)
    assert bundle['packet'] == alphabet_packet()
    assert bundle['alphabet_cash_review'] == alphabet_cash_reading(bundle['packet'])
    assert any('원자료 8분기' in x.label for x in a.expander)
    a.session_state['hours'] = 7; a.run()
    assert not a.dataframe and any('6시간' in x.value for x in a.info)
    a.session_state['hours'] = 0; a.session_state['fail'] = True
    a.button[0].click().run()
    assert not a.exception and not a.dataframe and a.warning
    a.session_state['fail'] = False; a.selectbox[0].select('MSFT').run()
    assert not a.dataframe
