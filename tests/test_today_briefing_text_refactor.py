"""Original briefing wording/priority from retained app, including pending views."""
import ast
from copy import deepcopy
from functools import lru_cache
import itertools
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from stock_lab_core.today_briefing_text import build_briefing_summary_text

BASE = "e641bd0e3eeaa1498b9b0da86af68d0441f9264c"
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(None)
def old_nodes():
    source = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT).decode("utf8")
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
              and n.name == "render_today_unified_briefing_panel")
    start = next(i for i,n in enumerate(fn.body) if isinstance(n,ast.FunctionDef) and n.name == "_row_name_list")
    end = next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and ast.unparse(n.value.func) == "st.markdown")
    return fn.body[start:end]


def test_summary_branches_and_wording_are_syntax_identical():
    fn = next(n for n in ast.parse(Path("stock_lab_core/today_briefing_text.py").read_text('utf8')).body
              if isinstance(n,ast.FunctionDef))
    assert ast.dump(ast.Module(body=fn.body[:-1],type_ignores=[])) == ast.dump(ast.Module(body=old_nodes(),type_ignores=[]))


@pytest.mark.parametrize("pending,defensive,core,review", list(itertools.product([False, True], repeat=4)))
@pytest.mark.parametrize("variant", ["normal", "empty", "no_masks", "misaligned"])
def test_text_and_priority_match_original(app_module,pending,defensive,core,review,variant):
    df = pd.DataFrame({"종목명":[f"Example {i}" for i in range(20)],"티커":[f"T{i}" for i in range(20)]},index=range(20,40))
    buy = pd.Series([i % 2 == 0 for i in range(20)],index=df.index)
    wait = ~buy
    if variant == "empty": df = df.iloc[:0]
    if variant == "no_masks": buy = wait = None
    if variant == "misaligned": buy.index = wait.index = range(100,120)
    kwargs=dict(buyish_mask=buy,wait_mask=wait,buyish_count=2 if core else 0,market_defensive=defensive,
                core_hold_lines=["core"] if core else [],review_lines=["review"] if review else [],
                keep_lines=["keep"] if not review else [],cash_available=0 if pending else 100,
                reserve_available=50 if core else 0,pending=pending)
    template=ast.parse('''def old(df, *, buyish_mask, wait_mask, buyish_count, market_defensive,
                             core_hold_lines, review_lines, keep_lines, cash_available, reserve_available, pending):
    pass
''').body[0]
    template.body=deepcopy(old_nodes())+ast.parse('return headline, recommendation_lines').body
    env=dict(vars(app_module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[template],type_ignores=[])),"<retained-text>","exec"),env)
    before=df.copy(deep=True)
    expected=env['old'](df,**kwargs)
    assert build_briefing_summary_text(df,**kwargs)==expected
    pd.testing.assert_frame_equal(df,before)
    assert kwargs['core_hold_lines']==(["core"] if core else [])
    if pending:
        assert "종목 계산 전" in expected[0]
