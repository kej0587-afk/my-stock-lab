"""Cache/refresh contract against the retained application, without account IO."""

import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta, timezone
from functools import lru_cache
import logging
from pathlib import Path
import subprocess
from unittest.mock import patch

import pandas as pd
import pytest

from stock_lab_core.formatters import clean_float, normalize_ticker, sanitize_ticker_value
from stock_lab_core.money_flow import SECTOR_CLUSTERS_KR
from tests.test_today_queue_view_refactor import FixedDateTime, freeze, UI as BaseUI


ROOT = Path(__file__).resolve().parents[1]
BASE = "7dc7a6cfc30c6bc156db7617b295a294e6fce98f"
MAIN = "_render_today_queue_tab"
KEY = "today_queue_summary_df"
SIG = "today_queue_summary_sig"
LAST = "today_queue_summary_last_run"
NONEMPTY = "today_queue_summary_last_nonempty_df"
NONEMPTY_SIG = "today_queue_summary_last_nonempty_sig"
OWNER = "today_queue_summary_owner"


@pytest.fixture(scope="module")
def sources():
    return (subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8"),
            (ROOT / "app.py").read_text(encoding="utf-8-sig"))


def is_assignment(node, name):
    return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)


@lru_cache(maxsize=2)
def compiled_prefix(source):
    tree = ast.parse(source)
    fn = deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == MAIN))
    start = next(i for i, n in enumerate(fn.body) if is_assignment(n, "portfolio_signal_attrs"))
    fn.body = fn.body[:start] + ast.parse("return summary_df, watch_items, queue_sig, run_summary").body
    fn.decorator_list = []
    helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {
        "_calculate_fresh_today_summary", "_preload_today_queue_kr_context", "_kr_rotation_context_requests"}]
    helpers += [n for n in tree.body if any(is_assignment(n, name) for name in (
        "TODAY_FLOW_SHORTLIST_VERSION", "MARKET_CLUSTER_CONTEXT_CACHE_KEY",
        "MARKET_CLUSTER_CONTEXT_CACHE_VERSION", "MARKET_CLUSTER_CONTEXT_CACHE_TTL_SECONDS"))]
    return compile(ast.fix_missing_locations(ast.Module(body=helpers + [fn], type_ignores=[])), "<queue-session>", "exec")


class Rerun(BaseException):
    pass


class StopCalculation(BaseException):
    pass


class State(dict):
    def __getattr__(self, key):
        return self[key]


class UI(BaseUI):
    def __init__(self, state, action, full):
        super().__init__()
        self.session_state = State(deepcopy(state))
        self.action, self.full = action, full

    def checkbox(self, label, **kwargs):
        self.record("checkbox", label, **kwargs)
        self.session_state[kwargs["key"]] = self.full
        return self.full

    def button(self, label, **kwargs):
        self.record("button", label, **kwargs)
        return self.action == kwargs["key"]

    def empty(self):
        self.record("empty")
        return self

    def rerun(self):
        self.record("rerun")
        raise Rerun()


def summary(ticker="WATCH"):
    frame = pd.DataFrame({"티커": [ticker], "종목명": ["Test " + ticker], "게이트상태": ["방어우선"]})
    frame.attrs = {"portfolio_signal_context": {"owner": "original"}, "sentinel": "preserved"}
    return frame


def case(kind):
    state = {"watchlist": [{"ticker": "WATCH", "name": "Watch"}], "fin_score_map": {"WATCH": 3},
             "sentinel": "preserved", "today_queue_refresh_flow_candidates": True}
    settings = {"action": None, "full": True, "fail": "", "demo": False,
                "owner": " Owner@Example.invalid ", "disk": None}
    if kind not in {"empty_watch", "first", "disk", "bad_disk", "disk_no_time", "disk_failure"}:
        state.update({KEY: summary(), SIG: "fixture:WATCH,HELD,OLD", LAST: "2026-11-02 14:00",
                      OWNER: "owner@example.invalid", "portfolio_today_signal_df": summary()})
    if kind == "empty_watch":
        state["watchlist"] = []
    elif kind in {"disk", "disk_no_time", "disk_failure", "bad_disk"}:
        settings["disk"] = summary("DISK") if kind != "bad_disk" else "bad"
        settings["fail"] = "load" if kind == "disk_failure" else ""
    elif kind == "fallback":
        state[KEY] = pd.DataFrame()
        state[NONEMPTY], state[NONEMPTY_SIG] = summary("FALLBACK"), "fallback_sig"
    elif kind == "bad_cache":
        state[KEY] = "bad"
    elif kind == "stale_signature":
        state[SIG] = "old input signature"
    elif kind == "old_time":
        state[LAST] = "2026-11-02 10:00"
    elif kind == "bad_time":
        state[LAST] = "bad date"
    elif kind in {"owner_change", "demo"}:
        state[OWNER] = "other@example.invalid"
        state[NONEMPTY], state[NONEMPTY_SIG] = summary("OTHER_OWNER"), "other_sig"
        settings["disk"] = summary("OWN_DISK")
        settings["demo"] = kind == "demo"
    elif kind in {"clear", "clear_failure"}:
        settings["action"] = "today_queue_clear_cached"
        settings["fail"] = "clear" if kind == "clear_failure" else ""
        state[NONEMPTY], state[NONEMPTY_SIG] = summary(), "old"
    if kind.startswith("refresh"):
        settings["action"] = "today_queue_run_once"
        settings["full"] = kind != "refresh_basic"
        state["today_queue_refresh_flow_candidates"] = settings["full"]
        failures = {"refresh_flow_failure": "flow", "refresh_merge_failure": "merge",
                    "refresh_compute_failure": "compute", "refresh_interrupt": "interrupt",
                    "refresh_empty": "empty", "refresh_save_failure": "save",
                    "refresh_dedupe_failure": "dedupe"}
        settings["fail"] = failures.get(kind, "")
    settings["disk_time"] = "" if kind == "disk_no_time" else "2026-11-02 13:00"
    return state, settings


def execute(source, kind, *, raw=False):
    state, settings = case(kind)
    ui = UI(state, settings["action"], settings["full"])
    disk = settings["disk"]
    original_disk = deepcopy(disk)
    computed = summary("NEW_CALC")
    computed_before = deepcopy(computed)

    @contextmanager
    def measure(*args):
        ui.record("measure_enter", *args)
        try:
            yield
        finally:
            ui.record("measure_exit", *args)

    def build_items(items):
        ui.record("build_items", items)
        return tuple(items) + (({"ticker": "HELD", "name": "Held"},) if items else ())

    def merge(items, snapshot):
        ui.record("merge", items, snapshot)
        if settings["fail"] == "merge" and snapshot["fresh"]:
            raise RuntimeError("merge unavailable")
        base = build_items(items)
        extra = ({"ticker": "NEW" if snapshot["fresh"] else "OLD", "bucket": "flow_candidate"},) if base else ()
        return base + extra, extra

    def signature(items, mode, *, logic_version):
        ui.record("signature", items, mode, logic_version=logic_version)
        return "fixture:" + ",".join(i["ticker"] for i in items)

    def snapshot(**kwargs):
        ui.record("load_snapshot", **kwargs)
        if settings["fail"] == "load":
            raise RuntimeError("load unavailable")
        return disk, "disk_sig", settings["disk_time"]

    def clear(**kwargs):
        ui.record("clear_snapshot", **kwargs)
        if settings["fail"] == "clear":
            raise RuntimeError("clear unavailable")

    def refresh(*, include_theme, force_theme_refresh, progress):
        ui.record("refresh_flow", include_theme=include_theme, force_theme_refresh=force_theme_refresh)
        progress("fixture progress")
        if settings["fail"] == "flow":
            raise RuntimeError("flow unavailable")
        return {"fresh": True}

    def calculate(*args, **kwargs):
        ui.record("calculate", *args, **kwargs)
        if settings["fail"] == "compute":
            raise RuntimeError("calculation unavailable")
        if settings["fail"] == "interrupt":
            raise StopCalculation()
        return computed.iloc[:0].copy() if settings["fail"] == "empty" else computed.copy()

    def dedupe(frame):
        ui.record("dedupe", frame)
        if settings["fail"] == "dedupe":
            raise RuntimeError("dedupe unavailable")
        return frame.drop_duplicates("티커").copy() if not frame.empty else frame.copy()

    def save(*args, **kwargs):
        ui.record("save_snapshot", *args, **kwargs)
        if settings["fail"] == "save":
            raise RuntimeError("save unavailable")

    def bind(frame):
        ui.record("bind_measurement", frame)
        frame.attrs["queue_measurement"] = {"run_id": "fixed"}
        return frame

    def stamp(frame):
        ui.record("stamp_context", frame)
        frame.attrs["portfolio_signal_context"] = {"owner": "current"}
        return frame

    env = dict(globals(), st=ui, datetime=FixedDateTime, measure=measure,
        CURRENT_USER_EMAIL=settings["owner"], IS_PUBLIC_DEMO=settings["demo"],
        TODAY_QUEUE_LOGIC_VERSION="fixture", load_fin_scores_db=lambda: {"WATCH": 3},
        financial_input_signature=lambda data: "financial", build_today_queue_signature=signature,
        build_today_queue_items=build_items, build_today_queue_items_with_flow_candidates=merge,
        get_cached_today_market_flow_snapshot=lambda: {"fresh": False},
        load_today_queue_summary_snapshot=snapshot, clear_today_queue_summary_snapshot=clear,
        refresh_today_market_flow_snapshot=refresh, get_all_summary=calculate,
        stamp_portfolio_signal_context=stamp, dedupe_dashboard_summary_df=dedupe,
        save_today_queue_summary_snapshot=save, load_price_df="price_df", load_price_frames_batch="batch",
        cache_clear=lambda fn: ui.record("cache_clear", fn),
        clear_latest_price_cache=lambda: ui.record("clear_latest"),
        enable_force_live_price_refresh=lambda: ui.record("force_quotes"),
        get_cash_available_for_dca=lambda mode: 0., get_reserve_available_for_crash_buy=lambda mode: 0.,
        build_today_market_guard=lambda *a: {"mode": "위험"})
    for name in ("render_data_basis_caption", "render_today_unified_briefing_panel", "render_today_candidate_tools"):
        env[name] = lambda *a, _name=name, **kw: ui.record(_name, *a, **kw)
    exec(compiled_prefix(source), env)
    result = error = None
    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch("stock_lab_core.performance.bind_summary_measurement", bind))
        try:
            import stock_lab_core.today_queue_session as session
        except ModuleNotFoundError:
            session = None
        if session is not None:
            stack.enter_context(patch.object(session, "datetime", FixedDateTime))
        try:
            result = env[MAIN]("test")
        except (RuntimeError, Rerun, StopCalculation) as exc:
            error = (type(exc).__name__, str(exc))
    pd.testing.assert_frame_equal(computed, computed_before, check_exact=True)
    if isinstance(disk, pd.DataFrame):
        pd.testing.assert_frame_equal(disk, original_disk, check_exact=True)
        assert disk.attrs == original_disk.attrs
    if raw:
        return ui, result, error
    attrs = {key: value.attrs for key, value in ui.session_state.items() if isinstance(value, pd.DataFrame)}
    return freeze((ui.log, ui.session_state, attrs, result, error))


CASES = ("empty_watch", "first", "cached", "disk", "disk_no_time", "bad_disk", "disk_failure",
         "fallback", "bad_cache", "stale_signature", "old_time", "bad_time", "owner_change", "demo",
         "clear", "clear_failure", "refresh", "refresh_basic", "refresh_flow_failure", "refresh_merge_failure",
         "refresh_compute_failure", "refresh_interrupt", "refresh_empty", "refresh_save_failure", "refresh_dedupe_failure")


@pytest.mark.parametrize("kind", CASES)
def test_cache_refresh_contract_and_unchanged_paths_match(sources, kind):
    from stock_lab_core.today_queue_session import STALE_KEY, CLEARED_OWNERS_KEY

    unchanged = {"empty_watch", "cached", "old_time", "bad_time", "refresh",
                 "refresh_flow_failure", "refresh_merge_failure", "refresh_save_failure", "refresh_dedupe_failure"}
    if kind in unchanged:
        assert execute(sources[0], kind) == execute(sources[1], kind)
        return
    ui, result, error = execute(sources[1], kind, raw=True)
    state = ui.session_state
    assert state["sentinel"] == "preserved"
    assert state["watchlist"] == [{"ticker": "WATCH", "name": "Watch"}]
    events = [entry[0] for entry in ui.log]
    expected_error = {"disk_failure": "RuntimeError", "clear": "Rerun", "clear_failure": "RuntimeError",
                      "refresh_compute_failure": "RuntimeError", "refresh_interrupt": "StopCalculation"}.get(kind)
    assert (error[0] if error else None) == expected_error
    if kind in {"clear", "clear_failure"}:
        assert all(key not in state for key in (KEY, SIG, LAST, NONEMPTY, NONEMPTY_SIG, "portfolio_today_signal_df"))
        assert "owner@example.invalid" in state[CLEARED_OWNERS_KEY]
        assert "clear_snapshot" in events
    elif kind in {"disk", "disk_no_time", "fallback", "stale_signature", "owner_change", "demo"}:
        assert not state[KEY].empty and state[STALE_KEY]
        assert "portfolio_signal_context" not in state[KEY].attrs
        assert "portfolio_today_signal_df" not in state
        assert state[KEY].iloc[0]["저장당시게이트상태"] == "방어우선"
        assert state[KEY].iloc[0]["게이트상태"] == "데이터확인"
        assert "calculate" not in events and "save_snapshot" not in events
    elif kind in {"first", "bad_disk", "bad_cache"}:
        assert state[KEY].empty and "calculate" not in events
    elif kind == "refresh_basic":
        assert state[KEY].iloc[0]["티커"] == "NEW_CALC"
        assert STALE_KEY not in state and "save_snapshot" in events
    elif kind in {"refresh_compute_failure", "refresh_interrupt", "refresh_empty"}:
        assert "calculate" in events and "save_snapshot" not in events
        assert state[NONEMPTY].iloc[0]["티커"] == "WATCH"


def test_calculation_and_refresh_blocks_remain_syntax_identical(sources):
    before = ast.parse(sources[0])
    after = ast.parse(sources[1])
    old = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == MAIN)
    calc = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == "_calculate_fresh_today_summary")
    branch = next(n for n in old.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "run_summary")
    spinner = next(n for n in branch.body if isinstance(n, ast.With))
    dump = lambda body: ast.dump(ast.Module(body=body, type_ignores=[]))
    assert dump(spinner.body) == dump(calc.body[:-1])
    module = ast.parse((ROOT / "stock_lab_core/today_queue_session.py").read_text(encoding="utf8"))
    functions = {n.name: n for n in module.body if isinstance(n, ast.FunctionDef)}

    remember_start = next(i for i, n in enumerate(branch.body) if is_assignment(n, "last_run_text")) + 1
    refresh = deepcopy(functions["refresh_today_summary"].body[:-2])
    refreshed_spinner = next(n for n in refresh if isinstance(n, ast.With))
    refreshed_spinner.body = deepcopy(calc.body[:-1])
    assert dump(branch.body[:remember_start]) == dump(refresh)
    for fn in functions.values():
        assert fn.end_lineno - fn.lineno + 1 <= 50, fn.name


@pytest.mark.parametrize("previous_owner, owner", [(None, "a"), ("a", "a"), ("b", "a"), ("", "a"), ("a", "")])
def test_owner_change_never_restores_another_owners_memory(previous_owner, owner):
    from stock_lab_core.today_queue_session import restore_cached_summary

    state = {KEY: summary("MEMORY"), NONEMPTY: summary("FALLBACK"), SIG: "old",
             NONEMPTY_SIG: "old", LAST: "old", "portfolio_today_signal_df": summary("OLD"),
             "watchlist": ["unchanged"], "fin_score_map": {"keep": 3}}
    if previous_owner is not None:
        state[OWNER] = previous_owner
    calls = []

    def load(**kwargs):
        calls.append(kwargs)
        return summary("OWN_DISK"), "new", "now"

    out = restore_cached_summary(state, owner, "expected", load_today_queue_summary_snapshot=load)
    changed = previous_owner is not None and previous_owner != owner
    assert out.iloc[0]["티커"] == ("OWN_DISK" if changed else "MEMORY")
    assert calls == ([{"owner_scope": owner, "expected_signature": None}] if changed else [])
    assert state[OWNER] == owner
    assert state["watchlist"] == ["unchanged"] and state["fin_score_map"] == {"keep": 3}
    if changed:
        assert "portfolio_today_signal_df" not in state


def test_restore_and_finalize_keep_private_copies_and_save_only_fresh_nonempty():
    from stock_lab_core.today_queue_session import restore_cached_summary, finalize_summary

    disk = summary()
    state = {}
    out = restore_cached_summary(state, "a", "sig",
        load_today_queue_summary_snapshot=lambda **kw: (disk, "sig", "timestamp"))
    out.loc[0, "종목명"] = "changed"
    assert disk.loc[0, "종목명"] == "Test WATCH"
    assert state[NONEMPTY].loc[0, "종목명"] == "Test WATCH"
    saves = []
    for fresh, frame in [(False, out), (True, pd.DataFrame()), (True, out)]:
        result = finalize_summary(state, frame, "sig", fresh, "a",
            dedupe_dashboard_summary_df=lambda df: df.copy(),
            save_today_queue_summary_snapshot=lambda *a, **kw: saves.append((a, kw)))
        pd.testing.assert_frame_equal(result, frame, check_exact=True)
    assert len(saves) == 1 and saves[0][1] == {"owner_scope": "a"}
    assert saves[0][0][1:] == ("sig", "timestamp")


def test_real_streamlit_refresh_toggle_owner_switch_and_clear_match_baseline():
    from streamlit.testing.v1 import AppTest

    script = '''
import streamlit as st
from contextlib import nullcontext
from tests.test_today_queue_session_refactor import *
owner = st.selectbox("Fixture owner", ["A", "B"], key="fixture_owner")
CURRENT_USER_EMAIL, IS_PUBLIC_DEMO = owner, False
datetime = FixedDateTime
TODAY_QUEUE_LOGIC_VERSION = "fixture"
st.session_state.setdefault("watchlist", [{"ticker": "WATCH", "name": "Watch"}])
st.session_state.setdefault("fin_score_map", {"WATCH": 3})
st.session_state.setdefault("fake_price_calls", 0)
st.session_state.setdefault("fake_store", {})
def load_today_queue_summary_snapshot(*, owner_scope, expected_signature):
    return st.session_state.fake_store.get(owner_scope, (pd.DataFrame(), "", ""))
def save_today_queue_summary_snapshot(df, sig, timestamp, *, owner_scope):
    st.session_state.fake_store[owner_scope] = (df.copy(), sig, timestamp)
def clear_today_queue_summary_snapshot(*, owner_scope):
    st.session_state.fake_store.pop(owner_scope, None)
def get_all_summary(scores, mode, items, *, fresh_quotes):
    assert fresh_quotes is True
    st.session_state.fake_price_calls += 1
    return pd.DataFrame({"티커": [i["ticker"] for i in items], "종목명": owner})
def build_today_queue_items_with_flow_candidates(items, snapshot):
    extra = ({"ticker": "AUTO", "name": "Auto", "bucket": "flow_candidate"},)
    return tuple(items) + extra, extra
def build_today_queue_signature(items, mode, *, logic_version):
    return tuple(i["ticker"] for i in items)
def refresh_today_market_flow_snapshot(**kwargs):
    kwargs["progress"]("fixture progress")
    return {}
def noop(*args, **kwargs):
    pass
measure = lambda *a: nullcontext()
build_today_queue_items = tuple
get_cached_today_market_flow_snapshot = lambda: {}
load_fin_scores_db = lambda: {}
financial_input_signature = lambda d: "fixed"
clear_latest_price_cache = enable_force_live_price_refresh = cache_clear = noop
load_price_df = load_price_frames_batch = None
stamp_portfolio_signal_context = lambda df: df
dedupe_dashboard_summary_df = lambda df: df.copy()
get_cash_available_for_dca = get_reserve_available_for_crash_buy = lambda mode: 0.
build_today_market_guard = lambda *a: {"mode": "위험"}
render_data_basis_caption = render_today_unified_briefing_panel = render_today_candidate_tools = noop
source = SOURCE_EXPRESSION
exec(compiled_prefix(source), globals())
result = _render_today_queue_tab("fixture")
if result is not None:
    st.dataframe(result[0])
'''
    expressions = ['subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")',
                   '(ROOT / "app.py").read_text(encoding="utf-8-sig")']
    from stock_lab_core import today_queue_session
    with patch.object(today_queue_session, "datetime", FixedDateTime):
        old, new = [AppTest.from_string(script.replace("SOURCE_EXPRESSION", expr)).run(timeout=30)
                    for expr in expressions]

        def same():
            assert not old.exception and not new.exception
            assert [c.value for c in old.caption] == [c.value for c in new.caption]
            assert [w.value for w in old.warning] == [w.value for w in new.warning]
            assert [i.value for i in old.info] == [i.value for i in new.info]
            assert len(old.dataframe) == len(new.dataframe)
            for a, b in zip(old.dataframe, new.dataframe):
                pd.testing.assert_frame_equal(a.value, b.value, check_exact=True)
            for key in (KEY, SIG, LAST, NONEMPTY, NONEMPTY_SIG, OWNER, "fake_price_calls", "fake_store"):
                a, b = (app.session_state.filtered_state.get(key) for app in (old, new))
                assert freeze(a) == freeze(b), key

        same()
        assert new.session_state["fake_price_calls"] == 0
        for app in (old, new):
            app.button(key="today_queue_run_once").click().run()
        same()
        assert new.session_state["fake_price_calls"] == 1
        assert len(new.dataframe[0].value) == 2
        for app in (old, new):
            app.checkbox(key="today_queue_refresh_flow_candidates").uncheck().run()
        assert not new.exception
        assert [w.value for w in old.warning] == [w.value for w in new.warning]
        pd.testing.assert_frame_equal(old.dataframe[0].value,
                                      new.dataframe[0].value[old.dataframe[0].value.columns])
        assert new.dataframe[0].value["게이트상태"].eq("데이터확인").all()
        assert new.session_state["fake_price_calls"] == 1
        for app in (old, new):
            app.button(key="today_queue_run_once").click().run()
        same()
        assert new.session_state["fake_price_calls"] == 2
        assert len(new.dataframe[0].value) == 1
        for app in (old, new):
            app.selectbox(key="fixture_owner").set_value("B").run()
        same()
        assert not new.dataframe
        for app in (old, new):
            app.selectbox(key="fixture_owner").set_value("A").run()
        same()
        assert new.session_state["fake_price_calls"] == 2
        assert new.dataframe[0].value.iloc[0]["종목명"] == "A"
        for app in (old, new):
            app.button(key="today_queue_clear_cached").click().run()
        same()
        assert not new.dataframe
        assert new.session_state["fake_price_calls"] == 2
