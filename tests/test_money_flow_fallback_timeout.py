import json
from inspect import unwrap

import pandas as pd
import pytest
import requests

from stock_lab_core import money_flow as flow
from stock_lab_core.performance import PerformanceTrace


def payload():
    values = {"open": [90, 101, 102], "high": [102, 104, 106], "low": [89, 99, 101],
              "close": [100, 102, 104], "volume": [1000, 1100, 1200]}
    return {"chart": {"result": [{"timestamp": [1759795200, 1759881600, 1759968000],
                                "indicators": {"quote": [values],
                                               "adjclose": [{"adjclose": [95, 97, 99]}]}}]}}


class Reply:
    def __init__(self, *, fail=False, drip=False):
        self.fail, self.drip, self.closed = fail, drip, False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def raise_for_status(self):
        if self.fail:
            raise requests.HTTPError("controlled failure")

    def json(self):
        return payload()

    def iter_content(self, chunk_size):
        yield json.dumps(payload()).encode()


@pytest.mark.parametrize("ticker,symbol", [("4062.T", "4062.T"), ("6787.T", "6787.T"),
                                           ("NVDA", "NVDA"), ("US10YT", "^TNX")])
def test_bounded_fallback_matches_installed_fdr_raw_prices(monkeypatch, ticker, symbol):
    fdr = pytest.importorskip("FinanceDataReader")
    calls, replies = [], []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        reply = Reply()
        replies.append(reply)
        return reply

    monkeypatch.setattr(requests, "get", request)
    monkeypatch.setattr(flow, "_FDR_AVAILABLE", True)
    start = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    fdr_symbol = f"TSE:{ticker[:-2]}" if ticker.endswith(".T") else ticker
    expected = fdr.DataReader(fdr_symbol, start)[["Close", "High", "Low", "Volume"]]
    with PerformanceTrace() as trace:
        actual = unwrap(flow._fetch_fdr_ohlc)(ticker)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert symbol.replace("^", "%5E") in calls[-1][0]
    assert calls[-1][1]["timeout"] == (2, 4)
    assert calls[-1][1]["stream"] is True
    assert calls[-1][1]["params"]["includeAdjustedClose"] == "true"
    assert replies[-1].closed
    assert any(row["name"] == "flow_overseas_fallback" for row in trace.report()["functions"])


@pytest.mark.parametrize("kind", ["timeout", "http_error", "slow_body"])
def test_fallback_failures_are_bounded_closed_and_marked_for_retry(monkeypatch, kind):
    monkeypatch.setattr(flow, "_FDR_AVAILABLE", True)
    clock = [0]
    reply = Reply(fail=kind == "http_error")

    def body(chunk_size):
        clock[0] = 7
        yield b" "

    def request(*args, **kwargs):
        if kind == "timeout":
            raise requests.ReadTimeout("controlled failure")
        return reply

    if kind == "slow_body":
        reply.iter_content = body
    monkeypatch.setattr(requests, "get", request)
    monkeypatch.setattr(flow.time, "monotonic", lambda: clock[0])
    frame = unwrap(flow._fetch_fdr_ohlc)("4062.T")
    assert frame.empty
    assert frame.attrs["transport_error"] == ("HTTPError" if kind == "http_error" else "ReadTimeout")
    assert reply.closed or kind == "timeout"


def test_stream_body_limits_do_not_wait_for_the_entire_response():
    from stock_lab_core.http_body import read_response_body

    class Raw:
        def read1(self, size, decode_content):
            return b"too big"

    reply = Reply()
    reply.raw = Raw()
    with pytest.raises(ValueError, match="size limit"):
        read_response_body(reply, 6, lambda: 0, max_bytes=4)
