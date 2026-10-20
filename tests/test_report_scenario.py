from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.report_scenario import (
    build_scenario_context, interval_observation, latest_futures_line, scenario_observation_line,
)

NOW = datetime.fromisoformat("2026-10-20T17:03:00+09:00")
DATES = {"US": "2026-10-19", "KR": "2026-10-20"}


def frame():
    # US close 16:00 ET = 05:00 KST; completed bar times, not start times.
    return pd.DataFrame({"Close": [100, 98, 97, 500]},
        index=pd.to_datetime(["2026-10-20T04:55+09:00", "2026-10-20T15:25+09:00",
                              "2026-10-20T16:55+09:00", "2026-10-20T17:00+09:00"]))


def test_close_and_latest_observations_are_separate_and_future_bar_excluded():
    data = build_scenario_context({"NQ=F": frame()}, DATES, NOW)
    assert data["kr_close"]["NQ=F"]["return"] == pytest.approx(-.02)
    assert data["latest"]["NQ=F"]["return"] == pytest.approx(-.03)
    assert "NQ=F -3.00%" in latest_futures_line(data)
    assert "17:00 KST" in latest_futures_line(data)
    line = scenario_observation_line({"티커": "418660.KS"}, data)
    assert "NQ=F -2.00%" in line and "원/달러: 동일 시간대 자료 미수집" in line
    assert "NAV·iNAV 미연결" in line and "기여도 분해·합산은 아님" in line
    assert "동일 배수로 추정하지 않음" in line
    assert "-4.00%" not in line


def test_stale_endpoints_nan_and_naive_timezone_fail_closed():
    start = datetime.fromisoformat("2026-10-20T05:00+09:00")
    end = datetime.fromisoformat("2026-10-20T15:30+09:00")
    stale = frame().iloc[[0]]
    assert not interval_observation(stale, start, end)
    naive = frame().tz_localize(None)
    assert not interval_observation(naive, start, end)
    bad = frame()
    bad.iloc[1, 0] = float("nan")
    assert not interval_observation(bad, start, end)
    assert not interval_observation([], start, end)
    assert not interval_observation(frame(), end, start)


def test_no_kr_close_values_for_previous_session_or_before_close():
    assert not build_scenario_context({"NQ=F": frame()}, dict(DATES, KR="2026-10-19"), NOW)["kr_close"]
    assert not build_scenario_context({"NQ=F": frame()}, DATES, NOW.replace(hour=14))["kr_close"]
    assert not build_scenario_context({}, {}, NOW)
    assert "미수집" in latest_futures_line({})
    assert scenario_observation_line({"티커": "RAM"}, {}) == ""
