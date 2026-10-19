"""Deterministic official-page fixtures; never reaches the network."""

from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from stock_lab_core import release_calendar as calendar


NOW = datetime(2026, 10, 18, 3, tzinfo=timezone.utc)
BLS = '''<table><tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
    <tr><td>September 2026</td><td>Oct. 14, 2026</td><td>08:30 AM</td></tr>
    <tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr></table>'''
FOMC = '''<h4><a>2026 FOMC Meetings</a></h4>
    <div class="row fomc-meeting">
      <div class="fomc-meeting__month"><strong>October</strong></div>
      <div class="fomc-meeting__date">27-28</div>
      <div class="fomc-meeting__minutes">Released November 18, 2026</div>
    </div>
    <div class="row fomc-meeting"><div class="fomc-meeting__month">December</div>
      <div class="fomc-meeting__date">8-9*</div></div>
    <h4>2027 FOMC Meetings</h4>
    <div class="row fomc-meeting"><div class="fomc-meeting__month">January</div>
      <div class="fomc-meeting__date">26-27</div></div>'''


@pytest.fixture
def pages(monkeypatch):
    calendar.clear_release_calendar_cache()
    state = {"calls": [], "closed": [], "fail": set(), "error": None,
             "bls": BLS, "fomc": FOMC, "fred_calls": [], "fred_payload": None}

    class Response:
        def __init__(self, url, params=None):
            self.status_code = 403 if url in state["fail"] else 200
            self.text = state["fomc"] if url == calendar.FOMC_URL else state["bls"]
            self.params = params

        def json(self):
            if state["fred_payload"] is not None:
                return state["fred_payload"]
            return {"release_dates": [{"release_id": self.params["release_id"], "date": day}
                                     for day in ("2026-10-14", "2026-10-20", "2026-10-20")]}

        def close(self):
            state["closed"].append(True)

    def get(url, **kwargs):
        state["calls"].append(url)
        assert kwargs["timeout"] == 4
        assert kwargs["allow_redirects"] is False
        if state["error"]:
            raise state["error"]
        if url == calendar.FRED_DATES_URL:
            state["fred_calls"].append(kwargs["params"])
        return Response(url, kwargs.get("params"))

    monkeypatch.setattr(calendar.requests, "get", get)
    yield state
    calendar.clear_release_calendar_cache()


def test_confirmed_bls_reference_months_dst_and_date_only_fomc(pages):
    result = calendar.load_release_calendar(now=NOW)
    assert result["connected"] is True
    assert all(source["status"] == "connected" and source["reason"] == "" for source in result["sources"])
    assert len(result["events"]) == 9
    cpi = [event for event in result["events"] if event["indicator"] == "US_CPI"]
    assert cpi[0]["period"] == "2026-09"
    assert cpi[0]["release_at"] == "2026-10-14T08:30:00-04:00"
    assert cpi[1]["release_at"] == "2026-11-10T08:30:00-05:00"
    fomc = [event for event in result["events"] if event["source"] == "Federal Reserve FOMC"]
    assert [event["date"] for event in fomc] == ["2026-10-28", "2026-12-09", "2027-01-27"]
    assert fomc[0]["release_at"] == "2026-10-28"
    assert fomc[0]["start_date"] == "2026-10-27"
    assert all("period" not in event for event in fomc)
    assert len(pages["calls"]) == 4 and len(pages["closed"]) == 4


def test_empty_next_week_still_connected_and_distinct_from_connection_failure(pages):
    result = calendar.load_release_calendar(now=NOW)
    horizon = (NOW + timedelta(days=7)).date().isoformat()
    upcoming = [event for event in result["events"] if NOW.date().isoformat() <= event["date"] <= horizon]
    assert upcoming == [] and result["connected"] is True
    calendar.clear_release_calendar_cache()
    pages["fail"] = set(pages["calls"])
    failed = calendar.load_release_calendar(now=NOW)
    assert failed["events"] == [] and failed["connected"] is False
    assert all(source["reason"] == "http_403" for source in failed["sources"])


def test_partial_source_failure_is_visible_and_retried(pages):
    pages["fail"].add(calendar.FOMC_URL)
    result = calendar.load_release_calendar(now=NOW)
    assert result["connected"] is True
    assert result["sources"][-1] == {"name": "Federal Reserve FOMC", "status": "unavailable", "reason": "http_403"}
    pages["fail"].clear()
    recovered = calendar.load_release_calendar(now=NOW)
    assert recovered["sources"][-1]["status"] == "connected"
    assert len(pages["calls"]) == 5


def test_success_cache_is_bounded_isolated_and_expires(pages, monkeypatch):
    tick = [100.0]
    monkeypatch.setattr(calendar.time, "monotonic", lambda: tick[0])
    first = calendar.load_release_calendar(now=NOW)
    first["events"][0]["event"] = "mutated"
    assert calendar.load_release_calendar(now=NOW)["events"][0]["event"] != "mutated"
    assert len(pages["calls"]) == 4
    tick[0] += calendar.CACHE_TTL + 1
    calendar.load_release_calendar(now=NOW)
    assert len(pages["calls"]) == 8


def test_request_exception_does_not_expose_url_or_secret(pages):
    pages["error"] = requests.Timeout("https://example.test?key=must-not-echo")
    result = calendar.load_release_calendar(now=NOW)
    assert result["connected"] is False
    assert "must-not-echo" not in str(result)
    assert all(source["reason"] == "request_failed:Timeout" for source in result["sources"])


@pytest.mark.parametrize("html", ["<html>access denied</html>", "<table><tr><td>2026-10-28</td></tr></table>"])
def test_unrecognized_http_success_is_not_a_successful_empty_calendar(pages, html):
    pages.update(bls=html, fomc=html)
    result = calendar.load_release_calendar(now=NOW)
    assert result["connected"] is False
    assert all(source["reason"] == "calendar_rows_unrecognized" for source in result["sources"])


def test_fomc_cross_month_and_uncertain_or_nonmeeting_rows():
    html = '''<h4>2024 FOMC Meetings</h4>
    <div class="fomc-meeting"><div class="fomc-meeting__month">Apr/May</div>
      <div class="fomc-meeting__date">30-1</div></div>
    <div class="fomc-meeting"><div class="fomc-meeting__month">August</div>
      <div class="fomc-meeting__date">22 (notation vote)</div></div>
    <div class="fomc-meeting"><div class="fomc-meeting__month">October</div>
      <div class="fomc-meeting__date">TBD</div></div>
    <div class="fomc-meeting"><div class="fomc-meeting__month">December</div>
      <div class="fomc-meeting__date">8-9 (tentative)</div></div>'''
    events = calendar._fomc_events(html, datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert len(events) == 1
    assert events[0]["start_date"] == "2024-04-30" and events[0]["date"] == "2024-05-01"


def test_missing_timezone_database_keeps_confirmed_date_only(monkeypatch):
    def unavailable(_):
        raise calendar.ZoneInfoNotFoundError()

    monkeypatch.setattr(calendar, "ZoneInfo", unavailable)
    assert calendar._bls_events(BLS, "cpi")[0]["release_at"] == "2026-10-14"


def test_date_clock_and_invalid_clock(pages):
    assert calendar.load_release_calendar(now=date(2026, 10, 18))["connected"] is True
    with pytest.raises(TypeError):
        calendar.load_release_calendar(now="2026-10-18")


def test_failed_bls_uses_fred_dates_without_inventing_month_or_time(pages):
    pages["fail"].update(calendar.SCHEDULE_URLS.values())
    result = calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert result["connected"]
    assert len(pages["fred_calls"]) == 3
    assert {call["release_id"] for call in pages["fred_calls"]} == {10, 46, 50}
    assert all(call["api_key"] == "test-secret" and call["include_release_dates_with_no_data"] == "true"
               for call in pages["fred_calls"])
    assert len(result["events"]) == 9  # Six deduplicated FRED dates + three FOMC dates.
    for event in result["events"]:
        if event["source"] == "FRED release calendar":
            assert event["release_at"] == event["date"]
            assert "period" not in event and "T" not in event["release_at"]
    assert all(source["provider"] == "FRED" and source["primary_reason"] == "http_403"
               for source in result["sources"][:3])
    assert "test-secret" not in str(result) + str(calendar._CACHE)
    assert len(pages["closed"]) == 7


def test_bls_success_does_not_call_fred_even_with_key(pages):
    calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert len(pages["calls"]) == 4 and not pages["fred_calls"]


def test_fred_success_cached_but_primary_retry_can_recover(pages):
    pages["fail"].add(calendar.SCHEDULE_URLS["cpi"])
    calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert len(pages["fred_calls"]) == 1
    pages["fail"].clear()
    recovered = calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    cpi = [event for event in recovered["events"] if event["indicator"] == "US_CPI"]
    assert cpi[0]["period"] == "2026-09" and "T" in cpi[0]["release_at"]
    assert "provider" not in recovered["sources"][0]


def test_fred_failure_is_safe_visible_and_retried(pages):
    pages["fail"].update([calendar.SCHEDULE_URLS["cpi"], calendar.FRED_DATES_URL])
    failed = calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert failed["sources"][0]["fallback_reason"] == "http_403"
    assert failed["sources"][0]["status"] == "unavailable"
    pages["fail"].remove(calendar.FRED_DATES_URL)
    recovered = calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert recovered["sources"][0]["provider"] == "FRED"
    assert len(pages["fred_calls"]) == 2 and "test-secret" not in str(failed)


@pytest.mark.parametrize("payload", [[], {}, {"release_dates": []},
    {"release_dates": [{"release_id": 50, "date": "2026-10-20"}]},
    {"release_dates": [{"release_id": 10, "date": "2026-02-30"}]},
    {"release_dates": [{"release_id": 10, "date": "2024-10-20"}]},
    {"release_dates": [{"release_id": 10, "date": "2026-10-20T08:30:00"}]},
])
def test_fred_rejects_bad_or_irrelevant_dates(pages, payload):
    pages["fail"].add(calendar.SCHEDULE_URLS["cpi"])
    pages["fred_payload"] = payload
    result = calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert result["sources"][0]["fallback_reason"] == "calendar_rows_unrecognized"
    assert not any(event["indicator"] == "US_CPI" for event in result["events"])
