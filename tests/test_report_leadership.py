"""Market rotation reading cannot promote relative defense to an uptrend."""
from copy import deepcopy
import socket

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.report_leadership import price_reading, leadership_lines, company_research_question
from stock_lab_core.market_observation import build_sector_rotation
from stock_lab_core.report_editorial import reading_order


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**k:pytest.fail('unexpected network'))


def row(ticker='XLI', **changes):
    return dict(ticker=ticker,sector={'XLI':'Industrials','XLV':'Health care','XLE':'Energy',
        'SOXX':'Semiconductors','SMH':'Semiconductors'}.get(ticker,ticker),market='US',
        date='2026-11-06',return_5d=.02,return_20d=.08,return_3m=.15,
        rs_5d_change=.01,rs_20d_change=.05,**changes)


def altered(**changes):
    r=row();r.update(changes);return r


@pytest.mark.parametrize('changes,label',[
    ({},'상승 추세 후보'),
    ({'return_20d':-.03,'return_3m':-.2},'상대적 방어'),
    ({'return_20d':0},'상대적 방어'),
    ({'return_20d':-.08,'rs_20d_change':-.1},'반등·회복 관찰'),
    ({'return_5d':-.02,'return_20d':-.08,'rs_20d_change':-.1},'가격·상대강도 약세'),
    ({'rs_5d_change':-.01},'추세 확인 대기'),
    ({'return_5d':-.03},'추세 확인 대기'),
    ({'return_3m':None},'자료 부족'),
    ({'return_20d':float('nan')},'자료 부족'),
    ({'rs_5d_change':True},'자료 부족'),
])
def test_reading_separates_absolute_relative_and_rebound(changes,label):
    assert price_reading(altered(**changes))[0]==label


def packet(rows,market='US'):
    return {'markets':{market:{'date':'2026-11-06','sample_count':len(rows),'rows':rows}}}


def test_falling_market_never_invents_next_leader_or_mutates_input():
    r=packet([altered(return_20d=-.03,return_3m=-.1)])
    original=deepcopy(r)
    out='\n'.join(leadership_lines(r,[]))
    assert '조건을 충족한 업종이 없습니다' in out
    assert '상대적 방어' in out and '실제 수익률은 상승이 아님' in out
    assert r==original and '6업종 미만' in out


def test_duplicate_semiconductor_etfs_have_one_vote_and_company_scope_is_explicit():
    r=packet([row('SOXX'),row('SMH'),row('XLI'),row('XLV'),row('XLE')])
    out='\n'.join(leadership_lines(r,[{'티커':'MSFT'},{'티커':'GOOG'},{'티커':'GOOGL'},{'티커':'MU'}]))
    assert '비교 4업종(ETF 5개' in out and '(SMH)' not in out and '(SOXX)' in out
    assert 'MSFT, GOOGL' in out and 'GOOGL, GOOG' not in out
    assert '실적 변화나 하락 원인 주장이 아닙니다' in out
    assert '기업 심층분석' in out and '회사 전체' in out


def test_each_market_is_independent_and_missing_history_is_not_zero():
    r=packet([altered(return_20d=-.03,return_3m=-.1)])
    kr=row('494670.KS');kr.update(market='KR',sector='Shipbuilding',date='2026-11-05')
    r['markets']['KR']={'date':'2026-11-05','sample_count':1,'rows':[kr]}
    out='\n'.join(leadership_lines(r,[]))
    assert '**KR · 2026-11-05 확정 종가:** 조선' in out
    assert '**US · 2026-11-06 확정 종가:** 반도체·기술 외 상승 추세 후보 조건을 충족한 업종이 없습니다' in out
    empty='\n'.join(leadership_lines({'markets':{}},[]))
    assert '후보 선정을 보류' in empty and '0.0%' not in empty


def test_kr_technology_is_focus_not_a_nontechnology_alternative():
    tech=row('139260.KS');tech.update(market='KR',sector='Technology')
    out='\n'.join(leadership_lines(packet([tech],market='KR'),[]))
    assert '(139260.KS)' in out
    assert '조건을 충족한 업종이 없습니다' in out
    assert '**다른 업종에서 확인할 후보**' not in out


def test_new_returns_use_same_uncompressed_benchmark_window():
    dates=pd.bdate_range('2026-01-02',periods=140)
    base=np.arange(140)*0.1+100
    asset=np.arange(140)*0.3+50
    frames={'^GSPC':pd.DataFrame({'Close':base},index=dates),'XLI':pd.DataFrame({'Close':asset},index=dates)}
    kwargs=dict(sessions={'US':dates[-1].date().isoformat()},as_of='2026-11-08T00:00:00Z',
        sector_map={'XLI':{'market':'US','sector':'Industrials','kind':'sector_etf'}})
    r=build_sector_rotation(frames,**kwargs)['markets']['US']['rows'][0]
    assert r['return_20d']==pytest.approx(asset[-1]/asset[-21]-1)
    assert r['return_5d']==pytest.approx(asset[-1]/asset[-6]-1)
    frames['XLI']=frames['XLI'].drop(dates[-10])
    assert not build_sector_rotation(frames,**kwargs)['markets']


def test_existing_rotation_runs_once_and_summary_precedes_audit(monkeypatch):
    from stock_lab_core import report_observation_panel as panel
    calls=[]
    original=panel.build_sector_rotation
    def counted(*a,**k):
        calls.append(1);return original(*a,**k)
    monkeypatch.setattr(panel,'build_sector_rotation',counted)
    lines=panel.observation_report_lines({},[],[],'2026-11-08T00:00:00Z')
    assert calls==[1]
    out='\n'.join(reading_order(['## 내 보유 종목 영향','kept',*lines,'## 핵심 해석','kept2']))
    assert out.count('## 주도 업종 교체 관측')==1
    assert out.index('## 핵심 해석')<out.index('## 주도 업종 교체 관측')<out.index('## 내 보유 종목 영향')
    from stock_lab_core.report_view import COLLAPSED_SECTIONS
    assert '관찰 근거 · 매매 판정과 별도' in COLLAPSED_SECTIONS
    assert '주도 업종 교체 관측' not in COLLAPSED_SECTIONS


def test_company_questions_differentiate_spenders_suppliers_and_advertising():
    assert '투자지출' in company_research_question('MSFT')['시장 질문']
    assert '실제 주문' in company_research_question('NVDA')['시장 질문']
    assert '광고 효율' in company_research_question('META')['시장 질문']
    assert '업종 가격 강세' in company_research_question('XOM')['시장 질문']


def article(**overrides):
    return dict(dict(title='반도체 고객 실적 전망 우려', market='US', session_date='2026-11-06',
                     published_at='2026-11-06T15:00:00-05:00', news_bucket='session_news',
                     link='https://www.reuters.com/example-chip-report'), **overrides)


def test_story_links_weak_focus_and_real_alternative_without_claiming_capital_transfer():
    chip=altered(ticker='SOXX',sector='Semiconductors',return_20d=-.1,rs_20d_change=-.08)
    r=packet([chip,row('XLI')]); before=deepcopy(r)
    out='\n'.join(leadership_lines(r,[],{},[], '2026-11-08T00:00:00Z'))
    assert '반도체는 20일 실제 수익률과' in out
    assert '반면 산업재는 5·20·63일 실제 상승' in out
    assert '주도권 이동 가능성' in out and '자금 이동이나 실적 개선까지 증명된 것은 아닙니다' in out
    assert '반도체의 5일 반등은 이 중기 약세와 함께' in out
    assert '구성종목으로 확산' in out and '수주' in out
    assert r==before


def test_relative_defense_is_not_an_improving_leader_and_dates_are_filtered():
    weak=altered(ticker='SOXX',sector='Semiconductors',return_5d=-.01,return_20d=-.1,rs_20d_change=-.08)
    defense=altered(return_20d=-.02)
    wrong=altered(ticker='XLE',sector='Energy',date='2026-11-05')
    out='\n'.join(leadership_lines(packet([weak,defense,wrong]),[]))
    assert '새 주도업종이 생겼다고 읽기 어렵습니다' in out
    assert '덜 하락한 것이며 상승 추세와 다릅니다' in out
    assert '(XLE)' not in out and '같은 확정 거래일의 매크로 근거가 미연결' in out


@pytest.mark.parametrize('changes',[
    {'market':'KR'}, {'session_date':'2026-11-05'}, {'news_bucket':'next_session_news'},
    {'published_at':'2026-11-09T00:00:00Z'}, {'published_at':''}, {'link':'javascript:alert(1)'},
    {'title':'Chip stocks futures poised to rise ahead of open'},
])
def test_story_rejects_news_outside_session_or_source(changes):
    out='\n'.join(leadership_lines(packet([row('SOXX')]),[],{},[article(**changes)],'2026-11-08T00:00:00Z'))
    assert 'reuters.com/example-chip-report' not in out
    assert '미확인: 같은 세션의 관련 보도 원문 미연결' in out


def test_body_is_article_claim_and_same_url_not_independent_evidence():
    fact={'summary':'회사는 주문 전망을 낮췄다는 보도', 'implication':'매출 전환 지연 가능성',
          'check':'다음 주문·매출 공시 확인'}
    news=[article(title='반도체·산업재 고객 실적 우려',body_status='verified',body_facts=[fact])]
    out='\n'.join(leadership_lines(packet([row('SOXX'),row('XLI')]),[],{},news,'2026-11-08T00:00:00Z'))
    assert '기사 주장 · 업종 관련 보도' in out and '해석(추정): 매출 전환 지연 가능성' in out
    assert out.count('https://www.reuters.com/example-chip-report')==1
    assert '중복 계산하지 않음' in out and '20·63일 흐름 전체의 원인 증명이 아닙니다' in out
    news[0]['body_status']='failed'
    out='\n'.join(leadership_lines(packet([row('SOXX')]),[],{},news,'2026-11-08T00:00:00Z'))
    assert '제목 수준' in out and '매출 전환 지연 가능성' not in out


def test_macro_and_price_volume_require_matching_dates_not_new_scores():
    r=packet([altered(money_flow_score=78,money_flow_date='2026-11-06')])
    context={'sessions':{'US':'2026-11-06','KR':'2026-11-06'},'macro_data':{
        'VIX':{'val':26,'chg':15,'as_of':'2026-11-06','source':'test VIX'},
        '유가':{'val':120,'chg':30,'as_of':'2026-11-05','source':'stale oil'}}}
    before=deepcopy((r,context))
    out='\n'.join(leadership_lines(r,[],context,[],'2026-11-08T00:00:00Z'))
    assert 'VIX 26.00pt' in out and 'stale oil' not in out
    assert '가격·거래량 점수 78.0' in out and '실제 자금 유입액' in out
    assert (r,context)==before
    r['markets']['US']['rows'][0]['money_flow_date']='2026-11-05'
    assert '점수 78.0' not in '\n'.join(leadership_lines(r,[],context,[],'2026-11-08T00:00:00Z'))


def test_common_market_story_does_not_steal_direct_shipping_evidence():
    chip=altered(ticker='396500.KS',sector='Semiconductors',market='KR',return_20d=-.1,rs_20d_change=-.08)
    ship=altered(ticker='494670.KS',sector='Shipbuilding',market='KR')
    news=[article(title='코스피 반등, 조선 수주 호조',market='KR',published_at='2026-11-06T14:00:00+09:00',
                  body_status='verified',body_facts=[{'summary':'조선 수주 A | B', 'implication':'주문이 매출로 전환될 가능성', 'check':'납기 확인'}])]
    out='\n'.join(leadership_lines(packet([chip,ship],market='KR'),[],{},news,'2026-11-08T00:00:00Z'))
    chipline=next(s for s in out.splitlines() if s.startswith('KR 반도체 ·'))
    shipline=next(s for s in out.splitlines() if s.startswith('KR 조선 ·'))
    assert '조선 수주 A' not in chipline and '미확인' in chipline
    assert '조선 수주 A / B' in shipline and len(shipline.split(' | '))==3
    assert out.count('https://www.reuters.com/example-chip-report')==1


def test_after_close_article_keeps_timing_caveat():
    chip=altered(ticker='396500.KS',sector='Semiconductors',market='KR')
    news=[article(market='KR',published_at='2026-11-06T19:00:00+09:00',post_close_context=True)]
    out='\n'.join(leadership_lines(packet([chip],market='KR'),[],{},news,'2026-11-08T00:00:00Z'))
    assert '종가 이후 보도(당시 가격 원인으로 소급하지 않음)' in out


def test_price_audit_is_collapsible_but_story_remains_visible():
    from stock_lab_core.report_view import SECTION_DETAILS
    markers, _ = SECTION_DETAILS['주도 업종 교체 관측']
    out='\n'.join(leadership_lines(packet([row('SOXX'),row('XLI')]),[]))
    boundary=min(out.index(marker) for marker in markers if marker in out)
    assert '해석(추정)' in out[:boundary] and '가격 관측을 사업 근거로 확인할 곳' in out[:boundary]
    assert 'RS 변화 5일 / 20일' in out[boundary:]
