import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest
from stock_lab_core.company_deep_dive import company_options

SCRIPT = '''
import streamlit as st
from datetime import datetime, timezone
from tests.test_sec_quarter_review import payload
from stock_lab_core.company_deep_dive import render_company_deep_dive
if 'calls' not in st.session_state: st.session_state.calls=[]
def identity(ticker):
 st.session_state.calls.append(ticker)
 if st.session_state.get('fail'): raise ValueError('secret-provider-response')
 return '123', {'ticker':ticker,'cik_str':123}
def kr(symbol):
 st.session_state.calls.append(symbol)
 return {'ok':False,'source':'dart','reason':'DART API 키 없음'}
render_company_deep_dive(st,universe=[
 {'ticker':t,'name':t,'source':'관심','is_etf':False} for t in ('AMZN','NVDA','GOOGL','005930.KS')],
 owner=st.session_state.get('owner','a'), configured=True, resolve_cik=identity,
 fetch_facts=lambda cik:payload(), load_kr=kr, now=datetime(2026,11,8,tzinfo=timezone.utc))
'''


def test_only_held_watch_companies_sorted_deduplicated_without_mutation():
    rows=[dict(ticker='SOXL',name='ETF',source='보유',is_etf=True),
          dict(ticker='MSFT',name='Microsoft',source='관심'),
          dict(ticker='AMZN',name='Amazon',source='보유'),
          dict(ticker='MSFT',name='Microsoft',source='보유'),
          dict(ticker='NVDA',name='NVIDIA',source='레이더')]
    assert list(company_options(rows)) == ['AMZN','MSFT']
    assert rows[1]['source']=='관심'


def test_selection_is_on_demand_scoped_and_failure_clears_old_packet():
    a=AppTest.from_string(SCRIPT).run()
    assert not a.exception and a.session_state.calls==[]
    a.selectbox[0].select('AMZN').run()
    assert a.session_state.calls==[]
    a.button[0].click().run()
    assert not a.exception and a.session_state.calls==['AMZN']
    assert any(x.value=='AMZN (AMZN)' for x in a.subheader)
    a.selectbox[0].select('NVDA').run()
    assert not any(x.value=='AMZN (AMZN)' for x in a.subheader)
    a.session_state['fail']=True
    a.button[0].click().run()
    assert a.warning and not a.dataframe and not a.exception
    assert 'secret-provider' not in str([x.value for x in a.warning])
    a.session_state['owner']='b';a.run()
    assert a.selectbox[0].value=='' and not a.dataframe


def test_googl_is_us_and_kr_failure_is_explicit():
    a=AppTest.from_string(SCRIPT).run()
    a.selectbox[0].select('GOOGL').run();a.button[0].click().run()
    assert not a.exception and a.dataframe
    a.selectbox[0].select('005930.KS').run();a.button[0].click().run()
    assert not a.exception and not a.dataframe
    assert any('DART' in x.value for x in a.info)


def test_default_market_collector_has_no_implicit_msft_fetch():
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    collect=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_collect_today_report_context')
    assert 'collect_msft' not in ast.unparse(collect)
    assert 'collect_msft' not in Path('stock_lab_core/report_context.py').read_text(encoding='utf-8')
    from tests.test_report_section_contract import report_case
    from stock_lab_core.report_evidence import report_sections
    result,_=report_sections(**report_case('2026-11-08T00:00:00+00:00'))
    assert '## MSFT' not in '\n'.join(result)
