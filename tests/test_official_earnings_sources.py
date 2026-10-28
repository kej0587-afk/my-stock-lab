"""Primary-source date facts and synthetic transport fixtures; no network."""

from datetime import datetime, timedelta
import json

import pytest
import requests

from stock_lab_core import earnings_sources as earnings
from stock_lab_core import release_calendar as calendar

NOW = datetime.fromisoformat("2026-10-28T09:00:00+00:00")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    earnings.clear_earnings_source_cache()
    monkeypatch.setattr(earnings.requests, "get", lambda *a, **k: pytest.fail("Unexpected network"))
    yield
    earnings.clear_earnings_source_cache()


@pytest.fixture
def pages(monkeypatch):
    state = dict(calls=[], closed=[], status=200, error=None, changed=False)
    specs = {spec["url"]: spec for spec in earnings._ISSUERS.values()}

    class Response:
        def __init__(self, url):
            self.status_code = state["status"]
            self.text = "changed" if state["changed"] else "<p>" + " </p><p>".join(specs[url]["evidence"]) + "</p>"
            self.content = self.text.encode()

        def close(self):
            state["closed"].append(True)

    def get(url, **kwargs):
        assert kwargs["timeout"] == (2, 4) and kwargs["allow_redirects"] is False
        state["calls"].append(url)
        if state["error"]:
            raise state["error"]
        return Response(url)

    monkeypatch.setattr(earnings.requests, "get", get)
    return state


def test_seven_verified_issuers_keep_results_and_next_schedules_distinct(pages):
    result = earnings.load_official_earnings(earnings._ISSUERS, NOW)
    assert len(result["events"]) == 7 and len(pages["calls"]) == 6
    assert len(pages["closed"]) == 6
    assert {e["ticker"] for e in result["recent_earnings"]} == {"META", "TSLA", "000660.KS"}
    assert {e["ticker"] for e in result["upcoming_earnings"]} == {"GOOGL", "MSFT", "005930.KS", "NVDA"}
    assert all(not e["release_time_confirmed"] for e in result["events"])
    assert all(e["release_precision"] == "date" for e in result["events"] if e["event_kind"] != "conference_call")
    assert all(e["source_url"].startswith("https://") and e["source_verified_at"] for e in result["events"])
    for s in result["sources"]:
        assert s["next_schedule_status"] == ("unconfirmed" if s["ticker"] in {"META", "TSLA", "000660.KS"} else "confirmed")
    nvda = next(e for e in result["events"] if e["ticker"] == "NVDA")
    assert nvda["date"] == "2026-11-17" and nvda["source_page"] == 15
    assert nvda["event_kind"] == "conference_call" and not nvda["release_date_confirmed"]
    assert nvda["release_at"] is None and nvda["release_precision"] == "unconfirmed"
    assert nvda["event_at"] == "2026-11-17" and nvda["event_precision"] == "date"
    assert "conference_call_at" not in nvda
    samsung = next(e for e in result["events"] if e["ticker"] == "005930.KS")
    assert samsung["conference_call_at"] == "2026-10-29T10:00:00+09:00"
    assert not samsung["release_date_confirmed"] and samsung["release_at"] is None
    assert samsung["event_at"] == samsung["conference_call_at"] and samsung["event_precision"] == "datetime"


def test_holdings_only_alias_dedup_unknown_status_and_collection_cap(pages):
    result = earnings.load_official_earnings(["GOOG", "googl", "GOOG", "005930", "005935.KS", "UNKNOWN"], NOW)
    assert len(pages["calls"]) == 2 and len(result["events"]) == 2
    assert result["sources"][0]["requested_tickers"] == ["GOOG", "GOOGL"]
    assert result["sources"][-1]["coverage_status"] == "unconnected"
    assert result["sources"][-1]["reason"] == "issuer_not_connected"
    assert earnings.load_official_earnings([], NOW)["events"] == []
    large = earnings.load_official_earnings(("UNKNOWN" + str(i) for i in range(10000)), NOW)
    assert len(large["sources"]) == earnings.MAX_TICKERS + 1
    assert large["sources"][-1]["reason"] == "ticker_limit" and len(pages["calls"]) == 2


def test_verified_timestamp_and_expiry_never_leak_future_results(pages):
    before = datetime.fromisoformat(earnings.VERIFIED_AT) - timedelta(seconds=1)
    assert earnings.load_official_earnings(earnings._ISSUERS, before)["events"] == []
    assert earnings.load_official_earnings(earnings._ISSUERS, NOW.replace(year=2027))["events"] == []
    at_expiry = NOW.replace(month=11, day=21, hour=0)
    assert earnings.load_official_earnings(["META", "TSLA"], at_expiry)["events"] == []
    assert not pages["calls"]


def test_elapsed_schedule_does_not_assert_released_or_stay_upcoming():
    result = earnings.load_official_earnings(["GOOGL", "MSFT", "005930.KS"],
                                            NOW.replace(hour=22), refresh=False)
    assert {e["ticker"] for e in result["elapsed_earnings"]} == {"GOOGL", "MSFT"}
    assert not result["recent_earnings"]
    assert [e["ticker"] for e in result["upcoming_earnings"]] == ["005930.KS"]
    after_call = earnings.load_official_earnings("005930.KS", NOW.replace(day=29, hour=1), refresh=False)
    assert after_call["events"][0]["event_status"] == "elapsed_unconfirmed"


def test_transport_fallback_is_visible_cached_safe_and_expiring(pages, monkeypatch):
    tick = [100.0]
    monkeypatch.setattr(earnings.time, "monotonic", lambda: tick[0])
    pages["error"] = requests.ConnectTimeout("https://private.test/?key=secret-not-output")
    result = earnings.load_official_earnings(["MSFT"], NOW)
    source = result["sources"][0]
    assert source["provider"] == "verified_snapshot" and source["fallback_connected"]
    assert source["primary_reason"] == "request_failed:ConnectTimeout"
    assert "secret-not-output" not in json.dumps(result) + str(earnings._CACHE)
    cached = earnings.load_official_earnings(["MSFT"], NOW)
    assert cached["sources"][0]["request"]["from_cache"] and len(pages["calls"]) == 1
    tick[0] += earnings.FAILURE_TTL + 1
    pages["error"] = None
    recovered = earnings.load_official_earnings(["MSFT"], NOW)
    assert recovered["sources"][0]["provider"] == "official_page" and len(pages["calls"]) == 2
    expired = earnings.load_official_earnings(["MSFT"], NOW.replace(month=11, day=4))
    assert not expired["events"] and len(pages["calls"]) == 2


def test_success_cache_isolated_and_expires(pages, monkeypatch):
    tick = [100.0]
    monkeypatch.setattr(earnings.time, "monotonic", lambda: tick[0])
    result = earnings.load_official_earnings(["META"], NOW)
    result["sources"][0]["request"]["status"] = "mutated"
    result["events"][0]["date"] = "2000-01-01"
    cached = earnings.load_official_earnings(["META"], NOW)
    assert cached["sources"][0]["request"]["status"] == "connected"
    assert cached["events"][0]["date"] == "2026-10-21" and len(pages["calls"]) == 1
    tick[0] += earnings.CACHE_TTL + 1
    earnings.load_official_earnings(["META"], NOW)
    assert len(pages["calls"]) == 2


def test_changed_evidence_and_script_only_text_fail_closed(pages, monkeypatch):
    pages["changed"] = True
    result = earnings.load_official_earnings(["GOOGL"], NOW)
    assert not result["events"] and result["sources"][0]["reason"] == "announcement_evidence_changed"
    text = earnings._Text('<script>verified title</script><style>date</style><p>visible</p>')
    assert text.parts == ["visible"]


def test_release_calendar_preserves_recent_default_and_explicit_issuer_scope(monkeypatch):
    monkeypatch.setattr(calendar, "_load_bls_source", lambda *a: ([], dict(name="BLS", status="unavailable")))
    monkeypatch.setattr(calendar, "_load_source", lambda *a, **k: ([], dict(name="Fed", status="unavailable")))
    result = calendar.load_release_calendar(NOW)
    assert {e["ticker"] for e in result["recent_earnings"]} == {"META", "TSLA"}
    assert not result["upcoming_earnings"]
    monkeypatch.setattr(calendar, "load_official_earnings",
                        lambda tickers, now: earnings.load_official_earnings(tickers, now, refresh=False))
    result = calendar.load_release_calendar(NOW, earnings_tickers=["GOOG", "UNKNOWN"])
    assert [e["ticker"] for e in result["upcoming_earnings"]] == ["GOOGL"]
    assert not result["recent_earnings"]
    assert any(s.get("reason") == "issuer_not_connected" for s in result["sources"])
