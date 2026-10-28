"""Focused journal UI regressions using real Streamlit and an offline ledger."""

from copy import deepcopy
import csv
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


OWNER = "owner-a@example.test"
OTHER_OWNER = "owner-b@example.test"
SOURCE = """
import streamlit as st
from stock_lab_core.event_swing import render_event_swing_panel

render_event_swing_panel(st, [], client=st.session_state["_test_client"],
                         owner=st.session_state["_test_owner"])
"""


class MemoryClient:
    def __init__(self):
        self.rows = {}
        self.writes = []
        self.fail_next = False

    def table(self, name):
        assert name == "event_swing_ledger"
        return MemoryQuery(self)


class MemoryQuery:
    def __init__(self, client):
        self.client = client
        self.owner = None
        self.pending = None

    def select(self, columns):
        assert columns == "trade_id,payload,created_at"
        return self

    def eq(self, column, value):
        assert column == "owner_email"
        self.owner = value
        return self

    def order(self, column, *, desc):
        assert column == "created_at" and desc
        return self

    def limit(self, count):
        assert count == 200
        return self

    def upsert(self, row, *, on_conflict):
        assert on_conflict == "owner_email,trade_id"
        self.pending = deepcopy(row)
        return self

    def execute(self):
        if self.pending is not None:
            self.client.writes.append(deepcopy(self.pending))
            if self.client.fail_next:
                self.client.fail_next = False
                return SimpleNamespace(data=[])
            key = (self.pending["owner_email"], self.pending["trade_id"])
            self.client.rows[key] = deepcopy(self.pending)
            return SimpleNamespace(data=[deepcopy(self.pending)])
        assert self.owner is not None, "Private ledger reads must bind an owner"
        return SimpleNamespace(data=[deepcopy(row) for (owner, _), row in self.client.rows.items()
                                     if owner == self.owner][:200])


@pytest.fixture
def journal():
    client = MemoryClient()
    app = AppTest.from_string(SOURCE, default_timeout=15)
    app.session_state["_test_client"] = client
    app.session_state["_test_owner"] = OWNER
    app.run()
    assert not app.exception
    return app, client


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def fill_trade(app, *, ticker="TEST", catalyst="Public earnings release"):
    widget(app.text_input, "실제 체결 종목 티커").set_value(ticker)
    widget(app.number_input, "평균 체결가").set_value(100.0)
    widget(app.number_input, "체결 수량").set_value(2.0)
    widget(app.number_input, "기록할 손절 기준가").set_value(90.0)
    widget(app.text_input, "촉매·확인 출처").set_value(catalyst)
    widget(app.checkbox, "촉매의 발표일·출처를 직접 확인함").check()
    widget(app.checkbox, "실제로 체결한 거래를 기록함").check()


def submit(app):
    widget(app.button, "체결 기록 저장").click().run()
    assert not app.exception


def assert_empty_form(app):
    assert all(item.value == "" for item in app.text_input)
    assert all(item.value == 0 for item in app.number_input)
    assert all(not item.value for item in app.checkbox)
    assert not widget(app.button, "체결 기록 저장").disabled


def test_repeat_submit_and_rerun_keep_one_saved_trade_and_same_id(journal):
    app, client = journal
    trade_id = app.session_state[f"event_swing_trade_id:{OWNER}"]
    fill_trade(app)
    submit(app)
    assert len(client.rows) == 1 and app.success
    assert app.session_state[f"event_swing_trade_id:{OWNER}"] == trade_id
    assert app.session_state[f"event_swing_saved:{OWNER}"] is True
    payload = client.rows[(OWNER, trade_id)]["payload"]
    assert payload["건별손실한도(원)"] is None
    assert payload["조건상태"] == "건별 손실한도 미설정"

    # A second click can arrive from the just-rendered pre-lock submit button.
    submit(app)
    assert len(client.rows) == 1
    assert app.session_state[f"event_swing_trade_id:{OWNER}"] == trade_id
    assert widget(app.button, "체결 기록 저장").disabled
    writes = len(client.writes)
    app.run()
    assert not app.exception and len(client.writes) == writes
    assert len(client.rows) == 1


def test_explicit_new_trade_resets_form_and_requires_fresh_confirmation(journal):
    app, client = journal
    fill_trade(app)
    submit(app)
    first_id = app.session_state[f"event_swing_trade_id:{OWNER}"]
    app.run()
    widget(app.button, "새 거래 기록").click().run()
    assert not app.exception
    new_id = app.session_state[f"event_swing_trade_id:{OWNER}"]
    assert new_id != first_id
    assert app.session_state[f"event_swing_saved:{OWNER}"] is False
    assert_empty_form(app)
    assert len(client.rows) == 1

    fill_trade(app, ticker="NEXT")
    widget(app.checkbox, "실제로 체결한 거래를 기록함").uncheck()
    submit(app)
    assert app.error and len(client.rows) == 1
    widget(app.checkbox, "실제로 체결한 거래를 기록함").check()
    submit(app)
    assert len(client.rows) == 2
    assert client.rows[(OWNER, first_id)]["payload"]["티커"] == "TEST"
    assert client.rows[(OWNER, new_id)]["payload"]["티커"] == "NEXT"


def test_saved_trade_cannot_be_overwritten_from_the_still_enabled_success_form(journal):
    app, client = journal
    fill_trade(app)
    submit(app)
    saved = deepcopy(client.rows)
    assert app.session_state[f"event_swing_saved:{OWNER}"] is True
    # Form edits do not rerun the script; the success response can still show
    # the previously enabled submit button until the next submission arrives.
    if not widget(app.button, "체결 기록 저장").disabled:
        widget(app.text_input, "실제 체결 종목 티커").set_value("CHANGED")
        widget(app.number_input, "체결 수량").set_value(99.0)
        submit(app)
    assert client.rows == saved, "A saved trade was overwritten without explicit new-trade confirmation"
    assert len(client.writes) == 1


def test_unconfirmed_save_retries_same_id_and_preserves_input(journal):
    app, client = journal
    trade_id = app.session_state[f"event_swing_trade_id:{OWNER}"]
    client.fail_next = True
    fill_trade(app)
    submit(app)
    assert app.error and not app.success and not client.rows
    assert app.session_state[f"event_swing_trade_id:{OWNER}"] == trade_id
    assert widget(app.text_input, "실제 체결 종목 티커").value == "TEST"
    assert not widget(app.button, "체결 기록 저장").disabled
    submit(app)
    assert app.success and len(client.rows) == 1
    assert [row["trade_id"] for row in client.writes] == [trade_id, trade_id]


def test_owner_switch_does_not_reuse_trade_form_lock_or_rows(journal):
    app, client = journal
    fill_trade(app)
    submit(app)
    first_id = app.session_state[f"event_swing_trade_id:{OWNER}"]
    app.session_state["_test_owner"] = OTHER_OWNER
    app.run()
    assert not app.exception and not app.dataframe
    assert_empty_form(app)
    other_id = app.session_state[f"event_swing_trade_id:{OTHER_OWNER}"]
    assert other_id != first_id
    fill_trade(app, ticker="OTHER")
    submit(app)
    assert len(client.rows) == 2
    app.session_state["_test_owner"] = OWNER
    app.run()
    assert not app.exception
    assert app.session_state[f"event_swing_trade_id:{OWNER}"] == first_id
    assert widget(app.button, "체결 기록 저장").disabled
    assert app.dataframe[0].value["티커"].tolist() == ["TEST"]


def test_download_escapes_formula_text_without_mutating_ledger(journal, monkeypatch):
    app, client = journal
    values = ["=1+1", "+SUM(1,1)", "-1+2", "@SUM(1,1)", "  =1+1",
              "\t=1+1", "\r=1+1", "\n=1+1", "Public source"]
    for value in values:
        trade_id = str(uuid4())
        client.rows[(OWNER, trade_id)] = {
            "owner_email": OWNER, "trade_id": trade_id,
            "payload": {"티커": "TEST", "촉매": value, "체결가": 100.0},
        }
    other_id = str(uuid4())
    client.rows[(OTHER_OWNER, other_id)] = {
        "owner_email": OTHER_OWNER, "trade_id": other_id,
        "payload": {"티커": "PRIVATE", "촉매": "Other owner's private note"},
    }
    before, downloads = deepcopy(client.rows), []
    real_download = st.download_button

    def capture_download(label, data, *args, **kwargs):
        downloads.append(data)
        return real_download(label, data, *args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture_download)
    app.run()
    assert not app.exception and len(app.get("download_button")) == 1
    assert len(downloads) == 1 and downloads[0].startswith(b"\xef\xbb\xbf")
    exported = list(csv.DictReader(StringIO(downloads[0].decode("utf-8-sig"))))
    assert [row["촉매"] for row in exported] == ["'" + value for value in values[:-1]] + values[-1:]
    assert all(row["체결가"] == "100.0" for row in exported)
    assert "Other owner's private note" not in downloads[0].decode("utf-8-sig")
    assert app.dataframe[0].value["촉매"].tolist() == values
    assert client.rows == before and not client.writes
