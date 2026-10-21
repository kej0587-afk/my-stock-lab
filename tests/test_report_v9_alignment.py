from copy import deepcopy
from datetime import datetime
import urllib.error
import ast
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core.report_holdings import completed_scenario_comparison, cumulative_holding_comparison
from stock_lab_core.report_history import update_report_history
from stock_lab_core.performance import (
    PerformanceTrace, archive_queue_measurement, matching_report_measurement, measure, queue_measurement_details,
    bind_summary_measurement, summary_measurement_reference,
)

NOW = datetime.fromisoformat("2026-10-20T22:00:00+09:00")
DATES = {"KR": "2026-10-20", "US": "2026-10-19"}


def cumulative_case():
    def frame(days, values):
        return pd.DataFrame({"Close": values}, index=pd.to_datetime(days))

    frames = {
        "379810.KS": frame(["2026-10-16", "2026-10-19", "2026-10-20"], [100, 98.81, 98.81 * .9927]),
        "418660.KS": frame(["2026-10-16", "2026-10-19", "2026-10-20"], [100, 97.46, 97.46 * .985]),
        "QQQ": frame(["2026-10-15", "2026-10-16", "2026-10-19"], [100, 97.5, 97.5 * 1.0121]),
    }
    observations = {
        "379810.KS": {"date": DATES["KR"], "previous_date": "2026-10-19", "return": -.0073},
        "418660.KS": {"date": DATES["KR"], "previous_date": "2026-10-19", "return": -.015},
        "QQQ": {"date": DATES["US"], "previous_date": "2026-10-16", "return": .0121},
    }
    return frames, observations


def aligned_frames():
    index = pd.to_datetime(["2026-10-19T15:25:00+09:00", "2026-10-20T15:25:00+09:00"])
    return {"NQ=F": pd.DataFrame({"Close": [100, 101.21]}, index=index),
            "USDKRW=X": pd.DataFrame({"Close": [1300, 1313]}, index=index)}


def test_same_kr_close_timestamps_replace_asynchronous_us_daily_residual():
    frames, obs = cumulative_case()
    before = {key: value.copy(deep=True) for key, value in frames.items()}
    row = {"티커": "379810.KS"}
    actual = cumulative_holding_comparison(row, obs, DATES, NOW, frames, scenario_frames=aligned_frames())
    assert actual["anchor"] == "2026-10-19"
    assert actual["actual"] == pytest.approx(-.0073)
    assert actual["reference"] == pytest.approx(.0121)
    assert actual["residual_pp"] == pytest.approx(-1.94)
    assert actual["fx_return"] == pytest.approx(.01)
    line = completed_scenario_comparison(row, obs, DATES, NOW, price_frames=frames, scenario_frames=aligned_frames())
    assert "실제 -0.73%" in line and "NQ=F +1.21%" in line and "차이 -1.94%p" in line
    assert "2026-10-19 15:30 KST" in line and "2026-10-20 15:30 KST" in line
    assert "2026-10-15" not in line
    for key in frames:
        pd.testing.assert_frame_equal(frames[key], before[key])


def test_leverage_does_not_pretend_raw_futures_match_daily_reset_product():
    frames, obs = cumulative_case()
    result = cumulative_holding_comparison({"티커": "418660.KS"}, obs, DATES, NOW, frames, scenario_frames=aligned_frames())
    assert result["reference"] == pytest.approx(.0121)
    assert result["residual_pp"] is None
    line = completed_scenario_comparison({"티커": "418660.KS"}, obs, DATES, NOW, price_frames=frames, scenario_frames=aligned_frames())
    assert "배수 잔차 산출 보류" in line and "2배" not in line


def test_missing_exact_future_anchor_is_not_filled_with_us_daily_close():
    frames, obs = cumulative_case()
    scenario = aligned_frames()
    scenario["NQ=F"] = scenario["NQ=F"].iloc[1:]
    result = cumulative_holding_comparison({"티커": "418660.KS"}, obs, DATES, NOW, frames, scenario_frames=scenario)
    assert result.get("error") and "reference" not in result


def test_korean_holiday_uses_real_kr_close_with_same_time_future_anchor():
    frames = {"379810.KS": pd.DataFrame({"Close": [100, 99, 98]}, index=pd.to_datetime(["2026-10-08", "2026-10-12", "2026-10-13"]))}
    observations = {"379810.KS": {"date": "2026-10-13"}}
    scenario = {"NQ=F": pd.DataFrame({"Close": [100, 103]},
                 index=pd.to_datetime(["2026-10-12T15:25:00+09:00", "2026-10-13T15:25:00+09:00"]))}
    result = cumulative_holding_comparison({"티커": "379810.KS"}, observations,
        {"KR": "2026-10-13", "US": "2026-10-12"}, NOW.replace(day=13), frames, scenario_frames=scenario)
    assert result["anchor"] == "2026-10-12"
    assert result["actual"] == pytest.approx(98 / 99 - 1) and result["reference"] == pytest.approx(.03)


@pytest.mark.parametrize("problem", ["no_frames", "missing_anchor", "wrong_session", "invalid_price"])
def test_cumulative_comparison_never_fabricates_an_anchor_or_one_day_error(problem):
    frames, obs = cumulative_case()
    if problem == "no_frames":
        frames = {}
    elif problem == "missing_anchor":
        frames["QQQ"] = frames["QQQ"].iloc[1:]
    elif problem == "wrong_session":
        obs["QQQ"]["date"] = "2026-10-16"
    else:
        frames["QQQ"].iloc[0, 0] = 0
    line = completed_scenario_comparison({"티커": "379810.KS"}, obs, DATES, NOW, price_frames=frames)
    assert "누적 비교 보류" in line
    assert "-1.93%p" not in line and "시나리오 vs" not in line


def test_previous_names_repair_owner_bound_history_and_preserve_custom_names(tmp_path):
    old = {"KR": "2026-10-19", "US": "2026-10-16"}
    tickers = ["003160.KS", "003670.KS", "028300.KQ", "096530.KQ", "192820.KS"]
    rows = [{"티커": ticker, "최종읽기": "대기"} for ticker in tickers]
    before = deepcopy(rows)
    path = tmp_path / "history.json"
    update_report_history(rows, old, path=path, owner_scope="alice")
    result = update_report_history([{**rows[0], "종목명": "내 표시명"}], DATES, path=path, owner_scope="alice")
    assert [row["종목명"] for row in result["previous_summary"]] == ["디아이", "포스코퓨처엠", "HLB", "씨젠", "코스맥스"]
    again = update_report_history(rows[:1], DATES, path=path, owner_scope="alice")
    assert again["previous_run_summary"][0]["종목명"] == "내 표시명"
    assert not update_report_history(rows, DATES, path=path, owner_scope="bob")["previous_summary"]
    assert rows == before


def test_calculation_archive_survives_rerender_and_report_matches_exact_identity():
    state = {}
    with PerformanceTrace() as full:
        with measure("phase", "summary"):
            pass
    archive_queue_measurement(state, full.report())
    identity = full.report()["measurement_id"]
    state["today_market_report_measurement_id"] = identity
    for _ in range(12):
        with PerformanceTrace() as render:
            pass
        archive_queue_measurement(state, render.report())
    assert len(state["today_queue_measurements"]) == 8
    match = matching_report_measurement(state, "빌드: 점검 측정ID " + identity)
    assert match["measurement_id"] == identity and match["is_full_today_queue_measurement"]
    assert match["measurement_kind"] == "calculation"
    assert not matching_report_measurement(state, "점검 측정ID " + "f" * 32)
    assert queue_measurement_details(render.report())["measurement_kind"] == "render_only"


def test_interrupted_render_keeps_completed_calculation_but_not_full_render_label():
    class RerunException(Exception):
        pass

    state = {}
    with pytest.raises(RerunException):
        with PerformanceTrace() as trace:
            with measure("phase", "summary"):
                pass
            raise RerunException()
    archive_queue_measurement(state, trace.report())
    assert state["today_queue_performance"]["calculation_completed"]
    assert not state["today_queue_performance"]["is_full_today_queue_measurement"]
    assert state["today_queue_performance"]["measurement_status"] == "interrupted"


def test_late_pinning_recovers_last_calculation_before_a_new_calculation_replaces_it():
    state = {}
    with PerformanceTrace() as old:
        with measure("phase", "summary"):
            pass
    archive_queue_measurement(state, old.report())
    for _ in range(10):
        with PerformanceTrace() as render:
            pass
        archive_queue_measurement(state, render.report())
    old_id = old.report()["measurement_id"]
    assert old_id not in state["today_queue_measurements"]
    state["today_market_report_measurement_id"] = old_id
    with PerformanceTrace() as new:
        with measure("phase", "summary"):
            pass
    archive_queue_measurement(state, new.report())
    assert matching_report_measurement(state, "점검 측정ID " + old_id)["measurement_id"] == old_id


def test_new_calculation_never_relabels_an_older_unreplaced_dataframe():
    state = {}
    with PerformanceTrace() as old:
        with measure("phase", "summary"):
            summary = pd.DataFrame({"티커": ["AAPL"]})
        bind_summary_measurement(summary)
    archive_queue_measurement(state, old.report())
    with PerformanceTrace() as unused:
        with measure("phase", "summary"):
            pass
    archive_queue_measurement(state, unused.report())
    assert state["today_queue_performance"]["measurement_id"] == unused.measurement_id
    assert summary_measurement_reference(summary.copy())["measurement_id"] == old.measurement_id
    assert not summary_measurement_reference(pd.DataFrame({"티커": ["AAPL"]}))


def test_transport_timeouts_are_counted_separately_from_batch_wait(monkeypatch):
    from stock_lab_core import prices

    def request(*args, **kwargs):
        raise urllib.error.URLError(TimeoutError("controlled timeout"))

    monkeypatch.setattr(prices.urllib.request, "urlopen", request)
    with PerformanceTrace() as trace:
        assert prices._fetch_naver_realtime_quote.__wrapped__("005930.KS") == {}
        assert prices._fetch_naver_basic_quote.__wrapped__("005930.KS") == {}
    assert trace.report()["transport_events"] == {"naver_realtime.request": 1, "naver_realtime.timeout": 1,
                                                 "naver_basic.request": 1, "naver_basic.timeout": 1}


def test_report_download_exposes_its_matching_measurement_without_account_loading():
    from streamlit.testing.v1 import AppTest

    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "render_today_market_memo_panel")
    block = next(node for node in function.body if isinstance(node, ast.If) and
                 isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Constant)
                 and node.test.left.value == "## 기준일")
    source = '''
import streamlit as st
import json
identity = "a" * 32
saved_report = "## 기준일\\n빌드: 점검 측정ID " + identity
st.session_state["today_queue_measurements"] = {identity: {
    "measurement_id": identity, "measurement_status": "completed",
    "functions": [{"category": "phase", "name": "summary", "failures": 0}]}}
''' + ast.unparse(block)
    app = AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert [item.label for item in app.get("download_button")] == ["리포트 다운로드", "이 리포트와 같은 측정ID JSON"]
