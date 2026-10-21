import copy

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.chart_enrichment import build_volume_signal_series
from stock_lab_core.precision_chart_view import (
    build_price_figure, chart_basis_rows, finish_price_figure, frame_last_date,
)


def frame(end="2026-10-21", count=80):
    close = np.linspace(90, 110, count)
    return pd.DataFrame({
        "Open": close - 1, "High": close + 2, "Low": close - 2,
        "Close": close, "Volume": np.arange(count) + 100,
        "MA5": close - .5, "MA20": close - 1,
    }, index=pd.bdate_range(end=end, periods=count))


def test_basis_distinguishes_source_overlay_and_future_bucket_dates():
    source, chart = frame("2026-10-20"), frame()
    week, month = frame("2026-10-23"), frame("2026-10-30")
    pack = {"주봉": {"df": week, "source_asof": "2026-10-20"},
            "월봉": {"df": month, "source_asof": "2026-10-20"}}
    before = copy.deepcopy(pack)
    rows = chart_basis_rows(source, chart, pack, live_applied=True)
    assert rows[0]["원자료 마지막 날짜"] == "2026-10-20"
    assert rows[0]["차트 마지막 봉"] == "2026-10-21"
    assert "확정봉 아님" in rows[0]["가격 반영"]
    assert rows[1]["원자료 마지막 날짜"] == "2026-10-20"
    assert rows[1]["차트 마지막 봉"] == "2026-10-23"
    for key in pack:
        pd.testing.assert_frame_equal(pack[key]["df"], before[key]["df"])


def test_missing_basis_does_not_invent_today_or_source_from_bucket():
    rows = chart_basis_rows(pd.DataFrame(), None, {"주봉": {"df": frame()}})
    assert all(row["원자료 마지막 날짜"] == "미확인" for row in rows)
    assert rows[0]["차트 마지막 봉"] == "미확인"
    assert frame_last_date(pd.DataFrame({"Close": [1]})) == ""


def test_basis_preserves_exchange_local_date():
    source = frame("2026-10-20")
    source.index = source.index.tz_localize("America/New_York")
    assert frame_last_date(source) == "2026-10-20"


@pytest.mark.parametrize("timeframe", ["daily", "weekly", "monthly"])
def test_chart_keeps_ohlcv_indicators_and_shapes_when_hiding_labels(timeframe):
    source = frame()
    before = source.copy(deep=True)
    signals = build_volume_signal_series(source, timeframe=timeframe)
    fig = build_price_figure(source, avg_price=102)
    fig.add_hrect(y0=98, y1=100, annotation_text="지지")
    original_shapes = [shape.to_plotly_json() for shape in fig.layout.shapes]
    finish_price_figure(fig, source, signals)
    pd.testing.assert_frame_equal(source, before)
    for col in ("open", "high", "low", "close"):
        np.testing.assert_array_equal(getattr(fig.data[0], col), source[col.title()])
    assert list(fig.data[0].x) == list(source.index)
    assert [shape.to_plotly_json() for shape in fig.layout.shapes] == original_shapes
    assert all(annotation.visible is False for annotation in fig.layout.annotations)
    assert [a.text for a in fig.layout.annotations] == ["내 평단가", "지지"]
    np.testing.assert_array_equal(next(t for t in fig.data if t.name == "MA20").y, source.MA20)
    np.testing.assert_array_equal(next(t for t in fig.data if t.type == "bar").y, signals.volume)
    assert fig.layout.yaxis.domain[0] > fig.layout.yaxis2.domain[1]


def test_chart_labels_can_be_restored_without_volume():
    source = frame()
    fig = build_price_figure(source, avg_price=100)
    finish_price_figure(fig, source, pd.DataFrame(), show_level_labels=True)
    assert all(a.visible is True for a in fig.layout.annotations)


def test_timeframe_source_dates_do_not_change_candles_or_snapshots(app_module):
    daily, long = frame(), frame(count=600)
    pack = app_module.build_precision_multi_timeframe_pack("379810.KS", daily, _long_price_df=long)
    for label, rule, count in (("주봉", "W-FRI", 260), ("월봉", pd.offsets.MonthEnd(), 180)):
        expected = app_module.build_indicators(app_module.resample_ohlcv_timeframe(long, rule).tail(count))
        pd.testing.assert_frame_equal(pack[label]["df"], expected)
        assert pack[label]["source_asof"] == "2026-10-21"
        assert pack[label]["snapshot"] == app_module.build_precision_timeframe_snapshot(label, expected, _indicators_ready=True)
    pd.testing.assert_frame_equal(pack["일봉"]["df"], daily)


def test_basis_and_chart_render_in_streamlit():
    from streamlit.testing.v1 import AppTest

    def screen():
        import pandas as pd
        import streamlit as st
        from stock_lab_core.precision_chart_view import render_chart_basis, build_price_figure, finish_price_figure

        source = pd.DataFrame({"Open": [100], "High": [102], "Low": [99], "Close": [101]},
                              index=pd.to_datetime(["2026-10-20"]))
        render_chart_basis(st, source, source, {})
        labels = st.checkbox("차트 안 가격대 이름", value=False)
        fig = build_price_figure(source, 100)
        finish_price_figure(fig, source, pd.DataFrame(), show_level_labels=labels)
        st.plotly_chart(fig)

    app = AppTest.from_function(screen).run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["원자료 마지막 날짜"] == "2026-10-20"
    app.checkbox[0].check().run()
    assert not app.exception


def test_timeframe_fallback_discloses_quote_overlay_without_changing_aggregation(app_module, monkeypatch):
    source = frame("2026-10-20")
    chart = frame()
    monkeypatch.setattr(app_module, "load_price_df", lambda *args: pd.DataFrame())
    pack = app_module.build_precision_multi_timeframe_pack("RAM", chart)
    rows = chart_basis_rows(source, chart, pack, live_applied=True)
    for item in rows[1:]:
        assert item["원자료 마지막 날짜"] == "2026-10-20"
        assert item["가격 반영"] == "일봉 대체 집계 · 현재가 보정 포함"
    for label, rule in (("주봉", "W-FRI"), ("월봉", pd.offsets.MonthEnd())):
        assert pack[label]["source_kind"] == "daily_fallback"
        assert pack[label]["source_asof"] == ""
        expected = app_module.build_indicators(app_module.resample_ohlcv_timeframe(chart, rule))
        pd.testing.assert_frame_equal(pack[label]["df"], expected)
