"""Opt-in, per-run timings with separate wall and concurrent work totals."""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from threading import Lock
from time import perf_counter


_trace = ContextVar("stock_lab_performance_trace", default=None)
_span = ContextVar("stock_lab_performance_span", default=None)


class PerformanceTrace:
    def __init__(self, *, clock=perf_counter):
        self.clock = clock
        self._lock = Lock()
        self._entries = {}
        self.elapsed_seconds = 0.0

    def __enter__(self):
        self._started = self.clock()
        self._token = _trace.set(self)
        self._span_token = _span.set(None)
        return self

    def __exit__(self, *exc):
        self.elapsed_seconds = max(0.0, self.clock() - self._started)
        _span.reset(self._span_token)
        _trace.reset(self._token)

    def record(self, category, name, elapsed, children, failed):
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

    def report(self):
        with self._lock:
            entries = [dict(entry) for entry in self._entries.values()]
        entries.sort(key=lambda entry: entry["total_seconds"], reverse=True)
        categories = {}
        for entry in entries:
            if entry["category"] != "phase":
                categories[entry["category"]] = categories.get(entry["category"], 0.0) + entry["self_seconds"]
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "categories_work_seconds": categories,
            "functions": entries,
            "work_totals_are_concurrent": True,
        }


@contextmanager
def measure(category, name):
    trace = _trace.get()
    if trace is None:
        yield
        return
    parent = _span.get()
    current = {"children": 0.0}
    token = _span.set(current)
    started = trace.clock()
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        elapsed = max(0.0, trace.clock() - started)
        _span.reset(token)
        if parent is not None:
            parent["children"] += elapsed
        trace.record(category, name, elapsed, current["children"], failed)


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
