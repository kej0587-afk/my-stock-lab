"""Freeze one source/quote/clock across the existing price consumers; no network."""
from copy import deepcopy
from datetime import datetime
import socket
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_lab_core import decision_engine as engine
from stock_lab_core.decision_inputs import prepare_decision_price_inputs
from stock_lab_core.leveraged_comparison import comparison_context, completed_comparison_row
from stock_lab_core.leveraged_watch import _build_watch_row
from stock_lab_core.leveraged_quote_view import quote_evidence, render_quote_evidence
from stock_lab_core.report_evidence import price_observation
from stock_lab_core.report_intraday import extended_quote_text
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.ta_engine import build_indicators
from tests.fixtures_price import make_price_df


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Frozen audit must not fetch newer prices")
    monkeypatch.setattr(socket.socket, 'connect', fail)
    monkeypatch.setattr(socket, 'getaddrinfo', fail)


def trace_paths(source, ticker, raw, now):
    """The same supplied scalar is deliberate: eliminate provider/time differences."""
    price = raw['postMarketPrice']
    live = engine.apply_live_price_with_indicators(source, price, ticker, build_indicators)
    decision = prepare_decision_price_inputs(source, ticker, price,
        build_indicators=build_indicators, apply_live_price_with_indicators=engine.apply_live_price_with_indicators,
        _live_indicator_context=live)
    context = comparison_context('SOXL', now=now)
    watch = completed_comparison_row((ticker, '비교 상품', ticker), source, context=context,
        pct_text=lambda value: f'{value:+.2f}%', judge=lambda *args: 'fixed callback')
    report = price_observation(source, ticker, now)
    evidence = quote_evidence(ticker, raw, now)
    audit = evidence['audit']
    report_context = {'sessions': {'US': report['date']},
        'extended_prices': {ticker: audit['extended']} if audit['extended'] else {},
        'extended_reference_prices': {ticker: audit['delayed_reference']} if audit['delayed_reference'] else {}}
    return dict(decision=decision, chart=live[0], watch=watch, report=report, evidence=evidence,
                briefing=extended_quote_text(report_context, ticker, now))


@pytest.mark.parametrize('ticker', ['SOXL', 'GOOGL'])
@pytest.mark.parametrize('state', ['fresh', 'delayed', 'closed'])
def test_one_input_exposes_intended_basis_and_scalar_validation_gap(monkeypatch, ticker, state):
    source = make_price_df(seed=21)
    source.index = _exchange_schedule('US', '2025-01-01', '2026-11-27').index[-len(source):]
    source = build_indicators(source)
    saved = source.copy(deep=True)
    close, previous = source.Close.iloc[-1], source.Close.iloc[-2]
    price = float(close)*.95
    now = datetime.fromisoformat('2026-11-27T21:10:00+00:00' if state != 'closed' else '2026-11-27T23:10:00+00:00')
    trade = pd.Timestamp('2026-11-27T21:09:00Z' if state != 'delayed' else '2026-11-27T20:40:00Z')
    raw = dict(symbol=ticker, regularMarketPrice=float(close), regularMarketPreviousClose=float(previous),
               regularMarketTime=pd.Timestamp('2026-11-27T18:00:01Z').timestamp(),
               postMarketPrice=price, postMarketTime=trade.timestamp())
    monkeypatch.setattr(engine, '_get_live_price_row_date', lambda _: source.index[-1])
    result = trace_paths(source, ticker, raw, now)
    d, chart, watch, report = (result[k] for k in ('decision', 'chart', 'watch', 'report'))
    assert d['cur_p'] == chart.Close.iloc[-1] == price
    assert chart.LiveQuoteOnly.iloc[-1] and pd.isna(chart.Volume.iloc[-1])
    assert d['last']['RSI'] == chart.RSI.iloc[-1] != source.RSI.iloc[-1]
    assert engine.calc_atr_for_decision(chart) == engine.calc_atr_for_decision(source)
    assert chart.MFI.iloc[-1] == source.MFI.iloc[-1]
    assert report['price'] == close
    assert watch['_1d']/100 == pytest.approx(report['return'])
    assert d['regular_day_ret'] == pytest.approx(report['return'])
    assert d['live_ref_ret'] == pytest.approx(-.05)
    if state == 'fresh':
        assert result['evidence']['price'] == price
        assert '-5.00%' in result['briefing'] and '마감 후' in result['briefing']
    else:
        # Observed limitation, not approval: scalar input lacks timestamp validation;
        # report/evidence reject promotion while legacy decision overlay still applies.
        assert 'price' not in result['evidence']
        assert not result['evidence']['audit']['extended']
        assert ('지연 참고' in result['briefing']) if state == 'delayed' else result['briefing'] == ''
    pd.testing.assert_frame_equal(source, saved)


def test_legacy_watch_basis_is_not_completed_session_basis():
    frame = pd.DataFrame({'Close':[100.,110.]}, index=pd.to_datetime(['2026-11-25','2026-11-27']))
    row = _build_watch_row(('QQQ','기초 ETF','QQQ'), load_quote=lambda _:104.5,
        load_history=lambda *args:frame, pct_text=str, judge=lambda *args:'legacy')
    assert row['_1d'] == pytest.approx(4.5)  # quote / prior daily close; not 10% regular or -5% after


@pytest.mark.parametrize('delay', [1,30])
def test_panel_wording_does_not_claim_all_other_inputs_exclude_aftermarket(delay):
    now = datetime.fromisoformat('2026-11-27T21:10:00+00:00')
    raw = dict(symbol='SOXL', regularMarketPrice=100, regularMarketPreviousClose=90,
               regularMarketTime=pd.Timestamp('2026-11-27T18:00:01Z').timestamp(),
               postMarketPrice=95, postMarketTime=(pd.Timestamp(now)-pd.Timedelta(minutes=delay)).timestamp())
    before = deepcopy(raw)
    st = MagicMock()
    render_quote_evidence(st, 'SOXL', now=now, fetch_quote=lambda _:raw)
    captions = ' '.join(str(call.args[0]) for call in st.caption.call_args_list)
    assert '판정·차트 입력에 반영하지 않는' not in captions
    assert '현재가격·판정 입력에 반영하지 않음' not in captions
    assert '가격 기준' in captions
    assert raw == before
