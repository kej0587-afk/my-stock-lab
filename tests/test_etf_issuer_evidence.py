from copy import deepcopy
from datetime import datetime, timezone

import pytest

from stock_lab_core.etf_holdings import load_etf_holdings, ETFHoldingsCache, _Unavailable
from stock_lab_core.etf_roundhill import parse_roundhill
from stock_lab_core.etf_issuer_evidence import related_issuers, merge_issuer_evidence, collect_issuer_earnings
from stock_lab_core.portfolio_market_review import holding_market_review

NOW = datetime(2026, 11, 4, 7, tzinfo=timezone.utc)
CSV = '''Date,Account,StockTicker,SecurityName,Weightings,MoneyMarketFlag
11/04/2026,DRAM,000660 KS,SK hynix Inc,16.36%,
11/04/2026,DRAM,MU,Micron,25.12%,
11/04/2026,DRAM,000660-TRS,SK hynix SWAP,8.32%,
11/04/2026,DRAM,285A JP,Kioxia,10.00%,
11/04/2026,DRAM,Cash&Other,Cash,-1.0%,Y
11/04/2026,MAGS,MSFT,Microsoft,14.4%,
'''


def snapshot():
    return load_etf_holdings('DRAM', fetch=lambda *a, **k: CSV, now=NOW)


def test_roundhill_filters_fund_preserves_weights_and_unmapped_identifiers():
    value = snapshot()
    assert value['as_of'] == '2026-11-03'
    assert value['status'] == 'ok'
    assert len(value['rows']) == 5
    assert value['rows'][0]['ticker'] == '000660.KS'
    assert value['rows'][0]['weight_pct'] == 16.36
    assert value['rows'][2]['kind'] == 'swap' and not value['rows'][2]['reviewable']
    assert value['rows'][3]['source_ticker'] == '285A JP' and value['rows'][3]['ticker'] is None
    assert value['rows'][4]['weight_pct'] == -1


def test_roundhill_cache_does_not_fetch_on_second_view_and_bound_failures():
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return CSV
    cache = ETFHoldingsCache()
    a = load_etf_holdings('DRAM', fetch=fetch, now=NOW, cache=cache)
    b = load_etf_holdings('DRAM', fetch=fetch, now=NOW, cache=cache)
    assert len(calls) == 1 and b['from_cache']
    b['rows'][0]['weight_pct'] = 0
    assert a['rows'][0]['weight_pct'] == 16.36
    calls.clear()
    def fail(url, **kwargs):
        calls.append(url)
        raise _Unavailable('http_404')
    unavailable = load_etf_holdings('RAM', fetch=fail, now=NOW)
    assert len(calls) == 4 and not unavailable['rows']


@pytest.mark.parametrize('body', ['<html>Error</html>', CSV.replace('11/04/2026,DRAM,MU', '11/03/2026,DRAM,MU')])
def test_malformed_or_mixed_date_not_reported_as_current_holdings(body):
    with pytest.raises(_Unavailable):
        parse_roundhill(body, 'DRAM')


def test_ram_links_underlying_without_multiplying_or_substituting_direct_weights():
    state = {'etf_constituents_DRAM': snapshot()}
    before = deepcopy(state)
    links = related_issuers('RAM', state, NOW)
    assert set(links) == {'RAM', '000660.KS', 'MU'}
    assert '기초 ETF DRAM' in links['MU'][0]
    assert '직접비중 아님' in links['MU'][0]
    assert related_issuers('SOXL', state, NOW) == {'SOXL': ('직접 기업', '')}
    assert state == before


@pytest.mark.parametrize('change', [
    {'as_of': '2026-10-01'}, {'observed_at': '2026-11-03T00:00:00Z'},
    {'as_of': '2026-11-05'}, {'status': 'stale'}, {'holdings_basis': 'historical_reference'},
])
def test_stale_or_unverified_holdings_not_promoted_to_earnings(change):
    value = dict(snapshot(), **change)
    assert set(related_issuers('RAM', {'etf_constituents_DRAM': value}, NOW)) == {'RAM'}


def test_selected_issuer_collection_and_portfolio_join_preserve_scope(monkeypatch):
    from stock_lab_core import earnings_sources, earnings_result_sources
    calls = []
    event = {'ticker': 'MU', 'name': 'Micron', 'date': '2026-11-03', 'event_status': 'released',
             'result_confirmation': 'official_result', 'fiscal_period': 'FY2026Q4',
             'source_url': 'https://example.com/ir',
             'result_metrics': {'revenue': {'status': 'reported', 'text': 'Reported revenue', 'source_url': 'https://example.com/ir'}}}
    def load(tickers, now):
        calls.extend(tickers)
        return {'events': [event], 'sources': [{'ticker':'MU', 'status':'connected'}]}
    monkeypatch.setattr(earnings_sources, 'load_official_earnings', load)
    monkeypatch.setattr(earnings_result_sources, 'load_earnings_results', lambda *a: {'results': [], 'sources': []})
    extra = collect_issuer_earnings('MU', 'Micron', now=NOW)
    assert calls == ['MU']
    state = {'etf_constituents_DRAM': snapshot(), 'etf_issuer_earnings_MU': extra}
    data = {'sessions': {'US':'2026-11-03'}, 'quote_checked_at': NOW.isoformat()}
    before = deepcopy(data)
    review = holding_market_review('RAM', data, state, now=NOW)
    assert any(row['기업'] == 'Micron' for row in review['earnings'])
    assert all('기초 ETF DRAM' in row['연결'] for row in review['earnings'])
    assert not holding_market_review('CIBR', data, state, now=NOW)['earnings']
    assert data == before
    old = deepcopy(extra)
    old['checked_at'] = '2026-11-03T00:00:00Z'
    assert not merge_issuer_evidence(data, {'MU': ('','')}, {'etf_issuer_earnings_MU':old}, NOW)['earnings']


def test_shared_panel_app_test_no_automatic_fetch(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from stock_lab_core import etf_holdings
    calls = []
    def load(ticker, **kwargs):
        calls.append(ticker)
        return snapshot()
    monkeypatch.setattr(etf_holdings, 'load_etf_holdings', load)
    at = AppTest.from_string('''
import streamlit as st
from stock_lab_core.etf_review import render_exposure_review
ticker = st.selectbox('ETF', ['RAM', 'CIBR'])
render_exposure_review(st, ticker, key_prefix='portfolio')
''').run()
    assert not at.exception and calls == []
    assert any('DRAM' in e.label for e in at.expander)
    at.button(key='portfolio_underlying_etf_fetch_DRAM').click().run()
    assert not at.exception and calls == ['DRAM']
    at.selectbox[0].select('CIBR').run()
    assert not at.exception and calls == ['DRAM']
