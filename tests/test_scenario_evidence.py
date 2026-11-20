"""Completed-session scenario observations must not become new investment rules."""

from copy import deepcopy
import math
import socket

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.scenario_evidence import (
    build_scenario_evidence, completed_scenario_frame, conditional_price_rows, scenario_evidence_rows,
)
from stock_lab_core.precision_scenarios import build_precision_scenarios, render_precision_scenarios
from tests.test_precision_scenarios import case, assert_unchanged, FakeUI


@pytest.fixture(autouse=True)
def no_collection(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Scenario analysis must reuse captured bars")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def bars():
    dates = pd.bdate_range('2026-07-01', periods=90)
    prices = 100 + 9*np.sin(np.arange(90)*.37) + .05*np.arange(90)
    return pd.DataFrame({'Open': prices, 'High': prices+2, 'Low': prices-2,
                         'Close': prices+.3, 'Volume': 1000+np.arange(90)*5, 'MFI': 42.}, index=dates)


def evidence(bars, **kwargs):
    return build_scenario_evidence(bars, bars.index[-1].date().isoformat(), **kwargs)


def test_source_prices_volume_and_pivot_confirmation_are_measured(bars):
    before = bars.copy(deep=True)
    e = evidence(bars)
    pd.testing.assert_frame_equal(bars, before)
    assert e['fresh'] and e['available'] and e['close'] == bars.Close.iloc[-1]
    assert e['support']['price'] < e['close'] < e['recovery']['price'] < e['target']['price']
    assert e['measures']['volume_ratio'] == pytest.approx(bars.Volume.iloc[-1]/bars.Volume.iloc[-21:-1].mean())
    for level in e['levels']:
        assert level['known_at'] <= e['asof']
        if level['source'].startswith('확인'):
            assert bars.index.get_loc(pd.Timestamp(level['known_at'])) - bars.index.get_loc(pd.Timestamp(level['at'])) == 3
    assert e['rr'] == pytest.approx((e['target']['price']-e['recovery']['price'])/(e['recovery']['price']-e['support']['price']))


@pytest.mark.parametrize('quote_only', [False, True])
def test_future_and_vendor_partial_rows_never_enter_complete_observations(bars, quote_only):
    expected = evidence(bars)
    later = bars.iloc[[-1]].copy()
    later.index = [bars.index[-1]+pd.Timedelta(days=1)]
    later.loc[:,['Open','High','Low','Close']] = 9999
    later['Volume'] = 1e15
    later['LiveQuoteOnly'] = quote_only
    mixed = pd.concat([bars,later])
    actual = build_scenario_evidence(mixed, expected['asof'])
    assert actual == expected


def test_same_date_quote_only_overlay_does_not_claim_latest_complete_price(bars):
    bars['LiveQuoteOnly'] = False
    bars.loc[bars.index[-1], 'LiveQuoteOnly'] = True
    e = evidence(bars)
    assert e['available'] and not e['fresh']
    assert e['asof'] == bars.index[-2].date().isoformat()
    assert conditional_price_rows(e, 'SOXL') == []


@pytest.mark.parametrize('cutoff', [None, '', True, 0, pd.NA, pd.NaT, 'bad'])
def test_unknown_calendar_never_guesses_complete_session(bars, cutoff):
    e = build_scenario_evidence(bars, cutoff)
    assert not e['available'] and conditional_price_rows(e, 'TEST') == []


@pytest.mark.parametrize('fault', ['reversed', 'duplicate', 'nat', 'nan', 'inf', 'zero', 'range', 'missing'])
def test_invalid_source_is_not_silently_repaired(bars, fault):
    cutoff = bars.index[-1].date().isoformat()
    if fault == 'reversed': bars = bars.iloc[::-1]
    elif fault == 'duplicate': bars.index = [*bars.index[:-1], bars.index[-2]]
    elif fault == 'nat': bars.index = [*bars.index[:-1], pd.NaT]
    elif fault == 'missing': bars = bars.drop(columns='Close')
    else: bars.iloc[-1, bars.columns.get_loc('High')] = {'nan': math.nan, 'inf': math.inf, 'zero': 0, 'range': 1}[fault]
    assert not build_scenario_evidence(bars, cutoff)['available']


@pytest.mark.parametrize('n', [1, 6, 10, 20, 25])
def test_short_histories_report_period_limits_without_filling(bars, n):
    e = evidence(bars.tail(n))
    assert e['measures']['range_ratio'] is None
    assert e['range']['bars'] == min(n,20)
    if n < 21: assert e['measures']['volume_ratio'] is None
    if n < 20: assert e['measures']['ma20'] is None


@pytest.mark.parametrize('value', [math.nan, math.inf, -1, 'missing'])
def test_missing_volume_leaves_price_structure_intact(bars, value):
    bars['Volume'] = bars.Volume.astype(object)
    bars.loc[bars.index[-1], 'Volume'] = value
    e = evidence(bars)
    assert e['available'] and e['support'] and e['recovery']
    assert e['measures']['volume_ratio'] is None
    assert '자료 부족' in scenario_evidence_rows(e,'TEST')[3]['관측']


def test_zero_volume_is_observed_not_missing(bars):
    bars.loc[bars.index[-1], 'Volume'] = 0
    assert evidence(bars)['measures']['volume_ratio'] == 0


def test_broken_old_low_above_close_is_resistance_not_support(bars):
    bars.loc[bars.index[-1], ['Open','High','Low','Close']] = [80,82,79,81]
    e = evidence(bars)
    assert e['support'] is None
    assert e['recovery']['price'] > e['close']
    assert e['rr'] is None
    assert 'R/R 미산출' in conditional_price_rows(e,'TEST')[0]['가격비율']


def test_future_extreme_cannot_confirm_pivot_at_earlier_cutoff(bars):
    cutoff = bars.index[-4]
    e = build_scenario_evidence(bars, cutoff)
    assert all(pd.Timestamp(row['known_at']) <= cutoff for row in e['levels'])
    assert e == build_scenario_evidence(bars.iloc[:-3], cutoff)


@pytest.mark.parametrize('profile_date', ['2020-01-01', None, 'current'])
def test_profile_requires_matching_session(bars, profile_date):
    profile = {'ok':True,'poc':{'low':90,'high':100}, 'asof':bars.index[-1].strftime('%Y-%m-%d') if profile_date=='current' else profile_date}
    assert bool(evidence(bars,profile=profile)['poc']) is (profile_date=='current')


@pytest.mark.parametrize('ticker', ['SOXL','RAM','BITX','418660.KS','MSFT'])
def test_generic_prices_have_instrument_currency_no_leverage_multiplier(bars,ticker):
    e=evidence(bars)
    rows=conditional_price_rows(e,ticker)
    assert len(rows)==3
    assert ('$', '₩')[ticker.endswith('.KS')] in rows[0]['확인 가격']
    assert '승률 아님' in rows[0]['가격비율']
    assert '자동 매도' in rows[1]['가격비율']
    assert '확정 아님' in rows[2]['가격비율']


def test_observations_enrich_damaged_b_focus_without_modifying_gate_plan_or_inputs(case,bars):
    decision, context, plan=case
    context.update(daily_source=bars,expected_close=bars.index[-1].strftime('%Y-%m-%d'))
    context['multi_timeframe']['월봉']['snapshot']['state']='추세훼손'
    decision['live_quote']={'volume_status':'missing_live_volume'}
    before=deepcopy(case)
    model=build_precision_scenarios(decision,'TEST',context,plan,has_pos=True)
    for current, previous in zip(case,before): assert_unchanged(current,previous)
    assert model['focus'].startswith('B안') and not model['ready']['execution_allowed']
    assert not model['flow_known'] and model['completed_evidence']['measures']['volume_ratio'] is not None
    assert len(model['price_rows'])==3
    assert '현재 근거 부족' not in model['scenarios'][2]['evidence']
    assert '현재 채널 가격 제시 보류' not in model['scenarios'][0]['evidence']
    assert '기존 최종 체크를 우회하지 않음' in model['scenarios'][0]['condition']
    ui=FakeUI()
    render_precision_scenarios(ui,model)
    assert ui.tab_names[0].startswith('B안')
    output='\n'.join(x[0] for x in ui.markdowns)
    assert '확인 가격' in output and '진폭' in output and '시세 전용 봉 제외' in output
    assert all(x=={'expanded':False} for x in ui.expanders)


def test_quote_is_shown_separately_and_cannot_change_source_prices(case,bars):
    decision,context,plan=case
    context.update(daily_source=bars,expected_close=bars.index[-1].strftime('%Y-%m-%d'))
    base=build_precision_scenarios(decision,'TEST',context,plan)
    context['quote_evidence']={'status':'연결됨','price':999,'session':'데이마켓','as_of':'2026-11-20 16:00 KST'}
    current=build_precision_scenarios(decision,'TEST',context,plan)
    assert current['completed_evidence']==base['completed_evidence']
    assert current['price_rows']==base['price_rows']
    assert '999.00' in current['quote_basis'] and '혼합하지 않음' in current['quote_basis']


def test_no_negative_or_missing_reference_becomes_a_recommendation(bars):
    e=build_scenario_evidence(bars,bars.index[-1]+pd.Timedelta(days=1))
    assert e['available'] and not e['fresh']
    assert scenario_evidence_rows(e,'TEST') and not conditional_price_rows(e,'TEST')


@pytest.mark.parametrize('quote_position', ['below','inside','above'])
@pytest.mark.parametrize('as_string', [False, True])
def test_intraday_reference_never_confirms_daily_break(case,bars,quote_position,as_string):
    d,c,p=case
    c.update(daily_source=bars,expected_close=bars.index[-1].strftime('%Y-%m-%d'))
    e=evidence(bars)
    price={'below':e['support']['price']-1,'inside':e['close'],'above':e['recovery']['price']+1}[quote_position]
    c['quote_evidence']={'status':'연결됨','price':str(price) if as_string else price,'session':'시간외','as_of':'2026-11-20 05:30 KST'}
    model=build_precision_scenarios(d,'TEST',c,p)
    assert '확정' in model['quote_basis']
    assert '종가 이탈 확정 전' in model['quote_basis'] if quote_position=='below' else True
    assert model['ready']['execution_allowed'] is False
    assert model['completed_evidence']['close']==bars.Close.iloc[-1]


def test_production_adapter_supplies_source_cutoff_and_exports_analysis():
    import ast
    from pathlib import Path
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='build_precision_scenarios']
    assert len(calls)==1
    supplied={k.value: v for k,v in zip(calls[0].args[2].keys,calls[0].args[2].values)}
    assert isinstance(supplied['daily_source'],ast.Name) and supplied['daily_source'].id=='df'
    assert 'expected_close' in supplied and 'completed_profile' in supplied and 'quote_evidence' in supplied
    assert any(isinstance(n,ast.Constant) and n.value=='scenario_analysis' for n in ast.walk(tree))
    renderer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='render_precision_candlestick_chart')
    expected=[k.value for n in ast.walk(renderer) if isinstance(n,ast.Call) for k in n.keywords if k.arg=='chart_expected_close']
    assert len(expected)==1 and isinstance(expected[0],ast.Call)
