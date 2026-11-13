"""Exact row parity and failure/forced-refresh contracts for 6mo batching."""
import ast
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
import subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import leveraged_watch as module, prices
from stock_lab_core.performance import PerformanceTrace, submit_with_context
from tests.test_leveraged_watch import assert_exact_rows, baseline_rows, baseline_scope


@pytest.fixture(autouse=True)
def summary_scope():
    with module.leveraged_watch_history_scope():
        yield


@pytest.fixture
def callbacks():
    scope = baseline_scope()
    return dict(pct_text=scope['_leveraged_precision_pct_text'],
                judge=scope['_leveraged_precision_proxy_judgement'])


@pytest.mark.parametrize('length', [0, 1, 2, 5, 6, 21, 22, 23, 128])
@pytest.mark.parametrize('quote', [0, 150.25, np.nan])
def test_exact_rows_duplicates_order_kr_fallback_and_no_mutation(callbacks, length, quote):
    watch = [(' b ', 'sector', 'first'), ('005930.KS', 'KR', 'second'),
             ('A', 'market', 'third'), (' b ', 'repeat', 'fourth')]
    frame = pd.DataFrame({'Close': np.arange(length, dtype=float) + 100})
    frame.attrs = {'source': 'fixture'}
    frames = {'A': frame.copy(), 'B': frame.copy()}
    saved = deepcopy(frames)
    history = Mock(side_effect=lambda ticker, period: frame.copy())
    batch = Mock(return_value=frames)
    providers = dict(load_quote=lambda ticker: quote, load_history=history)
    expected = baseline_rows(watch, **providers, **callbacks)
    history.reset_mock()
    with PerformanceTrace() as trace:
        actual = module.build_leveraged_watch_rows_batched(iter(watch), load_batch=batch,
                                                          **providers, **callbacks)
    assert_exact_rows(actual, expected)
    batch.assert_called_once_with(('005930.KS', 'A', 'B'), '6mo')
    assert history.call_count == (4 if length == 0 else 1)
    assert all(call.args[1] == '6mo' for call in history.call_args_list)
    assert trace.report()['transport_events']['leveraged_watch.original_history_fallback'] >= 1
    for ticker in frames:
        pd.testing.assert_frame_equal(frames[ticker], saved[ticker], check_exact=True)
        assert frames[ticker].attrs == saved[ticker].attrs


@pytest.mark.parametrize('result', [None, {}, [], {'A': pd.DataFrame()},
                                    {'A': pd.DataFrame({'Other': [1, 2]})}, RuntimeError('batch failed')])
def test_batch_failure_or_missing_symbol_retries_original_loader(callbacks, result):
    watch = [('A', '', ''), ('B', '', '')]
    batch = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    providers = dict(load_quote=lambda t: 12, load_history=lambda t, p: pd.DataFrame({'Close': [10, 11]}))
    assert_exact_rows(module.build_leveraged_watch_rows_batched(watch, load_batch=batch, **providers, **callbacks),
                      baseline_rows(watch, **providers, **callbacks))


@pytest.mark.parametrize('watch', [[], [('A', '', '')]])
def test_empty_single_avoid_batch(callbacks, watch):
    batch = Mock(side_effect=AssertionError('unnecessary batch'))
    providers = dict(load_quote=lambda t: 12, load_history=lambda t, p: pd.DataFrame({'Close': [10, 11]}))
    assert_exact_rows(module.build_leveraged_watch_rows_batched(watch, load_batch=batch, **providers, **callbacks),
                      baseline_rows(watch, **providers, **callbacks))
    batch.assert_not_called()


def test_batch_control_flow_is_not_swallowed(callbacks):
    with pytest.raises(KeyboardInterrupt):
        module.build_leveraged_watch_rows_batched([('A', '', ''), ('B', '', '')],
            load_batch=Mock(side_effect=KeyboardInterrupt), load_quote=Mock(), load_history=Mock(), **callbacks)


@pytest.mark.parametrize('force,available', [(True, True), (False, True), (False, False)])
def test_app_uses_original_caller_for_forced_refresh_and_old_module(monkeypatch, force, available):
    tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'build_leveraged_precision_watch_rows')
    node.decorator_list = []
    original, batched = Mock(return_value=['original']), Mock(return_value=['batch'])
    if available:
        monkeypatch.setattr(module, 'build_leveraged_watch_rows_batched', batched)
    else:
        monkeypatch.delattr(module, 'build_leveraged_watch_rows_batched')
    monkeypatch.setattr(prices, '_force_live_price_refresh_active', lambda: force)
    scope = dict(LEVERAGED_ETF_PRECISION_PROFILES={'profile': {'watch': [('A', '', '')]}},
                 build_leveraged_watch_rows=original, load_display_live_price=Mock(),
                 load_price_df=Mock(), _leveraged_precision_pct_text=Mock(),
                 _leveraged_precision_proxy_judgement=Mock())
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), scope)
    result = scope['build_leveraged_precision_watch_rows']('profile')
    if not force and available:
        assert result == ['batch']
        original.assert_not_called()
        assert batched.call_args.kwargs['load_batch'] is prices.load_price_frames_batch
    else:
        assert result == ['original']
        assert original.call_args.kwargs['parallel'] is (not force)
        batched.assert_not_called()


def test_overlapping_profiles_share_successes_even_when_concurrent(callbacks):
    frame = pd.DataFrame({'Close': [10.0, 11.0]})
    batch = Mock(side_effect=lambda ts, p: {t: frame for t in ts})
    args = dict(load_quote=lambda t: 12.0, load_history=Mock(side_effect=AssertionError('duplicate')),
                load_batch=batch, **callbacks)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [submit_with_context(pool, module.build_leveraged_watch_rows_batched,
                    [(t, '', '') for t in tickers], **args)
                   for tickers in [('A', 'B'), ('B', 'C'), ('A', 'C')]]
        assert all(len(f.result()) == 2 for f in futures)
    requested = [t for call in batch.call_args_list for t in call.args[0]]
    assert sorted(requested) == ['A', 'B', 'C']
    with module.leveraged_watch_history_scope():
        module.build_leveraged_watch_rows_batched([('A', '', ''), ('B', '', '')], **args)
    assert batch.call_args.args == (('A', 'B'), '6mo')


def test_failed_symbols_are_retried_and_new_scope_does_not_retain_frames(callbacks):
    watch = [('A', '', ''), ('B', '', '')]
    frame = pd.DataFrame({'Close': [10, 11]})
    batch = Mock(side_effect=[{'A': frame}, {'B': frame}])
    args = dict(load_quote=lambda t: 12, load_history=lambda t, p: frame, load_batch=batch, **callbacks)
    first = module.build_leveraged_watch_rows_batched(watch, **args)
    second = module.build_leveraged_watch_rows_batched(watch, **args)
    assert_exact_rows(first, second)
    assert batch.call_args_list[1].args == (('B',), '6mo')


def test_precision_visit_outside_summary_keeps_original_loader(callbacks):
    token = module._BATCH_HISTORY.set(None)
    batch = Mock(side_effect=AssertionError('no prefetch on precision visit'))
    history = Mock(return_value=pd.DataFrame({'Close': [10.0, 11.0]}))
    try:
        actual = module.build_leveraged_watch_rows_batched([('A', '', ''), ('B', '', '')],
            load_quote=lambda t: 12.0, load_history=history, load_batch=batch, **callbacks)
        assert len(actual) == 2 and history.call_count == 2
        batch.assert_not_called()
    finally:
        module._BATCH_HISTORY.reset(token)


def test_new_route_retains_streamlit_cache_copy_clear_and_force_policy(monkeypatch):
    import streamlit as st
    tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'build_leveraged_precision_watch_rows')
    forced = [False]
    monkeypatch.setattr(prices, '_force_live_price_refresh_active', lambda: forced[0])
    batch = Mock(return_value=[{'Ticker': 'A'}])
    original = Mock(return_value=[{'Ticker': 'A'}])
    monkeypatch.setattr(module, 'build_leveraged_watch_rows_batched', batch)
    scope = dict(st=st, LEVERAGED_ETF_PRECISION_PROFILES={'batch_fixture': {'watch': [('A', '', '')]}},
                 build_leveraged_watch_rows=original, load_display_live_price=Mock(), load_price_df=Mock(),
                 _leveraged_precision_pct_text=Mock(), _leveraged_precision_proxy_judgement=Mock())
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), scope)
    cached = scope[node.name]
    cached.clear()
    try:
        cached('batch_fixture')[0]['Ticker'] = 'EDIT'
        assert cached('batch_fixture') == [{'Ticker': 'A'}]
        batch.assert_called_once()
        forced[0] = True
        cached.clear()
        assert cached('batch_fixture') == [{'Ticker': 'A'}]
        original.assert_called_once()
        assert original.call_args.kwargs['parallel'] is False
    finally:
        cached.clear()


def test_only_explicit_io_wrapping_changed_against_immutable_reference():
    original = ast.parse(subprocess.check_output(['git', 'show', 'b82d1b61:app.py'], encoding='utf-8-sig'))
    current = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    names = {'get_all_summary', 'build_leveraged_precision_watch_rows'}
    old = {n.name: n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in names}
    new = {n.name: n for n in current.body if isinstance(n, ast.FunctionDef) and n.name in names}
    for name, node in new.items():
        from tests.leveraged_view_ast_contract import before_leveraged_product_view
        node = before_leveraged_product_view(node)
        node.body = [n for n in node.body if not (
            isinstance(n, ast.ImportFrom) and any(alias.asname == 'watch_loader' for alias in n.names))]
        if name == 'build_leveraged_precision_watch_rows':
            node.body = [n for n in node.body if not (
                isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'batch_builder' for t in n.targets))
                and not (isinstance(n, ast.If) and 'batch_builder' in ast.unparse(n.test))]
        else:
            removed = 0
            for child in ast.walk(node):
                if isinstance(child, ast.With):
                    kept = [item for item in child.items if 'leveraged_watch_history_scope' not in ast.unparse(item.context_expr)]
                    removed += len(child.items) - len(kept)
                    child.items = kept
            assert removed == 1
        assert ast.dump(node) == ast.dump(old[name]), name
