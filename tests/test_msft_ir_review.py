"""Synthetic issuer wording/periods: no remote requests or scoring mutations."""

from copy import deepcopy
from datetime import datetime, timezone
import ast
from pathlib import Path
import socket
import subprocess

import pytest

from stock_lab_core.msft_ir_review import (
    HOME, ROOT, source_identity, discover_msft_release, parse_msft_release, attach_msft_call,
    reconcile_sec, business_reading,
)
from stock_lab_core.msft_ir_source import load_msft_business_evidence, read_official_page

NOW = datetime(2026,11,8,tzinfo=timezone.utc)
RELEASE_URL = ROOT + '/en-us/investor/earnings/fy-2027-q1/press-release-webcast'
CALL_URL = ROOT + '/en-us/investor/events/fy-2027/earnings-fy-2027-q1'
HOME_HTML = f'<a href="{RELEASE_URL}">Result</a><a href="{CALL_URL}">Call</a>'.encode()
RELEASE = b'''<main><h1>Earnings Release FY27 Q1</h1>
<p>REDMOND, Wash. -- October 28, 2026 -- Microsoft Corp. today announced results for the quarter ended September 30, 2026</p>
<p>\xc2\xb7 Revenue was $100.0 billion and increased 20%</p>
<p>Business Highlights</p>
<p>Revenue in Agents and Infra was $70.0 billion and increased 25%</p>
<p>Microsoft Cloud revenue was $60.0 billion and increased 30% (up 31% in constant currency)</p>
<p>Azure revenue increased 40%</p>
<p>Revenue in Devices and Consumer was $30.0 billion and decreased 3%</p>
<p>Business Outlook</p><p>We have recast periods for changes to our segments.</p></main>'''.replace(b'--',b'-')
CALL = b'''<main><h1>Microsoft Fiscal Year 2027 First Quarter Earnings Conference Call</h1>
<p>Wednesday, October 28, 2026</p>
<p>Capital expenditures were $47.0 billion. This quarter, finance leases were $8.8 billion.
We recognize the full principal value of finance leases in capex at the time of lease commencement.
And cash paid for P, P, and E was $40.0 billion. Cash flow from operations was $60 billion.
And free cash flow was $20.0 billion.</p>
<p>Now, moving to the outlook for our second quarter, which is on a US dollar basis.
In Q2, we expect CapEx spend will be over $55 billion.
We expect to continue to remain free cash flow positive in FY27.</p>
<p>With that, let's go to Q&amp;A. ANALYST: Capital expenditures were $999 billion.</p></main>'''


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*a,**k):
        pytest.fail('offline fixture must not contact network')
    monkeypatch.setattr(socket.socket,'connect',fail)


def packet(release=RELEASE, call=CALL):
    def read(url, deadline):
        return {HOME:HOME_HTML,RELEASE_URL:release,CALL_URL:call}[url]
    return load_msft_business_evidence(NOW,read_page=read)


def sec_result():
    return dict(ticker='MSFT',cik='0000789019',currency='USD',quarter=[dict(start='2026-07-01',end='2026-09-30',
        unit='USD',is_single_quarter=True,revenue=100.03e9,cash_capex=39.98e9,ocf=60e9,
        fcf_cash=20.02e9,cash_capex_scope='유형자산')])


def test_latest_official_release_discovered_without_guessed_call_url():
    old = ROOT+'/en-us/investor/earnings/fy-2026-q4/press-release-webcast'
    chosen = discover_msft_release(HOME_HTML+f'<a href="{old}">old</a>'.encode())
    assert chosen['fiscal_year']==2027 and chosen['fiscal_quarter']==1
    assert chosen['call']==CALL_URL
    assert 'call' not in discover_msft_release(f'<a href="{RELEASE_URL}">new</a>'.encode())


@pytest.mark.parametrize('url',[RELEASE_URL+'?key=bad',RELEASE_URL+'#fragment',RELEASE_URL.replace('www.microsoft.com','evil.example'),
    RELEASE_URL.replace('www.microsoft.com','www.microsoft.com.evil.example'),RELEASE_URL.replace('https://','http://'),
    RELEASE_URL.replace('www.microsoft.com','a@www.microsoft.com'),CALL_URL.replace('/fy-2027/','/fy-2026/')])
def test_untrusted_urls_rejected(url):
    assert source_identity(url) is None


def test_actual_scope_growth_guidance_and_qa_isolation():
    p=packet()
    m={x['key']:x for x in p['metrics']}
    assert p['status']=='confirmed' and not p['missing_metrics'] and p['segment_recast']
    assert m['company_revenue']['value']==100 and m['cloud_revenue']['value']==60
    assert m['cloud_revenue']['scope']=='overlapping_cloud_metric'
    assert m['cloud_growth']['value']==30  # not constant-currency31
    assert m['cloud_growth']['source_excerpt']=='30%'
    assert m['cloud_revenue']['source_excerpt']=='$60.0 billion'
    assert m['azure_growth']['value']==40
    assert m['reported_capex']['value']==47 and m['cash_ppe']['value']==40
    assert m['reported_capex']['scope']=='includes_finance_lease_principal'
    assert m['next_capex']['operator']=='gt' and m['next_capex']['value']==55
    assert m['next_capex']['kind']=='management_outlook' and '2026-12-31' in m['next_capex']['period']
    assert m['fy_fcf']['period']=='FY2027' and p['consensus_status']=='not_connected'
    assert p['eligible_for_scoring'] is False and p['period_start']=='2026-07-01'
    assert any(x[0]=='해석(추정)' for x in business_reading(p))


@pytest.mark.parametrize('old,new',[(b'FY27 Q1',b'FY27 Q2'),(b'September 30, 2026',b'June 30, 2026'),
    (b'October 28, 2026',b'December 28, 2026')])
def test_release_wrong_or_future_period_fails(old,new):
    with pytest.raises(ValueError,match='release_period_mismatch'):
        packet(release=RELEASE.replace(old,new))


@pytest.mark.parametrize('old,new',[(b'First Quarter',b'Second Quarter'),(b'October 28, 2026',b'October 29, 2026'),
    (b'our second quarter',b'our third quarter'),(b'With that, let',b'Something else, let')])
def test_call_mismatch_or_unknown_boundary_does_not_import_guidance(old,new):
    p=packet(call=CALL.replace(old,new))
    assert p['status']=='partial' and p['issues']==['call_unavailable_or_unverified']
    assert not any(m['kind']=='management_outlook' for m in p['metrics'])


def test_conflicting_actual_numbers_withheld_not_arbitrarily_selected():
    p=packet(release=RELEASE.replace(b'Business Outlook',b'Azure revenue increased 99% Business Outlook'))
    assert 'azure_growth' in p['missing_metrics'] and p['status']=='partial'


def test_lease_scope_not_inferred_from_presence_of_lease_amount():
    p=packet(call=CALL.replace(b'recognize the full principal value',b'changed our presentation of'))
    m=next(x for x in p['metrics'] if x['key']=='reported_capex')
    assert m['scope']=='unverified_capex_scope'


def test_guidance_currency_and_attached_conditions_not_stripped():
    p=packet(call=CALL.replace(b'US dollar basis',b'constant currency basis'))
    assert 'next_capex' in p['missing_metrics']
    p=packet(call=CALL.replace(b'over $55 billion.',b'over $55 billion if the acquisition closes.'))
    assert 'next_capex' in p['missing_metrics']


def test_same_period_sec_comparison_uses_scope_and_source_rounding():
    s=sec_result(); before=deepcopy(s)
    rows=reconcile_sec(packet(),s)
    assert len(rows)==4 and all('범위 내 일치' in r['상태'] for r in rows)
    assert s==before and not any(r['항목']=='회사 발표 CAPEX' for r in rows)
    s['quarter'][0]['cash_capex']=35e9
    assert '불일치' in reconcile_sec(packet(),s)[1]['상태']
    s['quarter'][0]['cash_capex_scope']='유형·소프트웨어·무형자산'
    assert '범위 확인' in reconcile_sec(packet(),s)[1]['상태']


@pytest.mark.parametrize('field,value',[('start','2026-01-01'),('end','2026-06-30'),('unit','EUR'),('is_single_quarter',False)])
def test_other_period_or_currency_sec_not_compared(field,value):
    s=sec_result();s['quarter'][0][field]=value
    assert reconcile_sec(packet(),s)[0]['항목']=='SEC 대조'


def test_missing_call_is_partial_three_requests_max_no_automatic_retry():
    requests=[]
    def read(url, deadline):
        requests.append(url)
        if url==CALL_URL: raise ValueError('secret_response')
        return HOME_HTML if url==HOME else RELEASE
    p=load_msft_business_evidence(NOW,read_page=read)
    assert requests==[HOME,RELEASE_URL,CALL_URL] and p['status']=='partial'
    assert 'secret_response' not in str(p)


def test_transport_rejects_redirect_and_closes_response(monkeypatch):
    import time
    class Response:
        status_code=302
        def close(self): self.closed=True
    response=Response()
    def get(url,**kwargs):
        assert kwargs['allow_redirects'] is False
        return response
    monkeypatch.setattr('stock_lab_core.msft_ir_source.requests.get',get)
    with pytest.raises(ValueError,match='http_302'):
        read_official_page(RELEASE_URL,time.monotonic()+10)
    assert response.closed


def test_app_functions_unchanged():
    old=subprocess.check_output(['git','show','9390e4ce:app.py']).decode('utf-8-sig')
    def functions(text):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
    assert functions(old)==functions(Path('app.py').read_text(encoding='utf-8-sig'))
