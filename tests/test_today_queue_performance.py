import json
import ast
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core import decision_engine, prices
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import SCENARIOS, _bench_info, _to_jsonable


@pytest.fixture
def batch_provider(monkeypatch):
    prices.load_price_frames_batch.clear()
    monkeypatch.setattr(prices, "_maybe_align_ohlcv_to_live_price", lambda ticker, frame: frame)
    yield
    prices.load_price_frames_batch.clear()


@pytest.mark.parametrize("ticker_first", [False, True])
def test_batch_matches_single_history_and_never_mixes_symbols(batch_provider, monkeypatch, ticker_first):
    fields = ["Open", "High", "Low", "Close", "Volume", "Adj Close"]
    data = pd.DataFrame([[10, 100] * len(fields)],
                        columns=pd.MultiIndex.from_product([fields, ["BITX", "SPY"]]),
                        index=pd.to_datetime(["2026-10-14"]))
    if ticker_first:
        data.columns = data.columns.swaplevel()
    original = data.copy(deep=True)
    calls = []
    def download(*a, **kw):
        calls.append((a, kw))
        return data
    monkeypatch.setattr(prices.yf, "download", download)
    batch = prices.load_price_frames_batch(("BITX", "SPY", "005930.KS"))
    assert set(batch) == {"BITX", "SPY"}
    assert calls[0][0][0] == ["BITX", "SPY"]
    assert calls[0][1]["threads"] == 2
    assert calls[0][1]["auto_adjust"] is False
    for ticker in batch:
        pd.testing.assert_frame_equal(batch[ticker], prices._fetch_yfinance_ohlcv(ticker))
    pd.testing.assert_frame_equal(data, original)


def test_ambiguous_flat_batch_is_rejected_and_missing_symbol_is_omitted(batch_provider, monkeypatch):
    frame = pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-10-14"]))
    monkeypatch.setattr(prices.yf, "download", lambda *a, **kw: frame)
    assert prices.load_price_frames_batch.__wrapped__(("BITX", "SPY")) == {}
    frame.columns = pd.MultiIndex.from_tuples([("Close", "SPY")])
    batch = prices.load_price_frames_batch.__wrapped__(("BITX", "SPY"))
    assert set(batch) == {"SPY"}


def test_prefetch_preserves_domestic_and_missing_symbol_fallbacks(app_module, monkeypatch):
    frame = pd.DataFrame({"Close": [100]})
    calls = []
    monkeypatch.setattr(app_module, "load_price_frames_batch", lambda *a: {"SPY": frame})
    monkeypatch.setattr(app_module, "load_price_df", lambda ticker, period: calls.append((ticker, period)) or frame)
    result = app_module.prefetch_price_data_parallel(["SPY", "SPY", "005930.KS", "BITX"])
    assert set(result) == {"SPY", "005930.KS", "BITX"}
    assert sorted(calls) == [("005930.KS", "1y"), ("BITX", "1y")]
    monkeypatch.setattr(app_module, "load_price_frames_batch", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    calls.clear()
    assert set(app_module.prefetch_price_data_parallel(["SPY"])) == {"SPY"}
    assert calls == [("SPY", "1y")]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario[0] for scenario in SCENARIOS])
@pytest.mark.parametrize("live_gap", [0.0, 0.02])
def test_shared_live_context_keeps_entire_decision_unchanged(app_module, monkeypatch, scenario, live_gap):
    _, price_kwargs, rs_score, rs_slope, kwargs = scenario
    frame = make_price_df(**price_kwargs)
    original = frame.copy(deep=True)
    monkeypatch.setattr(app_module, "get_rs_score", lambda *a: rs_score)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda *a: rs_slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: frame.index[-1])
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.0
    context = app_module.apply_live_price_with_indicators(frame, live, kwargs["ticker"], app_module.build_indicators)
    baseline = app_module.calc_scores_and_decision(df=frame, live_price=live, **kwargs)
    shared = app_module.calc_scores_and_decision(df=frame, live_price=live, _live_indicator_context=context, **kwargs)
    assert json.dumps(_to_jsonable(shared), sort_keys=True, default=str) == json.dumps(_to_jsonable(baseline), sort_keys=True, default=str)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("days", [20, 600])
def test_prefetched_mtf_keeps_short_history_fallbacks_and_all_timeframes(app_module, monkeypatch, days):
    frame = make_price_df(days=days)
    daily = frame.tail(260).copy()
    calls = []
    monkeypatch.setattr(app_module, "load_price_df", lambda ticker, period: calls.append(period) or frame)
    baseline = app_module.build_precision_multi_timeframe_pack("TEST", daily)
    baseline_calls = list(calls)
    calls.clear()
    shared = app_module.build_precision_multi_timeframe_pack("TEST", daily, _long_price_df=frame)
    assert calls == baseline_calls[1:]
    assert set(shared) == set(baseline)
    for timeframe in baseline:
        pd.testing.assert_frame_equal(shared[timeframe]["df"], baseline[timeframe]["df"])
        assert json.dumps(_to_jsonable(shared[timeframe]["snapshot"]), sort_keys=True) == json.dumps(_to_jsonable(baseline[timeframe]["snapshot"]), sort_keys=True)


def test_price_refresh_clears_batch_cache(app_module, monkeypatch):
    clears = []
    monkeypatch.setattr(app_module, "load_price_frames_batch", type("Cache", (), {"clear": lambda self: clears.append(True)})())
    app_module.clear_price_and_chart_cache()
    assert clears == [True]


def test_older_loaded_price_module_keeps_individual_fallback(monkeypatch):
    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    block = next(node for node in tree.body if isinstance(node, ast.Try) and any(
        isinstance(child, ast.ImportFrom) and any(alias.name == "load_price_frames_batch" for alias in child.names)
        for child in node.body
    ))
    monkeypatch.delattr(prices, "load_price_frames_batch")
    namespace = {}
    exec(compile(ast.Module(body=[block], type_ignores=[]), "app.py", "exec"), namespace)
    assert namespace["load_price_frames_batch"](("SPY",), "10y") == {}
