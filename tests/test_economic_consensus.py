"""Offline contract fixtures, never production consensus or historical surveys."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
import requests

from stock_lab_core import economic_consensus as consensus


NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
KEY = "fixture-client:fixture-secret"
TARGET = {"indicator": "US_CPI", "period": "2026-09", "basis": "MoM", "unit": "%",
          "release_at": "2026-10-14T12:30:00+00:00", "actual": 0.6, "previous": 0.4}
# Structure from the provider schema, deliberately synthetic numeric values.
EVENT = {"Country": "United States", "Event": "Inflation Rate MoM", "Category": "Inflation Rate",
         "ReferenceDate": "2026-09-30T00:00:00", "Date": "2026-10-14T12:30:00",
         "DateSpan": "0", "Forecast": "0.2%", "TEForecast": "9.9%", "Actual": "8.8%",
         "Previous": "7.7%", "Unit": "%", "Source": "Official actual agency"}


class Response:
    def __init__(self, payload, status=200, raw=None):
        self.status_code, self.closed = status, False
        self.body = json.dumps(payload).encode() if raw is None else raw

    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def close(self):
        self.closed = True


class Fetch:
    def __init__(self, payload=None, status=200, raw=None):
        self.payload = [deepcopy(EVENT)] if payload is None else payload
        self.status, self.raw, self.calls, self.responses = status, raw, [], []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = Response(self.payload, self.status, self.raw)
        self.responses.append(response)
        return response


@pytest.fixture(autouse=True)
def clear_cache():
    consensus.clear_economic_consensus_cache()
    yield
    consensus.clear_economic_consensus_cache()


def load(fetch, rows=None, now=NOW):
    return consensus.load_economic_consensus([TARGET] if rows is None else rows, now, api_key=KEY, fetch=fetch)


def test_only_documented_survey_field_and_exact_key_are_returned():
    fetch = Fetch()
    original = deepcopy(TARGET)
    result = load(fetch)
    event, = result["events"]
    assert event["forecast"] == 0.2
    assert event["forecast_kind"] == "survey_consensus"
    assert event["forecast_source"] == consensus.PROVIDER
    assert event["forecast_source"] != EVENT["Source"]
    assert event["actual"] is event["previous"] is None
    assert consensus.consensus_key(event) == consensus.consensus_key(TARGET)
    assert TARGET == original
    url, kwargs = fetch.calls[0]
    assert url == consensus.API_URL + "united%20states/2026-10-14/2026-10-14"
    assert KEY not in url
    assert event["forecast_source_url"] == url
    assert kwargs["headers"]["Authorization"] == KEY
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == consensus.REQUEST_TIMEOUT
    assert fetch.responses[0].closed
    assert KEY not in str(result)


@pytest.mark.parametrize("updates", [
    {"ReferenceDate": "2026-08-31T00:00:00"}, {"ReferenceDate": None},
    {"ReferenceDate": "invalid", "Reference": "Sep"},
    {"Date": "2026-10-15T12:30:00"}, {"Date": None},
    {"DateSpan": "1"}, {"DateSpan": None},
    {"Event": "Inflation Rate YoY"}, {"Event": "Core Inflation Rate MoM"},
    {"Event": "Inflation Rate"}, {"Event": "CPI"},
    {"Country": "Canada"}, {"Unit": "K"},
    {"Forecast": ""}, {"Forecast": None}, {"Forecast": "NaN"},
    {"Forecast": "0.2K"}, {"Forecast": True}, {"Forecast": "Infinity"},
])
def test_missing_or_mismatched_fields_never_borrow_another_consensus(updates):
    result = load(Fetch([{**EVENT, **updates}]))
    assert result["events"] == []
    assert result["diagnostics"]["reason"] == "exact_consensus_unavailable"


def test_no_fallback_to_teforecast_numeric_extra_fields_actual_or_previous():
    event = {**EVENT, "Forecast": "", "ForecastValue": 999, "TEForecastValue": 999}
    assert load(Fetch([event]))["events"] == []


@pytest.mark.parametrize("updates", [
    {"period": ""}, {"period": "2026-13"}, {"period": "2026-09-30"},
    {"release_at": None}, {"release_at": "2026-10-14T12:30:00"},
    {"basis": "unknown"}, {"basis": []}, {"unit": "persons"},
    {"release_precision": "schedule_rule"}, {"release_time_confirmed": False},
    {"indicator": "US_FED_TARGET_UPPER"},
])
def test_incomplete_or_incompatible_target_prevents_fetch(updates):
    fetch = Fetch()
    assert load(fetch, [{**TARGET, **updates}])["events"] == []
    assert fetch.calls == []


def test_utc_release_date_and_year_boundary_require_explicit_reference():
    target = {**TARGET, "period": "2025-12", "release_at": "2026-01-15T00:30:00+09:00"}
    event = {**EVENT, "ReferenceDate": "2025-12-31T00:00:00", "Date": "2026-01-14T15:30:00"}
    assert load(Fetch([event]), [target])["events"][0]["period"] == "2025-12"
    assert load(Fetch([{**event, "ReferenceDate": "2026-12-31T00:00:00"}]), [target])["events"] == []


@pytest.mark.parametrize("forecast,unit,expected", [("125K", "K", 125), ("0.125M", "M", 125), (125, "K", 125)])
def test_payroll_units_are_explicit_and_normalized(forecast, unit, expected):
    target = {**TARGET, "indicator": "US_NONFARM_PAYROLLS", "unit": "thousand persons"}
    event = {**EVENT, "Event": "Non Farm Payrolls", "Unit": unit, "Forecast": forecast}
    assert load(Fetch([event]), [target])["events"][0]["forecast"] == expected


def test_multiple_countries_basis_and_core_are_kept_separate():
    kr = {**TARGET, "indicator": "KR_EXPORTS", "basis": "YoY"}
    core = {**TARGET, "indicator": "US_CORE_CPI"}
    events = [EVENT, {**EVENT, "Country": "South Korea", "Event": "Exports YoY", "Forecast": "4%"},
              {**EVENT, "Event": "Core Inflation Rate MoM", "Forecast": "0.3%"}]
    fetch = Fetch(events)
    result = load(fetch, [TARGET, kr, core])
    assert {event["indicator"]: event["forecast"] for event in result["events"]} == {
        "US_CPI": 0.2, "US_CORE_CPI": 0.3, "KR_EXPORTS": 4}
    assert "south%20korea,united%20states/" in fetch.calls[0][0]


def test_conflicting_duplicate_exact_events_fail_closed():
    result = load(Fetch([EVENT, {**EVENT, "Forecast": "0.3%"}, EVENT]))
    assert result["events"] == []
    assert result["diagnostics"]["reason"] == "conflicting_consensus"


@pytest.mark.parametrize("key,reason", [(None, "api_key_required"), ("", "api_key_required"),
                                      ("guest:guest", "guest_access_discontinued")])
def test_no_credential_or_discontinued_guest_never_calls_network(key, reason):
    fetch = Fetch()
    result = consensus.load_economic_consensus([TARGET], NOW, api_key=key, fetch=fetch, public_fallback=False)
    assert not fetch.calls
    assert result["diagnostics"]["reason"] == reason
    assert result["diagnostics"]["setup_url"] == consensus.SETUP_URL


@pytest.mark.parametrize("status,reason", [(401, "api_key_rejected"), (403, "calendar_subscription_required"),
    (410, "guest_access_discontinued"), (429, "rate_limited"), (302, "http_error"), (503, "http_error")])
def test_http_failures_have_safe_diagnostics_and_close_response(status, reason):
    fetch = Fetch(status=status, raw=KEY.encode())
    result = load(fetch)
    assert result["events"] == []
    assert result["diagnostics"]["reason"] == reason
    assert result["diagnostics"]["http_status"] == status
    assert KEY not in str(result)
    assert fetch.responses[0].closed
    assert load(fetch)["diagnostics"]["from_cache"] is True
    assert len(fetch.calls) == 1


def test_transport_exception_cannot_expose_api_key():
    def fetch(*args, **kwargs):
        raise requests.Timeout("url or Authorization: " + KEY)
    result = load(fetch)
    assert result["diagnostics"]["reason"] == "request_failed"
    assert KEY not in str(result)


def test_cache_expires_is_bounded_isolated_and_returns_copies(monkeypatch):
    tick = [10.0]
    monkeypatch.setattr(consensus.time, "monotonic", lambda: tick[0])
    fetch = Fetch()
    first = load(fetch)
    first["events"][0]["forecast"] = 900
    cached = load(fetch)
    assert cached["diagnostics"]["from_cache"] is True
    assert cached["events"][0]["forecast"] == 0.2
    assert len(fetch.calls) == 1
    tick[0] += consensus.CACHE_TTL + 1
    assert load(fetch)["diagnostics"]["from_cache"] is False
    assert len(fetch.calls) == 2
    assert load(Fetch())["diagnostics"]["from_cache"] is False
    for i in range(consensus._CACHE_LIMIT + 1):
        consensus.load_economic_consensus([TARGET], NOW, api_key="fixture-" + str(i), fetch=fetch)
    assert len(consensus._CACHE) == consensus._CACHE_LIMIT


def test_cache_never_reuses_a_future_retrieval_or_another_month():
    fetch = Fetch()
    load(fetch)
    assert load(fetch, now=NOW - timedelta(days=1))["diagnostics"]["from_cache"] is False
    assert load(fetch, [{**TARGET, "period": "2026-08"}])["events"] == []


@pytest.mark.parametrize("payload,raw,reason", [
    ({"error": KEY}, None, "invalid_response"), ([], b"<html>" + KEY.encode(), "invalid_response"),
    ([EVENT] * (consensus.MAX_PROVIDER_ROWS + 1), None, "too_many_provider_rows"),
    ([], b" " * (consensus.MAX_RESPONSE_BYTES + 1), "response_too_large"),
], ids=["non-list-json", "html", "row-limit", "byte-limit"])
def test_body_and_schema_limits_fail_closed(payload, raw, reason):
    fetch = Fetch(payload, raw=raw)
    result = load(fetch)
    assert result["events"] == []
    assert result["diagnostics"]["reason"] == reason
    assert KEY not in str(result)
    assert fetch.responses[0].closed


def test_input_window_and_row_limits_prevent_requests():
    fetch = Fetch()
    assert load(fetch, [TARGET] * (consensus.MAX_RELEASE_ROWS + 1))["diagnostics"]["reason"] == "too_many_release_rows"
    assert load(fetch, [TARGET, {**TARGET, "release_at": "2027-01-01"}])["diagnostics"]["reason"] == "release_window_too_wide"
    assert fetch.calls == []


# Synthetic fixture reproducing only the inspected public #calendar markup.
# All four live pages returned 200 on 2026-10-21; no gated history was requested.
def public_html(*, title="Inflation Rate YoY", category="Inflation Rate", release="2026-10-14",
                reference="Sep", forecast="0.2%", teforecast="9.9%"):
    return f"""<html><table id="calendar" class="table table-hover">
    <thead><tr><th>Calendar</th><th colspan="2">GMT</th><th>Reference</th>
    <th>Actual</th><th>Previous</th><th>Consensus</th><th>TEForecast</th></tr></thead>
    <tbody><tr data-id="fixture-event" data-country="United States" data-category="{category}">
    <td>{release}</td><td>12:30 PM</td><td><div class="d-none">{title}</div></td>
    <td id="reference">{reference}</td><td id="actual">8.8%</td><td id="previous">7.7%</td>
    <td>{forecast}</td><td>{teforecast}</td></tr></tbody></table></html>""".encode()


PUBLIC_TARGET = {
    **TARGET, "basis": "YoY", "source_url": "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0",
    "value_kind": "calculated_from_official_levels",
    "release_source_url": "https://www.bls.gov/schedule/news_release/cpi.htm",
}


def public_load(fetch, rows=None, **kwargs):
    return consensus.load_economic_consensus([PUBLIC_TARGET] if rows is None else rows, NOW,
                                            fetch=fetch, **kwargs)


def test_public_default_needs_no_key_and_uses_only_visible_survey_consensus():
    fetch = Fetch(raw=public_html())
    result = public_load(fetch)
    event, = result["events"]
    assert event["forecast"] == 0.2
    assert event["period"] == PUBLIC_TARGET["period"]
    assert event["provider_reference"] == "Sep"
    assert event["forecast_period_source"] == "verified_official_row_exact_release_join"
    assert event["actual"] is event["previous"] is None
    assert consensus.consensus_key(event) == consensus.consensus_key(PUBLIC_TARGET)
    assert event["forecast_source_url"] == consensus._PUBLIC_ROOT + "inflation-cpi"
    assert result["diagnostics"]["access_mode"] == "public"
    assert result["diagnostics"]["http_status"] == 200
    url, kwargs = fetch.calls[0]
    assert url == event["forecast_source_url"]
    assert "Authorization" not in kwargs["headers"]
    assert "params" not in kwargs
    assert kwargs["allow_redirects"] is False
    assert fetch.responses[0].closed


@pytest.mark.parametrize("updates", [
    {"source_url": None}, {"release_source_url": None}, {"value_kind": "supplied_event"},
    {"source_url": "https://api.bls.gov.attacker.test/data"},
    {"release_source_url": "https://example.test/calendar"},
    {"basis": "MoM"}, {"indicator": "US_CORE_CPI"}, {"release_precision": "schedule_rule"},
])
def test_public_requires_verified_official_identity_and_date(updates):
    fetch = Fetch(raw=public_html())
    assert public_load(fetch, [{**PUBLIC_TARGET, **updates}])["events"] == []
    assert not fetch.calls


@pytest.mark.parametrize("options", [
    {"release": "2026-10-15"}, {"reference": "Aug"}, {"forecast": ""},
    {"forecast": "0.2K"}, {"forecast": "0.2"}, {"forecast": "NaN"},
])
def test_public_exact_date_month_and_units_have_no_fallback(options):
    result = public_load(Fetch(raw=public_html(**options)))
    assert result["events"] == []
    assert result["diagnostics"]["public"]["reason"] == "exact_public_consensus_unavailable"


@pytest.mark.parametrize("change,reason", [
    (lambda body: body.replace(b"<th>Consensus</th>", b"<th>Forecast</th>"), "public_schema_changed"),
    (lambda body: body.replace(b">2026-10-14<", b">Oct 14<"), "public_full_release_date_required"),
    (lambda body: body.replace(b"Inflation Rate YoY", b"Core Inflation Rate YoY"), "public_schema_changed"),
    (lambda body: body.replace(b'id="reference"', b'id="unknown"'), "public_schema_changed"),
    (lambda body: b"<html><p>Sign in</p></html>", "public_schema_changed"),
])
def test_public_schema_or_gating_changes_fail_closed(change, reason):
    result = public_load(Fetch(raw=change(public_html())))
    assert result["events"] == []
    assert result["diagnostics"]["public"]["sources"][0]["reason"] == reason


def test_public_does_not_infer_year_and_rejects_ambiguous_official_periods():
    # The verified official December period is retained across January exactly.
    target = {**PUBLIC_TARGET, "period": "2025-12", "release_at": "2026-01-14"}
    fetch = Fetch(raw=public_html(release="2026-01-14", reference="Dec"))
    assert public_load(fetch, [target])["events"][0]["period"] == "2025-12"
    ambiguous = {**target, "period": "2024-12"}
    other_fetch = Fetch(raw=public_html(release="2026-01-14", reference="Dec"))
    assert public_load(other_fetch, [target, ambiguous])["events"] == []
    assert not other_fetch.calls


def test_public_cache_rejoins_against_current_official_targets():
    fetch = Fetch(raw=public_html())
    public_load(fetch)
    result = public_load(fetch)
    assert result["diagnostics"]["from_cache"] is True
    assert len(fetch.calls) == 1
    assert public_load(fetch, [{**PUBLIC_TARGET, "period": "2026-08"}])["events"] == []


def test_public_supports_exactly_the_four_inspected_pages():
    rows, calls = [], []
    expected = {}
    for spec, (url, title, category, domain) in consensus._PUBLIC_PAGES.items():
        rows.append({**PUBLIC_TARGET, "indicator": spec[0], "basis": spec[1], "unit": spec[2],
                     "source_url": "https://api." + domain + "/official-observations",
                     "release_source_url": "https://www." + domain + "/official-release"})
        expected[url] = public_html(title=title, category=category,
                                    forecast="125K" if spec[2] == "thousand persons" else "0.2%")

    def fetch(url, **kwargs):
        calls.append(url)
        assert "Authorization" not in kwargs["headers"]
        return Response([], raw=expected[url])

    result = public_load(fetch, rows)
    assert len(result["events"]) == 4
    assert len(calls) == 4
    assert next(event for event in result["events"] if event["indicator"] == "US_NONFARM_PAYROLLS")["forecast"] == 125


def test_api_failure_can_fall_back_without_sending_credentials_to_public_page():
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        if url.startswith(consensus.API_URL):
            assert kwargs["headers"]["Authorization"] == KEY
            return Response([], status=403)
        assert "Authorization" not in kwargs["headers"]
        return Response([], raw=public_html())

    result = public_load(fetch, api_key=KEY)
    assert len(result["events"]) == 1
    assert result["diagnostics"]["access_mode"] == "api_and_public"
    assert len(calls) == 2


@pytest.mark.parametrize("status", [302, 403, 429])
def test_public_block_or_redirect_is_not_retried_or_bypassed(status):
    fetch = Fetch(status=status, raw=b"gated")
    result = public_load(fetch)
    assert result["events"] == []
    assert result["diagnostics"]["public"]["sources"][0]["http_status"] == status
    assert len(fetch.calls) == 1
