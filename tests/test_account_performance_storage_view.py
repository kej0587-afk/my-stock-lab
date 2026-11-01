"""Real form lifecycle with an explicitly synthetic, in-memory owner store."""

from copy import deepcopy
from hashlib import sha256

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core.account_performance_io import decode_ledger, encode_ledger
from tests.test_account_performance_io import ledger


class MemoryStore:
    def __init__(self, database, calls, faults, owner):
        self.database, self.calls, self.faults, self.owner = database, calls, faults, owner

    def load(self, *, owner_scope):
        assert owner_scope == self.owner
        self.calls.append(("load", self.owner))
        if self.faults.get("load"):
            raise self.faults["load"]
        return deepcopy(self.database.get(self.owner))

    def save(self, candidate, *, expected_revision, owner_scope):
        from stock_lab_core.account_performance_store import AccountPerformanceStoreError

        assert owner_scope == self.owner
        self.calls.append(("save", self.owner, expected_revision))
        if self.faults.get("save"):
            raise self.faults["save"]
        previous = self.database.get(self.owner)
        if (previous["revision"] if previous else None) != expected_revision:
            raise AccountPerformanceStoreError("conflict")
        record = dict(revision=(expected_revision or 0) + 1, ledger=decode_ledger(encode_ledger(candidate)),
                      updated_at="2026-11-01T00:00:00+00:00")
        self.database[self.owner] = deepcopy(record)
        return record


SCRIPT = '''
import streamlit as st
from stock_lab_core.account_performance_view import render_account_performance
from tests.test_account_performance_storage_view import MemoryStore
owner = st.radio("test owner", ["A", "B"], key="test_owner")
store = MemoryStore(st.session_state["test_db"], st.session_state["test_calls"], st.session_state["test_faults"], owner)
render_account_performance(st, owner_scope=owner, store=store)
'''


def prefix(owner="A"):
    return "account_performance_v1_" + sha256(owner.lower().encode()).hexdigest()[:20]


def app_with_store(database=None, *, draft=None):
    app = AppTest.from_string(SCRIPT)
    app.session_state["test_db"] = {} if database is None else database
    app.session_state["test_calls"] = []
    app.session_state["test_faults"] = {}
    app.session_state[prefix() + "_draft"] = ledger() if draft is None else draft
    app.session_state[prefix() + "_revision"] = 0
    return app.run()


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


def restore(app):
    next(widget for widget in app.checkbox if widget.label.startswith("서버 저장본으로")).check().run()
    button(app, "저장본 적용").click().run()


def test_no_background_read_or_write_and_save_waits_for_server_baseline():
    app = app_with_store()
    assert not app.exception
    assert not app.session_state["test_calls"]
    assert button(app, "적용·개인 저장").disabled
    button(app, "원장 초안 적용").click().run()
    assert not app.session_state["test_calls"]
    assert button(app, "적용·개인 저장").disabled


def test_empty_server_first_save_then_new_session_explicit_restore():
    app = app_with_store()
    button(app, "서버 저장본 확인").click().run()
    assert app.session_state["test_calls"] == [("load", "A")]
    assert not button(app, "적용·개인 저장").disabled
    button(app, "적용·개인 저장").click().run()
    assert not app.exception
    record = app.session_state["test_db"]["A"]
    assert record["revision"] == 1
    assert any("저장 완료" in item.value for item in app.success)
    restarted = app_with_store(deepcopy(app.session_state["test_db"]), draft={
        "valuations": ledger()["valuations"].iloc[:0].copy(), "flows": ledger()["flows"].iloc[:0].copy(),
    })
    button(restarted, "서버 저장본 확인").click().run()
    assert restarted.session_state[prefix() + "_draft"]["valuations"].empty
    assert button(restarted, "저장본 적용").disabled
    assert button(restarted, "적용·개인 저장").disabled
    restore(restarted)
    assert not restarted.exception
    assert not restarted.session_state[prefix() + "_draft"]["valuations"].empty
    pd.testing.assert_frame_equal(restarted.session_state[prefix() + "_draft"]["valuations"], record["ledger"]["valuations"])
    assert not button(restarted, "적용·개인 저장").disabled
    assert all(call[0] == "load" for call in restarted.session_state["test_calls"])


def test_existing_server_preview_does_not_replace_local_draft_or_rebase_save():
    record = dict(revision=4, ledger=ledger(), updated_at="2026-11-01T00:00:00Z")
    local = ledger()
    local["valuations"].loc[0, "value_krw"] = 77.
    app = app_with_store({"A": record}, draft=local)
    button(app, "서버 저장본 확인").click().run()
    assert not app.exception
    assert app.session_state[prefix() + "_draft"]["valuations"].iloc[0]["value_krw"] == 77.
    assert button(app, "적용·개인 저장").disabled
    assert app.session_state["test_db"]["A"]["revision"] == 4


def test_concurrent_save_conflict_keeps_applied_draft_and_newer_server_data():
    app = app_with_store()
    button(app, "서버 저장본 확인").click().run()
    button(app, "적용·개인 저장").click().run()
    original = deepcopy(app.session_state[prefix() + "_draft"])
    app.session_state["test_db"]["A"]["revision"] = 2
    app.session_state["test_db"]["A"]["ledger"]["valuations"].loc[0, "value_krw"] = 999.
    app.run()
    button(app, "적용·개인 저장").click().run()
    assert not app.exception
    assert any("다른 접속" in item.value for item in app.warning)
    assert button(app, "적용·개인 저장").disabled
    pd.testing.assert_frame_equal(app.session_state[prefix() + "_draft"]["valuations"], original["valuations"])
    assert app.session_state["test_db"]["A"]["revision"] == 2
    assert app.session_state["test_db"]["A"]["ledger"]["valuations"].iloc[0]["value_krw"] == 999.


@pytest.mark.parametrize("operation", ["load", "save"])
@pytest.mark.parametrize("code", ["schema_unavailable", "store_unavailable", "write_unconfirmed", "invalid_data"])
def test_storage_failure_retains_draft_and_does_not_expose_database_details(operation, code):
    from stock_lab_core.account_performance_store import AccountPerformanceStoreError

    app = app_with_store()
    original = deepcopy(app.session_state[prefix() + "_draft"])
    if operation == "save":
        button(app, "서버 저장본 확인").click().run()
    app.session_state["test_faults"][operation] = AccountPerformanceStoreError(code)
    label = "서버 저장본 확인" if operation == "load" else "적용·개인 저장"
    button(app, label).click().run()
    assert not app.exception
    assert app.warning
    assert button(app, "적용·개인 저장").disabled
    pd.testing.assert_frame_equal(app.session_state[prefix() + "_draft"]["valuations"], original["valuations"])
    assert not app.session_state["test_db"]


def test_unexpected_backend_error_is_redacted_and_no_data_is_lost():
    app = app_with_store()
    app.session_state["test_faults"]["load"] = RuntimeError("DO_NOT_EXPOSE_TOKEN")
    button(app, "서버 저장본 확인").click().run()
    assert not app.exception
    assert all("DO_NOT_EXPOSE" not in item.value for item in app.warning)
    assert "DO_NOT_EXPOSE" not in repr(app.session_state[prefix() + "_storage"])


def test_switching_owner_keeps_drafts_and_revision_baselines_separate():
    app = app_with_store()
    button(app, "서버 저장본 확인").click().run()
    button(app, "적용·개인 저장").click().run()
    app.radio[0].set_value("B").run()
    assert not app.exception
    assert button(app, "적용·개인 저장").disabled
    assert app.session_state[prefix("B") + "_draft"]["valuations"].empty
    assert app.session_state[prefix() + "_storage"]["base_revision"] == 1
    assert set(app.session_state["test_db"]) == {"A"}


def test_restore_and_save_clear_results_and_do_not_store_completeness():
    app = app_with_store()
    next(widget for widget in app.checkbox if widget.label.startswith("이 계좌의 평가기간")).check().run()
    button(app, "계좌 성과 계산").click().run()
    assert app.metric
    button(app, "서버 저장본 확인").click().run()
    assert app.metric
    button(app, "적용·개인 저장").click().run()
    assert not app.metric
    assert not next(widget for widget in app.checkbox if widget.label.startswith("이 계좌의 평가기간")).value
    assert set(app.session_state["test_db"]["A"]["ledger"]) == {"valuations", "flows"}


def test_local_apply_does_not_keep_an_old_cloud_save_success_message():
    app = app_with_store()
    button(app, "서버 저장본 확인").click().run()
    button(app, "적용·개인 저장").click().run()
    assert any("저장 완료" in item.value for item in app.success)
    saved = deepcopy(app.session_state["test_db"])
    calls = list(app.session_state["test_calls"])
    button(app, "원장 초안 적용").click().run()
    assert not app.exception
    assert not any("저장 완료" in item.value for item in app.success)
    assert app.session_state["test_calls"] == calls
    assert app.session_state["test_db"]["A"]["revision"] == saved["A"]["revision"]
    pd.testing.assert_frame_equal(app.session_state["test_db"]["A"]["ledger"]["valuations"], saved["A"]["ledger"]["valuations"])
