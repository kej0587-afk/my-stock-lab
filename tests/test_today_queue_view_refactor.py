"""Characterize the detail UI against the retained pre-extraction application."""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.backup import dataframe_to_csv_bytes
from stock_lab_core.formatters import normalize_ticker
from stock_lab_core.today_queue import sort_today_queue_detail_table
from tests.test_money_flow_renderer_refactor import UI as BaseUI
from tests.test_portfolio_renderer_refactor import freeze as base_freeze


ROOT = Path(__file__).resolve().parents[1]
BASE = "26da1c00a97afc6d53f52d551e9a069216d25c8d"
MAIN = "_render_today_queue_tab"
MASKS = ("execution", "wait", "overweight", "market_defense", "price_defense",
         "rapid_drop", "structure", "overheat", "data_issue", "other_caution")
CALLBACKS = ("render_today_review_export_download", "render_today_research_links_panel",
             "render_today_flow_shortlist_panel", "render_summary_signal_validation_panel",
             "render_today_candidate_tools")


def freeze(value):
    if isinstance(value, pd.Series):
        return ("series", value.to_json(orient="split", date_format="iso", double_precision=15))
    if isinstance(value, dict):
        return tuple(sorted((key, freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return base_freeze(value)


@pytest.fixture(scope="module")
def sources():
    old = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    return old, (ROOT / "app.py").read_text(encoding="utf-8-sig")


@lru_cache(maxsize=2)
def function(source):
    return next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == MAIN)


def detail_start(fn):
    for i, node in enumerate(fn.body):
        if isinstance(node, ast.If) and "candidate_focus_mask.sum()" in ast.unparse(node.test):
            return i
        if isinstance(node, ast.ImportFrom) and node.module == "stock_lab_core.today_queue_view":
            return i
    raise AssertionError("Detail section boundary not found")


@lru_cache(maxsize=2)
def compiled_section(source):
    fn = function(source)
    return compile(ast.Module(body=fn.body[detail_start(fn):], type_ignores=[]), "<queue-detail>", "exec")


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 2, 14, 30, tzinfo=timezone(timedelta(hours=9)))
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class UI(BaseUI):
    def __init__(self):
        super().__init__(None)
        self.session_state = {"sentinel": "unchanged"}

    def record(self, name, *args, **kwargs):
        self.log.append((name, freeze(args), freeze(kwargs)))

    def tabs(self, labels):
        self.record("tabs", labels)
        return [self] * len(labels)

    def expander(self, *args, **kwargs):
        self.record("expander", *args, **kwargs)
        return self


def sample(n=30):
    frame = pd.DataFrame({
        "종목명": [f"종목 {i}" for i in range(n)],
        "티커": [f"T{i}" for i in range(n)],
        "유형": "주식", "현재가": "$100.00",
        "게이트상태": [MASKS[i % len(MASKS)] for i in range(n)],
        "게이트근거": [f"기존 근거 {i}" for i in range(n)],
        "🔥기술적 타점": ["분할 매수", "추세방어", "눌림대기"] * (n // 3) + ["관망"] * (n % 3),
        "판정코드": "WAIT", "최종읽기": "관망", "📌후보등급": "A급",
        "Adj점수": np.arange(n) % 4, "R/R": np.arange(n) % 3,
        "안전상태": "GREEN", "매크로상태": "CAUTION", "데이터상태": "OK",
        "실행메모": "원계획", "1차조건": "다음 봉", "현재실행안내": "old", "현재진입조건": "old",
    })
    gates = ["실행가능", "대기/관찰", "방어우선", "데이터확인"]
    frame["게이트상태"] = [gates[i % 4] for i in range(n)]
    frame.attrs = {"portfolio_signal_context": {"owner": "offline"}, "measurement_id": "retained"}
    return frame


def masks_for(frame, *, overlapping=False):
    masks = {key: pd.Series(np.arange(len(frame)) % len(MASKS) == i, index=frame.index)
             for i, key in enumerate(MASKS)}
    if overlapping:
        masks["wait"] = pd.Series(True, index=frame.index)
    return masks


def run(source, frame, *, masks=None, watch_items=None, ui=None):
    ui = ui or UI()
    masks = masks_for(frame) if masks is None else masks
    watch_items = watch_items if watch_items is not None else [
        {"ticker": t, "asset_class": "us_stock"} for t in frame.get("티커", [])]
    shortlist = pd.DataFrame({"티커": ["FLOW"], "점수": [42.]})
    holdings = pd.DataFrame({"티커": ["HELD"], "수량": [12.]})
    guard = {"mode": "위험", "kr_stats": {"mode": "방어"}}
    env = dict(globals(), st=ui, datetime=FixedDateTime, summary_df=frame,
        queue_masks=masks, flow_shortlist_df=shortlist, holdings_table=holdings,
        market_guard=guard, watch_items=watch_items,
        candidate_focus_mask=masks["execution"] | masks["wait"])
    env.update({key + "_mask": mask for key, mask in masks.items()})
    for name in CALLBACKS:
        env[name] = lambda *a, _name=name, **kw: ui.record(_name, *a, **kw)

    def snapshot():
        ui.record("get_cached_today_market_flow_snapshot")
        return {"source": "unchanged snapshot"}

    env["get_cached_today_market_flow_snapshot"] = snapshot
    originals = [deepcopy(v) for v in (frame, masks, watch_items, shortlist, holdings, guard)]
    # Freeze both the old nested renderer and the extracted CSV filename clock.
    from unittest.mock import patch
    try:
        import stock_lab_core.today_queue_view as view
    except ModuleNotFoundError:
        view = None
    if view is None:
        exec(compiled_section(source), env)
    else:
        with patch.object(view, "datetime", FixedDateTime):
            exec(compiled_section(source), env)
    for before, after in zip(originals, (frame, masks, watch_items, shortlist, holdings, guard)):
        if isinstance(before, pd.DataFrame):
            pd.testing.assert_frame_equal(before, after, check_exact=True)
            assert before.attrs == after.attrs
        else:
            assert freeze(before) == freeze(after)
    assert ui.session_state == {"sentinel": "unchanged"}
    return ui.log


@pytest.mark.parametrize("kind", ["normal", "empty", "minimal", "no_ticker", "states", "noncontiguous",
                                  "duplicate_index", "string_index", "overlap", "wait_only", "no_class", "no_raw_plan"])
def test_ui_tables_order_csv_keys_callbacks_and_inputs_are_unchanged(sources, kind):
    frame = sample()
    if kind == "empty":
        frame = frame.iloc[:0].copy()
    elif kind == "minimal":
        frame = frame[["종목명", "티커"]]
    elif kind == "no_ticker":
        frame = frame.drop(columns="티커")
    elif kind == "states":
        frame.loc[0, ["매크로상태", "데이터상태"]] = ["RISK", "ERROR"]
    elif kind == "noncontiguous":
        frame.index = np.arange(len(frame)) * 3 + 7
    elif kind == "duplicate_index":
        frame.index = np.arange(len(frame)) // 2
    elif kind == "string_index":
        frame.index = [f"row{i}" for i in range(len(frame))]
    elif kind == "no_raw_plan":
        frame = frame.drop(columns=["실행메모", "1차조건"])
    masks = masks_for(frame, overlapping=kind == "overlap")
    if kind == "wait_only":
        masks["wait"] |= masks["execution"]
        masks["execution"][:] = False
    opts = {"masks": masks, "watch_items": [] if kind == "no_class" else None}
    assert run(sources[0], frame, **opts) == run(sources[1], frame, **opts)


@pytest.mark.parametrize("seed", range(20))
def test_random_values_keep_risk_sorting_and_csv_bytes_identical(sources, seed):
    rng = np.random.default_rng(seed)
    frame = sample(int(rng.integers(1, 90)))
    for col in ("Adj점수", "R/R", "RR값"):
        frame[col] = rng.choice(["-", "1.50", "nan", "0", "-2", "상단 $132.05"], len(frame))
    frame["게이트상태"] = rng.choice([None, "실행가능", "대기/관찰", "방어우선", "데이터확인"], len(frame))
    frame["판정코드"] = rng.choice(["WAIT", "HARD_BLOCK_OVERWEIGHT", "DATA_ERROR"], len(frame))
    frame["안전상태"] = rng.choice(["GREEN", "RED", "YELLOW", "DATA"], len(frame))
    assert run(sources[0], frame) == run(sources[1], frame)


def test_post_calculation_gates_and_timing_boundary_are_syntax_unchanged(sources):
    old, new = map(function, sources)
    # Cache/refresh now has its own retained-baseline parity suite.
    def policy_start(fn):
        return next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "portfolio_signal_attrs" for t in n.targets))
    assert ast.dump(ast.Module(body=old.body[policy_start(old):detail_start(old)], type_ignores=[])) == ast.dump(
        ast.Module(body=new.body[policy_start(new):detail_start(new)], type_ignores=[]))
    assert ast.dump(ast.Module(body=old.decorator_list, type_ignores=[])) == ast.dump(
        ast.Module(body=new.decorator_list, type_ignores=[]))


def test_display_guidance_is_computed_once_and_never_written_to_raw_exports(sources, monkeypatch):
    from stock_lab_core import execution_readiness, today_queue_view

    original = execution_readiness.execution_guidance_fields
    calls = []

    def counted(row):
        calls.append(row["티커"])
        return original(row)

    monkeypatch.setattr(execution_readiness, "execution_guidance_fields", counted)
    monkeypatch.setattr(today_queue_view, "execution_guidance_fields", counted)
    frame = sample(85)
    before = run(sources[0], frame)
    assert len(calls) == 170
    calls.clear()
    after = run(sources[1], frame)
    assert len(calls) == 85
    assert before == after
    assert frame["현재실행안내"].eq("old").all()


def test_prepared_view_is_local_to_each_render_not_a_stale_cross_session_cache():
    from stock_lab_core.today_queue_view import prepare_detail_view

    frame = sample(3)
    first = prepare_detail_view(frame)
    frame.loc[0, "게이트상태"] = "방어우선"
    frame.loc[0, "게이트근거"] = "새로운 방어 사유"
    second = prepare_detail_view(frame)
    assert first.loc[0, "현재실행안내"] != second.loc[0, "현재실행안내"]
    assert "새로운 방어 사유" in second.loc[0, "현재실행안내"]
    assert first.attrs == second.attrs == frame.attrs
    assert frame["현재실행안내"].eq("old").all()


def test_extracted_functions_remain_small_and_have_no_io_or_session_storage():
    tree = ast.parse((ROOT / "stock_lab_core/today_queue_view.py").read_text(encoding="utf8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            assert node.end_lineno - node.lineno + 1 < 80, node.name
    assert not any(isinstance(n, ast.Attribute) and n.attr in {"session_state", "cache_data", "cache_resource"}
                   for n in ast.walk(tree))


def test_real_streamlit_tabs_downloads_and_reruns_match_baseline():
    from streamlit.testing.v1 import AppTest

    script = '''
import streamlit as st
from tests.test_today_queue_view_refactor import *
choice = st.radio("Dataset", ["all", "sparse"], key="dataset")
summary_df = sample(30 if choice == "all" else 2)
queue_masks = masks_for(summary_df)
globals().update({key + "_mask": mask for key, mask in queue_masks.items()})
candidate_focus_mask = execution_mask | wait_mask
watch_items = [{"ticker": t, "asset_class": "us_stock"} for t in summary_df["티커"]]
flow_shortlist_df = pd.DataFrame({"티커": ["FLOW"]})
holdings_table = pd.DataFrame({"티커": ["HELD"]})
market_guard = {"mode": "위험"}
st.session_state["callback_order"] = []
def callback(name):
    def record(*args, **kwargs):
        st.session_state["callback_order"].append(name)
    return record
for name in CALLBACKS:
    globals()[name] = callback(name)
def get_cached_today_market_flow_snapshot():
    return {}
source = SOURCE_EXPRESSION
exec(compiled_section(source), globals())
'''
    old_expr = 'subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")'
    new_expr = '(ROOT / "app.py").read_text(encoding="utf-8-sig")'
    old, new = [AppTest.from_string(script.replace("SOURCE_EXPRESSION", expr)).run(timeout=30)
                for expr in (old_expr, new_expr)]
    for sparse in (False, True):
        if sparse:
            old.radio(key="dataset").set_value("sparse").run()
            new.radio(key="dataset").set_value("sparse").run()
        assert not old.exception and not new.exception
        assert [t.label for t in old.tabs] == [t.label for t in new.tabs]
        assert len(new.tabs) == 12
        assert [c.value for c in old.caption] == [c.value for c in new.caption]
        assert len(old.dataframe) == len(new.dataframe) == (6 if sparse else 22)
        for a, b in zip(old.dataframe, new.dataframe):
            pd.testing.assert_frame_equal(a.value, b.value, check_exact=True)
        assert len(old.get("download_button")) == len(new.get("download_button")) == (3 if sparse else 11)
        assert old.session_state["callback_order"] == new.session_state["callback_order"] == list(CALLBACKS)
