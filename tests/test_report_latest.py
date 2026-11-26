"""Last completed report: owner-bound restore first, replace and store a new one once."""

from types import SimpleNamespace

import pytest

from stock_lab_core import report_latest as latest
from stock_lab_core.report_build import invalidate_saved_report
from stock_lab_core.report_widget_state import MEMO_KEY

REPORT = "# Stock Lab 자동 뉴스픽 · 2026-11-27 08:10 KST\n\n## 기준일\n- US 11/26\n"
NEWER = REPORT.replace("08:10", "09:40")
ACC = latest.account_key([])
KEY = ("me@example.test", ACC)


class Query:
    def __init__(self, table):
        self.table = table
        self.filters = {}

    def select(self, columns):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, n):
        return self

    def upsert(self, row, on_conflict):
        assert on_conflict == "owner_email,account_key"
        self.row = row
        return self

    def execute(self):
        if self.table.error:
            raise self.table.error
        if hasattr(self, "row"):
            self.table.rows[(self.row["owner_email"], self.row["account_key"])] = dict(self.row)
            self.table.writes += 1
            return SimpleNamespace(data=[dict(self.row)])
        row = self.table.rows.get((self.filters.get("owner_email"), self.filters.get("account_key")))
        return SimpleNamespace(data=[dict(row)] if row else [])


class Client:
    def __init__(self, error=None):
        self.rows, self.writes, self.error = {}, 0, error

    def table(self, name):
        assert name == "report_latest"
        return Query(self)


def store(client, owner="me@example.test"):
    return latest.SupabaseReportLatestStore(client, owner_scope=owner)


def test_new_report_is_stored_once_then_restored_first_in_a_new_session(tmp_path):
    client = Client()
    state = {MEMO_KEY: REPORT}
    assert latest.persist_last_report(state, owner_scope="Me@Example.test", store=store(client), path=tmp_path / "l.json") == "supabase"
    assert latest.persist_last_report(state, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json") == ""
    assert client.writes == 1
    fresh = {}
    assert latest.restore_last_report(fresh, owner_scope="me@example.test", store=store(client), build_id="b2", path=tmp_path / "x.json")
    assert fresh[MEMO_KEY] == REPORT
    assert "2026-11-27 08:10 KST" in latest.restored_notice(fresh)
    # The code-change invalidation must not wipe the restored copy.
    assert not invalidate_saved_report(fresh, "b2") and fresh[MEMO_KEY] == REPORT
    # Restoring is not a new report: no write.
    assert latest.persist_last_report(fresh, owner_scope="me@example.test", store=store(client), path=tmp_path / "x.json") == ""
    # A newly generated report replaces it, the notice disappears and it is stored.
    fresh[MEMO_KEY] = NEWER
    assert latest.restored_notice(fresh) == ""
    assert latest.persist_last_report(fresh, owner_scope="me@example.test", store=store(client), path=tmp_path / "x.json") == "supabase"
    assert client.rows[KEY]["report_text"] == NEWER


def test_other_owner_and_handwritten_or_partial_text_are_never_shared_or_stored(tmp_path):
    client = Client()
    latest.persist_last_report({MEMO_KEY: REPORT}, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json")
    other = {}
    assert not latest.restore_last_report(other, owner_scope="you@example.test", store=store(client, "you@example.test"), path=tmp_path / "l.json")
    assert MEMO_KEY not in other
    for text in ("내가 붙여넣은 메모", "🌇 Stock Lab 자동 뉴스픽\n• 초안 생성을 보류했습니다."):
        assert latest.persist_last_report({MEMO_KEY: text}, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json") == ""
    assert latest.persist_last_report({MEMO_KEY: REPORT}, owner_scope="", store=None, path=tmp_path / "l.json") == ""
    with pytest.raises(latest.ReportHistoryStoreError):
        store(client).load(owner_scope="you@example.test", account=ACC)


def test_existing_text_or_second_try_is_left_alone(tmp_path):
    client = Client()
    client.rows[KEY] = {"owner_email": "me@example.test", "account_key": ACC, "generated_at": "t", "report_text": REPORT}
    mine = {MEMO_KEY: "내 메모"}
    assert not latest.restore_last_report(mine, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json")
    assert mine[MEMO_KEY] == "내 메모"
    cleared = {}
    assert latest.restore_last_report(cleared, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json")
    cleared[MEMO_KEY] = ""
    assert not latest.restore_last_report(cleared, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json")
    assert cleared[MEMO_KEY] == ""


def test_missing_table_falls_back_to_owner_hashed_local_copy_without_leaking_errors(tmp_path):
    error = type("APIError", (Exception,), {})("relation report_latest at https://secret.example does not exist")
    error.code = "42P01"
    client = Client(error=error)
    state = {MEMO_KEY: REPORT}
    assert latest.persist_last_report(state, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json") == "local:schema_unavailable"
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and "me@example" not in files[0].name
    fresh = {}
    assert latest.restore_last_report(fresh, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json")
    assert fresh[MEMO_KEY] == REPORT and fresh[latest.STATUS_KEY] == "schema_unavailable"
    assert not latest.restore_last_report({}, owner_scope="you@example.test", store=None, path=tmp_path / "l.json")


def test_failed_or_uncomputed_new_report_keeps_the_last_complete_one_until_a_complete_one_arrives(tmp_path):
    client = Client()
    client.rows[KEY] = {"owner_email": "me@example.test", "account_key": ACC, "generated_at": "t", "report_text": REPORT}
    state = {}
    assert latest.restore_last_report(state, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json")
    assert "08:10" in latest.last_report_caption(state)
    uncomputed = NEWER + "\n오늘 점검 미계산 · 보유 종목 영향 확인 불가(영향 없음이 아님).\n"
    failed = "🌇 Stock Lab 자동 뉴스픽\n• 초안 생성을 보류했습니다."
    for text, reason in ((uncomputed, "uncomputed"), (failed, "failed")):
        state[MEMO_KEY] = text
        assert latest.persist_last_report(state, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json") == ""
        assert latest.keep_last_complete(state) == reason and state[MEMO_KEY] == REPORT
        assert latest.kept_notice(reason) and latest.restored_notice(state)
    assert client.writes == 0 and client.rows[KEY]["report_text"] == REPORT
    state[MEMO_KEY] = NEWER
    assert latest.persist_last_report(state, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json") == "supabase"
    assert latest.keep_last_complete(state) == "" and state[MEMO_KEY] == NEWER and "09:40" in latest.last_report_caption(state)
    # A handwritten memo is never swapped back.
    state[MEMO_KEY] = "내 메모"
    assert latest.keep_last_complete(state) == "" and state[MEMO_KEY] == "내 메모"


def test_uncomputed_report_without_a_previous_one_is_shown_but_not_stored(tmp_path):
    client = Client()
    state = {MEMO_KEY: REPORT + "\n오늘 점검 미계산 · 보유 종목 영향 확인 불가\n"}
    assert latest.persist_last_report(state, owner_scope="me@example.test", store=store(client), path=tmp_path / "l.json") == ""
    assert latest.keep_last_complete(state) == "" and "미계산" in state[MEMO_KEY]
    assert client.writes == 0 and not list(tmp_path.iterdir())


def test_report_of_one_account_set_is_never_shown_for_another(tmp_path):
    client = Client()
    isa = {MEMO_KEY: REPORT}
    assert latest.persist_last_report(isa, owner_scope="me@example.test", accounts=["ISA"], store=store(client), path=tmp_path / "l.json") == "supabase"
    assert latest.account_key(["연금", "ISA"]) == latest.account_key(["ISA", "연금", "ISA"]) != latest.account_key(["ISA"])
    both = {}
    assert not latest.restore_last_report(both, owner_scope="me@example.test", accounts=["ISA", "연금"], store=store(client), path=tmp_path / "l.json")
    assert MEMO_KEY not in both
    # Same session switching account filter: the ISA report is no longer labelled as the last complete one.
    assert latest.restore_last_report(isa, owner_scope="me@example.test", accounts=["ISA"], store=store(client), path=tmp_path / "l.json") is False
    assert not latest.restore_last_report(isa, owner_scope="me@example.test", accounts=["연금"], store=store(client), path=tmp_path / "l.json")
    assert latest.last_report_caption(isa) == "" and latest.restored_notice(isa) == ""
    assert latest.restore_last_report(isa, owner_scope="me@example.test", accounts=["ISA"], store=store(client), path=tmp_path / "l.json")
    assert isa[MEMO_KEY] == REPORT and "08:10" in latest.last_report_caption(isa)
    with pytest.raises(latest.ReportHistoryStoreError):
        store(client).load(owner_scope="me@example.test", account="ISA")
