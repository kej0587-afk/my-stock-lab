"""Offline contracts for explicit missing baselines and preliminary export data."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from stock_lab_core import economic_releases as r, economic_cache as cache
from stock_lab_core import economic_exports_preliminary as p
from stock_lab_core.economic_release_metadata import apply_verified_release_metadata

NOW = datetime(2026, 11, 13, 5, tzinfo=timezone.utc)
LISTING = '<a href="/kor/article/ATCL3f49a5a8c/123/view?pageIndex=1">2026년 10월 수출입 동향</a>'
DETAIL = '''<div class="detail-tit">2026년 10월 수출입 동향</div>
<div class="detail-info"><li><em>등록일</em><span>2026-11-01</span></li></div>
<div class="detail-cont">1~10월 누적 수출 +60.6%, 반도체 +259%.
【총괄】 ‘26.10월 수출은 전년 동월 대비 93.7% 증가한 1,152.8억 달러,
수입은 36.0% 증가한 727.8억 달러</div>'''


@pytest.fixture(autouse=True)
def clean_cache():
    r.clear_economic_releases_cache()
    yield
    r.clear_economic_releases_cache()


def test_bls_explicit_missing_is_not_previous_month_fallback(monkeypatch):
    values = {'2026-10': 110, '2026-09': 109, '2025-10': '-', '2025-09': 100}
    payload = {'status': 'REQUEST_SUCCEEDED', 'Results': {'series': [
        {'seriesID': spec.series, 'data': [{'year': month[:4], 'period': 'M' + month[5:], 'value': str(value)}
                                         for month, value in values.items()]} for spec in r._BLS_SERIES]}}
    monkeypatch.setattr(r, '_request', lambda *args, **kw: payload)
    row = next(x for x in r._bls(NOW) if x['indicator'] == 'US_CPI' and x['basis'] == 'YoY')
    old = dict(row, actual=9., period='2026-09', status='released', official_comparison_unavailable=False)
    cache.retain_successful_observations([old], NOW)
    result = cache.retain_successful_observations([row], NOW)[0]
    assert result['period'] == '2026-10' and result['actual'] is None
    assert result['comparison_period'] == '2025-10'
    assert '공식 비교 기준값 미제공' in cache.collection_status(result)
    failure = dict(row, official_comparison_unavailable=False, missing_reason='http_503')
    assert cache.retain_successful_observations([failure], NOW)[0]['actual'] == 9.


@pytest.mark.parametrize('period,now,expected', [
    ('2026-10', NOW, True), ('2026-09', NOW, False),
    ('2026-10', datetime(2026, 11, 9, tzinfo=timezone.utc), False),
    ('2026-10', datetime(2026, 12, 13, tzinfo=timezone.utc), False)])
def test_release_metadata_period_and_expiry(period, now, expected):
    row = r._row('US_CPI', '%', 'YoY', 'BLS', r.BLS_URL, now, period=period)
    apply_verified_release_metadata(row, now)
    assert bool(row['release_at']) == expected
    assert row['actual'] is None
    if expected:
        assert row['release_at'] == '2026-11-10T08:30:00-05:00'
        row['release_at'] = '2026-11-10T13:31:00+00:00'
        apply_verified_release_metadata(row, now)
        assert row['release_at'].endswith('13:31:00+00:00')


def test_ministry_strict_month_total_and_date():
    period, url = p.parse_listing(LISTING + '<a href="https://evil.test/x">2026년 11월 수출입 동향</a>', NOW)
    assert period == '2026-10' and url.endswith('/123/view')
    row = p.parse_detail(DETAIL, period, NOW)
    assert row['actual'] == 93.7 and row['raw_actual'] == 1152.8
    assert 'raw_year_ago' not in row
    assert p.parse_detail(DETAIL.replace('93.7% 증가', '9.7% 감소'), period, NOW)['actual'] == -9.7


@pytest.mark.parametrize('old,new', [('2026년 10월', '2026년 9월'),
    ('2026-11-01', '2026-12-01'), ('총괄', '누계'), ('수출은 전년', '수입은 전년'),
    ('93.7% 증가', '193.7% 감소')])
def test_ministry_rejects_ambiguous_or_invalid_detail(old, new):
    with pytest.raises(ValueError):
        p.parse_detail(DETAIL.replace(old, new), '2026-10', NOW)


def fake_ministry(monkeypatch):
    calls = []
    def request(url, **kwargs):
        calls.append(url)
        kwargs['diagnostics'].update(http_status=200, attempted=True)
        return LISTING if url == p.LIST_URL else DETAIL
    monkeypatch.setattr(r, '_request', request)
    return calls


def test_preliminary_collection_cache_and_final_priority(monkeypatch):
    calls = fake_ministry(monkeypatch)
    first = p.load_preliminary_exports(NOW)
    assert first['actual'] == 93.7 and first['data_vintage'] == 'preliminary_bulletin'
    assert p.load_preliminary_exports(NOW)['actual'] == 93.7 and len(calls) == 2
    old = r._row('KR_EXPORTS', '%', 'YoY', 'Bank of Korea ECOS', '', NOW,
                 period='2026-09', actual=83.7, official_bulletin_fetch=True,
                 forecast=90., reaction='old reaction')
    rows = [old]
    p.apply_preliminary_exports(rows, NOW)
    assert rows[0]['period'] == '2026-10' and rows[0]['forecast'] is None
    assert rows[0].get('reaction') is None and rows[0]['previous'] is None
    final = dict(first, source='Korea Customs Service (monthly final bulletin)',
                 data_vintage='final_bulletin', actual=93.6)
    expected = deepcopy(final)
    p.apply_preliminary_exports([final], NOW)
    assert final == expected


def test_preliminary_failure_retains_success_without_overwriting_customs_cache(monkeypatch):
    fake_ministry(monkeypatch)
    first = p.load_preliminary_exports(NOW)
    cache.retain_successful_observations([first], NOW)
    r.clear_economic_releases_cache()
    def fail(*args, **kwargs):
        raise r._Unavailable('http_503')
    monkeypatch.setattr(r, '_request', fail)
    failed = cache.retain_successful_observations([p.load_preliminary_exports(NOW)], NOW)[0]
    assert failed['actual'] == 93.7 and failed['status'] == 'stale'
    assert cache._key(failed) != cache._key(dict(first, series_id='customs/monthly_final'))


def test_full_bulletin_pipeline_upgrades_only_exports(monkeypatch):
    from stock_lab_core import economic_bulletins as b
    fake_ministry(monkeypatch)
    monkeypatch.setattr(b, '_apply_live_exports', lambda rows, now: None)
    monkeypatch.setattr(b, '_apply_live_cpi', lambda rows, now: None)
    old = r._row('KR_EXPORTS', '%', 'YoY', 'Bank of Korea ECOS', '', NOW,
                 period='2026-09', actual=83.7, official_bulletin_fetch=True)
    other = r._row('KR_CPI', '%', 'YoY', 'Bank of Korea ECOS', '', NOW, actual=3., period='2026-10')
    rows = b.apply_official_bulletins([old, other], NOW)
    assert rows[0]['period'] == '2026-10' and rows[0]['actual'] == 93.7
    assert rows[1] == other and old['period'] == '2026-09'


def test_production_report_has_no_fake_rate_or_final_export_claim(monkeypatch):
    from stock_lab_core.report_evidence import report_sections
    fake_ministry(monkeypatch)
    cpi = r._row('US_CPI', '%', 'YoY', 'BLS', r.BLS_URL, NOW, period='2026-10',
                 official_comparison_unavailable=True, comparison_period='2025-10')
    apply_verified_release_metadata(cpi, NOW)
    lines, _ = report_sections(context={'economic_releases': [cpi, p.load_preliminary_exports(NOW)]},
                              news=[], flow_rows=[], event_rows=[], summary_rows=[], now=NOW)
    output = '\n'.join(lines)
    assert '2026-11-10 22:30 KST' in output
    assert '공식 비교 기준값 미제공(2025-10)' in output
    assert '93.7% · 공식 잠정치' in output
    assert '수출 원자료 검산:' not in output
    assert '발표 여부 미확인' not in output
