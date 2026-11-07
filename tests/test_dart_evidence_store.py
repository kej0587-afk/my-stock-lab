"""Real PostgREST request builder with an in-memory HTTP transport; no DB access."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket

import httpx
from postgrest import SyncPostgrestClient
import pytest

from stock_lab_core.dart_evidence import ENDPOINT, EvidenceError
from stock_lab_core.dart_evidence_store import EvidenceStoreError, SupabaseDartEvidenceStore, TABLE_NAME


NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
OWNER = "first@example.invalid"
MAP = {"005930": "00126380", "000660": "00164779"}
SCOPE = [{"year": "2026", "report_code": "11012"}]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("unexpected network"))


def bundle(at=NOW):
    return {"schema_version": 1, "collector_version": "1", "source": "dart", "endpoint": ENDPOINT,
            "ticker": "005930.KS", "corp_code": MAP["005930"], "collected_at": at.isoformat(),
            "requested_reports": deepcopy(SCOPE), "attempts": [{"year": "2026", "report_code": "11012",
                "fs_div": "CFS", "status": "success", "cause": "ok", "http_status": 200,
                "api_status": "000", "elapsed_seconds": 0.2, "retrieved_at": at.isoformat()}],
            "reports": [{"year": "2026", "report_code": "11012", "fs_div": "CFS", "retrieved_at": at.isoformat(),
                "rows": [{"rcept_no": "20260814000001", "corp_code": MAP["005930"], "bsns_year": "2026",
                          "reprt_code": "11012", "sj_div": "IS", "account_id": "ifrs-full_Revenue",
                          "account_nm": "매출액", "currency": "KRW", "thstrm_add_amount": "250,000"}]}]}


class MemoryTransport:
    def __init__(self):
        self.rows, self.calls = [], []
        self.error = None
        self.override = None

    def handle(self, request):
        assert request.url.path == "/" + TABLE_NAME
        assert request.method in {"GET", "POST"}  # No upsert/update/delete path.
        self.calls.append(request)
        if self.error:
            return httpx.Response(400, json={"code": self.error, "message": "PRIVATE_DB_DETAIL", "details": "SECRET", "hint": None})
        if self.override is not None:
            return httpx.Response(200, json=deepcopy(self.override))
        if request.method == "POST":
            row = json.loads(request.content)
            assert "imported_at" not in row
            assert "resolution=merge-duplicates" not in request.headers.get("prefer", "")
            key = lambda x: (x["owner_email"], x["ticker"], x["bundle_sha256"])
            if any(key(x) == key(row) for x in self.rows):
                return httpx.Response(409, json={"code": "23505", "message": "PRIVATE_DB_DETAIL", "details": None, "hint": None})
            row["imported_at"] = NOW.isoformat()
            self.rows.append(deepcopy(row))
            return httpx.Response(201, json=[row])
        params = request.url.params
        assert params.get("owner_email", "").startswith("eq.")
        assert params.get("ticker", "").startswith("eq.")
        assert params["limit"] == "1"
        rows = deepcopy(self.rows)
        for name, query in params.multi_items():
            if name in {"select", "order", "limit"}:
                continue
            op, value = query.split(".", 1)
            if op == "eq":
                rows = [r for r in rows if r[name] == value]
            else:
                bound = datetime.fromisoformat(value)
                rows = [r for r in rows if (datetime.fromisoformat(r[name]) >= bound if op == "gte"
                                           else datetime.fromisoformat(r[name]) <= bound)]
        rows.sort(key=lambda r: (r["collected_at"], r["imported_at"], r["bundle_sha256"]), reverse=True)
        return httpx.Response(200, json=rows[:1])


@pytest.fixture
def storage():
    memory = MemoryTransport()
    with httpx.Client(transport=httpx.MockTransport(memory.handle)) as http:
        client = SyncPostgrestClient("https://test.invalid", http_client=http)
        # Supabase's table entry point delegates to PostgREST's from_.
        client.table = client.from_
        yield SupabaseDartEvidenceStore(client, owner_scope=OWNER), memory, client


def save(store, payload=None, **kw):
    return store.insert_bundle(payload if payload is not None else bundle(), ticker="005930.KS",
                               owner_scope=kw.pop("owner_scope", OWNER), corporate_codes=kw.pop("codes", MAP),
                               now=kw.pop("now", NOW), **kw)


def load(store, **kw):
    return store.load_latest(kw.pop("ticker", "005930.KS"), requested_reports=kw.pop("scope", SCOPE),
                             owner_scope=kw.pop("owner_scope", OWNER), corporate_codes=kw.pop("codes", MAP),
                             now=kw.pop("now", NOW), **kw)


def test_idempotent_immutable_roundtrip_and_request_headers(storage):
    store, memory, _ = storage
    original = bundle()
    before = deepcopy(original)
    first = save(store, original)
    second = save(store, original)
    assert first["inserted"] and not second["inserted"] and len(memory.rows) == 1
    assert first["imported_at"] == second["imported_at"]
    assert original == before and load(store)["payload"] == original
    assert "return=representation" in memory.calls[0].headers["prefer"]
    assert memory.calls[2].url.params["bundle_sha256"] == "eq." + first["summary"]["sha256"]
    first["payload"]["reports"].clear()
    assert load(store)["payload"]["reports"]  # Caller cannot mutate durable evidence.


def test_owner_isolation_and_return_validation(storage):
    store, memory, client = storage
    save(store)
    other = SupabaseDartEvidenceStore(client, owner_scope="second@example.invalid")
    assert load(other, owner_scope="second@example.invalid") is None
    save(other, owner_scope="second@example.invalid")
    assert len(memory.rows) == 2
    count = len(memory.calls)
    with pytest.raises(EvidenceStoreError, match="owner_scope_mismatch"):
        load(store, owner_scope="second@example.invalid")
    with pytest.raises(EvidenceStoreError, match="owner_scope_mismatch"):
        save(store, owner_scope="second@example.invalid")
    assert len(memory.calls) == count
    memory.override = [memory.rows[1]]
    with pytest.raises(EvidenceStoreError, match="owner_scope_mismatch"):
        load(store)


def test_corrected_filing_is_a_new_bundle(storage):
    store, memory, _ = storage
    save(store)
    revised = bundle(NOW + timedelta(minutes=1))
    revised["reports"][0]["rows"][0]["rcept_no"] = "20261107000001"
    save(store, revised, now=NOW + timedelta(minutes=1))
    assert len(memory.rows) == 2
    assert load(store, now=NOW + timedelta(minutes=1))["payload"] == revised


def test_scope_and_ticker_must_match(storage):
    store, memory, _ = storage
    save(store)
    assert load(store, ticker="000660.KS") is None
    assert load(store, scope=[{"year": "2025", "report_code": "11011"}]) is None
    memory.override = [memory.rows[0]]
    with pytest.raises(EvidenceStoreError, match="scope_mismatch"):
        load(store, scope=[{"year": "2025", "report_code": "11011"}])
    with pytest.raises(EvidenceStoreError, match="ticker_mismatch"):
        load(store, ticker="000660.KS")


@pytest.mark.parametrize("kind", ["partial", "expired", "future", "empty", "missing_map", "wrong_map", "owner_in_file"])
def test_bad_evidence_never_replaces_good_row(storage, kind):
    store, memory, _ = storage
    save(store)
    old = deepcopy(memory.rows)
    bad, codes = bundle(), MAP
    if kind == "partial":
        bad["reports"] = []
        bad["attempts"][0].update(status="failed", cause="transport_error", http_status=None, api_status=None)
    elif kind == "expired":
        bad = bundle(NOW - timedelta(days=8))
    elif kind == "future":
        bad = bundle(NOW + timedelta(minutes=6))
    elif kind == "empty":
        bad["reports"] = []
        bad["attempts"][0].update(status="no_data", cause="no_data", api_status="013")
        bad["attempts"].append({**bad["attempts"][0], "fs_div": "OFS"})
    elif kind == "missing_map":
        codes = None
    elif kind == "wrong_map":
        codes = {"005930": "99999999"}
    else:
        bad["owner_email"] = "second@example.invalid"
    count = len(memory.calls)
    with pytest.raises((EvidenceStoreError, EvidenceError)):
        save(store, bad, codes=codes)
    assert len(memory.calls) == count and memory.rows == old


def test_age_is_not_reset_by_import_and_empty_is_not_error(storage):
    store, memory, _ = storage
    assert load(store) is None
    save(store, bundle(NOW - timedelta(days=2)))
    assert load(store)["summary"]["freshness"] == "stale"
    assert load(store, now=NOW + timedelta(days=6)) is None
    assert len(memory.rows) == 1  # Expiry is selection, not deletion.


@pytest.mark.parametrize("code,expected", [("42P01", "schema_unavailable"), ("PGRST205", "schema_unavailable"),
                                            ("42501", "store_unavailable"), ("08006", "store_unavailable")])
def test_database_failures_are_not_empty_success_or_private_error_text(storage, code, expected):
    store, memory, _ = storage
    memory.error = code
    for operation in (save, load):
        with pytest.raises(EvidenceStoreError, match=expected) as caught:
            operation(store)
        assert "PRIVATE" not in str(caught.value) and "SECRET" not in str(caught.value)


@pytest.mark.parametrize("field,value", [("bundle_sha256", "0" * 64), ("scope_sha256", "0" * 64),
                                        ("corp_code", "99999999"), ("collected_at", "2026-01-01T00:00:00+00:00"),
                                        ("imported_at", "invalid")])
def test_returned_metadata_cannot_disagree_with_payload(storage, field, value):
    store, memory, _ = storage
    save(store)
    memory.override = deepcopy(memory.rows)
    memory.override[0][field] = value
    with pytest.raises(EvidenceStoreError):
        load(store)


def test_unconfirmed_write_is_not_reported_as_saved(storage):
    store, memory, _ = storage
    memory.override = []
    with pytest.raises(EvidenceStoreError, match="write_unconfirmed"):
        save(store)


def test_duplicate_verification_failure_is_not_success(storage):
    store, memory, _ = storage
    memory.error = "23505"
    with pytest.raises(EvidenceStoreError, match="store_unavailable"):
        save(store)  # Duplicate verification itself fails; never claim success.


def test_corrupt_partial_stored_payload_is_not_exposed(storage):
    store, memory, _ = storage
    save(store)
    memory.override = deepcopy(memory.rows)
    payload = memory.override[0]["payload"]
    payload["reports"] = []
    payload["attempts"][0].update(status="failed", cause="transport_error", http_status=None, api_status=None)
    with pytest.raises(EvidenceStoreError, match="evidence_not_eligible"):
        load(store)


def test_scope_hash_is_order_independent():
    from stock_lab_core.dart_evidence_store import _scope_hash
    scope = SCOPE + [{"year": "2025", "report_code": "11011"}]
    assert _scope_hash(scope, NOW) == _scope_hash(list(reversed(scope)), NOW)


def test_prepared_sql_is_insert_only_and_has_isolation_guards():
    sql = Path("docs/20261107_dart_evidence.sql").read_text(encoding="utf-8")
    assert "grant select, insert on" in sql
    assert "grant select, insert, update" not in sql
    assert "primary key (owner_email, ticker, bundle_sha256)" in sql
    assert "enable row level security" in sql and "force row level security" in sql
    assert "using (false) with check (false)" in sql
    assert "create table public.financial_evidence_bundles" in sql
    assert "create table if not exists" not in sql.lower().split("begin;")[1]
