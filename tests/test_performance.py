from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar

import pytest

from stock_lab_core.performance import PerformanceTrace, measure, submit_with_context, timed_call


def test_nested_timings_do_not_double_count_categories():
    now = [0.0]
    with PerformanceTrace(clock=lambda: now[0]) as trace:
        with measure("decision", "outer"):
            now[0] = 1
            with measure("prices", "inner"):
                now[0] = 3
            now[0] = 4
    report = trace.report()
    assert report["elapsed_seconds"] == 4
    assert report["categories_work_seconds"] == {"decision": 2, "prices": 2}
    assert report["functions"][0]["total_seconds"] == 4
    assert report["categories_active_wall_seconds"] == {"decision": 2, "prices": 2}
    assert report["measured_active_wall_seconds"] == 4
    assert report["concurrent_overlap_work_seconds"] == 0


def test_parallel_intervals_separate_work_sum_from_wall_union():
    trace = PerformanceTrace(clock=lambda: 0)
    trace.record("prices", "fetch", 4, 0, False, started=0, ended=4, child_intervals=[])
    trace.record("prices", "fetch", 4, 0, False, started=1, ended=5, child_intervals=[])
    trace.record("indicators", "calculate", 2, 0, False, started=3, ended=5, child_intervals=[])
    report = trace.report()
    assert report["categories_work_seconds"] == {"prices": 8, "indicators": 2}
    assert report["categories_active_wall_seconds"] == {"prices": 5, "indicators": 2}
    assert report["measured_active_wall_seconds"] == 5
    assert report["concurrent_overlap_work_seconds"] == 5
    assert next(row for row in report["functions"] if row["name"] == "fetch")["active_wall_seconds"] == 5


def test_decorator_preserves_clear_unwrapped_output_and_exceptions():
    def original(value):
        if value < 0:
            raise ValueError("negative")
        return value + 1
    original.clear = lambda: True
    wrapped = timed_call("indicators")(original)
    assert wrapped(2) == 3
    assert wrapped.clear() is True
    assert wrapped.__wrapped__ is original
    with PerformanceTrace() as trace:
        with pytest.raises(ValueError):
            wrapped(-1)
    assert trace.report()["functions"][0]["failures"] == 1
    wrapped(3)
    assert trace.report()["functions"][0]["calls"] == 1


def test_workers_inherit_run_context_but_do_not_share_parent_spans():
    value = ContextVar("test_context", default="missing")
    token = value.set("run")
    try:
        with PerformanceTrace() as trace:
            with measure("phase", "workers"), ThreadPoolExecutor(max_workers=3) as executor:
                @timed_call("prices", "fetch")
                def fetch():
                    return value.get()
                futures = [submit_with_context(executor, fetch) for _ in range(12)]
                assert [future.result() for future in futures] == ["run"] * 12
        report = trace.report()
        assert next(row for row in report["functions"] if row["name"] == "fetch")["calls"] == 12
        assert report["work_totals_are_concurrent"] is True
        assert all(row["self_seconds"] >= 0 for row in report["functions"])
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(value.get).result() == "missing"
    finally:
        value.reset(token)


def test_nested_runs_are_isolated():
    with PerformanceTrace() as outer:
        with measure("prices", "outer"):
            with PerformanceTrace() as inner:
                with measure("prices", "inner"):
                    pass
    assert [row["name"] for row in outer.report()["functions"]] == ["outer"]
    assert [row["name"] for row in inner.report()["functions"]] == ["inner"]


def test_running_phase_snapshot_is_available_before_blocking_work_finishes():
    now = [0.0]
    progress = []
    with PerformanceTrace(clock=lambda: now[0], on_phase=lambda name, elapsed: progress.append((name, elapsed))) as trace:
        now[0] = 2
        with measure("phase", "price_history_10y"):
            now[0] = 8
            snapshot = trace.report()
            assert snapshot["measurement_status"] == "running"
            assert snapshot["elapsed_seconds"] == 8
            assert snapshot["current_phase"] == "price_history_10y"
            assert snapshot["measurement_finished_at"] is None
    assert progress == [("price_history_10y", 2)]
    assert trace.report()["measurement_status"] == "completed"


def test_failed_run_records_time_and_does_not_swallow_original_error():
    with pytest.raises(ValueError, match="source failed"):
        with PerformanceTrace() as trace:
            with measure("phase", "summary"):
                raise ValueError("source failed")
    report = trace.report()
    assert report["measurement_status"] == "failed"
    assert report["functions"][0]["failures"] == 1
    assert report["measurement_finished_at"]


def test_phase_notifications_stay_on_script_thread_and_observer_failures_do_not_change_results():
    from threading import get_ident
    calls = []
    with PerformanceTrace(on_phase=lambda *a: calls.append(get_ident())):
        with ThreadPoolExecutor(max_workers=1) as pool:
            def worker():
                with measure("phase", "worker_phase"):
                    return 42
            assert submit_with_context(pool, worker).result() == 42
        with measure("phase", "main_phase"):
            pass
    assert calls == [get_ident()]
    with PerformanceTrace(on_phase=lambda *a: (_ for _ in ()).throw(RuntimeError("UI failed"))):
        with measure("phase", "data"):
            assert 2 + 2 == 4


def test_timing_panel_renders_and_retains_last_calculation(app_module):
    from streamlit.testing.v1 import AppTest
    source = '''
import app
import streamlit as st
from stock_lab_core.performance import measure
original = app._render_today_queue_tab
def render_stub(mode):
    if not st.session_state.get("reuse", False):
        with measure("phase", "summary"):
            with measure("prices", "probe"):
                pass
try:
    app._render_today_queue_tab = render_stub
    app.render_today_queue_tab("test")
finally:
    app._render_today_queue_tab = original
'''
    app = AppTest.from_string(source, default_timeout=30).run()
    assert not app.exception
    report = app.session_state["today_queue_performance"]
    assert report["functions"]
    assert len(app.metric) == 3
    assert len(app.dataframe) == 3
    app.session_state["reuse"] = True
    app.run()
    assert not app.exception
    assert app.session_state["today_queue_performance"] == report
