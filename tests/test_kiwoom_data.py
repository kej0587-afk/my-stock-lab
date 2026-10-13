from datetime import datetime, timezone

import pytest
import requests

from stock_lab_core.kiwoom_data import KiwoomConfig, KiwoomDataClient, kiwoom_client_from_secrets, normalize_kiwoom_domestic_snapshot


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_disabled_missing_keys_and_us_symbol_do_not_request():
    session = Session([])
    assert KiwoomDataClient(session=session).get_domestic_snapshot("005930")["status"] == "disabled"
    assert KiwoomDataClient(KiwoomConfig(enabled=True), session=session).get_domestic_snapshot("005930")["status"] == "missing_configuration"
    assert KiwoomDataClient(KiwoomConfig(enabled=True, appkey="test", secretkey="test"), session=session).get_domestic_snapshot("DELL")["status"] == "unsupported_ticker"
    assert session.calls == []


def test_normalization_keeps_missing_and_rejects_other_ticker():
    response = {"return_code": 0, "stk_cd": "005930", "cur_prc": "-100,000", "per": "", "pbr": "1.5", "mac": "10", "cup_nga": "-2", "trde_qty": "16,594"}
    result = normalize_kiwoom_domestic_snapshot(response, "005930.KS")
    assert result["ok"]
    assert result["data"]["currentPrice"] == 100000
    assert result["data"]["per"] is None
    assert result["data"]["marketCap"] == 1000000000
    assert result["data"]["netIncome"] == -200000000
    assert result["data"]["volume"] == 16594
    assert not result["asof"]
    assert not normalize_kiwoom_domestic_snapshot(response, "000660")["ok"]


def test_token_reused_only_allowlisted_stock_requests():
    session = Session([
        Response({"return_code": 0, "token": "TEST_TOKEN", "token_type": "bearer", "expires_dt": "20261013090000"}),
        Response({"return_code": 0, "stk_cd": "005930", "per": "12"}),
        Response({"return_code": 0, "stk_cd": "000660", "pbr": "2"}),
    ])
    config = KiwoomConfig(enabled=True, appkey="TEST_KEY", secretkey="TEST_SECRET")
    now = datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp()
    client = KiwoomDataClient(config, session=session, now=lambda: now)
    assert client.get_domestic_snapshot("005930.KS")["ok"]
    assert client.get_domestic_snapshot("000660.KS")["ok"]
    assert len(session.calls) == 3
    assert [c[1]["headers"]["api-id"] for c in session.calls] == ["au10001", "ka10001", "ka10001"]
    assert session.calls[0][1]["json"]["grant_type"] == "client_credentials"
    assert session.calls[1][1]["allow_redirects"] is False
    assert session.calls[1][1]["timeout"] == (3.05, 10.0)
    assert "TEST_SECRET" not in repr(config)


@pytest.mark.parametrize("response,status", [(requests.Timeout("private_key_in_exception"), "timeout"), (Response({}, 429), "rate_limited"), (Response({}, 403), "auth_error"), (Response([], 200), "invalid_response")])
def test_errors_are_sanitized_and_not_retried(response, status):
    session = Session([response])
    client = KiwoomDataClient(KiwoomConfig(enabled=True, appkey="test", secretkey="test"), session=session)
    result = client.get_domestic_snapshot("005930")
    assert result["status"] == status
    assert "private_key" not in str(result)
    assert len(session.calls) == 1


def test_secrets_require_explicit_boolean_enable():
    assert kiwoom_client_from_secrets({}).status == "disabled"
    assert kiwoom_client_from_secrets({"kiwoom": {"enabled": "true"}}).status == "invalid_configuration"


def test_user_secret_aliases_preserve_mock_environment_without_network():
    client = kiwoom_client_from_secrets({"kiwoom": {
        "enabled": True, "app_key": "TEST_KEY", "app_secret": "TEST_SECRET", "use_mock": True,
    }})
    assert client.status == "ready"
    session = Session([
        Response({"return_code": 0, "token": "TEST_TOKEN", "token_type": "bearer", "expires_dt": "20991013090000"}),
        Response({"return_code": 0, "stk_cd": "005930", "per": "12"}),
    ])
    client._session = session
    result = client.get_domestic_snapshot("005930")
    assert result["is_mock"]
    assert all(url.startswith("https://mockapi.kiwoom.com/") for url, _ in session.calls)
    assert session.calls[0][1]["json"]["appkey"] == "TEST_KEY"


@pytest.mark.parametrize("overrides", [
    {"environment": "real"}, {"use_mock": "true"}, {"appkey": "OTHER_KEY"}, {"secretkey": "OTHER_SECRET"},
])
def test_conflicting_or_malformed_aliases_fail_closed(overrides):
    settings = {"enabled": True, "app_key": "TEST_KEY", "app_secret": "TEST_SECRET", "use_mock": True, **overrides}
    client = kiwoom_client_from_secrets({"kiwoom": settings})
    assert client.status == "invalid_configuration"
    assert client.get_domestic_snapshot("005930")["status"] == "invalid_configuration"


def test_blank_user_keys_remain_missing_not_ready():
    client = kiwoom_client_from_secrets({"kiwoom": {"enabled": True, "app_key": "", "app_secret": "", "use_mock": True}})
    assert client.status == "missing_configuration"
