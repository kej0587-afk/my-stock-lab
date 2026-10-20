"""Public-source failures must not erase known observations or publication dates."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import logging

import pytest
import requests

from stock_lab_core import economic_bulletins as bulletins
from stock_lab_core import economic_cache as cache
from stock_lab_core import economic_releases as releases


NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
PUBLISHED = "2026-10-14T08:30:00-04:00"
SCHEDULE_URL = releases._SCHEDULE_URLS["cpi"]


class Response:
    def __init__(self, payload=None, status=200):
        self.payload, self.status_code, self.closed = payload, status, False

    def json(self):
        return deepcopy(self.payload)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    releases.clear_economic_releases_cache()

    def forbidden(*args, **kwargs):
        pytest.fail("Use public response fixtures; no credentials or network")

    monkeypatch.setattr(releases, "_api_key", forbidden)
    monkeypatch.setattr(releases.requests, "get", forbidden)
    monkeypatch.setattr(releases.requests, "post", forbidden)
    yield
    releases.clear_economic_releases_cache()


@pytest.fixture
def bls(monkeypatch):
    state = {"status": 200, "error": None, "calls": [], "responses": []}
    series = []
    for spec in releases._BLS_SERIES:
        values = {"2025-08": 100, "2025-09": 100, "2026-07": 101,
                  "2026-08": 102, "2026-09": 103}
        series.append({"seriesID": spec.series, "data": [
            {"year": period[:4], "period": "M" + period[5:], "value": str(value)}
            for period, value in values.items()]})

    def post(url, **kwargs):
        assert url == releases.BLS_URL
        assert kwargs["timeout"] == 4 and kwargs["allow_redirects"] is False
        assert set(kwargs["json"]) == {"seriesid", "startyear", "endyear"}
        state["calls"].append(kwargs)
        if state["error"]:
            raise state["error"]
        response = Response({"status": "REQUEST_SUCCEEDED", "Results": {"series": series}}, state["status"])
        state["responses"].append(response)
        return response

    monkeypatch.setattr(releases.requests, "post", post)
    return state


@pytest.mark.parametrize("failure", [403, 429, 503, "timeout"])
def test_bls_diagnostics_distinguish_failed_collection_from_pending(bls, caplog, failure):
    if failure == "timeout":
        bls["error"] = requests.ReadTimeout("https://example.test/?key=private-value")
    else:
        bls["status"] = failure
    with caplog.at_level(logging.WARNING):
        rows = releases._bls(NOW)
    for row in rows:
        assert row["status"] == "unavailable" and row["publication_status"] == "unconfirmed"
        assert row["actual"] is None and row["release_at"] is None
        assert "awaiting_release" not in row["missing_reason"]
        assert row["request_metadata"]["failure_reason"] == row["missing_reason"]
        if failure == "timeout":
            assert row["request_metadata"]["transport_error"] == "ReadTimeout"
            assert row["request_metadata"]["http_status"] is None
        else:
            assert row["request_metadata"]["http_status"] == failure
    assert "BLS HTTP=" in caplog.text
    assert "private-value" not in json.dumps(rows) + caplog.text
    releases._bls(NOW)
    assert len(bls["calls"]) == 2
    assert all(response.closed for response in bls["responses"])


def test_bls_success_cache_retains_safe_request_diagnostics(bls):
    first = releases._bls(NOW)
    assert first[0]["publication_status"] == "available"
    assert first[0]["request_metadata"]["http_status"] == 200
    assert first[0]["request_metadata"]["from_cache"] is False
    first[0]["request_metadata"]["http_status"] = 999
    cached = releases._bls(NOW)
    assert cached[0]["request_metadata"]["http_status"] == 200
    assert cached[0]["request_metadata"]["from_cache"] is True
    assert cached[0]["request_metadata"]["latest_observation_period"] == "2026-09"
    assert len(bls["calls"]) == 1


def test_bls_legacy_cache_reconnects_calendar_after_failed_batch(bls, monkeypatch):
    cache.retain_successful_observations(releases._bls(NOW), NOW)
    releases.clear_economic_releases_cache()
    bls["status"] = 503
    monkeypatch.setattr(releases, "_api_key", lambda name: "")
    monkeypatch.setattr(releases, "_retail", lambda now, key: releases._row(
        "US_RETAIL_SALES", "%", "MoM", "Census fixture", "", now))
    monkeypatch.setattr(releases, "load_release_calendar", lambda **kwargs: {
        "sources": [{"name": "BLS CPI", "connected": True}],
        "events": [{"indicator": "US_CPI", "period": "2026-09", "release_at": PUBLISHED,
                    "source_url": SCHEDULE_URL}]})
    rows = releases.load_economic_releases(now=NOW)
    row = next(row for row in rows if row["indicator"] == "US_CPI")
    assert row["status"] == "stale" and row["actual"] == 1.0
    assert row["period"] == "2026-09" and row["release_at"] == PUBLISHED
    assert row["release_source_url"] == SCHEDULE_URL
    assert "release_schedule_period_unavailable" not in row["missing_reason"]
    assert "release_date_unavailable" not in row["missing_reason"]
    assert row["collection_error"].startswith("http_503")
    assert row["request_metadata"]["http_status"] == 503
    assert row["publication_status"] == "unconfirmed"


@pytest.mark.parametrize("publication", [PUBLISHED, "2026-11-14T08:30:00-05:00", None])
def test_cache_preserves_only_sourced_past_release_for_restored_period(bls, publication):
    row = releases._bls(NOW)[0]
    row.update(release_at=publication, release_precision="datetime", release_source="BLS schedule",
               release_source_url=SCHEDULE_URL, forecast=999)
    cache.retain_successful_observations([row], NOW)
    failure = releases._row("US_CPI", "%", "MoM", "BLS", releases.BLS_URL, NOW,
                            series_id=row["series_id"], seasonal_adjustment="SA",
                            release_at="2026-11-10", forecast=777, missing_reason="http_503",
                            request_metadata={"http_status": 503})
    restored = cache.retain_successful_observations([failure], NOW)[0]
    expected = PUBLISHED if publication == PUBLISHED else None
    assert restored["release_at"] == expected and restored["period"] == "2026-09"
    assert restored["forecast"] is None and restored["status"] == "stale"
    assert restored["request_metadata"] == {"http_status": 503}
    saved = json.loads(cache.CACHE_PATH.read_text(encoding="utf-8"))
    assert "forecast" not in next(iter(saved.values()))


@pytest.mark.parametrize("period", ["2026-09", "2026-10"])
def test_successful_refresh_without_date_cannot_erase_same_month_publication(bls, period):
    first = releases._bls(NOW)[0]
    first.update(release_at=PUBLISHED, release_precision="datetime", release_source="BLS schedule",
                 release_source_url=SCHEDULE_URL)
    cache.retain_successful_observations([first], NOW)
    refresh = dict(first, period=period, release_at=None, release_precision=None,
                   release_source=None, release_source_url=None, missing_reason="release_date_unavailable")
    result = cache.retain_successful_observations([refresh], NOW)[0]
    assert result["release_at"] == (PUBLISHED if period == "2026-09" else None)
    assert ("release_date_unavailable" in result["missing_reason"]) == (period != "2026-09")


@pytest.fixture
def public_cpi(monkeypatch):
    # Exact public ECOS samples underlying the user's latest report, not a seed.
    values = {"202606": "119.99", "202607": "119.77", "202608": "120.05", "202609": "120.43",
              "202506": "116.31", "202507": "116.52", "202508": "116.45", "202509": "117.06"}
    calls = []

    def get(url, **kwargs):
        assert "/sample/json/kr/1/10/" in url
        calls.append(url)
        if "StatisticItemList" in url:
            return Response({"StatisticItemList": {"row": [{
                "STAT_CODE": "901Y009", "ITEM_CODE": "0", "STAT_NAME": "소비자물가지수",
                "ITEM_NAME": "총지수", "GRP_CODE": "Group1", "CYCLE": "M", "UNIT_NAME": "2020=100"}]}})
        first, last = url.split("/")[-3:-1]
        return Response({"StatisticSearch": {"row": [{
            "STAT_CODE": "901Y009", "ITEM_CODE1": "0", "ITEM_NAME1": "총지수",
            "UNIT_NAME": "2020=100", "TIME": month, "DATA_VALUE": value}
            for month, value in values.items() if first <= month <= last]}})

    monkeypatch.setattr(releases.requests, "get", get)
    return calls


@pytest.mark.parametrize("period", ["2026-09", "2026-08", ""])
def test_cpi_public_recovery_keeps_report_values_and_only_same_period_date(public_cpi, period):
    base = releases._ecos(NOW, "", "KR_CPI")
    base.update(period=period, release_at="2026-10-01", release_precision="date",
                release_source="official fixture", release_source_url="https://kostat.go.kr/")
    result = bulletins.apply_official_bulletins([base], NOW)[0]
    assert (result["period"], result["actual"], result["previous"]) == ("2026-09", 2.9, 3.1)
    assert result["previous3mean"] == pytest.approx(3.033333)
    assert result["release_at"] == ("2026-10-01" if period == "2026-09" else None)
    assert ("release_date_unavailable" in result["missing_reason"]) == (period != "2026-09")
    assert result["source_url"] in public_cpi and "StatisticSearch/sample/" in result["source_url"]
    assert result["publication_status"] == "available" and result["forecast"] is None


@pytest.mark.parametrize("error,label", [
    ("http_503", "공급처 HTTP 오류"),
    ("request_failed:ReadTimeout", "응답 시간 초과"),
    ("ecos_observation_series_or_unit_mismatch", "통계 항목/단위 검증 실패"),
])
def test_public_fallback_failure_is_not_misreported_as_missing_private_key(error, label):
    row = {"status": "unavailable", "missing_reason": "ECOS_API_KEY_missing;cpi_automatic_primary_unavailable",
           "collection_error": "ECOS_API_KEY_missing", "bulletin_collection_error": error}
    assert cache.collection_status(row) == label


def test_explicit_pending_and_census_key_requirement_have_distinct_diagnostics():
    assert cache.collection_status({"status": "pending"}) == "발표 대기"
    assert cache.collection_status({"missing_reason": "CENSUS_API_KEY_required_or_invalid_response"}) == "Census API 키 필요"
