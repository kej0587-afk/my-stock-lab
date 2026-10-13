"""Separate successful data retention from short provider-failure cooldowns."""

from functools import wraps
import hashlib
import inspect
import marshal

import streamlit as st


class _UnsuccessfulResult(Exception):
    def __init__(self, result):
        super().__init__("Provider returned no usable data")
        self.result = result


def cache_result(*, ttl, failure_ttl=60, is_success=None):
    """Cache successes normally; returned failures expire after a short cooldown.

    Exceptions still propagate and are never cached. The outer cache prevents
    every rerun from immediately hammering an unavailable provider. Clearing the
    public function clears both layers, including manual-refresh callers.
    """
    successful = is_success or (lambda value: isinstance(value, dict) and value.get("ok") is True)

    def decorate(fn):
        # Streamlit sees the wrapper source, so include the provider's code too.
        try:
            source = inspect.getsource(fn).encode("utf-8")
        except (OSError, TypeError):
            source = marshal.dumps(fn.__code__)
        revision = hashlib.sha256(source).hexdigest()[:16]

        def success_only(*args, **kwargs):
            value = fn(*args, **kwargs)
            if not successful(value):
                raise _UnsuccessfulResult(value)
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
            return with_cooldown(*args, **kwargs)

        def clear(*args, **kwargs):
            with_cooldown.clear(*args, **kwargs)
            success_only.clear(*args, **kwargs)

        wrapped.clear = clear
        return wrapped
    return decorate
