"""Two original-statement reconciliations, not a generic cross-filing exception.

The 2026 Q3 earnings exhibit directly reports BOTH 2025/2026 cash quarters.
Each equals the nine-month less six-month cash statements; the 2025 original
release independently agrees. See docs/maintenance/20261108_alphabet_cash_q3.md.
Only the exact reviewed operands are eligible. The source packet stays intact.
No fetch, interpolation, score changes or recovery of other fiscal quarters.
"""
from datetime import date, datetime, timedelta, timezone

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

CIK = '0001652044'
FACTS_URL = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json'
REVIEWED_ON = '2026-11-08'
RELEASE_ACCESSION = '0001652044-26-000080'
RELEASE_FILED = '2026-10-28'
RELEASE_URL = 'https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm'
PRIOR_RELEASE_URL = 'https://www.sec.gov/Archives/edgar/data/1652044/000165204425000087/googexhibit991q32025.htm'
NINE_MONTH = ('0001652044-26-000084', '2026-10-29', '10-Q')
SIX_MONTH = ('0001652044-26-000071', '2026-07-23', '10-Q')
TAGS = {'ocf': 'NetCashProvidedByUsedInOperatingActivities',
        'cash_capex': 'PaymentsToAcquirePropertyPlantAndEquipment'}
# USD millions: (nine months, six months, directly reported quarter).
REVIEWED_MILLIONS = {
    '2025-09-30': {'ocf': (112311, 63897, 48414), 'cash_capex': (63596, 39643, 23953)},
    '2026-09-30': {'ocf': (127149, 84859, 42290), 'cash_capex': (131953, 80598, 51355)},
}


def reviewed_alphabet_q3(packet, row):
    """Report-only fallback after exact issuer, period, status and operand checks.

The caller owns the six-hour UI freshness guard. Here the collection date must
match the as-of date and must not precede the review (no historical lookahead).
Any revised filing, value, scope or guard status is withheld for a new review.
"""
    try:
        cutoff = date.fromisoformat(packet['as_of'])
        checked = datetime.fromisoformat(packet['checked_at'])
        if (packet.get('ticker') not in {'GOOG', 'GOOGL'} or packet.get('cik') != CIK
                or packet.get('source_url') != FACTS_URL or packet.get('currency') != 'USD'
                or packet.get('review_only') is not True or packet.get('eligible_for_scoring') is not False
                or packet.get('status') != 'quarter_evidence_only'
                or checked.tzinfo is None
                or checked.astimezone(timezone(timedelta(hours=9))).date() != cutoff
                or cutoff < date.fromisoformat(REVIEWED_ON)):
            return None
        end = row['end']
        values = REVIEWED_MILLIONS[end]
        year = int(end[:4])
        if (row['start'] != f'{year}-07-01' or row['fiscal_year_start'] != f'{year}-01-01'
                or row['fiscal_quarter'] != 3 or row['unit'] != 'USD'
                or row['is_single_quarter'] is not True or row['cash_capex_scope'] != '유형자산'):
            return None
        amounts, reconciliation = {}, []
        for field, (nine_month, six_month, direct) in values.items():
            evidence = row['provenance'][field]
            if (evidence.get('method') != 'cumulative_difference'
                    or evidence.get('status') != 'cross_filing_difference_review'
                    or nine_month - six_month != direct or row[field] != direct * 1_000_000):
                return None
            expected = [dict(start=f'{year}-01-01', end=period_end, value=value * 1_000_000,
                tag=TAGS[field], unit='USD', accession=filing[0], filed=filing[1], form=filing[2])
                for period_end, value, filing in ((end, nine_month, NINE_MONTH),
                                                (f'{year}-06-30', six_month, SIX_MONTH))]
            if evidence.get('facts') != expected:
                return None
            amounts[field] = direct * 1_000_000
            reconciliation.append(dict(field=field, nine_month=nine_month * 1_000_000,
                six_month=six_month * 1_000_000, direct_quarter=amounts[field]))
        return dict(ticker=packet['ticker'], start=row['start'], end=end, **amounts,
            accession=RELEASE_ACCESSION, filed=RELEASE_FILED, source_url=RELEASE_URL,
            prior_source_url=PRIOR_RELEASE_URL, reviewed_on=REVIEWED_ON, unaudited=True,
            recovery='reviewed_direct_alphabet_q3_release', reconciliation=reconciliation)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return None
