"""Small official-shape fixtures; all normal tests are offline."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
import requests

from stock_lab_core import market_watch_calendar as watch
from stock_lab_core import release_calendar as calendar

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
CENSUS = '''<h1>Release Dates</h1><h2><strong>Advance Monthly Retail Trade Report</strong></h2>
<table><tr><td>Data Month</td><td>Release Date at 8:30 am</td></tr>
<tr><td>September 2026</td><td>October 15, 2026</td></tr>
<tr><td>October 2026</td><td>November 17, 2026</td></tr>
<tr><td>December 2026</td><td>January 15, 2027</td></tr>
<tr><td>January 2027</td><td>To be announced at a later date</td></tr></table>
<h2>Monthly Retail Trade Report</h2><table><tr><td>September 2026</td><td>November 17, 2026</td></tr></table>
<h2>Quarterly Retail E-Commerce Report</h2><table><tr><td>3rd Quarter 2026</td><td>November 19, 2026</td></tr></table>'''
APEC = '''<p>Publication 14 November 2026.</p><p>Leaders gather in Shenzhen, China,
for the APEC Economic Leaders' Meeting on 18–19 November, the culmination of
APEC Economic Leaders' Week 2026.</p><p>A bilateral meeting is unconfirmed.</p>'''
NEXT_RETAIL = "The October 2026 Advance Monthly Retail report is scheduled for release on November 17, 2026 at 8:30 a.m. EST."


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    calendar.clear_release_calendar_cache()
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: pytest.fail("Unexpected HTTP"))
    yield
    calendar.clear_release_calendar_cache()


def test_advance_periods_not_monthly_or_ecommerce_and_time_requires_zone_evidence():
    events = watch.parse_census_advance(CENSUS, NOW)
    assert [(e["period"], e["date"]) for e in events] == [
        ("2026-09", "2026-10-15"), ("2026-10", "2026-11-17"), ("2026-12", "2027-01-15")]
    assert all(e["indicator"] == "US_RETAIL_SALES" and e["source_url"] == watch.CENSUS_URL for e in events)
    assert all(e["release_at"] == e["date"] and e["release_precision"] == "date" and not e["release_time_confirmed"] for e in events)
    assert events[0]["event_status"] == "elapsed_unconfirmed"
    assert "actual" not in events[0] and "consensus" not in events[0]
    assert all(e["source_verified_at"] == NOW.isoformat() and e["coverage_expires_at"] ==
               (NOW + timedelta(seconds=calendar.CACHE_TTL)).isoformat() for e in events)


@pytest.mark.parametrize("zone", ["ET", "Eastern Time"])
def test_explicit_eastern_time_uses_dst_and_preserves_source_dates(zone):
    events = watch.parse_census_advance(CENSUS.replace("8:30 am", "8:30 am " + zone), NOW)
    assert events[0]["release_at"] == "2026-10-15T08:30:00-04:00"
    assert events[1]["release_at"] == "2026-11-17T08:30:00-05:00"
    assert all(e["timezone"] == "America/New_York" and e["release_precision"] == "datetime" for e in events)


@pytest.mark.parametrize("html", ["blocked", CENSUS.replace("Advance Monthly", "Other Monthly"),
    CENSUS.replace("September 2026", "invalid").replace("October 2026", "invalid").replace("December 2026", "invalid")])
def test_unrecognized_or_wrong_sections_fail_closed(html):
    with pytest.raises(calendar._InvalidCalendar):
        watch.parse_census_advance(html, NOW)


def test_conflicting_duplicate_period_is_not_arbitrarily_chosen():
    html = CENSUS.replace("<tr><td>December 2026", "<tr><td>October 2026</td><td>November 18, 2026</td></tr><tr><td>December 2026")
    with pytest.raises(calendar._InvalidCalendar, match="conflicting"):
        watch.parse_census_advance(html, NOW)


def test_apec_range_is_date_only_and_not_bilateral_confirmation():
    event, = watch.parse_apec_meeting(APEC, NOW)
    assert (event["start_date"], event["end_date"]) == ("2026-11-18", "2026-11-19")
    assert event["market"] == "GLOBAL" and event["release_precision"] == "date"
    assert event["release_at"] == "2026-11-18" and not event["release_time_confirmed"]
    assert event["event"] == "APEC Economic Leaders' Meeting"


@pytest.mark.parametrize("html", [APEC.replace("18–19", "TBA"), APEC.replace("Week 2026", "Week"),
                                     APEC.replace("18–19 November", "31–32 November")])
def test_apec_needs_explicit_range_and_same_context_year(html):
    with pytest.raises(calendar._InvalidCalendar):
        watch.parse_apec_meeting(html, NOW)


def test_loader_reuses_existing_cache_retries_failures_with_three_bounded_sources(monkeypatch):
    state = {"calls": [], "fail": True, "closed": 0}
    tick = [1.0]
    monkeypatch.setattr(calendar.time, "monotonic", lambda: tick[0])
    pdf = b"%PDF-1.7 synthetic verified calendar fixture"
    monkeypatch.setattr(watch, "CBOE_SHA256", sha256(pdf).hexdigest())
    monkeypatch.setattr(watch, "_parse_census_next_release_pdf", lambda data, now: watch.parse_census_next_release_text(NEXT_RETAIL, now))

    class Response:
        def __init__(self, url):
            self.status_code = 403 if state["fail"] and url == watch.CENSUS_URL else 200
            self.text = CENSUS if url == watch.CENSUS_URL else APEC
        def iter_content(self, chunk_size):
            yield pdf
        def close(self):
            state["closed"] += 1

    def get(url, **kwargs):
        assert url in {watch.CENSUS_URL, watch.APEC_URL, watch.CBOE_URL, watch.CENSUS_PDF_URL}
        assert kwargs["timeout"] == 4 and kwargs["allow_redirects"] is False
        state["calls"].append(url)
        return Response(url)

    monkeypatch.setattr(calendar.requests, "get", get)
    first = watch.load_market_watch_calendar(NOW)
    assert first["sources"][0]["reason"] == "http_403" and first["connected"]
    assert first["sources"][-1]["source_kind"] == "verified_calendar_mapping"
    state["fail"] = False
    result = watch.load_market_watch_calendar(NOW)
    assert len(result["events"]) == 12 and len(state["calls"]) == 5
    timed = next(e for e in result["events"] if e.get("period") == "2026-10")
    assert timed["release_at"] == "2026-11-17T08:30:00-05:00" and timed["source_url"] == watch.CENSUS_PDF_URL
    assert result["sources"][0]["source_verified_at"] == NOW.isoformat()
    expiry = (NOW + timedelta(seconds=calendar.CACHE_TTL)).isoformat()
    assert result["sources"][0]["coverage_expires_at"] == expiry
    result["events"][0]["event"] = "mutated"
    cached = watch.load_market_watch_calendar(NOW + timedelta(seconds=10))
    assert cached["events"][0]["event"] != "mutated"
    assert all(e["source_verified_at"] == NOW.isoformat() and e["coverage_expires_at"] == expiry for e in cached["events"])
    assert len(state["calls"]) == 5
    tick[0] += calendar.CACHE_TTL + 1
    refreshed_at = NOW + timedelta(seconds=calendar.CACHE_TTL + 1)
    refreshed = watch.load_market_watch_calendar(refreshed_at)
    assert all(e["source_verified_at"] == refreshed_at.isoformat() and
               datetime.fromisoformat(e["coverage_expires_at"]) > refreshed_at for e in refreshed["events"])
    assert len(state["calls"]) == 9 and state["closed"] == 9


def test_next_retail_clock_uses_exact_future_sentence_not_previous_release_edt():
    page = "FOR RELEASE AT 8:30 AM EDT, OCTOBER 15, 2026. " + NEXT_RETAIL
    row, = watch.parse_census_next_release_text(page, NOW)
    assert row["period"] == "2026-10" and row["date"] == "2026-11-17"
    assert row["release_at"] == "2026-11-17T08:30:00-05:00"
    from zoneinfo import ZoneInfo
    assert datetime.fromisoformat(row["release_at"]).astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M") == "22:30"
    with pytest.raises(calendar._InvalidCalendar):
        watch.parse_census_next_release_text(NEXT_RETAIL.replace("EST", "EDT"), NOW)
    with pytest.raises(calendar._InvalidCalendar):
        watch.parse_census_next_release_text("Next release November 17, 2026; previous release 8:30 AM EDT", NOW)


@pytest.mark.parametrize("change", [{"date": "2026-11-18"}, {"period": "2026-09"}, {}])
def test_time_proof_requires_both_period_and_date_and_does_not_change_other_rows(monkeypatch, change):
    events = watch.parse_census_advance(CENSUS, NOW)
    proof = dict(watch.parse_census_next_release_text(NEXT_RETAIL, NOW)[0], **change)
    monkeypatch.setattr(calendar, "_load_source", lambda *a, **k: ([proof], {"status": "connected"}))
    watch._attach_census_clock(events, NOW)
    timed = [e for e in events if e["release_precision"] == "datetime"]
    assert len(timed) == (0 if change else 1)
    assert [(e["period"], e["date"]) for e in events] == [("2026-09", "2026-10-15"), ("2026-10", "2026-11-17"), ("2026-12", "2027-01-15")]


def test_missing_pdf_time_preserves_date_and_honest_source_failure(monkeypatch):
    events = watch.parse_census_advance(CENSUS, NOW)
    monkeypatch.setattr(calendar, "_load_source", lambda *a, **k: ([], {"status": "unavailable", "reason": "http_403"}))
    source = watch._attach_census_clock(events, NOW)
    assert source["reason"] == "http_403" and all(e["release_precision"] == "date" for e in events)


@pytest.mark.parametrize("now,status", [("2026-11-18T00:30:00+00:00", "scheduled"), ("2026-11-18T05:01:00+00:00", "elapsed_unconfirmed")])
def test_date_only_us_schedule_uses_local_day_not_utc_day(now, status):
    row = next(e for e in watch.parse_census_advance(CENSUS, datetime.fromisoformat(now)) if e["period"] == "2026-10")
    assert row["event_status"] == status and row["release_precision"] == "date"


def test_global_multiday_schedule_uses_its_own_local_end_date():
    row, = watch.parse_apec_meeting(APEC, datetime.fromisoformat("2026-11-19T16:01:00+00:00"))
    assert row["event_status"] == "elapsed_unconfirmed"


def test_timeout_returns_visible_missing_sources_without_guessed_dates(monkeypatch):
    def fail(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(calendar.requests, "get", fail)
    result = watch.load_market_watch_calendar(NOW)
    assert result["events"] == [] and not result["connected"]
    assert all(s["reason"] == "request_failed:Timeout" for s in result["sources"])


def test_cboe_exact_finite_visual_mapping_has_distinct_last_trade_and_expiration_dates():
    events = watch._cboe_events(watch.CBOE_SHA256, NOW)
    assert [(e["date"], e["indicator"]) for e in events] == [
        ("2026-11-17", "US_VIX_LAST_TRADE"), ("2026-11-18", "US_VIX_STANDARD_EXPIRY"),
        ("2026-11-19", "US_AM_INDEX_OPTIONS_LAST_TRADE"), ("2026-11-20", "US_STANDARD_OPTIONS_EXPIRY"),
        ("2026-12-15", "US_VIX_LAST_TRADE"), ("2026-12-16", "US_VIX_STANDARD_EXPIRY"),
        ("2026-12-17", "US_AM_INDEX_OPTIONS_LAST_TRADE"), ("2026-12-18", "US_STANDARD_OPTIONS_EXPIRY")]
    assert all(e["source_kind"] == "verified_calendar_mapping" and e["verified_at"] == "2026-11-15"
               and e["expires_at"] == "2027-01-01T00:00:00+00:00" for e in events)
    assert all(e["release_at"] == e["date"] and not e["release_time_confirmed"] for e in events)
    assert events[0]["event_kind"] != events[1]["event_kind"]
    with pytest.raises(calendar._InvalidCalendar, match="sha256_changed"):
        watch._cboe_events("different-file", NOW)


@pytest.mark.parametrize("now", [datetime(2026, 11, 14, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc)])
def test_cboe_mapping_has_no_future_verification_or_next_year_rollover(monkeypatch, now):
    monkeypatch.setattr(watch, "_fetch_cboe_sha256", lambda: pytest.fail("Outside validity must not fetch"))
    events, source = watch._load_cboe_source(now)
    assert events == [] and source["reason"] == "cboe_verified_mapping_outside_validity"


def test_cboe_failed_refresh_does_not_republish_old_verified_schedule(monkeypatch):
    tick = [1.0]
    monkeypatch.setattr(calendar.time, "monotonic", lambda: tick[0])
    monkeypatch.setattr(watch, "_fetch_cboe_sha256", lambda: watch.CBOE_SHA256)
    assert len(watch._load_cboe_source(NOW)[0]) == 8
    tick[0] += calendar.CACHE_TTL + 1
    monkeypatch.setattr(watch, "_fetch_cboe_sha256", lambda: "changed")
    events, source = watch._load_cboe_source(NOW + timedelta(seconds=calendar.CACHE_TTL + 1))
    assert events == [] and source["reason"] == "cboe_pdf_sha256_changed"


def test_cboe_cache_cannot_extend_mapping_expiry(monkeypatch):
    monkeypatch.setattr(watch, "_fetch_cboe_sha256", lambda: watch.CBOE_SHA256)
    events, _ = watch._load_cboe_source(watch.CBOE_EXPIRES_AT - timedelta(minutes=5))
    assert all(e["coverage_expires_at"] == watch.CBOE_EXPIRES_AT.isoformat() for e in events)
    assert watch._load_cboe_source(watch.CBOE_EXPIRES_AT)[0] == []


@pytest.mark.parametrize("status,chunks,reason", [
    (403, [], "http_403"), (200, [b"<html>blocked</html>"], "not_pdf"),
    (200, [b"%PDF-" + b"x" * 2_000_000], "size_limit"),
])
def test_cboe_download_rejects_errors_nonpdf_and_oversize_and_always_closes(monkeypatch, status, chunks, reason):
    closed = []
    class Response:
        status_code = status
        def iter_content(self, chunk_size):
            yield from chunks
        def close(self):
            closed.append(True)
    monkeypatch.setattr(calendar.requests, "get", lambda *a, **k: Response())
    with pytest.raises(calendar._InvalidCalendar, match=reason):
        watch._fetch_cboe_sha256()
    assert closed == [True]
