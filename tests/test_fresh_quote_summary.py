"""Replay real app summary assembly with deterministic upstream inputs.

No app import, network, account access, or timing-performance claim. Decision
fixtures isolate transport changes; this does not retest the scoring engine.
Every output column, dtype, row order, and financial-score state is compared.
"""

import ast
from copy import deepcopy
import logging
from pathlib import Path
import socket
from threading import current_thread
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import prices, quote_prefetch
from stock_lab_core.asset_classifier import (
    infer_asset_class_for_ticker,
    is_fin_score_exempt_asset,
    is_leveraged_or_inverse_product,
)
from stock_lab_core.decision_engine import (
    apply_live_price_with_indicators,
    build_sideways_quality_state,
    classify_macro_state,
)
from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.execution_gate import classify_sector_rs_state
from stock_lab_core.formatters import (
    clean_bool, clean_float, finite_num, format_currency, is_kr_listed,
    normalize_ticker, sanitize_ticker_value,
)
from stock_lab_core.performance import measure, submit_with_context, timed_call
from stock_lab_core.signal_basis import build_signal_basis
from stock_lab_core.ta_engine import build_indicators


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {
    "get_all_summary", "_compute_summary_item", "load_display_live_price",
    "dedupe_dashboard_summary_df", "build_summary_status_item",
    "_build_live_only_summary_item", "get_dashboard_market_label",
    "get_dashboard_type_label", "get_dashboard_group_label",
}


class MainThreadScores(dict):
    def __setitem__(self, key, value):
        assert current_thread().name == "MainThread"
        super().__setitem__(key, value)


@pytest.fixture(scope="module")
def summary_ast():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert {node.name for node in nodes} == FUNCTIONS
    return compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "app.py"), "exec")


@pytest.fixture
def replay(monkeypatch, summary_ast):
    prices.clear_latest_price_cache()
    clock = [0.0]
    monkeypatch.setattr(quote_prefetch.time, "monotonic", lambda: clock[0])
    network = Mock(side_effect=AssertionError("Unexpected live quote request"))
    monkeypatch.setattr(prices.urllib.request, "urlopen", network)
    monkeypatch.setattr(socket.socket, "connect", network)
    quotes = {
        "379810.KS": 100.0, "122630.KS": 110.0, "MSFT": 120.0,
        "PANW": 130.0, "006400.KS": 140.0, "0167A0.KS": 150.0,
        "035900.KQ": 160.0, "NOHISTORY": 170.0,
    }
    watchlist = [
        {"ticker": "379810.KS", "name": "Core", "is_etf": True, "bucket": "core"},
        {"ticker": "MSFT", "name": "Individual"},
        {"ticker": "122630.KS", "name": "Leveraged", "is_etf": True},
        {"ticker": "PANW", "name": "Projected target"},
        {"ticker": "006400.KS", "name": "Financial restriction"},
        {"ticker": "0167A0.KS", "name": "Live only", "is_etf": True},
        {"ticker": "035900.KQ", "name": "Decision failure"},
        {"ticker": "NOHISTORY", "name": "Missing history"},
        {"ticker": "379810.KS", "name": "Duplicate must not replace first", "is_etf": True},
        {"ticker": "", "name": "Empty ticker"},
    ]
    index = pd.bdate_range(end="2026-10-29", periods=260)
    close = np.linspace(70.0, 100.0, len(index)) + np.sin(np.arange(len(index)))
    frame = pd.DataFrame({
        "Open": close - .5, "High": close + 2, "Low": close - 2,
        "Close": close, "Volume": 1_000_000,
    }, index=index)
    frame.attrs["source"] = "fixture"
    frames = {ticker: frame.copy(deep=True) for ticker in quotes}
    frames["0167A0.KS"] = pd.DataFrame()
    frames["NOHISTORY"] = pd.DataFrame()
    originals = {ticker: value.copy(deep=True) for ticker, value in frames.items()}
    baseline_items = deepcopy(watchlist)
    singles = Mock(side_effect=lambda ticker: quotes[ticker])
    us = Mock(side_effect=lambda ticker: quotes[ticker])
    bulk = Mock(side_effect=lambda keys: {key: {"price": quotes[key]} for key in keys})
    monkeypatch.setattr(prices, "_fetch_naver_realtime_price", singles)
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", bulk)
    monkeypatch.setattr(prices, "_fetch_us_realtime_price", us)

    def prefetch(tickers, period):
        assert period in {"1y", "10y"}
        return {ticker: frames[ticker].copy(deep=True) for ticker in tickers}

    def decision(**kwargs):
        ticker = kwargs["ticker"]
        assert (kwargs["_macro_penalty"], kwargs["_final_macro_risk"], kwargs["_total_eval"]) == (1, 2, 1_000_000)
        assert (kwargs["_cash_available"], kwargs["_reserve_available"]) == (100_000, 200_000)
        assert kwargs["live_price"] == quotes[ticker]
        if ticker == "035900.KQ":
            raise ValueError("fixture decision failure")
        current = kwargs["live_price"]
        result = {
            "cur_p": current, "grade": "A", "t_score": 8,
            "dec": "Entry", "decision_code": "NEW_ENTRY_LEADER", "decision_group": "buyish",
            "rs_label": "neutral", "rsi": 55.0, "mfi": 60.0, "pct_b": .6, "adj": 8.0,
            "dd": -.1, "rr_stop": current * .9, "rr_target": current * 1.2,
            "rr_ratio": 2.0, "atr": 5.0, "ma20": current * .98,
            "bucket": "core" if kwargs["is_etf"] else "satellite",
            "current_w": 2.0, "target_w": 5.0, "safety_state": "GREEN", "macro_state": "NORMAL",
        }
        if ticker == "122630.KS":
            result.update(decision_code="LEVERAGED_DCA_CONDITIONAL", dec="DCA conditional")
        elif ticker == "PANW":
            result.update(rr_target_is_projection=True, rr_target_source="fixture projection")
        elif ticker == "006400.KS":
            result.update(decision_code="HARD_BLOCK_FINANCIAL", decision_group="caution", dec="Financial restriction")
        return result

    env = dict(
        pd=pd, np=np, logging=logging, measure=measure, timed_call=timed_call,
        submit_with_context=submit_with_context, price_frame_scope=prices.price_frame_scope,
        clean_bool=clean_bool, clean_float=clean_float, finite_num=finite_num,
        format_currency=format_currency, is_kr_listed=is_kr_listed,
        normalize_ticker=normalize_ticker, sanitize_ticker_value=sanitize_ticker_value,
        sanitize_asset_name=lambda name, ticker: name or ticker,
        is_fin_score_exempt_asset=is_fin_score_exempt_asset,
        infer_asset_class_for_ticker=infer_asset_class_for_ticker,
        is_leveraged_or_inverse_product=is_leveraged_or_inverse_product,
        build_indicators=build_indicators, apply_live_price_with_indicators=apply_live_price_with_indicators,
        build_sideways_quality_state=build_sideways_quality_state, classify_macro_state=classify_macro_state,
        build_decision_workflow=build_decision_workflow, classify_sector_rs_state=classify_sector_rs_state,
        build_signal_basis=lambda source, context: build_signal_basis(source, context, calculated_at="fixture clock"),
        calc_series_mdd=lambda series: (series / series.cummax() - 1).min(),
        prefetch_price_data_parallel=Mock(side_effect=prefetch),
        prefetch_rs_price_frames=Mock(return_value={}), prefetch_benchmark_info_parallel=Mock(),
        resolve_decision_runtime_inputs=lambda: (1, 2, 1_000_000),
        get_cash_available_for_dca=lambda mode: 100_000,
        get_reserve_available_for_crash_buy=lambda mode: 200_000,
        load_fin_score_meta_fast=lambda ticker, is_etf: (1 if ticker == "006400.KS" else 4, {}),
        get_my_price=lambda *args: 90, has_position=lambda name, ticker: ticker == "379810.KS",
        load_latest_price=prices.load_latest_price, calc_scores_and_decision=decision,
        fetch_yahoo_daymarket_price_direct=Mock(side_effect=AssertionError("unexpected fallback")),
        _fetch_yahoo_regular_close_price=Mock(side_effect=AssertionError("unexpected fallback")),
        build_precision_multi_timeframe_pack=lambda *args, **kwargs: {},
        apply_precision_mtf_decision_guard=lambda value, *args, **kwargs: value,
        apply_leveraged_dca_dashboard_override=lambda value: value,
        apply_leveraged_precision_decision_override=lambda value, *args: value,
        detect_chart_pattern_candidates=lambda value: [],
        summarize_chart_pattern_for_dashboard=lambda *args: ("-", "", ""),
        get_auto_benchmark_info=lambda *args: {
            "market_bench": "SPY", "underlying_bench": "", "sector_bench": "",
            "sector_rs_change_pct": np.nan, "sector_rs_asof": "fixture date",
        },
        get_benchmark_display_name=lambda ticker: ticker,
        DECISION_GROUP_BY_CODE={"DATA_ERROR": "caution", "DATA_UNAVAILABLE": "caution"},
    )
    exec(summary_ast, env)

    def run(fresh_quotes=False, *, items=None):
        state = SimpleNamespace(fin_score_map=MainThreadScores({"UNCHANGED": 3}))
        env["st"] = SimpleNamespace(session_state=state)
        result = env["get_all_summary"](
            tuple(state.fin_score_map.items()), "fixture mode",
            watchlist if items is None else items, fresh_quotes=fresh_quotes,
        )
        assert quote_prefetch.prefetched_quote("379810.KS") is None
        return result, dict(state.fin_score_map)

    yield SimpleNamespace(run=run, env=env, bulk=bulk, singles=singles, us=us,
                          quotes=quotes, clock=clock, watchlist=watchlist)
    prices.clear_latest_price_cache()
    assert watchlist == baseline_items
    for ticker, original in originals.items():
        pd.testing.assert_frame_equal(frames[ticker], original, check_exact=True)
        assert frames[ticker].attrs == original.attrs
    network.assert_not_called()


@pytest.mark.parametrize("bulk_case", ["success", "partial", "invalid", "timeout", "expired"])
def test_real_summary_full_output_and_state_equal_with_fresh_quotes(replay, bulk_case):
    before, before_state = replay.run(False)
    replay.bulk.assert_not_called()
    us_before = replay.us.call_args_list.copy()
    prices.clear_latest_price_cache()
    replay.us.reset_mock()
    replay.singles.reset_mock()

    def fetch(keys):
        if bulk_case == "timeout":
            raise TimeoutError("fixture bulk timeout")
        if bulk_case == "expired":
            replay.clock[0] += 15.0
        values = {key: {"price": replay.quotes[key]} for key in keys}
        if bulk_case == "partial":
            values.pop("379810.KS")
        if bulk_case == "invalid":
            values["379810.KS"] = {"price": float("nan")}
        return values

    replay.bulk.side_effect = fetch
    after, after_state = replay.run(True)
    pd.testing.assert_frame_equal(before, after, check_exact=True)
    assert before_state == after_state
    assert sorted(str(call) for call in us_before) == sorted(str(call) for call in replay.us.call_args_list)
    replay.bulk.assert_called_once_with(["379810.KS", "122630.KS", "006400.KS", "0167A0.KS", "035900.KQ"])
    assert after["티커"].tolist() == [item["ticker"] for item in replay.watchlist[:8]]
    assert after.iloc[0]["종목명"] == "Core"
    assert after_state["UNCHANGED"] == 3
    assert normalize_ticker("035900.KQ") not in after_state
    assert after_state == {
        "UNCHANGED": 3,
        **{normalize_ticker(ticker): (1 if ticker == "006400.KS" else 4)
           for ticker in ("379810.KS", "MSFT", "122630.KS", "PANW", "006400.KS")},
    }
    codes = after.set_index("티커")["판정코드"]
    assert codes["MSFT"] == "NEW_ENTRY_LEADER"
    assert codes["379810.KS"] == codes["PANW"] == "NEW_ENTRY_LEADER"
    assert codes["122630.KS"] == "LEVERAGED_DCA_CONDITIONAL"
    assert codes["006400.KS"] == "HARD_BLOCK_FINANCIAL"
    assert codes["0167A0.KS"] == codes["NOHISTORY"] == "LIVE_ONLY_DATA"
    assert codes["035900.KQ"] == "DATA_ERROR"
    if bulk_case == "success":
        replay.singles.assert_not_called()
    else:
        assert replay.singles.called


def test_default_summary_preserves_warm_quote_cache_without_bulk(replay):
    for ticker in replay.quotes:
        prices.load_latest_price(ticker)
    replay.singles.reset_mock()
    replay.us.reset_mock()
    first, first_state = replay.run()
    second, second_state = replay.run()
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert first_state == second_state
    replay.bulk.assert_not_called()
    replay.singles.assert_not_called()
    replay.us.assert_not_called()


def test_failed_upper_timeframe_verification_is_not_executable(replay):
    def failed(*args, **kwargs):
        raise TimeoutError("synthetic MTF lookup failure")
    replay.env["build_precision_multi_timeframe_pack"] = failed
    frame, _ = replay.run()
    row = frame.set_index("티커").loc["MSFT"]
    assert row["데이터상태"] == "상위시간대 조회 실패"
    assert row["게이트상태"] == "데이터확인"


def test_old_loaded_price_module_keeps_original_summary_path(replay, monkeypatch):
    before, before_state = replay.run()
    prices.clear_latest_price_cache()
    monkeypatch.delattr(prices, "fresh_kr_quote_scope")
    after, after_state = replay.run(True)
    pd.testing.assert_frame_equal(before, after, check_exact=True)
    assert before_state == after_state
    replay.bulk.assert_not_called()


@pytest.mark.parametrize("session", ["closed", "regular", "after_hours", "overnight"])
def test_real_summary_preserves_us_session_source_order(replay, monkeypatch, session):
    calls = []
    monkeypatch.setattr(prices, "_fetch_us_realtime_price", lambda ticker: calls.append("realtime") or 0)
    monkeypatch.setattr(prices, "_us_equity_market_closed_today", lambda: session == "closed")
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: session == "regular")
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: session == "after_hours")
    monkeypatch.setattr(prices, "_accept_us_untimed_quote_price", lambda ticker, value: value)
    monkeypatch.setattr(prices, "_fetch_kis_us_quote_price", lambda ticker, **kwargs: calls.append(("kis", kwargs)) or 120)
    monkeypatch.setattr(prices, "_fetch_yahoo_quote", lambda ticker: calls.append("yahoo_quote") or 120)
    monkeypatch.setattr(prices, "_fetch_yahoo_overnight_page_price", lambda ticker: calls.append("overnight") or 120)
    items = [replay.watchlist[1]]
    before, before_state = replay.run(False, items=items)
    before_calls = calls.copy()
    calls.clear()
    prices.clear_latest_price_cache()
    after, after_state = replay.run(True, items=items)
    pd.testing.assert_frame_equal(before, after, check_exact=True)
    assert before_state == after_state
    expected = {
        "closed": ["realtime", ("kis", {"regular_only": True})],
        "regular": ["realtime", "yahoo_quote"],
        "after_hours": ["realtime", "yahoo_quote"],
        "overnight": ["realtime", "overnight"],
    }
    assert calls == before_calls == expected[session]
    assert after.iloc[0]["판정코드"] == "NEW_ENTRY_LEADER"
    replay.bulk.assert_not_called()
