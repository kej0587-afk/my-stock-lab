"""A recovered source close must reach report returns without the post quote."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.report_context import collect_report_context
from stock_lab_core.yahoo_daily_close import fill_history_close, missing_close_quote


DATES = pd.to_datetime(['2026-11-18', '2026-11-19', '2026-11-20'])


def frame(closes):
    return pd.DataFrame({key: closes for key in ('Open', 'High', 'Low', 'Close')}, index=DATES)


def inputs(route):
    soxl = frame([55., 45.30, 30.88])
    soxl.loc[DATES[-1], ['Open', 'High', 'Low']] = [42.40, 42.57, 29.82]
    quote = dict(symbol='SOXL', regularMarketPrice=30.88, regularMarketPreviousClose=45.30,
                 regularMarketTime=pd.Timestamp('2026-11-20T21:00:04Z').timestamp(),
                 regularMarketOpen=42.40, regularMarketDayHigh=42.57,
                 regularMarketDayLow=29.82, regularMarketVolume=533762471,
                 postMarketPrice=33.3694,
                 postMarketTime=pd.Timestamp('2026-11-21T00:59:59Z').timestamp())
    if route != 'complete':
        soxl.loc[DATES[-1], 'Close'] = float('nan')
    if route == 'shared_repair':
        raw = {'meta': {'symbol': 'SOXL', 'exchangeTimezoneName': 'America/New_York',
                        'regularMarketPrice': 30.88, 'regularMarketTime': quote['regularMarketTime']},
               'timestamp': [pd.Timestamp('2026-11-20T14:30:00Z').timestamp()],
               'indicators': {'quote': [{'close': [None], 'open': [42.40],
                                         'high': [42.57], 'low': [29.82]}]}}
        soxl = fill_history_close(soxl, 'SOXL', missing_close_quote(raw, 'SOXL', now='2026-11-21T00:59:59Z'))
    frames = {t: frame([100., 101., 102.]) for t in ('^GSPC', '^IXIC', '^DJI')}
    frames.update(SOXL=soxl, GOOGL=frame([280., 272.66, 265.29]))
    googl_quote = dict(symbol='GOOGL', regularMarketPrice=265.29, regularMarketPreviousClose=272.66,
                       regularMarketTime=pd.Timestamp('2026-11-20T21:00:01Z').timestamp(),
                       postMarketPrice=270.18, postMarketTime=pd.Timestamp('2026-11-21T00:59:57Z').timestamp())
    # Synthetic holdings, never a production account snapshot or trade instruction.
    rows = [{'ticker': t, 'name': t, 'qty': 1, 'current_w': 50, 'decision_code': 'UNCHANGED'} for t in ('SOXL', 'GOOGL')]
    return frames, {'US': {'SOXL': quote, 'GOOGL': googl_quote}}, rows


def collect(frames, quotes, rows, clock):
    return collect_report_context(rows, now=pd.Timestamp(clock), price_frames=frames,
                                  quote_data=quotes, economic_releases=[],
                                  calendar={'events': [], 'sources': []},
                                  live_frames={}, scenario_frames={})


@pytest.mark.parametrize('route', ['complete', 'shared_repair', 'report_repair'])
@pytest.mark.parametrize('clock,active_post', [('2026-11-21T00:59:59Z', True),
                                               ('2026-11-21T06:00:00Z', False)])
def test_report_keeps_repaired_regular_close_and_extended_quote_separate(route, clock, active_post):
    frames, quotes, rows = inputs(route)
    before = deepcopy((frames, quotes, rows))
    result = collect(frames, quotes, rows, clock)
    assert result['sessions']['US'] == '2026-11-20'
    for ticker, regular, previous, post in [('SOXL', 30.88, 45.30, 33.3694),
                                           ('GOOGL', 265.29, 272.66, 270.18)]:
        obs = result['prices'][ticker]
        assert (obs['date'], obs['previous_date']) == ('2026-11-20', '2026-11-19')
        assert obs['price'] == pytest.approx(regular)
        assert obs['return'] == pytest.approx(regular / previous - 1)
        if active_post:
            extended = result['extended_prices'][ticker]
            assert extended['price'] == pytest.approx(post)
            assert extended['previous_price'] == pytest.approx(regular)
            assert extended['return'] == pytest.approx(post / regular - 1)
        else:
            assert ticker not in result['extended_prices']
            assert ticker not in result['extended_reference_prices']
            assert '현재 미국 시간외' in result['extended_quote_status'][ticker]
    if route == 'shared_repair':
        assert result['price_frames']['SOXL'].attrs['daily_close_repair']['date'] == '2026-11-20'
    for ticker, old in before[0].items():
        pd.testing.assert_frame_equal(frames[ticker], old)
        assert frames[ticker].attrs == old.attrs
    assert (quotes, rows) == before[1:]


def test_unrecoverable_close_is_flagged_not_relabelled_or_filled_from_post():
    frames, quotes, rows = inputs('report_repair')
    quotes['US']['SOXL']['regularMarketTime'] -= 86400  # Prior-day quote cannot repair today's gap.
    result = collect(frames, quotes, rows, '2026-11-21T06:00:00Z')
    assert result['prices']['SOXL']['date'] == '2026-11-19'
    assert 'SOXL' in result['price_alignment']['unaligned']
    assert any('SOXL' in reason for reason in result['missing'])
    assert 'SOXL' not in result['extended_prices']
    assert pd.isna(frames['SOXL'].Close.iloc[-1])


@pytest.mark.parametrize('clock,active_post', [('2026-11-21T00:59:59Z', True),
                                               ('2026-11-21T02:00:00Z', False),
                                               ('2026-11-21T06:00:00Z', False)])
def test_rendered_holdings_distinguish_inactive_window_from_missing_quotes(clock, active_post):
    from stock_lab_core.market_memo import build_auto_market_memo

    frames, quotes, rows = inputs('shared_repair')
    now = pd.Timestamp(clock)
    context = collect(frames, quotes, rows, clock)
    before = deepcopy(rows)
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=now)
    line = next(line for line in report.splitlines() if line.startswith('SOXL(SOXL) |'))
    assert '-31.83% (2026-11-20 확정 종가)' in line
    if active_post:
        assert '+8.06%' in line and '애프터마켓' in line
        assert '별도 현재시세 표시 안 함' not in line
    else:
        assert '별도 현재시세 표시 안 함 · 기준일 종가 참조' in line
        assert '시세 미연결' not in line and '+8.06%' not in line
    assert rows == before
