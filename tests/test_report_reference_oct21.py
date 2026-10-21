from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pandas as pd
import pytest

from stock_lab_core import report_reference as reference
from stock_lab_core.report_prices import MACRO_SYMBOLS, aligned_macro

NOW = pd.Timestamp("2026-10-21T09:00:00+09:00")
DAY = "2026-10-20"
NAMES = {symbol: name for name, symbol in MACRO_SYMBOLS.items()}


def bars(points, *, interval=None):
    rows, index = [], []
    for day, value in points.items():
        anchor = pd.Timestamp(day + " 16:00", tz="America/New_York")
        index.extend([anchor - pd.Timedelta(minutes=10), anchor - pd.Timedelta(minutes=5), anchor])
        rows.extend([1, value, 9999])
    frame = pd.DataFrame({"Close": rows}, index=pd.DatetimeIndex(index).tz_convert("UTC"))
    if interval:
        frame.attrs["interval"] = interval
    return frame


def daily(points):
    return pd.DataFrame({"Close": list(points.values())}, index=pd.to_datetime(list(points)))


def us_history():
    return pd.DataFrame({"Close": 100.}, index=pd.bdate_range(end=DAY, periods=22))


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "DEFAULT_CACHE_DIR", tmp_path / "references")


@pytest.mark.parametrize("symbol", list(reference.REFERENCE_SYMBOLS))
def test_same_date_reuses_exact_snapshot_after_raw_price_revision(symbol, tmp_path):
    first = reference.snapshot_at_us_close(bars({DAY: 72.5}), symbol, DAY, NOW, cache_dir=tmp_path)
    changed = reference.snapshot_at_us_close(bars({DAY: 88}), symbol, DAY, NOW + pd.Timedelta(hours=2), cache_dir=tmp_path)
    offline = reference.snapshot_at_us_close(None, symbol, DAY, NOW + pd.Timedelta(hours=3), cache_dir=tmp_path)
    assert first["val"] == 72.5
    assert first == changed == offline
    # A fresh read does not depend on a cached Python object or caller mutations.
    first["val"] = 999
    assert reference.snapshot_at_us_close(None, symbol, DAY, NOW, cache_dir=tmp_path)["val"] == 72.5
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_next_date_requires_and_captures_a_fresh_anchor(tmp_path):
    old = reference.snapshot_at_us_close(bars({DAY: 72.5}), "CL=F", DAY, NOW, cache_dir=tmp_path)
    next_day, later = "2026-10-21", NOW + pd.Timedelta(days=1)
    assert reference.snapshot_at_us_close(bars({DAY: 72.5}), "CL=F", next_day, later, cache_dir=tmp_path) == {}
    fresh = reference.snapshot_at_us_close(bars({DAY: 88, next_day: 73}), "CL=F", next_day, later, cache_dir=tmp_path)
    assert fresh["val"] == 73 and fresh["as_of"] == next_day
    assert reference.snapshot_at_us_close(None, "CL=F", DAY, later, cache_dir=tmp_path) == old


def test_source_and_exact_asof_are_distinct_from_capture_time():
    frame = bars({DAY: 72.5})
    frame.attrs["token"] = "never-store-frame-attrs"
    row = reference.snapshot_at_us_close(frame, "CL=F", DAY, NOW)
    assert row["as_of"] == DAY
    assert row["as_of_at"] == "2026-10-20T16:00:00-04:00"
    assert row["bar_start"] == "2026-10-20T15:55:00-04:00"
    assert row["captured_at"] == NOW.isoformat()
    assert "Yahoo Finance CL=F 5m" in row["source"]
    assert row["as_of_at"] in row["source"]
    assert "not official settlement" in row["source"]
    saved = next(reference.DEFAULT_CACHE_DIR.glob("*.json")).read_text(encoding="utf-8")
    assert "never-store-frame-attrs" not in saved
    assert "token" not in saved


@pytest.mark.parametrize("day,offset", [("2026-10-20", "-04:00"), ("2026-11-03", "-05:00")])
def test_new_york_anchor_tracks_dst(day, offset):
    now = pd.Timestamp(day + "T23:00:00Z")
    row = reference.snapshot_at_us_close(bars({day: 72}), "CL=F", day, now)
    assert row["as_of_at"] == day + "T16:00:00" + offset


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf"), 0, -1, "bad", True])
def test_missing_or_invalid_bar_never_becomes_zero_or_older_price(value):
    row = reference.snapshot_at_us_close(bars({DAY: value}), "CL=F", DAY, NOW)
    assert row == {}
    assert not reference.DEFAULT_CACHE_DIR.exists()
    # An invalid first observation must not block later valid data.
    assert reference.snapshot_at_us_close(bars({DAY: 73}), "CL=F", DAY, NOW)["val"] == 73


@pytest.mark.parametrize("shape", ["missing", "naive", "daily", "duplicate", "1m", "unlabelled_1m", "isolated", "no_close"])
def test_unverifiable_frames_are_not_snapshots(shape):
    frame = bars({DAY: 72})
    if shape == "missing":
        frame = frame.iloc[[0, 2]]
    elif shape == "naive":
        frame.index = frame.index.tz_localize(None)
    elif shape == "daily":
        frame = daily({DAY: 72})
    elif shape == "duplicate":
        frame = pd.concat([frame, frame.iloc[[1]]])
    elif shape == "1m":
        frame.attrs["interval"] = "1m"
    elif shape == "unlabelled_1m":
        frame = frame.reindex(pd.date_range(frame.index[0], frame.index[-1], freq="1min")).ffill()
    elif shape == "isolated":
        frame = frame.iloc[[1]]
    elif shape == "no_close":
        frame = frame.rename(columns={"Close": "Open"})
    assert reference.snapshot_at_us_close(frame, "CL=F", DAY, NOW) == {}


def test_future_anchor_and_naive_now_cannot_seed_or_reuse_snapshot():
    frame = bars({DAY: 72})
    before_close = pd.Timestamp("2026-10-20T19:59:59Z")
    assert reference.snapshot_at_us_close(frame, "CL=F", DAY, before_close) == {}
    assert reference.snapshot_at_us_close(frame, "CL=F", DAY, NOW.tz_localize(None)) == {}
    assert reference.snapshot_at_us_close(frame, "CL=F", DAY, NOW)
    assert reference.snapshot_at_us_close(frame, "CL=F", DAY, before_close) == {}


def test_explicit_5m_sparse_bar_and_exact_completion_are_accepted():
    frame = bars({DAY: 72}, interval="5m").iloc[[1]]
    at_close = pd.Timestamp("2026-10-20T20:00:00Z")
    assert reference.snapshot_at_us_close(frame, "CL=F", DAY, at_close)["val"] == 72


def test_aligned_macro_freezes_both_return_endpoints_not_daily_prices(tmp_path):
    history = us_history()
    base = history.index[-22].date().isoformat()
    frames = {"^GSPC": history, "CL=F": history * 10, "USDKRW=X": history * 20}
    intraday = {"CL=F": bars({base: 60, "2026-10-19": 70, DAY: 72})}
    first = aligned_macro(frames, DAY, NOW, scenario_frames=intraday, cache_dir=tmp_path)[NAMES["CL=F"]]
    changed = aligned_macro({key: frame * 99 for key, frame in frames.items()}, DAY, NOW,
                            scenario_frames={"CL=F": bars({base: 80, "2026-10-19": 90, DAY: 99})},
                            cache_dir=tmp_path)[NAMES["CL=F"]]
    assert first == changed
    assert first["val"] == 72
    assert first["day_ret"] == pytest.approx(72 / 70 - 1)
    assert first["chg"] == pytest.approx(20)
    assert first["previous_date"] == "2026-10-19"
    assert first["base_date"] == base
    assert first["base_as_of_at"].endswith("T16:00:00-04:00")
    assert first["previous_as_of_at"].endswith("T16:00:00-04:00")
    assert first["comparison_missing"] == {}
    assert first["stress_incomplete"] is False
    assert first["base_as_of_at"] in first["chg_source"]
    assert first["as_of_at"] in first["chg_source"]
    assert first["previous_as_of_at"] in first["day_ret_source"]
    assert "not official settlement" in first["chg_source"]


def test_daily_only_24h_assets_are_omitted_but_index_path_is_unchanged():
    history = us_history()
    frames = {symbol: history.copy() for symbol in MACRO_SYMBOLS.values()}
    result = aligned_macro(frames, DAY, NOW)
    assert NAMES["CL=F"] not in result
    assert NAMES["USDKRW=X"] not in result
    assert set(result) == {NAMES[symbol] for symbol in ("^TNX", "^VIX", "^MOVE")}
    assert result["VIX"]["val"] == 100
    assert result["VIX"]["chg"] == 0
    assert result["VIX"]["source"].startswith("Yahoo Finance daily")


def test_no_misaligned_month_or_day_comparison_and_no_frame_mutation():
    history = us_history()
    frames = {"^GSPC": history, "CL=F": history * 12}
    frame = bars({"2026-10-18": 71, DAY: 72})
    untouched = frame.copy(deep=True)
    result = aligned_macro(frames, DAY, NOW, scenario_frames={"CL=F": frame})[NAMES["CL=F"]]
    assert result["val"] == 72
    assert result["day_ret"] is None and result["previous_date"] == ""
    assert result["chg"] is None and result["base_date"] == ""
    assert result["base_as_of_at"] == result["previous_as_of_at"] == ""
    assert result["chg_source"] == result["day_ret_source"] == ""
    assert result["stress_incomplete"] is True
    assert set(result["comparison_missing"]) == {"chg", "day_ret"}
    assert "required baseline snapshot missing" in result["comparison_missing"]["chg"]
    assert "2026-09-21T16:00:00-04:00" in result["comparison_missing"]["chg"]
    assert "baseline" not in result["source"]
    pd.testing.assert_frame_equal(frame, untouched)


def test_missing_us_calendar_does_not_guess_comparison_dates():
    result = aligned_macro({}, DAY, NOW, scenario_frames={"CL=F": bars({"2026-10-19": 70, DAY: 72})})
    assert result[NAMES["CL=F"]]["day_ret"] is None
    assert result[NAMES["CL=F"]]["chg"] is None
    assert "baseline session date unverified" in result[NAMES["CL=F"]]["comparison_missing"]["chg"]


@pytest.mark.parametrize("value,contribution", [(72, 0), (110, 18)])
def test_missing_month_keeps_level_warning_and_flags_incomplete_not_relief(value, contribution):
    from stock_lab_core.report_evidence import macro_components

    history = us_history()
    frames = {symbol: history for symbol in MACRO_SYMBOLS.values()}
    frames["^GSPC"] = history
    result = aligned_macro(frames, DAY, NOW, scenario_frames={
        "CL=F": bars({"2026-10-19": value - 1, DAY: value}), "USDKRW=X": bars({DAY: 1400}),
    })
    assert set(result) == set(MACRO_SYMBOLS)
    oil = result[NAMES["CL=F"]]
    assert oil["val"] == value and oil["day_ret"] is not None
    assert oil["chg"] is None and oil["chg_source"] == oil["base_date"] == ""
    assert oil["stress_incomplete"] is True
    assert set(oil["comparison_missing"]) == {"chg"}
    assert oil["day_ret_source"] and oil["source"]
    component = next(row for row in macro_components(result) if row["name"] == NAMES["CL=F"])
    assert component["change"] is None
    assert component["contribution"] == contribution


def test_verified_month_and_missing_day_have_independent_coverage():
    history = us_history()
    base = history.index[-22].date().isoformat()
    result = aligned_macro({"^GSPC": history}, DAY, NOW,
                           scenario_frames={"CL=F": bars({base: 60, DAY: 72})})[NAMES["CL=F"]]
    assert result["chg"] == pytest.approx(20)
    assert result["stress_incomplete"] is False
    assert set(result["comparison_missing"]) == {"day_ret"}
    assert result["chg_source"] and result["day_ret_source"] == ""
    assert result["previous_date"] == result["previous_as_of_at"] == ""


def test_xle_uses_frozen_macro_return_not_unrelated_cl_daily_observation():
    from stock_lab_core.report_analysis import sector_evidence

    frames = {"^GSPC": us_history(), "CL=F": daily({"2026-10-19": 100, DAY: 1})}
    macro = aligned_macro(frames, DAY, NOW, scenario_frames={"CL=F": bars({"2026-10-19": 70, DAY: 72})})
    row = {"Ticker": "XLE", "date": DAY, "1D": .01}
    observations = {"CL=F": {"date": DAY, "return": -.99}}
    first = sector_evidence(row, macro, [], observations=observations)
    revised = aligned_macro(frames, DAY, NOW,
                            scenario_frames={"CL=F": bars({"2026-10-19": 100, DAY: 50})})
    again = sector_evidence(row, revised, [], observations=observations)
    assert "WTI +2.86%" in first["reading"]
    assert again["reading"] == first["reading"]
    missing_day = dict(macro[NAMES["CL=F"]], day_ret=None)
    assert "WTI" not in sector_evidence(row, {NAMES["CL=F"]: missing_day}, [], observations=observations)["reading"]


def test_cache_directories_are_isolated(tmp_path):
    one = reference.snapshot_at_us_close(bars({DAY: 72}), "CL=F", DAY, NOW, cache_dir=tmp_path / "one")
    two = reference.snapshot_at_us_close(bars({DAY: 73}), "CL=F", DAY, NOW, cache_dir=tmp_path / "two")
    assert (one["val"], two["val"]) == (72, 73)


@pytest.mark.parametrize("fault", ["corrupt", "oversized", "wrong_anchor", "wrong_source"])
def test_bad_cache_never_gets_replaced_by_changed_raw_data(fault):
    reference.snapshot_at_us_close(bars({DAY: 72}), "CL=F", DAY, NOW)
    path = next(reference.DEFAULT_CACHE_DIR.glob("*.json"))
    content = path.read_text(encoding="utf-8")
    if fault == "corrupt":
        content = "not json"
    elif fault == "oversized":
        content = " " * (reference.MAX_RECORD_BYTES + 1)
    else:
        payload = json.loads(content)
        payload["as_of_at" if fault == "wrong_anchor" else "source"] = "unverified"
        content = json.dumps(payload)
    path.write_text(content, encoding="utf-8")
    assert reference.snapshot_at_us_close(bars({DAY: 99}), "CL=F", DAY, NOW) == {}
    assert path.read_text(encoding="utf-8") == content


def test_storage_failure_omits_reference_and_cleans_temporary_file(monkeypatch):
    def unavailable(*args):
        raise OSError("unavailable")
    monkeypatch.setattr(reference.os, "link", unavailable)
    assert reference.snapshot_at_us_close(bars({DAY: 72}), "CL=F", DAY, NOW) == {}
    assert list(reference.DEFAULT_CACHE_DIR.iterdir()) == []


def test_parallel_writers_return_one_immutable_snapshot(monkeypatch):
    barrier, publish = Barrier(4), reference.os.link

    def racing_publish(*args):
        barrier.wait(timeout=10)
        return publish(*args)

    monkeypatch.setattr(reference.os, "link", racing_publish)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda value: reference.snapshot_at_us_close(bars({DAY: value}), "CL=F", DAY, NOW),
                             [70, 71, 72, 73]))
    assert rows[0]["val"] in (70, 71, 72, 73)
    assert all(row == rows[0] for row in rows)
    assert len(list(reference.DEFAULT_CACHE_DIR.iterdir())) == 1


def test_cache_retention_is_bounded_and_does_not_touch_unrelated_files(monkeypatch):
    monkeypatch.setattr(reference, "MAX_SNAPSHOTS", 4)
    reference.DEFAULT_CACHE_DIR.mkdir()
    unrelated = reference.DEFAULT_CACHE_DIR / "other.json"
    unrelated.write_text("keep", encoding="utf-8")
    for day in pd.date_range("2026-10-10", periods=10).strftime("%Y-%m-%d"):
        assert reference.snapshot_at_us_close(bars({day: 72}), "CL=F", day, NOW)
    paths = sorted(reference.DEFAULT_CACHE_DIR.glob("*-wti.json"))
    assert len(paths) == 4
    assert paths[0].name.startswith("2026-10-16")
    assert unrelated.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("symbol,day", [("../../secret", DAY), ("CL=F", "../../secret"), ("CL=F", "20261020")])
def test_snapshot_path_is_not_controlled_by_unvalidated_input(symbol, day):
    assert reference.snapshot_at_us_close(bars({DAY: 72}), symbol, day, NOW) == {}
    assert not reference.DEFAULT_CACHE_DIR.exists()
