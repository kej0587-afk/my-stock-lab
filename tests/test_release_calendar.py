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
META = """<h2>Meta to Announce Third Quarter 2026 Results</h2>
<p>October 12, 2026</p><p>The company's third quarter 2026 financial results
will be released after market close on Wednesday, October 21st, 2026.</p>
<p>Meta will host a conference call to discuss its results at 1:30 p.m. PT / 4:30 p.m. ET the same day.</p>"""


@pytest.fixture
def pages(monkeypatch):
    calendar.clear_release_calendar_cache()
    state = {"calls": [], "closed": [], "fail": set(), "error": None,
             "bls": BLS, "fomc": FOMC, "meta": META, "fred_calls": [], "fred_payload": None}

    class Response:
        def __init__(self, url, params=None):
            self.status_code = 403 if url in state["fail"] else 200
            self.text = (state["fomc"] if url == calendar.FOMC_URL else
                         state["meta"] if url == calendar.META_IR_URL else state["bls"])
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
    assert len(result["events"]) == 18
    cpi = [event for event in result["events"] if event["indicator"] == "US_CPI"]
    assert cpi[0]["period"] == "2026-09"
    assert cpi[0]["release_at"] == "2026-10-14T08:30:00-04:00"
    assert cpi[1]["release_at"] == "2026-11-10T08:30:00-05:00"
    fomc = [event for event in result["events"] if event["source"] == "Federal Reserve FOMC"]
    assert [event["date"] for event in fomc] == ["2026-10-28", "2026-12-09", "2027-01-27"]
    assert fomc[0]["release_at"] == "2026-10-28"
    assert fomc[0]["start_date"] == "2026-10-27"
    assert all("period" not in event for event in fomc)
    assert len(pages["calls"]) == 5 and len(pages["closed"]) == 5


def test_empty_next_week_still_connected_and_distinct_from_connection_failure(pages):
    now = NOW.replace(month=11, day=12)
    result = calendar.load_release_calendar(now=now)
    horizon = (now + timedelta(days=7)).date().isoformat()
    upcoming = [event for event in result["events"] if now.date().isoformat() <= event["date"] <= horizon]
    assert upcoming == [] and result["connected"] is True
    calendar.clear_release_calendar_cache()
    pages["fail"] = set(pages["calls"])
    # Outside fixture coverage no source can silently claim connectivity.
    failed = calendar.load_release_calendar(now=NOW.replace(year=2028))
    assert failed["events"] == [] and failed["connected"] is False
    assert all(source["reason"] == "http_403" for source in failed["sources"][:4])


def test_partial_source_failure_is_visible_and_retried(pages):
    pages["fail"].add(calendar.FOMC_URL)
    result = calendar.load_release_calendar(now=NOW)
    assert result["connected"] is True
    assert result["sources"][3] == {"name": "Federal Reserve FOMC", "status": "unavailable", "reason": "http_403"}
    pages["fail"].clear()
    recovered = calendar.load_release_calendar(now=NOW)
    assert recovered["sources"][3]["status"] == "connected"
    assert len(pages["calls"]) == 6


def test_success_cache_is_bounded_isolated_and_expires(pages, monkeypatch):
    tick = [100.0]
    monkeypatch.setattr(calendar.time, "monotonic", lambda: tick[0])
    first = calendar.load_release_calendar(now=NOW)
    first["events"][0]["event"] = "mutated"
    assert calendar.load_release_calendar(now=NOW)["events"][0]["event"] != "mutated"
    assert len(pages["calls"]) == 5
    tick[0] += calendar.CACHE_TTL + 1
    calendar.load_release_calendar(now=NOW)
    assert len(pages["calls"]) == 10


def test_request_exception_does_not_expose_url_or_secret(pages):
    pages["error"] = requests.Timeout("https://example.test?key=must-not-echo")
    result = calendar.load_release_calendar(now=NOW)
    assert result["connected"] is True  # Confirmed fixtures survive transport errors.
    assert "must-not-echo" not in str(result)
    assert all(source["reason"] == "request_failed:Timeout" for source in result["sources"][:4])
    assert result["sources"][4]["primary_reason"] == "request_failed:Timeout"


@pytest.mark.parametrize("html", ["<html>access denied</html>", "<table><tr><td>2026-10-28</td></tr></table>"])
def test_unrecognized_http_success_is_not_a_successful_empty_calendar(pages, html):
    pages.update(bls=html, fomc=html)
    result = calendar.load_release_calendar(now=NOW)
    assert all(source["status"] == "unavailable" for source in result["sources"][:4])
    assert all(source["reason"] == "calendar_rows_unrecognized" for source in result["sources"][:4])


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


def test_failed_bls_uses_fred_dates_with_explicit_standard_time_rule(pages):
    pages["fail"].update(calendar.SCHEDULE_URLS.values())
    result = calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert result["connected"]
    assert len(pages["fred_calls"]) == 3
    assert {call["release_id"] for call in pages["fred_calls"]} == {10, 46, 50}
    assert all(call["api_key"] == "test-secret" and call["include_release_dates_with_no_data"] == "true"
               for call in pages["fred_calls"])
    assert len(result["events"]) == 18
    for event in result["events"]:
        if event["source"] == "FRED release calendar":
            assert event["release_at"].startswith(event["date"] + "T08:30:00")
            assert "period" not in event
            assert event["release_precision"] == "schedule_rule"
            assert event["schedule_rule"] == "08:30 America/New_York"
            assert event["release_time_confirmed"] is False
            assert event["schedule_rule_source_url"] in calendar.SCHEDULE_URLS.values()
    assert all(source["provider"] == "FRED" and source["primary_reason"] == "http_403"
               for source in result["sources"][:3])
    assert all(source["fallback_connected"] for source in result["sources"][:3])
    assert "test-secret" not in str(result) + str(calendar._CACHE)
    assert len(pages["closed"]) == 8


def test_bls_success_does_not_call_fred_even_with_key(pages):
    calendar.load_release_calendar(now=NOW, fred_api_key="test-secret")
    assert len(pages["calls"]) == 5 and not pages["fred_calls"]


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


def test_verified_bok_policy_meetings_exclude_general_and_stability_meetings(pages):
    result = calendar.load_release_calendar(now=NOW)
    bok = [event for event in result["events"] if event["market"] == "KR"]
    assert len(bok) == 8
    assert [event["date"] for event in bok][-2:] == ["2026-10-22", "2026-11-26"]
    assert all(event["release_at"] == event["date"] and event["release_precision"] == "date" for event in bok)
    assert all(event["source_url"] == calendar.BOK_URL and event["source_verified_at"] for event in bok)
    assert not calendar._bok_source(NOW.replace(year=2027))[0]


def test_meta_official_after_close_is_not_the_conference_call_time(pages):
    result = calendar.load_release_calendar(now=NOW)
    meta, = [event for event in result["events"] if event.get("ticker") == "META"]
    assert meta["date"] == meta["release_at"] == "2026-10-21"
    assert meta["session_timing"] == "after_market_close"
    assert meta["release_precision"] == "date" and not meta["release_time_confirmed"]
    assert meta["conference_call_at"] == "2026-10-21T16:30:00-04:00"
    from zoneinfo import ZoneInfo
    assert datetime.fromisoformat(meta["conference_call_at"]).astimezone(ZoneInfo("Asia/Seoul")).isoformat() == "2026-10-22T05:30:00+09:00"


def test_meta_blocked_page_uses_stamped_finite_fixture_without_leaking_error(pages):
    pages["fail"].add(calendar.META_IR_URL)
    result = calendar.load_release_calendar(now=NOW)
    source = next(source for source in result["sources"] if source["name"] == "Meta Investor Relations")
    assert source["provider"] == "verified_fixture" and source["fallback_connected"]
    meta = next(event for event in result["events"] if event.get("ticker") == "META")
    assert meta["source_published_at"] == "2026-10-12" and meta["source_verified_at"]
    assert not calendar._meta_source(NOW.replace(month=9))[0]
    assert not calendar._meta_source(NOW.replace(year=2027))[0]


@pytest.mark.parametrize("html", [META.replace("third quarter 2026", "second quarter 2026"),
                                  META.replace("October 21st", "February 30th"),
                                  META.replace("after market close", "at an unconfirmed time"),
                                  "<p>Meta earnings expected October 22, 2026</p>"])
def test_meta_parser_requires_explicit_announcement_for_the_supported_quarter(html):
    with pytest.raises(calendar._InvalidCalendar):
        calendar._meta_events(html, calendar.META_IR_URL)


@pytest.mark.parametrize("group", ["cpi", "ppi", "empsit"])
def test_fred_standard_clock_converts_dst_to_kst_without_claiming_confirmation(group):
    from zoneinfo import ZoneInfo
    payload = {"release_dates": [{"release_id": calendar._FRED_RELEASES[group], "date": day}
                                for day in ("2026-10-20", "2026-11-10")]}
    rows = calendar._fred_events(payload, group, NOW)
    assert [datetime.fromisoformat(row["release_at"]).astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M")
            for row in rows] == ["21:30", "22:30"]
    assert all(row["release_precision"] == "schedule_rule" and not row["release_time_confirmed"] for row in rows)


def test_fred_without_timezone_database_keeps_date_and_standard_clock_metadata(monkeypatch):
    monkeypatch.setattr(calendar, "ZoneInfo", lambda _: (_ for _ in ()).throw(calendar.ZoneInfoNotFoundError()))
    row, = calendar._fred_events({"release_dates": [{"release_id": 10, "date": "2026-10-20"}]}, "cpi", NOW)
    assert row["release_at"] == "2026-10-20" and row["release_precision"] == "date"
    assert row["schedule_rule"] == "08:30 America/New_York"
