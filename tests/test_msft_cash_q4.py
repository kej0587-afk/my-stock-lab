"""Original SEC cash statement facts, and adversarial source-pin changes."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from stock_lab_core.msft_cash_trend import build_msft_cash_trend
from stock_lab_core.msft_cash_q4 import reviewed_msft_q4, RELEASE_URL
from tests.test_msft_cash_trend import NOW, packet, text


def reviewed_rows():
    return json.loads(Path('tests/fixtures/msft_reviewed_q4.json').read_text(encoding='utf-8'))


def evidence_packet():
    p = packet()
    for row in reviewed_rows():
        p['quarter'][2 if row['end'] == '2025-06-30' else 6] = row
    return p


def test_original_statements_restore_only_reviewed_rows_and_same_release_yoy():
    p = evidence_packet(); before = deepcopy(p)
    trend = build_msft_cash_trend(p, NOW)
    assert p == before and trend['held_count'] == 0 and len(trend['comparisons']) == 4
    for index, ocf, capex, residual in [(2, 42647e6, 17079e6, 25568e6), (6, 55441e6, 35802e6, 19639e6)]:
        r = trend['rows'][index]
        assert (r['ocf'], r['cash_capex'], r['residual']) == (ocf, capex, residual)
        assert r['burden_pct'] == pytest.approx(capex/ocf*100)
        assert r['source_url'] == RELEASE_URL and r['recovery'] == 'reviewed_direct_q4_release'
    assert trend['rows'][2]['accession'] == trend['rows'][6]['accession']
    # Existing six quarters and three comparisons are byte-for-byte unchanged.
    baseline = build_msft_cash_trend(packet(), NOW)
    assert [r for r in trend['rows'] if not r.get('recovery')] == [r for i,r in enumerate(baseline['rows']) if i not in (2,6)]
    assert [c for c in trend['comparisons'] if c['current_end'] != '2026-06-30'] == [c for c in baseline['comparisons'] if c['current_end'] != '2026-06-30']
    assert trend['latest_comparison'] == baseline['latest_comparison']
    s = text(p)
    assert '검증 보류 0분기' in s and '원문 대조 복구 2분기' in s and '미감사' in s
    assert '426.5 | 170.8 | 40.0% | 255.7' in s
    assert '554.4 | 358.0 | 64.6% | 196.4' in s


@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('field', ['ocf', 'cash_capex'])
@pytest.mark.parametrize('key,value', [('accession','0001193125-26-999999'),
    ('filed','2026-11-01'), ('start','2024-07-02'), ('end','2026-03-30'),
    ('form','10-K/A'), ('tag','PaymentsToAcquireProductiveAssets'), ('unit','EUR'), ('value',0)])
def test_changed_operands_never_bypass_the_generic_guard(index, field, key, value):
    p = evidence_packet(); r = p['quarter'][6]
    r['provenance'][field]['facts'][index][key] = value
    assert not build_msft_cash_trend(p, NOW)['rows'][6]['valid']


@pytest.mark.parametrize('field', ['ocf', 'cash_capex'])
@pytest.mark.parametrize('status', ['later_revision_in_subtrahend', 'direct_cumulative_conflict', '', None])
def test_other_statuses_cannot_be_rescued(field, status):
    p = evidence_packet(); p['quarter'][6]['provenance'][field]['status'] = status
    assert not build_msft_cash_trend(p, NOW)['rows'][6]['valid']


def test_missing_fields_values_other_quarters_scopes_and_lookahead_stay_withheld():
    row = reviewed_rows()[0]
    assert reviewed_msft_q4(row, date(2026,11,7)) is None
    for key,value in [('ocf',None),('cash_capex',0),('cash_capex_scope','유형·소프트웨어·무형자산'),
                      ('end','2027-06-30'),('start','2025-04-02'),('unit','EUR'),
                      ('fiscal_quarter',3),('is_single_quarter',False)]:
        r=deepcopy(row);r[key]=value
        assert reviewed_msft_q4(r,NOW.date()) is None
    for key in row:
        r=deepcopy(row);del r[key]
        assert reviewed_msft_q4(r,NOW.date()) is None


@pytest.mark.parametrize('key,value', [('ticker','AMZN'),('cik','0001018724'),
    ('source_url','https://example.com/facts'),('currency','EUR'),('eligible_for_scoring',True)])
def test_packet_identity_guard_precedes_recovery(key,value):
    p=evidence_packet();p[key]=value
    assert build_msft_cash_trend(p,NOW)['rows'] == []


def test_old_packet_or_query_failure_cannot_restore_historical_values():
    p=evidence_packet();p['checked_at']=(NOW-timedelta(days=2)).isoformat()
    assert build_msft_cash_trend(p,NOW)['rows'] == []
    assert build_msft_cash_trend(None,NOW)['rows'] == []
