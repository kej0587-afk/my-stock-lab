"""Stock table/CSV parity against the retained inline renderer, without providers."""

import ast
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.formatters import finite_num, format_currency
from tests.test_theme_group_display import original_parts


ROOT = Path(__file__).resolve().parents[1]
BASE = "340fe067"
KINDS = ["mixed", "empty_optional", "minimal", "nullable", "empty", "reversed"]


@lru_cache
def source():
    return subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf-8")


def renderer(text):
    return next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)
                and n.name == "render_image_theme_flow_section")


def stock_block(node):
    tab = next(n for n in node.body if isinstance(n, ast.With)
               and ast.unparse(n.items[0].context_expr) == "stocks_tab")
    start = next(i for i, n in enumerate(tab.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "show_stock" for t in n.targets))
    end = next(i for i in range(start + 1, len(tab.body)) if isinstance(tab.body[i], ast.Expr)
               and isinstance(tab.body[i].value, ast.Call)
               and ast.unparse(tab.body[i].value.func) == "st.dataframe")
    return tab, start, end


def reference(frame):
    fmt, badges, _ = original_parts()
    tab, start, end = stock_block(renderer(source()))
    env = dict(pd=pd, finite_num=finite_num, format_currency=format_currency, stock_view=frame)
    exec(compile(ast.Module(body=[fmt, badges, *tab.body[start:end]], type_ignores=[]),
                 "<frozen-stock-table>", "exec"), env)
    return env["show_stock"][env["_it_show_cols"]], env


def sample(kind, mode="종합"):
    n = 12
    rng = np.random.default_rng(711)
    frame = pd.DataFrame({
        "Ticker": ["005930.KS", "AAA", "000001.kq", "BBB", "CCC", "DDD"] * 2,
        "현재가": [12345.67, 12.345, 0., -1.25, np.nan, np.inf, -np.inf, None, 1., 12., 12.999, 9999.9],
        "투자유형": ["⚪ 관망", "🚀 스윙후보", "🌱 장기후보"] * 4,
        "하위테마": ["가", "나"] * 6, "종목명": [f"Fixture{i}" for i in range(n)],
        "상태": ["강세 가속", "가격부족", "새 상태", None, np.nan, "관찰"] * 2,
        "추격위험": ["-"] * n, "원자료추가열": range(n),
    }, index=pd.Index([i // 2 for i in range(n)], name="원래순서"))
    for col in ["1개월수익률", "3개월수익률", "상대3개월수익률", "6개월수익률",
                "가속도", "거래량증가", "가격수준", "돈흐름점수"]:
        frame[col] = [np.nan, np.inf, -np.inf, 0., -0., *rng.normal(size=n-5)]
    frame = frame.sort_values({"종합": "돈흐름점수", "스윙": "가속도", "장기": "3개월수익률"}[mode],
                              ascending=False, na_position="last")
    if kind == "empty_optional":
        frame["상대3개월수익률"] = np.nan
        frame["추격위험"] = " "
    elif kind == "minimal":
        frame = frame[["Ticker", "현재가", "종목명"]]
    elif kind == "nullable":
        frame["현재가"] = pd.array([pd.NA, 12.345] * 6, dtype="Float64")
        frame["3개월수익률"] = pd.array([pd.NA, .12] * 6, dtype="Float64")
    elif kind == "empty":
        frame = frame.iloc[:0]
    elif kind == "reversed":
        frame = frame.iloc[::-1, ::-1]
    frame.attrs = {"reference_date": "2026-11-06", "mode": mode}
    return frame


@pytest.mark.parametrize("mode", ["종합", "스윙", "장기"])
@pytest.mark.parametrize("kind", KINDS)
def test_exact_display_csv_and_source_preservation(kind, mode):
    from stock_lab_core.theme_flow_view import prepare_theme_stock_display

    frame = sample(kind, mode)
    before = frame.copy(deep=True)
    expected, env = reference(frame)
    actual = prepare_theme_stock_display(frame, env["_it_state_badge"], format_pct=env["fmt_flow_pct"])
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual.attrs == expected.attrs
    assert actual.to_csv(index=False) == expected.to_csv(index=False)
    if not actual.empty:
        actual.iloc[0, 0] = "edited display"
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    assert frame.attrs == before.attrs


def test_only_stock_table_preparation_changes_in_renderer():
    from tests.test_theme_selection import inline_theme_selection
    old, new = renderer(source()), renderer((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    new = inline_theme_selection(new)
    tab, start, end = stock_block(new)
    assert end == start + 1
    assert ast.unparse(tab.body[start].value) == (
        "prepare_theme_stock_display(stock_view, _it_state_badge, format_pct=fmt_flow_pct)")
    for node in (old, new):
        tab, start, end = stock_block(node)
        tab.body[end].value.args[0] = ast.Name(id="prepared_stock_table", ctx=ast.Load())
        del tab.body[start:end]
    assert ast.dump(old, include_attributes=False) == ast.dump(new, include_attributes=False)


@pytest.mark.parametrize("retained_old_module", [False, True])
def test_stateless_import_guard_recovers_old_module_only_when_needed(monkeypatch, retained_old_module):
    import importlib
    import stock_lab_core.theme_flow_view as module

    if retained_old_module:
        monkeypatch.delattr(module, "prepare_theme_stock_display")
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    start = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.Import)
                 and any(a.asname == "_theme_flow_view" for a in n.names))
    real_reload, calls = importlib.reload, []
    def reload(target):
        assert target is module
        calls.append(target.__name__)
        return real_reload(target)
    monkeypatch.setattr(importlib, "reload", reload)
    env = {}
    exec(compile(ast.Module(body=tree.body[start:start+3], type_ignores=[]), "<display-import>", "exec"), env)
    assert len(calls) == int(retained_old_module)
    assert env["prepare_theme_stock_display"] is module.prepare_theme_stock_display
