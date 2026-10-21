from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident

import pandas as pd
import pytest
import requests

from stock_lab_core import kr_flow_history as history
from stock_lab_core import money_flow as flow
from stock_lab_core.performance import submit_with_context
from tests.test_kr_flow_history import response


def test_connections_are_worker_local_closed_and_not_reused_between_batches(monkeypatch):
    sessions = []
    barrier = Barrier(4)

    class Session:
        def __init__(self):
            self.owner = get_ident()
            self.calls = []
            self.closed = False
            self.cookies = requests.cookies.RequestsCookieJar()
            sessions.append(self)

        def get(self, *args, **kwargs):
            assert get_ident() == self.owner
            assert not self.closed and not self.cookies
            self.cookies.set("server_cookie", "not_carried_to_next_ticker")
            self.calls.append((args, kwargs))
            return response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(history.requests, "Session", Session)
    reader = history.KrFlowHistoryReader()

    def worker():
        barrier.wait(timeout=5)
        return [reader.read(ticker, now="2026-10-20") for ticker in ("005930.KS", "000660.KS")]

    for batch in range(2):
        with history.reuse_kr_history_connections():
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [submit_with_context(pool, worker) for _ in range(4)]
                frames = [f.result() for f in results]
                assert len(sessions) == (batch + 1) * 4
                assert all(not s.closed for s in sessions[-4:])
        assert all(s.closed for s in sessions)
        assert all(len(s.calls) == 2 for s in sessions)
        for pair in frames:
            pd.testing.assert_frame_equal(pair[0], pair[1], check_exact=True)
    assert history._connections.get() is None


def test_nested_scope_and_exception_cleanup(monkeypatch):
    closed = []

    class Session:
        cookies = requests.cookies.RequestsCookieJar()

        def get(self, *args, **kwargs):
            return response()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(history.requests, "Session", Session)
    with pytest.raises(RuntimeError):
        with history.reuse_kr_history_connections():
            with history.reuse_kr_history_connections():
                history.KrFlowHistoryReader().read("005930.KS")
            assert not closed
            raise RuntimeError("batch failed")
    assert closed == [True]
    assert history._connections.get() is None


def test_batch_output_and_requests_match_unpooled_provider(monkeypatch):
    from tests.fixtures_price import make_price_df

    calls, sessions = [], []
    frame = make_price_df()
    frame.index = pd.bdate_range(end="2026-10-20", periods=len(frame))
    xml = "<protocol>" + "".join(
        f'<item data="{date:%Y%m%d}|{row.Open}|{row.High}|{row.Low}|{row.Close}|{row.Volume}"/>'
        for date, row in frame.iterrows()
    ) + "</protocol>"

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return response(xml)

    class Session:
        cookies = requests.cookies.RequestsCookieJar()

        def __init__(self):
            sessions.append(self)

        get = staticmethod(request)
        close = lambda self: None

    monkeypatch.setattr(history.requests, "Session", Session)
    # Real metric calculation sees the same dated rows and metadata.
    reader = history.KrFlowHistoryReader()
    monkeypatch.setattr(flow, "load_kr_flow_history", lambda ticker: reader.read(ticker, now="2026-10-20"))
    universe = [{"ticker": t} for t in ("005930.KS", "000660.KS", "005930.KS")]
    actual = flow._load_universe_metrics(pd.DataFrame(), universe)
    actual_calls = sorted(calls, key=lambda c: c[1]["params"]["symbol"])
    calls.clear()
    baseline = history.KrFlowHistoryReader(request=request)
    expected = {}
    for t in dict.fromkeys(row["ticker"] for row in universe):
        frame = baseline.read(t, now="2026-10-20")
        expected[t] = flow._compute_ticker_metrics(frame) if len(frame) >= 20 else None
    assert actual == expected
    assert all(value is not None for value in actual.values())
    assert actual_calls == sorted(calls, key=lambda c: c[1]["params"]["symbol"])
    assert sessions
