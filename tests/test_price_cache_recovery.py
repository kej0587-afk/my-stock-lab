import ast
from functools import wraps
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core import prices, result_cache


@pytest.mark.parametrize("name,failure_ttl,args", [
    ("load_price_df", 15, ("TEST",)),
    ("load_usdkrw_rate", 15, ()),
    ("_load_latest_price_cached", 5, ("TEST",)),
])
def test_price_loaders_retry_failures_before_normal_ttl(name, failure_ttl, args, monkeypatch):
    clock, calls = [0], []
    def fake_cache(*, ttl, **kwargs):
        def decorate(fn):
            stored = {}
            @wraps(fn)
            def cached(*a, **kw):
                key = repr((a, kw))
                if key not in stored or clock[0] - stored[key][0] >= ttl:
                    stored[key] = (clock[0], fn(*a, **kw))
                return stored[key][1]
            cached.clear = lambda *a, **kw: stored.clear()
            return cached
        return decorate
    monkeypatch.setattr(result_cache.st, "cache_data", fake_cache)
    def provider(*a, **kw):
        calls.append(clock[0])
        if name == "_load_latest_price_cached":
            return 0.0 if len(calls) == 1 else 123.4
        return pd.DataFrame() if len(calls) == 1 else pd.DataFrame({"Close": [123.4]})
    monkeypatch.setattr(prices, "_fetch_yfinance_ohlcv", provider)
    monkeypatch.setattr(prices.yf, "download", provider)
    monkeypatch.setattr(prices, "_fetch_price_uncached", provider)
    tree = ast.parse(Path(prices.__file__).read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    cache_node = next(d for d in node.decorator_list if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "cache_result")
    decorator = eval(compile(ast.Expression(cache_node), prices.__file__, "eval"), vars(prices))
    cached = decorator(getattr(prices, name).__wrapped__)
    failed = cached(*args)
    if isinstance(failed, pd.DataFrame):
        assert failed.empty
    else:
        assert failed == 0.0
    clock[0] = failure_ttl - 1
    cached(*args)
    assert calls == [0]
    clock[0] = failure_ttl + 1
    recovered = cached(*args)
    assert (recovered.iloc[-1]["Close"] if isinstance(recovered, pd.DataFrame) else recovered) == 123.4
    clock[0] += 1
    cached(*args)
    assert calls == [0, failure_ttl + 1]
