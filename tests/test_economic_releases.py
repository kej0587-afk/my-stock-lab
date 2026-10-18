"""Official-provider fixtures only; these tests never contact the network."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
import requests

from stock_lab_core import economic_releases as releases
from stock_lab_core import release_calendar


NOW = datetime(2026, 10, 18, 3, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload=None, *, text="", status=200):
        self.payload = payload
        self.text = text
        self.status_code = status
        self.closed = False

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return deepcopy(self.payload)

    def close(self):
        self.closed = True


def _observations(values):
    return [{"year": period[:4], "period": "M" + period[5:], "value": str(value)}
            for period, value in values.items()]


@pytest.fixture
def providers(monkeypatch):
    releases.clear_economic_releases_cache()
    monkeypatch.setattr(releases, "_api_key", lambda name: "")
    state = {"calls": [], "responses": [], "bls_error": None, "schedule_status": 200,
             "census_error": None}
    series = []
    for spec in releases._BLS_SERIES:
        values = {"2025-08": 100, "2025-09": 100, "2026-07": 101,
                  "2026-08": 102, "2026-09": 103}
        if spec.mode == "change":
            values = {"2026-07": 150000, "2026-08": 150200, "2026-09": 150450}
        if spec.mode == "level":
            values = {"2026-08": 4.1, "2026-09": 4.2}
        series.append({"seriesID": spec.series, "data": _observations(values)})
    state["bls"] = {"status": "REQUEST_SUCCEEDED", "Results": {"series": series}}
    state["census"] = [
        ["cell_value", "time_slot_date", "category_code", "data_type_code", "seasonally_adj", "error_data"],
        ["0.6", "2026-08-01", "44X72", "MPCSM", "yes", "no"],
        ["0.2", "2026-09-01", "44X72", "MPCSM", "yes", "no"],
    ]
    state["schedule"] = """<table><tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
        <tr><td>September 2026</td><td>Oct. 14, 2026</td><td>08:30 AM</td></tr>
        <tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr></table>"""

    def request(method, url, **kwargs):
        state["calls"].append((method, url, kwargs))
        assert 0 < kwargs["timeout"] <= 5
        assert kwargs["allow_redirects"] is False
        if url == releases.BLS_URL:
            if state["bls_error"]:
                raise state["bls_error"]
            response = Response(state["bls"])
        elif url == releases.CENSUS_URL:
            if state["census_error"]:
                raise state["census_error"]
            response = Response(state["census"])
        elif url in releases._SCHEDULE_URLS.values():
            response = Response(text=state["schedule"], status=state["schedule_status"])
        elif url == release_calendar.FOMC_URL:
            response = Response(text='''<h4>2026 FOMC Meetings</h4><div class="fomc-meeting">
                <div class="fomc-meeting__month">October</div>
                <div class="fomc-meeting__date">27-28</div></div>''')
        elif url == releases.FRED_URL:
            response = Response({"observations": [
                {"date": "2026-10-17", "value": "."},
                {"date": "2026-10-16", "value": "4.00"},
                {"date": "2026-10-15", "value": "4.00"},
            ]})
        else:
            pytest.fail(f"unexpected URL: {url}")
        state["responses"].append(response)
        return response

    monkeypatch.setattr(releases.requests, "post", lambda url, **kw: request("POST", url, **kw))
    monkeypatch.setattr(releases.requests, "get", lambda url, **kw: request("GET", url, **kw))
    yield state
    releases.clear_economic_releases_cache()


def _find(rows, indicator="US_CPI", basis="MoM", period="2026-09"):
    return next(row for row in rows if (row["indicator"], row["basis"], row["period"]) == (indicator, basis, period))


def test_keyless_bls_units_basis_previous_and_real_release_date(providers):
    rows = releases.load_economic_releases(now=NOW)
    monthly = _find(rows)
    assert monthly["actual"] == 1.0
    assert monthly["previous"] == 1.0
    assert monthly["unit"] == "%"
    assert monthly["seasonal_adjustment"] == "SA"
    assert monthly["value_kind"] == "calculated_from_official_levels"
    assert monthly["previous_period"] == "2026-08"
    assert monthly["release_at"] == "2026-10-14T08:30:00-04:00"
    assert monthly["release_source"] == "BLS schedule"
    assert monthly["as_of"] == NOW.isoformat()
    assert monthly["forecast"] is None
    assert monthly["forecast_source"] is None
    assert monthly["actual_minus_forecast"] is None
    assert "forecast_not_supplied" in monthly["missing_reason"]
    yearly = _find(rows, basis="YoY")
    assert (yearly["actual"], yearly["previous"]) == (3.0, 2.0)
    assert yearly["seasonal_adjustment"] == "NSA"
    payrolls = _find(rows, "US_NONFARM_PAYROLLS")
    assert (payrolls["actual"], payrolls["previous"], payrolls["unit"]) == (250, 200, "thousand persons")
    assert _find(rows, "US_UNEMPLOYMENT", "level")["actual"] == 4.2
    assert _find(rows, "US_PPI", "YoY")["actual"] == 3.0
    assert len([c for c in providers["calls"] if c[0] == "POST"]) == 1
    assert len(providers["calls"]) == 6
    assert all(response.closed for response in providers["responses"])


def test_release_date_not_inferred_when_schedule_blocked(providers):
    providers["schedule_status"] = 403
    row = _find(releases.load_economic_releases(now=NOW))
    assert row["status"] == "released"
    assert row["release_at"] is None
    assert row["period"] == "2026-09"
    assert "release_schedule_http_403" in row["missing_reason"]
    assert "release_date_unavailable" in row["missing_reason"]


def test_missing_month_is_not_a_previous_observation(providers):
    providers["bls"]["Results"]["series"][0]["data"] = _observations({"2026-07": 100, "2026-09": 103})
    row = _find(releases.load_economic_releases(now=NOW))
    assert row["actual"] is None
    assert row["previous"] is None
    assert row["status"] == "unavailable"
    assert "comparison_period_unavailable" in row["missing_reason"]


def test_annual_average_future_and_nonfinite_observations_ignored(providers):
    providers["bls"]["Results"]["series"][0]["data"] += [
        {"year": "2026", "period": "M13", "value": "900"},
        {"year": "2026", "period": "M11", "value": "999"},
        {"year": "2026", "period": "M10", "value": "NaN"},
    ]
    assert _find(releases.load_economic_releases(now=NOW))["actual"] == 1.0


def test_same_period_consensus_preserves_official_actual_and_revised_previous(providers):
    event = {"indicator": "US_CPI", "period": "2026-09", "basis": "MoM", "unit": "%",
             "actual": 9, "forecast": 0.3, "previous": 9, "source": "calendar", "date": "2026-10-14",
             "forecast_source": "survey vendor", "forecast_source_url": "https://example.test/survey"}
    original = deepcopy(event)
    row = _find(releases.load_economic_releases([event], now=NOW))
    assert (row["actual"], row["forecast"], row["previous"]) == (1, 0.3, 1)
    assert row["forecast_source"] == "survey vendor"
    assert row["forecast_source_url"] == "https://example.test/survey"
    assert row["actual_minus_forecast"] == 0.7
    assert row["difference_unit"] == "pp"
    assert row["source"] == "BLS"
    assert event == original


def test_existing_raw_title_date_contract_matches_verified_release(providers):
    rows = releases.load_economic_releases([{
        "event": "\ubbf8\uad6d CPI \ubc1c\ud45c", "raw_title": "Core CPI m/m", "date": "2026-10-14",
        "forecast": "0.2%", "source": "auto: FF", "country": "USD",
    }], now=NOW)
    assert _find(rows, "US_CORE_CPI")["forecast"] == 0.2
    assert _find(rows)["forecast"] is None


def test_pending_event_never_reuses_previous_actual_or_infers_observation_month(providers):
    rows = releases.load_economic_releases([{
        "raw_title": "CPI m/m", "date": "2026-11-10", "actual": "8.0%",
        "forecast": "0.2%", "source": "calendar",
    }], now=NOW)
    event = _find(rows, period="")
    assert event["status"] == "pending"
    assert event["actual"] is None
    assert event["forecast"] == 0.2
    assert event["previous"] is None
    assert event["release_at"] == "2026-11-10"
    assert event["actual_minus_forecast"] is None
    assert "future_release_actual_ignored" in event["missing_reason"]
    assert "observation_period_unavailable" in event["missing_reason"]
    assert _find(rows)["forecast"] is None


@pytest.mark.parametrize("updates", [
    {"forecast_basis": "YoY"}, {"forecast_unit": "persons"},
])
def test_comparison_requires_same_units_and_basis(providers, updates):
    event = {"indicator": "US_CPI", "period": "2026-09", "unit": "%", "basis": "MoM",
             "forecast": 0.3, "source": "vendor", **updates}
    row = _find(releases.load_economic_releases([event], now=NOW))
    assert row["forecast"] == 0.3
    assert row["actual_minus_forecast"] is None
    assert "forecast_unit_or_basis_mismatch" in row["missing_reason"]


def test_unqualified_cpi_is_not_attached_to_monthly_yearly_or_core(providers):
    rows = releases.load_economic_releases([{
        "event": "\ubbf8\uad6d CPI \ubc1c\ud45c", "date": "2026-10-14", "forecast": "3.2%", "source": "calendar",
    }], now=NOW)
    assert _find(rows)["forecast"] is None
    assert _find(rows, basis="YoY")["forecast"] is None
    event = next(row for row in rows if row["indicator"] == "US_CPI" and row["basis"] == "unknown")
    assert event["forecast"] == 3.2
    assert event["actual_minus_forecast"] is None


def test_wrong_country_and_generic_fomc_never_become_us_observations(providers):
    rows = releases.load_economic_releases([
        {"raw_title": "CPI m/m", "country": "EUR", "actual": "1%"},
        {"event": "China CPI y/y", "actual": "1%"},
        {"event": "FOMC", "date": "2026-11-01", "forecast": "3.75%"},
    ], now=NOW)
    assert len(rows) == 12


def test_nonfarm_k_suffix_is_thousands_without_double_scaling(providers):
    row = _find(releases.load_economic_releases([{
        "raw_title": "Non-Farm Employment Change", "period": "2026-09",
        "forecast": "220K", "source": "calendar",
    }], now=NOW), "US_NONFARM_PAYROLLS")
    assert row["forecast"] == 220
    assert row["actual_minus_forecast"] == 30
    assert row["difference_unit"] == "thousand persons"


def test_census_filters_errors_other_categories_and_adjustments(providers):
    providers["census"] += [
        ["99", "2026-10-01", "44X72", "MPCSM", "yes", "yes"],
        ["88", "2026-10-01", "44000", "MPCSM", "yes", "no"],
        ["77", "2026-10-01", "44X72", "MPCSM", "no", "no"],
        ["66", "2026-11-01", "44X72", "MPCSM", "yes", "no"],
    ]
    row = _find(releases.load_economic_releases(now=NOW), "US_RETAIL_SALES")
    assert row["actual"] == 0.2
    assert row["previous"] == 0.6
    assert row["release_at"] is None


def test_census_missing_key_html_is_explicit_and_not_cached(providers):
    providers["census"] = None
    rows = releases.load_economic_releases(now=NOW)
    row = next(row for row in rows if row["indicator"] == "US_RETAIL_SALES")
    assert row["status"] == "unavailable"
    assert "CENSUS_API_KEY_required" in row["missing_reason"]
    releases.load_economic_releases(now=NOW)
    assert sum(call[1] == releases.CENSUS_URL for call in providers["calls"]) == 2


def test_missing_keys_kr_and_fed_explicit_and_no_fred_request(providers):
    rows = releases.load_economic_releases(now=NOW)
    for indicator in ("KR_CPI", "KR_EXPORTS"):
        row = next(row for row in rows if row["indicator"] == indicator)
        assert row["status"] == "unavailable"
        assert row["actual"] is None
        assert "ECOS_API_KEY_missing" in row["missing_reason"]
    row = next(row for row in rows if row["indicator"] == "US_FED_TARGET_UPPER")
    assert "FRED_API_KEY_missing" in row["missing_reason"]
    assert all(call[1] != releases.FRED_URL for call in providers["calls"])


def test_optional_fred_is_daily_target_upper_not_a_release_or_fomc_decision(providers, monkeypatch):
    monkeypatch.setattr(releases, "_api_key", lambda name: "fixture-secret" if name == "FRED_API_KEY" else "")
    row = next(row for row in releases.load_economic_releases(now=NOW) if row["indicator"] == "US_FED_TARGET_UPPER")
    assert row["period"] == "2026-10-16"
    assert row["actual"] == 4.0
    assert row["previous"] == 4.0
    assert row["release_at"] is None
    assert "previous daily observation" in row["previous_source"]
    assert "fixture-secret" not in str(row)


def test_cache_success_only_and_return_values_are_isolated(providers):
    first = releases.load_economic_releases(now=NOW)
    first[0]["actual"] = 999
    second = releases.load_economic_releases(now=NOW)
    assert _find(second)["actual"] == 1.0
    assert len(providers["calls"]) == 6
    assert second == releases.load_economic_releases(now=NOW)


def test_cache_expires(providers, monkeypatch):
    tick = [100.0]
    monkeypatch.setattr(releases.time, "monotonic", lambda: tick[0])
    releases.load_economic_releases(now=NOW)
    tick[0] += releases.CACHE_TTL + 1
    releases.load_economic_releases(now=NOW)
    assert len(providers["calls"]) == 12


def test_request_failure_retried_without_secret_or_exception_text(providers):
    providers["bls_error"] = requests.Timeout("https://example.test?api_key=must-not-echo")
    row = next(row for row in releases.load_economic_releases(now=NOW) if row["indicator"] == "US_CPI")
    assert row["status"] == "unavailable"
    assert "Timeout" in row["missing_reason"]
    assert "must-not-echo" not in str(row)
    providers["bls_error"] = None
    assert _find(releases.load_economic_releases(now=NOW))["status"] == "released"
    assert sum(call[1] == releases.BLS_URL for call in providers["calls"]) == 2


def test_partial_bls_batch_not_cached(providers):
    missing = providers["bls"]["Results"]["series"].pop()
    rows = releases.load_economic_releases(now=NOW)
    assert _find(rows)["status"] == "released"
    assert next(row for row in rows if row["indicator"] == "US_UNEMPLOYMENT")["status"] == "unavailable"
    providers["bls"]["Results"]["series"].append(missing)
    assert _find(releases.load_economic_releases(now=NOW), "US_UNEMPLOYMENT", "level")["status"] == "released"


def test_date_only_today_waits_for_confirmation_and_unknown_timezone_is_not_assumed(providers):
    rows = releases.load_economic_releases([
        {"indicator": "KR_CPI", "period": "2026-10", "date": "2026-10-18", "unit": "%",
         "basis": "YoY", "forecast": 2.5, "source": "calendar"},
        {"indicator": "KR_EXPORTS", "period": "2026-10", "release_at": "2026-10-19T08:00:00",
         "unit": "%", "basis": "YoY", "source": "calendar"},
    ], now=NOW)
    assert _find(rows, "KR_CPI", "YoY", "2026-10")["status"] == "pending"
    assert _find(rows, "KR_EXPORTS", "YoY", "2026-10")["release_at"] is None


def test_ui_korean_dates_status_and_result_aliases(providers):
    rows = releases.load_economic_releases([
        {"\uc774\ubca4\ud2b8": "\ubbf8\uad6d CPI \ubc1c\ud45c", "\uc2dc\uc791\uc77c": "2026-10-27",
         "\uc885\ub8cc\uc77c": "2026-10-28", "\uc0c1\ud0dc": "\ub300\uae30", "\uacb0\uacfc": "\uc2e4\uc81c 3% / \uc608\uc0c1 2%", "\ucd9c\ucc98": "calendar"},
        {"indicator": "KR_CPI", "period": "2026-10", "unit": "%", "basis": "YoY",
         "\uc2dc\uc791\uc77c": "2026-10-18", "\uacb0\uacfc": "3.0%", "\ucd9c\ucc98": "calendar"},
        {"indicator": "KR_EXPORTS", "basis": "YoY", "unit": "%", "\uc0c1\ud0dc": "\ub300\uae30"},
    ], now=NOW)
    event = next(row for row in rows if row["indicator"] == "US_CPI" and row["basis"] == "unknown")
    assert event["release_at"] == "2026-10-28"
    assert event["status"] == "pending"
    assert event["actual"] is None
    assert event["forecast"] is None  # Composite display text is never reparsed as consensus.
    same_day = _find(rows, "KR_CPI", "YoY", "2026-10")
    assert same_day["actual"] == 3.0
    assert same_day["status"] == "released"
    undated = next(row for row in rows if row["indicator"] == "KR_EXPORTS")
    assert undated["status"] == "pending"
    assert undated["release_at"] is None


def test_core_ppi_and_retail_never_attach_to_headline_series(providers):
    rows = releases.load_economic_releases([
        {"event": "Core PPI m/m", "period": "2026-09", "forecast": "0.3%", "source": "calendar"},
        {"event": "Core Retail Sales m/m", "period": "2026-09", "forecast": "0.5%", "source": "calendar"},
    ], now=NOW)
    assert _find(rows, "US_PPI")["forecast"] is None
    assert _find(rows, "US_RETAIL_SALES")["forecast"] is None


@pytest.mark.parametrize("payload", [{"status": "REQUEST_SUCCEEDED", "Results": []},
                                      {"status": "REQUEST_SUCCEEDED", "Results": {"series": [None]}},
                                      {"status": "REQUEST_NOT_PROCESSED"}, []])
def test_malformed_or_rejected_bls_response_is_unavailable(providers, payload):
    providers["bls"] = payload
    rows = releases.load_economic_releases(now=NOW)
    assert all(row["actual"] is None for row in rows[:8])
    assert all(row["status"] == "unavailable" for row in rows[:8])


def test_dataframe_contract_and_event_bound(providers):
    import pandas as pd
    event = {"indicator": "US_CPI", "period": "2026-09", "basis": "MoM", "unit": "%",
             "forecast": 0.5, "source": "calendar"}
    rows = releases.load_economic_releases(pd.DataFrame([event]), now=NOW)
    assert _find(rows)["forecast"] == 0.5
    events = ({"indicator": "KR_CPI", "period": "2026-10", "basis": "unknown", "date": "2026-11-01"}
              for _ in range(releases.MAX_EVENT_ROWS + 100))
    assert len(releases.load_economic_releases(events, now=NOW)) <= 12 + releases.MAX_EVENT_ROWS


def test_monthly_history_is_rates_and_changes_not_raw_levels(providers):
    levels = {releases._shift("2024-01", index): 100 + index for index in range(33)}
    for entry in providers["bls"]["Results"]["series"]:
        entry["data"] = _observations(levels)
    rows = releases.load_economic_releases(now=NOW)
    for row in rows[:8]:
        assert len(row["history"]) >= 12
        assert row["history"] == sorted(row["history"], key=lambda entry: entry["period"])
        assert row["history"][-1] == {"period": row["period"], "value": row["actual"]}
        assert row["previous3mean"] == pytest.approx(
            sum(entry["value"] for entry in row["history"][-4:-1]) / 3, abs=1e-6)
    yearly = _find(rows, basis="YoY")
    assert yearly["history"][0] == {"period": "2025-01", "value": 12.0}
    assert _find(rows, "US_NONFARM_PAYROLLS")["history"][-1]["value"] == 1.0
    assert _find(rows, "US_UNEMPLOYMENT", "level")["history"][-1]["value"] == 132.0
    yearly["history"][0]["value"] = 999
    assert _find(releases.load_economic_releases(now=NOW), basis="YoY")["history"][0]["value"] == 12.0


def test_three_month_mean_requires_consecutive_prior_months_and_excludes_actual(providers):
    values = {"2026-05": 100, "2026-06": 101, "2026-07": 102, "2026-09": 200}
    entry = next(entry for entry in providers["bls"]["Results"]["series"] if entry["seriesID"] == "LNS14000000")
    entry["data"] = _observations(values)
    row = _find(releases.load_economic_releases(now=NOW), "US_UNEMPLOYMENT", "level")
    assert row["previous3mean"] is None
    assert row["previous3mean_reason"] == "three_consecutive_prior_months_unavailable"
    assert len(row["history"]) == 4
    releases.clear_economic_releases_cache()
    entry["data"] = _observations({**values, "2026-08": 103})
    row = _find(releases.load_economic_releases(now=NOW), "US_UNEMPLOYMENT", "level")
    assert row["previous3mean"] == 102.0
    assert row["previous3mean_reason"] == ""


def test_census_monthly_history_is_same_unit_direct_published_changes(providers):
    providers["census"] = [providers["census"][0]] + [
        [str(index / 10), releases._shift("2025-01", index) + "-01", "44X72", "MPCSM", "yes", "no"]
        for index in range(21)]
    row = _find(releases.load_economic_releases(now=NOW), "US_RETAIL_SALES")
    assert len(row["history"]) == 21
    assert row["history"][-1]["value"] == 2.0
    assert row["previous3mean"] == 1.8


def test_future_scheduled_actual_not_exposed_in_history(providers):
    providers["schedule"] = providers["schedule"].replace("Oct. 14, 2026", "Oct. 30, 2026")
    row = _find(releases.load_economic_releases(now=NOW))
    assert row["actual"] is None
    assert row["status"] == "pending"
    assert all(entry["period"] < "2026-09" for entry in row["history"])


@pytest.mark.parametrize("location", ["environment", "flat", "economic"])
def test_key_configuration_supports_environment_and_both_secret_layouts(monkeypatch, location):
    import sys
    from types import SimpleNamespace

    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    secrets = {}
    if location == "environment":
        monkeypatch.setenv("ECOS_API_KEY", "  example-key  ")
        secrets["ECOS_API_KEY"] = "lower-priority"
    elif location == "flat":
        secrets = {"ECOS_API_KEY": "example-key", "economic": {"ECOS_API_KEY": "lower-priority"}}
    else:
        secrets = {"economic": {"ECOS_API_KEY": "example-key"}}
    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(secrets=secrets))
    assert releases._api_key("ECOS_API_KEY") == "example-key"


@pytest.fixture
def ecos_provider(monkeypatch):
    releases.clear_economic_releases_cache()
    state = {"calls": [], "reject": False, "bad_unit": False, "bad_mapping": False, "missing_baseline": False}

    def request(url, **kwargs):
        state["calls"].append(url)
        assert kwargs["timeout"] == 4
        assert kwargs["allow_redirects"] is False
        stat = "901Y009" if "901Y009" in url else "901Y118"
        indicator = "KR_CPI" if stat == "901Y009" else "KR_EXPORTS"
        _, item, title, item_name = releases._ECOS_SERIES[indicator]
        unit = "2020=100" if indicator == "KR_CPI" else "천불"
        if state["reject"]:
            return Response({"RESULT": {"CODE": "INFO-200", "MESSAGE": "do not echo"}})
        if "StatisticItemList" in url:
            return Response({"StatisticItemList": {"row": [
                {"STAT_CODE": stat, "STAT_NAME": title, "GRP_CODE": "Group1", "CYCLE": "M",
                 "ITEM_CODE": "wrong" if state["bad_mapping"] else item,
                 "ITEM_NAME": item_name, "UNIT_NAME": unit}]}})
        rows = []
        for index in range(33):
            if state["missing_baseline"] and index == 20:
                continue
            period = releases._shift("2024-01", index)
            rows.append({"STAT_CODE": stat, "ITEM_CODE1": item, "ITEM_NAME1": item_name,
                         "TIME": period.replace("-", ""), "DATA_VALUE": str(100 + index),
                         "UNIT_NAME": "wrong" if state["bad_unit"] else unit})
        return Response({"StatisticSearch": {"row": rows}})

    monkeypatch.setattr(releases.requests, "get", request)
    yield state
    releases.clear_economic_releases_cache()


@pytest.mark.parametrize("indicator", ["KR_CPI", "KR_EXPORTS"])
def test_verified_ecos_monthly_levels_become_yoy_rates(ecos_provider, indicator):
    row = releases._ecos(NOW, "FixtureECOSKey", indicator)
    assert row["status"] == "released"
    assert row["actual"] == 10.0  # 132 / 120 - 1, not an index or a monthly change.
    assert row["previous"] == 10.1
    assert row["unit"] == "%" and row["basis"] == "YoY"
    assert row["release_at"] is None
    assert len(row["history"]) == 21
    assert row["history"][0] == {"period": "2025-01", "value": 12.0}
    assert row["previous3mean"] == 10.2  # Prior three YoY values: 10.1, 10.2, 10.3.
    assert "FixtureECOSKey" not in str(row)
    assert len(ecos_provider["calls"]) == 2
    releases._ecos(NOW, "FixtureECOSKey", indicator)
    assert len(ecos_provider["calls"]) == 2


@pytest.mark.parametrize("failure,reason", [("reject", "ecos_metadata_rejected"),
                                            ("bad_mapping", "ecos_series_mapping_unverified"),
                                            ("bad_unit", "ecos_observation_series_or_unit_mismatch")])
def test_ecos_rejects_unverified_mapping_and_units_and_retries(ecos_provider, failure, reason):
    ecos_provider[failure] = True
    row = releases._ecos(NOW, "FixtureECOSKey", "KR_CPI")
    assert row["actual"] is None and row["history"] == []
    assert reason in row["missing_reason"]
    ecos_provider[failure] = False
    assert releases._ecos(NOW, "FixtureECOSKey", "KR_CPI")["actual"] == 10.0


def test_ecos_does_not_substitute_a_nearby_month_for_yoy_baseline(ecos_provider):
    ecos_provider["missing_baseline"] = True
    row = releases._ecos(NOW, "FixtureECOSKey", "KR_EXPORTS")
    assert row["actual"] is None
    assert row["previous"] == 10.1
    assert "comparison_period_unavailable" in row["missing_reason"]
    assert all(entry["period"] != "2026-09" for entry in row["history"])


def test_daily_fred_does_not_fabricate_monthly_history(providers, monkeypatch):
    monkeypatch.setattr(releases, "_api_key", lambda name: "fixture-secret" if name == "FRED_API_KEY" else "")
    row = next(row for row in releases.load_economic_releases(now=NOW) if row["indicator"] == "US_FED_TARGET_UPPER")
    assert row["history"] == [] and row["previous3mean"] is None
    assert row["history_frequency"] == "daily"
