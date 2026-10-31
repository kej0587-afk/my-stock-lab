"""Synthetic chart regressions; no quotes, network, or trade-score changes."""

import copy
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.chart_enrichment import build_volume_signal_series
from stock_lab_core.chart_execution import chart_volume_ratio
from stock_lab_core.chart_patterns import build_recent_trendline_guides
from stock_lab_core.chart_scorecard import build_chart_scorecard, render_chart_scorecard, volume_review
from stock_lab_core.precision_chart_view import build_price_figure, finish_price_figure


def bars(count=300):
    close = np.linspace(100, 140, count)
    return pd.DataFrame({
        "Open": close - 1, "High": close + 2, "Low": close - 2,
        "Close": close, "Volume": np.arange(count, dtype=float) + 100,
    }, index=pd.bdate_range(end="2026-10-30", periods=count))


def test_chart_initial_zoom_keeps_full_history_and_volume_scale():
    frame = bars(400)
    signals = build_volume_signal_series(frame)
    figure = finish_price_figure(build_price_figure(frame), frame, signals)
    assert len(figure.data[0].x) == 400
    assert figure.layout.xaxis.range[0] == frame.index[-180]
    assert figure.layout.yaxis.range[0] < frame.tail(180)["Low"].min()
    assert figure.layout.yaxis2.range is None
    assert figure.layout.legend.y < 0
    assert figure.layout.margin.b >= 100


def factors(frame, benchmark=None):
    _, items = build_chart_scorecard({}, frame, is_etf=True, benchmark=benchmark)
    return {item["항목"]: item["값"] for item in items}


@pytest.mark.parametrize("missing", [np.nan, np.inf, -1])
def test_volume_ratio_never_reuses_older_volume_for_missing_latest_bar(missing):
    frame = bars(30)
    frame.loc[frame.index[-1], "Volume"] = missing
    assert np.isnan(chart_volume_ratio(frame))


def test_volume_ratio_window_counts_bars_instead_of_nonmissing_values():
    frame = bars(5)
    frame["Volume"] = [1000, np.nan, 100, np.nan, 200]
    before = frame.copy(deep=True)
    assert chart_volume_ratio(frame, lookback=3) == pytest.approx(200 / 150)
    pd.testing.assert_frame_equal(frame, before)


def test_ud_ratio_requires_known_directions_for_every_bar_in_window():
    frame = bars(7)
    frame["Close"] = [100, 90, 95, np.nan, 110, 109, 110]
    frame["Volume"] = 100
    signals = build_volume_signal_series(frame, ud_length=2)
    assert signals.up_down_ratio.iloc[4:6].isna().all()
    assert signals.up_down_ratio.iloc[-1] == pytest.approx(1)


def test_volume_plot_aligns_signals_by_date_and_discloses_missing_rvol():
    frame = bars(4)
    signals = build_volume_signal_series(frame).iloc[[2, 0]]
    before = signals.copy(deep=True)
    fig = finish_price_figure(build_price_figure(frame), frame, signals)
    volume = next(trace for trace in fig.data if trace.type == "bar")
    assert list(volume.x) == list(frame.index)
    np.testing.assert_allclose(volume.y, [100, np.nan, 102, np.nan], equal_nan=True)
    assert volume.customdata[0][1] == "미수집"
    assert volume.customdata[1][0] == "UNAVAILABLE"
    assert "%{x|%Y-%m-%d}" in volume.hovertemplate
    assert fig.layout.yaxis.domain[0] > fig.layout.yaxis2.domain[1]
    pd.testing.assert_frame_equal(signals, before)


def test_volume_plot_does_not_show_signals_outside_the_display_window():
    frame = bars(5)
    signals = build_volume_signal_series(frame.iloc[:2])
    visible = frame.iloc[2:]
    fig = finish_price_figure(build_price_figure(visible), visible, signals)
    assert not any(trace.type == "bar" for trace in fig.data)


def test_year_position_uses_52_calendar_weeks_instead_of_252_bars():
    frame = bars()
    frame[["Open", "Close"]] = 100.0
    frame["High"], frame["Low"] = 120.0, 80.0
    cutoff = frame.index[-1] - pd.Timedelta(weeks=52)
    in_year = frame.index[frame.index > cutoff]
    frame.loc[in_year[0], "High"] = 500
    frame.loc[frame.index[0], "High"] = 1000
    before = frame.copy(deep=True)
    assert factors(frame)["52주 위치"] == pytest.approx((100 - 80) / (500 - 80) * 100)
    pd.testing.assert_frame_equal(frame, before)


def test_year_position_accepts_fewer_than_252_sessions_when_full_year_is_loaded():
    frame = bars()
    # Simulate nontrading dates without inventing prices for those dates.
    frame = frame.drop(frame.index[50:105])
    assert len(frame) < 252
    assert factors(frame)["52주 위치"] is not None


def test_year_position_does_not_claim_full_year_from_short_calendar_span():
    assert factors(bars(252))["52주 위치"] is None


def test_year_position_does_not_skip_invalid_high_low_in_its_window():
    frame = bars()
    frame.loc[frame.index[-2], "High"] = np.nan
    assert factors(frame)["52주 위치"] is None


@pytest.mark.parametrize("missing", [np.nan, np.inf, 0, -1])
def test_momentum_does_not_reuse_older_close_when_latest_is_invalid(missing):
    frame = bars()
    frame.loc[frame.index[-1], "Close"] = missing
    assert all(value is None for value in factors(frame, bars()).values())


def test_momentum_does_not_bridge_recent_missing_session():
    frame = bars()
    frame.loc[frame.index[-2], "Close"] = np.nan
    result = factors(frame)
    assert result["RSI(14)"] is None
    assert result["MA20/50/200"] is None
    assert result["30일 연율변동성"] is None


def test_rs_matches_exchange_local_dates_without_mutation_or_forward_fill():
    frame, benchmark = bars(), bars()
    frame.index = frame.index.tz_localize("America/New_York")
    benchmark["Close"] = 100.0
    original = copy.deepcopy((frame, benchmark))
    result = factors(frame, benchmark)
    for days, label in ((126, "6M RS"), (252, "12M RS")):
        expected = (frame.Close.iloc[-1] / frame.Close.iloc[-days - 1] - 1) * 100
        assert result[label] == pytest.approx(expected)
    benchmark.loc[benchmark.index[-1], "Close"] = np.nan
    assert factors(frame, benchmark)["6M RS"] is None
    pd.testing.assert_frame_equal(frame, original[0])
    benchmark.iloc[-1, benchmark.columns.get_loc("Close")] = 100.0
    pd.testing.assert_frame_equal(benchmark, original[1])


@pytest.mark.parametrize("missing", [np.inf, 0, -1])
def test_rs_rejects_invalid_benchmark_endpoints(missing):
    benchmark = bars()
    benchmark.loc[benchmark.index[-1], "Close"] = missing
    result = factors(bars(), benchmark)
    assert result["6M RS"] is None and result["12M RS"] is None


def test_rs_with_duplicate_benchmark_dates_stays_missing_instead_of_crashing():
    benchmark = bars()
    benchmark = pd.concat([benchmark, benchmark.iloc[[-1]]])
    assert factors(bars(), benchmark)["6M RS"] is None


def test_scorecard_render_forwards_benchmark_to_calculation():
    tables = []
    st = SimpleNamespace(
        markdown=lambda *args: None, caption=lambda *args: None,
        dataframe=lambda frame, **kwargs: tables.append(frame),
        expander=lambda *args: nullcontext(),
        column_config=SimpleNamespace(TextColumn=lambda *args, **kwargs: None,
                                      ProgressColumn=lambda *args, **kwargs: None),
    )
    render_chart_scorecard(st, bars(), benchmark=bars(), is_etf=True)
    rs = tables[1].loc[tables[1]["항목"].isin(["6M RS", "12M RS"])]
    assert len(rs) == 2 and rs["값"].eq(0).all()


def test_volume_review_handles_missing_close_without_inventing_turnover():
    rows, _ = volume_review(bars().drop(columns="Close"))
    assert rows[1]["값"] is None and rows[2]["값"] is None


def test_trendline_path_uses_every_bar_for_irregular_date_axis():
    frame = bars(90)
    base = np.linspace(100, 140, len(frame)) + np.sin(np.arange(len(frame)) / 3) * 6
    frame["Open"], frame["Close"] = base - .5, base
    frame["High"], frame["Low"] = base + 1.5, base - 1.5
    before = frame.copy(deep=True)
    guides = build_recent_trendline_guides(frame)
    assert guides
    for guide in guides:
        assert guide["x"][0] == guide["x0"] and guide["x"][-1] == guide["x1"]
        assert guide["y"][0] == pytest.approx(guide["y0"])
        assert guide["y"][-1] == pytest.approx(guide["y1"])
        np.testing.assert_allclose(np.diff(guide["y"]), np.diff(guide["y"])[0])
        assert len(set(np.diff(pd.DatetimeIndex(guide["x"])).tolist())) > 1
    pd.testing.assert_frame_equal(frame, before)
