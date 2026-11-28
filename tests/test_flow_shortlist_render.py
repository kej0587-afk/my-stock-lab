"""Run-local reuse cannot hide changed data, registration or refreshes."""
from copy import deepcopy
import pandas as pd
import pytest

from stock_lab_core.flow_shortlist_render import FlowShortlistRenderReuse


def setup_reader():
    snapshot = {"_flow_shortlist_version": "v1", "_flow_shortlist_df": pd.DataFrame(
        {"Ticker": ["AAA", "BBB"], "등록상태": ["미등록", "미등록"], "돈흐름점수": [8., 5.]})}
    calls = []
    def build(value):
        calls.append(value)
        return value["_flow_shortlist_df"].copy()
    return snapshot, calls, FlowShortlistRenderReuse(build, "v1")


def test_same_cached_input_reuses_once_and_isolates_consumer_changes():
    snapshot, calls, reader = setup_reader()
    original = deepcopy(snapshot)
    kw = dict(holdings=pd.DataFrame({"티커": ["AAA"], "보유량": [1]}), watchlist=[{"ticker": "BBB"}])
    first = reader.get(snapshot, **kw)
    first.loc[0, "돈흐름점수"] = -999
    second = reader.get(snapshot, **kw)
    pd.testing.assert_frame_equal(second, original["_flow_shortlist_df"])
    assert len(calls) == 1
    pd.testing.assert_frame_equal(snapshot["_flow_shortlist_df"], original["_flow_shortlist_df"])


@pytest.mark.parametrize("change", ["new_snapshot", "inplace_value", "order", "version", "quantity",
                                  "value", "name_column", "ticker", "watch_add", "watch_nested"])
def test_changed_inputs_always_build(change):
    snapshot, calls, reader = setup_reader()
    holdings = pd.DataFrame({"티커": ["AAA"], "보유량": [1], "원화환산": [10]})
    watch = [{"ticker": "BBB", "meta": {"name": "B"}}]
    reader.get(snapshot, holdings=holdings, watchlist=watch)
    if change == "new_snapshot": snapshot = deepcopy(snapshot)
    elif change == "inplace_value": snapshot["_flow_shortlist_df"].loc[0, "돈흐름점수"] = 9
    elif change == "order": snapshot["_flow_shortlist_df"] = snapshot["_flow_shortlist_df"].iloc[::-1]
    elif change == "version": snapshot["_flow_shortlist_version"] = "v2"
    elif change == "quantity": holdings.loc[0, "보유량"] = 0
    elif change == "value": holdings.loc[0, "원화환산"] = 0
    elif change == "name_column": holdings["자산명"] = "A"
    elif change == "ticker": holdings.loc[0, "티커"] = "BBB"
    elif change == "watch_add": watch.append({"ticker": "AAA"})
    elif change == "watch_nested": watch[0]["meta"]["name"] = "Changed"
    reader.get(snapshot, holdings=holdings, watchlist=watch)
    assert len(calls) == 2


def test_no_time_or_session_reuse_and_failed_build_not_saved():
    snapshot, calls, reader = setup_reader()
    kw = dict(holdings=None, watchlist=[])
    reader.get(snapshot, **kw)
    FlowShortlistRenderReuse(reader.build, "v1").get(snapshot, **kw)
    assert len(calls) == 2
    def failing(_): raise RuntimeError("failure")
    reader.build = failing
    snapshot["_flow_shortlist_version"] = "invalid"
    with pytest.raises(RuntimeError): reader.get(snapshot, **kw)
    assert reader.saved is None


def test_actual_builder_registration_and_queue_output_match(app_module, monkeypatch):
    app = app_module
    snapshot, _, _ = setup_reader()
    snapshot["_flow_shortlist_version"] = app.TODAY_FLOW_SHORTLIST_VERSION
    snapshot["_flow_shortlist_df"]["종목명"] = ["Example A", "Example B"]
    snapshot["_flow_shortlist_df"]["후보군"] = ["회복추적", "스윙후보"]
    holdings = pd.DataFrame({"티커": ["AAA"], "보유량": [1]})
    state = {"watchlist": [{"ticker": "BBB", "name": "Example B"}]}
    monkeypatch.setattr(app, "holdings_table", holdings)
    monkeypatch.setattr(app.st, "session_state", state)
    calls = []
    def build(s):
        calls.append(1)
        return app.build_today_flow_shortlist_df(s)
    reader = FlowShortlistRenderReuse(build, app.TODAY_FLOW_SHORTLIST_VERSION)
    def shared(s): return reader.get(s, holdings=holdings, watchlist=state["watchlist"])
    expected = app.build_today_flow_candidate_queue_items(snapshot, limit=2)
    actual = app.build_today_flow_candidate_queue_items(snapshot, limit=2, shortlist_builder=shared)
    assert actual == expected
    pd.testing.assert_frame_equal(shared(snapshot), app.build_today_flow_shortlist_df(snapshot))
    assert len(calls) == 1
    holdings.loc[0, "보유량"] = 0
    state["watchlist"] = []
    pd.testing.assert_frame_equal(shared(snapshot), app.build_today_flow_shortlist_df(snapshot))
    assert len(calls) == 2
