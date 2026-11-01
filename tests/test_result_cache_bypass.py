import pytest

from stock_lab_core.result_cache import UncachedValue, cache_result


@pytest.mark.parametrize("value", [100.0, 0.0, None, {"ok": True}])
def test_explicit_bypass_never_populates_success_or_failure_cache(value):
    calls = []
    admission = []

    @cache_result(ttl=900, failure_ttl=60, is_success=lambda v: admission.append(v) or True)
    def load(key):
        calls.append(key)
        return UncachedValue(value)

    load.clear()
    try:
        assert load("TEST") == value
        assert load("TEST") == value
        assert calls == ["TEST", "TEST"]
        assert admission == []
    finally:
        load.clear()


def test_bypass_then_fresh_value_has_normal_cache_lifetime():
    calls = []

    @cache_result(ttl=900, failure_ttl=60, is_success=lambda v: v > 0)
    def load(key):
        calls.append(key)
        return UncachedValue(100.0) if len(calls) == 1 else 120.0

    load.clear()
    try:
        assert load("TEST") == 100.0
        assert load("TEST") == 120.0
        assert load("TEST") == 120.0
        assert calls == ["TEST", "TEST"]
        load.clear()
        assert load("TEST") == 120.0
        assert len(calls) == 3
    finally:
        load.clear()
