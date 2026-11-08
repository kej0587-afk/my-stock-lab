"""Public SEC statement values; no account data, credentials or network."""
from copy import deepcopy
import json
import socket

import pytest
from streamlit.testing.v1 import AppTest
from tests.test_bigtech_cash_comparison import comparable
from stock_lab_core.alphabet_cash_q3 import reviewed_alphabet_q3
from stock_lab_core.bigtech_cash_comparison import compare_bigtech_cash
from stock_lab_core.bigtech_cash_view import _display_rows


def alphabet_packet():
    # Numeric source fixture independent from the recovery module's registry.
    packet = comparable('GOOGL')
    packet.update(cik='0001652044', source_url='https://data.sec.gov/api/xbrl/companyfacts/CIK0001652044.json')
    packet['quarter'] = [deepcopy(packet['quarter'][-1]) for _ in range(2)]
    for row, year, values in zip(packet['quarter'], [2025, 2026], [
            {'ocf': (112311, 63897, 48414), 'cash_capex': (63596, 39643, 23953)},
            {'ocf': (127149, 84859, 42290), 'cash_capex': (131953, 80598, 51355)}]):
        row.update(start=f'{year}-07-01', end=f'{year}-09-30', fiscal_year_start=f'{year}-01-01', fiscal_quarter=3)
        for field, (nine, six, quarter) in values.items():
            tag = {'ocf': 'NetCashProvidedByUsedInOperatingActivities', 'cash_capex': 'PaymentsToAcquirePropertyPlantAndEquipment'}[field]
            row[field] = quarter * 1000000
            row['provenance'][field] = dict(method='cumulative_difference', status='cross_filing_difference_review', facts=[
                dict(start=f'{year}-01-01', end=f'{year}-09-30', value=nine*1000000, unit='USD', tag=tag,
                     accession='0001652044-26-000084', filed='2026-10-29', form='10-Q'),
                dict(start=f'{year}-01-01', end=f'{year}-06-30', value=six*1000000, unit='USD', tag=tag,
                     accession='0001652044-26-000071', filed='2026-07-23', form='10-Q')])
    return packet


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('unexpected request'))


def comparison(p):
    # Peer on identical calendar periods, synthetic fields, no recovery.
    peer = deepcopy(p)
    peer.update(ticker='MSFT', cik='0000789019')
    return compare_bigtech_cash({p['ticker']: p, 'MSFT': peer})


def test_exact_original_values_restore_both_quarters_without_mutating_evidence():
    p = alphabet_packet(); before = deepcopy(p)
    r = comparison(p)
    assert p == before and len(r['recoveries']) == 2
    current = r['rows'][0]; change = r['trends'][0]
    assert current['영업현금(백만$)'] == 42290
    assert current['현금 투자(백만$)'] == 51355
    assert current['단순차액(백만$)'] == -9065
    assert current['투자/영업현금(%)'] == 121.4
    assert current['확인 상태'] == '실적발표 원문 대조(미감사)'
    assert _display_rows([current])[0]['확인 상태'] == current['확인 상태']
    assert change['전년 영업현금(백만$)'] == 48414 and change['전년 현금 투자(백만$)'] == 23953
    assert (change['영업현금 YoY(%)'], change['현금 투자 YoY(%)'], change['투자 비율 변화(%p)']) == (-12.6, 114.4, 72)
    assert r['rows'][1]['영업현금(백만$)'] is None  # Never rescue another issuer.
    assert '영업현금 감소' in r['readings'][0]['해석(추정)']
    assert len({x['accession'] for x in r['recoveries']}) == 1
    assert all(x['unaudited'] and x['reviewed_on']=='2026-11-08' for x in r['recoveries'])
    assert json.loads(json.dumps(r, ensure_ascii=False)) == r


@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('field', ['ocf', 'cash_capex'])
@pytest.mark.parametrize('key,value', [('accession','0001652044-26-999999'), ('filed','2026-11-01'),
    ('start','2026-01-02'), ('end','2026-06-29'), ('form','10-Q/A'), ('unit','EUR'),
    ('value',0), ('tag','PaymentsToAcquireProductiveAssets')])
def test_changed_operand_returns_to_hold(index, field, key, value):
    p=alphabet_packet(); row=p['quarter'][-1]
    row['provenance'][field]['facts'][index][key]=value
    assert reviewed_alphabet_q3(p,row) is None
    assert comparison(p)['rows'][0]['투자/영업현금(%)'] is None


@pytest.mark.parametrize('field', ['ocf','cash_capex'])
@pytest.mark.parametrize('status', ['', None, 'later_revision_in_subtrahend','direct_cumulative_conflict'])
def test_other_guard_reasons_are_not_bypassed(field,status):
    p=alphabet_packet();p['quarter'][-1]['provenance'][field]['status']=status
    assert reviewed_alphabet_q3(p,p['quarter'][-1]) is None


@pytest.mark.parametrize('key,value', [('ticker','AMZN'),('cik','0001018724'),('source_url','https://example.com/'),
    ('currency','EUR'),('review_only',False),('eligible_for_scoring',True),('status','failed'),
    ('checked_at','2026-11-07T00:00:00+00:00'),('checked_at','2026-11-08T00:00:00'),('as_of','2026-11-07')])
def test_identity_and_collection_date_required(key,value):
    p=alphabet_packet();p[key]=value
    assert reviewed_alphabet_q3(p,p['quarter'][-1]) is None


def test_goog_alias_missing_values_and_no_historical_lookahead():
    p=alphabet_packet();p['ticker']='GOOG'
    assert len(comparison(p)['recoveries'])==2
    p['checked_at']='2026-11-07T00:00:00+00:00';p['as_of']='2026-11-07'
    assert reviewed_alphabet_q3(p,p['quarter'][-1]) is None
    for key,value in [('ocf',None),('cash_capex',0),('unit','EUR'),('start','2026-07-02'),
                      ('end','2027-09-30'),('fiscal_year_start','2026-04-01'),('fiscal_quarter',2),
                      ('is_single_quarter',False),('cash_capex_scope','유형·소프트웨어·무형자산')]:
        p=alphabet_packet();row=p['quarter'][-1];row[key]=value
        assert reviewed_alphabet_q3(p,row) is None
    for key in ('ocf','cash_capex','end','provenance','fiscal_year_start'):
        p=alphabet_packet();row=p['quarter'][-1];del row[key]
        assert reviewed_alphabet_q3(p,row) is None


def test_one_revised_quarter_blocks_yoy_but_preserves_other_reviewed_quarter():
    p=alphabet_packet();p['quarter'][0]['provenance']['ocf']['facts'][0]['value']+=1
    r=comparison(p)
    assert r['rows'][0]['영업현금(백만$)']==42290
    assert r['trends'][0]['투자 비율 변화(%p)'] is None
    assert [x['end'] for x in r['recoveries']]==['2026-09-30']


def test_ui_renders_audited_status_and_sources_not_a_hold(monkeypatch):
    import stock_lab_core.bigtech_cash_view as view
    def load(ticker, **kwargs):
        p=alphabet_packet()
        if ticker!='GOOGL': p.update(ticker=ticker,cik='0000789019')
        return p
    monkeypatch.setattr(view,'load_quarter_evidence',load)
    a=AppTest.from_string('''
import streamlit as st
from datetime import datetime,timezone
from stock_lab_core.bigtech_cash_view import render_bigtech_comparison
render_bigtech_comparison(st, options=['MSFT','GOOGL'], prefix='synthetic', configured=True,
resolve_cik=None,fetch_facts=None,now=datetime(2026,11,8,tzinfo=timezone.utc))
''').run()
    assert not a.dataframe
    a.button[0].click().run()
    assert not a.exception
    assert any('2025-09-30, 2026-09-30' in x.value for x in a.caption)
    assert any('실적발표 원문 대조(미감사)' in str(x.value) for x in a.dataframe)
    assert any('googexhibit991q32026.htm' in x.value for x in a.markdown)
    assert not any('GOOGL · 보류 근거' in x.value for x in a.caption)
