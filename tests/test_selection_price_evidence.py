"""Saved observation/mode evidence must not become another decision engine."""

from copy import deepcopy
import io
import json
import socket
import zipfile

import pandas as pd

from stock_lab_core.signal_basis import build_signal_basis, selection_basis
from stock_lab_core.portfolio_holding_review import price_comparison_rows
from stock_lab_core.precision_review_export import build_precision_review_export_zip
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable


def test_same_held_etf_and_prices_can_have_different_policy_paths(app_module, monkeypatch):
    app = app_module
    def no_network(*a, **kw):
        raise AssertionError('fixed comparison must not fetch')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    monkeypatch.setattr(socket, 'getaddrinfo', no_network)
    monkeypatch.setattr(app, 'get_rs_score', lambda *a: (1, '➖보통'))
    monkeypatch.setattr(app, 'get_rs_slope', lambda *a: (0., '➡️RS횡보', 0))
    monkeypatch.setattr(app, 'get_auto_benchmark_info', lambda *a: _bench_info())
    monkeypatch.setattr(app, 'get_sector_flow_state', lambda *a: 'fixture')
    monkeypatch.setattr(app, 'get_effective_weights', lambda *a: (35., 25.))
    monkeypatch.setattr(app, 'get_effective_buy_amount', lambda *a: 0.)
    source = make_price_df(seed=6, tail_shock=-.4, tail_shock_days=15)
    before = source.copy(deep=True)
    kwargs = dict(name='나스닥', ticker='379810.KS', is_etf=True, asset_class='us_etf_nasdaq',
                  df=source, my_price=100., has_pos=True, fin_score=0, app_mode='자유모드',
                  user_total_asset=10000000., user_curr_w=35., user_targ_w=25.,
                  _macro_penalty=0., _final_macro_risk=1., _total_eval=10000000.,
                  _cash_available=0., _reserve_available=0.)
    held = app.calc_scores_and_decision(**kwargs, is_free=False)
    free = app.calc_scores_and_decision(**kwargs, is_free=True)
    assert held['decision_code'] == 'HARD_BLOCK_OVERWEIGHT'
    assert free['decision_code'] != held['decision_code']
    for key in ('cur_p', 'regular_day_ret', 'live_ref_ret', 'grade', 't_score', 'current_w', 'target_w'):
        assert _to_jsonable(held[key]) == _to_jsonable(free[key]), key
    basis = build_signal_basis(source, (source, False, ''), ticker='379810.KS',
                               calculated_at='2026-11-21 10:00:00 KST')
    for mode, decision in ((False, held), (True, free)):
        original = deepcopy(decision)
        metadata = selection_basis(is_free=mode, has_position=True, selection_type='free' if mode else 'today')
        decision['input_basis'] = dict(basis, **metadata)
        assert decision['input_basis']['보유확인'] == '보유'
        assert decision['input_basis']['자유입력여부'] is mode
        assert decision['input_basis']['가격입력ID'] == basis['가격입력ID']
        assert _to_jsonable({k:v for k,v in decision.items() if k!='input_basis'}) == _to_jsonable(original)
    pd.testing.assert_frame_equal(source, before)


def test_price_table_does_not_splice_or_restamp_two_observations():
    detail = {'signal': {'현재가':'$100.00', '가격자료기준일':'2026-11-19', '가격입력ID':'old',
                         '현재가관측시각':'2026-11-20 10:00:00 KST', '현재가세션':'애프터마켓',
                         '연결출처':'오늘점검', **selection_basis(is_free=False, has_position=True, selection_type='today')},
              'precision': {'workflow': {'현재가':'$101.00', '가격자료기준일':'2026-11-20',
                                         '가격입력ID':'new', '현재가관측시각':'2026-11-21 09:59:59 KST',
                                         '현재가세션':'애프터마켓',
                                         **selection_basis(is_free=True, has_position=True, selection_type='free')}}}
    before = deepcopy(detail)
    rows = price_comparison_rows(detail).to_dict('records')
    assert rows[0]['선택가격 / 원자료일'] == '$100.00 / 2026-11-19'
    assert rows[1]['선택가격 / 원자료일'] == '$101.00 / 2026-11-20'
    assert [r['가격입력ID'] for r in rows] == ['old','new']
    assert rows[0]['판정 경로'] == '계좌기준 · 보유'
    assert rows[1]['판정 경로'] == '자유입력 · 보유'
    assert detail == before
    assert all(r['가격입력ID']=='미확인' for r in price_comparison_rows({}).to_dict('records'))


def test_export_preserves_call_mode_and_public_close_repair_only():
    source = make_price_df(seed=6)
    source.attrs['daily_close_repair'] = {'source':'yahoo_regular_close_metadata','symbol':'SOXL',
        'date':'2026-11-20','price':30.88,'field':'Close','api_key':'never-export'}
    mode = selection_basis(is_free=True, has_position=True, selection_type='free')
    payload = build_precision_review_export_zip(selected_ticker='SOXL', result_ticker='SOXL',
        decision={'cur_p':33.37,'input_basis':mode}, context={'signal_basis':mode}, ohlcv={'source':source})
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        snapshot = json.loads(z.read('snapshot.json'))
        exported = snapshot['sections']['context']['signal_basis']
        repair = snapshot['manifest']['ohlcv']['source']['attrs']['daily_close_repair']
        assert exported == mode
        assert repair['price'] == 30.88 and repair['date']=='2026-11-20'
        assert b'never-export' not in z.read('snapshot.json')
    assert selection_basis(is_free=None,has_position=None,selection_type='bad')['분석경로']=='미확인'


def test_held_free_input_uses_account_path_like_today():
    """User decision 2026-11-24: a held ticker found by free input is judged like Today."""
    from stock_lab_core.signal_basis import decision_uses_free_path
    assert decision_uses_free_path(selection_is_free=True, has_position=True) is False
    assert decision_uses_free_path(selection_is_free=True, has_position=False) is True
    assert decision_uses_free_path(selection_is_free=True, has_position=None) is True
    assert decision_uses_free_path(selection_is_free=False, has_position=True) is False
    assert decision_uses_free_path(selection_is_free=False, has_position=False) is False


def test_precision_view_passes_the_decision_path_not_the_selection_type():
    import ast
    from pathlib import Path
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    assert "precision_has_pos, fin_score, precision_decision_is_free," in source
    assert "precision_has_pos, fin_score, is_free," not in source
    ast.parse(source)
