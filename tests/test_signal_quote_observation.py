"""Selected-price evidence stays observational across displays and decisions."""

import ast
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from stock_lab_core import decision_engine as engine
from stock_lab_core.quote_observation import observed_price
from stock_lab_core.signal_basis import build_signal_basis, quote_display_label, source_bar_observation
from stock_lab_core.ta_engine import build_indicators
from tests.fixtures_price import make_price_df

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('session', ['pre', 'regular', 'post', 'overnight', 'unknown'])
def test_same_price_evidence_does_not_change_indicators_atr_or_identity(monkeypatch, session):
    source = make_price_df(seed=21)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    price = float(source.Close.iloc[-1]) * .95
    observed = observed_price(price, ticker='SOXL', source='Yahoo chart',
                              observed_at='2026-11-20T14:25:00Z', session=session, timestamp_kind='bar_start')
    plain_context = engine.apply_live_price_with_indicators(source, price, 'SOXL', build_indicators)
    rich_context = engine.apply_live_price_with_indicators(source, observed, 'SOXL', build_indicators)
    pd.testing.assert_frame_equal(plain_context[0], rich_context[0])
    assert plain_context[1:] == rich_context[1:]
    assert engine.calc_atr_for_decision(plain_context[0]) == engine.calc_atr_for_decision(rich_context[0])
    before = build_signal_basis(source, plain_context, ticker='SOXL', input_price=price)
    after = build_signal_basis(source, rich_context, ticker='SOXL', input_price=observed)
    assert before['가격입력ID'] == after['가격입력ID']
    assert after['현재가관측시각'] == '2026-11-20 23:25:00 KST'
    assert after['현재가시각종류'] == '분봉 시작시각 · 체결시각 아님'


def test_manual_wrong_symbol_and_untimed_prices_do_not_inherit_other_evidence():
    source = make_price_df(seed=21)
    quote = observed_price(100, ticker='SOXL', source='Yahoo', observed_at='2026-11-20T14:25:00Z', session='pre')
    for value, ticker, manual in [(quote, 'SOXL', True), (quote, 'RAM', False), (float(quote), 'SOXL', False)]:
        basis = build_signal_basis(source, (source, False, ''), ticker=ticker, input_price=value, manual=manual)
        assert basis['현재가관측시각'] == basis['현재가세션'] == '미확인'
    assert quote_display_label(auto_price=quote) == '조회 현재가 · 프리마켓'


@pytest.mark.parametrize('session, date, expected', [
    ('regular', '2026-11-20', '장중 미완성 가능'),
    ('pre', '2026-11-20', '완료 여부 미확인'),
    ('post', '2026-11-20', '완료 여부 미확인'),
    ('regular', '2026-11-19', '종가 확정은 별도 확인'),
    ('regular', '2026-11-21', '기준일 확인 필요'),
])
def test_daily_bar_audit_does_not_certify_or_drop_source_rows(session, date, expected):
    # 01:00 KST is still the previous US calendar date; no processing clock involved.
    frame = pd.DataFrame({'Close':[100]}, index=pd.to_datetime([date]))
    before = frame.copy(deep=True)
    result = source_bar_observation(frame, {'observed_at':'2026-11-21T01:00:00+09:00', 'session':session}, 'SOXL')
    assert expected in result
    pd.testing.assert_frame_equal(frame, before)


def _display_loader(code, latest, direct, close):
    tree = ast.parse(code)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_display_live_price')
    node.decorator_list = []
    calls = []
    def provider(label, value):
        def fetch(_):
            calls.append(label)
            return value
        return fetch
    scope = {'clean_float':lambda x, default: float(x) if x is not None else default,
             'load_latest_price':provider('latest', latest), 'is_kr_listed':lambda t: t.endswith('.KS'),
             'fetch_yahoo_daymarket_price_direct':provider('direct', direct),
             '_fetch_yahoo_regular_close_price':provider('close', close)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<display_loader>', 'exec'), scope)
    return scope['load_display_live_price'], calls


@pytest.mark.parametrize('ticker, prices', [
    ('SOXL',(42.7,0,0)), ('SOXL',(0,42.6,0)), ('SOXL',(0,0,42.5)), ('SOXL',(0,0,0)),
    ('SOXL',(None,0,42.5)), ('005930.KS',(0,42.6,42.5)), ('005930.KS',(50000,0,0)),
])
def test_display_loader_numeric_result_and_provider_order_match_previous_code(ticker, prices):
    baseline = subprocess.check_output(['git','show','7ee2fc7d:app.py'], cwd=ROOT, encoding='utf-8-sig')
    current = (ROOT/'app.py').read_text(encoding='utf-8-sig')
    rich = [observed_price(x, ticker=ticker, source='existing provider', observed_at='2026-11-20T13:00:00Z')
            if x is not None and x > 0 else x for x in prices]
    old, old_calls = _display_loader(baseline, *rich)
    new, new_calls = _display_loader(current, *rich)
    result = new(ticker)
    assert result == old(ticker)
    assert new_calls == old_calls
    if result > 0:
        assert any(result is value for value in rich)
