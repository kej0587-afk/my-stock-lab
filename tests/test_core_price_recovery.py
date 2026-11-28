from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from scripts.core_price_recovery import recover_empty_frame, assert_only_target_changed


def inputs():
    days = pd.bdate_range('2020-01-01', periods=150)
    frame = pd.DataFrame({'Open': 10., 'High': 11., 'Low': 9., 'Close': 10.,
                          'Adj Close': 9.5, 'Volume': 100.}, index=days)
    snapshot = {'frames': {'000001.KS': frame * np.nan, 'OTHER': frame.copy()},
                'kinds': {'000001.KS': 'stock'}, 'markets': {'000001.KS': 'KR'},
                'flow_tickers': ['OTHER'], 'original_candidates': [],
                'sessions': {'KR': days}, 'cutoff': str(days[-1].date()),
                'source': {'start': '2020-01-01', 'end_exclusive': '2021-01-01', 'auto_adjust': False}}
    return snapshot, frame


def test_repair_changes_only_empty_prices_not_candidate_identity_or_inputs():
    base, frame = inputs()
    before, price_before = deepcopy(base), frame.copy(deep=True)
    out = recover_empty_frame(base, '000001.KS', '000001.KQ', frame)
    assert_only_target_changed(base, out, '000001.KS')
    assert list(out['kinds']) == ['000001.KS']
    pd.testing.assert_frame_equal(out['frames']['000001.KS'], frame, check_exact=True)
    pd.testing.assert_frame_equal(base['frames']['000001.KS'], before['frames']['000001.KS'])
    pd.testing.assert_frame_equal(frame, price_before)
    out['frames']['OTHER'].iloc[0, 0] = 999.
    pd.testing.assert_frame_equal(base['frames']['OTHER'], before['frames']['OTHER'])
    with pytest.raises(AssertionError):
        assert_only_target_changed(base, out, '000001.KS')


@pytest.mark.parametrize('invalid', ['observed', 'flow', 'symbol', 'short', 'future',
                                    'duplicate', 'timezone', 'nan_open', 'adjusted'])
def test_repair_fails_closed_for_nonempty_or_incompatible_inputs(invalid):
    base, price = inputs()
    provider = '000001.KQ'
    if invalid == 'observed': base['frames']['000001.KS'].iloc[0, 3] = 10.
    elif invalid == 'flow': base['flow_tickers'].append('000001.KS')
    elif invalid == 'symbol': provider = '000002.KQ'
    elif invalid == 'short': price = price.iloc[:117]
    elif invalid == 'future': price.index = price.index + pd.Timedelta(days=200)
    elif invalid == 'duplicate': price = pd.concat([price, price.iloc[[0]]])
    elif invalid == 'timezone': price.index = price.index.tz_localize('Asia/Seoul')
    elif invalid == 'nan_open': price.iloc[0, 0] = np.nan
    elif invalid == 'adjusted': base['source']['auto_adjust'] = True
    with pytest.raises(ValueError):
        recover_empty_frame(base, '000001.KS', provider, price)


def test_provider_range_anomaly_is_not_silently_repaired_or_dropped():
    base, price = inputs()
    price.iloc[0, 1] = 1.
    out = recover_empty_frame(base, '000001.KS', '000001.KQ', price)
    pd.testing.assert_frame_equal(out['frames']['000001.KS'], price, check_exact=True)


def test_frozen_metadata_and_calendar_changes_are_rejected():
    base, price = inputs()
    out = recover_empty_frame(base, '000001.KS', '000001.KQ', price)
    out['sessions']['KR'] = out['sessions']['KR'][:-1]
    with pytest.raises(AssertionError):
        assert_only_target_changed(base, out, '000001.KS')
    out = recover_empty_frame(base, '000001.KS', '000001.KQ', price)
    out['source']['start'] = '2020-01-02'
    with pytest.raises(AssertionError):
        assert_only_target_changed(base, out, '000001.KS')
