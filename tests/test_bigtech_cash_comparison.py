from copy import deepcopy
import json
import socket

import pytest
from streamlit.testing.v1 import AppTest
from tests.test_company_cash_reading import packet, set_value
from stock_lab_core.bigtech_cash_comparison import compare_bigtech_cash, comparison_options
from stock_lab_core.bigtech_cash_view import _display_rows


def comparable(ticker='MSFT', productive=False):
    p = packet(ticker, productive=productive)
    prior = deepcopy(p['quarter'][-1])
    for field in ('start', 'end', 'fiscal_year_start'):
        if prior.get(field):
            prior[field] = prior[field].replace('2026', '2025')
    for evidence in prior['provenance'].values():
        for fact in evidence.get('facts', []):
            for field in ('start', 'end'):
                if fact.get(field):
                    fact[field] = fact[field].replace('2026', '2025')
    p['quarter'].insert(0, prior)
    set_value(p, 'cash_capex', 24e6)
    return p


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('unexpected network'))


def test_same_calendar_dates_different_fiscal_quarters_and_scopes():
    p = dict(MSFT=comparable(), AMZN=comparable('AMZN', True))
    p['MSFT']['quarter'][-1]['fiscal_quarter'] = 4
    before = deepcopy(p)
    result = compare_bigtech_cash(p)
    assert p == before
    assert result['period'] == '2026-04-01 ~ 2026-06-30'
    assert result['previous_period'] == '2025-04-01 ~ 2025-06-30'
    assert all(r['투자 비율 변화(%p)'] == 40 for r in result['trends'])
    assert all(r['현금 투자 YoY(%)'] == 100 for r in result['trends'])
    assert '합계' in result['scope_note'] and '서버·설비 몫' in result['readings'][0]['해석(추정)']
    assert result['status'] == 'compared'


@pytest.mark.parametrize('fault', ['cross_filing', 'tampered', 'currency', 'future', 'identity', 'duplicate'])
def test_bad_evidence_is_not_replaced_by_older_complete_values(fault):
    p = dict(MSFT=comparable(), AMZN=comparable('AMZN'))
    r = p['AMZN']['quarter'][-1]
    if fault == 'cross_filing': r['provenance']['ocf']['status'] = 'cross_filing_difference_review'
    if fault == 'tampered': r['ocf'] *= 2
    if fault == 'currency': r['unit'] = 'KRW'
    if fault == 'future': p['AMZN']['as_of'] = '2026-05-01'
    if fault == 'identity': p['AMZN']['ticker'] = 'META'
    if fault == 'duplicate': p['AMZN']['quarter'].append(deepcopy(r))
    result = compare_bigtech_cash(p)
    if fault in ('cross_filing', 'tampered'):
        assert result['period'].endswith('2026-06-30')
        assert result['rows'][1]['투자/영업현금(%)'] is None
        assert result['trends'][1]['투자 비율 변화(%p)'] is None
    else:
        assert result['status'] == 'held' and not result['rows']


@pytest.mark.parametrize('ocf', [0, -10e6])
def test_nonpositive_cash_has_no_burden_ratio(ocf):
    p = dict(MSFT=comparable(), AMZN=comparable('AMZN'))
    set_value(p['AMZN'], 'ocf', ocf)
    r = compare_bigtech_cash(p)
    assert r['rows'][1]['투자/영업현금(%)'] is None
    assert r['rows'][1]['단순차액(백만$)'] == ocf/1e6 - 24
    assert '현금 고갈을 뜻하지' in r['readings'][1]['해석(추정)']


def test_latest_common_coverage_not_latest_individual_and_missing_yoy():
    p = dict(MSFT=comparable(), AMZN=comparable('AMZN'))
    p['AMZN']['quarter'].pop()
    r = compare_bigtech_cash(p)
    assert r['period'] == '2026-01-01 ~ 2026-03-31'
    assert r['coverage'][0]['최근 관측 분기'] == '2026-06-30'
    assert all(x['투자 비율 변화(%p)'] is None for x in r['trends'])


def test_universe_dedup_and_failed_selected_company():
    assert comparison_options(['MSFT','GOOG','GOOGL','NVDA','AMZN']) == ['MSFT','AMZN','GOOGL']
    assert not compare_bigtech_cash(dict(MSFT=comparable(), AMZN={}))['rows']
    assert not compare_bigtech_cash(dict(GOOG=comparable('GOOG'), GOOGL=comparable('GOOGL')))['rows']


def test_display_formats_holds_without_changing_numeric_audit():
    rows = [{'현금': None, '금액': 12345.1, '확인 상태': 'ocf: cross filing'}]
    assert _display_rows(rows) == [{'현금': '보류', '금액': '12,345.1', '확인 상태': '공시 대조 필요'}]
    assert rows[0]['현금'] is None and rows[0]['금액'] == 12345.1


def test_changed_scope_blocks_yoy_and_never_uses_cached_derived_values():
    p = dict(MSFT=comparable(), AMZN=comparable('AMZN'))
    p['AMZN']['quarter'][0] = comparable('AMZN', True)['quarter'][0]
    p['MSFT']['quarter'][-1].update(fcf_cash=123e12, yoy_pct={'cash_capex':999})
    r = compare_bigtech_cash(p)
    assert r['rows'][0]['단순차액(백만$)'] == 6
    assert r['trends'][0]['현금 투자 YoY(%)'] == 100
    assert r['trends'][1]['현금 투자 YoY(%)'] is None


def test_different_yoy_filing_needs_reconciliation():
    p = dict(MSFT=comparable(), AMZN=comparable('AMZN'))
    for field in ('ocf', 'cash_capex'):
        p['AMZN']['quarter'][0]['provenance'][field]['facts'][0]['accession'] = '0000000123-25-000002'
    result = compare_bigtech_cash(p)
    assert result['rows'][1]['투자/영업현금(%)'] == 80
    assert result['trends'][1]['투자 비율 변화(%p)'] is None


def test_rising_ratio_with_falling_investment_is_not_expansion():
    p = dict(MSFT=comparable(), AMZN=comparable('AMZN'))
    set_value(p['AMZN'], 'ocf', 15e6)
    set_value(p['AMZN'], 'cash_capex', 10e6)
    reading = compare_bigtech_cash(p)['readings'][1]
    assert '현금 투자는 줄었' in reading['해석(추정)']
    assert '영업현금 감소' in reading['해석(추정)']
    assert '투자 확대' not in reading['해석(추정)']


SCRIPT = '''
import streamlit as st
from datetime import datetime, timezone, timedelta
from tests.test_company_deep_dive import SCRIPT
exec(SCRIPT.replace("('AMZN','NVDA','GOOGL','005930.KS')", "('AMZN','MSFT','GOOGL')").replace(
"datetime(2026,11,8,tzinfo=timezone.utc)", "datetime(2026,11,8,tzinfo=timezone.utc)+timedelta(hours=st.session_state.get('hours',0))"))
'''


def test_ui_explicit_query_rerender_selection_owner_expiry_and_failed_refresh():
    a = AppTest.from_string(SCRIPT).run()
    a.radio[0].set_value('빅테크 같은 기간 비교').run()
    assert a.session_state.calls == [] and not a.exception
    a.button[0].click().run()
    assert sorted(a.session_state.calls) == ['AMZN','GOOGL','MSFT'] and a.dataframe
    a.run()
    assert len(a.session_state.calls) == 3
    a.multiselect[0].set_value(['AMZN','MSFT']).run()
    assert not a.dataframe and len(a.session_state.calls) == 3
    a.button[0].click().run()
    assert a.dataframe
    a.session_state['hours'] = 7; a.run()
    assert not a.dataframe and any('6시간' in i.value for i in a.info)
    a.session_state['hours'] = 0
    a.session_state['fail'] = True
    a.button[0].click().run()
    assert not a.exception
    assert not any('같은 기간 현금 비교' in x.value for x in a.markdown)
    assert 'secret-provider-response' not in str(a)
    a.session_state['owner'] = 'b'; a.run()
    assert a.radio[0].value == '개별기업' and not a.dataframe
