"""Synthetic same-filing quarter comparisons, independent of live account state."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import ast
from pathlib import Path

import pytest

from stock_lab_core.msft_cash_trend import build_msft_cash_trend, SOURCE_URL, TAGS
from stock_lab_core import report_msft_cash as report

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def packet():
    rows=[]
    for i,(year,month) in enumerate([(2024,12),(2025,3),(2025,6),(2025,9),
                                    (2025,12),(2026,3),(2026,6),(2026,9)]):
        next_month=date(year+1,1,1) if month==12 else date(year,month+1,1)
        end=(next_month-timedelta(days=1)).isoformat(); start=date(year,month-2,1).isoformat()
        filed={12:'2026-01-28',3:'2026-04-29',6:'2026-07-29',9:'2026-10-28'}[month]
        accession=f'0000789019-26-{month:06d}'
        row=dict(start=start,end=end,unit='USD',is_single_quarter=True,
            fiscal_quarter={9:1,12:2,3:3,6:4}[month],cash_capex_scope='유형자산',
            ocf=(100 if i<4 else 120)*1e8,cash_capex=(40 if i<4 else 90)*1e8,provenance={})
        for field,tag in TAGS.items():
            row['provenance'][field]=dict(method='reported',facts=[dict(start=start,end=end,
                unit='USD',tag=tag,value=row[field],filed=filed,accession=accession,form='10-Q')])
        rows.append(row)
    return dict(ticker='MSFT',cik='0000789019',source_url=SOURCE_URL,currency='USD',
                checked_at=NOW.isoformat(),as_of=NOW.date().isoformat(),review_only=True,
                eligible_for_scoring=False,status='quarter_evidence_only',quarter=rows)


def text(p):
    return '\n'.join(report.msft_cash_lines({'msft_cash_evidence':{'packet':p}},NOW))


def test_cash_burden_yoy_math_with_immutable_input():
    p=packet(); before=deepcopy(p); trend=build_msft_cash_trend(p,NOW)
    c=trend['latest_comparison']
    assert trend['status']=='connected' and len(trend['rows'])==8 and len(trend['comparisons'])==4
    assert c['burden_delta_pp']==pytest.approx(35)
    assert c['ocf_growth_pct']==pytest.approx(20) and c['capex_growth_pct']==pytest.approx(125)
    assert c['residual_delta']==pytest.approx(-30e8) and p==before
    s=text(p)
    assert '부담이 커졌습니다' in s and '40.0%보다 +35.0%p' in s and '4쌍' in s
    assert '현금 고갈 예측' in s and '공시' in s and '다음 확인' in s


@pytest.mark.parametrize('key,value',[('currency','EUR'),('ticker','OTHER'),('source_url',SOURCE_URL+'?fake'),
    ('cik','0000000123'),('checked_at',(NOW+timedelta(seconds=1)).isoformat()),
    ('checked_at',(NOW-timedelta(days=2)).isoformat()),('as_of','2026-11-09'),('eligible_for_scoring',True)])
def test_unusable_packet_withheld(key,value):
    p=packet();p[key]=value
    assert build_msft_cash_trend(p,NOW)['status']=='unavailable'
    assert '보류' in text(p) and '75.0%' not in text(p)


@pytest.mark.parametrize('mutation',['missing','revision','mixed_filing','scope','nonfinite','negative_capex',
                                     'wrong_fact_period','future_filing','value_mismatch'])
def test_latest_invalid_values_never_substituted_with_zero_or_older_quarter(mutation):
    p=packet(); r=p['quarter'][-1]; e=r['provenance']['cash_capex']
    if mutation=='missing': r['ocf']=None
    elif mutation=='revision': e['status']='later_revision_in_subtrahend'
    elif mutation=='mixed_filing': e['facts'][0]['accession']='0000789019-26-999999'
    elif mutation=='scope': r['cash_capex_scope']='유형·소프트웨어·무형자산'
    elif mutation=='nonfinite': r['ocf']=float('inf')
    elif mutation=='negative_capex': r['cash_capex']=e['facts'][0]['value']=-1
    elif mutation=='wrong_fact_period': e['facts'][0]['start']='2026-04-01'
    elif mutation=='future_filing': e['facts'][0]['filed']='2026-12-01'
    else: r['cash_capex']=0
    t=build_msft_cash_trend(p,NOW)
    assert t['latest_comparison'] is None and not t['rows'][-1]['valid']
    assert '2026-09-30 | — | — | — | —' in text(p)


@pytest.mark.parametrize('ocf',[0,-100])
def test_nonpositive_ocf_keeps_amounts_but_withholds_ratio(ocf):
    p=packet(); r=p['quarter'][-1];r['ocf']=r['provenance']['ocf']['facts'][0]['value']=ocf
    t=build_msft_cash_trend(p,NOW)
    assert t['rows'][-1]['valid'] and t['rows'][-1]['burden_pct'] is None
    assert t['latest_comparison'] is None and '보류(영업현금≤0)' in text(p)


def test_zero_capex_is_real_zero_and_not_missing():
    p=packet();r=p['quarter'][-1];r['cash_capex']=r['provenance']['cash_capex']['facts'][0]['value']=0
    assert build_msft_cash_trend(p,NOW)['rows'][-1]['burden_pct']==0
    assert '부담이 줄었습니다' in text(p)


def test_cross_filing_yoy_is_withheld_even_when_each_quarter_is_valid():
    p=packet()
    for e in p['quarter'][-1]['provenance'].values():e['facts'][0]['accession']='0000789019-26-999999'
    t=build_msft_cash_trend(p,NOW)
    assert t['rows'][-1]['valid'] and t['latest_comparison'] is None


def test_cumulative_difference_same_filing_allowed_cross_filing_withheld():
    p=packet();r=p['quarter'][-2]
    for field,e in r['provenance'].items():
        original=e['facts'][0]
        e['method']='cumulative_difference'
        e['facts']=[dict(original,start='2025-07-01',value=r[field]*4),
                    dict(original,start='2025-07-01',end='2026-03-31',value=r[field]*3)]
    assert build_msft_cash_trend(p,NOW)['rows'][-2]['valid']
    for e in r['provenance'].values():e['facts'][1]['accession']='0000789019-26-999999'
    assert not build_msft_cash_trend(p,NOW)['rows'][-2]['valid']


def test_gaps_and_partial_evidence_do_not_become_an_eight_quarter_total():
    p=packet(); del p['quarter'][2]
    t=build_msft_cash_trend(p,NOW)
    assert t['gaps'] and len(t['rows'])==7 and t['latest_comparison']
    assert '관측 7분기' in text(p) and '누락 있음' in text(p)
    p['quarter'].append(deepcopy(p['quarter'][-1]))
    assert build_msft_cash_trend(p,NOW)['status']=='unavailable'


def test_collect_once_cache_failure_config_and_render_without_requests(monkeypatch):
    calls=[]; p=packet()
    monkeypatch.setattr(report,'_CACHE',{})
    def load(symbol,**kwargs): calls.append(symbol); return deepcopy(p)
    monkeypatch.setattr(report,'load_quarter_evidence',load)
    kwargs=dict(configured=True,resolve_cik=None,fetch_facts=None)
    a=report.collect_msft_cash_evidence(NOW,**kwargs)
    b=report.collect_msft_cash_evidence(NOW,**kwargs)
    report.msft_cash_lines({'msft_cash_evidence':a},NOW)
    assert calls==['MSFT'] and b['collection']=='success_cache'
    b['packet']['quarter'].clear(); assert a['packet']['quarter']
    assert report.collect_msft_cash_evidence(NOW,**dict(kwargs,configured=False))['packet'] is None
    monkeypatch.setattr(report,'_CACHE',{})
    def fail(*a,**kw):calls.append('failed');raise RuntimeError('secret provider body')
    monkeypatch.setattr(report,'load_quarter_evidence',fail)
    for _ in range(2): assert 'secret' not in str(report.collect_msft_cash_evidence(NOW,**kwargs))
    assert calls[-2:]==['failed','failed'] and not report._CACHE


def test_full_report_has_one_cash_section_preserves_inputs_and_old_report():
    from tests.test_report_section_contract import report_case
    from stock_lab_core.report_evidence import report_sections
    args=report_case(NOW.isoformat());args['context']['msft_cash_evidence']={'packet':packet()}
    before=deepcopy(args);lines,_=report_sections(**args);s='\n'.join(lines)
    assert s.count('## MSFT 8분기 현금 부담')==1 and '75.0%' in s
    assert s.index('## 핵심 해석')<s.index('## MSFT 8분기')<s.index('## 내 보유 종목 영향')
    assert args==before and report.msft_cash_lines({},NOW)==[]


def test_briefing_uses_post_collection_clock_for_fresh_evidence():
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_generate_today_briefing_market_memo')
    assignment=next(n for n in function.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='memo_kwargs' for t in n.targets))
    clock=[NOW];calls=[]
    class Clock:
        @staticmethod
        def now(tz): return clock[0].astimezone(tz)
    def collect(*args,**kwargs):
        calls.append('collect');clock[0]+=timedelta(seconds=5)
        p=packet();p['checked_at']=clock[0].isoformat()
        return {'msft_cash_evidence':{'packet':p}}
    env=dict(snapshot={},macro_res={},event_rows=[],index_rotation_rows=[],news_rows=[],memo_summary_df=[],
             datetime=Clock,timezone=timezone,timedelta=timedelta,options={'include_market':False},_collect_today_report_context=collect)
    exec(compile(ast.Module(body=[assignment],type_ignores=[]),'app.py','exec'),env)
    kwargs=env['memo_kwargs']
    assert calls==['collect']
    assert '75.0%' in '\n'.join(report.msft_cash_lines(kwargs['report_context'],kwargs['now']))
