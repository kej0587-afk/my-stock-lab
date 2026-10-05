import ast
from concurrent.futures import ThreadPoolExecutor
import gc
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import certifi
from curl_cffi import requests
import pytest

from stock_lab_core import yahoo_transport as transport


@pytest.fixture(autouse=True)
def isolated_transport(monkeypatch):
    session_factory = transport._windows_yahoo_session
    session_factory.cache_clear()
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    yield
    session_factory.cache_clear()


def test_non_windows_retains_default_transport(monkeypatch):
    monkeypatch.setattr(transport, "_is_windows", lambda: False)
    monkeypatch.setattr(transport, "_windows_yahoo_session", lambda: pytest.fail("Unexpected session"))
    assert transport.yahoo_session_kwargs() == {}


def test_ascii_certificate_retains_default_transport(monkeypatch, tmp_path):
    monkeypatch.setattr(transport, "_is_windows", lambda: True)
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "cacert.pem"))
    monkeypatch.setattr(requests, "Session", lambda **kwargs: pytest.fail("Unexpected session"))
    assert transport.yahoo_session_kwargs() == {}


def test_unicode_certificate_is_copied_without_disabling_verification(monkeypatch, tmp_path):
    source = tmp_path / "\uC8FC\uC2DD" / "cacert.pem"
    source.parent.mkdir()
    source.write_bytes(b"trusted original CA bytes")
    monkeypatch.setattr(transport, "_is_windows", lambda: True)
    monkeypatch.setattr(certifi, "where", lambda: str(source))
    monkeypatch.setattr(transport.tempfile, "gettempdir", lambda: str(tmp_path))
    sessions = []

    def session(**kwargs):
        sessions.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(requests, "Session", session)
    first = transport.yahoo_session_kwargs()["session"]
    assert transport.yahoo_session_kwargs()["session"] is first
    assert len(sessions) == 1
    assert first.impersonate == "chrome"
    assert isinstance(first.verify, str) and first.verify.isascii()
    assert Path(first.verify).read_bytes() == source.read_bytes()
    transport._windows_yahoo_session.cache_clear()
    gc.collect()
    assert Path(first.verify).read_bytes() == source.read_bytes()


def test_custom_ca_is_preserved(monkeypatch, tmp_path):
    custom = tmp_path / "company-ca.pem"
    custom.write_bytes(b"company trusted CA bytes")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(custom))
    monkeypatch.setattr(transport, "_is_windows", lambda: True)
    monkeypatch.setattr(certifi, "where", lambda: "unused-default.pem")
    monkeypatch.setattr(requests, "Session", lambda **kwargs: SimpleNamespace(**kwargs))
    assert transport.yahoo_session_kwargs()["session"].verify == str(custom)


def test_concurrent_first_use_keeps_one_session_and_live_bundle(monkeypatch, tmp_path):
    source = tmp_path / "\uC8FC\uC2DD" / "cacert.pem"
    source.parent.mkdir()
    source.write_bytes(b"trusted original CA bytes")
    monkeypatch.setattr(transport, "_is_windows", lambda: True)
    monkeypatch.setattr(certifi, "where", lambda: str(source))
    monkeypatch.setattr(transport.tempfile, "gettempdir", lambda: str(tmp_path))
    calls = []

    def make_session(**kwargs):
        time.sleep(0.02)
        calls.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(requests, "Session", make_session)
    barrier = threading.Barrier(4)

    def first_use(_):
        barrier.wait(timeout=5)
        return transport.yahoo_session_kwargs()["session"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        sessions = list(pool.map(first_use, range(4)))
    assert len(calls) == 1
    assert all(session is sessions[0] for session in sessions)
    transport._windows_yahoo_session.cache_clear()
    gc.collect()
    assert Path(sessions[0].verify).read_bytes() == source.read_bytes()


def test_copy_failure_does_not_fall_back_to_unverified_tls(monkeypatch, tmp_path):
    monkeypatch.setattr(transport, "_is_windows", lambda: True)
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "\uC8FC\uC2DD" / "missing.pem"))
    monkeypatch.setattr(transport.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(requests, "Session", lambda **kwargs: pytest.fail("Unexpected session"))
    with pytest.raises(FileNotFoundError):
        transport.yahoo_session_kwargs()


def test_unicode_temp_path_is_reported_not_silently_bypassed(monkeypatch, tmp_path):
    monkeypatch.setattr(transport.tempfile, "gettempdir", lambda: str(tmp_path / "\uC8FC\uC2DD"))
    with pytest.raises(OSError, match="ASCII temporary"):
        transport._ascii_ca_bundle(str(tmp_path / "\uC8FC\uC2DD" / "cacert.pem"))


@pytest.mark.parametrize("filename", [
    "app.py", "stock_lab_core/prices.py", "stock_lab_core/news.py", "stock_lab_core/money_flow.py",
])
def test_yfinance_call_sites_use_shared_verified_transport(filename):
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / filename).read_text(encoding="utf-8-sig"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "yf" and node.func.attr in {"Ticker", "download"}]
    assert calls
    for call in calls:
        assert any(keyword.arg is None and isinstance(keyword.value, ast.Call)
                   and isinstance(keyword.value.func, ast.Name)
                   and keyword.value.func.id == "yahoo_session_kwargs"
                   for keyword in call.keywords), f"Missing session: {filename}:{call.lineno}"
