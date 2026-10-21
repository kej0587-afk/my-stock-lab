"""Opt-in, per-run timings with separate wall and concurrent work totals."""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from threading import Lock, get_ident
from time import perf_counter
from datetime import datetime, timezone
from uuid import uuid4
import logging
import re


_trace = ContextVar("stock_lab_performance_trace", default=None)
_span = ContextVar("stock_lab_performance_span", default=None)


def _exception_details(exc):
    """Retain types and safe message summaries, never exception payloads/URLs.

    Arbitrary messages can contain unlabeled tokens, headers or widget state;
    regex replacement alone cannot make them safe. Only fixed summaries leave
    this function, with an optional recognized HTTP status number.
    """
    classes = type(exc).__mro__
    streamlit_control = any(
        cls.__name__ in {"RerunException", "StopException"}
        or (cls.__name__ == "ScriptControlException"
            and cls.__module__.startswith("streamlit.runtime.scriptrunner"))
        for cls in classes
    )
    control = streamlit_control or isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit))
    if streamlit_control:
        message = "Streamlit script control flow (payload omitted)"
    elif control:
        message = "Interpreter control flow (payload omitted)"
    else:
        message = "Exception message redacted (untrusted payload)"
        # Do not call arbitrary __str__/__repr__ or inspect response/state objects.
        args = BaseException.args.__get__(exc)
        text = " ".join(arg[:4096] for arg in args[:4] if type(arg) is str).lower()
        names = {cls.__name__ for cls in classes}
        status = re.search(r"\b([45]\d{2})\s+(?:client|server)\s+error\b", text)
        if status:
            message = f"HTTP {status[1]} response (details redacted)"
        elif names & {"Timeout", "TimeoutError", "ReadTimeout", "ConnectTimeout", "ReadTimeoutError"} or "timed out" in text:
            message = "Operation timed out (details redacted)"
        elif names & {"ConnectionError", "ConnectionRefusedError", "NewConnectionError"}:
            message = "Connection failed (details redacted)"
        elif isinstance(exc, KeyError):
            message = "Missing key (key redacted)"
    return {
        "exception_type": f"{type(exc).__module__}.{type(exc).__name__}",
        "exception_kind": "control_flow" if control else "error",
        "message": message,
        "message_redacted": True,
    }


def _merged_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _exclusive_intervals(start, end, children):
    cursor = start
    result = []
    for left, right in _merged_intervals(children):
        left, right = max(start, left), min(end, right)
        if left > cursor:
            result.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        result.append((cursor, end))
    return result


def _interval_seconds(intervals):
    return sum(end - start for start, end in _merged_intervals(intervals))


class PerformanceTrace:
    def __init__(self, *, clock=perf_counter, scope="instrumented_run", on_phase=None):
        self.clock = clock
        self.scope = scope
        self.measurement_id = None
        self.measurement_started_at = None
        self.measurement_finished_at = None
        self._lock = Lock()
        self._entries = {}
        self._function_intervals = {}
        self._category_intervals = {}
        self._events = {}
        self.elapsed_seconds = 0.0
        self.status = "not_started"
        self.on_phase = on_phase
        self.current_phase = ""
        self.termination_exception = None

    def __enter__(self):
        self.measurement_id = uuid4().hex
        self.measurement_started_at = datetime.now(timezone.utc).isoformat()
        self.measurement_finished_at = None
        self.termination_exception = None
        self._started = self.clock()
        self._owner_thread = get_ident()
        self.status = "running"
        self._token = _trace.set(self)
        self._span_token = _span.set(None)
        return self

    def __exit__(self, *exc):
        self.elapsed_seconds = max(0.0, self.clock() - self._started)
        self.measurement_finished_at = datetime.now(timezone.utc).isoformat()
        self.termination_exception = _exception_details(exc[1]) if len(exc) > 1 and exc[1] is not None else None
        self.status = ("completed" if self.termination_exception is None else
                       "interrupted" if self.termination_exception["exception_kind"] == "control_flow" else "failed")
        _span.reset(self._span_token)
        _trace.reset(self._token)

    def phase_started(self, name):
        # Streamlit output must remain on the script thread, never a price worker.
        if get_ident() != self._owner_thread:
            return
        self.current_phase = name
        if self.on_phase is not None:
            try:
                self.on_phase(name, max(0.0, self.clock() - self._started))
            except Exception as exc:
                self.on_phase = None
                logging.warning("Performance progress display disabled (%s)", type(exc).__name__)

    def record(self, category, name, elapsed, children, failed, *, started, ended, child_intervals, exception=None):
        exclusive = _exclusive_intervals(started, ended, child_intervals)
        with self._lock:
            entry = self._entries.setdefault((category, name), {
                "category": category, "name": name, "calls": 0,
                "total_seconds": 0.0, "self_seconds": 0.0,
                "max_seconds": 0.0, "failures": 0,
                "errors": 0, "control_flow_exits": 0, "unclassified_exceptions": 0,
                "exceptions": [], "exceptions_omitted": 0,
            })
            entry["calls"] += 1
            entry["total_seconds"] += elapsed
            entry["self_seconds"] += max(0.0, elapsed - children)
            entry["max_seconds"] = max(entry["max_seconds"], elapsed)
            entry["failures"] += int(failed)
            if failed:
                counter = ("unclassified_exceptions" if exception is None else
                           "control_flow_exits" if exception["exception_kind"] == "control_flow" else "errors")
                entry[counter] += 1
                if exception is not None:
                    match = next((row for row in entry["exceptions"]
                                  if all(row.get(key) == value for key, value in exception.items())), None)
                    if match is not None:
                        match["count"] += 1
                    elif len(entry["exceptions"]) < 8:
                        entry["exceptions"].append(dict(exception, count=1))
                    else:
                        entry["exceptions_omitted"] += 1
            self._function_intervals.setdefault((category, name), []).append((started, ended))
            if category != "phase":
                self._category_intervals.setdefault(category, []).extend(exclusive)

    def count_event(self, name, count=1):
        with self._lock:
            self._events[name] = self._events.get(name, 0) + count

    def report(self):
        with self._lock:
            entries = [dict(entry, exceptions=[dict(row) for row in entry["exceptions"]])
                       for entry in self._entries.values()]
            function_intervals = {key: list(value) for key, value in self._function_intervals.items()}
            category_intervals = {key: list(value) for key, value in self._category_intervals.items()}
            events = dict(self._events)
        for entry in entries:
            entry["active_wall_seconds"] = _interval_seconds(function_intervals[(entry["category"], entry["name"])])
        entries.sort(key=lambda entry: entry["total_seconds"], reverse=True)
        categories = {}
        for entry in entries:
            if entry["category"] != "phase":
                categories[entry["category"]] = categories.get(entry["category"], 0.0) + entry["self_seconds"]
        active_wall = _interval_seconds([interval for values in category_intervals.values() for interval in values])
        return {
            "measurement_id": self.measurement_id,
            "measurement_started_at": self.measurement_started_at,
            "measurement_finished_at": self.measurement_finished_at,
            "measurement_scope": self.scope,
            "measurement_reused": False,
            "elapsed_seconds": max(0.0, self.clock() - self._started) if self.status == "running" else self.elapsed_seconds,
            "measurement_status": self.status,
            "termination_exception": dict(self.termination_exception) if self.termination_exception else None,
            "exception_schema_version": 1,
            "failure_count_includes_control_flow": True,
            "current_phase": self.current_phase,
            "transport_events": events,
            "categories_work_seconds": categories,
            "functions": entries,
            "work_totals_are_concurrent": True,
            "timing_schema_version": 2,
            "categories_active_wall_seconds": {key: _interval_seconds(value) for key, value in category_intervals.items()},
            "measured_active_wall_seconds": active_wall,
            "concurrent_overlap_work_seconds": max(0.0, sum(categories.values()) - active_wall),
            "active_wall_categories_can_overlap": True,
        }


def count_event(name, count=1):
    trace = _trace.get()
    if trace is not None:
        trace.count_event(name, count)


def queue_measurement_details(report):
    summary = next((row for row in report.get("functions", ())
                    if row.get("category") == "phase" and row.get("name") == "summary"), None)
    completed = bool(summary and not summary.get("failures"))
    return {"measurement_kind": "calculation" if summary else "render_only",
            "calculation_completed": completed,
            "is_full_today_queue_measurement": completed and report.get("measurement_status", "completed") == "completed"}


def archive_queue_measurement(state, report):
    """Keep the report's exact measurement even after an unrelated rerender."""
    identity = report.get("measurement_id")
    if not identity:
        return
    report = dict(report, **queue_measurement_details(report))
    history = dict(state.get("today_queue_measurements", {}))
    pinned = state.get("today_market_report_measurement_id")
    previous = state.get("today_queue_performance", {})
    if pinned and previous.get("measurement_id") == pinned:
        history.setdefault(pinned, previous)
    history[identity] = report
    removable = [key for key in history if key != pinned and key != identity]
    while len(history) > 8 and removable:
        history.pop(removable.pop(0))
    state["today_queue_measurements"] = history
    if report["calculation_completed"]:
        state["today_queue_performance"] = report


def matching_report_measurement(state, report_text):
    match = re.search(r"점검 측정ID\s+([0-9a-f]{32})\b", str(report_text or ""))
    if not match:
        return None
    identity = match[1]
    for candidate in (state.get("today_queue_measurements", {}).get(identity), state.get("today_queue_performance")):
        if isinstance(candidate, dict) and candidate.get("measurement_id") == identity:
            return dict(candidate, **queue_measurement_details(candidate))
    return None


def queue_measurement_reference(previous=None):
    trace = _trace.get()
    if trace is not None:
        with trace._lock:
            calculated = ("phase", "summary") in trace._entries
        if calculated:
            report = trace.report()
            return {key: value for key, value in dict(report, **queue_measurement_details(report)).items()
                    if key.startswith("measurement_")}
    return {key: value for key, value in (previous or {}).items()
            if key.startswith("measurement_")}


def bind_summary_measurement(summary):
    summary.attrs["queue_measurement"] = queue_measurement_reference()
    return summary


def summary_measurement_reference(summary):
    # The last completed trace may not belong to the currently displayed data
    # (for example, a rerun stopped before replacing the cached result).
    reference = getattr(summary, "attrs", {}).get("queue_measurement", {})
    return dict(reference) if isinstance(reference, dict) else {}


@contextmanager
def measure(category, name):
    trace = _trace.get()
    if trace is None:
        yield
        return
    if category == "phase":
        trace.phase_started(name)
    parent = _span.get()
    current = {"children": 0.0, "intervals": []}
    token = _span.set(current)
    started = trace.clock()
    failed = False
    exception = None
    try:
        yield
    except BaseException as exc:
        failed = True
        exception = _exception_details(exc)
        raise
    finally:
        ended = trace.clock()
        elapsed = max(0.0, ended - started)
        _span.reset(token)
        if parent is not None:
            parent["children"] += elapsed
            parent["intervals"].append((started, ended))
        trace.record(category, name, elapsed, current["children"], failed,
                     started=started, ended=ended, child_intervals=current["intervals"], exception=exception)


def timed_call(category, name=None):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if _trace.get() is None:
                return fn(*args, **kwargs)
            with measure(category, name or fn.__name__):
                return fn(*args, **kwargs)
        wrapped.__wrapped__ = getattr(fn, "__wrapped__", fn)
        if hasattr(fn, "clear"):
            wrapped.clear = fn.clear
        return wrapped
    return decorate


def submit_with_context(executor, fn, *args, **kwargs):
    """Carry run-local data into a worker, without sharing its parent span."""
    context = copy_context()

    def run():
        token = _span.set(None)
        try:
            return fn(*args, **kwargs)
        finally:
            _span.reset(token)

    return executor.submit(context.run, run)
