"""Calculation-local Yahoo chart connections; no quote or failure caching."""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock, get_ident
import urllib.error
import urllib.request

import requests

from stock_lab_core.performance import count_event


_pool = ContextVar("yahoo_chart_connections", default=None)


class _NoAuth(requests.auth.AuthBase):
    def __call__(self, request):
        # Public quotes must not pick up machine-local .netrc credentials.
        return request


@contextmanager
def reuse_yahoo_chart_connections():
    """The caller must join workers before leaving this scope."""
    if _pool.get() is not None:
        yield
        return
    sessions, lock = {}, Lock()
    token = _pool.set((sessions, lock))
    try:
        yield
    finally:
        _pool.reset(token)
        for session in sessions.values():
            session.close()


class _Response:
    def __init__(self, response):
        self.response = response

    def read(self):
        return self.response.content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.response.close()


def open_yahoo_chart(request, *, timeout):
    pool = _pool.get()
    if pool is None:
        return urllib.request.urlopen(request, timeout=timeout)
    sessions, lock = pool
    with lock:
        session = sessions.get(get_ident())
        if session is None:
            session = sessions[get_ident()] = requests.Session()
            session.auth = _NoAuth()
            count_event("yahoo_chart.connection_session_created")
        else:
            count_event("yahoo_chart.connection_session_reused")
    session.cookies.clear()
    headers = dict(request.header_items())
    headers["Accept-Encoding"] = "identity"
    try:
        response = session.get(request.full_url, headers=headers, timeout=timeout, stream=True)
        if response.status_code >= 400:
            response.close()
            raise urllib.error.HTTPError(
                request.full_url, response.status_code, response.reason, response.headers, None,
            )
        # Read within the error translation boundary, preserving the raw JSON bytes.
        try:
            response.content
        except Exception:
            response.close()
            raise
        return _Response(response)
    except requests.exceptions.Timeout as exc:
        raise urllib.error.URLError(TimeoutError("timed out")) from exc
    except requests.exceptions.RequestException as exc:
        raise urllib.error.URLError(str(exc)) from exc
