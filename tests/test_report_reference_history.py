import pandas as pd
import pytest
import requests
import yfinance as yf

from stock_lab_core import report_reference as reference
from stock_lab_core import yahoo_transport
from stock_lab_core.report_prices import MACRO_SYMBOLS, aligned_macro


DAY = "2026-03-09"
PREVIOUS = "2026-03-06"
BASE = "2026-02-05"
NOW = pd.Timestamp("2026-03-10T09:00:00+09:00")
NAMES = {symbol: name for name, symbol in MACRO_SYMBOLS.items()}


def bars(points):
    index, values = [], []
    for day, value in points.items():
        anchor = pd.Timestamp(day + " 16:00", tz="America/New_York")
        index.extend([anchor - 2 * reference.BAR, anchor - reference.BAR, anchor])
        values.extend([1, value, 9999])
    return pd.DataFrame({"Close": values}, index=pd.DatetimeIndex(index).tz_convert("UTC"))


def us_history():
    # Presidents' Day is absent; these are 22 actual US sessions, spanning DST.
    sessions = pd.bdate_range(BASE, DAY).difference(pd.to_datetime(["2026-02-16"]))
    assert len(sessions) == 22
    return pd.DataFrame({"Close": 100.}, index=sessions)


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch, tmp_path):
    def no_network(*args, **kwargs):
        pytest.fail("Network must be mocked")

    monkeypatch.setattr(reference, "DEFAULT_CACHE_DIR", tmp_path / "references")
    monkeypatch.setattr(yahoo_transport, "yahoo_session_kwargs", lambda: {})
    monkeypatch.setattr(yf, "download", no_network)
    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    reference._load_reference_window.clear()
    yield
    reference._load_reference_window.clear()


def test_short_live_frames_backfill_only_missing_21_session_anchors(monkeypatch):
    calls = []
    baseline = {"CL=F": 60., "USDKRW=X": 1400.}

    def download(tickers, **kwargs):
        calls.append((tickers, kwargs))
        return pd.concat({tickers[0]: bars({BASE: baseline[tickers[0]]})}, axis=1)

    monkeypatch.setattr(yf, "download", download)
    live = {"CL=F": bars({PREVIOUS: 70, DAY: 72}),
            "USDKRW=X": bars({PREVIOUS: 1420, DAY: 1440})}
    original = {ticker: frame.copy(deep=True) for ticker, frame in live.items()}
    history = us_history()
    frames = {"^GSPC": history, "CL=F": history * 99, "USDKRW=X": history * 200}
    macro = aligned_macro(frames, DAY, NOW, scenario_frames=live,
                          reference_loader=reference.load_macro_reference_frame)

    assert len(calls) == 2
    for (tickers, kwargs), symbol in zip(calls, reference.REFERENCE_SYMBOLS):
        assert tickers == [symbol]
        assert pd.Timestamp(kwargs["start"]) == pd.Timestamp(BASE + "T15:55:00-05:00")
        assert pd.Timestamp(kwargs["end"]) == pd.Timestamp(BASE + "T16:00:00-05:00")
        row = macro[NAMES[symbol]]
        assert row["base_date"] == BASE and row["previous_date"] == PREVIOUS
        assert row["base_as_of_at"] == BASE + "T16:00:00-05:00"
        assert row["as_of_at"] == DAY + "T16:00:00-04:00"
        assert row["stress_incomplete"] is False and row["comparison_missing"] == {}
        pd.testing.assert_frame_equal(live[symbol], original[symbol])
    assert macro[NAMES["CL=F"]]["chg"] == pytest.approx(20)
    assert macro[NAMES["CL=F"]]["day_ret"] == pytest.approx(72 / 70 - 1)
    assert macro[NAMES["USDKRW=X"]]["chg"] == pytest.approx((1440 / 1400 - 1) * 100)
    assert len(list(reference.DEFAULT_CACHE_DIR.glob("*.json"))) == 6

    # A rerun reuses all persisted endpoints even if current live prices change.
    changed = {ticker: frame * 2 for ticker, frame in live.items()}
    assert aligned_macro(frames, DAY, NOW, scenario_frames=changed,
                         reference_loader=reference.load_macro_reference_frame) == macro
    assert aligned_macro(frames, DAY, NOW, scenario_frames={}) == macro
    assert len(calls) == 2


def test_no_live_frame_fetches_one_bounded_window_longer_than_one_month(monkeypatch):
    calls = []
    raw = bars({BASE: 60, PREVIOUS: 70, DAY: 72, "2026-03-10": 99})

    def download(tickers, **kwargs):
        calls.append(kwargs)
        return pd.concat({tickers[0]: raw}, axis=1)

    monkeypatch.setattr(yf, "download", download)
    row = reference.macro_reference(None, "CL=F", DAY, NOW, previous_date=PREVIOUS, base_date=BASE,
                                    history_loader=reference.load_macro_reference_frame)
    assert len(calls) == 1
    kwargs = calls[0]
    start, end = pd.Timestamp(kwargs["start"]), pd.Timestamp(kwargs["end"])
    assert start == pd.Timestamp(BASE + "T15:55:00-05:00")
    assert end == pd.Timestamp(DAY + "T16:00:00-04:00")
    assert pd.Timedelta(days=31) < end - start < reference.HISTORY_RETENTION
    assert end <= NOW and start >= NOW - reference.HISTORY_RETENTION
    assert kwargs["interval"] == "5m" and kwargs["ignore_tz"] is False
    assert kwargs["threads"] is False and kwargs["timeout"] == 4
    assert "period" not in kwargs
    assert row["val"] == 72 and row["chg"] == pytest.approx(20)
    assert row["previous_date"] == PREVIOUS
    assert "not official settlement" in row["source"]
    assert {path.name[:10] for path in reference.DEFAULT_CACHE_DIR.glob("*.json")} == {BASE, PREVIOUS, DAY}


def test_history_cache_reuses_sorted_dates_and_retains_only_requested_endpoints(monkeypatch):
    calls = []

    def download(*args, **kwargs):
        calls.append(kwargs)
        return bars({BASE: 60, PREVIOUS: 70, DAY: 72})

    monkeypatch.setattr(yf, "download", download)
    first = reference.load_macro_reference_frame("CL=F", (DAY, BASE), NOW)
    again = reference.load_macro_reference_frame("CL=F", (BASE, DAY, BASE), NOW + pd.Timedelta(hours=1))
    pd.testing.assert_frame_equal(first, again)
    assert len(calls) == 1 and list(first.Close) == [60, 72]
    assert len(first) == 2 and first.attrs["interval"] == "5m"
    assert not reference.DEFAULT_CACHE_DIR.exists()


@pytest.mark.parametrize("symbol,dates,now", [
    ("AAPL", (DAY,), NOW),
    ("../../private", (DAY,), NOW),
    ("CL=F", ("20260309",), NOW),
    ("CL=F", ("../../private",), NOW),
    ("CL=F", (DAY,), NOW.tz_localize(None)),
    ("CL=F", (DAY,), pd.NaT),
    ("CL=F", ("2026-03-10",), NOW),
    ("CL=F", ("2026-01-01",), NOW),
    ("CL=F", (), NOW),
])
def test_unavailable_or_invalid_window_never_calls_provider(symbol, dates, now):
    assert reference.load_macro_reference_frame(symbol, dates, now).empty


def test_mixed_dates_query_only_completed_anchors_inside_provider_retention(monkeypatch):
    calls = []

    def download(*args, **kwargs):
        calls.append(kwargs)
        return bars({DAY: 72})

    monkeypatch.setattr(yf, "download", download)
    frame = reference.load_macro_reference_frame("CL=F", ("2026-01-01", DAY, "2026-03-10"), NOW)
    assert list(frame.Close) == [72]
    assert pd.Timestamp(calls[0]["start"]) == pd.Timestamp(DAY + "T15:55:00-04:00")
    assert pd.Timestamp(calls[0]["end"]) == pd.Timestamp(DAY + "T16:00:00-04:00")


@pytest.mark.parametrize("fault", ["missing", "daily", "naive", "duplicate", "interval", "invalid", "symbol", "empty", "exception"])
def test_bad_history_keeps_missing_comparison_and_cannot_replace_with_daily(monkeypatch, fault):
    frame = bars({BASE: 60})
    if fault == "missing":
        frame = frame.iloc[[0, 2]]
    elif fault == "daily":
        frame = pd.DataFrame({"Close": [60]}, index=pd.to_datetime([BASE], utc=True))
    elif fault == "naive":
        frame.index = frame.index.tz_localize(None)
    elif fault == "duplicate":
        frame = pd.concat([frame, frame.iloc[[1]]])
    elif fault == "interval":
        frame.attrs["interval"] = "1m"
    elif fault == "invalid":
        frame.iloc[1, 0] = float("nan")
    elif fault == "symbol":
        frame = pd.concat({"WRONG": frame}, axis=1)
    elif fault == "empty":
        frame = pd.DataFrame()

    calls = []

    def download(*args, **kwargs):
        calls.append(kwargs)
        if fault == "exception":
            raise yf.exceptions.YFRateLimitError()
        return frame

    monkeypatch.setattr(yf, "download", download)
    frames = {"^GSPC": us_history(), "CL=F": us_history()}
    kwargs = dict(scenario_frames={"CL=F": bars({PREVIOUS: 70, DAY: 72})},
                  reference_loader=reference.load_macro_reference_frame)
    row = aligned_macro(frames, DAY, NOW, **kwargs)[NAMES["CL=F"]]
    assert row["val"] == 72 and row["day_ret"] == pytest.approx(72 / 70 - 1)
    assert row["chg"] is None and row["stress_incomplete"] is True
    assert set(row["comparison_missing"]) == {"chg"}
    assert row["base_date"] == row["base_as_of_at"] == row["chg_source"] == ""
    assert len(list(reference.DEFAULT_CACHE_DIR.glob("*.json"))) == 2
    assert aligned_macro(frames, DAY, NOW, **kwargs)[NAMES["CL=F"]] == row
    assert len(calls) == 2  # One cold request per symbol; failures then cool down.


def test_missing_history_can_recover_without_replacing_existing_snapshots(monkeypatch):
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: pd.DataFrame())
    kwargs = dict(previous_date=PREVIOUS, base_date=BASE,
                  history_loader=reference.load_macro_reference_frame)
    live = bars({PREVIOUS: 70, DAY: 72})
    first = reference.macro_reference(live, "CL=F", DAY, NOW, **kwargs)
    assert first["chg"] is None
    assert not (reference.DEFAULT_CACHE_DIR / (BASE + "-wti.json")).exists()
    reference._load_reference_window.clear()
    monkeypatch.setattr(yf, "download", lambda *args, **kw: bars({BASE: 60, PREVIOUS: 100, DAY: 10}))
    recovered = reference.macro_reference(live * 3, "CL=F", DAY, NOW, **kwargs)
    assert recovered["val"] == 72 and recovered["chg"] == pytest.approx(20)
    assert recovered["day_ret"] == pytest.approx(72 / 70 - 1)


def test_unverified_session_dates_are_not_guessed_for_history_loader():
    calls = []

    def history_loader(symbol, dates, now):
        calls.append((symbol, dates))
        return bars({DAY: 72})

    row = aligned_macro({}, DAY, NOW, scenario_frames={"CL=F": bars({DAY: 72})},
                        reference_loader=history_loader)[NAMES["CL=F"]]
    assert calls == [("USDKRW=X", (DAY,))]
    assert row["chg"] is row["day_ret"] is None
    assert "baseline session date unverified" in row["comparison_missing"]["chg"]


def test_future_reference_does_not_trigger_backfill():
    def forbidden(*args):
        pytest.fail("An incomplete current anchor must not trigger history")

    assert reference.macro_reference(None, "CL=F", DAY, pd.Timestamp(DAY + "T19:59:59Z"),
                                     history_loader=forbidden) == {}
