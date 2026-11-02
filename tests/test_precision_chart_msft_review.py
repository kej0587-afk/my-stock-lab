"""MSFT chart presentation regressions; trading formulas remain untouched."""

from copy import deepcopy
from itertools import product

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.chart_execution import build_chart_execution_guide, pick_support_zone
from stock_lab_core.chart_patterns import detect_chart_pattern_candidates
from stock_lab_core.chart_structure import build_chart_structure, build_parallel_channel
from stock_lab_core.precision_chart_view import build_price_figure, finish_price_figure, prepare_chart_layers
from tests.test_chart_structure import wave


@pytest.mark.parametrize("patterns,channel,signals", product((False, True), repeat=3))
def test_layer_switches_are_independent_and_do_not_recompute_cached_patterns(patterns, channel, signals):
    frame = wave()
    structure = {"channel": build_parallel_channel(frame), "patterns": [{"name": "fixture"}], "events": []}
    original = deepcopy(structure)
    calls = []
    def load(df):
        calls.append("structure")
        return structure
    def detect(df):
        calls.append("patterns")
        return structure["patterns"]
    def guides(df):
        calls.append("guides")
        return [{"kind": "support", "y1": 999}]
    result, found, rail, lines = prepare_chart_layers(
        frame, show_patterns=patterns, show_channel=channel, show_signals=signals,
        load_structure=load, detect_patterns=detect, build_trendlines=guides)
    assert bool(result) == (channel or signals)
    assert bool(rail) == channel
    assert bool(found) == patterns
    assert calls.count("patterns") == int(patterns and not (channel or signals))
    assert calls.count("guides") == int(patterns and not channel)
    if channel:
        assert [g["y1"] for g in lines] == [rail["lower"][-1], rail["upper"][-1]]
        assert all(g["source"] == "parallel_channel" for g in lines)
    assert structure == original


def test_cached_pattern_reuse_matches_original_and_keeps_channel_geometry():
    frame = wave(251)
    original = frame.copy(deep=True)
    structure = build_chart_structure(frame)
    _, patterns, channel, _ = prepare_chart_layers(
        frame, show_patterns=True, show_channel=True, show_signals=True,
        load_structure=lambda _: structure, detect_patterns=lambda _: pytest.fail("duplicate calculation"),
        build_trendlines=lambda _: pytest.fail("undrawn guides"))
    assert patterns == detect_chart_pattern_candidates(frame)
    assert channel == build_parallel_channel(frame)
    np.testing.assert_allclose(np.diff(channel["lower"]), np.diff(channel["upper"]))
    pd.testing.assert_frame_equal(frame, original)


def test_channel_explanation_uses_drawn_msft_prices_not_hidden_trendlines():
    frame = wave()
    channel = dict(build_parallel_channel(frame), lower=[491.22, 521.528586],
                   upper=[535.99573, 566.304317], x=list(frame.index[-2:]))
    frame.loc[frame.index[-2:], "Close"] = [522.65, 522.65]
    _, _, _, guides = prepare_chart_layers(
        frame, show_patterns=True, show_channel=True, show_signals=False,
        load_structure=lambda _: {"channel": channel, "patterns": []},
        detect_patterns=lambda _: [], build_trendlines=lambda _: pytest.fail("hidden line"))
    text = build_chart_execution_guide([], guides, {}, {}, "MSFT", 522.65)
    assert "평행 채널" in text and "$566.30" in text and "$521.53" in text
    assert "매수·매도 판정은 아닙니다" in text
    assert pick_support_zone(guides, {}, {}, "MSFT", 522.65)["label"] == "채널 하단"


def test_crowded_price_names_are_separated_without_moving_price_zones_or_candles():
    frame = wave()
    fig = build_price_figure(frame)
    for price, label in ((170, "OB 저항"), (170.1, "FVG 저항"), (170.2, "EQH")):
        fig.add_hline(y=price, annotation_text=label)
    fig.add_annotation(x=frame.index[-10], y=168, text="쌍바닥 구조", showarrow=True, ay=28)
    shapes = [s.to_plotly_json() for s in fig.layout.shapes]
    candle = fig.data[0].to_plotly_json()
    finish_price_figure(fig, frame, pd.DataFrame(), show_level_labels=True)
    labels = fig.layout.annotations[:3]
    height = fig.layout.height - fig.layout.margin.t - fig.layout.margin.b
    low, high = frame.Low.min(), frame.High.max()
    positions = [(a.y-low)/(high-low)*height-a.ay for a in labels]
    assert np.diff(positions).min() >= 21.99
    assert [a.y for a in labels] == [170, 170.1, 170.2]
    assert labels[2].text == "동일 고점 170.20"
    assert fig.layout.margin.r >= 140 and all(a.xanchor == "left" for a in labels)
    assert fig.layout.annotations[-1].text == "쌍바닥 구조"
    assert fig.layout.annotations[-1].ay == 28
    assert [s.to_plotly_json() for s in fig.layout.shapes] == shapes
    for key in ("open", "high", "low", "close", "x"):
        np.testing.assert_array_equal(fig.data[0][key], candle[key])


def test_precision_renderer_keeps_channel_when_patterns_hidden(app_module, monkeypatch):
    frame = wave()
    plots = []
    monkeypatch.setattr(app_module.st, "plotly_chart", lambda fig, **kw: plots.append(fig))
    result = app_module.render_precision_candlestick_chart(
        frame, show_patterns=False, show_channel=True, show_signals=False,
        show_liquidity=False, show_smc=False, ticker="MSFT")
    assert result["channel"]
    assert {"채널 하단", "채널 중심", "채널 상단"} <= {t.name for t in plots[0].data}
    assert result["events"] == [] and result["patterns"] == []


def test_old_cloud_chart_module_does_not_crash_app_or_display_mixed_chart(app_module, monkeypatch):
    from stock_lab_core import precision_chart_view
    warnings = []
    monkeypatch.delattr(precision_chart_view, "prepare_chart_layers")
    monkeypatch.setattr(app_module.st, "warning", warnings.append)
    monkeypatch.setattr(app_module.st, "plotly_chart", lambda *a, **kw: pytest.fail("mixed chart"))
    assert app_module.render_precision_candlestick_chart(wave()) == {}
    assert "Reboot app" in warnings[0]


def test_timeframe_comment_does_not_override_final_execution_policy(app_module, monkeypatch):
    frame = wave()
    frame["MA5"], frame["MA20"], frame["MA50"] = 185., 185., 150.
    frame["RSI"], frame["MFI"], frame["%B"] = 49., 20., .12
    frame["MACD"], frame["MACD_Sig"] = 0., 1.
    monkeypatch.setattr(app_module, "get_precision_timeframe_trend", lambda *a: "🚀정배열(상승)")
    result = app_module.build_precision_timeframe_snapshot("일봉", frame, _indicators_ready=True)
    assert result["state"] == "상승추세 내 조정"
    assert "실행 판단과 최종 체크" in result["summary"]
    assert "신규진입은 보류" not in result["summary"]


@pytest.mark.parametrize("target,current", [(0, 0), (5, 5), (5, 1), (0, 1)])
def test_plan_amounts_prices_and_status_match_baseline_except_unset_weight_text(app_module, monkeypatch, target, current):
    import ast
    import subprocess
    from pathlib import Path
    from stock_lab_core import precision_plan_panel

    monkeypatch.setattr(app_module, "get_target_weight_from_sheet", lambda *a: 0)
    monkeypatch.setattr(app_module, "get_sheet_current_weight", lambda *a: 0)
    monkeypatch.setattr(precision_plan_panel, "render_entry_plan_panel", lambda *a, **kw: {})
    source = subprocess.check_output(
        ["git", "show", "4b24b751:app.py"], encoding="utf8", cwd=Path(__file__).resolve().parents[1])
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "render_entry_execution_plan")
    env = dict(vars(app_module))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<original-plan>", "exec"), env)
    decision = dict(cur_p=522.65, atr=11.7378627, rr_stop=499.1743, rr_target=551.150024,
                    rr_ratio=1.2140223, target_w=target, current_w=current,
                    effective_total_asset=20000000, decision_code="NEW_ENTRY_LEADER",
                    asset_class="us_stock", is_leveraged_or_inverse=False)
    expected = env[fn.name]("Microsoft", "MSFT", decision)
    actual = app_module.render_entry_execution_plan("Microsoft", "MSFT", decision)
    if target == current == 0:
        assert "미설정" in actual["rows"][0]["조건"]
        actual["rows"][0]["조건"] = expected["rows"][0]["조건"]
    assert actual == expected
