from copy import deepcopy
from pathlib import Path
import socket

import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core.sec_cash_recovery import cash_anchors,collect_cash_release,parse_cash_release,recovered_cash_reading
from stock_lab_core.company_cash_reading import company_cash_reading
from tests.test_company_cash_reading import packet
from tests.test_company_deep_dive import SCRIPT


def held_packet(symbol='ACME'):
    p=packet(symbol,cumulative=True)
    for field in ('ocf','cash_capex'):
        e=p['quarter'][-1]['provenance'][field]
        e['status']='cross_filing_difference_review'
        e['facts'][1].update(filed='2026-05-01',accession='0000000123-26-000002')
    return p


def release():
    return b'''<html><table>
    <tr><th colspan="5">Condensed Consolidated Statements of Cash Flows (In millions)</th></tr>
    <tr><th></th><th colspan="2">Three Months Ended June 30,</th><th colspan="2">Six Months Ended June 30,</th></tr>
    <tr><th></th><th>2026</th><th>2025</th><th>2026</th><th>2025</th></tr>
    <tr><td>Net cash provided by operating activities</td><td>$30</td><td>20</td><td>60</td><td>40</td></tr>
    <tr><td>Purchases of property and equipment</td><td>(12)</td><td>(8)</td><td>(24)</td><td>(16)</td></tr>
    <tr><td>Capitalized software development costs</td><td>(2)</td><td>(1)</td><td>(4)</td><td>(2)</td></tr>
    <tr><td>Free cash flow</td><td>16</td><td>11</td><td>32</td><td>22</td></tr>
    </table></html>'''


def submissions():
    return {'cik':123,'filings':{'recent':{
        'form':['8-K'],'items':['2.02,9.01'],'filingDate':['2026-08-01'],
        'accessionNumber':['0000000123-26-000003'],'primaryDocument':['earnings.htm']}}}


def collect(p=None, *, sub=None, body=None, primary=None, fail=False):
    calls=[]
    def fetch(url):
        calls.append(url);return sub if sub is not None else submissions()
    class Response:
        def __init__(self,url):
            self.url=url
            self.content=(body or release()) if url.endswith('/release.htm') else (primary or b'<table><tr><td>99.1</td><td><a href="release.htm">Press release</a></td></tr></table>')
        def raise_for_status(self):
            if fail:raise RuntimeError('SECRET PROVIDER BODY')
    def get(url,**kwargs):
        assert kwargs['timeout']==15
        calls.append(url);return Response(url)
    result=collect_cash_release(p or held_packet(),fetch_json=fetch,user_agent='test-contact',get=get)
    return result,calls


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**kw:pytest.fail('unit tests must be offline'))


@pytest.mark.parametrize('symbol',['DDOG','NVDA','ORDINARY'])
def test_shared_recovery_keeps_packet_and_validates_quarter_plus_ytd(symbol):
    p=held_packet(symbol);original=deepcopy(p)
    r,calls=collect(p)
    assert r['status']=='verified_release' and len(calls)==3
    assert r['values']==dict(ocf=30e6,cash_capex=12e6,software=2e6,company_fcf=16e6,company_fcf_reconciled=True)
    row=recovered_cash_reading(p,r)
    assert '30.0백만 USD' in row['확인된 사실'] and '40.0%' in row['확인된 사실']
    assert '회사 공시 FCF 16.0' in row['확인된 사실']
    assert '소프트웨어 개발비' in row['왜 중요한가']
    assert p==original and '보류' in company_cash_reading(p)[-1]['확인된 사실']


@pytest.mark.parametrize('old,new',[
    (b'$30',b'$31'),(b'>60<',b'>61<'),(b'2026',b'2027'),(b'June 30',b'June 29'),
    (b'Three Months Ended',b'Nine Months Ended'),(b'In millions',b'In thousands'),
    (b'In millions',b'no units'),(b'property and equipment',b'acquisitions'),
    (b'$30',b'$(30)'),(b'Free cash flow</td><td>16',b'Free cash flow</td><td>17'),
])
def test_mismatching_dates_amounts_scope_and_company_fcf(old,new):
    r=parse_cash_release(release().replace(old,new),held_packet())
    if old.startswith(b'Free cash'):
        assert r and not r['company_fcf_reconciled']
    else:assert r is None


def test_conflicting_tables_with_same_header_are_held():
    content=release()+release().replace(b'$30',b'$31')
    assert parse_cash_release(content,held_packet()) is None


def test_split_currency_and_parenthesis_preserve_accounting_sign():
    from stock_lab_core.sec_cash_recovery import _amount
    assert _amount(['OCF','(','$','30',')'],3)==-30
    assert _amount(['OCF','($','30',')'],2)==-30
    assert _amount(['OCF','(','20',')','$','30'],5)==30
    body=release().replace(b'$30',b'( $30)')
    assert parse_cash_release(body,held_packet()) is None


@pytest.mark.parametrize('scope',[b'Unconsolidated affiliate',b'Projected',b'Estimated',b'Segment'])
def test_other_scope_or_forward_period_is_not_actual_cash(scope):
    body=release().replace(b'Three Months Ended',scope+b' Three Months Ended')
    assert parse_cash_release(body,held_packet()) is None


def test_disjoint_tables_cannot_supply_missing_operands():
    a=release().replace(b'Purchases of property and equipment',b'Other outflows')
    b=release().replace(b'Net cash provided by operating activities',b'Other inflows')
    assert parse_cash_release(a+b,held_packet()) is None


@pytest.mark.parametrize('prefix',[b'Projected ',b'Unconsolidated affiliate: '])
def test_external_heading_keeps_scope_qualifiers(prefix):
    title=b'Condensed Consolidated Statements of Cash Flows (In millions)'
    body=release().replace(b'<tr><th colspan="5">'+title+b'</th></tr>',b'')
    body=body.replace(b'<html>',b'<html><div>'+prefix+title+b'</div>')
    assert parse_cash_release(body,held_packet()) is None


def test_99_2_link_cannot_borrow_99_1_from_description():
    primary=b'<table><tr><td><a href="release.htm">99.2</a></td><td>Supplement to Exhibit 99.1</td></tr></table>'
    r,calls=collect(primary=primary)
    assert r=={'status':'held','reason':'release_exhibit_ambiguous'} and len(calls)==2
    primary=b'<table><tr><td>99.1</td><td><a href="release.htm">Exhibit 99.2</a></td></tr></table>'
    r,calls=collect(primary=primary)
    assert r=={'status':'held','reason':'release_exhibit_ambiguous'} and len(calls)==2


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(cik='bad'),lambda p:p.update(currency='EUR'),
    lambda p:p.update(eligible_for_scoring=True),lambda p:p.update(as_of='2026-07-01'),
    lambda p:p['quarter'][-1]['provenance']['ocf']['facts'][1].update(filed='2026-09-01'),
    lambda p:p['quarter'][-1]['provenance']['ocf']['facts'][1].update(form='8-K'),
    lambda p:p['quarter'][-1]['provenance']['ocf']['facts'][1].update(accession='bad'),
    lambda p:p['quarter'][-1]['provenance']['ocf'].update(status='later_revision_in_subtrahend'),
    lambda p:p['quarter'][-1].update(cash_capex_scope='AI investment'),
    lambda p:p['quarter'][-1]['provenance']['ocf']['facts'][1].update(end='2026-03-30'),
])
def test_invalid_or_revised_operands_no_network(mutation):
    p=held_packet();mutation(p)
    assert cash_anchors(p) is None
    r,calls=collect(p);assert r['status']=='not_applicable' and calls==[]


def test_unsupported_direct_packet_no_fetch_and_failures_sanitized():
    r,calls=collect(packet());assert r['status']=='not_applicable' and not calls
    r,calls=collect(fail=True);assert r=={'status':'held','reason':'source_unavailable'}
    assert len(calls)==2


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(cik=456),lambda r:r['filings']['recent']['items'].__setitem__(0,'9.01'),
    lambda r:r['filings']['recent']['filingDate'].__setitem__(0,'2027-01-01'),
    lambda r:r['filings']['recent']['primaryDocument'].__setitem__(0,'https://outside.example/x.htm'),
])
def test_discovery_identity_date_and_path_boundaries(mutation):
    sub=submissions();mutation(sub);r,calls=collect(sub=sub)
    assert r['status']=='held' and len(calls)==1


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(ticker='WRONG'),lambda r:r.update(end='2026-09-30'),
    lambda r:r.update(document_sha256='bad'),lambda r:r.update(source_url='https://outside.example/a'),
    lambda r:r['values'].update(ocf=31e6),lambda r:r.update(filed='2027-01-01'),
    lambda r:r['anchors']['ocf']['facts'][1].update(value=999),
])
def test_restored_evidence_is_bound_to_exact_packet(mutation):
    p=held_packet();r,_=collect(p);mutation(r)
    assert recovered_cash_reading(p,r) is None


def test_ui_no_fetch_on_selection_or_rerender_and_raw_packet_preserved():
    script=SCRIPT.replace("fetch_facts=lambda cik:payload(),", "fetch_facts=lambda cik:payload(), cash_release_loader=lambda packet: st.session_state.calls.append('release') or {'status':'held','reason':'source_unavailable'},")
    a=AppTest.from_string(script).run();a.selectbox[0].select('NVDA').run()
    assert a.session_state.calls==[]
    a.button[0].click().run();assert not a.exception and a.session_state.calls==['NVDA','release']
    a.run();assert a.session_state.calls==['NVDA','release']
    assert any('원문 대조 보류' in x.value for x in a.caption)


def test_recovery_is_review_only_and_default_market_collection_unchanged():
    import ast,subprocess
    base=ast.parse(subprocess.check_output(['git','show','7dd38ffe:app.py'],encoding='utf-8-sig'))
    current=ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    names=lambda tree:{n.name:ast.dump(n) for n in tree.body if isinstance(n,ast.FunctionDef)}
    a,b=names(base),names(current)
    assert a.keys()==b.keys()
    assert [k for k in a if a[k]!=b[k]]==['render_today_market_memo_panel']
    assert 'build_sec_statement_records' not in Path('stock_lab_core/sec_cash_recovery.py').read_text(encoding='utf-8')
