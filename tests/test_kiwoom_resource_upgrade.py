"""Deployment transitions must not reuse the pre-US cached client contract."""

import pytest

from stock_lab_core.kiwoom_data import KiwoomConfig, KiwoomDataClient


class LegacyClient:
    def get_market_snapshot(self, kind, theme_code=""):
        pytest.fail("US calls must not reach the old client")


@pytest.fixture(autouse=True)
def clear_caches(app_module):
    app_module.fetch_kiwoom_us_snapshot.clear()
    app_module._cached_kiwoom_data_client.clear()
    yield
    app_module.fetch_kiwoom_us_snapshot.clear()
    app_module._cached_kiwoom_data_client.clear()


def test_resource_cache_uses_contract_revision_and_demo_mode(app_module, monkeypatch):
    created = []
    credentials = {"kiwoom": {"enabled": False}}

    def factory(secrets):
        created.append(secrets)
        return object()

    monkeypatch.setattr(app_module, "kiwoom_client_from_secrets", factory)
    monkeypatch.setattr(app_module.st, "secrets", credentials)
    cached = app_module._cached_kiwoom_data_client
    old = cached("before-us", False)
    assert cached("before-us", False) is old
    new = cached("us-v1", False)
    demo = cached("us-v1", True)
    assert old is not new and new is not demo
    assert created == [credentials, credentials, None]
    app_module.cache_clear(app_module.get_kiwoom_data_client)
    assert cached("us-v1", False) is not new


@pytest.mark.parametrize("kind,ticker,exchange", [
    ("us_turnover", "", "ND"), ("us_sectors", "", "ND"), ("us_quote", "DELL", "NY"),
])
def test_stale_cached_client_is_recreated_once(app_module, monkeypatch, kind, ticker, exchange):
    calls = []

    class CurrentClient:
        def get_market_snapshot(self, kind, *, ticker="", exchange="ND"):
            calls.append((kind, ticker, exchange))
            return {"ok": True, "rows": [{"코드": ticker or "TEST"}]}

    current = CurrentClient()
    state = {"client": LegacyClient(), "clears": 0}

    def get_client():
        return state["client"]

    def clear():
        state.update(client=current, clears=state["clears"] + 1)

    get_client.clear = clear
    monkeypatch.setattr(app_module, "get_kiwoom_data_client", get_client)
    result = app_module.fetch_kiwoom_us_snapshot(kind, ticker, exchange)
    assert result["ok"]
    assert state["clears"] == 1 and calls == [(kind, ticker, exchange)]
    assert app_module.fetch_kiwoom_us_snapshot(kind, ticker, exchange) == result
    assert len(calls) == 1


def test_partial_deployment_reports_mismatch_without_repeated_rebuilds(app_module, monkeypatch):
    clears = []

    def get_client():
        return LegacyClient()

    get_client.clear = lambda: clears.append(True)
    monkeypatch.setattr(app_module, "get_kiwoom_data_client", get_client)
    result = app_module.fetch_kiwoom_us_snapshot("us_turnover")
    assert not result["ok"] and result["rows"] == []
    assert result["status"] == "client_version_mismatch"
    assert clears == [True]
    assert app_module.fetch_kiwoom_us_snapshot("us_turnover") == result
    assert clears == [True]  # failure cooldown does not keep rebuilding


def test_current_client_implementation_errors_are_not_hidden(app_module, monkeypatch):
    class BrokenClient:
        def get_market_snapshot(self, kind, *, ticker="", exchange="ND"):
            raise TypeError("error inside the provider parser")

    monkeypatch.setattr(app_module, "get_kiwoom_data_client", lambda: BrokenClient())
    with pytest.raises(TypeError, match="inside the provider parser"):
        app_module.fetch_kiwoom_us_snapshot("us_turnover")


def test_real_wrapper_client_parser_path_without_credentials(app_module, monkeypatch):
    calls = []

    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"return_code": 0, "result_list": [{"stk_cd": "DELL", "stex_tp": "NY",
                    "stk_nm": "델", "cur_prc": "+140", "flu_rt": "2.1", "rank": "1"}]}

        def close(self):
            pass

    class Session:
        def post(self, url, **kwargs):
            calls.append((url, kwargs["headers"]["api-id"]))
            return Response()

    client = KiwoomDataClient(KiwoomConfig(enabled=True, appkey="TEST", secretkey="TEST"), session=Session())
    monkeypatch.setattr(client, "_access_token", lambda: "TEST_TOKEN")
    monkeypatch.setattr(app_module, "get_kiwoom_data_client", lambda: client)
    result = app_module.fetch_kiwoom_us_snapshot("us_turnover")
    assert result["rows"][0]["코드"] == "DELL"
    assert calls == [("https://api.kiwoom.com/api/us/rkinfo", "usa20540")]
