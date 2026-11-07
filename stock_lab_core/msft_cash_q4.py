"""Two audited MSFT Q4 observations, NOT a general cross-filing exception.

See docs/maintenance/20261108_msft_q4_recovery.md for the original statements.
The 2026 earnings exhibit directly reports BOTH quarters. Its amounts agree
with the annual/interim cash statements, including the original 2025 release.
Restore only the exact reviewed companyfacts operands; any source/value/status
change requires another review. No network, estimates or scoring mutation.
"""

from datetime import date

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

REVIEWED_ON = '2026-11-08'
RELEASE_ACCESSION = '0001193125-26-323632'
RELEASE_FILED = '2026-07-29'
RELEASE_URL = 'https://www.sec.gov/Archives/edgar/data/789019/000119312526323632/msft-ex99_1.htm'
ANNUAL = ('0001193125-26-323660', '2026-07-29', '10-K')
NINE_MONTH = ('0001193125-26-191507', '2026-04-29', '10-Q')
TAGS = {'ocf': 'NetCashProvidedByUsedInOperatingActivities',
        'cash_capex': 'PaymentsToAcquirePropertyPlantAndEquipment'}
# Original statements use USD millions: (annual, nine months, directly reported Q4).
REVIEWED_MILLIONS = {
    '2025-06-30': {'ocf': (136162, 93515, 42647), 'cash_capex': (64551, 47472, 17079)},
    '2026-06-30': {'ocf': (182935, 127494, 55441), 'cash_capex': (115948, 80146, 35802)},
}


def reviewed_msft_q4(row, cutoff):
    """Report-only fallback; caller already verified MSFT identity/freshness."""
    try:
        end = row['end']
        values = REVIEWED_MILLIONS[end]
        year = int(end[:4])
        if (cutoff < date.fromisoformat(REVIEWED_ON)
                or row['start'] != f'{year}-04-01' or row['fiscal_quarter'] != 4
                or row['unit'] != 'USD' or row['is_single_quarter'] is not True
                or row['cash_capex_scope'] != '유형자산'):
            return None
        amounts = {}
        for field, (annual, nine_month, direct) in values.items():
            evidence = row['provenance'][field]
            if (evidence.get('method') != 'cumulative_difference'
                    or evidence.get('status') != 'cross_filing_difference_review'
                    or annual - nine_month != direct or row[field] != direct * 1_000_000):
                return None
            expected = [dict(start=f'{year-1}-07-01', end=period_end,
                value=value * 1_000_000, tag=TAGS[field], unit='USD',
                accession=filing[0], filed=filing[1], form=filing[2])
                for period_end, value, filing in ((end, annual, ANNUAL),
                    (f'{year}-03-31', nine_month, NINE_MONTH))]
            if evidence.get('facts') != expected:
                return None
            amounts[field] = direct * 1_000_000
        ocf, capex = amounts['ocf'], amounts['cash_capex']
        return dict(start=row['start'], end=end, valid=True, **amounts,
                    residual=ocf-capex, burden_pct=capex/ocf*100,
                    accession=RELEASE_ACCESSION, filed=RELEASE_FILED,
                    source_url=RELEASE_URL, reviewed_on=REVIEWED_ON,
                    recovery='reviewed_direct_q4_release')
    except (KeyError, TypeError, ValueError, IndexError):
        return None
