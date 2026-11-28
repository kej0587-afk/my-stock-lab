"""Known stale quote repair; no provider requests, policy or golden changes."""
from types import SimpleNamespace
import json
from pathlib import Path
import socket

import pandas as pd
import pytest

from stock_lab_core import decision_engine as engine, decision_quote_eligibility as eligibility
from stock_lab_core.decision_inputs import prepare_decision_price_inputs
from stock_lab_core.quote_observation import observed_price
from stock_lab_core.ta_engine import build_indicators
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.monthly_rebalance import compute_monthly_plan
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import SCENARIOS, _bench_info, _to_jsonable
from stock_lab_core.signal_basis import build_signal_basis, render_signal_basis, quote_display_label
from unittest.mock import MagicMock
from tests.test_monthly_signal_safety import _multiplier

NOW = pd.Timestamp('2026-11-27T21:10:00Z')


@pytest.fixture(autouse=True)
def fixed_clock_no_network(monkeypatch):
    monkeypatch.setattr(eligibility, 'datetime', SimpleNamespace(now=lambda _: NOW.to_pydatetime()))
    def forbidden(*args, **kwargs):
        raise AssertionError('Eligibility regressions must stay offline')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)


def quote(price=95., minutes=30, session='post', ticker='GOOGL', timed=True):
    return observed_price(price, ticker=ticker, source='fixed Yahoo',
        observed_at=NOW-pd.Timedelta(minutes=minutes) if timed else None, session=session)


@pytest.mark.parametrize('minutes,session,now,rejected', [
    (1, 'post', NOW, False), (20, 'post', NOW, False),
    (20.01, 'post', NOW, True), (30, 'post', NOW, True),
    (-1, 'post', NOW, True), (1, 'pre', NOW, True),
    (1, 'post', pd.Timestamp('2026-11-27T22:01:00Z'), True),
])
def test_known_extended_eligibility(minutes, session, now, rejected):
    assert bool(eligibility.decision_quote_rejection(quote(minutes=minutes, session=session), 'GOOGL', now=now)) == rejected


@pytest.mark.parametrize('value,manual', [
    (95., False), (quote(timed=False), False), (quote(session='unknown'), False),
    (quote(session='regular', minutes=300), False), (quote(), True),
])
def test_unknown_manual_regular_fallback_contract_preserved(value, manual):
    assert not eligibility.decision_quote_rejection(value, 'GOOGL', now=NOW, manual=manual)


def test_timed_wrong_symbol_is_rejected():
    assert eligibility.decision_quote_rejection(quote(ticker='SOXL', minutes=1), 'GOOGL', now=NOW)


@pytest.mark.parametrize('session,now', [
    ('pre', '2026-11-27T14:00:00Z'), ('overnight', '2026-11-27T06:00:00Z'),
    ('day', '2026-11-27T06:00:00Z'), ('post', '2026-11-25T22:00:00Z'),
])
def test_other_fresh_extended_windows_preserved(session, now):
    clock = pd.Timestamp(now)
    value = observed_price(95, ticker='GOOGL', source='fixed', session=session,
                           observed_at=clock-pd.Timedelta(minutes=1))
    assert not eligibility.decision_quote_rejection(value, 'GOOGL', now=clock)


@pytest.mark.parametrize('precomputed', [False, True])
@pytest.mark.parametrize('gap', [-.05, .002])
def test_stale_scalar_and_precomputed_overlay_restore_source(monkeypatch, precomputed, gap):
    source = make_price_df(seed=21)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    before = source.copy(deep=True)
    value = quote(float(source.Close.iloc[-1])*(1+gap))
    legacy = engine.apply_live_price_with_indicators(source, value, 'GOOGL', build_indicators)
    legacy_before = legacy[0].copy(deep=True)
    out = prepare_decision_price_inputs(source, 'GOOGL', value, build_indicators=build_indicators,
        apply_live_price_with_indicators=engine.apply_live_price_with_indicators,
        _live_indicator_context=legacy if precomputed else None, quote_now=NOW)
    assert out['cur_p'] == source.Close.iloc[-1] and not out['live_price_used']
    assert out['last'].RSI == source.RSI.iloc[-1]
    assert out['df'].attrs['decision_quote_rejection']
    pd.testing.assert_frame_equal(source, before)
    pd.testing.assert_frame_equal(legacy[0], legacy_before)
    shared = eligibility.prepare_eligible_live_context(source, value, 'GOOGL', build_indicators, now=NOW)
    assert not shared[1] and not shared[2]
    pd.testing.assert_frame_equal(shared[0], out['df'])


def test_shared_fresh_and_manual_preparation_matches_legacy(monkeypatch):
    source = make_price_df(seed=21)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    for value, manual in [(quote(float(source.Close.iloc[-1])*.95, minutes=1), False),
                          (float(source.Close.iloc[-1])*.95, False),
                          (quote(float(source.Close.iloc[-1])*.95), True)]:
        before = engine.apply_live_price_with_indicators(source, value, 'GOOGL', build_indicators)
        after = eligibility.prepare_eligible_live_context(source, value, 'GOOGL', build_indicators, now=NOW, manual=manual)
        pd.testing.assert_frame_equal(before[0], after[0])
        assert before[1:] == after[1:]


def test_exact_boundary_reads_one_clock_even_with_shared_wrapper_callback(monkeypatch):
    source = make_price_df(seed=21)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    clocks = []
    def advancing_clock(_):
        stamp = NOW + pd.Timedelta(milliseconds=len(clocks))
        clocks.append(stamp)
        return stamp.to_pydatetime()
    monkeypatch.setattr(eligibility, 'datetime', SimpleNamespace(now=advancing_clock))
    value = quote(float(source.Close.iloc[-1])*.95, minutes=20)
    result = prepare_decision_price_inputs(source, 'GOOGL', value, build_indicators=build_indicators,
        apply_live_price_with_indicators=eligibility.prepare_eligible_live_context)
    assert len(clocks) == 1
    assert result['live_price_used'] and result['cur_p'] == float(value)
    assert result['df'].LiveQuoteOnly.iloc[-1]
    assert result['df'].attrs['decision_quote_assessment']['checked_at'] == NOW.isoformat()


@pytest.mark.parametrize('initial_age,second_clock,accepted', [
    (20., NOW+pd.Timedelta(milliseconds=1), True),
    (20.+1/60000, NOW-pd.Timedelta(milliseconds=1), False),
])
def test_precomputed_adjudication_is_shared_across_boundary(monkeypatch, initial_age, second_clock, accepted):
    source = make_price_df(seed=21)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    value = quote(float(source.Close.iloc[-1])*.95, minutes=initial_age)
    context = eligibility.prepare_eligible_live_context(source, value, 'GOOGL', build_indicators, now=NOW)
    result = prepare_decision_price_inputs(source, 'GOOGL', value, build_indicators=build_indicators,
        apply_live_price_with_indicators=eligibility.prepare_eligible_live_context,
        _live_indicator_context=context, quote_now=second_clock)
    assert bool(context[1]) == result['live_price_used'] == accepted
    assert result['cur_p'] == (float(value) if accepted else source.Close.iloc[-1])
    pd.testing.assert_frame_equal(context[0], result['df'])
    assert result['df'].attrs['decision_quote_assessment'] == context[0].attrs['decision_quote_assessment']
    basis = build_signal_basis(source, context, ticker='GOOGL', input_price=value, calculated_at=second_clock.isoformat())
    assert ('미확정' in basis['가격반영']) == accepted
    assert bool(basis['자료주의']) != accepted


@pytest.mark.parametrize('first_age,second_age', [(30, 1), (1, 30)])
def test_precomputed_adjudication_cannot_be_reused_for_changed_observation(monkeypatch, first_age, second_age):
    source = make_price_df(seed=21)
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    value = float(source.Close.iloc[-1])*.95
    prior = eligibility.prepare_eligible_live_context(source, quote(value, minutes=first_age), 'GOOGL', build_indicators, now=NOW)
    result = prepare_decision_price_inputs(source, 'GOOGL', quote(value, minutes=second_age),
        build_indicators=build_indicators, apply_live_price_with_indicators=eligibility.prepare_eligible_live_context,
        _live_indicator_context=prior, quote_now=NOW)
    assert result['live_price_used'] == (second_age == 1)
    assert result['cur_p'] == (value if second_age == 1 else source.Close.iloc[-1])


def test_us_sizing_hint_never_divides_krw_by_unknown_or_usd_price():
    for currency in (None, 'USD'):
        hint = engine.build_position_sizing_hint(True, 10, 10_000_000, 155.4, False, price_currency=currency)
        assert '330,000원' in hint and '주 |' not in hint
    kr = engine.build_position_sizing_hint(True, 10, 10_000_000, 10_000, False, price_currency='KRW')
    assert '330,000원 / 약 33주' in kr


def test_engine_to_final_monthly_amount_fixed_input(app_module, monkeypatch):
    app = app_module
    assert app.apply_live_price_with_indicators is eligibility.prepare_eligible_live_context
    _, px, rs, slope, kwargs = next(s for s in SCENARIOS if s[0] == 'free_stock_new_entry_leader')
    source = make_price_df(**px)
    source.index = _exchange_schedule('US', '2025-01-01', '2026-11-27').index[-len(source):]
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    monkeypatch.setattr(app, 'get_rs_score', lambda *a: rs)
    monkeypatch.setattr(app, 'get_rs_slope', lambda *a: slope)
    monkeypatch.setattr(app, 'get_auto_benchmark_info', lambda *a: _bench_info())
    monkeypatch.setattr(app, 'get_sector_flow_state', lambda *a: 'fixed flow')
    kwargs = dict(kwargs, ticker='GOOGL', asset_class='us_stock', name='Synthetic audit stock')
    value = quote(float(source.Close.iloc[-1])*.95)
    prepared = engine.apply_live_price_with_indicators(source, value, 'GOOGL', build_indicators)
    shared = app.apply_live_price_with_indicators(source, value, 'GOOGL', build_indicators)
    assert not shared[1] and shared[0].Close.iloc[-1] == source.Close.iloc[-1]
    baseline = app.calc_scores_and_decision(df=source, live_price=0., **kwargs)
    stale = app.calc_scores_and_decision(df=source, live_price=value, _live_indicator_context=prepared, **kwargs)
    # Untimed floats intentionally preserve the old numerical policy: this is the
    # pre-fix stale acceptance counterfactual, not a new actual account trade.
    legacy = app.calc_scores_and_decision(df=source, live_price=float(value), **kwargs)
    assert stale['decision_code'] == baseline['decision_code'] == 'NEW_ENTRY_LEADER'
    assert legacy['decision_code'] == 'WATCH_WAIT_ENTRY'
    assert stale['buy_amt'] == baseline['buy_amt'] == legacy['buy_amt'] == 1_000_000
    assert stale['cur_p'] == baseline['cur_p']
    assert stale['macro_state'] == baseline['macro_state'] == 'NORMAL'
    assert '330,000원' in stale['sizing_hint'] and '주 |' not in stale['sizing_hint']
    def plan(result):
        holdings = pd.DataFrame([dict(티커='GOOGL', 자산명='Synthetic', 목표비중=10,
            bucket='core', asset_class='us_stock', 현재가=result['cur_p'], 매입가=0,
            보유량=0, is_etf=False, 운용대상=True)])
        monthly = compute_monthly_plan(holdings, total_invest=1_000_000, usdkrw=1400.,
            signal_cache={'GOOGL':result['dec']}, signal_decisions={'GOOGL':result},
            always_invest_set=set(), redistribute_mode=False, accumulated={},
            signal_multiplier=_multiplier, month='2026-11', account_scope='synthetic')
        row = monthly['rows'][0]
        assert monthly['alloc']['GOOGL'] == row['final_alloc']  # same allocation consumed by L3
        return row
    b, s, old = plan(baseline), plan(stale), plan(legacy)
    for key in ('final_alloc', 'rec_shares', 'rec_krw', 'effective_alloc'):
        assert s[key] == b[key]
    assert s['final_alloc'] == 1_000_000 and s['rec_shares'] == 4
    assert old['final_alloc'] == old['rec_shares'] == 0
    # A financial hard block must remain independent of the repaired quote.
    blocked = dict(kwargs, fin_score=1, is_free=False, has_pos=True)
    for price in (0., value):
        result = app.calc_scores_and_decision(df=source, live_price=price, **blocked)
        assert result['decision_code'] == 'HARD_BLOCK_FINANCIAL_F'
    output = Path(__file__).parents[1]/'cache/delayed_quote_audit_20261128'
    output.mkdir(parents=True, exist_ok=True)
    (output/'fixed_account_amount.json').write_text(json.dumps({
        'synthetic_account_only':True, 'not_execution_or_live_account':True,
        'legacy_stale':{k:old[k] for k in ('final_alloc','rec_shares','rec_krw')},
        'repaired':{k:s[k] for k in ('final_alloc','rec_shares','rec_krw')},
    }, indent=2), encoding='utf-8')


def test_all_18_fresh_results_preserved_delayed_overlay_zero_and_provenance(app_module, monkeypatch):
    app = app_module
    monkeypatch.setattr(app, 'get_auto_benchmark_info', lambda *a: _bench_info())
    monkeypatch.setattr(app, 'get_sector_flow_state', lambda *a: 'fixed flow')
    sessions = _exchange_schedule('US', '2025-01-01', '2026-11-27').index
    fresh_equal, delayed_overlays, rows = 0, 0, []
    for sid, px, rs, slope, original_kwargs in SCENARIOS:
        if original_kwargs['is_etf']:
            continue
        source = make_price_df(**px)
        source.index = sessions[-len(source):]
        monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
        monkeypatch.setattr(app, 'get_rs_score', lambda *a: rs)
        monkeypatch.setattr(app, 'get_rs_slope', lambda *a: slope)
        kwargs = dict(original_kwargs, ticker='GOOGL', asset_class='us_stock', name='Synthetic audit stock')
        baseline = app.calc_scores_and_decision(df=source, live_price=0., **kwargs)
        for gap in (-.05, .05):
            value = float(source.Close.iloc[-1])*(1+gap)
            fresh, stale = quote(value, minutes=1), quote(value, minutes=30)
            legacy = engine.apply_live_price_with_indicators(source, fresh, 'GOOGL', build_indicators)
            context = app.apply_live_price_with_indicators(source, fresh, 'GOOGL', build_indicators)
            pd.testing.assert_frame_equal(context[0], legacy[0])
            old = app.calc_scores_and_decision(df=source, live_price=value, _live_indicator_context=legacy, **kwargs)
            current = app.calc_scores_and_decision(df=source, live_price=fresh, _live_indicator_context=context, **kwargs)
            assert _to_jsonable(current) == _to_jsonable(old)
            fresh_equal += 1
            stale_context = app.apply_live_price_with_indicators(source, stale, 'GOOGL', build_indicators)
            delayed_overlays += int(stale_context[1])
            corrected = app.calc_scores_and_decision(df=source, live_price=stale, _live_indicator_context=stale_context, **kwargs)
            assert _to_jsonable(corrected) == _to_jsonable(baseline)
            basis = build_signal_basis(source, stale_context, ticker='GOOGL', input_price=stale, calculated_at=NOW.isoformat())
            source_basis = build_signal_basis(source, (source, False, ''), ticker='GOOGL', input_price=0., calculated_at=NOW.isoformat())
            assert basis['가격입력ID'] == source_basis['가격입력ID']
            assert basis['가격반영'] == '가격 이력 기준'
            assert basis['현재가출처'] == '별도 현재가 미연결 · 가격 이력 기준'
            assert basis['현재가관측시각'] == '미확인' and basis['현재가관측UTC'] == ''
            assert basis['제외시세출처'] == 'fixed Yahoo'
            assert basis['제외시세관측UTC'] == (NOW-pd.Timedelta(minutes=30)).isoformat()
            assert '20분 초과' in basis['자료주의'] and '제외' in basis['자료주의']
            ui = MagicMock()
            render_signal_basis(ui, basis)
            ui.warning.assert_called_once_with(basis['자료주의'])
            assert '조회 시세 제외' in quote_display_label(auto_price=stale, rejection_reason=basis['시세제외사유'])
            rows.append(dict(scenario=sid, gap=gap, fresh_equal=True, delayed_overlay=bool(stale_context[1]),
                             decision=corrected['decision_code'], basis=basis))
    assert fresh_equal == 18 and delayed_overlays == 0
    output = Path(__file__).parents[1]/'cache/delayed_quote_audit_20261128'
    output.mkdir(parents=True, exist_ok=True)
    (output/'fixed18_after.json').write_text(json.dumps(dict(fresh_equal=fresh_equal,
        delayed_overlays=delayed_overlays, rows=rows), ensure_ascii=False, indent=2), encoding='utf-8')
