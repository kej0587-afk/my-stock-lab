"""A broken historical channel must not supply a current entry price."""

from copy import deepcopy

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from stock_lab_core.chart_structure import add_channel_overlay, build_chart_structure
from stock_lab_core.precision_chart_view import (
    channel_caption, prepare_channel_display, prepare_chart_layers,
)
from tests.test_chart_structure import wave


def fixture(direction="상승"):
    times = pd.bdate_range("2026-09-01", periods=12)
    slope = 1 if direction == "상승" else -1
    lower = 100 + slope * np.arange(len(times))
    frame = pd.DataFrame({"Close": lower + 5}, index=times)
    channel = dict(direction=direction, state="채널 내부", x=list(times),
                   lower=lower.tolist(), middle=(lower + 5).tolist(),
                   upper=(lower + 10).tolist(), slope=slope, width=10,
                   known_at=times[5], anchors=[{"time": times[0], "price": 100}])
    return frame, channel


@pytest.mark.parametrize("direction", ["상승", "하락"])
def test_broken_channel_ends_at_first_confirmed_break_even_after_recovery(direction):
    frame, channel = fixture(direction)
    frame.iloc[7, 0] = channel["lower"][7] - 1 if direction == "상승" else channel["upper"][7] + 1
    before = deepcopy(channel)
    display = prepare_channel_display(frame, channel)
    assert display["ended_at"] == frame.index[7]
    assert not display["execution_guide_eligible"]
    assert display["lower"] == channel["lower"] and display["upper"] == channel["upper"]
    assert channel == before
    fig = go.Figure()
    add_channel_overlay(fig, display)
    assert len(fig.data) == 4  # Three rails plus their actual anchor markers.
    assert all(len(t.x) == 8 for t in fig.data[:3])
    assert all(t.name.startswith("과거") for t in fig.data[:3])
    np.testing.assert_allclose(np.diff(fig.data[0].y), np.diff(fig.data[2].y))
    np.testing.assert_allclose(np.array(fig.data[2].y) - fig.data[0].y, 10)
    assert "종료봉 기준" in channel_caption(display)
    assert "현재 지지·저항 안내에서 제외" in channel_caption(display)


@pytest.mark.parametrize("direction", ["상승", "하락"])
def test_only_confirmed_closes_can_retire_channel(direction):
    frame, channel = fixture(direction)
    frame.iloc[-1, 0] = channel["lower"][-1] - 1 if direction == "상승" else channel["upper"][-1] + 1
    pending = prepare_channel_display(frame, channel, provisional_last=True)
    assert "ended_at" not in pending
    assert not pending["execution_guide_eligible"]
    assert "미확정 봉" in channel_caption(pending)
    confirmed = prepare_channel_display(frame, channel)
    assert confirmed["ended_at"] == frame.index[-1]


def test_quote_only_and_pre_confirmation_crosses_are_not_finalized():
    frame, channel = fixture()
    frame.iloc[2, 0] = 1
    frame.iloc[7, 0] = 1
    frame["LiveQuoteOnly"] = False
    frame.loc[frame.index[7], "LiveQuoteOnly"] = True
    assert prepare_channel_display(frame, channel) == channel


def test_countertrend_break_at_confirmation_is_not_current_support():
    frame, channel = fixture()
    frame.iloc[5, 0] = 100
    result, patterns, display, guides = prepare_chart_layers(
        frame, show_patterns=True, show_channel=True, show_signals=True,
        load_structure=lambda _: {"channel": channel, "patterns": [], "events": [{"side": "sell"}]},
        detect_patterns=lambda _: pytest.fail("cached patterns"),
        build_trendlines=lambda _: pytest.fail("must not replace retired channel with undrawn guides"))
    assert display["ended_at"] == channel["known_at"]
    assert guides == [] and patterns == []
    assert result["events"] == [{"side": "sell"}] and result["channel"] == channel


@pytest.mark.parametrize("direction", ["상승", "하락"])
def test_trend_direction_breakout_does_not_retire_channel(direction):
    frame, channel = fixture(direction)
    frame.iloc[-1, 0] = channel["upper"][-1] + 1 if direction == "상승" else channel["lower"][-1] - 1
    assert prepare_channel_display(frame, channel) == channel


def test_display_cannot_see_future_break_or_mutate_cached_events():
    frame = wave()
    structure = build_chart_structure(frame)
    before = deepcopy(structure)
    original_frame = frame.copy(deep=True)
    prepare_chart_layers(frame, show_patterns=True, show_channel=True, show_signals=True,
                         load_structure=lambda _: structure, detect_patterns=lambda _: [],
                         build_trendlines=lambda _: [])
    assert structure == before
    pd.testing.assert_frame_equal(frame, original_frame)
    frame, channel = fixture()
    prefix = {key: value[:8] if key in {"x", "lower", "upper", "middle"} else value
              for key, value in channel.items()}
    earlier = prepare_channel_display(frame.iloc[:8], prefix)
    frame.iloc[10, 0] = 1
    assert "ended_at" not in earlier
    assert prepare_channel_display(frame, channel)["ended_at"] == frame.index[10]


def test_418660_export_regression_stops_september_channel_before_november():
    # Public price/rail values only; no holdings or account data from the export.
    dates = "09-14 09-15 09-16 09-17 09-18 09-21 09-22 09-23 09-28 09-29 09-30 10-01 10-02 10-06 10-07 10-08 10-12 10-13 10-14 10-15 10-16 10-19 10-20 10-21 10-22 10-23 10-26 10-27 10-28 10-29 10-30 11-02".split()
    times = pd.to_datetime(["2026-" + d for d in dates])
    closes = [36925,37670,38015,39060,40275,40895,41140,42010,41150,40510,40525,42240,41110,42065,42080,41565,41025,40235,40145,38155,38200,37230,36670,36930,36145,35405,34995,35615,37905,37120,35395,35280]
    lower = 36585 + np.arange(32) * (40070 - 36585) / 9
    width = 42370 - lower[6]
    channel = dict(direction="상승", state="하단 이탈", x=list(times), lower=lower.tolist(),
                   upper=(lower + width).tolist(), middle=(lower + width / 2).tolist(),
                   width=width, slope=(40070 - 36585) / 9, known_at=times[12], anchors=[])
    display = prepare_channel_display(pd.DataFrame({"Close": closes}, index=times), channel, provisional_last=True)
    assert display["ended_at"] == pd.Timestamp("2026-10-02")
    assert display["display_end_index"] == 12
    assert "48,588" not in channel_caption(display)
    assert not display["execution_guide_eligible"]


@pytest.mark.parametrize("name", ["render_personal_stock_analysis_panel", "build_pre_buy_final_checks"])
def test_explanation_edits_leave_every_policy_expression_unchanged(name):
    import ast
    from pathlib import Path
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    before = subprocess.check_output(["git", "show", "3d1934ae:app.py"], cwd=repo, encoding="utf8")
    after = (repo / "app.py").read_text(encoding="utf8")
    replacements = {
        "낙폭이 커진 구간입니다. 추세훼손 확정은 아니며 하락 원인과 종가 안정 확인":
        "낙폭 기준의 가격 경고입니다. 추세 상태는 위 시간대별 표, 추가매수 여부는 최종 체크를 함께 확인합니다.",
        "고점대비 낙폭이 큰 가격방어 구간입니다. 추세훼손 확정은 아니며 하락 원인과 종가 안정 확인이 우선입니다.":
        "고점대비 낙폭이 큰 가격방어 구간입니다. 이 낙폭 분류만으로 추세 상태를 단정하지 않으며, 시간대별 추세와 최종 체크를 함께 확인합니다.",
        ". 풀비중보다 1차 정찰 중심이 맞습니다.":
        ". 실행이 허용된 경우에만 풀비중보다 1차 정찰 중심으로 검토합니다. 방어·차단 상태에서는 추가매수 보류가 우선입니다.",
    }
    old_fn, new_fn = [next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)
                      for src in (before, after)]
    changed = 0
    for node in ast.walk(old_fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in replacements:
            node.value = replacements[node.value]
            changed += 1
    assert changed == (2 if name == "render_personal_stock_analysis_panel" else 1)
    assert ast.dump(old_fn) == ast.dump(new_fn)


def test_old_overlay_module_cannot_draw_extended_rails_with_new_caption(app_module, monkeypatch):
    from stock_lab_core import chart_structure
    warnings = []
    monkeypatch.delattr(chart_structure, "CHANNEL_DISPLAY_VERSION")
    monkeypatch.setattr(app_module.st, "warning", warnings.append)
    monkeypatch.setattr(app_module.st, "plotly_chart", lambda *a, **kw: pytest.fail("mixed chart versions"))
    assert app_module.render_precision_candlestick_chart(wave()) == {}
    assert "Reboot app" in warnings[0]
