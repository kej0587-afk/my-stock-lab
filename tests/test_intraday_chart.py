import pandas as pd
import pytest

from stock_lab_core import chart_preferences as cp
from stock_lab_core import intraday_chart as ic
from stock_lab_core.report_history_store import ReportHistoryStoreError


def _bars(starts, tz="America/New_York"):
    index = pd.DatetimeIndex(pd.to_datetime(starts)).tz_localize(tz)
    n = len(index)
    return pd.DataFrame({"Open": [10.0 + i for i in range(n)], "High": [11.0 + i for i in range(n)],
                         "Low": [9.0 + i for i in range(n)], "Close": [10.5 + i for i in range(n)],
                         "Volume": [100.0 * (i + 1) for i in range(n)]}, index=index)


def test_parse_ma_periods_keeps_valid_sorted_unique_and_reports_rest():
    periods, rejected = ic.parse_ma_periods("20, 5 1000/5, abc, 1, 9999")
    assert periods == [5, 20, 1000]
    assert rejected == ["abc", "1", "9999"]


def test_pair_sixty_minute_bars_pairs_within_session_and_keeps_short_last_bar():
    day1 = [f"2026-11-24 {h}" for h in ("09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30")]
    day2 = ["2026-11-25 09:30", "2026-11-25 10:30", "2026-11-25 11:30"]
    out = ic.pair_sixty_minute_bars(_bars(day1 + day2))
    assert [t.strftime("%m-%d %H:%M") for t in out.index] == [
        "11-24 09:30", "11-24 11:30", "11-24 13:30", "11-24 15:30", "11-25 09:30", "11-25 11:30"]
    first = out.iloc[0]
    assert (first.Open, first.High, first.Low, first.Close, first.Volume) == (10.0, 12.0, 9.0, 11.5, 300.0)
    assert out.iloc[3].Volume == 700.0  # 15:30 bar alone, never merged with next day
    assert str(out.index.tz) == "America/New_York"


def test_merge_tail_replaces_live_bar_and_appends_new():
    history = _bars(["2026-11-25 09:30", "2026-11-25 09:31"])
    tail = _bars(["2026-11-25 09:31", "2026-11-25 09:32"])
    tail.loc[tail.index[0], "Close"] = 99.0
    merged = ic.merge_tail(history, tail)
    assert len(merged) == 3 and merged.Close.iloc[1] == 99.0


def test_moving_average_shortage_gives_no_line_and_counts():
    frame = _bars([f"2026-11-25 09:{m:02d}" for m in range(30, 40)])
    lines, status = ic.moving_averages(frame, [5, 20])
    assert list(lines) == [5]
    assert lines[5].isna().sum() == 4 and lines[5].iloc[-1] == pytest.approx(frame.Close.iloc[-5:].mean())
    assert status[20] == {"ok": False, "have": 10, "need": 20}


def test_daily_overlay_uses_previous_completed_close_only():
    daily = _bars(["2026-11-20", "2026-11-21", "2026-11-24", "2026-11-25"])  # closes 10.5 11.5 12.5 13.5
    bars = _bars(["2026-11-25 09:30", "2026-11-25 09:31"])
    lines, status = ic.daily_overlay(daily, bars, [2, 4])
    # On 11-25 the 2-day SMA known is through 11-24: (11.5 + 12.5) / 2
    assert list(lines[2]) == [12.0, 12.0]
    assert status[4] == {"ok": False, "have": 4, "need": 4}


def test_last_bar_state_marks_in_progress_and_lag():
    frame = _bars(["2026-11-25 10:00", "2026-11-25 10:05"])
    session = {"phase": "intraday", "close": pd.Timestamp("2026-11-25 16:00", tz="America/New_York")}
    now = pd.Timestamp("2026-11-25 10:07", tz="America/New_York")
    state = ic.last_bar_state(frame, "5분", now, session)
    assert state["provisional"] is True and state["lag_minutes"] == pytest.approx(2.0)
    closed = ic.last_bar_state(frame, "5분", now, {"phase": "closed"})
    assert closed["provisional"] is False and closed["lag_minutes"] is None


def test_build_frame_120_pairs_after_merging_tail():
    history = _bars(["2026-11-25 09:30", "2026-11-25 10:30"])
    tail = _bars(["2026-11-25 10:30", "2026-11-25 11:30"])
    out = ic.build_frame(history, tail, "120분")
    assert len(out) == 2 and out.Volume.iloc[1] == 200.0


def test_preferences_normalize_and_store_fallbacks():
    prefs = cp.normalize({"periods": ["1000", 5, 5, "x", 1], "enabled": [1000, 7], "interval": "3분"})
    assert prefs == {"periods": [5, 1000], "enabled": [1000], "daily_overlay": False, "interval": "일봉"}

    class Missing:
        def load(self):
            raise ReportHistoryStoreError("schema_unavailable")

        def save(self, prefs):
            raise ReportHistoryStoreError("schema_unavailable")

    state = {}
    assert cp.load_into_state(state, Missing()) == cp.DEFAULTS
    assert state[cp.STATUS_KEY] == "table_missing"
    assert cp.save_from_state(state, {"periods": [7]}, Missing()) == "table_missing"
    assert state[cp.STATE_KEY]["periods"] == [7]


def test_supabase_store_filters_owner():
    calls = {}

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_):
            return self

        def eq(self, field, value):
            calls[field] = value
            return self

        def limit(self, _):
            return self

        def upsert(self, row, on_conflict):
            calls["upsert"] = (row, on_conflict)
            self.rows = [row]
            return self

        def execute(self):
            return type("R", (), {"data": self.rows})()

    class Client:
        def __init__(self, rows):
            self.rows = rows

        def table(self, name):
            assert name == "chart_preferences"
            return Query(self.rows)

    store = cp.SupabaseChartPreferenceStore(Client([{"owner_email": "a@b.c", "prefs": {"periods": [3]}}]),
                                            owner_scope=" A@B.C ")
    assert store.load()["periods"] == [3] and calls["owner_email"] == "a@b.c"
    store.save({"periods": [9], "enabled": [9]})
    assert calls["upsert"][1] == "owner_email" and calls["upsert"][0]["prefs"]["enabled"] == [9]
    other = cp.SupabaseChartPreferenceStore(Client([{"owner_email": "x@y.z", "prefs": {}}]), owner_scope="a@b.c")
    with pytest.raises(ReportHistoryStoreError):
        other.load()
