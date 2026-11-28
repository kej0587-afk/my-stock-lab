"""Retained application body vs extracted holdings interpretation; no baselines regenerated."""
import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.today_briefing_assets import build_briefing_asset_interpretation

BASE = "b2ccd2b725fac346256b435011cc7ac7155d82da"
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(None)
def retained_nodes():
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT).decode("utf8")
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
              and n.name == "render_today_unified_briefing_panel")
    start = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                 and ast.unparse(n.targets[0]) == "watch_meta")
    end = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.FunctionDef) and n.name == "_row_name_list")
    mask = next(n for n in fn.body if isinstance(n, ast.FunctionDef) and n.name == "_mask_at")
    return [mask, *fn.body[start:end]]


def retained(app):
    signature = ast.parse('''def old(df, held_meta, watch_items, *, hard_block_mask,
                       caution_mask, context_ok, market_defensive, safe_float):
    pass
''').body[0]
    signature.body = deepcopy(retained_nodes()) + ast.parse(
        'return (review_lines, core_hold_lines, keep_lines, no_add_lines, unknown_lines, asset_interpretation_rows)').body
    env = dict(vars(app))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[signature], type_ignores=[])), "<retained-briefing>", "exec"), env)
    return env["old"]


def test_extracted_branch_bodies_are_syntax_identical_to_retained():
    source = Path("stock_lab_core/today_briefing_assets.py").read_text(encoding="utf8")
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef))
    assert ast.dump(ast.Module(body=fn.body[:-1], type_ignores=[])) == ast.dump(
        ast.Module(body=retained_nodes(), type_ignores=[]))


def inputs(app, variant):
    names = ["S&P500", "나스닥100", "Plain equity", "TDF 2045", "SOXL 3X",
             "QLD", "Bitcoin", "Sector", "Gold", "Unknown"] * 2
    rows, meta, items = [], {}, []
    for i, name in enumerate(names):
        ticker = f"SYN{i}"
        rows.append({"티커": ticker, "종목명": name, "현재가": 80. + i,
                     "내손익률": [-20., -15., -10., 0., np.nan][i % 5],
                     "게이트상태": "방어우선", "게이트근거": "시장방어", "R/R": .19,
                     "🔥기술적 타점": ["강한 분할추매", "추세훼손", "하드차단", "100% 적립"][i % 4],
                     "판정코드": "HARD_BLOCK" if i % 6 == 0 else "WAIT"})
        key = app.normalize_ticker(ticker)
        meta[key] = {"매입가": 100., "현재비중": 10., "목표비중": [5., 10., 20.][i % 3]}
        items.append({"ticker": ticker, "bucket": ["core", "leverage", "satellite"][i % 3], "asset_class": "equity"})
    frame = pd.DataFrame(rows, index=np.arange(20) * 3 + 7)
    hard = pd.Series([i % 7 == 0 for i in range(20)], index=frame.index)
    caution = pd.Series([i % 3 == 0 for i in range(20)], index=frame.index)
    if variant == "empty": frame = frame.iloc[:0]
    if variant == "no_holdings": meta = {}
    if variant == "no_watch": items = []
    if variant == "missing_masks": hard = caution = None
    if variant == "misaligned_masks": hard.index = caution.index = range(20)
    if variant == "missing_values":
        frame["현재가"] = np.nan
        frame["내손익률"] = np.nan
        meta = {k: {} for k in meta}
    if variant == "formatted_values":
        frame["현재가"] = "$1,000.0"
        frame["내손익률"] = "(10%)"
    if variant == "unmatched_rows":
        frame["티커"] = "NOTHELD"
    frame.attrs["preserve"] = {"input": [1, 2]}
    return frame, meta, items, hard, caution


@pytest.mark.parametrize("variant", ["normal", "empty", "no_holdings", "no_watch", "missing_masks",
                                      "misaligned_masks", "missing_values", "formatted_values", "unmatched_rows"])
@pytest.mark.parametrize("defensive,matching", [(False, True), (True, True), (True, False)])
def test_fixed_twenty_assets_keep_every_reason_and_row_unchanged(app_module, variant, defensive, matching):
    frame, meta, items, hard, caution = inputs(app_module, variant)
    before = deepcopy((frame, meta, items, hard, caution))
    kwargs = dict(hard_block_mask=hard, caution_mask=caution, context_ok=matching,
                  market_defensive=defensive, safe_float=app_module.safe_float)
    previous = retained(app_module)(frame, meta, items, **kwargs)
    current = build_briefing_asset_interpretation(frame, meta, items, **kwargs)
    assert current == previous
    pd.testing.assert_frame_equal(frame, before[0])
    assert meta == before[1] and items == before[2] and frame.attrs == before[0].attrs
    for value, original in zip((hard, caution), before[3:]):
        if value is not None:
            pd.testing.assert_series_equal(value, original)
    current[0].append("caller edit")
    assert build_briefing_asset_interpretation(frame, meta, items, **kwargs) == previous
