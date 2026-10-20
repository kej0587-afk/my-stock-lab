"""Opt-in, per-run timings with separate wall and concurrent work totals."""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from threading import Lock, get_ident
from time import perf_counter
from datetime import datetime, timezone
from uuid import uuid4
import logging


_trace = ContextVar("stock_lab_performance_trace", default=None)
_span = ContextVar("stock_lab_performance_span", default=None)


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
        self.elapsed_seconds = 0.0
        self.status = "not_started"
        self.on_phase = on_phase
        self.current_phase = ""

    def __enter__(self):
        self.measurement_id = uuid4().hex
        self.measurement_started_at = datetime.now(timezone.utc).isoformat()
        self.measurement_finished_at = None
        self._started = self.clock()
        self._owner_thread = get_ident()
        self.status = "running"
        self._token = _trace.set(self)
        self._span_token = _span.set(None)
        return self

    def __exit__(self, *exc):
        self.elapsed_seconds = max(0.0, self.clock() - self._started)
        self.measurement_finished_at = datetime.now(timezone.utc).isoformat()
        self.status = "completed" if not exc or exc[0] is None else "interrupted" if exc[0].__name__ in {"RerunException", "StopException"} else "failed"
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

    def record(self, category, name, elapsed, children, failed, *, started, ended, child_intervals):
        exclusive = _exclusive_intervals(started, ended, child_intervals)
        with self._lock:
            entry = self._entries.setdefault((category, name), {
                "category": category, "name": name, "calls": 0,
                "total_seconds": 0.0, "self_seconds": 0.0,
                "max_seconds": 0.0, "failures": 0,
            })
            entry["calls"] += 1
            entry["total_seconds"] += elapsed
            entry["self_seconds"] += max(0.0, elapsed - children)
            entry["max_seconds"] = max(entry["max_seconds"], elapsed)
            entry["failures"] += int(failed)
            self._function_intervals.setdefault((category, name), []).append((started, ended))
            if category != "phase":
                self._category_intervals.setdefault(category, []).extend(exclusive)

    def report(self):
        with self._lock:
            entries = [dict(entry) for entry in self._entries.values()]
            function_intervals = {key: list(value) for key, value in self._function_intervals.items()}
            category_intervals = {key: list(value) for key, value in self._category_intervals.items()}
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
            "current_phase": self.current_phase,
            "categories_work_seconds": categories,
            "functions": entries,
            "work_totals_are_concurrent": True,
            "timing_schema_version": 2,
            "categories_active_wall_seconds": {key: _interval_seconds(value) for key, value in category_intervals.items()},
            "measured_active_wall_seconds": active_wall,
            "concurrent_overlap_work_seconds": max(0.0, sum(categories.values()) - active_wall),
            "active_wall_categories_can_overlap": True,
        }


def queue_measurement_reference(previous=None):
    trace = _trace.get()
    if trace is not None:
        with trace._lock:
            calculated = ("phase", "summary") in trace._entries
        if calculated:
            return {key: value for key, value in trace.report().items()
                    if key.startswith("measurement_")}
    return {key: value for key, value in (previous or {}).items()
            if key.startswith("measurement_")}


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
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        ended = trace.clock()
        elapsed = max(0.0, ended - started)
        _span.reset(token)
        if parent is not None:
            parent["children"] += elapsed
            parent["intervals"].append((started, ended))
        trace.record(category, name, elapsed, current["children"], failed,
                     started=started, ended=ended, child_intervals=current["intervals"])


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
