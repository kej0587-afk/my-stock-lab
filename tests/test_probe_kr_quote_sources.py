"""Offline contracts for the standalone comparison; no production routing edits."""

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import io
import json
from unittest.mock import Mock
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import probe_kr_quote_sources as probe


TICKER = "000660.KS"
TICKERS = ["005930.KS", TICKER, "379810.KS"]
STAMP = "2026-11-20T20:20:23+09:00"
NXT_STAMP = "2026-11-20T20:00:00+09:00"


def fixtures(code="000660", *, polling_price=1100000, basic_price=1100000):
    """Synthetic public schema with the observed root/NXT price distinction."""
    nxt = {"overPrice": "1,099,000", "localTradedAt": NXT_STAMP, "tradingSessionType": "AFTER_MARKET"}
    row = {"cd": code, "nv": polling_price, "ms": "CLOSE", "nxtOverMarketPriceInfo": deepcopy(nxt)}
    polling = {"result": {"time": 1795189441656, "areas": [{"name": "SERVICE_ITEM", "datas": [row]}]}}
    basic = {"itemCode": code, "closePrice": f"{basic_price:,}", "localTradedAt": STAMP,
             "marketStatus": "CLOSE", "marketSessionType": "afterMarket", "overMarketPriceInfo": deepcopy(nxt)}
    return polling, basic


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    opener = Mock(side_effect=AssertionError("unexpected network request"))
    monkeypatch.setattr(probe.urllib.request, "urlopen", opener)
    return opener


def test_equal_root_prices_do_not_certify_same_session_and_inputs_stay_unchanged():
    polling, basic = fixtures()
    original = deepcopy((polling, basic))
    result = probe.compare_pair(TICKER, polling, basic)
    assert result["polling_price"] == result["basic_price"] == 1100000
    assert result["same_numeric_price"] is True
    assert result["basic_minus_polling"] == result["basic_minus_polling_pct"] == 0
    assert result["assessment"] == "equal_numbers_not_proof_of_same_session"
    assert result["polling_observed_at"] is None
    assert result["basic_observed_at"] == "2026-11-20T11:20:23+00:00"
    assert result["basic_timestamp_meaning"] == "supplier_field_not_verified_execution_time"
    assert result["separate_polling_nxt"] == {"price": 1099000., "time": NXT_STAMP}
    assert result["separate_basic_overmarket"] == {"price": 1099000., "time": NXT_STAMP}
    assert (polling, basic) == original


def test_different_root_prices_stay_separate_from_nxt_price_and_timestamp():
    polling, basic = fixtures(basic_price=1100100)
    original = deepcopy((polling, basic))
    result = probe.compare_pair(TICKER, polling, basic)
    assert (result["polling_price"], result["basic_price"]) == (1100000., 1100100.)
    assert result["same_numeric_price"] is False
    assert result["basic_minus_polling"] == 100
    assert result["basic_minus_polling_pct"] == pytest.approx(100 / 1100000 * 100)
    assert result["assessment"] == "different_prices_do_not_substitute"
    assert result["polling_observed_at"] is None
    assert result["basic_observed_at"] == "2026-11-20T11:20:23+00:00"
    assert result["separate_polling_nxt"]["price"] == 1099000.
    assert result["separate_polling_nxt"]["time"] == NXT_STAMP
    assert (polling, basic) == original


def test_wrong_symbol_on_either_side_cannot_supply_price_or_time():
    polling, basic = fixtures()
    other_polling, other_basic = fixtures("005930")
    for payloads, missing_side in [((other_polling, basic), "polling"), ((polling, other_basic), "basic")]:
        original = deepcopy(payloads)
        result = probe.compare_pair(TICKER, *payloads)
        assert result[missing_side + "_price"] is None
        assert result[missing_side + "_observed_at"] is None
        assert result["same_numeric_price"] is None
        assert result["basic_minus_polling"] is result["basic_minus_polling_pct"] is None
        assert result["assessment"] == "missing_or_unproven_quote"
        assert payloads == original


def test_missing_naive_or_invalid_basic_time_is_not_filled_from_response_or_nested_time():
    for stamp in (None, "2026-11-20T20:20:23", "bad", "2026-02-30T20:20:23+09:00"):
        polling, basic = fixtures()
        basic["localTradedAt"] = stamp
        original = deepcopy((polling, basic))
        result = probe.compare_pair(TICKER, polling, basic)
        assert result["polling_price"] == result["basic_price"] == 1100000
        assert result["polling_observed_at"] is result["basic_observed_at"] is None
        assert result["assessment"] == "equal_numbers_not_proof_of_same_session"
        assert (polling, basic) == original
    result = probe.compare_pair(TICKER, {}, {})
    assert result["polling_price"] is result["basic_price"] is None
    assert result["same_numeric_price"] is None


def test_malformed_states_and_nested_shapes_do_not_invent_session_evidence():
    for state in (None, [], {}, 42, "unrecognized"):
        polling, basic = fixtures()
        row = polling["result"]["areas"][0]["datas"][0]
        row.update(ms=state, nxtOverMarketPriceInfo=["malformed"])
        basic.update(marketStatus=state, marketSessionType=state, overMarketPriceInfo="malformed")
        original = deepcopy((polling, basic))
        result = probe.compare_pair(TICKER, polling, basic)
        assert result["polling_observed_at"] is None
        assert result["basic_observed_at"] == "2026-11-20T11:20:23+00:00"
        assert result["separate_polling_nxt"] == result["separate_basic_overmarket"] == {"price": None, "time": None}
        assert result["assessment"] == "equal_numbers_not_proof_of_same_session"
        assert (polling, basic) == original


@pytest.mark.parametrize("basic_first", [False, True])
def test_collect_three_symbols_uses_exactly_one_bulk_and_three_basic_requests(basic_first):
    calls, payloads = [], []
    def fetch(url, *, timeout):
        calls.append((url, timeout))
        parsed = urlparse(url)
        if parsed.netloc == "polling.finance.naver.com":
            assert parse_qs(parsed.query)["query"] == ["SERVICE_ITEM:005930,000660,379810"]
            rows = [fixtures(t.split(".")[0])[0]["result"]["areas"][0]["datas"][0] for t in TICKERS]
            payload = {"result": {"areas": [{"name": "SERVICE_ITEM", "datas": rows}]}}
            elapsed = .1
        else:
            assert parsed.netloc == "m.stock.naver.com"
            payload = fixtures(parsed.path.split("/")[-2])[1]
            elapsed = .2
        payloads.append((payload, deepcopy(payload)))
        return {"request_count": 1, "elapsed_seconds": elapsed, "payload": payload}
    tickers = ["005930.ks", TICKER, "379810.KS", "005930.KS"]
    original = tickers.copy()
    result = probe.collect_round(tickers, basic_first=basic_first, fetch=fetch)
    bulk = ("https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM%3A005930%2C000660%2C379810", 6)
    singles = [(f"https://m.stock.naver.com/api/stock/{t.split('.')[0]}/basic", 5) for t in TICKERS]
    assert calls == singles + [bulk] if basic_first else calls == [bulk] + singles
    assert result["order"] == ("basic_then_polling" if basic_first else "polling_then_basic")
    assert result["cost"] == {"polling_requests": 1, "basic_requests": 3,
                              "polling_seconds": .1, "basic_sequential_seconds": .6}
    assert [row["ticker"] for row in result["rows"]] == TICKERS
    assert all(row["assessment"] == "equal_numbers_not_proof_of_same_session" for row in result["rows"])
    assert tickers == original
    assert all(payload == saved for payload, saved in payloads)


def test_invalid_or_conflicting_tickers_fail_before_any_fetch():
    invalid = [[], ["005930"], ["SOXL"], ["005930.KS/extra"], [None],
               ["005930.KS", "005930.KQ"], [f"{i:06d}.KS" for i in range(13)]]
    for tickers in invalid:
        fetch = Mock(side_effect=AssertionError("validation must precede fetch"))
        with pytest.raises(ValueError):
            probe.collect_round(tickers, fetch=fetch)
        fetch.assert_not_called()


class Response(io.BytesIO):
    status = 200


def test_fetch_capture_preserves_payload_hash_status_and_separate_request_clocks(monkeypatch):
    payload = fixtures()[1]
    raw = json.dumps(payload).encode()
    opener = Mock(return_value=Response(raw))
    monkeypatch.setattr(probe.urllib.request, "urlopen", opener)
    monkeypatch.setattr(probe, "perf_counter", Mock(side_effect=[10., 10.125]))
    url = "https://m.stock.naver.com/api/stock/000660/basic"
    result = probe.fetch_capture(url, timeout=5)
    opener.assert_called_once()
    assert opener.call_args.args[0].full_url == url
    assert opener.call_args.kwargs == {"timeout": 5}
    assert result["payload"] == payload
    assert result["http_status"] == 200 and result["error_type"] is None
    assert result["request_count"] == 1 and result["elapsed_seconds"] == .125
    assert result["response_bytes"] == len(raw)
    assert result["response_sha256"] == hashlib.sha256(raw).hexdigest()
    for field in ("requested_at", "received_at"):
        assert datetime.fromisoformat(result[field]).utcoffset() == timedelta(0)
    assert result["payload"]["localTradedAt"] == STAMP


@pytest.mark.parametrize("failure,status,error_name", [
    ("http", 429, "HTTPError"), ("timeout", None, "TimeoutError"), ("json", 200, "JSONDecodeError"),
])
def test_fetch_errors_are_single_attempt_and_keep_missing_quotes(monkeypatch, failure, status, error_name):
    if failure == "json":
        opener = Mock(return_value=Response(b"not-json"))
    else:
        error = TimeoutError("synthetic timeout") if failure == "timeout" else urllib.error.HTTPError(
            "https://example.invalid", 429, "synthetic rate limit", {}, None)
        opener = Mock(side_effect=error)
    monkeypatch.setattr(probe.urllib.request, "urlopen", opener)
    result = probe.fetch_capture("https://example.invalid", timeout=6)
    opener.assert_called_once()
    assert result["request_count"] == 1
    assert result["http_status"] == status and result["error_type"] == error_name
    assert result["payload"] == {}
    assert result["response_bytes"] == (8 if failure == "json" else 0)
    missing = probe.compare_pair(TICKER, result["payload"], result["payload"])
    assert missing["polling_price"] is missing["basic_price"] is None
    assert missing["same_numeric_price"] is None


@pytest.mark.parametrize("guard", ["no_live", "output_exists"])
def test_cli_guards_stop_before_collection_or_output_changes(monkeypatch, tmp_path, no_network, guard):
    output = tmp_path / "capture.json"
    args = ["--output", str(output)]
    if guard == "output_exists":
        output.write_text("keep original", encoding="utf-8")
        args.insert(0, "--live")
    collect = Mock(side_effect=AssertionError("guard must stop collection"))
    monkeypatch.setattr(probe, "collect_round", collect)
    with pytest.raises(SystemExit) as exc:
        probe.main(args)
    assert exc.value.code == 2
    collect.assert_not_called()
    no_network.assert_not_called()
    if guard == "output_exists":
        assert output.read_text(encoding="utf-8") == "keep original"
    else:
        assert not output.exists()


def test_cli_alternates_rounds_and_records_limits_without_certifying_replacement(monkeypatch, tmp_path, no_network):
    output = tmp_path / "nested" / "capture.json"
    collect = Mock(side_effect=lambda tickers, basic_first: {
        "cost": {"polling_requests": 1, "basic_requests": 3}, "rows": [],
        "order": "basic_then_polling" if basic_first else "polling_then_basic"})
    monkeypatch.setattr(probe, "collect_round", collect)
    probe.main(["--live", "--rounds", "2", "--tickers", *TICKERS, "--output", str(output)])
    assert [call.kwargs for call in collect.call_args_list] == [{"basic_first": False}, {"basic_first": True}]
    assert all(call.args == (TICKERS,) for call in collect.call_args_list)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["production_routing_changed"] is False
    assert report["replacement_supported"] is False
    assert report["scope"] == "public_local_probe_not_cloud_or_simultaneous_market_snapshot"
    assert len(report["runs"]) == 2
    assert any("one request per symbol" in item for item in report["limits"])
    assert any("not a Cloud performance benchmark" in item for item in report["limits"])
    no_network.assert_not_called()
