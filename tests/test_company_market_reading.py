from copy import deepcopy
from datetime import datetime, timezone
import socket

import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core.company_cash_reading import company_cash_reading
from stock_lab_core.company_market_reading import build_company_market_reading
from stock_lab_core.portfolio_market_review import EVIDENCE_KEY, select_market_review
from tests.test_company_cash_reading import packet
from tests.test_company_deep_dive import SCRIPT

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def market():
    return dict(quote_checked_at=NOW.isoformat(), sessions={'US':'2026-11-06'},
                prices={'^GSPC':dict(date='2026-11-06', **{'return':-.01}, source='fixture')},
                closed_flow_rows=[{'Ticker':s, '기준일':'2026-11-06', '1일수익률':r,
                                  '5일수익률':.02, '3개월수익률':-.1} for s, r in [('SOXX',-.03),('XLC',.01)]])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **kw: pytest.fail('No new network allowed'))


@pytest.mark.parametrize('ticker,proxy,label,expected', [
    ('NVDA','SOXX','반도체',-2), ('META','XLC','통신',2)])
def test_two_regular_companies_reuse_dated_prices_and_validated_financials(ticker, proxy, label, expected):
    p, data = packet(ticker), market()
    original = deepcopy((p, data))
    result = build_company_market_reading(ticker, data, sector=(proxy,label), readings=company_cash_reading(p), now=NOW)
    assert result['sector_excess_pp'] == pytest.approx(expected)
    assert '2026-11-06 종가' in result['headline'] and proxy in result['headline']
    assert len(result['financial']) == 2
    assert '30.0백만 USD' in result['financial'][1]['확인된 사실']
    assert '당일 가격 변화의 원인 증명이 아닙니다' in result['connection']
    assert result['review_only'] and not result['eligible_for_scoring']
    assert (p, data) == original


@pytest.mark.parametrize('checked', ['2026-11-07T23:29:00+00:00','2026-11-08T01:00:00+00:00','invalid'])
def test_stale_future_bad_snapshot_not_used(checked):
    data = dict(market(), quote_checked_at=checked)
    r = build_company_market_reading('NVDA',data,sector=('SOXX','반도체'),now=NOW)
    assert not r['observations'] and not r['news'] and r['sector_excess_pp'] is None


def test_account_scope_and_recent_collection_do_not_make_old_session_current():
    data = market()
    state = {EVIDENCE_KEY:{'scope':'a','data':data}}
    assert not select_market_review(state, 'b', now=NOW)[0]
    assert select_market_review(state, 'a', now=NOW)[0] == data
    data['sessions']['US']='2026-11-02'
    data['prices']['^GSPC']['date']='2026-11-02'
    for row in data['closed_flow_rows']:
        row['기준일']='2026-11-02'
    r = build_company_market_reading('NVDA',data,sector=('SOXX','반도체'),now=NOW)
    assert not r['observations']


def test_calendar_failure_and_stale_price_flags_are_not_current(monkeypatch):
    from stock_lab_core import company_market_reading as module
    data=market();data['prices']['^GSPC']['stale']=True
    r=build_company_market_reading('NVDA',data,sector=('SOXX','반도체'),now=NOW)
    assert r['sector_excess_pp'] is None
    monkeypatch.setattr(module,'session_reference',lambda *a,**kw:{'completed':''})
    assert not build_company_market_reading('NVDA',data,sector=('SOXX','반도체'),now=NOW)['observations']


def test_app_adapter_restores_only_current_company_context_change():
    import ast
    from pathlib import Path
    import subprocess
    from tests.company_market_ast_contract import before_company_market_context
    baseline=subprocess.check_output(['git','show','9f4451ed:app.py'],encoding='utf-8-sig')
    current=Path('app.py').read_text(encoding='utf-8-sig')
    def functions(source, restore=False):
        return {n.name:ast.dump(before_company_market_context(n) if restore else n)
                for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
    assert functions(baseline)==functions(current,True)


@pytest.mark.parametrize('sector', [(),('396500.KS','국내반도체'),('^GSPC','시장')])
def test_missing_or_cross_market_proxy_not_replaced_with_tech(sector):
    r=build_company_market_reading('UNKNOWN',market(),sector=sector,now=NOW)
    assert r['sector_excess_pp'] is None and '업종 비교 미연결' in r['headline']


def test_mismatched_dates_invalid_returns_and_unsupported_financials():
    d=market();d['closed_flow_rows'][0]['기준일']='2026-11-05'
    d['prices']['^GSPC']['return']=True
    r=build_company_market_reading('TSM',d,sector=('SOXX','반도체'),readings=company_cash_reading({}),now=NOW)
    assert not r['financial'] and not r['sector_excess_pp']
    assert '해석 보류' in r['coverage'][0]
    assert '0' not in r['headline']


def test_news_is_session_scoped_and_not_confirmed_causation():
    d=market()
    article=dict(title='Semiconductor shares fall amid AI investment fears',link='https://example.com/article',
                 market='US',session_date='2026-11-06',published_at='2026-11-06T20:00:00+00:00',news_bucket='session_news')
    d['news']=[article,dict(article,link='https://example.com/future',published_at='2026-11-09T20:00:00+00:00'),
               dict(article,link='https://example.com/old',session_date='2026-11-05')]
    r=build_company_market_reading('NVDA',d,sector=('SOXX','반도체'),now=NOW)
    assert len(r['news'])==1 and r['news'][0]['출처']==article['link']
    assert '기사 주장' in next(iter(r['news'][0]))


def test_ui_reuses_snapshot_without_refetching_or_duplicate_financial_block():
    script=SCRIPT.replace("'is_etf':False", "'is_etf':False,'sector':('SOXX','반도체')")
    script=script.replace('load_kr=kr, now=', "load_kr=kr, market_context=lambda:(__import__('tests.test_company_market_reading',fromlist=['market']).market(),'수집 확인'), now=")
    a=AppTest.from_string(script).run()
    a.selectbox[0].select('NVDA').run()
    assert a.session_state.calls==[]
    a.button[0].click().run()
    assert not a.exception and a.session_state.calls==['NVDA']
    assert any('시장에서 이 기업을 읽는 순서' in x.value for x in a.markdown)
    assert len([e for e in a.expander if e.label=='현금 창출·투자 · 근거와 다음 확인'])==1
    a.run();assert a.session_state.calls==['NVDA']
    a.selectbox[0].select('AMZN').run()
    assert not any('시장에서 이 기업을 읽는 순서' in x.value for x in a.markdown)
