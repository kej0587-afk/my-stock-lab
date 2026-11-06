"""Transport-only parity, bounded lifetime and real HTTP keep-alive coverage."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier, Thread
from unittest.mock import Mock
import urllib.error
import urllib.request

import pytest
import requests

from stock_lab_core import prices, yahoo_chart_connections as transport
from stock_lab_core.performance import PerformanceTrace, submit_with_context


def request():
    return urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/TEST?interval=1m&range=1d&includePrePost=true", headers=prices._YQ_HEADERS)


def test_app_scope_supports_previous_price_module_during_hot_reload():
    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    summary = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_all_summary")
    expressions = [item.context_expr for n in ast.walk(summary) if isinstance(n, ast.With) for item in n.items]
    expression = next(n for n in expressions if "reuse_yahoo_chart_connections" in ast.unparse(n))
    compiled = compile(ast.Expression(expression), "app.py", "eval")
    with eval(compiled, {"price_loader": SimpleNamespace(), "nullcontext": nullcontext}):
        pass
    scope = Mock(return_value=nullcontext())
    with eval(compiled, {"price_loader": SimpleNamespace(reuse_yahoo_chart_connections=scope), "nullcontext": nullcontext}):
        pass
    scope.assert_called_once_with()


def response(body, status=200):
    return Mock(content=body, status_code=status, reason="Too Many Requests" if status == 429 else "OK", headers={})


def test_unscoped_keeps_original_opener(monkeypatch):
    opener = Mock(return_value=object())
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    req = request()
    assert transport.open_yahoo_chart(req, timeout=6) is opener.return_value
    opener.assert_called_once_with(req, timeout=6)


def test_connection_scope_is_not_a_response_cache(monkeypatch):
    session = Mock()
    session.get.side_effect = [response(b"first"), response(b"second")]
    factory = Mock(return_value=session)
    monkeypatch.setattr(transport.requests, "Session", factory)
    with PerformanceTrace() as trace, transport.reuse_yahoo_chart_connections():
        with transport.open_yahoo_chart(request(), timeout=6) as first:
            assert first.read() == b"first"
        with transport.reuse_yahoo_chart_connections():
            with transport.open_yahoo_chart(request(), timeout=6) as second:
                assert second.read() == b"second"
        session.close.assert_not_called()
    assert factory.call_count == 1
    assert session.cookies.clear.call_count == session.get.call_count == 2
    session.close.assert_called_once()
    for call in session.get.call_args_list:
        assert call.args == (request().full_url,)
        assert call.kwargs == {"headers": {**dict(request().header_items()), "Accept-Encoding": "identity"}, "timeout": 6, "stream": True}
    assert trace.report()["transport_events"] == {
        "yahoo_chart.connection_session_created": 1, "yahoo_chart.connection_session_reused": 1,
    }
    assert transport._pool.get() is None


@pytest.mark.parametrize("outcome", ["success", "empty", "bad_json", "timeout", "429", "401", "500"])
def test_scoped_chart_return_and_request_sequence_match_unscoped(monkeypatch, outcome):
    row = {"meta": {"regularMarketTime": 123, "symbol": "TEST"}, "indicators": {"quote": [{"close": [99.0]}]}}
    body = json.dumps({"chart": {"result": [row] if outcome == "success" else []}}).encode()
    if outcome == "bad_json":
        body = b"{bad-json"
    status = int(outcome) if outcome.isdigit() else 200
    session = Mock()
    session.get.return_value = response(body, status)
    effect = None
    if outcome == "timeout":
        session.get.side_effect = requests.exceptions.Timeout("timed out")
        effect = urllib.error.URLError(TimeoutError("timed out"))
    elif status >= 400:
        effect = urllib.error.HTTPError(request().full_url, status, session.get.return_value.reason, {}, None)
    original_response = Mock()
    original_response.__enter__ = Mock(return_value=original_response)
    original_response.__exit__ = Mock(return_value=False)
    original_response.read.return_value = body
    opener = Mock(return_value=original_response, side_effect=effect)
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    monkeypatch.setattr(transport.requests, "Session", lambda: session)
    monkeypatch.setattr(prices, "_last_candle_close", lambda result: 99.)
    with PerformanceTrace() as before:
        expected = prices._fetch_yahoo_chart("TEST", "1m", "1d")
    with PerformanceTrace() as after, transport.reuse_yahoo_chart_connections():
        actual = prices._fetch_yahoo_chart("TEST", "1m", "1d")
    assert actual == expected
    assert session.get.call_count == opener.call_count
    assert [c.args[0] for c in session.get.call_args_list] == [c.args[0].full_url for c in opener.call_args_list]
    events = {k: v for k, v in after.report()["transport_events"].items() if "connection_session" not in k}
    assert events == before.report()["transport_events"]


def test_worker_sessions_are_private_and_closed_on_failure(monkeypatch):
    sessions = []
    def factory():
        session = Mock()
        session.get.return_value = response(b"ok")
        sessions.append(session)
        return session
    monkeypatch.setattr(transport.requests, "Session", factory)
    barrier = Barrier(2)
    def work():
        for _ in range(2):
            with transport.open_yahoo_chart(request(), timeout=6) as result:
                assert result.read() == b"ok"
            barrier.wait(timeout=5)
    with pytest.raises(RuntimeError), transport.reuse_yahoo_chart_connections():
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = [submit_with_context(executor, work) for _ in range(2)]
            for job in jobs:
                job.result()
        raise RuntimeError("caller stopped")
    assert len(sessions) == 2
    for session in sessions:
        assert session.get.call_count == 2
        session.close.assert_called_once()
    assert transport._pool.get() is None


def test_real_http_socket_is_reused_without_cookies_or_response_reuse():
    peers, cookies = [], []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            peers.append(self.client_address)
            cookies.append(self.headers.get("Cookie"))
            data = str(len(peers)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Set-Cookie", "test=not-reused")
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/chart")
        with transport.reuse_yahoo_chart_connections():
            for n in (1, 2):
                with transport.open_yahoo_chart(req, timeout=2) as result:
                    assert result.read() == str(n).encode()
        assert peers[0] == peers[1]
        assert cookies == [None, None]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
