from datetime import datetime

import pytest

from stock_lab_core import release_calendar as calendar

ANNOUNCEMENT = """<p>Tesla will post its financial results for the third quarter of 2026
after market close on Wednesday, October 21, 2026.</p><p>4:30 p.m. Central Time / 5:30 p.m. Eastern Time</p>"""


def test_verified_after_close_announcement_separates_release_and_call():
    event, = calendar._tesla_events(ANNOUNCEMENT)
    assert event["release_at"] == "2026-10-21" and not event["release_time_confirmed"]
    assert event["conference_call_at"] == "2026-10-21T17:30:00-04:00"
    assert event["source_url"] == calendar.TESLA_IR_URL


def test_earnings_parser_does_not_turn_forecast_or_other_quarter_into_an_event():
    for page in ("Tesla earnings expected October 21, 2026", ANNOUNCEMENT.replace("third", "fourth")):
        with pytest.raises(calendar._InvalidCalendar):
            calendar._tesla_events(page)


def test_finite_verified_announcement_has_provenance_without_an_extra_request(monkeypatch):
    calendar.clear_release_calendar_cache()
    monkeypatch.setattr(calendar, "_request", lambda url: pytest.fail("No extra calendar request expected"))
    events, source = calendar._tesla_source(datetime.fromisoformat("2026-10-21T12:00:00+00:00"))
    assert source["provider"] == "verified_fixture" and source["status"] == "connected"
    assert events[0]["source_verified_at"] == "2026-10-21"
    events, source = calendar._tesla_source(datetime.fromisoformat("2027-01-21T12:00:00+00:00"))
    assert not events and source["status"] == "unavailable"
    calendar.clear_release_calendar_cache()
