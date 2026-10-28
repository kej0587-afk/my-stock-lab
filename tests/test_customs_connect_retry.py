"""Bounded connection retry and expiry-safe failure cooldown."""

from datetime import datetime, timezone
import json
import logging

import pytest
import requests

from stock_lab_core import economic_bulletins as bulletins
from stock_lab_core import economic_releases as releases
from tests.test_economic_release_live_sources import LISTING, DETAIL, Response

NOW = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)


@pytest.fixture
def transport(monkeypatch):
    releases.clear_economic_releases_cache()
    bulletins.clear_customs_bulletin_failures()
    state = dict(calls=[], responses=[], failures=2, error=requests.ConnectTimeout("secret-query"))

    def get(url, **kwargs):
        state["calls"].append(url)
        if url == bulletins.CUSTOMS_DETAIL_URL:
            assert kwargs["timeout"] == (2, 4) and not kwargs["allow_redirects"]
            if state["failures"]:
                state["failures"] -= 1
                raise state["error"]
        response = Response(text=LISTING if url == bulletins.CUSTOMS_LIST_URL else DETAIL)
        state["responses"].append(response)
        return response

    monkeypatch.setattr(releases.requests, "get", get)
    yield state
    releases.clear_economic_releases_cache()
    bulletins.clear_customs_bulletin_failures()


def test_single_connect_retry_can_recover_without_repeating_listing(transport):
    transport["failures"] = 1
    row = bulletins.load_kr_exports_bulletin(NOW)
    assert row["status"] == "released" and row["actual"] == 83.7
    assert transport["calls"] == [bulletins.CUSTOMS_LIST_URL, bulletins.CUSTOMS_DETAIL_URL, bulletins.CUSTOMS_DETAIL_URL]
    detail = row["bulletin_request_metadata"]["detail"]
    assert detail["attempt_count"] == 2 and detail["http_status"] == 200
    assert detail["attempts"][0]["exception_type"] == "ConnectTimeout"
    assert "transport_error" not in detail and "exception_type" not in detail
    assert all(response.closed for response in transport["responses"])


def test_failed_retry_cools_down_without_log_spam_then_recovers(transport, monkeypatch, caplog):
    tick = [100.0]
    monkeypatch.setattr(bulletins.time, "monotonic", lambda: tick[0])
    with caplog.at_level(logging.INFO):
        row = bulletins.load_kr_exports_bulletin(NOW)
        initial_logs = len(caplog.records)
        cached = bulletins.load_kr_exports_bulletin(NOW)
    assert len(transport["calls"]) == 3 and len(caplog.records) == initial_logs
    assert row["actual"] is None and row["missing_reason"] == "request_failed:ConnectTimeout"
    request = cached["bulletin_request_metadata"]
    assert request["failure_cooldown"] and request["retry_after_seconds"] == 180
    assert not request["detail"]["attempted"] and request["detail"]["origin"] == "failure_cooldown"
    assert request["detail"]["attempt_count"] == 0 and len(request["detail"]["attempts"]) == 2
    assert "secret-query" not in json.dumps(cached) + caplog.text + str(bulletins._CUSTOMS_FAILURES)
    tick[0] += bulletins.CUSTOMS_FAILURE_TTL + 1
    recovered = bulletins.load_kr_exports_bulletin(NOW)
    assert recovered["status"] == "released" and len(transport["calls"]) == 5


def test_read_timeout_is_not_retried(transport):
    transport["error"] = requests.ReadTimeout("secret-query")
    row = bulletins.load_kr_exports_bulletin(NOW)
    assert row["actual"] is None and len(transport["calls"]) == 2
    assert row["bulletin_request_metadata"]["detail"]["attempt_count"] == 1


def test_cooldown_cannot_extend_manual_fact_expiry(transport, monkeypatch):
    now = NOW.replace(month=11, day=3)
    transport["failures"] = 10
    row = releases._ecos(now, "", "KR_EXPORTS")
    first = bulletins.apply_official_bulletins([row], now)[0]
    cached = bulletins.apply_official_bulletins([row], now)[0]
    assert first["actual"] is None and cached["actual"] is None
    assert cached["bulletin_request_metadata"]["failure_cooldown"]
    assert len(transport["calls"]) == 3
