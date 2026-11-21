from copy import deepcopy
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core.yahoo_daily_close import missing_close_quote, fill_history_close
from stock_lab_core.quote_observation import quote_provenance


def payload():
    return {
        "meta": {"symbol": "SOXL", "exchangeTimezoneName": "America/New_York",
                 "regularMarketPrice": 30.88, "regularMarketTime": 1795208404},
        "timestamp": [1795098600, 1795185000],
        "indicators": {"quote": [{"close": [45.30, None], "open": [53.99, 42.40],
                                     "high": [56.36, 42.57], "low": [44.94, 29.82],
                                     "volume": [330292000, 533762471]}]},
    }


def source():
    return pd.DataFrame({"Open": [53.99, 42.40], "High": [56.36, 42.57], "Low": [44.94, 29.82],
                         "Close": [45.30, float("nan")], "Adj Close": [45.30, float("nan")],
                         "Volume": [330292000, 533762471]}, index=pd.to_datetime(["2026-11-19", "2026-11-20"]))


NOW = "2026-11-21T01:00:00Z"


def test_null_close_recovers_matching_regular_trade_not_old_close_or_afterhours():
    raw, frame = payload(), source()
    before, old_frame = deepcopy(raw), frame.copy(deep=True)
    quote = missing_close_quote(raw, "SOXL", now=NOW)
    assert quote == 30.88
    assert quote_provenance(quote)["session"] == "regular"
    out = fill_history_close(frame, "SOXL", quote)
    assert out.Close.tolist() == [45.30, 30.88]
    assert pd.isna(out['Adj Close'].iloc[-1])
    pd.testing.assert_frame_equal(out.drop(columns='Close'), frame.drop(columns='Close'))
    pd.testing.assert_frame_equal(frame, old_frame)
    assert raw == before
    assert out.attrs['daily_close_repair']['date'] == '2026-11-20'


@pytest.mark.parametrize('change', ['symbol','date','preclose','range','timezone','valid_close','ohlc','future'])
def test_ambiguous_or_unfinished_source_is_not_repaired(change):
    raw = payload(); now = NOW
    if change == 'symbol': raw['meta']['symbol'] = 'SOXS'
    if change == 'date': raw['meta']['regularMarketTime'] -= 86400
    if change == 'preclose': now = '2026-11-20T20:59:00Z'
    if change == 'range': raw['meta']['regularMarketPrice'] = 50.
    if change == 'timezone': raw['meta']['exchangeTimezoneName'] = 'Asia/Seoul'
    if change == 'valid_close': raw['indicators']['quote'][0]['close'][-1] = 31.
    if change == 'ohlc': raw['indicators']['quote'][0]['open'][-1] = None
    if change == 'future': raw['meta']['regularMarketTime'] += 86400
    assert missing_close_quote(raw, 'SOXL', now=now) is None


@pytest.mark.parametrize('stamp', [None, float('nan'), pd.NaT])
def test_missing_timestamp_cannot_become_a_regular_close(stamp):
    raw = payload()
    raw['meta']['regularMarketTime'] = stamp
    assert missing_close_quote(raw, 'SOXL', now=NOW) is None
    assert missing_close_quote(payload(), 'SOXL', now=pd.NaT) is None


@pytest.mark.parametrize('kind', ['plain','wrong_symbol','different_date','valid_tail'])
def test_history_requires_exact_quote_and_missing_tail(kind):
    frame=source(); quote=missing_close_quote(payload(),'SOXL',now=NOW); ticker='SOXL'
    if kind=='plain': quote=float(quote)
    if kind=='wrong_symbol': ticker='SOXS'
    if kind=='different_date': frame.index=pd.to_datetime(['2026-11-18','2026-11-19'])
    if kind=='valid_tail': frame.iloc[-1,frame.columns.get_loc('Close')]=31.
    assert fill_history_close(frame,ticker,quote) is frame


def test_history_adapter_fetches_only_missing_us_tail(monkeypatch):
    from stock_lab_core import prices
    fetch=Mock(return_value=missing_close_quote(payload(),'SOXL',now=NOW))
    monkeypatch.setattr(prices,'_fetch_yahoo_regular_close_price',fetch)
    complete=source().fillna(30.88)
    assert prices._repair_missing_us_daily_close('SOXL',complete) is complete
    assert prices._repair_missing_us_daily_close('005930.KS',source()).Close.isna().iloc[-1]
    fetch.assert_not_called()
    assert prices._repair_missing_us_daily_close('SOXL',source()).Close.iloc[-1]==30.88
    fetch.assert_called_once_with('SOXL')


def test_duplicate_columns_keep_existing_cleaner_behavior_without_query(monkeypatch):
    from stock_lab_core import prices
    frame = source().fillna(30.88)
    frame = pd.concat([frame, frame[['Close']]], axis=1)
    fetch = Mock(side_effect=AssertionError('ambiguous duplicate columns must not query'))
    monkeypatch.setattr(prices, '_fetch_yahoo_regular_close_price', fetch)
    expected = prices._clean_ohlcv_frame(frame, keep_adj_close=True)
    actual = prices._clean_ohlcv_frame(prices._repair_missing_us_daily_close('SOXL', frame), keep_adj_close=True)
    pd.testing.assert_frame_equal(actual, expected)
    fetch.assert_not_called()


def test_timestamped_afterhours_precedes_untimed_daytime_after_session(monkeypatch):
    from stock_lab_core import prices
    monkeypatch.setattr(prices,'_us_equity_regular_session_active',lambda:False)
    monkeypatch.setattr(prices,'_us_equity_extended_session_active',lambda:False)
    monkeypatch.setattr(prices,'_fetch_yahoo_overnight_page_price',lambda t:0.)
    monkeypatch.setattr(prices,'_fetch_yahoo_quote',lambda t:32.94)
    kis=Mock(side_effect=AssertionError('untimed old daytime quote must not override chart'))
    monkeypatch.setattr(prices,'_fetch_kis_us_quote_price',kis)
    assert prices._fetch_us_realtime_price('SOXL')==32.94
    kis.assert_not_called()


def test_batch_history_reuses_same_missing_close_repair(monkeypatch):
    from stock_lab_core import prices
    frame=source()
    frame.columns=pd.MultiIndex.from_tuples([('SOXL',c) for c in frame.columns])
    monkeypatch.setattr(prices.yf,'download',lambda *a,**kw:frame)
    monkeypatch.setattr(prices,'_fetch_yahoo_regular_close_price',lambda t:missing_close_quote(payload(),t,now=NOW))
    monkeypatch.setattr(prices,'_maybe_align_ohlcv_to_live_price',lambda ticker,df:df)
    prices.load_price_frames_batch.clear()
    out=prices.load_price_frames_batch(['SOXL'],'5d')['SOXL']
    assert out.index[-1]==pd.Timestamp('2026-11-20') and out.Close.iloc[-1]==30.88
    assert out.attrs['daily_close_repair']['source']=='yahoo_regular_close_metadata'
    prices.load_price_frames_batch.clear()
