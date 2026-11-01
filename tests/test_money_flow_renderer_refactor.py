"""Golden UI calls/figures/state against the pre-extraction 594-line renderer."""

import ast
from pathlib import Path
import subprocess

import pandas as pd
import plotly.graph_objects as go
import pytest
import streamlit


ROOT = Path(__file__).resolve().parents[1]
BASE = "a4c4f5a1"
MAIN = "render_money_flow_etf_section"
HELPERS = ("_render_money_flow_etf_leaders", "_render_money_flow_etf_charts", "_render_money_flow_etf_distributions")


@pytest.fixture(scope="module")
def sources():
    try:
        old = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Golden renderer requires the retained baseline Git revision")
    return old, (ROOT / "app.py").read_text(encoding="utf-8-sig")


def freeze(value):
    if isinstance(value, pd.DataFrame):
        return ("frame", value.to_json(orient="split", double_precision=15, force_ascii=False))
    if isinstance(value, go.Figure):
        return ("figure", value.to_json())
    if isinstance(value, dict):
        return tuple(sorted((key, freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


class UI:
    column_config = streamlit.column_config

    def __init__(self, group):
        self.group, self.log = group, []
        self.session_state = {"money_flow_prev_leader_ticker": "OLD"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def record(self, name, *args, **kwargs):
        self.log.append((name, freeze(args), freeze(kwargs)))

    def columns(self, spec):
        self.record("columns", spec)
        return [self] * (spec if isinstance(spec, int) else len(spec))

    def spinner(self, *args, **kwargs):
        self.record("spinner", *args, **kwargs)
        return self

    def radio(self, *args, **kwargs):
        self.record("radio", *args, **kwargs)
        return self.group

    def plotly_chart(self, *args, **kwargs):
        self.record("plotly_chart", *args, **kwargs)
        return {"selection": {"points": []}}

    def __getattr__(self, name):
        return lambda *a, **k: self.record(name, *a, **k)


def sample():
    from stock_lab_core.money_flow import _compute_ticker_metrics
    from tests.fixtures_price import make_price_df
    metrics = _compute_ticker_metrics(make_price_df())
    return pd.DataFrame([dict(metrics, **{"구분": group, "섹터": name, "Ticker": symbol,
        "ETF 이름": name + " ETF", "돈흐름점수": 30 - i, "스윙점수": 10,
        "가격수준": .5, "상태": "주도 유지", "히트맵크기": 10})
        for i, (group, name, symbol) in enumerate([
            ("미국 섹터", "반도체", "SOXX"), ("한국 섹터", "한국 시장", "069500.KS"),
            ("글로벌", "금", "GLD"), ("매크로", "변동성", "^VIX"), ("월배당 ETF", "단기채", "SGOV")])])


def run(source, app, frame, group, *, ready=True):
    ui = UI(group)
    namespace = dict(vars(app), st=ui, holdings_table=pd.DataFrame({"티커": ["SOXX"]}),
        should_run_heavy_analysis=lambda *a, **k: ready,
        calculate_money_flow_df=lambda: frame.copy(deep=True),
        get_plotly_selected_ticker=lambda event: "SOXX")
    for name in ("render_flow_score_breakdown", "render_money_flow_composition_panel", "render_rotation_panel"):
        namespace[name] = lambda *a, _name=name, **k: ui.record(_name, *a, **k)
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
             and node.name in (MAIN, *HELPERS)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<renderer>", "exec"), namespace)
    namespace[MAIN]()
    return ui.log, ui.session_state


@pytest.mark.parametrize("group", ["전체", "미국 섹터", "한국 섹터", "매크로"])
def test_renderer_extraction_preserves_all_ui_values_figures_keys_and_selection(sources, app_module, group):
    frame = sample()
    before = frame.copy(deep=True)
    old, new = (run(source, app_module, frame, group) for source in sources)
    assert freeze(old) == freeze(new)
    pd.testing.assert_frame_equal(frame, before, check_exact=True)


@pytest.mark.parametrize("ready", [True, False])
def test_early_return_paths_are_unchanged(sources, app_module, ready):
    assert run(sources[0], app_module, pd.DataFrame(), "전체", ready=ready) == run(
        sources[1], app_module, pd.DataFrame(), "전체", ready=ready)


def test_extracted_blocks_are_syntax_identical_to_the_original_statements(sources):
    old = next(node for node in ast.parse(sources[0]).body if isinstance(node, ast.FunctionDef) and node.name == MAIN)
    new = {node.name: node for node in ast.parse(sources[1]).body if isinstance(node, ast.FunctionDef) and node.name in HELPERS}
    body = [statement for name in HELPERS for statement in new[name].body]
    start = next(i for i, statement in enumerate(old.body) if isinstance(statement, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "top_us" for t in statement.targets))
    assert ast.dump(ast.Module(body=old.body[start:], type_ignores=[]), include_attributes=False) == ast.dump(
        ast.Module(body=body, type_ignores=[]), include_attributes=False)
    current = next(node for node in ast.parse(sources[1]).body if isinstance(node, ast.FunctionDef) and node.name == MAIN)
    assert current.end_lineno - current.lineno + 1 <= 240
