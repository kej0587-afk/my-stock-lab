"""Offline market-board calculations, provider bounds, and Streamlit workflows."""

import math
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_lab_core import market_board as board


NOW = pd.Timestamp("2026-10-17T12:00:00Z")


def history(values, dates=None):
    dates = dates if dates is not None else pd.date_range("2026-10-15", periods=len(values), freq="D")
    return pd.DataFrame({"Close": values, "Adj Close": [9999] * len(values)}, index=pd.to_datetime(dates))


def all_frames():
    dates = pd.bdate_range("2026-06-01", "2026-10-16")
    return {item.ticker: history([100 + i + offset for i in range(len(dates))], dates)
            for instruments in board.MARKET_UNIVERSES.values()
            for offset, item in enumerate(instruments)}


@pytest.fixture(autouse=True)
def frozen_time(monkeypatch):
    monkeypatch.setattr(board, "_utc_now", lambda: NOW)
    board.load_kr_market_frames.clear()
    yield
    board.load_kr_market_frames.clear()


@pytest.mark.parametrize("market,indices,basket", [("KR", 4, 10), ("US", 4, 11), ("CRYPTO", 0, 6)])
def test_fixed_bounded_universes(market, indices, basket):
    items = board.MARKET_UNIVERSES[market]
    assert len({item.ticker for item in items}) == indices + basket
    assert sum(item.kind == "index" for item in items) == indices
    assert sum(item.kind == "basket" for item in items) == basket


@pytest.mark.parametrize("market", board.MARKET_UNIVERSES)
def test_one_cached_batch_only_for_selected_market(monkeypatch, market):
    from stock_lab_core import prices

    calls = []

    def download(symbols, **kwargs):
        calls.append((symbols, kwargs))
        return pd.concat({ticker: history([100, 110]) for ticker in symbols}, axis=1)

    monkeypatch.setattr(prices.yf, "download", download)
    monkeypatch.setattr(prices, "load_price_df", lambda *args: pytest.fail("individual fallback"))
    prices.load_price_frames_batch.clear()
    try:
        first = board.load_market_frames(market)
        second = board.load_market_frames(market)
        assert len(calls) == 1
        expected = set(board.market_tickers(market))
        assert set(calls[0][0]) == expected
        assert calls[0][1]["period"] == "6mo"
        assert calls[0][1]["auto_adjust"] is False
        if market == "KR":
            assert calls[0][1]["timeout"] == 6.0
            assert calls[0][1]["keepna"] is True
        assert set(first) == set(second) == expected
        first.clear()
        assert board.load_market_frames(market)
        assert len(calls) == 1
    finally:
        prices.load_price_frames_batch.clear()


@pytest.mark.parametrize("market", board.MARKET_UNIVERSES)
def test_provider_failure_returns_missing_without_individual_fallback(monkeypatch, market):
    from stock_lab_core import prices

    def fail(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(prices, "load_price_frames_batch", fail)
    monkeypatch.setattr(prices.yf, "download", fail)
    monkeypatch.setattr(prices, "load_price_df", lambda *args: pytest.fail("individual fallback"))
    assert board.load_market_frames(market) == {}


def test_kr_uses_existing_history_lock_and_never_calls_overseas_batch(monkeypatch):
    from stock_lab_core import prices, yahoo_transport

    lock = SimpleNamespace(active=False)

    class Lock:
        def __enter__(self):
            lock.active = True

        def __exit__(self, *args):
            lock.active = False

    def download(tickers, **kwargs):
        assert lock.active
        assert len(tickers) == 14 and "396500.KS" in tickers
        return pd.concat({ticker: history([100, 110]) for ticker in tickers}, axis=1)

    monkeypatch.setattr(yahoo_transport, "YAHOO_HISTORY_LOCK", Lock())
    monkeypatch.setattr(prices.yf, "download", download)
    monkeypatch.setattr(prices, "load_price_frames_batch", lambda *a: pytest.fail("overseas batch for KR"))
    frames = board.load_market_frames("KR")
    basket = board.build_market_snapshot("KR", frames, now=NOW)
    assert not lock.active
    assert len(frames) == 14
    assert board.breadth_counts(basket.loc[basket.kind == "basket"])["positive"] == 10


@pytest.mark.parametrize("ticker_first", [True, False])
def test_kr_batch_extracts_only_present_symbols_and_keeps_null_latest(monkeypatch, ticker_first):
    from stock_lab_core import prices

    data = pd.concat({"396500.KS": history([100, None]), "139270.KS": history([200, 180])}, axis=1)
    if not ticker_first:
        data.columns = data.columns.swaplevel()
    original = data.copy(deep=True)
    monkeypatch.setattr(prices.yf, "download", lambda *args, **kwargs: data)
    frames = board.load_market_frames("KR")
    assert set(frames) == {"396500.KS", "139270.KS"}
    assert frames["396500.KS"].Close.isna().iloc[-1]
    assert frames["139270.KS"].Close.tolist() == [200, 180]
    pd.testing.assert_frame_equal(data, original)


@pytest.mark.parametrize("data", [None, pd.DataFrame(), history([100, 110]),
    pd.concat({"396500.KS": history([None, None])}, axis=1)])
def test_kr_rejects_missing_flat_ambiguous_or_all_null_batches(monkeypatch, data):
    from stock_lab_core import prices

    calls = []
    monkeypatch.setattr(prices.yf, "download", lambda *a, **kw: calls.append(True) or data)
    monkeypatch.setattr(prices, "load_price_df", lambda *a: pytest.fail("individual fallback"))
    assert board.load_market_frames("KR") == {}
    assert board.load_market_frames("KR") == {}
    assert len(calls) == 1  # failure cooldown also prevents immediate retry storms


@pytest.mark.parametrize("period,base_date,expected", [
    ("1D", "2026-10-15", 20.0),
    ("1W", "2026-10-09", 50.0),
    ("1M", "2026-09-16", 100.0),
    ("3M", "2026-07-16", 200.0),
])
def test_returns_use_actual_raw_closes_and_calendar_targets(period, base_date, expected):
    frame = history([40, 60, 80, 100, 120], ["2026-07-16", "2026-09-16", "2026-10-09", "2026-10-15", "2026-10-16"])
    original = frame.copy(deep=True)
    row = board.build_market_snapshot("US", {"XLK": frame}, period, now=NOW).set_index("ticker").loc["XLK"]
    assert row.return_pct == pytest.approx(expected)
    assert row.close == 120
    assert row.close_date == "2026-10-16"
    assert row.base_date == base_date
    pd.testing.assert_frame_equal(frame, original)


def test_calendar_target_uses_preceding_supplied_session_without_backfilling():
    frame = history([80, 100, 120], ["2026-09-11", "2026-10-08", "2026-10-12"])
    row = board.build_market_snapshot("US", {"XLK": frame}, "1M", now=NOW).set_index("ticker").loc["XLK"]
    assert row.base_date == "2026-09-11"  # calendar target was Saturday, September 12
    assert row.return_pct == pytest.approx(50)
    short = board.build_market_snapshot("US", {"XLK": frame}, "3M", now=NOW).set_index("ticker").loc["XLK"]
    assert math.isnan(short.return_pct)
    assert short.status == "비교 기간 부족"


@pytest.mark.parametrize("market,now,included", [
    ("KR", "2026-10-16T06:44:00Z", False),
    ("KR", "2026-10-16T06:45:00Z", True),
    ("US", "2026-10-16T20:14:00Z", False),
    ("US", "2026-10-16T20:15:00Z", True),
    ("US", "2026-12-16T21:14:00Z", False),
    ("US", "2026-12-16T21:15:00Z", True),
])
def test_local_session_cutoffs_and_us_dst(market, now, included):
    date = now[:10]
    previous = (pd.Timestamp(date) - pd.Timedelta(days=1)).date().isoformat()
    close, removed = board.completed_close_series(history([100, 110], [previous, date]), market, now=now)
    assert close.iloc[-1] == (110 if included else 100)
    assert removed == (0 if included else 1)


def test_kr_and_us_close_dates_remain_separate_at_same_instant():
    now = "2026-10-16T08:00:00Z"
    frames = {"^KS11": history([100, 110]), "^GSPC": history([100, 110])}
    kr = board.build_market_snapshot("KR", frames, now=now).iloc[0]
    us = board.build_market_snapshot("US", frames, now=now).iloc[0]
    assert kr.close_date == "2026-10-16" and kr.return_pct == pytest.approx(10)
    assert us.close_date == "2026-10-15" and math.isnan(us.return_pct)
    assert "미완료 봉 제외" in us.status


def test_crypto_only_uses_completed_utc_days_including_weekends():
    frame = history([100, 110, 121], ["2026-10-16", "2026-10-17", "2026-10-18"])
    close, removed = board.completed_close_series(frame, "CRYPTO", now="2026-10-18T00:00:00Z")
    assert close.index[-1] == pd.Timestamp("2026-10-17")
    assert close.iloc[-1] == 110 and removed == 1


def test_daily_session_labels_are_not_shifted_by_timezone_conversion():
    frame = history([100, 110], pd.date_range("2026-10-15", periods=2, tz="UTC"))
    close, _ = board.completed_close_series(frame, "US", now=NOW)
    assert close.index[-1] == pd.Timestamp("2026-10-16")


@pytest.mark.parametrize("bad_close", [None, float("nan"), 0, -1, float("inf"), "bad"])
def test_bad_latest_close_is_missing_instead_of_stale_zero_return(bad_close):
    frame = history([100, bad_close])
    row = board.build_market_snapshot("US", {"XLK": frame}, now=NOW).set_index("ticker").loc["XLK"]
    assert math.isnan(row.close) and math.isnan(row.return_pct)
    assert row.close_date == "2026-10-16"
    assert row.status == "종가 결측"


def test_missing_comparison_candle_is_not_skipped_or_forward_filled():
    frame = history([100, None, 120], ["2026-10-14", "2026-10-15", "2026-10-16"])
    row = board.build_market_snapshot("US", {"XLK": frame}, now=NOW).set_index("ticker").loc["XLK"]
    assert row.status == "비교 종가 결측"
    assert row.base_date == "2026-10-15" and math.isnan(row.return_pct)


def test_lagging_instruments_do_not_enter_market_breadth():
    frames = {"XLK": history([100, 110]), "XLF": history([100, 90], ["2026-10-14", "2026-10-15"])}
    snapshot = board.build_market_snapshot("US", frames, now=NOW).set_index("ticker")
    assert snapshot.loc["XLK", "return_pct"] == pytest.approx(10)
    assert snapshot.loc["XLF", "status"] == "기준일 지연"
    assert snapshot.loc["XLF", "close_date"] == "2026-10-15"
    assert math.isnan(snapshot.loc["XLF", "return_pct"])


def test_missing_latest_session_does_not_make_older_prices_current():
    frames = {"XLK": history([100, None]), "XLF": history([100, 90], ["2026-10-14", "2026-10-15"])}
    snapshot = board.build_market_snapshot("US", frames, now=NOW).set_index("ticker")
    assert snapshot.loc["XLK", "status"] == "종가 결측"
    assert snapshot.loc["XLF", "status"] == "기준일 지연"
    assert math.isnan(snapshot.loc["XLF", "return_pct"])


def test_empty_short_malformed_and_unsorted_frames_are_safe():
    bad = [None, pd.DataFrame(), pd.DataFrame({"Adj Close": [100]}),
           pd.DataFrame({"Close": [100, 110]}),
           pd.DataFrame({"Close": [100]}, index=["not-a-date"]),
           pd.DataFrame([[100]], columns=pd.MultiIndex.from_tuples([("Close", "XLK")])),
           pd.DataFrame([[100, 110]], columns=["Close", "Close"])]
    for frame in bad:
        close, _ = board.completed_close_series(frame, "US", now=NOW)
        assert close.empty
    row = board.build_market_snapshot("US", {"XLK": history([100])}, now=NOW).set_index("ticker").loc["XLK"]
    assert math.isnan(row.return_pct) and row.status == "비교 기간 부족"
    frame = history([120, 100, 110], ["2026-10-16", "2026-10-15", "2026-10-16"])
    row = board.build_market_snapshot("US", {"XLK": frame}, now=NOW).set_index("ticker").loc["XLK"]
    assert row.return_pct == pytest.approx(10)
    with pytest.raises(ValueError):
        board.build_market_snapshot("US", {}, "YTD", now=NOW)


def test_breadth_counts_positive_negative_neutral_and_missing_separately():
    rows = pd.DataFrame({"return_pct": [2, -1, 0, None, float("inf")]})
    assert board.breadth_counts(rows) == dict(positive=1, negative=1, neutral=1, missing=2)


def test_treemap_equal_leaves_symmetric_clipping_and_actual_hover_values():
    frames = {"XLK": history([100, 250]), "XLF": history([100, 50]), "XLP": history([100, 100])}
    snapshot = board.build_market_snapshot("US", frames, now=NOW)
    basket = snapshot.loc[snapshot.kind == "basket"]
    figure = board.build_treemap(basket, "1D")
    trace = figure.data[0]
    leaves = {node_id: i for i, node_id in enumerate(trace.ids) if node_id in set(basket.ticker)}
    assert len(leaves) == 11
    assert {trace.values[i] for i in leaves.values()} == {1}
    assert trace.marker.cmin == -5 and trace.marker.cmax == 5 and trace.marker.cmid == 0
    assert trace.customdata[leaves["XLK"]][2] == "+150.00%"
    assert trace.customdata[leaves["XLK"]][3] == "2026-10-16"
    assert trace.customdata[leaves["XLK"]][4] == "2026-10-15"
    assert trace.customdata[leaves["XLF"]][2] == "-50.00%"
    assert trace.customdata[leaves["XLC"]][2] == "결측"
    assert trace.marker.colors[leaves["XLC"]] == board.MISSING_COLOR
    assert trace.marker.colors[leaves["XLP"]] != board.MISSING_COLOR
    assert trace.marker.colors[leaves["XLK"]] != trace.marker.colors[leaves["XLF"]]
    assert "customdata[2]" in trace.texttemplate
    for i, node_id in enumerate(trace.ids):
        if node_id.startswith("group:"):
            assert trace.customdata[i][0] == ""


@pytest.mark.parametrize("event,expected", [
    ({"selection": {"points": [{"customdata": ["XLK", "Technology"]}]}}, "XLK"),
    ({"selection": {"points": [{"id": "XLK"}]}}, "XLK"),
    ({"selection": {"points": [{"customdata": ["NVDA"]}]}}, None),
    ({"selection": {"points": [{"id": "group:성장·소비", "customdata": [""]}]}}, None),
    ({"selection": {"points": None}}, None),
    (None, None),
])
def test_plotly_selection_validates_visible_leaf_tickers(event, expected):
    assert board.selected_ticker_from_event(event, {"XLK"}) == expected


class FakeStreamlit:
    def __init__(self, market="US", period="1D", scope=None):
        self.session_state = {"test_market": market, "test_period": period}
        if scope:
            self.session_state["test_scope"] = scope
        self.charts, self.tables, self.captions = [], [], []
        self.event = {"selection": {"points": []}}
        self.column_config = SimpleNamespace(NumberColumn=lambda **kwargs: kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def container(self, **kwargs):
        return self

    def radio(self, label, options, *, key, **kwargs):
        return self.session_state.setdefault(key, options[0])

    def selectbox(self, label, options, *, key, index=0, **kwargs):
        return self.session_state.setdefault(key, options[index] if index is not None else None)

    def plotly_chart(self, figure, **kwargs):
        self.charts.append((figure, kwargs))
        return self.event if kwargs.get("on_select") else None

    def dataframe(self, frame, **kwargs):
        self.tables.append(frame)

    def caption(self, message):
        self.captions.append(message)

    def subheader(self, *args, **kwargs):
        pass

    metric = subheader
    info = subheader
    markdown = subheader


def test_render_injected_frames_skips_all_fetches_and_sorts_missing_last(monkeypatch):
    monkeypatch.setattr(board, "load_market_frames", lambda *args: pytest.fail("fetch with supplied frames"))
    st = FakeStreamlit(scope="섹터 ETF")
    frames = {"XLK": history([100, 110]), "XLF": history([100, 90]), "XLP": history([100, 100])}
    assert board.render_market_board(st, key="test", frames=frames) is None
    assert st.tables[-1]["티커"].tolist()[:3] == ["XLK", "XLP", "XLF"]
    assert st.tables[-1]["수익률(%)"].tail(8).isna().all()
    assert any("상승 1 · 하락 1 · 보합 1 · 결측 8" in caption for caption in st.captions)
    st.session_state["test_order"] = "하락순"
    board.render_market_board(st, key="test", frames=frames)
    assert st.tables[-1]["티커"].tolist()[:3] == ["XLF", "XLP", "XLK"]
    assert board.render_market_board(FakeStreamlit(), key="test", frames={}) is None


def test_kr_first_screen_loads_sector_etfs_once_without_overseas_fetch(monkeypatch):
    from stock_lab_core import prices

    calls = []

    def download(tickers, **kwargs):
        calls.append(tuple(tickers))
        return pd.concat({ticker: history([100, 110]) for ticker in tickers}, axis=1)

    monkeypatch.setattr(prices.yf, "download", download)
    monkeypatch.setattr(prices, "load_price_frames_batch", lambda *a: pytest.fail("overseas fetch"))
    st = FakeStreamlit(market="KR", scope="섹터 ETF")
    assert board.render_market_board(st, key="test") is None
    assert st.tables[-1]["수익률(%)"].notna().sum() == 10
    assert any("상승 10 · 하락 0 · 보합 0 · 결측 0" in caption for caption in st.captions)
    assert board.render_market_board(st, key="test") is None
    assert calls == [board.market_tickers("KR")]


def test_render_loads_only_selected_market_and_filter_controls_tree_and_table(monkeypatch):
    calls = []
    monkeypatch.setattr(board, "load_market_frames", lambda market: calls.append(market) or all_frames())
    st = FakeStreamlit(market="US", scope="섹터 ETF")
    st.session_state["test_US_group"] = "방어"
    board.render_market_board(st, key="test")
    assert calls == ["US"]
    assert set(st.tables[-1]["티커"]) == {"XLV", "XLP", "XLU"}
    leaves = {node_id for node_id in st.charts[-1][0].data[0].ids if not node_id.startswith("group:")}
    assert leaves == {"XLV", "XLP", "XLU"}
    assert st.charts[-1][1]["selection_mode"] == "points"


def test_render_chart_and_symbol_events_return_once_and_keep_detail(monkeypatch):
    monkeypatch.setattr(board, "load_market_frames", lambda *args: pytest.fail("fetch"))
    st = FakeStreamlit(scope="섹터 ETF")
    st.event = {"selection": {"points": [{"customdata": ["XLK"]}]}}
    frames = all_frames()
    assert board.render_market_board(st, key="test", frames=frames) == "XLK"
    assert board.render_market_board(st, key="test", frames=frames) is None
    assert st.session_state["test_US_detail"] == "XLK"
    st.session_state["test_US_전체_symbol"] = "XLF"
    assert board.render_market_board(st, key="test", frames=frames) == "XLF"
    assert board.render_market_board(st, key="test", frames=frames) is None
    st.session_state["test_market"] = "KR"
    assert board.render_market_board(st, key="test", frames=frames) is None


def test_apptest_markets_periods_group_sort_and_symbol_fallback():
    from streamlit.testing.v1 import AppTest

    source = '''
import pandas as pd
import streamlit as st
from stock_lab_core import market_board as board
dates = pd.bdate_range("2026-06-01", "2026-10-16")
frames = {item.ticker: pd.DataFrame({"Close": [100 + i + j for i in range(len(dates))]}, index=dates)
          for universe in board.MARKET_UNIVERSES.values() for j, item in enumerate(universe)}
st.session_state["result"] = board.render_market_board(st, key="smoke", frames=frames)
'''
    app = AppTest.from_string(source, default_timeout=20).run()
    assert not app.exception
    assert app.radio(key="smoke_scope").value == "대표 종목"
    assert len(app.dataframe[0].value) == 36
    app.radio(key="smoke_scope").set_value("섹터 ETF").run()
    assert len(app.metric) == 4 and len(app.dataframe[0].value) == 10
    app.radio(key="smoke_market").set_value("US").run()
    assert not app.exception and len(app.dataframe[0].value) == 11
    app.radio(key="smoke_period").set_value("3M").run()
    assert not app.exception
    assert app.dataframe[0].value["비교일"].eq("2026-07-16").all()
    app.selectbox(key="smoke_US_group").select("방어").run()
    assert not app.exception and len(app.dataframe[0].value) == 3
    app.radio(key="smoke_order").set_value("하락순").run()
    assert app.dataframe[0].value["수익률(%)"].is_monotonic_increasing
    app.selectbox(key="smoke_US_방어_symbol").select("XLV").run()
    assert not app.exception and app.session_state["result"] == "XLV"
    app.run()
    assert not app.exception and app.session_state["result"] is None
    app.radio(key="smoke_market").set_value("CRYPTO").run()
    assert not app.exception and len(app.dataframe[0].value) == 6
