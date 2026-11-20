"""Same captured price inputs across views, independent of rendering clock."""

import ast
import io
import json
from pathlib import Path
import socket
import zipfile

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import decision_engine as engine
from stock_lab_core.decision_inputs import prepare_decision_price_inputs
from stock_lab_core.signal_basis import build_signal_basis
from stock_lab_core.signal_input_contract import price_input_identity, source_price_rows
from stock_lab_core.ta_engine import build_indicators
from tests.fixtures_price import make_price_df


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Input reconciliation must not fetch another quote')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)


@pytest.mark.parametrize('ticker', ['SOXL', 'RAM', 'BITX', '418660.KS', 'MSFT'])
@pytest.mark.parametrize('same_date', [True, False])
def test_source_atr_and_dates_survive_quote_overlay(monkeypatch, ticker, same_date):
    source = make_price_df(seed=17)
    before = source.copy(deep=True)
    day = source.index[-1] if same_date else source.index[-1] + pd.offsets.BDay()
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: day)
    price = float(source.Close.iloc[-1]) * .92
    context = engine.apply_live_price_with_indicators(source, price, ticker, build_indicators)
    overlay, applied, issue = context
    assert applied and not issue and overlay.Close.iloc[-1] == price
    assert np.isnan(overlay.Volume.iloc[-1])
    assert engine.calc_atr_for_decision(overlay) == engine.calc_atr_for_decision(source)
    basis = build_signal_basis(source, context, ticker=ticker, input_price=price)
    assert basis['ATR기준일'] == source.index[-1].strftime('%Y-%m-%d')
    assert basis['ATR가격봉수'] == len(source)
    assert '시각/정규장 완료일 아님' in basis['임시봉날짜의미']
    assert '미확인' in basis['현재가출처']
    pd.testing.assert_frame_equal(source, before)
    original_overlay = overlay.copy(deep=True)
    recovered = source_price_rows(overlay)
    pd.testing.assert_frame_equal(recovered[['Open','High','Low','Close','Volume']],
                                  source[['Open','High','Low','Close','Volume']], check_freq=False)
    pd.testing.assert_frame_equal(overlay, original_overlay)


def test_repeated_overlay_retains_original_row_not_previous_quote(monkeypatch):
    source = make_price_df(seed=18)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    one, _, _ = engine.apply_live_price_with_indicators(source, source.Close.iloc[-1]*1.03, 'TEST', build_indicators)
    two, _, _ = engine.apply_live_price_with_indicators(one, source.Close.iloc[-1]*.95, 'TEST', build_indicators)
    assert engine.calc_atr_for_decision(two) == engine.calc_atr_for_decision(source)
    assert two.attrs['live_quote']['source_last_bar'] == one.attrs['live_quote']['source_last_bar']


@pytest.mark.parametrize('bad', [None, {}, {'at':'bad'}, {'at':'2026-01-01', 'Open':1, 'High':2, 'Low':1, 'Close':1}])
def test_uncaptured_or_mismatched_source_bar_stays_excluded(bad):
    source = make_price_df(seed=17)
    overlay = source.copy()
    overlay['LiveQuoteOnly'] = False
    overlay.loc[overlay.index[-1], 'LiveQuoteOnly'] = True
    overlay.attrs['live_quote'] = {'source_last_bar': bad}
    assert engine.calc_atr_for_decision(overlay) == engine.calc_atr_for_decision(source.iloc[:-1])


def test_invalid_captured_ohlc_cannot_restore_a_bar():
    source = make_price_df(seed=17)
    source['LiveQuoteOnly'] = False
    source.loc[source.index[-1], 'LiveQuoteOnly'] = True
    source.attrs['live_quote'] = {'source_last_bar': {'at':source.index[-1].isoformat(), 'Open':100, 'High':90, 'Low':99, 'Close':100}}
    assert len(source_price_rows(source)) == len(source)-1


@pytest.mark.parametrize('same_date', [True, False])
def test_today_board_precision_same_capture_has_identical_prepared_inputs(monkeypatch, same_date):
    source = make_price_df(seed=19)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1] if same_date else source.index[-1]+pd.offsets.BDay())
    price = float(source.Close.iloc[-1])*.97
    records = []
    for view in ('today', 'board', 'precision'):
        context = engine.apply_live_price_with_indicators(source, price, 'SOXL', build_indicators)
        prepared = prepare_decision_price_inputs(source, 'SOXL', price, build_indicators=build_indicators,
                    apply_live_price_with_indicators=engine.apply_live_price_with_indicators, _live_indicator_context=context)
        basis = build_signal_basis(source, context, ticker='SOXL', input_price=price, calculated_at=view)
        records.append((prepared, basis))
    for prepared, basis in records[1:]:
        assert basis['가격입력ID'] == records[0][1]['가격입력ID']
        for key in ('cur_p','regular_day_ret','live_ref_ret','ret_1m','ret_3m','ret_6m'):
            assert prepared[key] == records[0][0][key]
        pd.testing.assert_frame_equal(prepared['df'], records[0][0]['df'])


def test_identity_detects_source_quote_ticker_or_provisional_changes():
    source = make_price_df(seed=17)
    key = price_input_identity(source, source, ticker='SOXL', input_price=100)
    assert key == price_input_identity(source.copy(), source.copy(), ticker=' soxl ', input_price='100')
    assert key != price_input_identity(source, source, ticker='RAM', input_price=100)
    assert key != price_input_identity(source, source, ticker='SOXL', input_price=101)
    altered = source.copy()
    altered.loc[altered.index[0], 'Close'] += 1
    assert key != price_input_identity(altered, source, ticker='SOXL', input_price=100)
    altered = source.copy()
    altered['LiveQuoteOnly'] = False
    altered.loc[altered.index[-1], 'LiveQuoteOnly'] = True
    assert key != price_input_identity(source, altered, ticker='SOXL', input_price=100)


@pytest.mark.parametrize('unit', ['ns', 'us', 'ms', 's'])
def test_identity_ignores_datetime_storage_resolution(unit):
    source = make_price_df(seed=17)
    other = source.copy()
    other.index = other.index.as_unit(unit)
    assert price_input_identity(source, source, ticker='SOXL', input_price=42.93) == price_input_identity(
        other, other, ticker='SOXL', input_price=42.93)


def test_exported_price_frames_replay_same_identity(monkeypatch):
    from stock_lab_core.precision_review_export import build_precision_review_export_zip
    source = make_price_df(seed=17)
    price = float(source.Close.iloc[-1]) * .92
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    chart, applied = engine.apply_live_price_to_ohlcv(source, price, 'SOXL')
    assert applied
    data = build_precision_review_export_zip(selected_ticker='SOXL', result_ticker='SOXL',
        decision={'cur_p': price}, ohlcv={'source':source, 'chart':chart})
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        replay = []
        for label in ('source', 'chart'):
            entry = manifest['ohlcv'][label]
            frame = pd.read_csv(io.BytesIO(archive.read(entry['file'])), float_precision='round_trip')
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop('_row_index'))).as_unit('us')
            frame.attrs = entry['attrs']
            replay.append(frame)
    assert price_input_identity(source, chart, ticker='SOXL', input_price=price) == price_input_identity(
        *replay, ticker='SOXL', input_price=price)
    assert engine.calc_atr_for_decision(replay[1]) == engine.calc_atr_for_decision(source)


def test_real_entrypoints_share_context_and_pass_quote_identity():
    tree = ast.parse((Path(__file__).parents[1]/'app.py').read_text(encoding='utf-8-sig'))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    contexts = {k.value.id for n in calls if n.func.id=='calc_scores_and_decision'
                for k in n.keywords if k.arg=='_live_indicator_context' and isinstance(k.value, ast.Name)}
    assert {'live_context','precision_live_context','demo_live_context'} <= contexts
    basis_calls = [n for n in calls if n.func.id=='build_signal_basis']
    assert len(basis_calls)==3
    assert all({'ticker','input_price'} <= {k.arg for k in n.keywords} for n in basis_calls)


def test_basis_survives_workflow_export_and_view_projection():
    from stock_lab_core.dashboard_view import _DETAIL_COLUMNS
    from stock_lab_core.decision_workflow import build_decision_workflow
    from stock_lab_core.precision_review_export import build_precision_review_export_zip
    from stock_lab_core.today_queue_view import DETAIL_COLUMNS
    source = make_price_df(seed=17)
    basis = build_signal_basis(source, (source, False, ''), ticker='SOXL')
    decision = {'cur_p': float(source.Close.iloc[-1]), 'input_basis': basis}
    workflow = build_decision_workflow('SOXL', 'SOXL', decision, is_etf=True)
    data = build_precision_review_export_zip(selected_ticker='SOXL', result_ticker='SOXL',
        decision=decision, context={'signal_basis': basis}, workflow_display=pd.DataFrame([workflow]))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        exported = json.loads(archive.read('snapshot.json'))['sections']['context']['signal_basis']
    for column in ('가격입력ID','현재가출처','임시봉날짜의미','ATR기준일',
                   '현재가관측시각','현재가관측UTC','현재가세션','현재가시각종류','원자료봉상태'):
        assert column in _DETAIL_COLUMNS and column in DETAIL_COLUMNS
        assert workflow[column] == exported[column] == basis[column]


def test_captured_bar_survives_json_roundtrip(monkeypatch):
    source = make_price_df(seed=17)
    source.index = source.index.tz_localize('America/New_York')
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1].tz_localize(None))
    overlay, applied = engine.apply_live_price_to_ohlcv(source, source.Close.iloc[-1] * .92, 'SOXL')
    assert applied
    overlay.attrs = json.loads(json.dumps(overlay.attrs, allow_nan=False))
    assert engine.calc_atr_for_decision(overlay) == engine.calc_atr_for_decision(source)
