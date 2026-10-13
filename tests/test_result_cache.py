from functools import wraps

from stock_lab_core import result_cache


def test_failure_cooldown_expires_before_success_ttl_and_clear_clears_both(monkeypatch):
    clock = [0]

    def fake_cache(*, ttl, **kwargs):
        def decorate(fn):
            cache = {}
            @wraps(fn)
            def wrapped(*args, **kw):
                key = repr((args, kw))
                if key in cache and clock[0] - cache[key][0] < ttl:
                    return cache[key][1]
                value = fn(*args, **kw)
                cache[key] = (clock[0], value)
                return value
            wrapped.clear = lambda *a, **kw: cache.clear()
            return wrapped
        return decorate

    monkeypatch.setattr(result_cache.st, "cache_data", fake_cache)
    calls = []

    @result_cache.cache_result(ttl=21600, failure_ttl=60)
    def lookup(ticker):
        calls.append(ticker)
        return {"ok": len(calls) > 1, "source": ticker}

    assert not lookup("TEST")["ok"]
    assert not lookup("TEST")["ok"]
    assert len(calls) == 1
    clock[0] = 61
    assert lookup("TEST")["ok"]
    clock[0] = 200
    assert lookup("TEST")["ok"]
    assert len(calls) == 2
    lookup.clear()
    lookup("TEST")
    assert len(calls) == 3


def test_streamlit_cache_layers_do_not_share_values_between_functions():
    @result_cache.cache_result(ttl=3600)
    def first():
        return {"ok": True, "source": "first"}

    @result_cache.cache_result(ttl=3600)
    def second():
        return {"ok": True, "source": "second"}

    first.clear()
    second.clear()
    assert first()["source"] == "first"
    assert second()["source"] == "second"


def test_changed_provider_code_does_not_reuse_old_success():
    def old_lookup():
        return {"ok": True, "source": "old"}

    def new_lookup():
        return {"ok": True, "source": "new"}

    new_lookup.__qualname__ = old_lookup.__qualname__
    old_cached = result_cache.cache_result(ttl=3600)(old_lookup)
    new_cached = result_cache.cache_result(ttl=3600)(new_lookup)
    old_cached.clear()
    new_cached.clear()
    try:
        assert old_cached()["source"] == "old"
        assert new_cached()["source"] == "new"
    finally:
        old_cached.clear()
        new_cached.clear()
