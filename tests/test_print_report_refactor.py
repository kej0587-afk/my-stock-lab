"""Characterize the print report against the retained, pre-refactor revision."""

import ast
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import subprocess
from unittest.mock import patch

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytest

from stock_lab_core.asset_classifier import resolve_effective_investment_bucket
from stock_lab_core.formatters import (
    clean_bool, format_report_money, format_report_pct, format_report_ratio,
    is_kr_listed, normalize_bucket, report_num, sanitize_ticker_value,
)
from stock_lab_core.portfolio import append_cash_rows, calc_pnl_krw_from_row, calc_reserve_summary
from tests.test_money_flow_renderer_refactor import UI as BaseUI
from tests.test_portfolio_renderer_refactor import freeze


ROOT = Path(__file__).resolve().parents[1]
BASE = "455fc34c3ecf44faffdd9ef1313423ccc14f5c73"
MAIN = "render_print_report_v2"


@pytest.fixture(scope="module")
def sources():
    old = subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8")
    return old, (ROOT / "app.py").read_text(encoding="utf-8-sig")


@lru_cache(maxsize=2)
def compiled_renderer(source):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == MAIN)
    return compile(ast.Module(body=[node], type_ignores=[]), "<print-report>", "exec")


class Rerun(BaseException):
    pass


class UI(BaseUI):
    def __init__(self, state, close=False):
        super().__init__(None)
        self.session_state = deepcopy(state)
        self.sidebar = self
        self.close = close

    def record(self, name, *args, **kwargs):
        self.log.append((name, freeze(args), freeze(kwargs)))

    def button(self, *args, **kwargs):
        self.record("button", *args, **kwargs)
        return self.close

    def rerun(self):
        self.record("rerun")
        raise Rerun()


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 2, 11, 0, tzinfo=tz)


def holdings():
    return pd.DataFrame([
        {"자산명": name, "티커": ticker, "bucket": bucket, "asset_class": asset_class,
         "운용대상": active, "현재가": price, "매입가": average, "보유량": quantity,
         "목표비중": target, "현재비중": weight, "원화환산": value,
         "수익률": profit, "평가손익": value * profit, "기술적타점": "fallback"}
        for name, ticker, bucket, asset_class, active, price, average, quantity, target, weight, value, profit in [
            ("국내", "379810.KS", "core", "us_etf_nasdaq", True, 10000, 11000, 20, 40, 30, 200000, -.1),
            ("US", "MSFT", "core", "us_stock", "true", 100, 90, 2, 30, 20, 280000, .1),
            ("Leveraged", "SOXL", "leverage", "us_etf_nasdaq", True, 85, 100, 1, 10, 15, 119000, -.15),
            ("Satellite", "ABC", "satellite", "us_stock", True, 1000, 900, 1, 10, 5, 1400000, .1),
            ("Reserve", "SGOV", "reserve", "us_etf_other", True, 100, 100, 1, 5, 5, 140000, 0),
            ("Inactive", "DEF", "core", "us_stock", False, 10, 10, 1, 5, 5, 14000, 0),
        ]
    ])


def monthly_frame():
    return pd.DataFrame({"month_label": ["2026-09", "2026-10"],
        "evaluated_value": [1900000., 2000000.], "total_invested": [2000000., 2000000.],
        "cum_profit": [-100000., 0.], "cum_return_pct": [-5., 0.], "dividend": [120., 200.]})


def run(source, frame, *, mode="normal", redistribute=True, monthly=750000, fx=1400., close=False):
    state = {"rebcalc_monthly": monthly, "rebcalc_carryover": 10000 if monthly else 0,
        "rebcalc_accum": {"MSFT": 1500., "SOXL": 400.}, "rebcalc_redistribute": redistribute,
        "_ticker_signal_cache": {"MSFT": "blocked", "SOXL": "small"}}
    ui = UI(state, close)
    before = frame.copy(deep=True)
    cash = 0 if mode == "empty" else 1000

    def multiplier(signal, bucket, *, dip_level):
        ui.record("signal_multiplier", signal, bucket, dip_level=dip_level)
        if mode == "multiplier_failure":
            raise ValueError("fixture")
        return {"blocked": 0., "small": .5}.get(signal, 2. if bucket == "core" else 1.)

    def analysis(*args, **kwargs):
        ui.record("analysis", *args, **kwargs)
        if mode == "analysis_failure":
            raise ValueError("fixture analysis unavailable")
        return ({"risk_grade": "주의", "risk_index": 50., "portfolio_vol": 20.,
                 "portfolio_mdd": -15., "top3_weight": 65.},
            pd.DataFrame({"자산명": ["US"], "원화환산": [280000.], "MDD": [-15.]}),
            pd.DataFrame({"항목": ["위험"], "내용": ["fixture"]}),
            pd.DataFrame(), pd.Series(dtype=float), pd.DataFrame())

    def prepare_monthly(frame):
        ui.record("prepare_monthly", frame)
        if mode == "monthly_failure":
            raise ValueError("fixture monthly unavailable")
        if mode in {"no_monthly", "empty"}:
            return pd.DataFrame()
        result = monthly_frame()
        if mode == "missing_monthly_column":
            result = result.drop(columns="cum_profit")
        if mode == "no_dividend":
            result = result.drop(columns="dividend")
        return result

    def benchmark(frame, spec):
        ui.record("benchmark", frame, spec)
        if mode == "benchmark_failure":
            raise ValueError("fixture benchmark unavailable")
        if mode == "no_benchmark":
            return pd.DataFrame()
        return pd.DataFrame({"구분": ["내 기간수익률", "S&P500"],
            "month_label": ["2026-10", "2026-10"], "수익률_pct": [0., 1.]})

    namespace = dict(globals(), st=ui, datetime=FixedDateTime,
        KST=timezone(timedelta(hours=9)), holdings_table=frame,
        portfolio_summary={"current_asset": 2000000., "stock_value": 1900000.,
            "cash_value": 100000., "cum_profit": -5000., "cum_return": -.25, "total_dividend": 320.},
        krw_cash=cash, usd_cash=0, usdkrw=fx, reserve_target_weight=10., monthly_logs_df=monthly_frame(),
        sanitize_asset_name=lambda name, ticker: str(name or ticker), _rebcalc_signal_multiplier=multiplier,
        build_portfolio_analysis_report=analysis, get_portfolio_analysis_start_date=lambda _: "2026-09-01",
        prepare_monthly_performance_df=prepare_monthly, build_benchmark_return_df=benchmark,
        get_current_blended_benchmark_spec=lambda: {"fixture": 1.})
    exec(compiled_renderer(source), namespace)
    with ExitStack() as stack:
        # The view owns its clock after extraction, not the app's global clock.
        if (ROOT / "stock_lab_core/print_report_view.py").exists():
            stack.enter_context(patch("stock_lab_core.print_report_view.datetime", FixedDateTime))
        try:
            namespace[MAIN]()
        except Rerun:
            pass
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    if not close:
        assert ui.session_state == state
    return ui.log, ui.session_state


@pytest.mark.parametrize("mode", ["normal", "empty", "analysis_failure", "monthly_failure",
    "no_monthly", "missing_monthly_column", "no_dividend", "benchmark_failure", "no_benchmark", "multiplier_failure"])
@pytest.mark.parametrize("redistribute", [False, True])
def test_every_table_chart_metric_callback_and_input_is_preserved(sources, mode, redistribute):
    frame = pd.DataFrame() if mode == "empty" else holdings()
    assert run(sources[0], frame, mode=mode, redistribute=redistribute) == run(
        sources[1], frame, mode=mode, redistribute=redistribute)


@pytest.mark.parametrize("monthly,fx", [(0., 1400.), (-100., 1400.), (1., 1400.), (750000., 0.), (750000., np.nan)])
def test_zero_small_budget_and_missing_fx_preserve_existing_behavior(sources, monthly, fx):
    assert run(sources[0], holdings(), monthly=monthly, fx=fx) == run(sources[1], holdings(), monthly=monthly, fx=fx)


def test_print_mode_exit_preserves_state_and_stops_work(sources):
    old, new = (run(source, holdings(), close=True) for source in sources)
    assert old == new
    assert new[1]["print_mode_toggle_final"] is False
    assert not any(name in {"analysis", "signal_multiplier", "benchmark"} for name, *_ in new[0])


@pytest.mark.parametrize("kind", ["no_target", "rebalance_target", "all_inactive"])
def test_plan_filter_and_target_column_priority(sources, kind):
    frame = holdings()
    if kind == "no_target":
        frame = frame.drop(columns="목표비중")
    elif kind == "rebalance_target":
        frame["리밸런싱목표비중"] = [0., 50., 20., 30., 0., 0.]
    elif kind == "all_inactive":
        frame["운용대상"] = False
    assert run(sources[0], frame) == run(sources[1], frame)


def test_reserve_only_portfolio_no_longer_loses_columns_on_empty_boolean_filter(sources):
    frame = holdings().query("bucket == 'reserve'")
    with pytest.raises(KeyError, match="목표비중"):
        run(sources[0], frame)
    log, _ = run(sources[1], frame)
    assert any(name == "info" and "운용 대상 자산이 없습니다" in str(args) for name, args, _ in log)
    assert not any(name == "signal_multiplier" for name, *_ in log)


def test_active_holdings_are_prepared_once_per_render_and_not_cached_between_runs(sources):
    from stock_lab_core.print_report_data import active_plan_rows

    with patch("stock_lab_core.print_report_view.active_plan_rows", wraps=active_plan_rows) as prepare:
        first = run(sources[1], holdings())
        assert prepare.call_count == 1
        changed = holdings()
        changed["목표비중"] = 0.
        second = run(sources[1], changed)
        assert prepare.call_count == 2
    assert first != second
    assert second == run(sources[0], changed)


def test_moved_helper_bodies_are_unchanged_except_explicit_inputs_and_empty_guard(sources):
    root = next(n for n in ast.parse(sources[0]).body if isinstance(n, ast.FunctionDef) and n.name == MAIN)
    moved = {}
    for filename in ("print_report_data.py", "print_report_view.py"):
        for node in ast.parse((ROOT / "stock_lab_core" / filename).read_text(encoding="utf8")).body:
            if isinstance(node, ast.FunctionDef):
                moved[node.name] = node
                assert node.end_lineno - node.lineno + 1 <= 165

    class ExplicitInputs(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == "_rebcalc_signal_multiplier":
                return ast.copy_location(ast.Name(id="signal_multiplier", ctx=node.ctx), node)
            return node

        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "st" and node.attr == "session_state":
                return ast.copy_location(ast.Name(id="state", ctx=node.ctx), node)
            return self.generic_visit(node)

    for old in (node for node in root.body if isinstance(node, ast.FunctionDef)):
        body = deepcopy(old.body)
        new_body = deepcopy(moved[old.name[1:]].body)
        if old.name.startswith("_build_"):
            body = [statement for statement in body if not (
                isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name) and statement.value.func.id == "_active_plan_rows")]
        if old.name == "_active_plan_rows":
            # Sole intentional behavioral change: preserve columns after reserve/cash exclusion.
            guard = ast.parse("if df.empty:\n    return df").body[0]
            matching = [i for i, node in enumerate(new_body) if ast.dump(node) == ast.dump(guard)]
            assert len(matching) == 1
            new_body.pop(matching[0])
        if old.name in {"_build_monthly_plan_report", "_build_total_needed_shares_report"}:
            body = [ExplicitInputs().visit(statement) for statement in body]
        assert ast.dump(ast.Module(body=body, type_ignores=[])) == ast.dump(
            ast.Module(body=new_body, type_ignores=[])), old.name


@pytest.fixture(scope="module")
def original_plan_helpers(sources):
    tree = ast.parse(sources[0])
    root = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == MAIN)
    helpers = [deepcopy(n) for n in root.body if isinstance(n, ast.FunctionDef)]
    multiplier = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_rebcalc_signal_multiplier")
    namespace = dict(globals(), _num=report_num, _fmt_money=format_report_money,
        _fmt_pct=format_report_pct, _fmt_ratio=format_report_ratio,
        sanitize_asset_name=lambda name, ticker: str(name or ticker))
    exec(compile(ast.Module(body=[multiplier, *helpers], type_ignores=[]), "<baseline-helpers>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("seed", range(40))
def test_unformatted_plan_values_and_real_signal_multiplier_are_exact(original_plan_helpers, seed):
    from stock_lab_core.print_report_data import active_plan_rows, build_monthly_plan_report, build_total_needed_shares_report

    rng = np.random.default_rng(seed)
    frame = holdings()
    frame["현재가"] = rng.choice([0., np.nan, 85., 90., 95., 100., 10000.], len(frame))
    frame["목표비중"] = rng.choice([0., -1., np.nan, 10., 20., 30.], len(frame))
    frame["보유량"] = rng.uniform(0., 10., len(frame))
    if seed % 2:
        frame["리밸런싱목표비중"] = rng.uniform(1., 20., len(frame))
    state = {"rebcalc_monthly": float(rng.choice([0., -10., 1000., 750000.])),
        "rebcalc_carryover": 100., "rebcalc_accum": {"SOXL": 500.}, "rebcalc_redistribute": bool(seed % 2),
        "_ticker_signal_cache": {ticker: str(rng.choice(["분할 매수", "추세방어", "과열", "소액 1차", "-"]))
            for ticker in ["MSFT", "SOXL"]}}
    state_before = deepcopy(state)
    frame_before = frame.copy(deep=True)
    summary = {"current_asset": float(rng.uniform(0., 3000000.))}
    fx = float(rng.choice([0., np.nan, 1300., 1400.]))
    old = original_plan_helpers.copy()
    # Functions retain the namespace in which they were compiled.
    original_plan_helpers.update(holdings_table=frame, st=UI(state), portfolio_summary=summary, usdkrw=fx)
    old_monthly = old["_build_monthly_plan_report"]()
    old_needed = old["_build_total_needed_shares_report"]()
    active = active_plan_rows(frame)
    active_before = active.copy(deep=True)
    callbacks = dict(sanitize_asset_name=old["sanitize_asset_name"], signal_multiplier=old["_rebcalc_signal_multiplier"])
    new_monthly = build_monthly_plan_report(active, state, fx, **callbacks)
    new_needed = build_total_needed_shares_report(active, state, fx, summary, **callbacks)
    pd.testing.assert_frame_equal(old_monthly[0], new_monthly[0], check_exact=True)
    assert old_monthly[1] == new_monthly[1]
    pd.testing.assert_frame_equal(old_needed, new_needed, check_exact=True)
    pd.testing.assert_frame_equal(frame, frame_before, check_exact=True)
    pd.testing.assert_frame_equal(active, active_before, check_exact=True)
    assert state == state_before
