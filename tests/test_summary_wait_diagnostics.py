"""Instrumentation must preserve calculation statements, provider policy and outputs."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from types import ModuleType
from unittest.mock import Mock

import pytest
from stock_lab_core import news, yahoo_metadata
from stock_lab_core.performance import PerformanceTrace, measure

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ('summary_asset_metadata[', 'summary_financial_score[', 'summary_holdings_lookup[',
            'summary_live_alignment[', 'summary_leverage_review[', 'summary_benchmark_lookup[')


class StripAddedTiming(ast.NodeTransformer):
    def visit_With(self, node):
        self.generic_visit(node)
        if len(node.items) == 1:
            call = node.items[0].context_expr
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'measure':
                if len(call.args) == 2 and isinstance(call.args[1], ast.JoinedStr):
                    if isinstance(call.args[1].values[0], ast.Constant) and call.args[1].values[0].value in PREFIXES:
                        return node.body
        return node

    def visit_Name(self, node):
        if node.id == '_timed_today_analyst_snapshot':
            node.id = 'get_analyst_snapshot'
        return node


def strip_added_timing(node):
    return StripAddedTiming().visit(node)


def test_all_app_functions_match_immutable_reference_after_removing_only_timers():
    old = subprocess.check_output(['git', 'show', 'f746134c:app.py'], cwd=ROOT, encoding='utf-8-sig')
    current = (ROOT / 'app.py').read_text(encoding='utf-8-sig')
    def functions(source):
        return {n.name: ast.dump(strip_added_timing(n)) for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name != '_timed_today_analyst_snapshot'}
    assert functions(old) == functions(current)


def test_analyst_callback_identity_errors_and_symbol_timing():
    node = next(n for n in ast.parse((ROOT / 'app.py').read_text(encoding='utf-8-sig')).body
                if isinstance(n, ast.FunctionDef) and n.name == '_timed_today_analyst_snapshot')
    result = {'data': {'targetMeanPrice': 120}}
    callback = Mock(return_value=result)
    env = dict(measure=measure, get_analyst_snapshot=callback)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), env)
    with PerformanceTrace() as trace:
        assert env[node.name]('TEST') is result
    callback.assert_called_once_with('TEST')
    assert trace.report()['functions'][0]['name'] == 'today_analyst_snapshot[TEST]'
    callback.side_effect = RuntimeError('fixture')
    with pytest.raises(RuntimeError):
        env[node.name]('TEST')


def test_lock_wait_is_separate_from_fetch_and_cached_hit():
    clock = [0.0]
    class FakeLock:
        def __enter__(self): clock[0] += 2
        def __exit__(self, *args): pass
    reader = yahoo_metadata.YahooMetadataReader(clock=lambda: clock[0], min_interval=0)
    reader._lock = FakeLock()
    def fetch(ticker):
        clock[0] += 3
        return {'targetMeanPrice': 120}
    with PerformanceTrace(clock=lambda: clock[0]) as trace:
        first = reader.read('info', 'TEST', fetch)
        second = reader.read('info', 'TEST', Mock(side_effect=AssertionError('cache miss')))
    assert first == second
    rows = {r['name']: r for r in trace.report()['functions']}
    assert rows['yahoo_metadata_lock_wait[info]']['total_seconds'] == 4
    assert rows['yahoo_metadata_provider[info]']['total_seconds'] == 3
    assert trace.report()['transport_events'] == {'yahoo_metadata.info.lookup': 2,
        'yahoo_metadata.info.provider_attempt': 1, 'yahoo_metadata.info.cache_hit': 1}


def test_metadata_original_results_calls_and_cooldowns_are_identical(monkeypatch):
    reference = ModuleType('metadata_reference')
    exec(subprocess.check_output(['git', 'show', 'f746134c:stock_lab_core/yahoo_metadata.py'],
                                cwd=ROOT, encoding='utf-8'), reference.__dict__)
    class FrozenDate:
        @staticmethod
        def now(tz=None): return datetime(2026, 11, 7, tzinfo=timezone.utc)
    monkeypatch.setattr(yahoo_metadata, 'datetime', FrozenDate)
    reference.datetime = FrozenDate
    def replay(cls):
        clock = [0.0]
        sleeps, calls, results = [], [], []
        def sleep(delay):
            sleeps.append(delay)
            clock[0] += delay
        reader = cls(clock=lambda: clock[0], sleep=sleep)
        def fetch(t):
            calls.append(t)
            if t == 'FAIL': raise ValueError('fixture')
            return {'v': 1} if t != 'EMPTY' else {}
        for ticker in ['A', 'A', 'B', 'EMPTY', 'EMPTY', 'FAIL', 'FAIL']:
            results.append(reader.read('info', ticker, fetch))
        clock[0] += 61
        results.append(reader.read('info', 'EMPTY', fetch))
        return results, calls, sleeps, reader.counts()
    with PerformanceTrace():
        assert replay(yahoo_metadata.YahooMetadataReader) == replay(reference.YahooMetadataReader)


def test_analyst_outer_cache_reports_reuse_without_repeating_provider(monkeypatch):
    reader = yahoo_metadata.YahooMetadataReader(min_interval=0)
    provider = Mock(return_value={'targetMeanPrice': 120})
    monkeypatch.setattr(news, 'yahoo_metadata_reader', reader)
    monkeypatch.setattr(news, '_fetch_yahoo_analyst_data', provider)
    news.get_analyst_snapshot.clear()
    try:
        with PerformanceTrace() as trace:
            first = news.get_analyst_snapshot('TEST_DIAG')
            second = news.get_analyst_snapshot('TEST_DIAG')
        assert first == second
        provider.assert_called_once()
        events = trace.report()['transport_events']
        assert events['cache.analyst_snapshot.lookup'] == 2
        assert events['cache.analyst_snapshot.miss'] == events['cache.analyst_snapshot.reuse'] == 1
        assert events['yahoo_metadata.analyst_direct.provider_attempt'] == 1
    finally:
        news.get_analyst_snapshot.clear()


def test_analyst_scope_restores_and_shares_original_cache_key():
    reader = yahoo_metadata.YahooMetadataReader(min_interval=0)
    provider = Mock(return_value={'v': 1})
    with PerformanceTrace() as trace:
        with yahoo_metadata.metadata_diagnostic_scope('analyst'):
            first = reader.read('info', 'TEST', provider)
        second = reader.read('info', 'TEST', provider)
    assert first == second and provider.call_count == 1
    events = trace.report()['transport_events']
    assert events['yahoo_metadata.analyst:info.provider_attempt'] == 1
    assert events['yahoo_metadata.info.cache_hit'] == 1
