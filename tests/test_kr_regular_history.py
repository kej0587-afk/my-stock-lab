from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.kr_regular_history import align_regular_frames, regular_close_frame
from stock_lab_core.report_evidence import price_observation
from stock_lab_core.report_quotes import repair_kr_report_closes


def payload():
    return {"items": [
        dict(tradingDateKst="2026-11-18", regularMarketClosingPrice="1144000", closingPrice="1164000", basePrice="1098000", regularMarketChangePrice="46000"),
        dict(tradingDateKst="2026-11-19", regularMarketClosingPrice="1183000", closingPrice="1190000", basePrice="1144000", regularMarketChangePrice="39000"),
        dict(tradingDateKst="2026-11-20", regularMarketClosingPrice="1097000", closingPrice="1100000", basePrice="1183000", regularMarketChangePrice="-86000"),
    ]}


def schedule():
    return pd.DataFrame({"market_close": pd.to_datetime(["2026-11-18T06:30Z", "2026-11-19T07:30Z", "2026-11-20T06:30Z"])},
                        index=pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20"]))


def test_regular_close_not_aftermarket_or_nxt():
    source = payload()
    before = deepcopy(source)
    frame = regular_close_frame(source, "2026-11-20T09:00+09:00", schedule=schedule())
    obs = price_observation(frame, "000660.KS", pd.Timestamp("2026-11-20T09:00+09:00"))
    assert obs["price"] == 1183000
    assert obs["return"] == pytest.approx(1183000 / 1144000 - 1)
    assert obs["date"] == "2026-11-19"
    assert source == before
    assert list(frame.columns) == ["Close", "RegularBase"]


@pytest.mark.parametrize("source", [None, [], {}, {"items": None}, {"items": "invalid"}])
def test_missing_payload_has_no_invented_closes(source):
    frame = regular_close_frame(source, "2026-11-20T09:00+09:00", schedule=schedule())
    assert frame.empty
    assert frame.attrs["basis_reason"]


def test_special_session_not_confirmed_at_normal_close():
    frame = regular_close_frame(payload(), "2026-11-19T16:00+09:00", schedule=schedule())
    assert str(frame.index[-1].date()) == "2026-11-18"
    frame = regular_close_frame(payload(), "2026-11-19T16:45+09:00", schedule=schedule())
    assert str(frame.index[-1].date()) == "2026-11-19"


@pytest.mark.parametrize("value", [None, True, "nan", "inf", "-1"])
def test_missing_regular_field_never_uses_final_trade(value):
    source = payload()
    source["items"][1]["regularMarketClosingPrice"] = value
    frame = regular_close_frame(source, "2026-11-20T09:00+09:00", schedule=schedule())
    obs = price_observation(frame, "000660.KS", pd.Timestamp("2026-11-20T09:00+09:00"))
    assert obs["return"] is None


def test_provider_basis_disagreement_never_becomes_daily_return():
    source = payload()
    source["items"][1].update(basePrice="1164000", regularMarketChangePrice="19000")
    frame = regular_close_frame(source, "2026-11-20T09:00+09:00", schedule=schedule())
    assert price_observation(frame, "000660.KS", pd.Timestamp("2026-11-20T09:00+09:00"))["return"] is None


def test_close_quote_does_not_repair_regular_series_with_final_trade():
    now = pd.Timestamp("2026-11-19T20:30+09:00")
    frame = regular_close_frame(payload(), now, schedule=schedule())
    result = repair_kr_report_closes({"000660.KS": frame}, {}, now, tickers=("000660.KS",))
    pd.testing.assert_frame_equal(result["000660.KS"], frame)
    assert "report_close_pending_date" not in result["000660.KS"].attrs


def test_aligned_frames_are_reused_without_new_fetch():
    now = pd.Timestamp("2026-11-20T09:00+09:00")
    frame = regular_close_frame(payload(), now, schedule=schedule())
    def no_fetch(_):
        pytest.fail("already aligned")
    out = align_regular_frames({"000660.KS": frame}, ("000660.KS",), now, loader=no_fetch)
    pd.testing.assert_frame_equal(out["000660.KS"], frame)


def test_parallel_load_keeps_request_measurement_context():
    from contextvars import ContextVar
    trace = ContextVar("regular_history_test_trace", default=None)
    token = trace.set("active_measurement")
    calls = []
    def load(ticker):
        calls.append((ticker, trace.get()))
        return payload()
    try:
        align_regular_frames({}, ("000660.KS", "005930.KS"), "2026-11-20T09:00+09:00", loader=load)
    finally:
        trace.reset(token)
    assert sorted(calls) == [("000660.KS", "active_measurement"), ("005930.KS", "active_measurement")]
