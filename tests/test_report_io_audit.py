from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest
from stock_lab_core.performance import PerformanceTrace
from stock_lab_core.report_io_audit import http_call, lock_wait, provider_label
from stock_lab_core import economic_releases as releases


def test_transport_wait_distinct_and_payload_never_exported():
    clock = [0.0]
    response = SimpleNamespace(status_code=403, text='SECRET')
    class Lock:
        def acquire(self): clock[0] += 2
        def release(self): pass
    def fetch(*args, **kwargs):
        clock[0] += 3
        return response
    with PerformanceTrace(clock=lambda: clock[0]) as trace:
        with lock_wait(Lock(), 'test'):
            assert http_call('fred', fetch, 'https://x/?key=SECRET') is response
    result = trace.report()
    rows = {r['category']: r for r in result['functions']}
    assert rows['official_wait']['total_seconds'] == 2
    assert rows['official_transport']['total_seconds'] == 3
    assert result['elapsed_seconds'] == 5
    assert result['transport_events']['official_http.fred.attempt'] == 1
    assert result['transport_events']['official_http.fred.status_403'] == 1
    assert 'SECRET' not in json.dumps(result)


def test_transport_exception_identity_preserved():
    error = TimeoutError('sensitive')
    def fetch(): raise error
    with PerformanceTrace() as trace:
        with pytest.raises(TimeoutError) as caught:
            http_call('fred', fetch)
    assert caught.value is error
    assert trace.report()['transport_events']['official_http.fred.transport_error'] == 1


def test_economic_cache_counts_preserve_ttl_and_copies(monkeypatch):
    monkeypatch.setattr(releases, '_CACHE', releases.OrderedDict())
    tick = [100.0]
    monkeypatch.setattr(releases.time, 'monotonic', lambda: tick[0])
    now = datetime(2026, 11, 27, tzinfo=timezone.utc)
    calls = []
    def fetch():
        calls.append(1)
        return {'value': 10}
    with PerformanceTrace() as trace:
        a = releases._cached(('bls', 'PRIVATE'), fetch, now)
        tick[0] += 899
        b = releases._cached(('bls', 'PRIVATE'), fetch, now)
        assert b == a and b[0] is not a[0]
        b[0]['value'] = 99
        tick[0] += 1
        c = releases._cached(('bls', 'PRIVATE'), fetch, now)
    assert c == a and len(calls) == 2
    assert trace.report()['transport_events']['official_cache.bls.miss'] == 2
    assert trace.report()['transport_events']['official_cache.bls.hit'] == 1
    assert 'PRIVATE' not in json.dumps(trace.report())


def test_provider_labels_are_allowlisted():
    assert provider_label('https://ecos.bok.or.kr/api/SECRET') == 'bok'
    assert provider_label('https://evilbls.gov/?token=SECRET') == 'other_official'


def test_coverage_has_counts_not_private_input_and_does_not_mutate():
    from copy import deepcopy
    from stock_lab_core.report_generation_performance import generation_measurement, record_official_coverage
    context = {'economic_releases': [{'actual': 3.1, 'status': 'ok', 'secret': 'PRIVATE'}],
               'earnings_results': [{'status': 'official_result', 'ticker': 'PRIVATE'}]}
    original = deepcopy(context)
    state = {}
    with generation_measurement(state):
        record_official_coverage(context)
        state['today_market_memo_text'] = 'unchanged'
    report = state['auto_report_performance']
    assert context == original
    assert report['official_coverage']['economic_releases']['with_actual'] == 1
    assert report['official_coverage']['earnings_results']['rows'] == 1
    assert 'PRIVATE' not in json.dumps(report)
