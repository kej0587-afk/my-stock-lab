"""Owner isolation and optimistic writes, entirely offline with synthetic drafts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_lab_core.account_performance_io import MAX_BYTES, MAX_ROWS, empty_ledger, encode_ledger
from stock_lab_core.account_performance_store import (
    AccountPerformanceStoreError, SupabaseAccountPerformanceStore, TABLE_NAME,
)


ALICE = "alice@example.test"
BOB = "bob@example.test"
STAMP = "2026-11-01T00:00:00+00:00"
MAX_REVISION = 2**63 - 1
UNSET = object()


class DatabaseFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("DO_NOT_EXPOSE_TOKEN_OR_OWNER database detail")


class FakeClient:
    def __init__(self):
        self.database = {}
        self.calls = []
        self.error = None
        self.response = UNSET
        self.response_transform = None
        self.mutate_input = False
        self.barrier = None
        self.lock = Lock()

    def table(self, name):
        assert name == TABLE_NAME
        self.calls.append(("table", name))
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, client):
        self.client = client
        self.filters = {}

    def select(self, columns):
        assert set(columns.split(",")) == {"owner_email", "revision", "payload", "updated_at"}
        self.operation = "select"
        return self

    def eq(self, name, value):
        self.filters[name] = value
        return self

    def limit(self, count):
        self.count = count
        return self

    def insert(self, row):
        assert row["revision"] == 1 and row["owner_email"]
        self.operation, self.row = "insert", row
        return self

    def update(self, row):
        assert "owner_email" not in row
        assert datetime.fromisoformat(row["updated_at"]).utcoffset() is not None
        self.operation, self.row = "update", row
        return self

    def upsert(self, *args, **kwargs):
        pytest.fail("upsert is forbidden")

    def delete(self, *args, **kwargs):
        pytest.fail("delete is forbidden")

    def execute(self):
        client = self.client
        with client.lock:
            client.calls.append((self.operation, deepcopy(self.filters),
                                 deepcopy(getattr(self, "row", None))))
        if self.operation == "select":
            assert self.filters.keys() == {"owner_email"}
            assert self.count <= 2
        elif self.operation == "update":
            assert self.filters.keys() == {"owner_email", "revision"}
            assert self.row["revision"] == self.filters["revision"] + 1
        else:
            assert not self.filters
        if client.error is not None:
            raise client.error
        if client.response is not UNSET:
            return client.response
        if self.operation != "select" and client.barrier is not None:
            client.barrier.wait(timeout=10)
        with client.lock:
            if self.operation == "select":
                rows = [row for row in client.database.values()
                        if row["owner_email"] == self.filters["owner_email"]]
                return SimpleNamespace(data=deepcopy(rows[:self.count]))
            if client.mutate_input:
                self.row["payload"]["flows"][0]["amount"] = 999.
            if self.operation == "insert":
                owner = self.row["owner_email"]
                if owner in client.database:
                    raise DatabaseFailure("23505")
                row = dict(deepcopy(self.row), updated_at=STAMP)
                client.database[owner] = row
                rows = [row]
            else:
                row = client.database.get(self.filters["owner_email"])
                if row is None or row["revision"] != self.filters["revision"]:
                    rows = []
                else:
                    row.update(deepcopy(self.row))
                    rows = [row]
            rows = deepcopy(rows)
        if client.response_transform:
            client.response_transform(rows)
        return SimpleNamespace(data=rows)


def ledger():
    return {
        "valuations": pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-11-01"]),
                                    "account": ["0007", "0007"], "value_krw": [100., 150.]}),
        "flows": pd.DataFrame({"id": ["0001"], "date": pd.to_datetime(["2026-10-31"]),
                              "account": ["0007"], "amount": [25.], "currency": ["KRW"],
                              "fx_rate": [None]}),
    }


def row():
    return {"owner_email": ALICE, "revision": 1, "payload": json.loads(encode_ledger(ledger())),
            "updated_at": STAMP}


def store(client, owner=ALICE):
    return SupabaseAccountPerformanceStore(client, owner_scope=owner)


def assert_code(expected, action):
    with pytest.raises(AccountPerformanceStoreError) as caught:
        action()
    assert caught.value.code == expected
    assert str(caught.value) == expected
    assert caught.value.args == (expected,)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ or caught.value.__context__ is None


def assert_ledger_equal(actual, expected):
    for name in ("valuations", "flows"):
        pd.testing.assert_frame_equal(actual[name], expected[name])


def test_constructor_is_lazy_and_module_registers_loaded_source():
    from stock_lab_core import account_performance_store, report_build

    client = FakeClient()
    store(client)
    assert not client.calls
    loaded = report_build._LOADED[account_performance_store.__name__]
    assert loaded["path"] == str(Path(account_performance_store.__file__).resolve())
    assert len(loaded["sha256"]) == 64


def test_owner_isolation_normalization_and_insert_load_update_roundtrip():
    client = FakeClient()
    alice = store(client, " Alice@Example.Test ")
    bob = store(client, BOB)
    assert alice.load(owner_scope=ALICE) is None
    saved = alice.save(ledger(), expected_revision=None, owner_scope=" ALICE@EXAMPLE.TEST ")
    assert saved["revision"] == 1 and saved["updated_at"] == STAMP
    assert set(saved) == {"revision", "ledger", "updated_at"}
    assert saved["ledger"]["flows"].iloc[0]["id"] == "0001"
    assert saved["ledger"]["valuations"].iloc[0]["account"] == "0007"
    assert all(pd.api.types.is_datetime64_any_dtype(frame["date"]) for frame in saved["ledger"].values())
    assert bob.load(owner_scope=BOB) is None
    bob.save(empty_ledger(), expected_revision=None, owner_scope=BOB)
    bob_before = deepcopy(client.database[BOB])
    changed = ledger()
    changed["flows"].loc[0, "amount"] = 35.
    updated = alice.save(changed, expected_revision=1, owner_scope=ALICE)
    assert updated["revision"] == 2
    assert datetime.fromisoformat(updated["updated_at"]).tzinfo == timezone.utc
    assert_ledger_equal(alice.load(owner_scope=ALICE)["ledger"], updated["ledger"])
    assert client.database[BOB] == bob_before
    assert set(client.database) == {ALICE, BOB}
    assert {call[0] for call in client.calls} == {"table", "select", "insert", "update"}


@pytest.mark.parametrize("bound,requested", [(ALICE, BOB), (ALICE, ""), (ALICE, None),
                                            ("", ""), (None, None), (False, False), (123, "123")])
def test_untrusted_or_mismatched_owner_never_queries(bound, requested):
    client = FakeClient()
    backend = store(client, bound)
    assert_code("owner_scope_mismatch", lambda: backend.load(owner_scope=requested))
    assert_code("owner_scope_mismatch",
                lambda: backend.save(ledger(), expected_revision=None, owner_scope=requested))
    assert not client.calls


def test_two_sessions_compare_and_swap_without_overwriting_stale_draft():
    client = FakeClient()
    first, second = store(client), store(client)
    first.save(ledger(), expected_revision=None, owner_scope=ALICE)
    a = first.load(owner_scope=ALICE)
    b = second.load(owner_scope=ALICE)
    a["ledger"]["flows"].loc[0, "amount"] = 40.
    b["ledger"]["flows"].loc[0, "amount"] = 50.
    first.save(a["ledger"], expected_revision=a["revision"], owner_scope=ALICE)
    before = deepcopy(client.database)
    assert_code("conflict", lambda: second.save(b["ledger"], expected_revision=b["revision"], owner_scope=ALICE))
    assert client.database == before
    assert b["ledger"]["flows"].loc[0, "amount"] == 50.
    refreshed = second.load(owner_scope=ALICE)
    assert refreshed["revision"] == 2
    assert refreshed["ledger"]["flows"].loc[0, "amount"] == 40.
    assert second.save(b["ledger"], expected_revision=2, owner_scope=ALICE)["revision"] == 3


@pytest.mark.parametrize("existing", [False, True])
def test_concurrent_first_create_and_update_have_exactly_one_winner(existing):
    client = FakeClient()
    if existing:
        store(client).save(ledger(), expected_revision=None, owner_scope=ALICE)
    client.barrier = Barrier(2)

    def attempt(amount):
        draft = ledger()
        draft["flows"].loc[0, "amount"] = amount
        try:
            return store(client).save(draft, expected_revision=1 if existing else None,
                                      owner_scope=ALICE)
        except AccountPerformanceStoreError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, [31., 42.]))
    assert outcomes.count("conflict") == 1
    winner = next(outcome for outcome in outcomes if isinstance(outcome, dict))
    assert winner["revision"] == (2 if existing else 1)
    assert len(client.database) == 1
    assert client.database[ALICE]["payload"]["flows"][0]["amount"] == winner["ledger"]["flows"].iloc[0]["amount"]


def test_first_insert_collision_and_update_of_absent_row_are_conflicts():
    client = FakeClient()
    backend = store(client)
    assert_code("conflict", lambda: backend.save(ledger(), expected_revision=1, owner_scope=ALICE))
    assert not client.database
    backend.save(ledger(), expected_revision=None, owner_scope=ALICE)
    before = deepcopy(client.database)
    assert_code("conflict", lambda: backend.save(empty_ledger(), expected_revision=None, owner_scope=ALICE))
    assert client.database == before


@pytest.mark.parametrize("revision", [True, False, 0, -1, 1., "1", MAX_REVISION, MAX_REVISION + 1, 10**1000])
def test_invalid_expected_revision_is_rejected_before_queries(revision):
    client = FakeClient()
    assert_code("invalid_data", lambda: store(client).save(ledger(), expected_revision=revision, owner_scope=ALICE))
    assert not client.calls


def test_bigint_last_increment_is_safe_but_overflow_is_rejected():
    client = FakeClient()
    client.database[ALICE] = dict(row(), revision=MAX_REVISION - 1)
    backend = store(client)
    saved = backend.save(ledger(), expected_revision=MAX_REVISION - 1, owner_scope=ALICE)
    assert saved["revision"] == backend.load(owner_scope=ALICE)["revision"] == MAX_REVISION
    calls = len(client.calls)
    assert_code("invalid_data", lambda: backend.save(ledger(), expected_revision=MAX_REVISION, owner_scope=ALICE))
    assert len(client.calls) == calls


@pytest.mark.parametrize("operation", ["load", "insert", "update"])
@pytest.mark.parametrize("code,expected", [("42P01", "schema_unavailable"), ("PGRST204", "schema_unavailable"),
                                         ("PGRST205", "schema_unavailable"), ("3F000", "schema_unavailable"),
                                         ("42703", "schema_unavailable"), ("PGRST106", "schema_unavailable"),
                                         ("42501", "store_unavailable"), ("08006", "store_unavailable"),
                                         (None, "store_unavailable")])
def test_backend_errors_are_fixed_codes_without_raw_details(operation, code, expected, capsys, caplog):
    client = FakeClient()
    client.error = DatabaseFailure(code) if code else OSError("DO_NOT_EXPOSE_TOKEN_OR_OWNER")
    backend = store(client)
    action = (lambda: backend.load(owner_scope=ALICE)) if operation == "load" else (
        lambda: backend.save(ledger(), expected_revision=None if operation == "insert" else 1, owner_scope=ALICE))
    assert_code(expected, action)
    captured = capsys.readouterr()
    assert "DO_NOT_EXPOSE" not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize("column,value", [
    ("date", "2026/10/01"), ("date", "2026-10-01T00:00:00Z"), ("date", date(9999, 12, 31)),
    ("date", True), ("value_krw", True), ("value_krw", "100"), ("value_krw", float("inf")),
    ("value_krw", 10**1000), ("value_krw", {"nested": 1}), ("account", 7),
])
def test_invalid_draft_shapes_are_rejected_without_mutation_or_queries(column, value):
    client = FakeClient()
    draft = ledger()
    draft["valuations"][column] = draft["valuations"][column].astype(object)
    draft["valuations"].at[0, column] = value
    before = deepcopy(draft)
    assert_code("invalid_data", lambda: store(client).save(draft, expected_revision=None, owner_scope=ALICE))
    assert_ledger_equal(draft, before)
    assert not client.calls


@pytest.mark.parametrize("column,value", [("id", 1), ("amount", False), ("fx_rate", "1.0"),
                                         ("amount", float("-inf")), ("currency", []),
                                         ("date", pd.Timestamp("2026-10-01T12:00:00"))])
def test_invalid_flow_cells_are_rejected_before_queries(column, value):
    client = FakeClient()
    draft = ledger()
    draft["flows"][column] = draft["flows"][column].astype(object)
    draft["flows"].at[0, column] = value
    assert_code("invalid_data", lambda: store(client).save(draft, expected_revision=None, owner_scope=ALICE))
    assert not client.calls


@pytest.mark.parametrize("draft", [None, {}, {"valuations": [], "flows": []},
                                   {"valuations": pd.DataFrame(), "flows": pd.DataFrame()}])
def test_invalid_ledger_container_is_rejected(draft):
    client = FakeClient()
    assert_code("invalid_data", lambda: store(client).save(draft, expected_revision=None, owner_scope=ALICE))
    assert not client.calls


@pytest.mark.parametrize("table", ["valuations", "flows"])
@pytest.mark.parametrize("oversize", ["rows", "bytes"])
def test_oversize_drafts_are_rejected_before_queries(table, oversize):
    client = FakeClient()
    draft = ledger()
    if oversize == "rows":
        draft[table] = pd.concat([draft[table].iloc[:1]] * (MAX_ROWS + 1), ignore_index=True)
    else:
        draft[table].loc[0, "account"] = "x" * (MAX_BYTES + 1)
    assert_code("invalid_data", lambda: store(client).save(draft, expected_revision=None, owner_scope=ALICE))
    assert not client.calls


@pytest.mark.parametrize("partial", [False, True])
def test_empty_and_partial_drafts_are_allowed_without_financial_validation(partial):
    client = FakeClient()
    draft = empty_ledger()
    if partial:
        draft = ledger()
        draft["valuations"].loc[0, "value_krw"] = float("nan")
        draft["flows"].loc[0, "date"] = pd.NaT
        draft["flows"].loc[0, "currency"] = None
        draft["flows"] = pd.concat([draft["flows"], draft["flows"]], ignore_index=True)
    result = store(client).save(draft, expected_revision=None, owner_scope=ALICE)
    assert result["revision"] == 1
    assert "flows_complete" not in result
    assert "flows_complete" not in client.database[ALICE]["payload"]
    if partial:
        assert pd.isna(result["ledger"]["valuations"].loc[0, "value_krw"])
        assert pd.isna(result["ledger"]["flows"].loc[0, "date"])
        assert list(result["ledger"]["flows"]["id"]) == ["0001", "0001"]
    else:
        assert all(frame.empty for frame in result["ledger"].values())


@pytest.mark.parametrize("response", [None, SimpleNamespace(), SimpleNamespace(data=None),
                                      SimpleNamespace(data={}), SimpleNamespace(data=[row(), row()]),
                                      SimpleNamespace(data=[None])])
def test_malformed_read_response_is_invalid_data(response):
    client = FakeClient()
    client.response = response
    assert_code("invalid_data", lambda: store(client).load(owner_scope=ALICE))


@pytest.mark.parametrize("change", [
    lambda r: r.update(revision=True), lambda r: r.update(revision=0), lambda r: r.update(revision=1.),
    lambda r: r.update(revision=MAX_REVISION + 1), lambda r: r.pop("revision"),
    lambda r: r.update(updated_at=None), lambda r: r.update(updated_at="bad"),
    lambda r: r.update(updated_at="2026-11-01T00:00:00"), lambda r: r.update(payload="{}"),
    lambda r: r["payload"].update(version=True), lambda r: r["payload"].update(version=2),
    lambda r: r["payload"].update(currency_basis="USD"), lambda r: r["payload"].update(flow_timing="begin_of_day"),
    lambda r: r["payload"].update(valuations={}),
    lambda r: r["payload"]["flows"][0].update(amount=True),
    lambda r: r["payload"]["flows"][0].update(amount=float("nan")),
    lambda r: r["payload"]["flows"][0].update(amount=10**1000),
    lambda r: r["payload"]["flows"][0].update(id=1),
    lambda r: r["payload"]["flows"][0].update(date="9999-12-31"),
    lambda r: r["payload"]["flows"][0].update(extra=1),
    lambda r: r["payload"]["valuations"][0].update(account="x" * (MAX_BYTES + 1)),
    lambda r: r["payload"].update(flows=r["payload"]["flows"] * (MAX_ROWS + 1)),
])
def test_load_validates_revision_schema_timestamp_and_bounded_portable_payload(change):
    client = FakeClient()
    returned = row()
    change(returned)
    before = deepcopy(returned)
    client.response = SimpleNamespace(data=[returned])
    assert_code("invalid_data", lambda: store(client).load(owner_scope=ALICE))
    assert returned == before


@pytest.mark.parametrize("operation", ["load", "insert", "update"])
def test_returned_owner_must_match_bound_owner(operation):
    client = FakeClient()
    client.response = SimpleNamespace(data=[dict(row(), owner_email=BOB)])
    backend = store(client)
    action = (lambda: backend.load(owner_scope=ALICE)) if operation == "load" else (
        lambda: backend.save(ledger(), expected_revision=None if operation == "insert" else 1, owner_scope=ALICE))
    assert_code("owner_scope_mismatch", action)


@pytest.mark.parametrize("expected_revision", [None, 1])
@pytest.mark.parametrize("response", [None, SimpleNamespace(), SimpleNamespace(data=None),
                                      SimpleNamespace(data={}), SimpleNamespace(data=[row(), row()])])
def test_absent_or_ambiguous_write_response_is_unconfirmed(expected_revision, response):
    client = FakeClient()
    client.response = response
    assert_code("write_unconfirmed", lambda: store(client).save(
        ledger(), expected_revision=expected_revision, owner_scope=ALICE))


def test_empty_insert_response_is_unconfirmed_but_empty_update_is_conflict():
    client = FakeClient()
    client.response = SimpleNamespace(data=[])
    backend = store(client)
    assert_code("write_unconfirmed", lambda: backend.save(ledger(), expected_revision=None, owner_scope=ALICE))
    assert_code("conflict", lambda: backend.save(ledger(), expected_revision=1, owner_scope=ALICE))


@pytest.mark.parametrize("expected_revision", [None, 1])
@pytest.mark.parametrize("change", [lambda r: r.update(revision=99),
                                    lambda r: r["payload"]["flows"][0].update(amount=999.)])
def test_different_returned_revision_or_payload_is_unconfirmed(expected_revision, change):
    client = FakeClient()
    if expected_revision:
        client.database[ALICE] = row()
    client.response_transform = lambda rows: change(rows[0])
    assert_code("write_unconfirmed", lambda: store(client).save(
        ledger(), expected_revision=expected_revision, owner_scope=ALICE))


def test_write_confirmation_compares_normalized_payload_not_raw_json_order_or_numeric_types():
    client = FakeClient()

    def normalize(rows):
        payload = rows[0]["payload"]
        payload["flows"][0]["amount"] = 25
        rows[0]["payload"] = dict(reversed(list(payload.items())))

    client.response_transform = normalize
    assert store(client).save(ledger(), expected_revision=None, owner_scope=ALICE)["revision"] == 1


def test_client_mutation_cannot_change_candidate_used_for_confirmation():
    client = FakeClient()
    client.mutate_input = True
    source = ledger()
    before = deepcopy(source)
    assert_code("write_unconfirmed", lambda: store(client).save(source, expected_revision=None, owner_scope=ALICE))
    assert_ledger_equal(source, before)


def test_save_load_and_caller_edits_never_mutate_input_or_database_payload():
    client = FakeClient()
    backend = store(client)
    source = ledger()
    before = deepcopy(source)
    saved = backend.save(source, expected_revision=None, owner_scope=ALICE)
    assert_ledger_equal(source, before)
    database_before = deepcopy(client.database)
    saved["ledger"]["flows"].loc[0, "id"] = "edited"
    source["valuations"].loc[0, "value_krw"] = 999.
    loaded = backend.load(owner_scope=ALICE)
    loaded["ledger"]["flows"].loc[0, "amount"] = 1000.
    assert client.database == database_before
    assert backend.load(owner_scope=ALICE)["ledger"]["flows"].loc[0, "id"] == "0001"


def test_sql_prepares_only_dedicated_private_table_with_no_client_or_delete_grants():
    sql = (Path(__file__).resolve().parents[1] / "docs" / "20261101_account_performance.sql").read_text()
    statements = " ".join(line for line in sql.lower().splitlines() if not line.lstrip().startswith("--"))
    assert "owner_email text primary key" in statements
    assert "revision bigint not null check (revision > 0)" in statements
    assert "updated_at timestamptz not null default now()" in statements
    assert "enable row level security" in statements and "force row level security" in statements
    assert "as restrictive for all to anon, authenticated" in statements
    assert "using (false) with check (false)" in statements
    assert f"revoke all on table public.{TABLE_NAME} from public, anon, authenticated" in statements
    assert f"revoke all on table public.{TABLE_NAME} from service_role" in statements
    assert f"grant select, insert, update on table public.{TABLE_NAME} to service_role" in statements
    assert "delete" not in statements and "upsert" not in statements
    assert "public.report_history" not in statements


def test_installed_postgrest_client_serializes_owner_and_revision_without_network():
    import httpx
    from postgrest import SyncPostgrestClient

    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        written = json.loads(request.content)
        if request.method == "PATCH":
            written["owner_email"] = ALICE
        written.setdefault("updated_at", STAMP)
        return httpx.Response(200, json=[written])

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        client = SyncPostgrestClient("https://ledger.invalid/rest/v1", http_client=transport)
        backend = store(client)
        assert not requests
        assert backend.load(owner_scope=ALICE) is None
        first = backend.save(ledger(), expected_revision=None, owner_scope=ALICE)
        assert backend.save(first["ledger"], expected_revision=first["revision"], owner_scope=ALICE)["revision"] == 2
    assert [request.method for request in requests] == ["GET", "POST", "PATCH"]
    read, insert, update = requests
    assert read.url.params["owner_email"] == update.url.params["owner_email"] == "eq." + ALICE
    assert update.url.params["revision"] == "eq.1"
    assert json.loads(insert.content)["owner_email"] == ALICE
    for request in requests:
        assert request.url.path == "/rest/v1/" + TABLE_NAME
        assert "on_conflict" not in request.url.params
        assert "resolution=" not in request.headers.get("prefer", "")
    for request in (insert, update):
        assert "return=representation" in request.headers["prefer"]
