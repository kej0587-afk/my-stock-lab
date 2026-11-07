"""Widget events/state and immutable source parity for theme UI extraction."""
import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = '9cd5f6a2'
RENDERER = 'render_image_theme_flow_section'
HELPER = '_render_image_theme_selection'


@lru_cache
def sources():
    return (subprocess.check_output(['git', 'show', BASE+':app.py'], cwd=ROOT, encoding='utf-8-sig'),
            (ROOT/'app.py').read_text(encoding='utf-8-sig'))


def functions(source):
    return {n.name:n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


def inline_theme_selection(node):
    """Restore just the tested helper call for earlier immutable renderer guards."""
    node = deepcopy(node)
    helper = functions(sources()[1])[HELPER]
    result = []
    for statement in node.body:
        if (isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name) and statement.value.func.id == HELPER):
            assert ast.unparse(statement) == 'selected_theme, selected_market = _render_image_theme_selection(themes)'
            result.extend(deepcopy(helper.body[1:-1]))  # original body without docstring/return
        else:
            result.append(statement)
    node.body = result
    return node


def test_extraction_changes_no_other_statements_or_functions():
    before, after = map(functions, sources())
    helper = after.pop(HELPER)
    assert ast.unparse(helper.body[-1]) == 'return (selected_theme, selected_market)'
    assert before.keys() == after.keys()
    after[RENDERER] = inline_theme_selection(after[RENDERER])
    assert {k:ast.dump(v) for k,v in before.items()} == {k:ast.dump(v) for k,v in after.items()}


class UI:
    def __init__(self, theme, market):
        self.events = []
        self.state = {'image_theme_flow_theme': theme, 'image_theme_flow_market': market}

    def __getattr__(self, name):
        def event(*args, **kwargs): self.events.append((name, args, kwargs))
        return event

    def columns(self, widths):
        self.events.append(('columns', widths))
        owner = self
        class Column:
            def __init__(self, i): self.i = i
            def __enter__(self): owner.events.append(('enter', self.i))
            def __exit__(self, *args): owner.events.append(('exit', self.i))
        return [Column(i) for i in range(len(widths))]

    def selectbox(self, label, options, *, format_func, key):
        self.events.append(('selectbox', label, list(options), [format_func(x) for x in options], key))
        return self.state[key]

    def radio(self, label, options, *, horizontal, key):
        self.events.append(('radio', label, options, horizontal, key))
        return self.state[key]

    def spinner(self, text):
        self.events.append(('spinner', text))
        return self.columns([1])[0]


def run(source, *, theme='Alpha', market='전체', meta=None, available=True, empty=False, lazy=False):
    nodes = functions(source)
    st = UI(theme, market)
    history = []
    def guard(*args):
        history.append(('lazy', args)); return lazy
    def load(*args):
        history.append(('load', args)); return pd.DataFrame()
    env = dict(st=st, IMAGE_THEME_META=deepcopy(meta or {}), IMAGE_THEME_FLOW_AVAILABLE=available,
               get_image_theme_names=lambda: [] if empty else ['Alpha','Beta'],
               should_run_heavy_analysis=guard, calculate_image_theme_flow_df=load)
    selected = [nodes[RENDERER]] + ([nodes[HELPER]] if HELPER in nodes else [])
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<theme-selector>', 'exec'), env)
    original_state = deepcopy(st.state)
    env[RENDERER]()
    assert st.state == original_state
    events = deepcopy(st.events)
    if HELPER in nodes and not empty:
        assert env[HELPER](['Alpha','Beta']) == (theme, market)
    return events, history, original_state


@pytest.mark.parametrize('market', ['전체','국내','해외'])
@pytest.mark.parametrize('theme', ['Alpha','Beta'])
@pytest.mark.parametrize('meta', [{}, {'Alpha':{}}, {'Alpha':{'tag':'A','desc':'설명'}},
                                  {'Alpha':{'tag':'A','desc':'설명','etf':'SPY'}, 'Beta':{'tag':'B','desc':'설명'}}])
def test_widget_formatting_keys_order_and_selection_state_identical(market, theme, meta):
    # Stop at lazy guard: fetching data is explicitly prohibited in this path.
    assert run(sources()[0], market=market, theme=theme, meta=meta) == run(
        sources()[1], market=market, theme=theme, meta=meta)


@pytest.mark.parametrize('available', [False,True])
def test_empty_theme_stops_before_widgets_and_data(available):
    old = run(sources()[0], empty=True, available=available)
    assert old == run(sources()[1], empty=True, available=available)
    assert old[1] == []


def test_lazy_enabled_loads_once_after_selection_and_keeps_empty_data_warning():
    old = run(sources()[0], lazy=True)
    assert old == run(sources()[1], lazy=True)
    assert [event[0] for event in old[1]] == ['lazy','load']
