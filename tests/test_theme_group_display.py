"""Compare table/CSV values with the retained pre-extraction renderer."""

import ast
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.formatters import finite_num


ROOT = Path(__file__).resolve().parents[1]
BASE = "612ab8c4"


@lru_cache
def original_parts():
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf-8")
    tree = ast.parse(source)
    renderer = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "render_image_theme_flow_section")
    fmt = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fmt_flow_pct")
    badges = next(n for n in renderer.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_it_state_badge" for t in n.targets))
    summary = next(n for n in renderer.body if isinstance(n, ast.With)
                   and ast.unparse(n.items[0].context_expr) == "summary_tab")
    start = next(i for i, n in enumerate(summary.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "show_group" for t in n.targets))
    return fmt, badges, summary.body[start:-1]


def original_display(frame):
    fmt, badges, block = original_parts()
    env = {"pd": pd, "finite_num": finite_num, "group_df": frame}
    exec(compile(ast.Module(body=[fmt, badges, *block], type_ignores=[]), "<frozen-renderer>", "exec"), env)
    return env["show_group"][env["_sg_show_cols"]], env


def sample(kind):
    rng = np.random.default_rng(701)
    n = 18
    frame = pd.DataFrame({
        "하위테마": [f"테마{i}" for i in range(n)], "종목수": list(range(n)),
        "대표주": [f"Fixture{i}" for i in range(n)], "구성종목": ["A, B"] * n,
        "상태": ["강세 가속", "가격부족", "새로운 상태", None, np.nan, "관찰"] * 3,
        "추격위험": ["-"] * n, "별도원자료": ["keep source"] * n,
    }, index=pd.Index([i // 2 for i in range(n)], name="원래순서"))
    for col in ["2주수익률", "1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률",
                "6개월수익률", "2주상승비율", "1개월상승비율", "상승종목비율", "가속도", "단기가속도",
                "거래량증가", "상위종목쏠림", "가격수준", "돈흐름점수"]:
        frame[col] = [np.nan, np.inf, -np.inf, 0., -0., *rng.normal(size=n-5)]
    if kind == "empty_optional":
        frame[["이전3개월수익률", "상대3개월수익률"]] = np.nan
        frame["추격위험"] = " "
    elif kind == "minimal":
        frame = frame[["하위테마", "대표주", "돈흐름점수"]]
    elif kind == "nullable":
        frame["3개월수익률"] = pd.array([pd.NA, .12] * 9, dtype="Float64")
    elif kind == "empty":
        frame = frame.iloc[:0]
    elif kind == "reversed":
        frame = frame.iloc[::-1, ::-1]
    frame.attrs = {"source_asof": "2026-11-06", "audit": "synthetic"}
    return frame


@pytest.mark.parametrize("kind", ["mixed", "empty_optional", "minimal", "nullable", "empty", "reversed"])
def test_table_and_csv_equal_frozen_renderer_without_mutating_input(kind):
    from stock_lab_core.theme_flow_view import prepare_theme_group_display

    source = sample(kind)
    before = source.copy(deep=True)
    expected, env = original_display(source)
    actual = prepare_theme_group_display(source, env["_it_state_badge"], format_pct=env["fmt_flow_pct"])
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual.attrs == expected.attrs
    assert actual.to_csv(index=False) == expected.to_csv(index=False)
    pd.testing.assert_frame_equal(source, before, check_exact=True)
    assert source.attrs == before.attrs
    if not actual.empty:
        actual.iloc[0, 0] = "edited display"
        pd.testing.assert_frame_equal(source, before, check_exact=True)


def test_renderer_changes_only_summary_preparation():
    old = ast.parse(subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf-8"))
    new = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    def renderer(tree):
        return next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "render_image_theme_flow_section")
    old, new = renderer(old), renderer(new)
    assignments = [n for n in ast.walk(new) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "show_group" for t in n.targets)]
    assert len(assignments) == 1
    assert ast.unparse(assignments[0].value) == (
        "prepare_theme_group_display(group_df, _it_state_badge, format_pct=fmt_flow_pct)")
    def replace_preparation(node):
        summary = next(n for n in node.body if isinstance(n, ast.With)
                       and ast.unparse(n.items[0].context_expr) == "summary_tab")
        start = next(i for i, n in enumerate(summary.body) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "show_group" for t in n.targets))
        summary.body[start:-1] = []
        summary.body[-1].value.args[0] = ast.Name(id="prepared_table", ctx=ast.Load())
        return ast.dump(node, include_attributes=False)
    assert replace_preparation(old) == replace_preparation(new)
