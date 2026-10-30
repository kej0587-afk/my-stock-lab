"""Offline safety and cache contracts for automatic read-only investor evidence."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import socket

import pytest

from stock_lab_core import market_sentiment as sentiment
from stock_lab_core.kiwoom_data import KiwoomConfig, KiwoomDataClient


@pytest.fixture(autouse=True)
def offline_cache(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Live network is forbidden in investor evidence tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    sentiment.load_investor_flow_evidence.clear()
    yield
    sentiment.load_investor_flow_evidence.clear()


def snapshot(**changes):
    return {"ok": True, "status": "available", "is_mock": False,
            "fetched_at": "2026-10-30T01:00:00+00:00", "has_more": True,
            "rows": [{"업종": "Technology", "외국인 순매수(억원)": 10,
                      "기관 순매수(억원)": -20}], **changes}


class Client:
    def __init__(self, *, status="ready", environment="real", result=None):
        self.connection_info = {"status": status, "environment": environment}
        self.result = result if result is not None else snapshot()
        self.calls = []

    def get_market_snapshot(self, kind):
        assert kind in ("sector_kospi", "sector_kosdaq")
        self.calls.append(kind)
        if isinstance(self.result, Exception):
            raise self.result
        return deepcopy(self.result)


def flow_rows(evidence, checked_at="2026-10-30T01:00:01+00:00", **context):
    result = sentiment.sentiment_evidence({"market_observation_evidence": evidence,
        "quote_checked_at": checked_at, **context})
    return [row for row in result["rows"] if "순매수" in row["지표"]]


@pytest.mark.parametrize("status,environment,expected", [
    ("ready", "mock", "mock_excluded"),
    ("disabled", "real", "disabled"),
    ("missing_configuration", "real", "missing_configuration"),
    ("invalid_configuration", "real", "invalid_configuration"),
    ("ready", "unknown", "unverified_environment"),
])
def test_only_live_configured_clients_are_read(status, environment, expected):
    client = Client(status=status, environment=environment)
    result = sentiment.load_investor_flow_evidence(client)
    assert client.calls == []
    assert all(not row["ok"] and not row["rows"] and row["status"] == expected for row in result.values())
    assert all(row["관측"] == "미연결" for row in flow_rows(result))
    if environment == "mock":
        assert all("모의자료 제외" in row["범위·한계"] for row in flow_rows(result))


def test_public_demo_does_not_even_inspect_client_configuration():
    class Unreadable:
        @property
        def connection_info(self):
            pytest.fail("Demo must not access client configuration")
    result = sentiment.load_investor_flow_evidence(Unreadable(), public_demo=True)
    assert {row["status"] for row in result.values()} == {"public_demo"}


def test_success_cache_is_per_client_bounded_and_returns_detached_rows(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(sentiment.time, "monotonic", lambda: clock[0])
    client = Client()
    first = sentiment.load_investor_flow_evidence(client)
    first["sector_kospi"]["rows"][0]["외국인 순매수(억원)"] = 999
    clock[0] += 179
    cached = sentiment.load_investor_flow_evidence(client)
    assert cached["sector_kospi"]["rows"][0]["외국인 순매수(억원)"] == 10
    assert len(client.calls) == 2
    clock[0] += 1
    sentiment.load_investor_flow_evidence(client)
    assert len(client.calls) == 4
    other = Client(result=snapshot(rows=[{"업종": "Other", "기관 순매수(억원)": 0}]))
    result = sentiment.load_investor_flow_evidence(other)
    assert result["sector_kospi"]["rows"][0]["업종"] == "Other"
    assert len(other.calls) == 2
    for _ in range(20):
        sentiment.load_investor_flow_evidence(Client())
    assert len(sentiment._investor_cache) == 32
    sentiment.load_investor_flow_evidence.clear()
    assert not sentiment._investor_cache


def test_failure_cooldown_is_shorter_and_raw_error_is_not_exposed(monkeypatch, caplog):
    clock = [100.0]
    monkeypatch.setattr(sentiment.time, "monotonic", lambda: clock[0])
    client = Client(result=RuntimeError("PRIVATE_SECRET_TOKEN"))
    result = sentiment.load_investor_flow_evidence(client)
    clock[0] += 59
    sentiment.load_investor_flow_evidence(client)
    assert len(client.calls) == 2
    assert "PRIVATE_SECRET_TOKEN" not in json.dumps(result) + caplog.text
    client.result = snapshot()
    clock[0] += 1
    assert all(row["ok"] for row in sentiment.load_investor_flow_evidence(client).values())
    assert len(client.calls) == 4


@pytest.mark.parametrize("changes,expected", [
    ({"is_mock": True}, "mock_excluded"),
    ({"is_mock": None}, "unverified_environment"),
    ({"ok": False, "status": "rate_limited", "reason": "PRIVATE_SECRET"}, "rate_limited"),
    ({"ok": False, "status": "PRIVATE_SECRET"}, "unavailable"),
    ({"ok": False, "status": {}}, "unavailable"),
    ({"fetched_at": "2026-10-30"}, "invalid_response"),
    ({"fetched_at": "2026-10-30T01:00:00"}, "invalid_response"),
    ({"rows": 7}, "invalid_response"),
    ({"rows": [{"업종": "T", "외국인 순매수(억원)": float("nan")}]}, "no_data"),
])
def test_untrusted_provider_status_mock_time_and_missing_values_fail_closed(changes, expected):
    result = sentiment.load_investor_flow_evidence(Client(result=snapshot(**changes)))
    assert all(not row["ok"] and row["status"] == expected for row in result.values())
    assert "PRIVATE_SECRET" not in json.dumps(result)


def test_partial_market_failure_does_not_discard_other_market():
    class Partial(Client):
        def get_market_snapshot(self, kind):
            return snapshot() if kind == "sector_kospi" else snapshot(ok=False, status="timeout")
    result = sentiment.load_investor_flow_evidence(Partial())
    rows = flow_rows(result)
    assert all(row["관측"] != "미연결" for row in rows[:2])
    assert all(row["관측"] == "미연결" and "시간 초과" in row["범위·한계"] for row in rows[2:])


def test_own_collection_clock_preserves_quote_clock_and_existing_freshness_rules():
    result = sentiment.load_investor_flow_evidence(Client())
    rows = flow_rows(result, checked_at="2026-10-30T00:00:00Z",
                     market_evidence_checked_at="2026-10-30T01:00:02Z")
    assert all(row["관측"] != "미연결" for row in rows)
    assert all("전체 합산 아님" in row["범위·한계"] and "추가 페이지 미조회" in row["범위·한계"] for row in rows)
    for checked_at in ("2026-10-30T00:59:59Z", "2026-10-30T01:05:01Z", "bad-time"):
        assert all(row["관측"] == "미연결" for row in flow_rows(result, market_evidence_checked_at=checked_at))
    assert all(row["관측"] != "미연결" for row in flow_rows(result, checked_at="2026-10-30T01:05:00Z"))


def test_zero_is_observed_but_missing_institution_is_not_zero():
    result = sentiment.load_investor_flow_evidence(Client(result=snapshot(
        rows=[{"업종": "T", "외국인 순매수(억원)": 0, "기관 순매수(억원)": None}])))
    rows = flow_rows(result)
    assert "+0.0억원" in rows[0]["관측"]
    assert rows[1]["관측"] == "미연결"


def test_real_client_uses_existing_readonly_contract_and_single_token_no_pagination():
    class Response:
        status_code = 200
        headers = {"cont-yn": "Y"}
        def __init__(self, payload):
            self.payload = payload
        def json(self):
            return self.payload
        def close(self):
            pass

    class Session:
        def __init__(self):
            self.calls = []
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/oauth2/token"):
                return Response({"return_code": 0, "token": "TEST_TOKEN", "token_type": "bearer",
                                 "expires_dt": "20261031090000"})
            return Response({"return_code": 0, "inds_netprps": [{"inds_cd": "001", "inds_nm": "Technology",
                "frgnr_netprps": "+12", "orgn_netprps": "-3"}]})

    session = Session()
    client = KiwoomDataClient(KiwoomConfig(enabled=True, appkey="TEST_KEY", secretkey="TEST_SECRET"),
        session=session, now=lambda: datetime(2026, 10, 30, 1, tzinfo=timezone.utc).timestamp())
    result = sentiment.load_investor_flow_evidence(client)
    assert all(row["ok"] for row in result.values())
    assert [call[1]["headers"]["api-id"] for call in session.calls] == ["au10001", "ka10051", "ka10051"]
    assert [call[1]["json"]["mrkt_tp"] for call in session.calls[1:]] == ["0", "1"]
    assert all(call[1]["timeout"] == (3.05, 10.0) and call[1]["allow_redirects"] is False for call in session.calls)
    assert all(call[1]["json"]["amt_qty_tp"] == "0" for call in session.calls[1:])
    assert all(call[0].endswith("/api/dostk/sect") for call in session.calls[1:])
    assert all(secret not in json.dumps(result) for secret in ("TEST_TOKEN", "TEST_KEY", "TEST_SECRET"))
    assert result["sector_kospi"]["rows"][0]["외국인 순매수(억원)"] == 12
    sentiment.load_investor_flow_evidence(client)
    assert len(session.calls) == 3
