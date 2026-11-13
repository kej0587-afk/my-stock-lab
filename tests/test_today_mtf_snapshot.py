"""Unused Today daily narrative removal, against immutable pre-change code."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import decision_engine
from stock_lab_core.signal_basis import build_signal_basis
from tests.fixtures_price import make_price_df
from tests.mtf_ast_contract import before_optional_daily_snapshot
from tests.company_market_ast_contract import before_company_market_context
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable
from tests.test_decision_refactor_parity import scenarios

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = 'c2d9397e'


@pytest.fixture(scope='module')
def original_source():
    return subprocess.check_output(['git', 'show', f'{REFERENCE}:app.py'], cwd=ROOT, encoding='utf-8-sig')


def original_function(source, name, namespace):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'original_app.py', 'exec'), namespace)
    return namespace[name]


def stable(value):
    return json.dumps(_to_jsonable(value), sort_keys=True, default=str, allow_nan=False)


def test_only_two_app_functions_change_and_only_reviewed_expressions(original_source):
    from tests.precision_fix_ast_contract import before_precision_fixes
    def functions(source, restore=False):
        return {n.name: ast.dump(before_company_market_context(before_optional_daily_snapshot(before_precision_fixes(n)) if restore else before_precision_fixes(n)))
                for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    current = (ROOT / 'app.py').read_text(encoding='utf-8-sig')
    old, new = functions(original_source), functions(current)
    assert {k for k in old if old[k] != new[k]} == {'build_precision_multi_timeframe_pack', '_compute_summary_item'}
    assert old == functions(current, restore=True)


@pytest.mark.parametrize('days', [0, 2, 12, 20, 64, 260])
@pytest.mark.parametrize('missing_volume', [False, True])
def test_default_precision_pack_exact_and_guard_uses_same_week_month(app_module, monkeypatch, original_source, days, missing_volume):
    app = app_module
    daily = make_price_df(days=260).iloc[:days].copy(deep=True)
    if missing_volume:
        daily['Volume'] = np.nan
    saved = daily.copy(deep=True)
    long = make_price_df(days=600)
    old = original_function(original_source, 'build_precision_multi_timeframe_pack', vars(app).copy())
    expected = old('TEST', daily, _long_price_df=long)
    current = app.build_precision_multi_timeframe_pack('TEST', daily, _long_price_df=long)
    calls = []
    original_snapshot = app.build_precision_timeframe_snapshot
    monkeypatch.setattr(app, 'build_precision_timeframe_snapshot',
                        lambda label, *a, **k: calls.append(label) or original_snapshot(label, *a, **k))
    reduced = app.build_precision_multi_timeframe_pack('TEST', daily, _long_price_df=long, _include_daily_snapshot=False)
    assert calls == ['주봉', '월봉']
    for label in ('일봉', '주봉', '월봉'):
        pd.testing.assert_frame_equal(current[label]['df'], expected[label]['df'], check_exact=True)
        assert stable(current[label]['snapshot']) == stable(expected[label]['snapshot'])
        pd.testing.assert_frame_equal(reduced[label]['df'], expected[label]['df'], check_exact=True)
        if label != '일봉':
            assert stable(reduced[label]['snapshot']) == stable(expected[label]['snapshot'])
    frozen = json.loads((ROOT / 'tests/golden/decision_refactor_full_snapshots.json').read_text(encoding='utf-8'))
    for decision in frozen.values():
        for held in (False, True):
            assert stable(app.apply_precision_mtf_decision_guard(decision, reduced, held)) == stable(
                app.apply_precision_mtf_decision_guard(decision, expected, held))
    pd.testing.assert_frame_equal(daily, saved, check_exact=True)


@pytest.mark.parametrize('case', scenarios(), ids=[c[0] for c in scenarios()])
def test_entire_today_worker_row_matches_original(app_module, monkeypatch, original_source, case):
    app = app_module
    sid, px, _, _, kwargs, live_gap = case
    frame = make_price_df(**px)
    long = make_price_df(days=600)
    originals = frame.copy(deep=True), long.copy(deep=True)
    frozen = json.loads((ROOT / 'tests/golden/decision_refactor_full_snapshots.json').read_text(encoding='utf-8'))[sid]
    def forbidden(*a, **k):
        raise AssertionError('Unexpected provider request')
    replacements = {
        'holdings_table': pd.DataFrame(),
        'lookup_yfinance_display_name': lambda ticker: 'Synthetic company',
        'load_price_df': forbidden, 'load_latest_price': forbidden,
        'load_display_live_price': lambda _: float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.,
        'load_fin_score_meta_fast': lambda *a: (kwargs['fin_score'], {}),
        'get_my_price': lambda *a: kwargs['my_price'], 'has_position': lambda *a: kwargs['has_pos'],
        'calc_scores_and_decision': lambda **k: deepcopy(frozen),
        'apply_leveraged_dca_dashboard_override': lambda value: value,
        'apply_leveraged_precision_decision_override': lambda value, *a: value,
        'get_auto_benchmark_info': lambda *a: _bench_info(),
        '_today_flow_candidate_status': lambda *a: '미등록',
        'build_signal_basis': lambda frame, context: build_signal_basis(frame, context, calculated_at='fixed'),
    }
    for key, value in replacements.items():
        monkeypatch.setattr(app, key, value)
    monkeypatch.setattr(decision_engine, '_get_live_price_row_date', lambda _: frame.index[-1])
    old = original_function(original_source, '_compute_summary_item', vars(app).copy())
    item = {k: kwargs[k] for k in ('ticker', 'name', 'is_etf', 'asset_class')}
    args = (item, kwargs['app_mode'], kwargs['_macro_penalty'], kwargs['_final_macro_risk'],
            kwargs['_total_eval'], kwargs['_cash_available'], kwargs['_reserve_available'])
    expected = old(*args, _price_df=frame, _long_price_df=long)
    actual = app._compute_summary_item(*args, _price_df=frame, _long_price_df=long)
    assert actual['f_score'] is not None
    assert stable(actual) == stable(expected)
    for source, saved in zip((frame, long), originals):
        pd.testing.assert_frame_equal(source, saved, check_exact=True)
