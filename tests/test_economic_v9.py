"""V9 primary-source recovery and diagnostics. No private keys or live services."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging

import pytest
import requests

from stock_lab_core import economic_bulletins as bulletins
from stock_lab_core import economic_cache as cache
from stock_lab_core import economic_releases as releases
from stock_lab_core import report_build


NOW = datetime(2026, 10, 20, 3, tzinfo=timezone.utc)
HISTORY = {"2026-06": 1.7, "2026-07": 2.2, "2026-08": 2.6, "2026-09": 2.4}
SECRET = "fixture-only-private-value"
HEADER = ["cell_value", "time_slot_date", "category_code", "data_type_code", "seasonally_adj", "error_data"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    releases.clear_economic_releases_cache()

    def forbidden(*args, **kwargs):
        pytest.fail("Use explicit fixtures; never inspect keys or contact live services")

    monkeypatch.setattr(releases, "_api_key", forbidden)
    monkeypatch.setattr(releases.requests, "get", forbidden)
    monkeypatch.setattr(releases.requests, "post", forbidden)
    yield
    releases.clear_economic_releases_cache()


def cpi(period="2026-09", values=None, now=NOW):
    values = HISTORY if values is None else values
    previous_period = releases._shift(period, -1)
    row = releases._row("KR_CPI", "%", "YoY", "Bank of Korea ECOS", releases.ECOS_URL, now,
                        period=period, actual=values[period], previous=values.get(previous_period),
                        previous_period=previous_period, previous_source="Bank of Korea ECOS",
                        previous_unit="%", previous_basis="YoY", raw_unit="2020=100",
                        series_id="901Y009/0", seasonal_adjustment="NSA", status="released",
                        retrieved_at=now.isoformat(), value_kind="calculated_from_official_levels")
    releases._monthly_history(row, values)
    return row


def test_actual_only_same_month_preserves_previous_history_and_mean():
    original = cpi()
    cache.retain_successful_observations([original], NOW)
    sparse = cpi(values={"2026-09": 2.7})
    recovered = cache.retain_successful_observations([sparse], NOW)[0]
    assert recovered["actual"] == 2.7 and recovered["previous"] == HISTORY["2026-08"]
    assert recovered["previous3mean"] == pytest.approx((1.7 + 2.2 + 2.6) / 3, abs=1e-6)
    assert recovered["history"][-1] == {"period": "2026-09", "value": 2.7}
    assert recovered["history_restored_from_cache"] is True
    saved = json.loads(cache.CACHE_PATH.read_text(encoding="utf-8"))["KR_CPI"]
    assert saved["previous"] == HISTORY["2026-08"] and len(saved["history"]) == 4
    assert original == cpi() and sparse["previous"] is None


def test_new_month_uses_last_actual_as_previous_and_shifts_average():
    cache.retain_successful_observations([cpi()], NOW)
    now = NOW.replace(month=11)
    row = cache.retain_successful_observations([cpi("2026-10", {"2026-10": 2.8}, now)], now)[0]
    assert row["previous_period"] == "2026-09" and row["previous"] == HISTORY["2026-09"]
    assert row["previous3mean"] == pytest.approx((2.2 + 2.6 + 2.4) / 3)
    assert row["actual_minus_previous"] == pytest.approx(0.4)


def test_new_revised_month_wins_without_erasing_other_months():
    cache.retain_successful_observations([cpi()], NOW)
    revised = cpi(values={"2026-08": 2.1, "2026-09": 2.5})
    row = cache.retain_successful_observations([revised], NOW)[0]
    assert row["previous"] == 2.1
    assert row["previous3mean"] == pytest.approx((1.7 + 2.2 + 2.1) / 3)
    assert dict((entry["period"], entry["value"]) for entry in row["history"])["2026-08"] == 2.1


def test_missing_month_clears_old_mean_and_never_averages_nearby_months():
    cache.retain_successful_observations([cpi(values={"2026-06": 1.7, "2026-08": 2.6, "2026-09": 2.4})], NOW)
    row = cpi(values={"2026-09": 2.7})
    row["previous3mean"] = 999
    restored = cache.retain_successful_observations([row], NOW)[0]
    assert restored["previous"] == 2.6 and restored["previous3mean"] is None
    assert restored["previous3mean_reason"] == "three_consecutive_prior_months_unavailable"


@pytest.mark.parametrize("field,value", [
    ("source", "unverified ministry citation"), ("series_id", "901Y009/A"), ("unit", "index"),
    ("basis", "MoM"), ("seasonal_adjustment", "SA"), ("raw_unit", "2025=100"),
    ("history_frequency", "daily"),
])
def test_failure_does_not_restore_incompatible_source_units_or_series(field, value):
    cache.retain_successful_observations([cpi()], NOW)
    failed = dict(cpi(), actual=None, status="unavailable", missing_reason="http_503")
    failed[field] = value
    assert cache.retain_successful_observations([failed], NOW)[0]["actual"] is None


def test_failure_restores_stale_history_and_keeps_current_diagnostics():
    cache.retain_successful_observations([cpi()], NOW)
    failed = dict(cpi(), period="", actual=None, history=[], previous=None, previous3mean=None,
                  status="unavailable", missing_reason="request_failed:ReadTimeout",
                  request_metadata={"http_status": None, "transport_error": "ReadTimeout"},
                  forecast=999, release_at="2026-11-02", actual_minus_forecast=999)
    result = cache.retain_successful_observations([failed], NOW)[0]
    assert result["status"] == "stale" and result["period"] == "2026-09"
    assert result["previous"] == 2.6 and result["previous3mean"] == cpi()["previous3mean"]
    assert result["last_success_at"] == NOW.isoformat()
    assert result["request_metadata"] == failed["request_metadata"]
    assert result["forecast"] is None and result["release_at"] is None
    assert cache.collection_status(result) == "\uc751\ub2f5 \uc2dc\uac04 \ucd08\uacfc"


@pytest.mark.parametrize("mode", ["expired", "future", "pending", "event"])
def test_invalid_cache_or_nonreleased_event_never_promotes_old_actual(mode):
    cache.retain_successful_observations([cpi()], NOW)
    failed = dict(cpi(), actual=None, status="unavailable")
    now = NOW
    if mode == "expired":
        now += timedelta(days=200)
    elif mode == "future":
        now -= timedelta(days=1)
    elif mode == "pending":
        failed["status"] = "pending"
    else:
        failed["value_kind"] = "supplied_event"
    assert cache.retain_successful_observations([failed], now)[0]["actual"] is None


def test_older_success_cannot_roll_cache_back_or_carry_consensus_to_another_month():
    cache.retain_successful_observations([cpi()], NOW)
    older = cpi("2026-08", {"2026-08": 2.0})
    older.update(forecast=1.0, forecast_source="older month", actual_minus_forecast=1.0)
    row = cache.retain_successful_observations([older], NOW)[0]
    assert row["status"] == "stale" and row["period"] == "2026-09"
    assert row["collection_error"] == "provider_observation_older_than_last_success"
    assert row["forecast"] is None and row["actual_minus_forecast"] is None
    assert json.loads(cache.CACHE_PATH.read_text(encoding="utf-8"))["KR_CPI"]["period"] == "2026-09"


def test_old_stale_provider_response_cannot_replace_newer_saved_month():
    cache.retain_successful_observations([cpi()], NOW)
    older = dict(cpi("2026-08", {"2026-08": 2.0}), status="stale",
                 missing_reason="latest_completed_month_not_in_response")
    row = cache.retain_successful_observations([older], NOW)[0]
    assert row["period"] == "2026-09" and row["actual"] == HISTORY["2026-09"]
    assert row["status"] == "stale" and row["collection_error"] == older["missing_reason"]


def test_explicitly_incompatible_history_entry_does_not_fill_a_gap():
    saved = cpi(values={"2026-06": 1.7, "2026-08": 2.6, "2026-09": 2.4})
    saved["history"].append({"period": "2026-07", "value": 99, "unit": "index"})
    cache.retain_successful_observations([saved], NOW)
    row = cache.retain_successful_observations([cpi(values={"2026-09": 2.7})], NOW)[0]
    assert row["previous3mean"] is None
    assert "2026-07" not in {entry["period"] for entry in row["history"]}


class Response:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}
        self.closed = False

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return deepcopy(self.payload)

    def close(self):
        self.closed = True


@pytest.fixture
def public_cpi(monkeypatch):
    # Public primary-source sample responses verified on 2026-10-20. Rates are
    # always calculated in tests and production, never seeded from a user value.
    state = {"recent": {"202606": "119.99", "202607": "119.77", "202608": "120.05", "202609": "120.43"},
             "baseline": {"202506": "116.31", "202507": "116.52", "202508": "116.45", "202509": "117.06"},
             "calls": [], "responses": [], "bad_unit": False, "status": 200, "reject": False}
    stat, item, title, item_name = releases._ECOS_SERIES["KR_CPI"]

    def get(url, **kwargs):
        assert "/sample/json/kr/1/10/" in url and "params" not in kwargs
        assert kwargs["timeout"] == 4 and kwargs["allow_redirects"] is False
        state["calls"].append(url)
        if state["reject"]:
            payload = {"RESULT": {"CODE": "INFO-100", "MESSAGE": SECRET}}
        elif "StatisticItemList" in url:
            payload = {"StatisticItemList": {"row": [{"STAT_CODE": stat, "STAT_NAME": title,
                       "ITEM_CODE": item, "ITEM_NAME": item_name, "GRP_CODE": "Group1",
                       "CYCLE": "M", "UNIT_NAME": "2020=100"}]}}
        else:
            values = state["baseline"] if "/2025" in url else state["recent"]
            payload = {"StatisticSearch": {"row": [{"STAT_CODE": stat, "ITEM_CODE1": item,
                       "ITEM_NAME1": item_name, "TIME": month, "DATA_VALUE": value,
                       "UNIT_NAME": "wrong" if state["bad_unit"] else "2020=100"}
                       for month, value in values.items()]}}
        response = Response(payload, state["status"])
        state["responses"].append(response)
        return response

    monkeypatch.setattr(releases.requests, "get", get)
    return state


def test_public_primary_cpi_automatically_recovers_exact_prior_month_and_three_month_mean(public_cpi):
    base = releases._ecos(NOW, "", "KR_CPI")
    result = bulletins.apply_official_bulletins([base], NOW)[0]
    expected = {month: round((float(level) / float(public_cpi["baseline"][str(int(month) - 100)]) - 1) * 100, 1)
                for month, level in public_cpi["recent"].items()}
    assert result["actual"] == expected["202609"] and result["previous"] == expected["202608"]
    assert result["previous3mean"] == pytest.approx(sum(expected[month] for month in ("202606", "202607", "202608")) / 3, abs=1e-6)
    assert result["previous_period"] == "2026-08" and len(result["history"]) == 4
    assert result["status"] == "released" and result["fallback_access"] == "public_sample"
    assert result["primary_collection_error"] == "ECOS_API_KEY_missing" and result["release_at"] is None
    assert all(url.startswith(releases.ECOS_URL) for url in result["source_urls"])
    assert result["forecast"] is None and "verified_at" not in result
    assert len(public_cpi["calls"]) == 3 and all(response.closed for response in public_cpi["responses"])
    cached = bulletins.load_kr_cpi_bulletin(NOW)
    assert cached["bulletin_request_metadata"]["from_cache"] and len(public_cpi["calls"]) == 3


@pytest.mark.parametrize("mode,reason", [
    ("bad_unit", "ecos_observation_series_or_unit_mismatch"),
    ("missing_baseline", "ecos_cpi_exact_year_ago_unavailable"),
    ("reject", "ecos_metadata_rejected:INFO-100"), ("http", "http_503"),
])
def test_public_cpi_failure_preserves_last_success_without_manual_substitution(public_cpi, mode, reason):
    cache.retain_successful_observations([cpi()], NOW)
    if mode == "missing_baseline":
        del public_cpi["baseline"]["202509"]
    elif mode == "http":
        public_cpi["status"] = 503
    else:
        public_cpi[mode] = True
    stale = cache.retain_successful_observations([releases._ecos(NOW, "", "KR_CPI")], NOW)[0]
    result = bulletins.apply_official_bulletins([stale], NOW)[0]
    assert result["actual"] == 2.4 and result["previous"] == 2.6 and result["status"] == "stale"
    assert result["previous3mean"] == cpi()["previous3mean"]
    assert result["bulletin_collection_error"] == reason
    assert SECRET not in json.dumps(result)
    before = len(public_cpi["calls"])
    bulletins.load_kr_cpi_bulletin(NOW)
    assert len(public_cpi["calls"]) > before


def test_cpi_manual_ministry_snapshot_is_never_used_when_automatic_primary_fails(public_cpi):
    public_cpi["status"] = 503
    result = bulletins.apply_official_bulletins([releases._ecos(NOW, "", "KR_CPI")], NOW)[0]
    assert result["actual"] is None and result["previous"] is None and result["history"] == []
    assert result["bulletin_collection_error"] == "http_503"
    assert "cpi_automatic_primary_unavailable" in result["missing_reason"]
    assert result["source"] == "Bank of Korea ECOS" and "verified_at" not in result


def test_supplied_offline_cpi_does_not_trigger_network_or_use_manual_snapshot():
    row = releases._row("KR_CPI", "%", "YoY", "Bank of Korea ECOS", releases.ECOS_URL, NOW)
    result = bulletins.apply_official_bulletins([row], NOW)[0]
    assert result["actual"] is None and result["fallback_mode"] == "unavailable"
    assert result["bulletin_collection_error"] == "cpi_primary_automatic_fetch_not_enabled"


def test_public_cpi_older_month_is_stale_and_missing_history_is_explicit(public_cpi):
    del public_cpi["recent"]["202609"]
    del public_cpi["recent"]["202607"]
    row = bulletins.load_kr_cpi_bulletin(NOW)
    assert row["period"] == "2026-08" and row["status"] == "stale"
    assert row["previous"] is None and row["previous3mean"] is None
    assert row["observation_recency"] == "older_period"


def test_public_cpi_timeout_is_explicit_without_exposing_exception(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 4
        raise requests.ReadTimeout("credential-bearing-url/" + SECRET)

    monkeypatch.setattr(releases.requests, "get", timeout)
    row = bulletins.apply_official_bulletins([releases._ecos(NOW, "", "KR_CPI")], NOW)[0]
    assert row["actual"] is None and "ReadTimeout" in row["bulletin_collection_error"]
    assert row["bulletin_request_metadata"]["metadata"]["transport_error"] == "ReadTimeout"
    assert SECRET not in json.dumps(row)


@pytest.mark.parametrize("status,payload,reason", [
    (302, None, "census_api_key_required"), (403, None, "http_403"), (429, None, "http_429"),
    (200, ValueError(SECRET), "invalid_response"), (200, [HEADER], "census_no_valid_observations"),
    (200, [["cell_value"]], "census_invalid_columns"),
])
def test_census_report_row_and_logs_keep_sanitized_failure_evidence(monkeypatch, caplog, status, payload, reason):
    response = Response(payload, status, {"Location": "https://api.census.gov/data/missing_key.html?key=" + SECRET})
    monkeypatch.setattr(releases.requests, "get", lambda *args, **kwargs: response)
    with caplog.at_level(logging.INFO):
        row = releases._retail(NOW, SECRET)
    diagnostic = row["request_metadata"]
    assert diagnostic["http_status"] == status and reason in diagnostic["failure_reason"]
    assert diagnostic["publication_status"] == "unconfirmed" and row["publication_status"] == "unconfirmed"
    assert diagnostic["parameters"]["data_type_code"] == "MPCSM"
    assert diagnostic["parameters"]["time"] == "from 2025-01 to 2026-10"
    assert f"HTTP={status}" in caplog.text and "publication_status=unconfirmed" in caplog.text
    assert reason in caplog.text and SECRET not in json.dumps(row) + caplog.text
    assert response.closed


def test_census_stale_cache_keeps_failed_http_status_and_unconfirmed_publication(monkeypatch, caplog):
    response = Response([HEADER, ["0.8", "2026-09-01", "44X72", "MPCSM", "yes", "no"]])
    monkeypatch.setattr(releases.requests, "get", lambda *args, **kwargs: response)
    with caplog.at_level(logging.INFO):
        success = releases._retail(NOW, "")
    assert success["publication_status"] == "available"
    assert success["request_metadata"]["failure_reason"] == ""
    cache.retain_successful_observations([success], NOW)
    releases.clear_economic_releases_cache()
    response.status_code = 403
    failure = releases._retail(NOW, "")
    row = cache.retain_successful_observations([failure], NOW)[0]
    assert row["status"] == "stale" and row["actual"] == 0.8
    assert row["publication_status"] == "unconfirmed" and row["request_metadata"]["http_status"] == 403
    assert row["request_metadata"]["failure_reason"] == "http_403"
    assert row["request_metadata"]["publication_status"] == "unconfirmed"


def test_supplier_modules_register_loaded_fingerprints_without_requiring_restart(monkeypatch):
    modules = ("economic_releases", "economic_cache", "economic_bulletins")
    monkeypatch.setattr(report_build, "_RENDER_MODULES", ("market_memo", *modules))
    info = report_build.get_report_build_info()
    for name in modules:
        row = info["sources"]["stock_lab_core." + name]
        assert row["sha256"] not in {"unrecorded", "unavailable"}
        assert row["sha256"] == row["disk_sha256"]
    assert info["restart_required"] is False and info["stale_modules"] == []


def test_supplier_disk_change_requires_restart_without_relabeling_loaded_code(monkeypatch):
    monkeypatch.setattr(report_build, "_RENDER_MODULES", ("market_memo", "economic_cache"))
    before = report_build.get_report_build_info()
    target = before["sources"][cache.__name__]["path"]
    file_hash = report_build._file_hash
    monkeypatch.setattr(report_build, "_file_hash", lambda path: "modified-on-disk" if path == target else file_hash(path))
    after = report_build.get_report_build_info()
    assert after["restart_required"] is True and after["stale_modules"] == [cache.__name__]
    assert after["loaded_source_sha256"] == before["loaded_source_sha256"]
