"""No score/permission writes; same completed session and risk basis throughout."""

import ast
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import soxl_short_observation as obs


def schedule(days=12, start="2026-11-02", early=False):
    dates = pd.bdate_range(start, periods=days)
    opening = dates.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)
    return pd.DataFrame({"market_open": opening.tz_convert("UTC"),
                         "market_close": (opening + pd.Timedelta(hours=3.5 if early else 6.5)).tz_convert("UTC")})


def fixture():
    sched = schedule()
    now = sched.market_close.iloc[-1] + pd.Timedelta(minutes=10)
    grid = obs.completed_hour_grid(sched, now)
    values = np.full(len(grid), 100.)
    frame = pd.DataFrame({"Open": values, "High": values + 2, "Low": values - 2,
                          "Close": values + 1, "Volume": values * 100}, index=grid)
    return sched, now, grid, frame


def channel(frame):
    return {"lower": [95.] * len(frame), "upper": [110.] * len(frame),
            "middle": [102.5] * len(frame), "x": frame.index.tolist()}


def test_completed_hours_exclude_active_afterhours_and_partial_session():
    sched = schedule(days=1)
    opening = sched.market_open.iloc[0]
    grid = obs.completed_hour_grid(sched, opening + pd.Timedelta(minutes=119))
    assert list(grid) == [opening]
    grid = obs.completed_hour_grid(sched, sched.market_close.iloc[0] + pd.Timedelta(hours=6))
    assert len(grid) == 6
    assert grid[-1] + obs.HOUR == sched.market_close.iloc[0] - pd.Timedelta(minutes=30)
    sched = schedule(days=1, early=True)
    assert len(obs.completed_hour_grid(sched, sched.market_close.iloc[0])) == 3


def test_dst_and_holiday_calendar_are_used():
    from stock_lab_core.report_eventstudy import _exchange_schedule
    sched = _exchange_schedule("US", "2026-10-30", "2026-11-28")
    grid = obs.completed_hour_grid(sched, pd.Timestamp("2026-11-28", tz="UTC"))
    assert pd.Timestamp("2026-10-30 13:30Z") in grid
    assert pd.Timestamp("2026-11-02 14:30Z") in grid
    assert not any(t.date().isoformat() == "2026-11-26" for t in grid)
    assert len(grid[grid.date == pd.Timestamp("2026-11-27").date()]) == 3


def test_plan_and_context_have_one_basis_and_do_not_mutate(monkeypatch):
    sched, now, grid, frame = fixture()
    frames = {t: frame.copy() for t in obs.SYMBOLS}
    before = deepcopy(frames)
    monkeypatch.setattr(obs, "build_parallel_channel", channel)
    model = obs.build_short_observation(frames, sched, now)
    plan = model["plan"]
    assert plan["entry"] == 101 and plan["stop"] == 95 and plan["target"] == 110
    assert plan["one_r"] == 107 and plan["rr"] == 1.5
    assert all(row["end"] == grid[-1] + obs.HOUR for row in model["rows"])
    for ticker in frames:
        pd.testing.assert_frame_equal(frames[ticker], before[ticker])
    assert "allow_current" not in model and "buy_amt" not in model


@pytest.mark.parametrize("entry", [94., 95., 110., 111., np.nan, np.inf])
def test_invalid_or_outside_channel_has_no_plan(entry):
    _, _, _, frame = fixture()
    frame.loc[frame.index[-1], "Close"] = entry
    assert obs.channel_plan(frame, channel(frame))[0] == {}


def test_upper_before_one_r_is_disclosed():
    _, _, _, frame = fixture()
    ch = channel(frame)
    ch["upper"][-1] = 104
    plan, _ = obs.channel_plan(frame, ch)
    assert plan["one_r"] == 107 and not plan["one_r_before_target"]


@pytest.mark.parametrize("fault", ["stale", "gap", "nan", "naive", "duplicate", "bad_ohlc", "empty"])
def test_unavailable_soxx_never_produces_plan(monkeypatch, fault):
    sched, now, grid, frame = fixture()
    if fault == "stale": frame = frame.iloc[:-1]
    if fault == "gap": frame = frame.drop(frame.index[-10])
    if fault == "nan": frame.loc[frame.index[-1], "Close"] = np.nan
    if fault == "naive": frame.index = frame.index.tz_localize(None)
    if fault == "duplicate": frame = pd.concat([frame, frame.iloc[-1:]])
    if fault == "bad_ohlc": frame.loc[frame.index[-1], "Low"] = 200
    if fault == "empty": frame = pd.DataFrame()
    monkeypatch.setattr(obs, "build_parallel_channel", channel)
    assert not obs.build_short_observation({"SOXX": frame}, sched, now)["plan"]


def test_missing_context_does_not_change_soxx_plan_or_shift_comparison(monkeypatch):
    sched, now, grid, frame = fixture()
    monkeypatch.setattr(obs, "build_parallel_channel", channel)
    model = obs.build_short_observation({"SOXX": frame, "QQQ": frame.iloc[:-1]}, sched, now)
    assert model["plan"]
    assert model["rows"][1]["close"] is None
    assert model["rows"][3]["change_pct"] is None
    assert model["status"] == "채널 내부 관찰"
    assert "과거값" in model["rows"][3]["status"]


def test_premarket_and_unfinished_bars_cannot_change_result(monkeypatch):
    sched, now, grid, frame = fixture()
    monkeypatch.setattr(obs, "build_parallel_channel", channel)
    extras = frame.iloc[-1:].copy()
    extras.index = pd.DatetimeIndex([sched.market_close.iloc[-1] + pd.Timedelta(hours=1)])
    extras *= 10
    before = obs.build_short_observation({"SOXX": frame}, sched, now)
    after = obs.build_short_observation({"SOXX": pd.concat([frame, extras])}, sched, now)
    assert after["plan"] == before["plan"]


def test_real_channel_is_parallel_and_confirmed():
    sched, now, grid, frame = fixture()
    wave = 100 + np.sin(np.arange(len(grid)) * .3) * 5 + np.arange(len(grid)) * .12
    for col, offset in (("Open", 0), ("High", 2), ("Low", -2), ("Close", .3)):
        frame[col] = wave + offset
    model = obs.build_short_observation({"SOXX": frame}, sched, now)
    ch = model["channel"]
    assert ch and ch["known_at"] <= grid[-1]
    np.testing.assert_allclose(np.diff(ch["upper"]), np.diff(ch["lower"]))


class UI:
    def __init__(self, clicked=False):
        self.clicked, self.session_state, self.text, self.tables = clicked, {}, [], []
    def expander(self, *args, **kwargs): return nullcontext()
    def spinner(self, *args, **kwargs): return nullcontext()
    def button(self, *args, **kwargs): return self.clicked
    def markdown(self, text): self.text.append(text)
    def caption(self, text): self.text.append(text)
    def info(self, text): self.text.append(text)
    def warning(self, text): self.text.append(text)
    def write(self, text): self.text.append(str(text))
    def number_input(self, label, **kwargs): return kwargs.get("value", 0)
    def download_button(self, *args, **kwargs): pass
    def table(self, rows): self.tables.append(rows)
    def dataframe(self, rows, **kwargs): self.tables.append(rows)
    def plotly_chart(self, fig, **kwargs): pass


def test_render_is_opt_in_soxl_only_and_preserves_decision(monkeypatch):
    from stock_lab_core import soxl_short_view as view
    def fail(): raise AssertionError("unexpected fetch")
    monkeypatch.setattr(view, "load_short_hours", fail)
    decision = {"execution_workflow": {"게이트상태": "방어우선", "게이트근거": "레버리지 시장방어"}, "buy_amt": 0}
    before = deepcopy(decision)
    ui = UI()
    view.render_soxl_short_observation(ui, "SOXL", decision)
    assert "매수 승인 아님" in " ".join(ui.text)
    assert decision == before and not ui.session_state
    ui = UI(clicked=True)
    view.render_soxl_short_observation(ui, "RAM", decision)
    assert not ui.text


def test_loader_requests_reference_and_soxl_in_one_regular_hourly_batch(monkeypatch):
    import yfinance
    from stock_lab_core import soxl_short_data as data
    _, _, _, frame = fixture()
    def download(tickers, **kwargs):
        assert tuple(tickers) == (*obs.SYMBOLS, "SOXL")
        assert kwargs["interval"] == "60m" and not kwargs["prepost"]
        assert kwargs["auto_adjust"] and not kwargs["ignore_tz"]
        assert kwargs["timeout"] == 6
        return pd.concat({ticker: frame for ticker in tickers}, axis=1)
    monkeypatch.setattr(yfinance, "download", download)
    assert data.load_short_hours.__wrapped__()["ok"]
    monkeypatch.setattr(yfinance, "download", lambda *a, **kw: frame)
    assert not data.load_short_hours.__wrapped__()["ok"]


def test_loader_failure_is_explicit_not_zero(monkeypatch):
    import yfinance
    from stock_lab_core import soxl_short_data as data
    def fail(*args, **kwargs): raise TimeoutError("provider timeout")
    monkeypatch.setattr(yfinance, "download", fail)
    result = data.load_short_hours.__wrapped__()
    assert not result["ok"] and result["frames"] == {}
    assert "TimeoutError" in result["issue"]


def test_no_fetch_on_rerender_and_missing_plan_visible(monkeypatch):
    from stock_lab_core import soxl_short_view as view
    ui = UI()
    ui.session_state[f"soxl_short_hours_v{obs.VERSION}_paired"] = {
        "frames": {}, "captured_at": "2026-11-13T05:30Z", "issue": "timeout"}
    monkeypatch.setattr(view, "_exchange_schedule", lambda *args: schedule())
    def fail(): raise AssertionError("rerender must not fetch")
    monkeypatch.setattr(view, "load_short_hours", fail)
    view.render_soxl_short_observation(ui, "SOXL", {})
    assert "계획 보류" in " ".join(ui.text)


def test_soxx_invalid_ohlc_does_not_pass_or_draw_reconstructed_prices():
    sched, now, grid, frame = fixture()
    frame.loc[frame.index[-1], "High"] = 1
    model = obs.build_short_observation({"SOXX": frame}, sched, now)
    assert not model["plan"] and pd.isna(model["frame"].Close.iloc[-1])


def test_wiring_is_display_only_outside_existing_calculation_functions():
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8-sig"))
    for function in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == "render_soxl_short_observation" for n in ast.walk(function))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "render_soxl_short_observation"]
    assert len(calls) == 1
