from copy import deepcopy
from datetime import date, timedelta
import json
from types import SimpleNamespace

import pytest

from stock_lab_core import report_history
from stock_lab_core.report_history import update_report_history
from stock_lab_core.report_history_store import (
    ReportHistoryStoreError, SupabaseReportHistoryStore, TABLE_NAME,
)
from stock_lab_core.today_snapshot import _snapshot_location


DATES = {"US": "2026-10-16", "KR": "2026-10-19"}
OLD = {"US": "2026-10-15", "KR": "2026-10-16"}
ROWS = [{"티커": "AAPL", "최종읽기": "대기", "게이트상태": "관찰"}]
MACRO = {"유가": {"val": 99.02, "as_of": "2026-10-16"}}


class DatabaseFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("DO_NOT_EXPOSE_TOKEN_OR_OWNER database detail")


class FakeClient:
    def __init__(self, database=None):
        self.database = database if database is not None else {}
        self.calls = []
        self.read_error = None
        self.write_error = None
        self.read_response = None
        self.write_response = None

    def table(self, name):
        assert name == TABLE_NAME
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, client):
        self.client = client
        self.filters = {}
        self.bounds = {}
        self.orders = []

    def select(self, columns):
        self.operation = "select"
        self.columns = columns
        return self

    def eq(self, name, value):
        self.filters[name] = value
        return self

    def lte(self, name, value):
        self.bounds[name] = value
        return self

    def order(self, name, desc=False):
        self.orders.append((name, desc))
        return self

    def limit(self, count):
        self.count = count
        return self

    def upsert(self, row, *, on_conflict):
        assert on_conflict == "owner_email,us_session,kr_session"
        self.operation, self.row = "upsert", deepcopy(row)
        return self

    def execute(self):
        if self.operation == "select":
            self.client.calls.append(("select", deepcopy(self.filters), deepcopy(self.bounds)))
            assert self.filters.keys() == {"owner_email"}
            assert self.bounds.keys() == {"us_session", "kr_session"}
            assert self.orders == [("us_session", True), ("kr_session", True)]
            if self.client.read_error:
                raise self.client.read_error
            if self.client.read_response is not None:
                return self.client.read_response
            rows = [row for row in self.client.database.values()
                    if all(row[k] == v for k, v in self.filters.items())
                    and all(row[k] <= v for k, v in self.bounds.items())]
            rows.sort(key=lambda row: (row["us_session"], row["kr_session"]), reverse=True)
            return SimpleNamespace(data=deepcopy(rows[:self.count]))
        self.client.calls.append(("upsert", deepcopy(self.row)))
        if self.client.write_error:
            raise self.client.write_error
        if self.client.write_response is not None:
            return self.client.write_response
        row = self.row
        key = (row["owner_email"], row["us_session"], row["kr_session"])
        self.client.database[key] = deepcopy(row)
        return SimpleNamespace(data=[deepcopy(row)])


def run(client, tmp_path, *, owner="alice@example.test", dates=None, rows=None, **kwargs):
    return update_report_history(
        ROWS if rows is None else rows, DATES if dates is None else dates,
        owner_scope=owner, path=tmp_path / "history.json",
        store=SupabaseReportHistoryStore(client, owner_scope=owner), **kwargs,
    )


def test_durable_pair_upsert_compares_prior_day_and_prior_run_after_restart(tmp_path):
    client = FakeClient()
    before = deepcopy((ROWS, DATES, MACRO))
    run(client, tmp_path / "first", dates=OLD, macro_data=MACRO)
    run(client, tmp_path / "second", macro_data=MACRO, generated_at="2026-10-19T09:00:00+09:00")
    revised = {"유가": {"val": 101.41, "as_of": "2026-10-16"}}
    changed = [dict(ROWS[0], 게이트상태="방어우선")]
    restarted = FakeClient(client.database)
    result = run(restarted, tmp_path / "no_local_cache", rows=changed, macro_data=revised)
    assert result["history_backend"] == "supabase" and result["history_durable"]
    assert not result["history_fallback"]
    assert result["previous_macro_data"] == MACRO
    assert result["previous_run_at"] == "2026-10-19T09:00:00+09:00"
    assert result["previous_run_date"] == "2026-10-16/2026-10-19"
    assert result["previous_run_summary"][0]["게이트상태"] == "관찰"
    assert result["previous_date"] == "2026-10-15/2026-10-16"
    assert result["previous_sessions"] == OLD
    assert len(client.database) == 2
    assert client.database[("alice@example.test", "2026-10-16", "2026-10-19")]["payload"]["macro_data"] == revised
    assert (ROWS, DATES, MACRO) == before


def test_mixed_pair_ranking_is_source_date_policy_not_utc_or_generation_order(tmp_path):
    client = FakeClient()
    mixed = {"US": "2026-10-20", "KR": "2026-10-19"}
    other = {"US": "2026-10-19", "KR": "2026-10-20"}
    current = {"US": "2026-10-20", "KR": "2026-10-20"}
    run(client, tmp_path / "mixed", dates=mixed, generated_at="2026-10-21T00:05:00+00:00")
    run(client, tmp_path / "other", dates=other, generated_at="2026-10-21T00:10:00+00:00")
    run(client, tmp_path / "same", dates=current, generated_at="2026-10-21T00:15:00+00:00")
    original = deepcopy(client.database)

    result = run(client, tmp_path / "restart", dates=current, generated_at="2026-10-21T10:32:00+09:00")

    assert result["previous_date"] == "2026-10-20/2026-10-19"
    assert result["previous_sessions"] == mixed
    assert result["previous_run_date"] == "2026-10-20/2026-10-20"
    assert result["previous_run_at"] == "2026-10-21T00:15:00+00:00"
    for dates in (mixed, other):
        key = ("alice@example.test", dates["US"], dates["KR"])
        assert client.database[key] == original[key]


def test_owner_isolation_and_case_normalization(tmp_path):
    client = FakeClient()
    run(client, tmp_path, owner=" Alice@Example.Test ", macro_data=MACRO)
    bob = run(client, tmp_path, owner="bob@example.test")
    assert not bob["previous_summary"] and "previous_run_summary" not in bob
    assert "previous_macro_data" not in bob
    alice = run(client, tmp_path / "restart", owner="alice@example.test")
    assert alice["previous_run_summary"]
    assert {key[0] for key in client.database} == {"alice@example.test", "bob@example.test"}
    assert [call[1]["owner_email"] for call in client.calls if call[0] == "select"] == [
        "alice@example.test", "bob@example.test", "alice@example.test",
    ]


def test_mismatched_bound_owner_falls_back_without_database_access(tmp_path):
    client = FakeClient()
    result = update_report_history(ROWS, DATES, owner_scope="bob@example.test", path=tmp_path / "history.json",
                                   store=SupabaseReportHistoryStore(client, owner_scope="alice@example.test"))
    assert not client.calls
    assert result["history_fallback"] and result["history_error"] == "owner_scope_mismatch"
    assert result["history_backend"] == "local" and not result["history_durable"]


@pytest.mark.parametrize("owner", ["", "  ", None])
def test_public_or_blank_owner_never_calls_backend_or_creates_default_cache(tmp_path, monkeypatch, owner):
    client = FakeClient()
    monkeypatch.setattr(report_history, "DEFAULT_PATH", tmp_path / "history.json")
    result = update_report_history(ROWS, DATES, owner_scope=owner,
                                   store=SupabaseReportHistoryStore(client, owner_scope=owner))
    assert not client.calls and not list(tmp_path.iterdir())
    assert result["history_backend"] == "none" and not result["history_durable"]


@pytest.mark.parametrize("dates,rows", [({"US": "", "KR": "2026-10-19"}, ROWS),
                                      ({"US": "invalid", "KR": "2026-10-19"}, ROWS), (DATES, [])])
def test_missing_or_invalid_evidence_does_not_touch_backend(tmp_path, dates, rows):
    client = FakeClient()
    result = run(client, tmp_path, dates=dates, rows=rows)
    assert not client.calls and not list(tmp_path.iterdir())
    assert not result["history_durable"]


@pytest.mark.parametrize("code,expected", [("42P01", "schema_unavailable"), ("PGRST205", "schema_unavailable"),
                                         ("42501", "store_unavailable"), ("08006", "store_unavailable")])
def test_read_failure_uses_local_history_with_explicit_redacted_status(tmp_path, capsys, caplog, code, expected):
    update_report_history(ROWS, OLD, owner_scope="alice@example.test", path=tmp_path / "history.json", macro_data=MACRO)
    client = FakeClient()
    client.read_error = DatabaseFailure(code)
    result = run(client, tmp_path)
    assert result["history_backend"] == "local" and result["history_fallback"]
    assert not result["history_durable"] and result["history_error"] == expected
    assert result["previous_date"] == "2026-10-15/2026-10-16"
    assert result["previous_macro_data"] == MACRO
    if expected == "schema_unavailable":
        assert "SQL 적용 미확인" in result["history_status"]
    captured = capsys.readouterr()
    assert "DO_NOT_EXPOSE" not in str(result) + captured.out + captured.err + caplog.text
    assert len(client.calls) == 1


def test_write_failure_keeps_cloud_comparisons_and_next_local_run(tmp_path):
    client = FakeClient()
    run(client, tmp_path / "old_server", macro_data=MACRO)
    client.write_error = DatabaseFailure("08006")
    result = run(client, tmp_path / "new_server", macro_data={"VIX": {"val": 22}})
    assert result["previous_macro_data"] == MACRO
    assert result["history_fallback"] and not result["history_durable"]
    client.read_error = DatabaseFailure("08006")
    following = run(client, tmp_path / "new_server")
    assert following["previous_macro_data"] == {"VIX": {"val": 22}}


def test_recovery_compares_newer_local_outage_run_instead_of_stale_cloud(tmp_path):
    client = FakeClient()
    run(client, tmp_path, macro_data=MACRO, generated_at="2026-10-19T00:00:00Z")
    client.read_error = DatabaseFailure("08006")
    outage_macro = {"VIX": {"val": 22}}
    run(client, tmp_path, macro_data=outage_macro, generated_at="2026-10-19T09:10:00+09:00")
    client.read_error = None
    result = run(client, tmp_path, generated_at="2026-10-19T00:20:00Z")
    assert result["previous_macro_data"] == outage_macro and result["history_durable"]


def test_future_or_incompatible_pairs_do_not_hide_previous_valid_pair(tmp_path):
    client = FakeClient()
    run(client, tmp_path, dates=OLD, macro_data=MACRO)
    run(client, tmp_path, dates={"US": "2026-10-19", "KR": "2026-10-16"})
    run(client, tmp_path, dates={"US": "2026-10-20", "KR": "2026-10-20"})
    result = run(client, tmp_path / "restart")
    assert result["previous_date"] == "2026-10-15/2026-10-16"
    assert result["previous_macro_data"] == MACRO
    assert "previous_run_summary" not in result and len(client.database) == 4


def test_more_than_40_pairs_are_retained_locally_and_in_database(tmp_path):
    client = FakeClient()
    for offset in range(42):
        day = (date(2026, 8, 1) + timedelta(days=offset)).isoformat()
        run(client, tmp_path, dates={"US": day, "KR": day})
    location, _ = _snapshot_location(tmp_path / "history.json", "alice@example.test")
    assert len(client.database) == 42
    assert len(json.loads(location.read_text(encoding="utf-8"))["sessions"]) == 42


def test_unexpected_response_owner_is_not_used_in_comparisons(tmp_path):
    client = FakeClient()
    run(client, tmp_path / "bob", owner="bob@example.test", macro_data=MACRO)
    client.read_response = SimpleNamespace(data=list(client.database.values()))
    result = run(client, tmp_path / "alice")
    assert result["history_error"] == "owner_scope_mismatch" and not result["history_durable"]
    assert "previous_run_summary" not in result and "previous_macro_data" not in result
    assert len([call for call in client.calls if call[0] == "upsert"]) == 1


@pytest.mark.parametrize("response", [SimpleNamespace(data=None), SimpleNamespace(data=[{}]), SimpleNamespace()])
def test_invalid_read_response_falls_back(tmp_path, response):
    client = FakeClient()
    client.read_response = response
    result = run(client, tmp_path)
    assert result["history_fallback"] and not result["history_durable"]
    assert len(client.calls) == 1


def test_empty_upsert_response_is_not_reported_as_durable(tmp_path):
    client = FakeClient()
    client.write_response = SimpleNamespace(data=[])
    result = run(client, tmp_path)
    assert result["history_error"] == "write_unconfirmed" and not result["history_durable"]
    assert result["history_backend"] == "local"


@pytest.mark.parametrize("change", ["dates", "rows"])
def test_malformed_cloud_payload_is_rejected_before_overwrite(tmp_path, change):
    client = FakeClient()
    run(client, tmp_path / "first")
    bad_row = deepcopy(next(iter(client.database.values())))
    if change == "dates":
        bad_row["payload"]["dates"]["US"] = "2026-10-15"
    else:
        bad_row["payload"]["rows"] = "invalid"
    client.read_response = SimpleNamespace(data=[bad_row])
    count = len(client.calls)
    result = run(client, tmp_path / "restart")
    assert result["history_error"] == "invalid_data" and not result["history_durable"]
    assert "previous_run_summary" not in result and len(client.calls) == count + 1


def test_database_and_local_failure_report_unavailable(tmp_path):
    location, _ = _snapshot_location(tmp_path / "history.json", "alice@example.test")
    location.write_text("{damaged", encoding="utf-8")
    client = FakeClient()
    client.read_error = DatabaseFailure("PGRST205")
    result = run(client, tmp_path)
    assert result["history_backend"] == "unavailable" and result["history_fallback"]
    assert not result["history_durable"] and result["history_local_status"] == "unavailable"
    assert location.read_text(encoding="utf-8") == "{damaged"


def test_local_mirror_failure_does_not_relabel_confirmed_cloud_write(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(report_history, "_save_local", lambda *args: (_ for _ in ()).throw(OSError()))
    result = run(client, tmp_path)
    assert result["history_durable"] and result["history_backend"] == "supabase"
    assert result["history_local_status"] == "unavailable"


def test_atomic_local_failure_preserves_previous_rows_and_cleans_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    update_report_history(ROWS, OLD, path=path)
    original = path.read_bytes()
    monkeypatch.setattr(report_history.os, "replace", lambda *args: (_ for _ in ()).throw(OSError()))
    result = update_report_history(ROWS, DATES, path=path)
    assert result["history_backend"] == "unavailable" and not result["history_durable"]
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_legacy_api_keeps_previous_run_without_timestamp(tmp_path):
    path = tmp_path / "history.json"
    update_report_history(ROWS, DATES, path=path, macro_data=MACRO)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sessions"]["2026-10-16/2026-10-19"].pop("generated_at")
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = update_report_history(ROWS, DATES, path=path)
    assert result["previous_run_at"] == "저장 시각 미확보" and result["previous_run_summary"]
    assert result["previous_macro_data"] == MACRO
    assert result["history_backend"] == "local" and not result["history_fallback"]


def test_corrupt_local_file_is_preserved_and_does_not_block_durable_store(tmp_path):
    location, _ = _snapshot_location(tmp_path / "history.json", "alice@example.test")
    location.write_text("{damaged", encoding="utf-8")
    result = run(FakeClient(), tmp_path)
    assert result["history_durable"] and result["history_local_status"] == "unavailable"
    assert location.read_text(encoding="utf-8") == "{damaged"


def test_direct_backend_requires_matching_nonempty_owner():
    client = FakeClient()
    store = SupabaseReportHistoryStore(client, owner_scope="alice@example.test")
    session = {"dates": DATES, "rows": []}
    with pytest.raises(ReportHistoryStoreError):
        store.load_sessions(DATES, owner_scope="")
    with pytest.raises(ReportHistoryStoreError):
        store.upsert_session(session, owner_scope="bob@example.test")
    assert not client.calls


def test_installed_postgrest_client_serializes_scoped_requests_without_network(tmp_path):
    import httpx
    from postgrest import SyncPostgrestClient

    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=[json.loads(request.content)])

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        client = SyncPostgrestClient("https://history.invalid/rest/v1", http_client=transport)
        result = run(client, tmp_path, macro_data=MACRO)
    assert result["history_durable"] and len(requests) == 2
    read, write = requests
    assert read.url.path == write.url.path == "/rest/v1/report_history"
    assert read.url.params["owner_email"] == "eq.alice@example.test"
    assert read.url.params["us_session"] == "lte.2026-10-16"
    assert read.url.params["kr_session"] == "lte.2026-10-19"
    assert write.url.params["on_conflict"] == "owner_email,us_session,kr_session"
    assert "resolution=merge-duplicates" in write.headers["prefer"]
    assert "return=representation" in write.headers["prefer"]
    assert json.loads(write.content)["owner_email"] == "alice@example.test"
