"""Offline diagnostic fixtures, not economic observations for production use."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import logging

import pytest
import requests

from stock_lab_core import economic_bulletins as bulletins
from stock_lab_core import economic_releases as releases


NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
SECRET = "private-key-that-must-not-escape"
HEADER = ["cell_value", "time_slot_date", "category_code", "data_type_code", "seasonally_adj", "error_data"]
CELLS = ["0.8", "2026-09-01", "44X72", "MPCSM", "yes", "no"]


class Response:
    status_code = 200
    text = SECRET
    closed = False

    def __init__(self, payload=None):
        self.payload = payload

    def json(self):
        if self.payload is None:
            raise ValueError(SECRET)
        return deepcopy(self.payload)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    releases.clear_economic_releases_cache()

    def forbidden(*args, **kwargs):
        pytest.fail("No live requests or credentials in diagnostic tests")

    monkeypatch.setattr(releases, "_api_key", forbidden)
    monkeypatch.setattr(releases.requests, "get", forbidden)
    monkeypatch.setattr(releases.requests, "post", forbidden)
    yield
    releases.clear_economic_releases_cache()


@pytest.mark.parametrize("index,value,reason", [
    (0, "NaN", "invalid_value"), (1, "09/01/2026", "invalid_period"),
    (1, "2026-10-01", "outside_completed_range"), (2, "44000", "category_mismatch"),
    (3, "SM", "data_type_mismatch"), (4, "no", "adjustment_mismatch"), (5, "yes", "error_data"),
])
def test_http200_rejection_has_bounded_evidence(monkeypatch, caplog, index, value, reason):
    cells = list(CELLS)
    cells[index] = value
    response = Response([HEADER, cells])
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(releases.requests, "get", get)
    with caplog.at_level(logging.INFO):
        row = releases._retail(NOW, SECRET)
    request = row["request_metadata"]
    assert request["http_status"] == 200 and request["attempted"]
    assert request["origin"] == "network" and not request["from_cache"]
    assert request["response_summary"]["columns"] == HEADER
    assert request["response_summary"]["row_count"] == 1
    assert request["rejected_rows"] == {reason: 1}
    assert request["observation_count"] == 0
    assert request["response_status"] == "no_valid_observations"
    assert row["actual"] is None and row["publication_status"] == "unconfirmed"
    assert SECRET not in json.dumps(row) + caplog.text and reason in caplog.text
    assert "key" not in request["parameters"] and calls[0]["params"]["key"] == SECRET
    releases._retail(NOW, SECRET)
    assert len(calls) == 2 and response.closed


@pytest.mark.parametrize("payload", [
    {"error": SECRET}, None, [[SECRET], [SECRET]],
    [[*HEADER, "unknown"], [*CELLS, SECRET]],
    [HEADER, [SECRET, *CELLS[1:]]],
])
def test_untrusted_response_fields_and_bodies_are_never_logged(monkeypatch, caplog, payload):
    response = Response(payload)
    monkeypatch.setattr(releases.requests, "get", lambda *a, **k: response)
    with caplog.at_level(logging.INFO):
        row = releases._retail(NOW, SECRET)
    assert SECRET not in json.dumps(row) + caplog.text
    assert "response_summary" in row["request_metadata"] and response.closed


def test_response_excerpt_is_bounded_and_redacts_numeric_credential():
    summary = releases._census_response_summary(
        [[*HEADER, *[SECRET] * 100], *[[*CELLS, *[SECRET] * 100]] * 100], "0.8")
    assert summary["column_count"] == 106 and summary["row_count"] == 100
    assert len(summary["columns"]) == 16 and len(summary["sample_rows"]) == 2
    assert all(len(row) == 16 for row in summary["sample_rows"])
    assert SECRET not in json.dumps(summary) and "0.8" not in json.dumps(summary)


def test_header_only_response_is_distinct_from_filtered_rows(monkeypatch):
    monkeypatch.setattr(releases.requests, "get", lambda *a, **k: Response([HEADER]))
    row = releases._retail(NOW, SECRET)
    request = row["request_metadata"]
    assert request["response_summary"]["row_count"] == 0
    assert request["response_summary"]["sample_rows"] == []
    assert request["rejected_rows"] == {} and request["observation_count"] == 0
    assert row["actual"] is None and "census_no_valid_observations" in row["missing_reason"]


def test_other_collectors_do_not_gain_unmanaged_attempt_provenance(monkeypatch):
    monkeypatch.setattr(releases.requests, "get", lambda *a, **k: Response({}))
    diagnostics = {}
    releases._request(releases.ECOS_URL, diagnostics=diagnostics)
    assert diagnostics["http_status"] == 200
    assert not {"attempted", "origin", "from_cache"} & diagnostics.keys()


def test_census_time_column_and_cache_keep_diagnostics_without_new_request(monkeypatch):
    header = ["time" if name == "time_slot_date" else name for name in HEADER]
    monkeypatch.setattr(releases.requests, "get", lambda *a, **k: Response([header, CELLS]))
    first = releases._retail(NOW, SECRET)
    assert first["actual"] == 0.8 and first["period"] == "2026-09"
    first["request_metadata"]["response_summary"]["columns"].clear()
    cached = releases._retail(NOW, SECRET)
    request = cached["request_metadata"]
    assert request["http_status"] == 200 and request["from_cache"]
    assert request["origin"] == "success_cache" and not request["attempted"]
    assert request["response_summary"]["columns"] == header


@pytest.fixture
def customs(monkeypatch):
    state = {"calls": [], "responses": [], "failure_url": None, "status": 200, "exception": None}

    def get(url, **kwargs):
        state["calls"].append(url)
        if url == state["failure_url"] and state["exception"]:
            raise state["exception"]
        response = Response()
        if url == state["failure_url"]:
            response.status_code = state["status"]
        state["responses"].append(response)
        return response

    monkeypatch.setattr(releases.requests, "get", get)
    # Parser behavior has separate HTML fixtures; isolate request provenance here.
    monkeypatch.setattr(bulletins, "_customs_listing", lambda *a: {"nttSn": "1", "nttSnUrl": "a" * 32})
    monkeypatch.setattr(bulletins, "_customs_observation", lambda *a: {
        "period": "2026-09", "actual": 1.0, "release_at": "2026-10-15"})
    return state


@pytest.mark.parametrize("stage", ["listing", "detail"])
@pytest.mark.parametrize("failure", ["timeout", "http", "parse", "value_error"])
def test_customs_records_failed_stage_and_unattempted_detail(customs, monkeypatch, stage, failure):
    customs["failure_url"] = bulletins.CUSTOMS_LIST_URL if stage == "listing" else bulletins.CUSTOMS_DETAIL_URL
    if failure in {"timeout", "value_error"}:
        customs["exception"] = requests.ReadTimeout(SECRET) if failure == "timeout" else ValueError(SECRET)
    elif failure == "http":
        customs["status"] = 503
    else:
        def fail(*args):
            raise ValueError(SECRET)
        monkeypatch.setattr(bulletins, "_customs_listing" if stage == "listing" else "_customs_observation", fail)
    row = bulletins.load_kr_exports_bulletin(NOW)
    request = row["bulletin_request_metadata"]
    detail = request[stage]
    assert detail["attempted"] and detail["origin"] == "network" and not detail["from_cache"]
    assert detail["failure_stage"] == ("parse" if failure == "parse" else "request")
    assert detail["http_status"] == (200 if failure == "parse" else 503 if failure == "http" else None)
    assert detail["exception_type"] == ({"timeout": "ReadTimeout", "http": "_Unavailable"}.get(failure, "ValueError"))
    assert request["failure_reason"] and row["actual"] is None
    if stage == "listing":
        assert not request["detail"]["attempted"] and request["detail"]["origin"] == "not_attempted"
    assert SECRET not in json.dumps(row)
    bulletins.load_kr_exports_bulletin(NOW)
    assert len(customs["calls"]) == (2 if stage == "listing" else 4)
    assert all(response.closed for response in customs["responses"])


def test_customs_cached_http_status_is_identified_as_historical(customs):
    fresh = bulletins.load_kr_exports_bulletin(NOW)
    assert fresh["bulletin_request_metadata"]["listing"]["attempted"]
    fresh["bulletin_request_metadata"]["listing"]["http_status"] = 999
    cached = bulletins.load_kr_exports_bulletin(NOW)
    request = cached["bulletin_request_metadata"]
    assert request["from_cache"] and len(customs["calls"]) == 2
    for stage in ("listing", "detail"):
        assert request[stage]["http_status"] == 200 and request[stage]["from_cache"]
        assert not request[stage]["attempted"] and request[stage]["origin"] == "success_cache"
