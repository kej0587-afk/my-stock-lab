"""Calendar reuse preserves finalized rows without a second collection."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from stock_lab_core import economic_releases as releases


NOW = datetime(2026, 10, 21, 5, tzinfo=timezone.utc)


@pytest.fixture
def offline_collectors(monkeypatch):
    monkeypatch.setattr(releases, "_api_key", lambda name: "")
    monkeypatch.setattr(releases.requests.sessions.Session, "request",
                        Mock(side_effect=AssertionError("Unexpected network request")))

    def bls(now):
        return [releases._row(
            spec.indicator, "thousand persons" if spec.mode == "change" else "%",
            spec.basis, "BLS", releases.BLS_URL, now,
            period="2026-09", actual=1.0, status="released", series_id=spec.series,
        ) for spec in releases._BLS_SERIES]

    monkeypatch.setattr(releases, "_bls", bls)
    monkeypatch.setattr(releases, "_retail", lambda now, key: releases._row(
        "US_RETAIL_SALES", "%", "MoM", "US Census Bureau", releases.CENSUS_URL, now))
    monkeypatch.setattr(releases, "_fed", lambda now, key: releases._row(
        "US_FED_TARGET_UPPER", "%", "level", "FRED", releases.FRED_URL, now))
    monkeypatch.setattr(releases, "_ecos", lambda now, key, indicator: releases._row(
        indicator, "%", "YoY", "Bank of Korea ECOS", releases.ECOS_URL, now))


def _calendar(connected):
    groups = (("US_CPI", "BLS CPI"), ("US_PPI", "BLS PPI"),
              ("US_NONFARM_PAYROLLS", "BLS Employment Situation"))
    return {
        "events": [{
            "indicator": indicator, "period": "2026-09", "date": "2026-10-14",
            "release_at": "2026-10-14T08:30:00-04:00",
            "source_url": "https://example.test/calendar",
        } for indicator, _ in groups] if connected else [],
        "sources": [{
            "name": name, "status": "connected" if connected else "unavailable",
            "reason": "" if connected else "request_failed:Timeout",
        } for _, name in groups],
        "connected": connected,
    }


@pytest.mark.parametrize("connected", [True, False], ids=["success", "failure"])
@pytest.mark.parametrize("default_options", [{}, {"include_calendar": False}],
                         ids=["default", "explicit-false"])
def test_calendar_collected_once_and_rows_unchanged(
        monkeypatch, offline_collectors, connected, default_options):
    calendar = _calendar(connected)
    loader = Mock(return_value=calendar)
    monkeypatch.setattr(releases, "load_release_calendar", loader)
    events = [{
        "indicator": "US_CPI", "period": "2026-09", "basis": "MoM", "unit": "%",
        "forecast": 0.3, "forecast_source": "fixture survey",
    }]

    default_rows = releases.load_economic_releases(events, now=NOW, **default_options)
    assert isinstance(default_rows, list)
    loader.assert_called_once_with(now=NOW, fred_api_key="")
    loader.reset_mock()

    result = releases.load_economic_releases(events, now=NOW, include_calendar=True)
    loader.assert_called_once_with(now=NOW, fred_api_key="")
    assert isinstance(result, tuple) and len(result) == 2
    rows, returned_calendar = result
    assert rows == default_rows
    assert returned_calendar is calendar
    assert returned_calendar == _calendar(connected)
    assert rows[0]["actual_minus_forecast"] == 0.7
    assert rows[0]["publication_status"] == "available"
    assert rows[0]["release_calendar_status"] == calendar["sources"][0]
    if connected:
        assert rows[0]["release_at"] == calendar["events"][0]["release_at"]
    else:
        assert rows[0]["release_at"] is None
        assert "release_schedule_request_failed:Timeout" in rows[0]["missing_reason"]


def test_include_calendar_is_keyword_only(offline_collectors):
    with pytest.raises(TypeError):
        releases.load_economic_releases(None, NOW, True)
