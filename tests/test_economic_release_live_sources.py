"""Offline fixtures based on Census MARTS and the Customs public monthly board."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging

import pytest
import requests

from stock_lab_core import economic_bulletins as bulletins
from stock_lab_core import economic_cache
from stock_lab_core import economic_releases as releases


NOW = datetime(2026, 10, 20, 3, tzinfo=timezone.utc)
SECRET = "fixture-private-key"
HEADER = ["cell_value", "time_slot_date", "category_code", "data_type_code", "seasonally_adj", "error_data"]
RETAIL = [HEADER, ["0.8", "2026-09-01", "44X72", "MPCSM", "yes", "no"]]

# Minimal structure of the official board and 2026-10-15 final-release HTML.
# Source: https://www.customs.go.kr/kcs/na/ntt/selectNttList.do?bbsId=1362&mi=2891
LISTING = """
<table class="bbsList"><tbody><tr>
<td data-table="subject"><a class="nttInfoBtn" href="javascript:"
 title="2026년 9월 월간 수출입 현황 [확정치]"
 data-id="10179763" data-url="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">release</a></td>
<td data-table="date">2026.10.15</td></tr></tbody></table>
"""
DETAIL = """
<h3>2026년 9월 월간 수출입 현황 [확정치]</h3>
<table class="bbsView"><tbody>
<tr><th>등록일</th><td>2026.10.15</td></tr>
<tr><td class="conts"><div class="conts">
<p>(단위: 백만 달러, %)</p>
<table><tbody>
<tr><td rowspan="2">구분</td><td colspan="2"><span>2025</span>년</td><td colspan="3">2026년</td></tr>
<tr><td>9월</td><td>1~9월</td><td>8월</td><td>9월</td><td>1~9월</td></tr>
<tr><td>수  출<br>(전년동기대비)</td>
<td><p>65,904</p><p>(12.6)</p></td><td>519,552 (2.2)</td>
<td>98,374 (68.9)</td><td><u>121,050</u> (<span>83.7</span>)</td><td>814,724 (56.8)</td></tr>
<tr><td>수입(전년동기대비)</td><td>56,420 (8.3)</td><td>469,732 (△0.4)</td>
<td>63,494 (22.4)</td><td>71,078 (26.0)</td><td>562,293 (19.7)</td></tr>
</tbody></table></div></td></tr></tbody></table>
"""


class Response:
    def __init__(self, payload=None, text="", status=200, headers=None):
        self.payload, self.text, self.status_code = payload, text, status
        self.headers, self.closed = headers or {}, False
        self.url = "https://api.census.gov/?key=" + SECRET

    def json(self):
        if self.payload is None:
            raise ValueError(self.url)
        return deepcopy(self.payload)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated_sources(monkeypatch):
    releases.clear_economic_releases_cache()

    def no_network(*args, **kwargs):
        pytest.fail("Tests must use an explicit official-source fixture")

    monkeypatch.setattr(releases.requests, "get", no_network)
    monkeypatch.setattr(releases.requests, "post", no_network)
    yield
    releases.clear_economic_releases_cache()


@pytest.fixture
def census(monkeypatch):
    state = {"response": Response(RETAIL), "calls": []}

    def get(url, **kwargs):
        assert url == releases.CENSUS_URL
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == 4
        state["calls"].append(kwargs)
        return state["response"]

    monkeypatch.setattr(releases.requests, "get", get)
    return state


@pytest.mark.parametrize("status", [204, 302, 400, 401, 403, 429, 503])
def test_http_failure_status_and_parameters_are_safe(census, caplog, status):
    census["response"] = Response(status=status, text=SECRET, headers={
        "Location": "https://api.census.gov/data/missing_key.html?key=" + SECRET})
    with caplog.at_level(logging.INFO):
        row = releases._retail(NOW, SECRET)
    assert row["api_key_configured"] is True
    assert row["request_metadata"]["http_status"] == status
    assert row["request_metadata"]["parameters"]["category_code"] == "44X72"
    assert row["request_metadata"]["parameters"]["time"] == "from 2025-01 to 2026-10"
    assert row["publication_status"] == "unconfirmed" and row["actual"] is None
    assert f"http_{status}" in row["missing_reason"]
    assert SECRET not in json.dumps(row) + caplog.text
    assert "?key=" not in json.dumps(row) + caplog.text
    assert census["response"].closed
    if status == 302:
        assert row["request_metadata"]["response_status"] == "api_key_required"
    releases._retail(NOW, SECRET)
    assert len(census["calls"]) == 2  # Failures are never success-cache entries.


def test_allowlisted_parameter_names_do_not_allow_arbitrary_secret_values(census, caplog):
    with caplog.at_level(logging.INFO):
        releases._request(releases.CENSUS_URL, params={
            "key": SECRET, "get": "cell_value," + SECRET,
            "time": "https://example.test/?key=" + SECRET, "category_code": SECRET,
            "data_type_code": "MPCSM", "seasonally_adj": "yes", "error_data": "no",
            "unexpected": SECRET})
    assert SECRET not in caplog.text and "https://" not in caplog.text
    assert "[redacted]" in caplog.text and "MPCSM" in caplog.text


def test_bad_json_and_transport_exceptions_never_escape_with_credentials(census, monkeypatch, caplog):
    census["response"] = Response(text=SECRET)
    with pytest.raises(ValueError) as error:
        releases._request(releases.CENSUS_URL, params={"key": SECRET})
    assert SECRET not in str(error.value)
    row = releases._retail(NOW, SECRET)
    assert row["request_metadata"]["http_status"] == 200
    assert row["request_metadata"]["response_status"] == "response_not_json"
    assert row["publication_status"] == "unconfirmed"

    def fail(*args, **kwargs):
        raise requests.Timeout("https://api.census.gov/?key=" + SECRET)

    monkeypatch.setattr(releases.requests, "get", fail)
    row = releases._retail(NOW, SECRET)
    assert row["request_metadata"]["http_status"] is None
    assert row["request_metadata"]["transport_error"] == "Timeout"
    assert SECRET not in json.dumps(row) + caplog.text


@pytest.mark.parametrize("payload,reason", [
    ({"error": SECRET}, "census_invalid_response"),
    ([[*HEADER, "cell_value"]], "census_invalid_columns"),
    ([["cell_value"], ["0.8"]], "census_invalid_columns"),
    ([HEADER, None], "census_invalid_row"),
    ([HEADER, ["0.8"]], "census_invalid_row"),
    ([HEADER, RETAIL[1], ["9.9", *RETAIL[1][1:]]], "census_conflicting_observations"),
])
def test_census_malformed_data_fails_closed(census, payload, reason):
    census["response"] = Response(payload)
    row = releases._retail(NOW, SECRET)
    assert row["actual"] is None and reason in row["missing_reason"]
    assert SECRET not in json.dumps(row)


@pytest.mark.parametrize("cell,index", [
    ("NaN", 0), ("Infinity", 0), (True, 0),
    ("2026-10-01", 1), ("2026-11-01", 1), ("2024-09-01", 1), ("2026-99-01", 1),
    ("44000", 2), ("SM", 3), ("no", 4), ("yes", 5),
])
def test_census_filters_nonfinite_wrong_series_and_unfinished_months(census, cell, index):
    bad = list(RETAIL[1])
    bad[index] = cell
    census["response"] = Response([HEADER, bad])
    row = releases._retail(NOW, SECRET)
    assert row["actual"] is None and row["history"] == []
    assert row["publication_status"] == "unconfirmed"


def test_success_cache_is_current_only_for_the_actual_observation_month(census):
    fresh = releases._retail(NOW, SECRET)
    assert fresh["status"] == "released" and fresh["actual"] == 0.8
    assert fresh["observation_recency"] == "latest_completed_month"
    assert fresh["request_metadata"]["latest_observation_period"] == "2026-09"
    assert fresh["publication_status"] == "available"
    fresh["request_metadata"]["parameters"]["category_code"] = "tampered"
    cached = releases._retail(NOW, SECRET)
    assert cached["request_metadata"]["from_cache"]
    assert cached["request_metadata"]["http_status"] == 200
    assert cached["request_metadata"]["parameters"]["category_code"] == "44X72"
    releases.clear_economic_releases_cache()
    census["response"] = Response([HEADER, ["0.5", "2026-07-01", *RETAIL[1][2:]]])
    old = releases._retail(NOW, SECRET)
    assert old["status"] == "stale" and old["observation_recency"] == "older_period"
    assert old["period"] == "2026-07" and old["latest_completed_period"] == "2026-09"
    assert "latest_completed_month_not_in_response" in old["missing_reason"]


def test_failed_refresh_preserves_public_cache_without_claiming_current_publication(census, monkeypatch):
    economic_cache.retain_successful_observations([releases._retail(NOW, SECRET)], NOW)
    releases.clear_economic_releases_cache()
    census["response"] = Response(status=403)
    monkeypatch.setattr(releases, "_api_key", lambda name: SECRET if name == "CENSUS_API_KEY" else "")
    monkeypatch.setattr(releases, "_bls", lambda now: [])
    monkeypatch.setattr(releases, "_fed", lambda now, key: releases._row("US_FED_TARGET_UPPER", "%", "level", "", "", now))
    monkeypatch.setattr(releases, "load_release_calendar", lambda **kwargs: {"sources": [], "events": []})
    # Keep the BLS zip empty when testing this narrowly scoped integration.
    monkeypatch.setattr(releases, "_BLS_SERIES", ())
    row = next(row for row in releases.load_economic_releases(now=NOW) if row["indicator"] == "US_RETAIL_SALES")
    assert row["status"] == "stale" and row["actual"] == 0.8
    assert row["publication_status"] == "unconfirmed" and row["observation_recency"] == "stale"
    assert row["request_metadata"]["http_status"] == 403
    assert row["collection_error"] == "http_403"
    assert SECRET not in json.dumps(row)
    saved = json.loads(economic_cache.CACHE_PATH.read_text(encoding="utf-8"))
    assert "request_metadata" not in saved["US_RETAIL_SALES"] and SECRET not in json.dumps(saved)


@pytest.fixture
def customs(monkeypatch):
    state = {"listing": LISTING, "detail": DETAIL, "status": 200, "calls": [], "responses": []}

    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == 4
        assert url in {bulletins.CUSTOMS_LIST_URL, bulletins.CUSTOMS_DETAIL_URL}
        assert "key" not in kwargs["params"]
        state["calls"].append((url, kwargs))
        if url == bulletins.CUSTOMS_DETAIL_URL:
            assert kwargs["params"]["nttSn"] == "10179763"
            assert kwargs["params"]["nttSnUrl"] == "a" * 32
        text = state["listing"] if url == bulletins.CUSTOMS_LIST_URL else state["detail"]
        response = Response(text=text, status=state["status"])
        state["responses"].append(response)
        return response

    monkeypatch.setattr(releases.requests, "get", get)
    return state


def test_official_customs_table_preserves_final_vintage_and_revised_previous(customs):
    row = bulletins.load_kr_exports_bulletin(NOW)
    assert (row["actual"], row["previous"], row["period"]) == (83.7, 68.9, "2026-09")
    assert (row["raw_actual"], row["raw_year_ago"]) == (121050, 65904)
    assert row["release_at"] == "2026-10-15" and row["previous_period"] == "2026-08"
    assert row["status"] == "released" and row["fallback_mode"] == "automatic_official"
    assert row["data_vintage"] == "final_bulletin" and row["value_kind"] == "official_bulletin"
    assert row["history"] == [] and row["forecast"] is None and row["previous3mean"] is None
    assert row["bulletin_request_metadata"]["listing"]["http_status"] == 200
    assert row["bulletin_request_metadata"]["detail"]["http_status"] == 200
    cached = bulletins.load_kr_exports_bulletin(NOW)
    assert cached["bulletin_request_metadata"]["from_cache"]
    assert len(customs["calls"]) == 2 and all(r.closed for r in customs["responses"])


@pytest.mark.parametrize("old,new", [
    ("[확정치]", "[잠정치]"),
    ("2026년 9월 월간", "2026년 9월 1일~20일"),
    ("2026.10.15", "2026.10.30"),
    ('data-id="10179763"', 'data-id="https://example.test"'),
    ('data-url="' + "a" * 32 + '"', 'data-url="https://example.test"'),
])
def test_listing_rejects_partial_preliminary_future_and_untrusted_targets(customs, old, new):
    customs["listing"] = LISTING.replace(old, new)
    row = bulletins.load_kr_exports_bulletin(NOW)
    assert row["actual"] is None and "customs_monthly_final_not_found" in row["missing_reason"]
    assert len(customs["calls"]) == 1


@pytest.mark.parametrize("old,new", [
    ("백만 달러", "천 달러"), ("83.7", "26.0"), ("65,904", "0"),
    ("2026.10.15", "2026.10.16"), ("2026년 9월 월간", "2026년 8월 월간"),
    ("<td>9월</td><td>1~9월</td></tr>", "<td>1~9월</td><td>1~9월</td></tr>"),
    ('colspan="3"', 'colspan="999999"'),
])
def test_customs_detail_rejects_wrong_units_periods_values_dates_and_spans(customs, old, new):
    customs["detail"] = DETAIL.replace(old, new)
    row = bulletins.load_kr_exports_bulletin(NOW)
    assert row["actual"] is None and row["status"] == "unavailable"
    assert row["missing_reason"].startswith("customs_")
    customs["detail"] = DETAIL
    assert bulletins.load_kr_exports_bulletin(NOW)["actual"] == 83.7
    assert len(customs["calls"]) == 4


def test_previous_must_be_exact_prior_month_and_accepts_negative_rate(customs):
    customs["detail"] = DETAIL.replace("68.9", "△2.5")
    assert bulletins.load_kr_exports_bulletin(NOW)["previous"] == -2.5
    releases.clear_economic_releases_cache()
    customs["detail"] = DETAIL.replace("<td>8월</td>", "<td>7월</td>")
    row = bulletins.load_kr_exports_bulletin(NOW)
    assert row["previous"] is None and row["previous_period"] == "2026-08"


def test_table_headers_handle_january_year_boundary():
    entry = {"period": "2027-01", "release_at": "2027-02-15",
             "title": "2027년1월월간수출입현황[확정치]"}
    html = """
    <h3>2027년 1월 월간 수출입 현황 [확정치]</h3>
    <table class="bbsView"><tr><th>등록일</th><td>2027.02.15</td></tr>
    <tr><td><p>(단위: 백만 달러, %)</p><table>
    <tr><td rowspan="2">구분</td><td colspan="2">2026년</td><td>2027년</td></tr>
    <tr><td>1월</td><td>12월</td><td>1월</td></tr>
    <tr><td>수출(전년동기대비)</td><td>50 (0.0)</td><td>60 (5.0)</td><td>55 (10.0)</td></tr>
    </table></td></tr></table>"""
    row = bulletins._customs_observation(html, entry)
    assert row["previous_period"] == "2026-12" and row["previous"] == 5.0
    assert row["raw_year_ago_period"] == "2026-01" and row["actual"] == 10


def test_old_bulletin_is_not_fresh_just_because_http_succeeded(customs):
    row = bulletins.load_kr_exports_bulletin(NOW + timedelta(days=40))
    assert row["status"] == "stale" and row["observation_recency"] == "older_period"
    assert row["period"] == "2026-09" and row["retrieved_at"] is not None
    assert "latest_completed_month_not_in_bulletin" in row["missing_reason"]


def test_collector_hook_uses_live_source_before_manual_and_persists_only_public_data(customs):
    base = releases._ecos(NOW, "", "KR_EXPORTS")
    base.update(forecast=999, forecast_source="different month", actual_minus_forecast=999)
    original = deepcopy(base)
    row = bulletins.apply_official_bulletins([base], NOW)[0]
    assert row["status"] == "released" and row["actual"] == 83.7
    assert row["fallback_mode"] == "automatic_official"
    assert row["primary_collection_error"] == "ECOS_API_KEY_missing"
    assert row["forecast"] is None and row["actual_minus_forecast"] is None
    assert base == original and row["api_key_configured"] is False
    assert "expires_at" not in row
    saved = json.loads(economic_cache.CACHE_PATH.read_text(encoding="utf-8"))
    assert saved["KR_EXPORTS"]["actual"] == 83.7
    assert "bulletin_request_metadata" not in saved["KR_EXPORTS"]
    assert "forecast" not in saved["KR_EXPORTS"]


@pytest.mark.parametrize("status", [302, 403, 503])
def test_live_failure_retains_manual_fallback_and_original_expiry(customs, status):
    customs["status"] = status
    base = releases._ecos(NOW, "", "KR_EXPORTS")
    row = bulletins.apply_official_bulletins([base], NOW)[0]
    assert row["status"] == "verified_snapshot" and row["actual"] == 83.7
    assert row["fallback_mode"] == "manual_verified"
    assert row["expires_at"] == "2026-11-03"
    assert row["bulletin_collection_error"] == f"http_{status}"
    assert row["bulletin_request_metadata"]["listing"]["http_status"] == status
    expired = bulletins.apply_official_bulletins([base], NOW.replace(month=11, day=3))[0]
    assert expired["actual"] is None
    assert not economic_cache.CACHE_PATH.exists()


def test_live_collection_works_after_manual_expiry(customs):
    customs["listing"] = LISTING.replace("9월", "10월").replace("2026.10.15", "2026.11.15")
    customs["detail"] = (DETAIL.replace("9월", "10월").replace("8월", "9월")
                         .replace("2026.10.15", "2026.11.15"))
    now = NOW.replace(month=11, day=20)
    row = bulletins.apply_official_bulletins([releases._ecos(now, "", "KR_EXPORTS")], now)[0]
    assert row["period"] == "2026-10" and row["status"] == "released"
    assert row["fallback_mode"] == "automatic_official" and "expires_at" not in row


def test_stale_success_survives_later_failure_without_becoming_manual_or_live(customs):
    base = releases._ecos(NOW, "", "KR_EXPORTS")
    success = bulletins.apply_official_bulletins([base], NOW)[0]
    releases.clear_economic_releases_cache()
    retained = economic_cache.retain_successful_observations([base], NOW)[0]
    assert retained["status"] == "stale"
    customs["status"] = 503
    row = bulletins.apply_official_bulletins([retained], NOW)[0]
    assert row["status"] == "stale" and row["actual"] == success["actual"]
    assert row["bulletin_collection_error"] == "http_503"


def test_current_provider_and_supplied_events_do_not_trigger_bulletin_fetch():
    current = releases._ecos(NOW, "", "KR_EXPORTS")
    current.update(status="released", actual=84, period="2026-09")
    assert bulletins.apply_official_bulletins([current], NOW) == [current]
    event = dict(current, value_kind="supplied_event", period="2026-10", status="pending", actual=None)
    assert bulletins.apply_official_bulletins([event], NOW) == [event]


def test_direct_bulletin_failure_restores_automatic_cache_before_manual(customs):
    base = releases._ecos(NOW, "", "KR_EXPORTS")
    success = bulletins.apply_official_bulletins([base], NOW)[0]
    releases.clear_economic_releases_cache()
    customs["status"] = 503
    # Deliberately skip the primary-provider cache wrapper to test this fallback.
    row = bulletins.apply_official_bulletins([base], NOW)[0]
    assert row["actual"] == success["actual"] and row["status"] == "stale"
    assert row["source"] == "Korea Customs Service (monthly final bulletin)"
    assert row["last_success_at"] == success["retrieved_at"]
    assert row["bulletin_request_metadata"]["listing"]["http_status"] == 503
    assert row["bulletin_collection_error"] == "http_503"
    assert row.get("fallback_mode") != "manual_verified"


def test_same_month_ecos_vintage_not_downgraded_by_final_bulletin(customs):
    row = releases._ecos(NOW, "", "KR_EXPORTS")
    row.update(status="stale", actual=84.1, period="2026-09", last_success_at=NOW.isoformat())
    result = bulletins.apply_official_bulletins([row], NOW)[0]
    assert result["actual"] == 84.1 and result["status"] == "stale"
    assert result["bulletin_not_applied"] == "existing_period_or_vintage_preserved"
    assert "bulletin_collection_error" not in result


def test_bulletin_timeout_and_oversized_html_fail_without_secrets(customs, monkeypatch):
    def fail(*args, **kwargs):
        raise requests.Timeout("https://example.test/?key=" + SECRET)

    monkeypatch.setattr(releases.requests, "get", fail)
    row = bulletins.load_kr_exports_bulletin(NOW)
    assert row["actual"] is None and "Timeout" in row["missing_reason"]
    assert row["bulletin_request_metadata"]["listing"]["transport_error"] == "Timeout"
    assert SECRET not in json.dumps(row)
    with pytest.raises(ValueError, match="customs_invalid_page"):
        bulletins._customs_listing(" " * (bulletins._MAX_HTML + 1), NOW)


def test_manual_snapshot_is_not_used_for_wrong_units():
    row = releases._row("KR_EXPORTS", "USD", "YoY", "supplied", "", NOW)
    assert bulletins.apply_official_bulletins([row], NOW) == [row]
