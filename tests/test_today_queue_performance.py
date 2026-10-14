import json
import ast
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core import decision_engine, prices
from stock_lab_core.performance import PerformanceTrace, submit_with_context
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


def test_rs_prefetch_uses_exact_period_market_and_sector_and_domestic_paths(app_module, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "get_rs_benchmark", lambda ticker, ac: "SPY")
    monkeypatch.setattr(app_module, "get_sector_benchmark_info", lambda *a: ("XLK", "Tech"))
    monkeypatch.setattr(app_module, "prefetch_price_data_parallel", lambda tickers, period: calls.append((tickers, period)) or {})
    app_module.prefetch_rs_price_frames([
        {"ticker": "NVDA", "name": "Nvidia", "asset_class": "us_stock"},
        {"ticker": "005930.KS", "name": "Samsung", "asset_class": "kr_stock"},
    ])
    assert calls == [(["005930.KS", "NVDA", "SPY", "XLK"], "3mo")]


def test_history_scope_copies_only_matching_successes_and_expires(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    frame = pd.DataFrame({"Close": [100.0]})
    calls = []
    monkeypatch.setattr(prices, "_fetch_yfinance_ohlcv", lambda ticker, period: calls.append((ticker, period)) or frame.copy())
    prices.load_price_df.clear()
    try:
        with prices.price_frame_scope({"NVDA": frame, "EMPTY": pd.DataFrame()}, "3mo"):
            with ThreadPoolExecutor(max_workers=2) as executor:
                got = submit_with_context(executor, prices.load_price_df, "NVDA", "3mo").result()
            got.iloc[0, 0] = 999
            assert prices.load_price_df("NVDA", "3mo").iloc[0, 0] == 100
            assert calls == []
            prices.load_price_df("NVDA", "1y")
            prices.load_price_df("EMPTY", "3mo")
        prices.load_price_df("NVDA", "3mo")
        assert calls == [("NVDA", "1y"), ("EMPTY", "3mo"), ("NVDA", "3mo")]
        pd.testing.assert_frame_equal(frame, pd.DataFrame({"Close": [100.0]}))
    finally:
        prices.load_price_df.clear()


@pytest.mark.parametrize("days", [3, 12, 20, 64, 260])
@pytest.mark.parametrize("label", ["일봉", "주봉", "월봉"])
def test_ready_timeframe_snapshot_matches_recomputed_indicators(app_module, days, label):
    frame = make_price_df(days=days)
    original = frame.copy(deep=True)
    expected = app_module.build_precision_timeframe_snapshot(label, frame)
    actual = app_module.build_precision_timeframe_snapshot(label, frame, _indicators_ready=True)
    assert json.dumps(_to_jsonable(actual), sort_keys=True) == json.dumps(_to_jsonable(expected), sort_keys=True)
    pd.testing.assert_frame_equal(frame, original)


def test_mtf_reuses_only_weekly_monthly_indicators(app_module, monkeypatch):
    frame = make_price_df(days=600)
    calls = []
    original = app_module.build_indicators
    monkeypatch.setattr(app_module, "build_indicators", lambda df: calls.append(len(df)) or original(df))
    with PerformanceTrace() as trace:
        pack = app_module.build_precision_multi_timeframe_pack("NVDA", frame.tail(260), _long_price_df=frame)
    assert len(calls) == 3
    for label in ("주봉", "월봉"):
        expected = app_module.build_precision_timeframe_snapshot(label, pack[label]["df"])
        assert json.dumps(_to_jsonable(pack[label]["snapshot"]), sort_keys=True) == json.dumps(_to_jsonable(expected), sort_keys=True)
    assert trace.report()["functions"]


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("failed_rows", [False, True])
def test_entire_summary_matches_old_rs_and_mtf_paths(app_module, monkeypatch, warm, failed_rows):
    app = app_module
    frame = make_price_df()
    long_frame = make_price_df(days=600)
    frames = {"1y": frame, "10y": long_frame, "3mo": frame.tail(64)}
    symbols = ("NVDA", "MSFT", "SPY", "005930.KS") + (("EMPTY", "ERROR") if failed_rows else ())
    items = tuple({"ticker": symbol, "name": "Profile company", "is_etf": symbol == "SPY", "asset_class": "us_etf_sp" if symbol == "SPY" else "kr_stock" if symbol.endswith(".KS") else "us_stock"} for symbol in symbols)
    monkeypatch.setattr(app, "holdings_table", pd.DataFrame())
    monkeypatch.setattr(app, "get_my_price", lambda *a: 0.0)
    monkeypatch.setattr(app, "has_position", lambda *a: False)
    monkeypatch.setattr(app, "load_display_live_price", lambda *a: 0.0)
    monkeypatch.setattr(app, "load_fin_score_meta_fast", lambda ticker, is_etf: (0 if is_etf else 3 if ticker.endswith(".KS") else 4, {}))
    monkeypatch.setattr(app, "get_sector_benchmark_info", lambda *a: ("XLK", "Tech"))
    monkeypatch.setattr(app, "get_sector_provenance", lambda *a: {})
    def history(ticker, period):
        if ticker == "ERROR":
            raise RuntimeError("provider probe")
        if ticker == "EMPTY":
            return pd.DataFrame()
        result = frames[period].copy()
        scale = 1 + sum(ord(character) for character in ticker) % 13 / 10
        result[["Open", "High", "Low", "Close"]] *= scale
        result["Volume"] *= scale
        return result
    monkeypatch.setattr(prices, "_fetch_yfinance_ohlcv", history)
    monkeypatch.setattr(prices, "_fetch_pykrx_ohlcv", history)
    monkeypatch.setattr(app, "load_price_frames_batch", lambda tickers, period: {ticker: history(ticker, period) for ticker in tickers if not ticker.endswith(".KS") and ticker not in {"ERROR", "EMPTY"}})
    snapshot = app.build_precision_timeframe_snapshot
    prefetch = app.prefetch_rs_price_frames
    app.st.session_state.fin_score_map = {}
    try:
        app.get_auto_benchmark_info.clear()
        prices.load_price_df.clear()
        monkeypatch.setattr(app, "prefetch_rs_price_frames", lambda *a: {})
        monkeypatch.setattr(app, "build_precision_timeframe_snapshot", lambda label, df, **kw: snapshot(label, df))
        baseline = app.get_all_summary((), "개인모드", items)
        baseline_scores = dict(app.st.session_state.fin_score_map)
        if not warm:
            app.get_auto_benchmark_info.clear()
            prices.load_price_df.clear()
        monkeypatch.setattr(app, "prefetch_rs_price_frames", prefetch)
        monkeypatch.setattr(app, "build_precision_timeframe_snapshot", snapshot)
        app.st.session_state.fin_score_map = {}
        optimized = app.get_all_summary((), "개인모드", items)
        assert len(baseline) == len(items)
        pd.testing.assert_frame_equal(optimized, baseline)
        assert dict(app.st.session_state.fin_score_map) == baseline_scores
        if failed_rows:
            assert baseline.set_index("티커").loc["EMPTY", "판정코드"] == "DATA_UNAVAILABLE"
            assert baseline.set_index("티커").loc["ERROR", "판정코드"] == "DATA_ERROR"
    finally:
        app.get_auto_benchmark_info.clear()
        prices.load_price_df.clear()


def test_old_price_module_skips_scoped_prefetch_without_import_crash(monkeypatch):
    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    block = next(node for node in tree.body if isinstance(node, ast.Try) and any(
        isinstance(child, ast.ImportFrom) and any(alias.name == "price_frame_scope" for alias in child.names)
        for child in node.body
    ))
    monkeypatch.delattr(prices, "price_frame_scope")
    namespace = {}
    exec(compile(ast.Module(body=[block], type_ignores=[]), "app.py", "exec"), namespace)
    assert namespace["RS_SCOPED_PREFETCH_AVAILABLE"] is False
    with namespace["price_frame_scope"]({}, "3mo"):
        pass


def test_simultaneous_history_scopes_are_isolated_and_restore_after_errors():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    def fetch(value):
        frame = pd.DataFrame({"Close": [float(value)]})
        with prices.price_frame_scope({"NVDA": frame}, "3mo"):
            barrier.wait(timeout=5)
            return prices.load_price_df("NVDA", "3mo").iloc[0, 0]
    with prices.price_frame_scope({"NVDA": pd.DataFrame({"Close": [9.0]})}, "3mo"):
        with ThreadPoolExecutor(max_workers=2) as executor:
            a, b = executor.submit(fetch, 100), executor.submit(fetch, 200)
            assert (a.result(), b.result()) == (100, 200)
        with pytest.raises(RuntimeError):
            with prices.price_frame_scope({"NVDA": pd.DataFrame({"Close": [99.0]})}, "3mo"):
                raise RuntimeError("probe")
        assert prices.load_price_df("NVDA", "3mo").iloc[0, 0] == 9
    assert prices._PREFETCHED_HISTORY.get() is None


def test_price_decorator_stack_preserves_targeted_clear_and_unwrapped(monkeypatch):
    calls = []
    monkeypatch.setattr(prices, "_fetch_yfinance_ohlcv", lambda ticker, period: calls.append((ticker, period)) or pd.DataFrame({"Close": [100.0]}))
    prices.load_price_df.clear()
    try:
        prices.load_price_df("TEST", "1y")
        prices.load_price_df("TEST", "1y")
        assert len(calls) == 1
        prices.load_price_df.__wrapped__("TEST", "1y")
        assert len(calls) == 2
        prices.load_price_df.clear("TEST", "1y")
        prices.load_price_df("TEST", "1y")
        assert len(calls) == 3
    finally:
        prices.load_price_df.clear()
