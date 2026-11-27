"""Restart-safe identity cache; no network, credentials or invented financials."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import time
from unittest.mock import Mock

import pytest

from stock_lab_core import dart_corporate_codes as codes
from stock_lab_core import dart_corporate_snapshot as snapshot
from stock_lab_core import earnings_filing_sources as sources
from stock_lab_core.earnings_dart_directory import directory_cache_valid, prepare_directory
from stock_lab_core.report_dart_earnings import identity_notice_lines

NOW = datetime(2026, 11, 27, 1, tzinfo=timezone.utc)
CODES = {"123456": "00123456"}


def payload(stamp=NOW):
    return {"version": 1, "source": snapshot.SOURCE, "retrieved_at": stamp.isoformat(), "codes": dict(CODES)}


@pytest.fixture(autouse=True)
def isolated():
    sources.clear_cache()
    snapshot.configure_corporate_store(None)
    yield
    sources.clear_cache()
    snapshot.configure_corporate_store(None)


@pytest.mark.parametrize("age,usable", [
    (timedelta(), True), (timedelta(hours=23, minutes=59), True),
    (timedelta(days=1), False), (timedelta(days=2), False),
    (timedelta(seconds=-1), False),
])
def test_original_day_lifetime_not_seven_day_outage_fallback(age, usable):
    store = Mock(load=Mock(return_value=payload(NOW - age)))
    result = snapshot.fresh_corporate_codes(now=NOW, store=store)
    assert bool(result) is usable
    store.save.assert_not_called()
    if usable:
        assert result.diagnostic["snapshot_valid_until"] == (NOW - age + timedelta(days=1)).isoformat()
        result["123456"] = "99999999"
        assert store.load.return_value["codes"] == CODES


@pytest.mark.parametrize("changes", [
    {"retrieved_at": "invalid"}, {"retrieved_at": "2026-11-27T00:00:00"},
    {"source": "https://example.invalid"}, {"codes": {"123456": "bad"}}, {"codes": {}},
])
def test_invalid_persistent_data_is_not_a_fresh_cache(changes):
    store = Mock(load=Mock(return_value={**payload(), **changes}))
    assert snapshot.fresh_corporate_codes(now=NOW, store=store) is None


def test_store_outage_or_missing_store_returns_to_live_path(monkeypatch):
    snapshot.configure_corporate_store(Mock(load=Mock(side_effect=ValueError("store_unavailable"))))
    live = codes.CorporateCodeMap(CODES, diagnostic={"cause": "ok"})
    fetch = Mock(return_value=live)
    monkeypatch.setattr(codes, "fetch_corporate_codes", fetch)
    pair = prepare_directory("test", NOW, time.monotonic() + 24, Mock())
    assert pair[0] == CODES and pair[1]["mapping_attempts"] == 1
    fetch.assert_called_once()


def test_restart_reuses_list_and_preserves_original_expiry(monkeypatch):
    original = payload(NOW - timedelta(hours=23))
    snapshot.configure_corporate_store(Mock(load=Mock(return_value=original)))
    fetch = Mock(side_effect=AssertionError("fresh cache must not download ZIP"))
    monkeypatch.setattr(codes, "fetch_corporate_codes", fetch)
    first = prepare_directory("test", NOW, time.monotonic() + 24, Mock())
    sources.clear_cache()
    snapshot.configure_corporate_store(Mock(load=Mock(return_value=deepcopy(original))))
    restored = prepare_directory("test", NOW + timedelta(minutes=30), time.monotonic() + 24, Mock())
    assert first == restored and restored[1]["mapping_attempts"] == 0
    assert directory_cache_valid(restored, NOW + timedelta(minutes=59))
    assert not directory_cache_valid(restored, NOW + timedelta(hours=1))
    assert not directory_cache_valid(restored, NOW - timedelta(days=2))


def test_process_cache_does_not_extend_persistent_lifetime(monkeypatch):
    snapshot.configure_corporate_store(Mock(load=Mock(return_value=payload(NOW - timedelta(hours=23)))))
    fetch = Mock(return_value=codes.CorporateCodeMap(CODES, diagnostic={"cause": "ok"}))
    monkeypatch.setattr(codes, "fetch_corporate_codes", fetch)
    def load(now):
        return sources._cached(("test_directory",), now,
                               lambda: prepare_directory("test", now, time.monotonic() + 24, Mock()),
                               ttl=86400, valid=lambda pair: directory_cache_valid(pair, now))
    first, hit = load(NOW)
    assert not hit and first[1]["mapping_attempts"] == 0
    _, hit = load(NOW + timedelta(minutes=30))
    assert hit and fetch.call_count == 0
    renewed, hit = load(NOW + timedelta(hours=1))
    assert not hit and renewed[1]["mapping_attempts"] == 1 and fetch.call_count == 1


def test_cached_identity_does_not_hide_filing_auth_error(monkeypatch):
    snapshot.configure_corporate_store(Mock(load=Mock(return_value=payload())))
    monkeypatch.setattr(codes, "fetch_corporate_codes", Mock(side_effect=AssertionError("cache hit")))
    response = Mock(status_code=200)
    response.iter_content.return_value = [json.dumps({"status": "010", "message": "invalid key"}).encode()]
    get = Mock(return_value=response)
    result = sources.collect_filing_earnings(["123456.KS"], NOW, sec_user_agent="", dart_api_key="invalid", get=get)
    assert result["events"] == result["results"] == []
    source = result["sources"][0]
    assert source["reason"] == "dart_api_error" and source["mapping_source"] == "official_cache"
    get.assert_called_once()
    assert get.call_args.kwargs["params"]["crtfc_key"] == "invalid"


def test_cached_identity_is_not_described_as_live_failure():
    snapshot.configure_corporate_store(Mock(load=Mock(return_value=payload())))
    pair = prepare_directory("test", NOW, time.monotonic() + 24, Mock())
    row = {**pair[1], "ticker": "123456.KS", "checked_at": NOW.isoformat()}
    notice = " ".join(identity_notice_lines({"earnings_sources": [row]}))
    assert "1일 캐시" in notice and "실시간 기업코드 조회 실패" not in notice
    assert "기준일과 수집 주기는 변경하지 않았습니다" in notice
    assert "2026-11-28" in notice
