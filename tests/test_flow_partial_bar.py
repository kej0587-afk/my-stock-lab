import numpy as np
import pandas as pd
import pytest

from stock_lab_core.money_flow import _extract_ohlc_from_yf, _compute_ticker_metrics
from stock_lab_core.flow_snapshot import flow_source_date_rows, flow_source_issue_rows


def sample():
    days = pd.bdate_range(end='2026-11-25', periods=140)
    value = np.arange(140, dtype=float) + 100
    clean = pd.DataFrame({'Close':value,'High':value+2,'Low':value-2,'Volume':1000.}, index=days)
    return pd.concat([clean, pd.DataFrame({'Close':[np.nan],'High':[250.], 'Low':[238.],
                                          'Volume':[1200.]}, index=pd.to_datetime(['2026-11-27']))])


@pytest.mark.parametrize('layout', ['single','ticker_first','ticker_last'])
def test_partial_received_bar_reports_reason_without_changing_metrics(layout):
    raw = sample()
    data = raw if layout == 'single' else pd.concat({'SOXX':raw}, axis=1)
    if layout == 'ticker_last':
        data.columns = data.columns.swaplevel()
    before = data.copy(deep=True)
    selected = _extract_ohlc_from_yf(data, 'SOXX')
    pd.testing.assert_frame_equal(selected, raw.iloc[:-1])
    expected = _compute_ticker_metrics(raw.iloc[:-1])
    actual = _compute_ticker_metrics(selected)
    for key, value in expected.items():
        assert actual[key] == value or pd.isna(actual[key]) and pd.isna(value)
    assert actual['원자료최근봉'] == '2026-11-27'
    assert actual['원자료누락항목'] == 'Close'
    assert actual['기준일'] == '2026-11-25'
    snapshot = {'flow_df':pd.DataFrame([{'Ticker':'SOXX', **actual}])}
    assert flow_source_date_rows(snapshot)[0]['최근봉 필수값 누락'] == 1
    issue = flow_source_issue_rows(snapshot)[0]
    assert issue['자료상태'] == '최근봉 불완전 · 이전 정상봉'
    assert issue['계산 기준일'] == '2026-11-25' and issue['수신 최근봉'] == '2026-11-27'
    pd.testing.assert_frame_equal(data, before)


def test_union_calendar_empty_row_is_not_an_incomplete_received_candle():
    raw = sample()
    raw.iloc[-1] = np.nan
    selected = _extract_ohlc_from_yf(raw, 'SOXX')
    assert not selected.attrs.get('flow_partial_bar')
    raw.loc[raw.index[-1], ['Close','High','Low','Volume']] = [240,245,238,np.nan]
    selected = _extract_ohlc_from_yf(raw, 'SOXX')
    assert not selected.attrs.get('flow_partial_bar')
    assert selected.index[-1] == pd.Timestamp('2026-11-27')
    assert pd.isna(selected.iloc[-1]['Volume'])
