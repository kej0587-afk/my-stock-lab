"""Frozen pre-change collector parity, using official-response fixtures offline."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import subprocess
from threading import Event, get_ident
from types import ModuleType

import pytest
import requests

from stock_lab_core import economic_bulletins as b, economic_cache, economic_releases as r
from stock_lab_core.performance import PerformanceTrace
from tests.test_economic_release_live_sources import LISTING, DETAIL, Response
from tests.test_economic_v9 import NOW, public_cpi


@pytest.fixture(scope='module')
def original():
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(['git', 'show', '44e5ba9f:stock_lab_core/economic_bulletins.py'], cwd=root, encoding='utf-8')
    module = ModuleType('bulletin_frozen_original')
    module.__file__ = b.__file__
    exec(compile(source, b.__file__, 'exec'), module.__dict__)
    return module


def inputs(mode):
    rows = [r._ecos(NOW, '', indicator) for indicator in ('KR_CPI', 'KR_EXPORTS')]
    if mode in ('pending', 'unflagged', 'supplied', 'wrong_basis', 'complete'):
        for row in rows:
            if mode == 'pending': row['status'] = 'pending'
            if mode == 'unflagged': row['official_bulletin_fetch'] = False
            if mode == 'supplied': row['value_kind'] = 'supplied_event'
            if mode == 'wrong_basis': row['basis'] = 'MoM'
            if mode == 'complete': row.update(status='released', actual=3., period='2026-09', previous=2., previous3mean=2.)
    if mode == 'duplicates': rows += deepcopy(rows)
    if mode == 'only_cpi': rows = rows[:1]
    if mode == 'only_exports': rows = rows[1:]
    if mode == 'newer':
        for row in rows: row.update(actual=3., period='2026-10', status='stale')
    if mode == 'same_period':
        for row in rows: row.update(actual=3., period='2026-09', status='stale', value_kind='ecos_observation')
    if mode == 'sourced_date':
        rows[0].update(period='2026-09', release_at='2026-10-02', release_precision='date',
                       release_source='Official fixture', release_source_url='https://example.org/release')
    return rows


@pytest.mark.parametrize('mode', ['cold', 'warm', 'pending', 'unflagged', 'supplied', 'wrong_basis',
                                'complete', 'duplicates', 'only_cpi', 'only_exports', 'newer',
                                'same_period', 'sourced_date', 'http_failure', 'cpi_reject',
                                'cooldown', 'expired_manual', 'restored_success'])
def test_full_output_requests_cache_and_persistence_equal_original(original, monkeypatch, tmp_path, mode):
    public = public_cpi.__wrapped__(monkeypatch)
    cpi_get = r.requests.get
    calls, failing = [], [False]
    monkeypatch.setattr(b.time, 'monotonic', lambda: 100.)

    def get(url, **kwargs):
        calls.append((url, str(kwargs.get('params')), str(kwargs['timeout'])))
        if failing[0] and (mode == 'http_failure' or mode == 'restored_success'):
            return Response(status=503)
        if url.startswith(r.ECOS_URL):
            public['reject'] = mode == 'cpi_reject'
            return cpi_get(url, **kwargs)
        if url == b.CUSTOMS_LIST_URL:
            return Response(text=LISTING)
        assert url == b.CUSTOMS_DETAIL_URL
        assert kwargs['timeout'] == (2., 4.) and kwargs['allow_redirects'] is False
        if mode in ('cooldown', 'expired_manual'):
            raise requests.ConnectTimeout('private-payload')
        return Response(text=DETAIL)

    monkeypatch.setattr(r.requests, 'get', get)
    monkeypatch.setattr(r.requests, 'post', lambda *a, **k: pytest.fail('unexpected POST'))
    rows = inputs(mode)
    saved_input = deepcopy(rows)
    now = NOW.replace(month=11, day=3) if mode == 'expired_manual' else NOW

    def run(module, filename):
        r.clear_economic_releases_cache()
        b.clear_customs_bulletin_failures()
        original.clear_customs_bulletin_failures()
        calls.clear()
        path = tmp_path / filename
        monkeypatch.setattr(economic_cache, 'CACHE_PATH', path)
        failing[0] = False
        if mode in ('warm', 'cooldown', 'restored_success'):
            module.apply_official_bulletins(rows, now)
            calls.clear()
        if mode == 'restored_success': r.clear_economic_releases_cache()
        failing[0] = True
        with PerformanceTrace() as trace:
            result = module.apply_official_bulletins(rows, now)
        return result, Counter(calls), path.read_bytes() if path.exists() else None, trace.report()

    expected, old_calls, old_file, _ = run(original, 'old.json')
    actual, new_calls, new_file, trace = run(b, 'new.json')
    assert actual == expected
    assert new_calls == old_calls
    assert new_file == old_file
    assert rows == saved_input
    if mode in ('cold', 'warm', 'http_failure', 'cooldown', 'restored_success'):
        assert trace['transport_events']['bulletin_prefetch.exports.started'] == 1
    if mode == 'warm':
        assert not new_calls
        assert trace['transport_events']['bulletin_cache.cpi.reuse'] == 1
        assert trace['transport_events']['bulletin_cache.exports.reuse'] == 1
    if mode == 'duplicates':
        assert trace['transport_events']['bulletin_prefetch.serial'] == 1
    assert len(r._CACHE) <= r._CACHE_LIMIT


def test_overlap_with_owner_thread_application_and_propagated_trace(monkeypatch):
    started, finish = Event(), Event()
    owner, apply_order = get_ident(), []
    rows = inputs('cold')

    def exports(now):
        assert get_ident() != owner
        started.set()
        assert finish.wait(2)
        from stock_lab_core.performance import count_event
        count_event('worker_probe')
        return dict(deepcopy(rows[1]), bulletin_request_metadata={})

    def cpi(now):
        assert get_ident() == owner and started.wait(2)
        finish.set()
        return dict(deepcopy(rows[0]), bulletin_request_metadata={})

    actual_apply_cpi, actual_apply_exports = b._apply_live_cpi, b._apply_live_exports

    def apply_cpi(*args, **kwargs):
        assert get_ident() == owner
        apply_order.append('cpi')
        return actual_apply_cpi(*args, **kwargs)

    def apply_exports(*args, **kwargs):
        assert get_ident() == owner
        apply_order.append('exports')
        return actual_apply_exports(*args, **kwargs)

    monkeypatch.setattr(b, 'load_kr_cpi_bulletin', cpi)
    monkeypatch.setattr(b, 'load_kr_exports_bulletin', exports)
    monkeypatch.setattr(b, '_apply_live_cpi', apply_cpi)
    monkeypatch.setattr(b, '_apply_live_exports', apply_exports)
    with PerformanceTrace() as trace:
        b.apply_official_bulletins(rows, NOW)
    assert apply_order == ['cpi', 'exports']
    assert trace.report()['transport_events']['worker_probe'] == 1
