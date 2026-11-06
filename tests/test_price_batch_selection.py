"""Exact output contracts for batch-local OHLCV column indexing."""

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import prices
from stock_lab_core.price_batch_selection import DownloadFrameSelector


def legacy_select(df, ticker):
    # Frozen selection logic from f2ad9174, before the batch-local index.
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        for level in range(df.columns.nlevels):
            matches = [value for value in df.columns.get_level_values(level).unique()
                       if str(value).strip().upper() == str(ticker).strip().upper()]
            if matches:
                out = df.xs(matches[0], axis=1, level=level).copy(deep=True)
                break
        else:
            return pd.DataFrame()
        if isinstance(out.columns, pd.MultiIndex):
            return pd.DataFrame()
        return out
    return df.copy(deep=True)


def batch(symbols=("AAA", "BBB"), rows=64):
    columns = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close", "Adj Close", "Volume"]])
    values = np.arange(rows * len(columns), dtype=float).reshape(rows, len(columns)) + 10
    frame = pd.DataFrame(values, columns=columns,
                         index=pd.bdate_range(end="2026-11-05", periods=rows, name="Date"))
    frame.iloc[-1, 3] = np.nan
    frame.attrs = {"source": "fixture", "basis": {"adjusted": False, "session": "regular"}}
    return frame


@pytest.mark.parametrize("layout", ["ticker_first", "field_first", "duplicate", "case_collision", "three_levels", "plain", "empty", "none"])
def test_selection_matches_original_and_is_copy_isolated(layout):
    frame = batch()
    if layout == "field_first":
        frame = frame.swaplevel(axis=1)
    elif layout == "duplicate":
        frame = pd.concat([frame, frame.iloc[:, :1]], axis=1)
    elif layout == "case_collision":
        frame = batch((" aaa ", "AAA", "Close"))
    elif layout == "three_levels":
        frame.columns = pd.MultiIndex.from_tuples([(*key, "extra") for key in frame.columns])
    elif layout == "plain":
        frame = frame["AAA"]
    elif layout == "empty":
        frame = frame.iloc[:0]
    elif layout == "none":
        frame = None
    selector = DownloadFrameSelector(frame)
    for ticker in ("AAA", " bbb ", "Close", "MISSING"):
        expected = legacy_select(frame, ticker)
        actual = selector.select(ticker)
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
        if not actual.empty:
            actual.iloc[0, 0] = -999
            actual.attrs["basis"]["session"] = "changed"
            again = selector.select(ticker)
            pd.testing.assert_frame_equal(again, expected, check_exact=True)
            assert again.attrs == expected.attrs


@pytest.mark.parametrize("period", ["3mo", "1y", "10y"])
def test_batch_pipeline_preserves_request_cleaning_and_values(monkeypatch, period):
    frame = batch()
    calls = []

    def download(*args, **kwargs):
        calls.append((args, kwargs))
        return frame

    monkeypatch.setattr(prices.yf, "download", download)
    monkeypatch.setattr(prices, "yahoo_session_kwargs", lambda: {})
    actual = prices.load_price_frames_batch.__wrapped__(("BBB", "AAA", "AAA", "005930.KS", "MISSING"), period)
    assert len(calls) == 1
    assert calls[0] == ((["AAA", "BBB", "MISSING"],), dict(period=period, interval="1d", group_by="ticker",
        progress=False, threads=3, auto_adjust=False, timeout=5))
    assert list(actual) == ["AAA", "BBB"]
    for ticker, result in actual.items():
        expected = prices._clean_ohlcv_frame(legacy_select(frame, ticker), keep_adj_close=True)
        pd.testing.assert_frame_equal(result, expected, check_exact=True)
        assert result.attrs == expected.attrs


def test_column_index_built_once_for_the_batch(monkeypatch):
    frame = batch(tuple(f"S{i}" for i in range(95)))
    original = pd.MultiIndex.get_level_values
    calls = []

    def record(index, level):
        if index is frame.columns:
            calls.append(level)
        return original(index, level)

    monkeypatch.setattr(pd.MultiIndex, "get_level_values", record)
    selector = DownloadFrameSelector(frame)
    for i in range(95):
        selector.select(f"S{i}")
    assert calls == [0, 1]
