from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from threading import Thread
from time import monotonic, sleep
from types import SimpleNamespace
from xml.etree import ElementTree

import pandas as pd
import pytest
import requests

from stock_lab_core import kr_flow_history as history
from stock_lab_core import money_flow as flow


XML = """<?xml version="1.0" encoding="EUC-KR"?>
<protocol><chartdata>
<item data="20261020|110|120|100|115|45678"/>
<item data="20261019|100|110|90|105|12345"/>
<item data="20241019|90|100|80|95|10000"/>
</chartdata></protocol>"""


def response(text=XML):
    return SimpleNamespace(text=text, raise_for_status=lambda: None)


def test_same_naver_rows_as_pykrx_parser_with_explicit_bounds():
    parsed = history.parse_history(XML, pd.Timestamp("2025-10-20"), pd.Timestamp("2026-10-20"))
    rows = [node.get("data").split("|") for node in ElementTree.fromstring(XML).iter("item")]
    reference = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    reference.index = pd.to_datetime(reference.pop("Date"), format="%Y%m%d")
    reference = reference.astype("int64").sort_index().loc["2025-10-20":"2026-10-20"]
    pd.testing.assert_frame_equal(parsed, reference)
    assert parsed["Volume"].tolist() == [12345, 45678]


@pytest.mark.parametrize("ticker,code", [("005930.KS", "005930"), ("098120.KQ", "098120"),
                                       ("0167a0.ks", "0167A0")])
def test_https_timeout_same_period_and_alphanumeric_codes(ticker, code):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response()

    reader = history.KrFlowHistoryReader(request=get)
    result = reader.read(ticker, now="2026-10-20")
    assert len(result) == 2
    url, kwargs = calls[0]
    assert url.startswith("https://")
    assert kwargs["timeout"] == (2, 4)
    assert kwargs["params"] == {"symbol": code, "timeframe": "day", "count": 367,
                                "requestType": "0"}


def test_transport_outage_pauses_batch_and_recovers():
    now, calls = [0], []

    def get(*args, **kwargs):
        calls.append(kwargs)
        if now[0] == 0:
            raise requests.ReadTimeout("stalled")
        return response()

    reader = history.KrFlowHistoryReader(request=get, clock=lambda: now[0])
    for i in range(300):
        assert reader.read(f"{i:06d}.KS").empty
    assert len(calls) == 3
    now[0] = 61
    assert not reader.read("005930.KS", now="2026-10-20").empty
    assert len(calls) == 4


def test_empty_valid_ticker_response_does_not_disable_other_tickers():
    calls = []

    def get(*args, **kwargs):
        calls.append(kwargs)
        return response("<protocol/>" if len(calls) <= 4 else XML)

    reader = history.KrFlowHistoryReader(request=get)
    for i in range(4):
        assert reader.read(f"{i:06d}.KS").empty
    assert not reader.read("005930.KS", now="2026-10-20").empty


def test_invalid_rows_are_not_forward_filled_into_prices():
    xml = """<protocol>
    <item data="20261019|100|bad|90|105|12345"/>
    <item data="bad-date|110|120|100|115|45678"/>
    <item data="20261020|110|120|100|115|45678"/>
    </protocol>"""
    result = history.parse_history(xml, "2025-10-20", "2026-10-20")
    assert len(result) == 1
    assert result.index[0] == pd.Timestamp("2026-10-20")


def test_live_socket_stall_finishes_workers_without_background_futures(monkeypatch):
    class SilentHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            sleep(0.3)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SilentHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(history, "_URL", f"http://127.0.0.1:{server.server_port}/")
    monkeypatch.setattr(history, "_TIMEOUT", (0.05, 0.05))
    reader = history.KrFlowHistoryReader()
    started = monotonic()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(reader.read, [f"{i:06d}.KS" for i in range(100)]))
        assert all(row.empty for row in rows)
        assert monotonic() - started < 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_reused_history_keeps_metrics_identical_to_old_ohlc_shape():
    close = pd.Series(range(100, 365), dtype=float)
    old = pd.DataFrame({"Close": close, "High": close + 2, "Low": close - 2, "Volume": close * 50})
    old.index = pd.bdate_range("2025-10-01", periods=len(old))
    new = old.assign(Open=old["Close"] - 1)
    assert flow._compute_ticker_metrics(new) == flow._compute_ticker_metrics(old)


def test_decorated_aggregate_tables_retry_transport_failures_after_short_ttl(monkeypatch):
    from streamlit.runtime.caching import cache_utils

    clock, calls = [0], []
    monkeypatch.setattr(cache_utils, "TTLCACHE_TIMER", lambda: clock[0])
    # Separate cache namespace lets the real Streamlit TTLs use a controlled clock.
    spec = importlib.util.spec_from_file_location("flow_recovery_test", flow.__file__)
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    universe = [{"ticker": "005930.KS", "name": "Samsung", "테마": "Test",
                 "하위테마": "Test", "구분": "Test", "섹터": "Test"}]
    monkeypatch.setattr(isolated, "build_money_flow_universe_with_naver_rankings", lambda: universe)
    monkeypatch.setattr(isolated, "IMAGE_THEME_UNIVERSE", universe)
    monkeypatch.setattr(isolated, "download_money_flow_prices", lambda _: pd.DataFrame())
    close = pd.Series(range(100, 365), dtype=float)
    frame = pd.DataFrame({"Close": close, "High": close + 2, "Low": close - 2, "Volume": close * 50})
    frame.index = pd.bdate_range("2025-10-01", periods=len(frame))

    def fetch(*args):
        calls.append(clock[0])
        return history._unavailable("ReadTimeout") if clock[0] < 15 else frame

    monkeypatch.setattr(isolated, "get_money_flow_ohlc", fetch)
    aggregates = [(isolated.calculate_money_flow_df, ()),
                  (isolated.calculate_image_theme_flow_df, ("",))]
    try:
        for calculate, args in aggregates:
            calculate.clear()
            assert calculate(*args).attrs["history_failures"] == ["005930.KS"]
            assert calculate(*args).attrs["history_failures"] == ["005930.KS"]
        assert calls == [0, 0]
        clock[0] = 16
        for calculate, args in aggregates:
            recovered = calculate(*args)
            assert "history_failures" not in recovered.attrs
            assert recovered["현재가"].notna().all()
        assert calls == [0, 0, 16, 16]
        clock[0] = 40
        for calculate, args in aggregates:
            assert not calculate(*args).empty
        assert calls == [0, 0, 16, 16]
    finally:
        for calculate, _ in aggregates:
            calculate.clear()
