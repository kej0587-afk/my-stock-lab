"""Selection must match the retained app, including ordering and exclusions."""
import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest


BASE = "b0194fa1"
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(None)
def original():
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT).decode("utf8")
    return next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "build_today_flow_candidate_queue_items")


def test_selection_body_is_syntax_identical():
    old = original()
    start = next(i for i, n in enumerate(old.body) if isinstance(n, ast.If))
    new = next(n for n in ast.parse((ROOT / "stock_lab_core/today_flow_queue.py").read_text("utf8")).body
               if isinstance(n, ast.FunctionDef))
    assert ast.dump(ast.Module(body=old.body[start:], type_ignores=[])) == ast.dump(ast.Module(body=new.body, type_ignores=[]))


@pytest.mark.parametrize("variant", ["normal", "empty", "none", "duplicates", "missing_score", "ties", "missing_names", "excluded"])
@pytest.mark.parametrize("limit", [0, 1, 4, 12])
@pytest.mark.parametrize("existing", [(), ({"ticker": "MSFT"},), ({"ticker": "005930.KS"}, None, {})])
def test_selection_equals_retained_app(app_module, monkeypatch, variant, limit, existing):
    app = app_module
    frame = pd.DataFrame({
        "Ticker": ["MSFT", "005930.KS", "QQQ", "SOXL", "GOOGL", "NVDA"],
        "종목명": ["Microsoft", "삼성전자", "QQQ", "SOXL", "Alphabet", "NVIDIA"],
        "등록상태": ["관심", "미등록", "미등록", "보유", "미등록", "미등록"],
        "후보군": ["회복추적", "스윙후보", "장기후보", "고점주의", "스윙후보", "회복추적"],
        "판정": ["회복", "스윙", "관망", "추격금지", "제외", "관망"],
        "돈흐름점수": [4, 8, np.nan, 10, 9, 3],
    })
    if variant == "empty": frame = frame.iloc[:0]
    elif variant == "none": frame = None
    elif variant == "duplicates": frame = pd.concat([frame, frame.iloc[[1, 0]]], ignore_index=True)
    elif variant == "missing_score": frame = frame.drop(columns="돈흐름점수")
    elif variant == "ties": frame["돈흐름점수"] = 8
    elif variant == "missing_names": frame = frame.drop(columns="종목명")
    elif variant == "excluded": frame["판정"], frame["후보군"] = "제외", ""
    before = deepcopy(frame)
    monkeypatch.setattr(app, "build_today_flow_shortlist_df", lambda _: frame)
    env = dict(vars(app))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[deepcopy(original())], type_ignores=[])), "<retained-flow-queue>", "exec"), env)
    expected = env["build_today_flow_candidate_queue_items"]({}, existing, limit)
    assert app.build_today_flow_candidate_queue_items({}, existing, limit) == expected
    if frame is not None: pd.testing.assert_frame_equal(frame, before)


def test_lookup_failure_still_returns_empty(app_module, monkeypatch):
    def fail(_): raise RuntimeError("provider unavailable")
    monkeypatch.setattr(app_module, "build_today_flow_shortlist_df", fail)
    assert app_module.build_today_flow_candidate_queue_items({}) == ()
