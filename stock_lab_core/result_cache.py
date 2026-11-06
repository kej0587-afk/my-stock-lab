"""Separate successful data retention from short provider-failure cooldowns."""

from functools import wraps
from contextvars import ContextVar
import hashlib
import inspect
import marshal

import streamlit as st
from stock_lab_core.performance import count_event


class _UnsuccessfulResult(Exception):
    def __init__(self, result):
        super().__init__("Provider returned no usable data")
        self.result = result


class UncachedValue:
    """Return usable data without starting another cache lifetime."""

    def __init__(self, value):
        self.value = value


class _UncachedResult(Exception):
    def __init__(self, value):
        super().__init__("Result deliberately bypasses cache storage")
        self.value = value


def cache_result(*, ttl, failure_ttl=60, is_success=None, trace_name=None):
    """Cache successes normally; returned failures expire after a short cooldown.

    Exceptions still propagate and are never cached. The outer cache prevents
    every rerun from immediately hammering an unavailable provider. Clearing the
    public function clears both layers, including manual-refresh callers.
    """
    successful = is_success or (lambda value: isinstance(value, dict) and value.get("ok") is True)

    def decorate(fn):
        probe = ContextVar(f"cache_probe_{fn.__qualname__}", default=None)

        def event(outcome):
            if trace_name:
                count_event(f"cache.{trace_name}.{outcome}")

        # Streamlit sees the wrapper source, so include the provider's code too.
        try:
            source = inspect.getsource(fn).encode("utf-8")
        except (OSError, TypeError):
            source = marshal.dumps(fn.__code__)
        revision = hashlib.sha256(source).hexdigest()[:16]

        def success_only(*args, **kwargs):
            marker = probe.get()
            if marker is not None:
                marker[0] = True
            event("miss")
            value = fn(*args, **kwargs)
            if isinstance(value, UncachedValue):
                raise _UncachedResult(value.value)
            if not successful(value):
                event("unavailable")
                raise _UnsuccessfulResult(value)
            event("success")
            return value

        success_only.__module__ = fn.__module__
        success_only.__qualname__ = fn.__qualname__ + ".success_only_" + revision
        success_only = st.cache_data(ttl=ttl, show_spinner=False)(success_only)

        def with_cooldown(*args, **kwargs):
            try:
                return success_only(*args, **kwargs)
            except _UnsuccessfulResult as exc:
                return exc.result

        with_cooldown.__module__ = fn.__module__
        with_cooldown.__qualname__ = fn.__qualname__ + ".with_cooldown_" + revision
        with_cooldown = st.cache_data(ttl=failure_ttl, show_spinner=False)(with_cooldown)

        @wraps(fn)
        def wrapped(*args, **kwargs):
            marker = [False]
            token = probe.set(marker) if trace_name else None
            event("lookup")
            try:
                value = with_cooldown(*args, **kwargs)
                if not marker[0]:
                    # Includes a concurrent cache wait; not a provider request.
                    event("reuse")
                return value
            except _UncachedResult as exc:
                event("bypass")
                return exc.value
            except BaseException:
                event("raised")
                raise
            finally:
                if token is not None:
                    probe.reset(token)

        def clear(*args, **kwargs):
            with_cooldown.clear(*args, **kwargs)
            success_only.clear(*args, **kwargs)

        wrapped.clear = clear
        return wrapped
    return decorate
