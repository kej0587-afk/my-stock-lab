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
