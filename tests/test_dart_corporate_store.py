"""DART identity list: save on live success, restore last good list on transport failure.

Synthetic identifiers only. No credentials, network or real database.
"""

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

from stock_lab_core import dart_corporate_snapshot as snap
from stock_lab_core.dart_corporate_codes import CorporateCodeMap
from stock_lab_core.dart_corporate_store import (
    SupabaseCorporateCodeStore, CorporateStoreError, TABLE_NAME, codes_digest,
)

NOW = datetime(2026, 11, 24, 2, 0, tzinfo=timezone.utc)
CODES = {f"{n:06d}": f"{n + 10000000:08d}" for n in range(100000, 100050)}


class _Query:
    def __init__(self, table, op, row=None):
        self.table, self.op, self.row, self.filters = table, op, row, {}

    def select(self, columns):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, n):
        return self

    def execute(self):
        client = self.table.client
        if client.fail:
            raise client.fail
        if self.op == "upsert":
            client.rows[self.row["source"]] = dict(self.row)
            client.writes += 1
            return Mock(data=[dict(self.row)])
        row = client.rows.get(self.filters.get("source"))
        return Mock(data=[dict(row)] if row else [])


class _Table:
    def __init__(self, client):
        self.client = client

    def select(self, columns):
        return _Query(self, "select").select(columns)

    def upsert(self, row, on_conflict=None):
        assert on_conflict == "source"
        return _Query(self, "upsert", row)


class FakeClient:
    def __init__(self):
        self.rows, self.writes, self.fail = {}, 0, None

    def table(self, name):
        assert name == TABLE_NAME
        return _Table(self)


def bundled(tmp_path, *, retrieved_at, codes=None):
    path = tmp_path / "codes.json"
    path.write_text(json.dumps({"version": 1, "source": snap.SOURCE, "retrieved_at": retrieved_at.isoformat(),
                                "codes": codes or {"100000": "11000000"}}), encoding="utf-8")
    return path


def stored(client, *, retrieved_at, codes=CODES):
    store = SupabaseCorporateCodeStore(client)
    store.save({"version": 1, "source": snap.SOURCE, "retrieved_at": retrieved_at.isoformat(), "codes": dict(codes)})
    client.writes = 0
    return store


def live_ok(codes=CODES):
    return CorporateCodeMap(codes, diagnostic={"cause": "ok", "mapped_count": len(codes)})


def timeout():
    return CorporateCodeMap(diagnostic={"cause": "connect_timeout", "elapsed_seconds": 5.0})


@pytest.fixture(autouse=True)
def no_global_store():
    snap.configure_corporate_store(None)
    yield
    snap.configure_corporate_store(None)


# 1. Normal live success -------------------------------------------------------

def test_live_success_is_returned_unchanged_and_saved_after_validation(tmp_path):
    client = FakeClient()
    store = SupabaseCorporateCodeStore(client)
    live = live_ok()
    result = snap.use_corporate_snapshot(live, path=tmp_path / "absent.json", now=NOW, store=store)
    assert result is live and dict(result) == CODES
    assert live.diagnostic["persist_status"] == "saved" and "mapping_source" not in live.diagnostic
    row = client.rows[snap.SOURCE]
    assert row["mapped_count"] == len(CODES) and row["codes_sha256"] == codes_digest(CODES)
    assert row["retrieved_at"] == NOW.isoformat()


def test_identical_recent_list_is_not_rewritten_but_changed_or_old_list_is(tmp_path):
    client = FakeClient()
    store = stored(client, retrieved_at=NOW - timedelta(hours=1))
    assert snap.remember_corporate_codes(live_ok(), store=store, now=NOW) == "unchanged_recent"
    assert client.writes == 0
    assert snap.remember_corporate_codes(live_ok(), store=store, now=NOW + timedelta(hours=12)) == "saved"
    changed = {**CODES, "100099": "11100099"}
    assert snap.remember_corporate_codes(live_ok(changed), store=store, now=NOW + timedelta(hours=13)) == "saved"
    assert client.rows[snap.SOURCE]["mapped_count"] == len(changed)


@pytest.mark.parametrize("codes,status", [
    ({k: v for k, v in list(CODES.items())[:40]}, "rejected_shrunk"),   # 80% of last good list
    ({"100000": "BAD"}, "rejected_invalid"),
])
def test_suspicious_live_list_never_overwrites_last_good_list(codes, status):
    client = FakeClient()
    store = stored(client, retrieved_at=NOW - timedelta(days=1))
    live = live_ok(codes)
    assert snap.use_corporate_snapshot(live, now=NOW, store=store) is live  # live result itself is untouched
    assert live.diagnostic["persist_status"] == status
    assert client.writes == 0 and client.rows[snap.SOURCE]["codes"] == CODES


def test_store_outage_never_breaks_live_success():
    client = FakeClient()
    client.fail = type("APIError", (Exception,), {"code": "PGRST205"})("private detail")
    live = live_ok()
    assert snap.use_corporate_snapshot(live, now=NOW, store=SupabaseCorporateCodeStore(client)) is live
    assert live.diagnostic["persist_status"] == "schema_unavailable"
    assert "private" not in json.dumps(live.diagnostic)


# 2. Connection failure --------------------------------------------------------

def test_reproduces_nov21_case_expired_bundled_list_and_no_store(tmp_path):
    path = bundled(tmp_path, retrieved_at=datetime(2026, 11, 7, 8, 7, tzinfo=timezone.utc))
    result = snap.use_corporate_snapshot(timeout(), path=path, now=datetime(2026, 11, 21, 11, tzinfo=timezone.utc))
    assert not result
    assert result.diagnostic["snapshot_status"] == "unavailable_or_expired"
    assert result.diagnostic["snapshot_candidates"] == {"bundled_file": "expired"}
    assert "7일 이내 보관 목록 없음" in snap.snapshot_notice(result.diagnostic)


@pytest.mark.parametrize("cause", ["missing_key", "api_error", "http_error", "invalid_zip_xml", "empty_mapping"])
def test_auth_and_provider_errors_are_still_not_hidden_by_stored_list(cause):
    client = FakeClient()
    store = stored(client, retrieved_at=NOW - timedelta(hours=2))
    live = CorporateCodeMap(diagnostic={"cause": cause, "api_status": "020"})
    assert snap.use_corporate_snapshot(live, now=NOW, store=store) is live


# 3. Restore last good list ----------------------------------------------------

def test_transport_failure_restores_persistent_last_success_with_date_and_freshness(tmp_path):
    client = FakeClient()
    store = stored(client, retrieved_at=NOW - timedelta(days=2, hours=1))
    path = bundled(tmp_path, retrieved_at=NOW - timedelta(days=17))  # bundled list already expired
    result = snap.use_corporate_snapshot(timeout(), path=path, now=NOW, store=store)
    assert dict(result) == CODES
    d = result.diagnostic
    assert d["cause"] == "connect_timeout" and d["mapping_source"] == "official_snapshot"
    assert d["snapshot_origin"] == "persistent_last_success" and d["snapshot_age_days"] == 2
    assert d["snapshot_candidates"] == {"persistent_last_success": "valid", "bundled_file": "expired"}
    assert d["snapshot_valid_until"] == (NOW - timedelta(days=2, hours=1) + snap.MAX_AGE).isoformat()
    notice = snap.snapshot_notice(d)
    assert "마지막 정상 조회 목록" in notice and "2일 경과" in notice and "재무제표·공시의 최신성과는 별개" in notice


def test_newest_valid_origin_wins_and_seven_day_limit_is_unchanged(tmp_path):
    client = FakeClient()
    store = stored(client, retrieved_at=NOW - timedelta(days=8))  # expired
    path = bundled(tmp_path, retrieved_at=NOW - timedelta(days=3))
    result = snap.use_corporate_snapshot(timeout(), path=path, now=NOW, store=store)
    assert result.diagnostic["snapshot_origin"] == "bundled_file"
    assert result.diagnostic["snapshot_candidates"]["persistent_last_success"] == "expired"
    both_old = snap.use_corporate_snapshot(timeout(), path=bundled(tmp_path, retrieved_at=NOW - timedelta(days=9)),
                                           now=NOW, store=store)
    assert not both_old and both_old.diagnostic["snapshot_status"] == "unavailable_or_expired"


def test_tampered_or_unreachable_store_row_is_not_used(tmp_path):
    client = FakeClient()
    stored(client, retrieved_at=NOW - timedelta(days=1))
    client.rows[snap.SOURCE]["codes"]["100000"] = "99999999"   # digest no longer matches
    store = SupabaseCorporateCodeStore(client)
    with pytest.raises(CorporateStoreError):
        store.load(snap.SOURCE)
    result = snap.use_corporate_snapshot(timeout(), path=tmp_path / "absent.json", now=NOW, store=store)
    assert not result and result.diagnostic["snapshot_candidates"] == {
        "persistent_last_success": "unavailable", "bundled_file": "unavailable"}
    client.fail = RuntimeError("down")
    down = snap.use_corporate_snapshot(timeout(), path=tmp_path / "absent.json", now=NOW, store=store)
    assert down.diagnostic["snapshot_candidates"]["persistent_last_success"] == "unavailable"


def test_saved_list_survives_restart_through_store_not_process_memory(tmp_path):
    client = FakeClient()  # stands in for the database that outlives the app process
    snap.configure_corporate_store(SupabaseCorporateCodeStore(client))
    snap.use_corporate_snapshot(live_ok(), path=tmp_path / "absent.json", now=NOW)
    snap.configure_corporate_store(SupabaseCorporateCodeStore(client))  # "rebooted" app, new store object
    result = snap.use_corporate_snapshot(timeout(), path=tmp_path / "absent.json", now=NOW + timedelta(hours=6))
    assert dict(result) == CODES and result.diagnostic["snapshot_origin"] == "persistent_last_success"


# 4. New issuer not in the saved list --------------------------------------------

def test_new_issuer_missing_from_saved_list_is_explicit_not_guessed(monkeypatch):
    from stock_lab_core import dart_corporate_codes, earnings_filing_sources as sources
    from stock_lab_core.earnings_pipeline import _source_reason
    sources.clear_cache()
    client = FakeClient()
    snap.configure_corporate_store(stored(client, retrieved_at=datetime(2026, 11, 19, 23, tzinfo=timezone.utc)))
    monkeypatch.setattr(dart_corporate_codes, "fetch_corporate_codes", Mock(return_value=timeout()))
    get = Mock()
    now = datetime.fromisoformat("2026-11-20T08:00:00+09:00")
    collected = sources.collect_filing_earnings(["0099A0.KS"], now, sec_user_agent="", dart_api_key="test", get=get)
    source = collected["sources"][0]
    assert collected["events"] == [] and source["reason"] == "dart_ticker_mapping_unavailable_in_snapshot"
    assert source["mapping_source"] == "official_snapshot" and source["snapshot_origin"] == "persistent_last_success"
    get.assert_not_called()  # no filing request is made under a guessed corporate code
    reason = _source_reason("0099A0.KS", dict(earnings_sources=[source]))
    assert "미등록" in reason and "신규 상장" in reason
    sources.clear_cache()


def test_report_states_dated_identity_list_only_when_used():
    from stock_lab_core.report_dart_earnings import identity_notice_lines
    row = dict(ticker="123456.KS", checked_at="2026-11-24T11:00:00+09:00", mapping_source="official_snapshot",
               snapshot_origin="persistent_last_success", snapshot_asof="2026-11-22T00:00:00+00:00",
               snapshot_valid_until="2026-11-29T00:00:00+00:00")
    lines = identity_notice_lines(dict(earnings_sources=[row]))
    assert "마지막 정상 조회 목록" in lines[1] and "2026-11-22 00:00" in lines[1] and "2일 경과" in lines[1]
    assert identity_notice_lines(dict(earnings_sources=[dict(ticker="123456.KS", status="connected")])) == []
