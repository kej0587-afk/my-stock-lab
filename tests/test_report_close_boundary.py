"""Report-only close boundaries; trading decisions and caller frames stay intact."""

from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_evidence import price_observation
from stock_lab_core.report_quotes import extended_quote_observation, repair_kr_report_closes


def history(dates, closes):
    return pd.DataFrame({c: closes for c in ("Open", "High", "Low", "Close")},
                        index=pd.to_datetime(dates))


@pytest.mark.parametrize("clock,expected", [("15:29", "2026-10-20"), ("15:30", "2026-10-21"),
                                            ("15:36", "2026-10-21"), ("15:40", "2026-10-21")])
@pytest.mark.parametrize("ticker", ["^KS11", "^KQ11", "379810.KS", "098120.KQ"])
def test_kr_report_clock_matches_regular_close(clock, expected, ticker):
    frame = history(["2026-10-19", "2026-10-20", "2026-10-21"], [100, 96, 99])
    now = datetime.fromisoformat(f"2026-10-21T{clock}:00+09:00")
    assert price_observation(frame, ticker, now)["date"] == expected


@pytest.mark.parametrize("minute", [1, 5, 14, 15, 60])
def test_aftermarket_starts_at_1600_not_1615(minute):
    close = pd.Timestamp("2026-10-20T16:00:00-04:00")
    now = close + pd.Timedelta(minutes=minute)
    quote = {"symbol": "RAM", "regularMarketPrice": 100, "regularMarketPreviousClose": 102,
             "regularMarketTime": close.timestamp(), "postMarketPrice": 103,
             "postMarketTime": (now - pd.Timedelta(seconds=15)).timestamp()}
    obs = extended_quote_observation(quote, "RAM", now)
    assert obs["kind"] == "애프터마켓"
    assert obs["previous_date"] == "2026-10-20"
    assert obs["return"] == pytest.approx(.03)


def test_1536_context_uses_today_kr_close_and_previous_us_close():
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    kr = history(["2026-10-19", "2026-10-20", "2026-10-21"], [100, 96, 99])
    us = history(["2026-10-19", "2026-10-20"], [100, 101])
    frames = {**{t: kr for t in ("^KS11", "^KQ11", "379810.KS", "396500.KS")},
              **{t: us for t in ("^GSPC", "^IXIC", "^DJI", "RAM")}}
    rows = [{"티커": "379810.KS", "종목명": "나스닥", "보유량": 1, "현재비중": 75,
             "게이트상태": "방어우선", "최종읽기": "추가매수 보류"}]
    before = deepcopy(rows)
    ctx = collect_report_context(rows, now=now, price_frames=frames, quote_data={},
                                 economic_releases=[], calendar={"events": [], "sources": []})
    assert ctx["sessions"] == {"KR": "2026-10-21", "US": "2026-10-20"}
    assert ctx["prices"]["^KS11"]["return"] == pytest.approx(99 / 96 - 1)
    assert ctx["news_sessions"]["KR"]["date"] == "2026-10-21"
    from stock_lab_core.market_memo import build_auto_market_memo
    report = build_auto_market_memo(summary_rows=rows, report_context=ctx, now=now)
    assert "한국 2026-10-21" in report and "+3.12%" in report
    assert rows == before


def test_missing_today_history_is_not_relabelled():
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    old = history(["2026-10-19", "2026-10-20"], [100, 96])
    assert price_observation(old, "^KS11", now)["date"] == "2026-10-20"


def close_payload():
    return {"time": pd.Timestamp("2026-10-21T15:35:45+09:00").timestamp() * 1000,
            "areas": [{"name": "SERVICE_ITEM", "datas": [
                {"cd": "379810", "ms": "CLOSE", "nv": 99, "cv": 3, "pcv": 96,
                 "rf": "2", "ov": 97, "hv": 100, "lv": 95, "aq": 1234}]}]}


def test_verified_close_replaces_intraday_cache_without_mutating_trading_frames():
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    old = history(["2026-10-20", "2026-10-21"], [96, 97])
    frames = {"^KS11": old, "379810.KS": old}
    result = repair_kr_report_closes(frames, close_payload(), now, tickers=("379810.KS",))
    assert result["379810.KS"].Close.iloc[-1] == 99
    assert result["379810.KS"].Volume.iloc[-1] == 1234
    assert "CLOSE" in result["379810.KS"].attrs["source"]
    assert frames["379810.KS"].Close.iloc[-1] == 97
    pd.testing.assert_frame_equal(result["^KS11"], old)


@pytest.mark.parametrize("change", [{"ms": "OPEN"}, {"pcv": 960}, {"nv": float("nan")},
                                    {"hv": 90}, {"rf": "?"}, {"cv": 30}])
def test_invalid_close_does_not_replace_cached_frame(change):
    payload = close_payload()
    payload["areas"][0]["datas"][0].update(change)
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    old = history(["2026-10-20", "2026-10-21"], [96, 97])
    result = repair_kr_report_closes({"^KS11": old, "379810.KS": old}, payload, now, tickers=("379810.KS",))
    pd.testing.assert_frame_equal(result["379810.KS"], old)


@pytest.mark.parametrize("clock", ["15:29", "15:34", "15:40"])
def test_open_future_or_old_close_poll_cannot_repair(clock):
    now = datetime.fromisoformat(f"2026-10-21T{clock}:00+09:00")
    old = history(["2026-10-20", "2026-10-21"], [96, 97])
    result = repair_kr_report_closes({"^KS11": old, "379810.KS": old}, close_payload(), now, tickers=("379810.KS",))
    pd.testing.assert_frame_equal(result["379810.KS"], old)


def test_quote_poll_clock_does_not_invent_a_holiday_session():
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    old = history(["2026-10-19", "2026-10-20"], [100, 96])
    result = repair_kr_report_closes({"^KS11": old, "379810.KS": old}, close_payload(), now, tickers=("379810.KS",))
    pd.testing.assert_frame_equal(result["379810.KS"], old)


def test_aftermarket_rejects_unfinished_1559_regular_price():
    now = pd.Timestamp("2026-10-20T16:05:00-04:00")
    quote = {"symbol": "RAM", "regularMarketPrice": 100, "regularMarketPreviousClose": 102,
             "regularMarketTime": pd.Timestamp("2026-10-20T15:59:00-04:00").timestamp(),
             "postMarketPrice": 103, "postMarketTime": now.timestamp()}
    assert not extended_quote_observation(quote, "RAM", now)


@pytest.mark.parametrize("payload", [{}, {"time": 0}, None])
def test_unverified_intraday_cache_cannot_become_confirmed_close(payload):
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    old = history(["2026-10-19", "2026-10-20", "2026-10-21"], [100, 96, 97])
    result = repair_kr_report_closes({"^KS11": old, "379810.KS": old}, payload, now, tickers=("379810.KS",))
    for ticker in result:
        assert price_observation(result[ticker], ticker, now)["date"] == "2026-10-20"
        assert result[ticker].attrs["report_close_pending_date"] == "2026-10-21"
    assert not old.attrs


def test_current_index_cannot_supply_missing_symbol_trading_date():
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    index = history(["2026-10-20", "2026-10-21"], [96, 99])
    old = history(["2026-10-19", "2026-10-20"], [100, 96])
    payload = close_payload()
    payload["areas"][0]["datas"][0].update(nv=96, cv=0, rf="3")
    result = repair_kr_report_closes({"^KS11": index, "379810.KS": old}, payload, now, tickers=("379810.KS",))
    pd.testing.assert_frame_equal(result["379810.KS"], old)


def test_closed_poll_allows_small_server_clock_skew_not_future_session():
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    old = history(["2026-10-20", "2026-10-21"], [96, 97])
    payload = close_payload()
    payload["time"] = (pd.Timestamp(now) + pd.Timedelta(seconds=2)).timestamp() * 1000
    result = repair_kr_report_closes({"379810.KS": old}, payload, now, tickers=("379810.KS",))
    assert price_observation(result["379810.KS"], "379810.KS", now)["date"] == "2026-10-21"


def test_unquoted_flow_member_stays_pending_even_when_index_is_current():
    now = datetime.fromisoformat("2026-10-21T15:36:00+09:00")
    old = history(["2026-10-19", "2026-10-20", "2026-10-21"], [100, 96, 97])
    result = repair_kr_report_closes({"005930.KS": old}, close_payload(), now, tickers=("379810.KS",))
    assert price_observation(result["005930.KS"], "005930.KS", now)["date"] == "2026-10-20"
