"""Single-row fast path equals the preserved generic normalizer and app base."""
import ast
from copy import deepcopy
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def assert_row_equal(actual, expected):
    assert list(actual) == list(expected)
    pd.testing.assert_series_equal(pd.Series(actual, dtype=object),
                                   pd.Series(expected, dtype=object), check_exact=True)
    for key in expected:
        if expected[key] is None:
            assert actual[key] is None


@pytest.mark.parametrize('status', ['보유', '관심', '미등록'])
@pytest.mark.parametrize('seed', range(40))
def test_scalar_rows_match_generic_with_missing_existing_and_null_fields(app_module, monkeypatch, seed, status):
    app = app_module
    monkeypatch.setattr(app, '_today_flow_candidate_status', lambda *args: status)
    rng = np.random.default_rng(seed)
    row = dict(Ticker=['MSFT', '005930.KS', '035900.KQ'][seed % 3], 종목명='Fixture',
               연결상태='연결', 기준일='2026-10-30', source_asof='2026-10-30')
    for key in ['가격수준', '1일수익률', '1주수익률', '2주수익률', '1개월수익률', '가속도', '돈흐름점수']:
        if rng.random() > .25:
            row[key] = [None, np.nan, -.1, 0., .04, .08, .90, 2.][rng.integers(8)]
    for key in ['종목명', '후보군', '시장', '세부축', '테마', '대분류', '기준업종', '타이밍',
                '주의요인', '판정', '시장맥락', '등록상태', '후보근거', '구분', '하위테마', '섹터']:
        if rng.random() > .5:
            row[key] = [None, np.nan, '', '한국', '반도체', '급등', '보유'][rng.integers(7)]
    original = deepcopy(row)
    expected = app._normalize_today_flow_context_frame(pd.DataFrame([row]), 10, '종목 자체 흐름').iloc[0].to_dict()
    actual = app._normalize_source_flow_row(row, 10, '종목 자체 흐름')
    assert_row_equal(actual, expected)
    assert_row_equal(row, original)


@pytest.mark.parametrize('days', [0, 12, 20, 30, 260, 365])
@pytest.mark.parametrize('missing_volume', [False, True])
def test_actual_source_history_context_exact_and_unchanged(app_module, monkeypatch, days, missing_volume):
    app = app_module
    monkeypatch.setattr(app, '_today_flow_candidate_status', lambda *args: '보유')
    from tests.fixtures_price import make_price_df
    frame = make_price_df(days=365)[['Open', 'High', 'Low', 'Close', 'Volume']].iloc[:days].copy()
    if missing_volume:
        frame['Volume'] = np.nan
    original = frame.copy(deep=True)
    fast = app._normalize_source_flow_row
    expected_normalizer = lambda row, priority, group: app._normalize_today_flow_context_frame(
        pd.DataFrame([row]), priority, group).iloc[0].to_dict()
    monkeypatch.setattr(app, '_normalize_source_flow_row', expected_normalizer)
    expected = app.build_source_flow_context(frame, 'MSFT', 'Fixture')
    monkeypatch.setattr(app, '_normalize_source_flow_row', fast)
    actual = app.build_source_flow_context(frame, 'MSFT', 'Fixture')
    assert_row_equal(actual, expected)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_failure_and_registration_call_order_preserved(app_module, monkeypatch):
    app = app_module
    row = {'Ticker': 'MSFT', '섹터': 'fallback'}
    monkeypatch.setattr(app, '_flow_display_broad_context', lambda *a, **k: (_ for _ in ()).throw(ValueError()))
    calls = []
    monkeypatch.setattr(app, '_today_flow_candidate_status', lambda *a: calls.append(a) or '관심')
    expected = app._normalize_today_flow_context_frame(pd.DataFrame([row]), 10, 'source').iloc[0].to_dict()
    before = list(calls)
    calls.clear()
    assert_row_equal(app._normalize_source_flow_row(row, 10, 'source'), expected)
    assert calls == before
    for invalid in [{}, {'Ticker': ''}]:
        with pytest.raises(IndexError):
            app._normalize_today_flow_context_frame(pd.DataFrame([invalid]), 10, 'source').iloc[0]
        with pytest.raises(IndexError):
            app._normalize_source_flow_row(invalid, 10, 'source')


def test_all_other_app_functions_unchanged_and_source_wrapper_only_changes_call():
    before = subprocess.check_output(['git', 'show', '125748fc:app.py'], cwd=ROOT, encoding='utf-8-sig')
    after = (ROOT/'app.py').read_text(encoding='utf-8-sig')
    def functions(source):
        from tests.report_ast_contract import before_msft_cash_report
        from tests.precision_fix_ast_contract import before_precision_fixes
        return {n.name: before_msft_cash_report(before_precision_fixes(n)) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    old, new = functions(before), functions(after)
    new.pop('_normalize_source_flow_row')
    new.pop('_render_image_theme_selection')
    # Later financial-input repair adds read-only review and an OCF fallback.
    # Those provider functions have direct contracts in test_financial_review;
    # the preserved decision/flow functions and original Git baseline stay frozen.
    new.pop('pick_dart_operating_cash_flow')
    new.pop('inspect_financial_inputs')
    from tests.test_theme_selection import inline_theme_selection
    new['render_image_theme_flow_section'] = inline_theme_selection(new['render_image_theme_flow_section'])
    assert old.keys() == new.keys()
    financial_repairs = {'fetch_dart_corp_code_map', 'fetch_dart_finstate_all_raw', 'extract_dart_metrics',
                         'fetch_kr_financials_auto', 'fetch_us_financials_sec'}
    for name in old.keys() - {'build_source_flow_context'} - financial_repairs:
        assert ast.dump(old[name]) == ast.dump(new[name]), name
    # The only old-function edit is this call; generic multi-row path stays frozen.
    restored = after.replace('_normalize_source_flow_row(row, 10, "종목 자체 흐름")',
        '_normalize_today_flow_context_frame(pd.DataFrame([row]), 10, "종목 자체 흐름").iloc[0].to_dict()')
    assert ast.dump(functions(restored)['build_source_flow_context']) == ast.dump(old['build_source_flow_context'])
