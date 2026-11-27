import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import intraday_chart as ic
from stock_lab_core import precision_chart_view as view


def bars(times):
    index = pd.DatetimeIndex(times)
    if index.tz is None:
        index = index.tz_localize("America/New_York")
    price = np.arange(len(index), dtype=float) + 50
    return pd.DataFrame(dict(Open=price, High=price + 2, Low=price - 1,
                             Close=price + 1, Volume=price * 100), index=index)


@pytest.mark.parametrize("day,hours,starts,volumes", [
    ("2026-11-25", 7, ["09:30", "11:30", "13:30", "15:30"], [10100, 10500, 10900, 5600]),
    ("2025-11-28", 4, ["09:30", "11:30"], [10100, 10500]),
])
def test_normal_and_early_close(day, hours, starts, volumes):
    source = bars(pd.date_range(f"{day} 09:30", periods=hours, freq="h"))
    result = ic.pair_sixty_minute_bars(source)
    assert result.index.strftime("%H:%M").tolist() == starts
    assert result.Volume.tolist() == volumes
    assert result.Volume.sum() == source.Volume.sum()
    assert result.attrs["aggregation"]["incomplete"] == 0
    assert result.attrs["aggregation"]["short_buckets"] == 1


def test_missing_hour_does_not_shift_buckets_or_mix_days():
    source = bars(["2026-11-24 10:30", "2026-11-24 11:30", "2026-11-24 13:30",
                   "2026-11-25 09:30", "2026-11-25 10:30"])
    result = ic.pair_sixty_minute_bars(source)
    assert result.index.strftime("%d %H:%M").tolist() == ["24 09:30", "24 11:30", "24 13:30", "25 09:30"]
    assert result.attrs["aggregation"]["incomplete"] == 3
    assert result.iloc[-1].Open == source.iloc[-2].Open
    assert result.Volume.sum() == source.Volume.sum()


def test_utc_dst_and_outside_regular_session():
    source = bars(["2026-10-30 09:30", "2026-10-30 10:30", "2026-11-02 09:30", "2026-11-02 10:30",
                   "2026-11-02 16:30"])
    source.index = source.index.tz_convert("UTC")
    result = ic.pair_sixty_minute_bars(source)
    assert result.index.strftime("%H:%M").tolist() == ["09:30", "09:30"]
    assert result.index.tz_convert("UTC").strftime("%H:%M").tolist() == ["13:30", "14:30"]
    assert result.attrs["aggregation"]["excluded"] == 1


def test_missing_volume_is_not_partial_sum():
    source = bars(["2026-11-25 09:30", "2026-11-25 10:30"])
    source.iloc[0, source.columns.get_loc("Volume")] = np.nan
    assert pd.isna(ic.pair_sixty_minute_bars(source).Volume.iloc[0])


def test_multiyear_labels_unique_and_long_ma_does_not_remove_candles():
    from stock_lab_core.intraday_chart_view import build_figure
    source = bars(["2025-11-25 09:30", "2025-11-25 11:30", "2026-11-25 09:30", "2026-11-25 11:30"])
    ma, status = ic.moving_averages(source, [1000])
    figure = build_figure(source, "120분", "US", ma, {})
    assert not status[1000]["ok"]
    assert len(set(figure.data[0].x)) == 4
    assert len(figure.data[0].close) == 4
    assert list(figure.data[-1].y) == source.Volume.tolist()


def test_daily_overlay_when_today_not_yet_published():
    daily = bars(["2026-11-23", "2026-11-24", "2026-11-25"])
    intraday = bars(["2026-11-27 09:30"])
    lines, status = ic.daily_overlay(daily, intraday, [3])
    assert status[3]["ok"]
    assert lines[3].iloc[0] == daily.Close.mean()


def test_all_layers_use_same_ordinal_axis_without_altering_prices():
    source = bars(pd.date_range("2026-11-25 09:30", periods=7, freq="h"))
    before = source.copy(deep=True)
    fig = view.build_price_figure(source, 50)
    fig.add_shape(type="line", x0=source.index[0], x1=source.index[-1], y0=50, y1=56)
    fig.add_scatter(x=source.index[2:4], y=[53, 54], name="pattern")
    view.intraday_display_axis(fig, source)
    assert list(fig.data[0].x) == list(range(7))
    assert list(fig.data[-1].x) == [2, 3]
    assert fig.layout.shapes[-1].x0 == 0 and fig.layout.shapes[-1].x1 == 6
    assert fig.layout.shapes[0].xref == "x domain"
    pd.testing.assert_frame_equal(source, before)


def test_original_renderer_with_intraday_layers_preserves_decision(app_module, monkeypatch):
    source = bars(pd.date_range("2026-11-02 09:30", periods=160, freq="h"))
    decision = {"chart_price_asof": "2026-11-25", "execution_workflow": {"게이트상태": "방어우선"},
                "chart_final_check": {"execution_allowed": False}, "price": 64, "stop_loss": 55}
    before = copy.deepcopy(decision)
    figures = []
    monkeypatch.setattr(app_module.st, "plotly_chart", lambda fig, **kwargs: figures.append(fig))
    ma, _ = ic.moving_averages(source, [5, 1000])
    snapshot = app_module.render_precision_candlestick_chart(
        source, ticker="SOXL", decision_context=decision, timeframe_override="intraday",
        provisional_override=False, display_averages=(ma, {}))
    assert decision == before
    assert snapshot["timeframe"] == "intraday"
    assert not any(e["execution_allowed"] for e in snapshot["events"])
    assert len(figures) == 1
    assert sum(t.type == "candlestick" for t in figures[0].data) == 1
    assert any(t.type == "bar" for t in figures[0].data)
    assert "MA1000" not in [t.name for t in figures[0].data]


def test_app_has_only_one_observatory_chart_call():
    source = Path("app.py").read_text(encoding="utf-8")
    assert "render_quick_chart(st, tkr" not in source
    assert 'day_tab, week_tab, month_tab = st.tabs' not in source
    assert source.count("render_analysis_chart(st, tkr") == 1


def test_interval_and_ma_restore_in_streamlit(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from stock_lab_core import intraday_chart_view as ui
    source = bars(pd.date_range("2026-11-25 09:30", periods=7, freq="h"))
    monkeypatch.setattr(ui, "load_history", lambda *args: source)
    monkeypatch.setattr(ui, "_session", lambda *args: {"phase": "closed"})

    def screen():
        import streamlit as st
        from stock_lab_core.intraday_chart_view import render_analysis_chart
        render_analysis_chart(st, "SOXL")

    app = AppTest.from_function(screen).run()
    assert not app.exception
    app.text_input[0].input("5,20,1000").run()
    for label in ("60분", "120분", "5분", "120분", "일봉"):
        app.button_group[0].set_value(label).run()
        assert not app.exception
        assert len(app.get("plotly_chart")) == 1
        assert app.session_state["_quick_chart_preferences"]["interval"] == label
        assert app.session_state["_quick_chart_preferences"]["periods"] == [5, 20, 1000]
