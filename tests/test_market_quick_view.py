import ast
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core import market_quick_view as q


def frame(days=("2026-11-24", "2026-11-25", "2026-11-27"), values=(90, 100, 110)):
    return pd.DataFrame({"Close": values}, index=pd.to_datetime(days))


def quote(ticker, at, price=120, previous=100):
    return {"symbol": ticker, "regularMarketTime": pd.Timestamp(at).timestamp(),
            "regularMarketPrice": price, "regularMarketPreviousClose": previous}


@pytest.mark.parametrize("clock,expected", [
    ("2026-11-27T14:00Z", "2026-11-25"),
    ("2026-11-27T17:59Z", "2026-11-25"),
    ("2026-11-27T18:16Z", "2026-11-27"),
    ("2026-11-28T06:00Z", "2026-11-27"),
    ("2026-11-26T19:00Z", "2026-11-25"),
])
def test_completed_close_respects_holiday_and_short_day(clock, expected):
    f = frame()
    before = f.copy()
    out = q.last_close(f, "US", pd.Timestamp(clock))
    assert out["date"] == expected
    pd.testing.assert_frame_equal(f, before)


def test_gap_missing_and_unknown_are_not_daily_returns():
    now = pd.Timestamp("2026-11-28T00:00Z")
    assert not q.last_close(None, "US", now)
    assert not q.last_close(frame(("2026-11-24", "2026-11-27"), (90, 110)), "US", now)
    assert not q.last_close(frame(values=(90, float("nan"), 110)), "US", now)


def test_live_regular_is_reference_only_and_indices_never_take_etf_or_post():
    now = pd.Timestamp("2026-11-27T16:00Z")
    row = quote("^IXIC", "2026-11-27T15:59Z")
    row.update(postMarketPrice=999, postMarketTime=now.timestamp())
    raw = {"US": {"^IXIC": row}}
    before = deepcopy(raw)
    snap = q.build_snapshot({"^IXIC": frame()}, raw, now)
    ix = next(r for r in snap["indices"] if r["ticker"] == "^IXIC")
    assert ix["selected"]["price"] == 120
    assert ix["close"]["price"] == 100
    assert ix["close"]["date"] == "2026-11-25"
    assert raw == before
    later = q.build_snapshot({"^IXIC": frame()}, raw, pd.Timestamp("2026-11-27T19:00Z"))
    ix = next(r for r in later["indices"] if r["ticker"] == "^IXIC")
    assert ix["selected"]["price"] == 110


@pytest.mark.parametrize("ticker,stamp,expected", [
    ("^IXIC", "2026-11-27T16:01Z", False),
    ("^GSPC", "2026-11-27T15:59Z", False),
    ("^IXIC", "2026-11-25T16:00Z", False),
    ("^IXIC", "2026-11-27T15:59Z", True),
])
def test_regular_timestamp_symbol_isolation(ticker, stamp, expected):
    assert bool(q.regular_live(quote(ticker, stamp), "^IXIC", pd.Timestamp("2026-11-27T16:00Z"))) is expected


def test_delayed_live_labeled_and_close_clock_not_trade():
    live = q.regular_live(quote("^IXIC", "2026-11-27T15:00Z"), "^IXIC", pd.Timestamp("2026-11-27T16:00Z"))
    assert "지연" in live["kind"]
    snap = q.build_snapshot({"^KS11": frame(("2026-11-25", "2026-11-26", "2026-11-27"))}, {}, pd.Timestamp("2026-11-28T01:00Z"))
    assert "거래소 마감시각" in snap["indices"][0]["selected"]["clock_kind"]


def test_etf_premarket_distinct_from_cash_index_and_missing_not_zero():
    now = pd.Timestamp("2026-11-27T14:00Z")
    row = quote("QQQ", "2026-11-25T21:00Z", price=100, previous=90)
    row.update(preMarketPrice=105, preMarketTime=pd.Timestamp("2026-11-27T13:59Z").timestamp())
    snap = q.build_snapshot({}, {"US": {"QQQ": row}}, now)
    assert not snap["indices"][3]["selected"]
    etf = snap["references"][1]
    assert "나스닥100" in etf["name"] and etf["selected"]["kind"] == "프리마켓"
    assert etf["selected"]["return"] == pytest.approx(.05)
    assert q.display_rows(snap["indices"])[0]["값"] == "미수신"


def test_both_entry_routes_only_call_shared_reader_not_today_calculation():
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8-sig"))
    for page in ("macro", "briefing"):
        node = next(n for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) == f"main_page == '{page}'")
        source = ast.unparse(node)
        assert "render_market_quick_view" in source
        assert "render_today_queue_tab" not in source and "get_all_summary" not in source


def test_two_surfaces_use_same_provider_keys_without_outer_retention(monkeypatch):
    from stock_lab_core import prices, report_live, report_quotes
    batch, kr, quotes = Mock(return_value={}), Mock(return_value=pd.DataFrame()), Mock(return_value={})
    monkeypatch.setattr(prices, "load_price_frames_batch", batch)
    monkeypatch.setattr(report_live, "load_kr_index_history", kr)
    monkeypatch.setattr(report_quotes, "load_report_quotes", quotes)
    q.collect_inputs()
    q.collect_inputs()
    assert batch.call_args_list[0] == batch.call_args_list[1]
    assert quotes.call_args_list[0] == quotes.call_args_list[1]
    assert batch.call_args.args == (q.US_TICKERS, "1mo")


def test_empty_new_session_renders_values_without_creating_decision_state(monkeypatch):
    from streamlit.testing.v1 import AppTest
    def app():
        import streamlit as st
        from stock_lab_core.market_quick_view import render_market_quick_view
        view = st.radio("view", ("charts", "briefing"))
        render_market_quick_view(st, key=view)
    monkeypatch.setattr(q, "collect_inputs", lambda: ({t: frame() for t in q.US_TICKERS}, {}))
    test = AppTest.from_function(app).run(timeout=30)
    assert not test.exception
    assert len(test.dataframe) == 2
    assert any("오늘점검 완료 0회" in cap.value for cap in test.caption)
    test.radio[0].set_value("briefing").run(timeout=30)
    assert not test.exception and len(test.dataframe) == 2
    assert "today_queue_summary_df" not in test.session_state


def test_quote_cache_clock_is_not_assembly_clock():
    row = quote("^GSPC", "2026-11-25T21:00Z")
    row["_retrieved_at"] = "2026-11-27T12:00:00Z"
    snapshot = q.build_snapshot({}, {"US": {"^GSPC": row}, "retrieved_at": "2026-11-27T12:01:00Z"},
                                pd.Timestamp("2026-11-27T12:01Z"))
    assert snapshot["provider_retrieved_at"]["^GSPC"] == row["_retrieved_at"]
    assert snapshot["quote_assembly_at"] != row["_retrieved_at"]
