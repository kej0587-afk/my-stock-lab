"""Period-exact BLS archive metadata; price/decision values remain untouched."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from stock_lab_core import economic_releases as releases
from stock_lab_core.economic_release_metadata import apply_verified_release_metadata
from stock_lab_core.report_reading import _recent_releases

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def observation(**changes):
    row = releases._row('US_PPI', '%', 'MoM', 'BLS', releases.BLS_URL,
                        NOW, period='2026-10')
    row.update(actual=.3, previous=1.4, forecast=None, status='released',
               missing_reason='forecast_not_supplied;release_date_unavailable')
    row.update(changes)
    return row


@pytest.mark.parametrize('basis', ['MoM', 'YoY'])
def test_verified_archive_date_survives_schedule_failure_without_changing_values(basis):
    row = observation(basis=basis)
    before = deepcopy(row)
    spec = next(s for s in releases._BLS_SERIES if s.indicator == 'US_PPI' and s.basis == basis)
    calendar = {'sources': [{'name': 'BLS PPI', 'reason': 'http_403'}], 'events': []}
    releases._link_bls_calendar(row, spec, calendar, NOW)
    assert row['release_at'] == '2026-11-13T08:30:00-05:00'
    assert row['release_metadata_mode'] == 'verified_snapshot'
    assert row['release_source_url'].endswith('/archives/ppi_11132026.htm')
    assert row['missing_reason'] == 'forecast_not_supplied'
    for key in ('actual', 'previous', 'forecast', 'period', 'basis', 'status', 'source'):
        assert row[key] == before[key]


@pytest.mark.parametrize('changes,now', [
    ({'period': '2026-09'}, NOW), ({'period': '2026-11'}, NOW),
    ({'indicator': 'US_CORE_PPI'}, NOW), ({'source': 'unverified'}, NOW),
    ({}, datetime(2026, 11, 13, 12, tzinfo=timezone.utc)),
    ({}, datetime(2026, 12, 15, 0, tzinfo=timezone.utc)),
])
def test_no_guessed_period_future_evidence_or_expired_snapshot(changes, now):
    row = observation(**changes)
    before = deepcopy(row)
    apply_verified_release_metadata(row, now)
    assert row == before


def test_existing_live_release_date_has_precedence():
    row = observation(release_at='2026-11-13T13:30:00+00:00')
    before = deepcopy(row)
    apply_verified_release_metadata(row, NOW)
    assert row == before


def test_main_recent_table_receives_ppi_only_after_verified_metadata():
    row = observation()
    source = ('지표 | 발표치 | 예상 | 이전 | 해석 | 반응\n'
              '--- | --- | --- | --- | --- | ---\n'
              'PPI | 0.3% | 미연결 | 1.4% | 이전 대비 둔화 | 동일일 +5bp')
    context = {'sessions': {'US': '2026-11-13'}, 'economic_releases': [row]}
    assert not _recent_releases({'경제지표': source}, context, NOW)
    apply_verified_release_metadata(row, NOW)
    rendered = '\n'.join(_recent_releases({'경제지표': source}, context, NOW))
    assert '2026-11-13T08:30:00-05:00' in rendered
    assert '0.3% | 미연결 | 1.4%' in rendered and '동일일 +5bp' in rendered
    row['status'] = 'stale'
    assert not _recent_releases({'경제지표': source}, context, NOW)
