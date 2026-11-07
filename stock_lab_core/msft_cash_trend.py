"""Pure SEC cash-burden evidence, independent of investment scores and gates."""

from datetime import date, datetime, timedelta
import math
import re
from zoneinfo import ZoneInfo

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.msft_cash_q4 import reviewed_msft_q4

register_loaded_source(__name__, __file__)

CIK = '0000789019'
SOURCE_URL = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json'
TAGS = {'ocf': 'NetCashProvidedByUsedInOperatingActivities',
        'cash_capex': 'PaymentsToAcquirePropertyPlantAndEquipment'}


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def usable_cash_packet(packet, now):
    try:
        checked = datetime.fromisoformat(packet['checked_at'])
        basis = date.fromisoformat(packet['as_of'])
        return (now.tzinfo is not None and checked.tzinfo is not None
                and timedelta(0) <= now - checked <= timedelta(days=1)
                and basis == checked.astimezone(ZoneInfo('Asia/Seoul')).date()
                and packet.get('ticker') == 'MSFT' and packet.get('cik') == CIK
                and packet.get('currency') == 'USD' and packet.get('source_url') == SOURCE_URL
                and packet.get('review_only') is True and packet.get('eligible_for_scoring') is False
                and packet.get('status') == 'quarter_evidence_only'
                and isinstance(packet.get('quarter'), list) and 0 < len(packet['quarter']) <= 8)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _period(row, cutoff):
    start, end = date.fromisoformat(row['start']), date.fromisoformat(row['end'])
    following = date(end.year + 1, 1, 1) if end.month == 12 else date(end.year, end.month + 1, 1)
    if (end.month not in (3, 6, 9, 12) or end != following - timedelta(days=1)
            or start != date(end.year, end.month - 2, 1) or end > cutoff
            or row.get('fiscal_quarter') != {9: 1, 12: 2, 3: 3, 6: 4}[end.month]
            or row.get('unit') != 'USD' or row.get('is_single_quarter') is not True):
        raise ValueError('period_or_currency')
    return start, end


def _field(row, field, start, end, cutoff):
    evidence = row['provenance'][field]
    if evidence.get('status') or not _finite(row.get(field)):
        raise ValueError('missing_or_revision')
    facts = evidence['facts']
    method = evidence.get('method')
    if not ((method == 'reported' and len(facts) == 1)
            or (method == 'cumulative_difference' and len(facts) == 2)):
        raise ValueError('calculation_method')
    for fact in facts:
        if (fact.get('tag') != TAGS[field] or fact.get('unit') != 'USD'
                or fact.get('form') not in {'10-Q', '10-Q/A', '10-K', '10-K/A'}
                or not _finite(fact.get('value'))
                or not date.fromisoformat(fact['end']) <= date.fromisoformat(fact['filed']) <= cutoff
                or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', fact.get('accession', ''))):
            raise ValueError('unverified_fact')
    if method == 'reported':
        if (facts[0]['start'], facts[0]['end']) != (start.isoformat(), end.isoformat()):
            raise ValueError('fact_period')
        value = facts[0]['value']
    else:
        a, b = facts
        if (a['end'] != end.isoformat() or b['end'] != (start - timedelta(days=1)).isoformat()
                or a['start'] != b['start'] or date.fromisoformat(a['start']) >= start
                or (a['accession'], a['filed']) != (b['accession'], b['filed'])):
            raise ValueError('cross_filing_difference')
        value = a['value'] - b['value']
    if not math.isclose(row[field], value, rel_tol=1e-10, abs_tol=1e-6):
        raise ValueError('value_provenance_mismatch')
    signature = tuple((f['start'], f['end'], f['accession'], f['filed'], f['unit']) for f in facts)
    return value, signature


def _quarter(row, cutoff):
    start, end = _period(row, cutoff)
    result = dict(start=start.isoformat(), end=end.isoformat(), valid=False,
                  ocf=None, cash_capex=None, residual=None, burden_pct=None, source_url='')
    try:
        if row.get('cash_capex_scope') != '유형자산':
            raise ValueError('investment_scope')
        ocf, ocf_basis = _field(row, 'ocf', start, end, cutoff)
        capex, capex_basis = _field(row, 'cash_capex', start, end, cutoff)
        if capex < 0 or ocf_basis != capex_basis:
            raise ValueError('mixed_basis')
        accession, filed = ocf_basis[0][2:4]
        result.update(valid=True, ocf=ocf, cash_capex=capex, residual=ocf-capex,
            burden_pct=capex / ocf * 100 if ocf > 0 else None,
            accession=accession, filed=filed,
            source_url=f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace('-', '')}/{accession}-index.html")
    except (KeyError, TypeError, ValueError, IndexError):
        restored = reviewed_msft_q4(row, cutoff)
        if restored is not None:
            return restored
        result['reason'] = '누락·제출본·기간/정의 확인 전 보류'
    return result


def _compare(current, previous):
    # Same filing's comparative cash-flow statements, not old/new filing splices.
    if (not current['valid'] or not previous['valid']
            or (current['accession'], current['filed']) != (previous['accession'], previous['filed'])
            or current['burden_pct'] is None or previous['burden_pct'] is None):
        return None
    return dict(current_end=current['end'], previous_end=previous['end'],
        burden_delta_pp=current['burden_pct']-previous['burden_pct'],
        current_burden=current['burden_pct'], previous_burden=previous['burden_pct'],
        ocf_growth_pct=(current['ocf']/previous['ocf']-1)*100,
        capex_growth_pct=(current['cash_capex']/previous['cash_capex']-1)*100 if previous['cash_capex'] > 0 else None,
        residual_delta=current['residual']-previous['residual'], source_url=current['source_url'])


def build_msft_cash_trend(packet, now):
    if not usable_cash_packet(packet, now):
        return dict(status='unavailable', rows=[], comparisons=[], latest_comparison=None)
    try:
        rows = sorted((_quarter(row, date.fromisoformat(packet['as_of'])) for row in packet['quarter']), key=lambda r: r['end'])
        if len({r['end'] for r in rows}) != len(rows):
            raise ValueError('duplicate_quarter')
        comparisons = []
        for current in rows:
            end = date.fromisoformat(current['end'])
            previous = next((r for r in rows if r['end'] == end.replace(year=end.year-1).isoformat()), None)
            comparison = _compare(current, previous) if previous else None
            if comparison:
                comparisons.append(comparison)
        latest = rows[-1]
        recent = (now.astimezone(ZoneInfo('Asia/Seoul')).date() - date.fromisoformat(latest['end'])).days <= 150
        latest_comparison = next((r for r in comparisons if r['current_end'] == latest['end']), None) if recent else None
        return dict(status='connected' if recent else 'old_period', rows=rows, comparisons=comparisons,
            latest_comparison=latest_comparison, checked_at=packet['checked_at'],
            gaps=any(date.fromisoformat(a['end'])+timedelta(days=1)!=date.fromisoformat(b['start']) for a,b in zip(rows,rows[1:])),
            held_count=sum(not r['valid'] for r in rows))
    except (KeyError, TypeError, ValueError, IndexError):
        return dict(status='unavailable', rows=[], comparisons=[], latest_comparison=None)
