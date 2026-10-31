"""Chart geometry and observation dates, not historical trade recommendations."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from stock_lab_core.chart_patterns import _chart_pattern_pivots, _detect_flag_pattern, _detect_head_shoulders_pattern
from stock_lab_core.chart_structure import (
    add_channel_overlay, add_event_overlays, build_chart_structure, build_parallel_channel,
    chart_date_breaks, last_bar_is_provisional, latest_completed_chart_session, qualify_chart_events,
)


def wave(count=100, sign=1):
    price = 150 + sign * np.arange(count) * .25 + np.sin(np.arange(count) / 3) * 5
    return pd.DataFrame({"Open": price - .2, "High": price + 1, "Low": price - 1,
                         "Close": price, "Volume": 100.0}, index=pd.bdate_range("2026-02-01", periods=count))


def double_top():
    index = pd.bdate_range("2026-09-03", "2026-10-30")
    knots = pd.to_datetime(["2026-09-03", "2026-09-22", "2026-10-01", "2026-10-14", "2026-10-20", "2026-10-21", "2026-10-30"])
    close = np.interp(np.arange(len(index)), index.get_indexer(knots), [340, 362, 337, 357, 336, 334.76, 280])
    frame = pd.DataFrame({"Open": close - .1, "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": 100.0}, index=index)
    frame.loc["2026-09-22", "High"] = 364.17
    frame.loc["2026-10-14", "High"] = 359.40
    frame.loc["2026-10-01", "Low"] = 335.51
    frame.loc["2026-10-21", "Volume"] = 150
    return frame


@pytest.mark.parametrize("sign", [1, -1])
def test_channel_is_parallel_and_touches_two_main_pivots_and_opposite_extreme(sign):
    frame = wave(sign=sign)
    before = frame.copy(deep=True)
    channel = build_parallel_channel(frame)
    assert channel and channel["direction"] == ("상승" if sign > 0 else "하락")
    np.testing.assert_allclose(np.subtract(channel["upper"], channel["lower"]), channel["width"])
    np.testing.assert_allclose(channel["middle"], (np.array(channel["upper"]) + channel["lower"]) / 2)
    main = "lower" if sign > 0 else "upper"
    for anchor in channel["anchors"][:2]:
        offset = channel["x"].index(anchor["time"])
        assert channel[main][offset] == pytest.approx(anchor["price"])
    opposite = channel["anchors"][2]
    assert channel["upper" if sign > 0 else "lower"][channel["x"].index(opposite["time"])] == pytest.approx(opposite["price"])
    assert channel["known_at"] >= channel["anchors"][1]["time"]
    pd.testing.assert_frame_equal(frame, before)


def test_no_channel_is_forced_without_confirmed_pivots():
    frame = wave()
    frame["High"], frame["Low"] = np.arange(len(frame)) + 200, np.arange(len(frame)) + 190
    assert build_parallel_channel(frame) == {}


def test_pivot_vectorization_exactly_preserves_original_windows_including_ties():
    rng = np.random.default_rng(42)
    frame = wave()
    frame["High"] = rng.integers(100, 111, len(frame))
    frame["Low"] = rng.integers(80, 91, len(frame))
    for left, right in ((3, 3), (2, 4), (1, 1)):
        actual = _chart_pattern_pivots(frame, left, right)
        for points, col, reducer in zip(actual, ("High", "Low"), (max, min)):
            expected = [i for i in range(left, len(frame) - right)
                        if frame[col].iloc[i] == reducer(frame[col].iloc[i-left:i+right+1])]
            assert [point["pos"] for point in points] == expected


def test_double_top_signal_is_on_neckline_cross_not_old_second_peak():
    frame = double_top()
    result = build_chart_structure(frame)
    events = [e for e in result["events"] if e["name"] == "쌍봉"]
    assert len(events) == 1
    event = events[0]
    assert event["time"] == pd.Timestamp("2026-10-21")
    assert event["formation_end"] == pd.Timestamp("2026-10-14")
    assert event["known_at"] == pd.Timestamp("2026-10-19")
    assert event["level"] == pytest.approx(335.51)
    assert not [e for e in build_chart_structure(frame.loc[:"2026-10-20"])["events"] if e["name"] == "쌍봉"]


def test_future_price_spike_does_not_backpaint_prior_arrows():
    frame = double_top().loc[:"2026-10-23"]
    past = build_chart_structure(frame)["events"]
    future = pd.DataFrame({"Open": [900.0], "High": [1000.0], "Low": [800.0], "Close": [950.0], "Volume": [9000.0]},
                          index=pd.to_datetime(["2026-10-26"]))
    later = build_chart_structure(pd.concat([frame, future]))["events"]
    assert [e for e in later if e["time"] <= frame.index[-1]] == past


@pytest.mark.parametrize("inverse", [False, True])
def test_shoulders_draws_all_five_turns_and_actual_sloped_neckline(inverse):
    frame = wave(60)
    frame[["Open", "High", "Low", "Close"]] = [100.0, 101.0, 99.0, 100.0]
    highs = [{"pos": p, "time": frame.index[p], "price": y} for p, y in ((10, 110), (25, 125), (40, 111))]
    lows = [{"pos": p, "time": frame.index[p], "price": y} for p, y in ((17, 100), (32, 102))]
    if inverse:
        highs, lows = ([dict(p, price=220-p["price"]) for p in lows], [dict(p, price=220-p["price"]) for p in highs])
    pattern = _detect_head_shoulders_pattern(frame, highs, lows, inverse)
    assert pattern and len(pattern["line_points"]) == 5
    path = pattern["line_paths"][0]
    assert path["x"][0] == frame.index[17]
    assert path["y"][15] == pytest.approx(118 if inverse else 102)
    assert pattern["known_at"] == frame.index[43]


@pytest.mark.parametrize("bullish", [True, False])
def test_flag_rails_parallel_and_breakout_bar_wick_cannot_change_the_boundary(bullish):
    prices = np.r_[np.linspace(80, 100, 27), np.linspace(100, 98, 17), 106.0]
    if not bullish:
        prices = 200 - prices
    frame = pd.DataFrame({"Open": prices, "High": prices+1, "Low": prices-1, "Close": prices},
                         index=pd.bdate_range("2026-01-01", periods=45))
    first = _detect_flag_pattern(frame, bullish)
    assert first and first["status"] == ("돌파" if bullish else "이탈")
    frame.iloc[-1, frame.columns.get_loc("High" if bullish else "Low")] += 60 if bullish else -60
    second = _detect_flag_pattern(frame, bullish)
    assert second["trigger_price"] == first["trigger_price"]
    np.testing.assert_allclose(np.diff(first["line_paths"][0]["y"]), np.diff(first["line_paths"][1]["y"]))


def event_context():
    stamp = pd.Timestamp("2026-10-21")
    event = {"time": stamp, "price": 110.0, "level": 105.0, "side": "buy", "name": "쌍바닥", "source": "pattern",
             "formation_start": stamp-pd.Timedelta(days=20), "formation_end": stamp-pd.Timedelta(days=5),
             "confirmation": "종가 돌파", "volume_ratio": 1.5}
    return {"events": [event], "last_bar": stamp}


@pytest.mark.parametrize("gate,final,provisional,volume,allowed", [
    ("실행가능", True, False, 1.5, True), ("방어우선", True, False, 1.5, False),
    ("대기/관찰", True, False, 1.5, False), ("실행가능", False, False, 1.5, False),
    ("실행가능", True, True, 1.5, False), ("실행가능", True, False, None, False),
    ("실행가능", True, False, .8, False),
])
def test_current_buy_review_cannot_bypass_gate_final_check_volume_or_unclosed_bar(gate, final, provisional, volume, allowed):
    structure = event_context()
    structure["events"][0]["volume_ratio"] = volume
    decision = {"execution_workflow": {"게이트상태": gate, "게이트근거": "원인 확인"},
                "chart_final_check": {"execution_allowed": final},
                "chart_price_asof": "2026-10-21", "chart_expected_close": "2026-10-21"}
    event = qualify_chart_events(structure, decision, provisional_last=provisional)[0]
    assert event["execution_allowed"] is allowed
    assert (event["label"] == "매수 검토") is allowed


def test_historical_and_higher_timeframe_markers_are_not_historical_buy_permissions():
    structure = event_context()
    decision = {"execution_workflow": {"게이트상태": "실행가능"}, "chart_final_check": {"execution_allowed": True}}
    structure["last_bar"] += pd.Timedelta(days=1)
    historical = qualify_chart_events(structure, decision)[0]
    assert historical["label"] == "매수형" and not historical["execution_allowed"]
    assert "미검증" in historical["execution"]
    assert not qualify_chart_events(structure, decision, timeframe="weekly")[0]["execution_allowed"]


def test_live_quote_only_bar_stays_provisional_even_in_later_history():
    structure = event_context()
    structure["events"][0]["provisional"] = True
    structure["last_bar"] += pd.Timedelta(days=1)
    assert qualify_chart_events(structure)[0]["provisional"]


def test_sell_warning_never_inherits_buy_execution_permission():
    structure = event_context()
    structure["events"][0]["side"] = "sell"
    decision = {"execution_workflow": {"게이트상태": "실행가능"}, "chart_final_check": {"execution_allowed": True}}
    event = qualify_chart_events(structure, decision)[0]
    assert event["label"] == "매도형" and not event["execution_allowed"]


@pytest.mark.parametrize("basis,expected", [(None, "2026-10-21"), ("2026-10-21", None),
                                            ("2026-10-21", "2026-10-30"), ("2026-10-20", "2026-10-21")])
def test_stale_or_unmatched_history_cannot_be_a_current_buy_even_when_gates_pass(basis, expected):
    decision = {"execution_workflow": {"게이트상태": "실행가능"}, "chart_final_check": {"execution_allowed": True},
                "chart_price_asof": basis, "chart_expected_close": expected}
    event = qualify_chart_events(event_context(), decision)[0]
    assert not event["execution_allowed"] and event["label"] == "매수형"


def test_confirmation_filter_cross_is_not_lost_after_a_small_unconfirmed_triangle_cross(monkeypatch):
    import stock_lab_core.chart_structure as module
    frame = wave(45)
    frame[["Open", "High", "Low", "Close"]] = [100.0, 101.0, 99.0, 100.0]
    frame.iloc[-2, frame.columns.get_loc("Close")] = 100.1
    frame.iloc[-1, frame.columns.get_loc("Close")] = 100.6

    def triangle(prefix, *args, distinct_directions=True):
        if prefix.Close.iloc[-1] <= 100.5:
            return []
        return [{"name": "삼각수렴", "direction": "bullish", "lifecycle": "현재유효", "trigger_price": 100.0,
                 "known_at": frame.index[30], "label_x": frame.index[27], "formation_id": ("triangle", 1),
                 "line_points": [((frame.index[10], 100.0), (prefix.index[-1], 100.0))]}]

    monkeypatch.setattr(module, "detect_chart_pattern_candidates", triangle)
    events = [e for e in module.build_chart_structure(frame)["events"] if e["name"] == "삼각수렴"]
    assert len(events) == 1 and events[0]["time"] == frame.index[-1]
    assert events[0]["level"] == pytest.approx(100.5)


def test_gradual_triangle_cross_with_real_detector():
    x = np.arange(65)
    price = 100 + (12-.1*x) * np.cos(x*np.pi/6)
    frame = pd.DataFrame({"Open": price, "High": price+.3, "Low": price-.3, "Close": price, "Volume": 100.0},
                         index=pd.bdate_range("2026-01-01", periods=65))
    first = 105.9 * 1.001
    frame.loc[frame.index[-1], ["Open", "High", "Close"]] = [first, first+.1, first]
    stamp = frame.index[-1] + pd.offsets.BDay()
    close = 105.8 * 1.006
    future = pd.DataFrame({"Open": [close], "High": [close+.1], "Low": [close-.1], "Close": [close], "Volume": [150.]}, index=[stamp])
    result = build_chart_structure(pd.concat([frame, future]))
    events = [e for e in result["events"] if e["name"] == "삼각수렴" and e["time"] >= frame.index[-1]]
    assert [(e["time"], e["side"]) for e in events] == [(stamp, "buy")]


def test_large_gap_channel_break_uses_previously_known_rails_instead_of_erasing_them():
    frame = wave()
    initial = build_parallel_channel(frame)
    assert initial
    stamp = frame.index[-1] + pd.offsets.BDay()
    price = initial["lower"][-1] * .85
    gap = pd.DataFrame({"Open": [price], "High": [price+1], "Low": [price-1], "Close": [price], "Volume": [200]}, index=[stamp])
    result = build_chart_structure(pd.concat([frame, gap]))
    assert result["channel"] and result["channel"]["state"] == "하단 이탈"
    event = next(e for e in result["events"] if e["name"] == "평행 채널" and e["time"] == stamp)
    assert event["side"] == "sell"
    assert event["level"] == pytest.approx(initial["lower"][-1] + initial["slope"])


@pytest.mark.parametrize("sign,rail,factor,side", [(1, "lower", .9, "sell"), (-1, "upper", 1.1, "buy")])
def test_gap_in_last_bar_does_not_erase_existing_channel_before_the_event(sign, rail, factor, side):
    frame = wave(sign=sign)
    channel = build_parallel_channel(frame)
    price = channel[rail][-1] * factor
    stamp = frame.index[-1]
    frame.loc[stamp, ["Open", "Close"]] = price
    frame.loc[stamp, "High"] = max(price, frame.loc[stamp, "High"])
    frame.loc[stamp, "Low"] = min(price, frame.loc[stamp, "Low"])
    assert any(e["source"] == "channel" and e["time"] == stamp and e["side"] == side for e in build_chart_structure(frame)["events"])


def test_completed_session_uses_exchange_calendar_and_time_not_loaded_history():
    assert latest_completed_chart_session("GOOGL", now=datetime(2026,10,31,7,tzinfo=timezone.utc)) == "2026-10-30"
    assert latest_completed_chart_session("GOOGL", now=datetime(2026,10,30,15,tzinfo=timezone.utc)) == "2026-10-29"
    assert latest_completed_chart_session("005930.KS", now=datetime(2026,10,31,7,tzinfo=timezone.utc)) == "2026-10-30"


def test_daily_axis_compresses_market_closures_but_keeps_missing_session_gaps():
    index = pd.bdate_range("2026-07-01", "2026-07-10").difference(pd.to_datetime(["2026-07-03", "2026-07-08"]))
    frame = wave(len(index))
    frame.index = index
    breaks = chart_date_breaks(frame, "GOOGL")
    assert breaks[0] == {"bounds": ["sat", "mon"]}
    hidden = [d for item in breaks for d in item.get("values", [])]
    assert "2026-07-03" in hidden
    assert "2026-07-08" not in hidden


def test_weekly_and_crypto_axes_do_not_hide_actual_bars():
    frame = wave(10)
    frame.index = pd.date_range("2026-10-01", periods=10, freq="D")
    assert chart_date_breaks(frame, "BTC-USD") == []
    frame.index = pd.date_range("2026-08-01", periods=10, freq="W-FRI")
    assert chart_date_breaks(frame, "GOOGL") == []


def test_missing_invalid_and_duplicate_ohlc_returns_issue_instead_of_inventing_geometry():
    frame = wave()
    for value in (np.nan, np.inf, -1):
        invalid = frame.copy()
        invalid.iloc[-1, invalid.columns.get_loc("High")] = value
        result = build_chart_structure(invalid)
        assert result["issue"] and not result["events"]
    assert build_chart_structure(pd.concat([frame, frame.iloc[[-1]]]))["issue"]
    assert build_chart_structure(frame.reset_index(drop=True))["issue"]
    frame.loc[frame.index[-1], "High"] = frame.Close.iloc[-1] - 1
    assert "범위" in build_chart_structure(frame)["issue"]


def test_old_loaded_pattern_module_is_explicitly_reported_without_import_crash(monkeypatch):
    import stock_lab_core.chart_structure as module
    monkeypatch.setattr(module, "detect_chart_pattern_candidates", lambda df: [])
    assert "버전 불일치" in module.build_chart_structure(wave())["issue"]


def test_live_and_resampled_bars_do_not_become_confirmed_close_signals_early():
    frame = wave(10)
    frame.index = pd.bdate_range(end="2026-10-30", periods=10)
    assert last_bar_is_provisional(frame, "GOOGL", now=datetime(2026,10,30,15,tzinfo=timezone.utc))
    assert not last_bar_is_provisional(frame, "GOOGL", now=datetime(2026,10,31,7,tzinfo=timezone.utc))
    frame["LiveQuoteOnly"] = True
    assert last_bar_is_provisional(frame, "GOOGL", now=datetime(2026,10,31,7,tzinfo=timezone.utc))
    frame = frame.drop(columns="LiveQuoteOnly")
    frame.index = pd.bdate_range(end="2026-11-06", periods=10)
    assert last_bar_is_provisional(frame, "GOOGL", "weekly", now=datetime(2026,11,3,20,tzinfo=timezone.utc))


def test_overlays_keep_channels_on_price_axis_and_markers_visible_without_annotation_labels():
    fig = go.Figure()
    channel = build_parallel_channel(wave())
    add_channel_overlay(fig, channel)
    events = qualify_chart_events(event_context())
    add_event_overlays(fig, events)
    assert len([t for t in fig.data if t.mode == "lines"]) == 5
    marker = next(t for t in fig.data if t.name == "매수형 패턴")
    assert marker.marker.symbol[0] == "triangle-up"
    assert marker.x[0] == events[0]["time"]
    assert all(t.yaxis is None for t in fig.data)
