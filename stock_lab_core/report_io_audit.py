"""Observation-only provider accounting; never retain URLs, keys or response bodies."""
from contextlib import contextmanager
from urllib.parse import urlsplit
from stock_lab_core.performance import count_event, measure


def provider_label(url):
    host = (urlsplit(url).hostname or "").lower()
    for domain, label in (("bls.gov", "bls"), ("census.gov", "census"),
                          ("stlouisfed.org", "fred"), ("bok.or.kr", "bok"),
                          ("customs.go.kr", "customs"), ("motir.go.kr", "motir"),
                          ("federalreserve.gov", "fed"), ("boj.or.jp", "boj"),
                          ("sec.gov", "sec")):
        if host == domain or host.endswith("." + domain):
            return label
    return "other_official"


def http_call(provider, call, *args, **kwargs):
    count_event(f"official_http.{provider}.attempt")
    try:
        with measure("official_transport", provider):
            response = call(*args, **kwargs)
    except Exception:
        count_event(f"official_http.{provider}.transport_error")
        raise
    status = getattr(response, "status_code", None)
    status = str(status) if type(status) is int and 100 <= status <= 599 else "unknown"
    count_event(f"official_http.{provider}.status_{status}")
    return response


@contextmanager
def lock_wait(lock, provider):
    with measure("official_wait", provider):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


def cache_event(provider, event):
    count_event(f"official_cache.{provider}.{event}")
