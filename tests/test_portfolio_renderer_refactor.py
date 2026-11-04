"""Renderer parity, except explicitly audited labels and true-cash corrections."""

import ast
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import subprocess
from unittest.mock import patch

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from tests.test_money_flow_renderer_refactor import UI as BaseUI, freeze as base_freeze


ROOT = Path(__file__).resolve().parents[1]
MAIN = "render_portfolio_analysis_tab"
HELPERS = ("_render_portfolio_risk_charts", "_render_portfolio_detailed_evaluation")


def approved_audit_changes(source):
    replacements = {
        "내 포트폴리오 수익률": "월별 원금대비 손익률 변화(%p)",
        "읽기 전용 분석입니다. 가격 기반 변동성, MDD, 집중도, 상관관계, 대기자금 비중을 함께 봅니다.":
            "보유자산 분석은 읽기 전용입니다. 계좌 성과 원장은 별도 저장 버튼으로만 반영합니다. 가격 기반 변동성, MDD, 집중도, 상관관계, 대기자금 비중을 함께 봅니다.",
        "%{x|%Y-%m}<br>누적수익률: %{y:.2f}%<extra></extra>": "%{x|%Y-%m}<br>첫 기록월 대비 손익률 변화: %{y:.2f}%p<extra></extra>",
        'yaxis_title="누적수익률(%)"': 'yaxis_title="가격 수익률(%) / 손익률 변화(%p)"',
        "초록선 = 첫 기록월 대비 내 실제 누적수익률 / 파란 점선 = 현재 보유 종목을 같은 시점부터 들고 있었다면의 가격 수익률 (비중 고정 가정)":
            "초록선 = 월별 원금대비 손익률의 첫 기록월 대비 차이(%p). 입출금 시점이 없어 시간가중 투자성과(TWR)가 아닙니다. 파란 점선 = 현재 비중 고정 가격 수익률(%). 두 선의 차이는 초과수익이 아닙니다.",
        "자산현황에서 분석 실행 후 다시 열면 보유종목별 기술 신호까지 붙여 포트폴리오 관리판을 보여줍니다.":
            "현재 계좌·보유 조건과 일치하는 판정이 없습니다. 오늘점검 또는 자산현황에서 다시 계산하면 연결됩니다. 이전 계좌의 판정은 사용하지 않습니다.",
        'active_val = metrics.get("active_value", 0.0)': 'cash_val = clean_float(reserve_summary.get("cash_value"), 0.0)',
        'cash_pct = (total_asset_val - active_val) / total_asset_val': 'cash_pct = cash_val / total_asset_val',
        '_active = metrics.get("active_value", 0.0)': '_cash_value = clean_float(metrics.get("reserve_summary", {}).get("cash_value"), 0.0)',
        '_cash_pct = (_total - _active) / _total': '_cash_pct = _cash_value / _total',
    }
    for old, new in replacements.items():
        assert old in source
        source = source.replace(old, new)
    head, tail = source.split("def render_portfolio_analysis_tab(", 1)
    tail = tail.replace('    period = st.selectbox(',
        '    from stock_lab_core.account_performance_view import render_account_performance\n'
        '    performance_options = dict(owner_scope=CURRENT_USER_EMAIL, monthly_logs_df=monthly_logs_df)\n'
        '    if "store" in inspect.signature(render_account_performance).parameters:\n'
        '        from stock_lab_core.account_performance_store import SupabaseAccountPerformanceStore\n'
        '        performance_options["store"] = None if IS_PUBLIC_DEMO else SupabaseAccountPerformanceStore(supabase, owner_scope=CURRENT_USER_EMAIL)\n'
        '    else:\n'
        '        st.warning("개인 원장 저장 모듈 교체 대기 · 현재는 파일 보관만 가능합니다. 앱 재시작 후 저장 연결을 다시 확인해 주세요.")\n'
        '    render_account_performance(st, **performance_options)\n'
        '    period = st.selectbox(', 1)
    # Intentional presentation change: commentary first, unchanged legacy panels folded.
    old_panels = ('    render_portfolio_decision_summary(metrics, asset_df, monthly_logs_df)\n'
                  '    render_portfolio_action_decision_panel(metrics, asset_df)')
    assert old_panels in tail
    tail = tail.replace(old_panels,
        '    holding_management = build_portfolio_action_decision_df(metrics, asset_df)\n'
        '    with st.expander("기존 위험·보유관리 상세", expanded=False):\n'
        '        render_portfolio_decision_summary(metrics, asset_df, monthly_logs_df)\n'
        '        render_portfolio_action_decision_panel(metrics, asset_df, prepared_decisions=holding_management)', 1)
    return head + "def render_portfolio_analysis_tab(" + tail


def freeze(value):
    if isinstance(value, pd.Series):
        return ("series", value.to_json(date_format="iso", double_precision=15))
    if isinstance(value, dict):
        return tuple(sorted((key, freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return str(value)
    return base_freeze(value)


class UI(BaseUI):
    def __init__(self, detail):
        super().__init__("1y")
        self.detail = detail

    def record(self, name, *args, **kwargs):
        self.log.append((name, freeze(args), freeze(kwargs)))

    def selectbox(self, *args, **kwargs):
        self.record("selectbox", *args, **kwargs)
        return "1y"

    def expander(self, *args, **kwargs):
        self.record("expander", *args, **kwargs)
        return self

    def toggle(self, *args, **kwargs):
        self.record("toggle", *args, **kwargs)
        return self.detail


class FixedDateTime(datetime):
    @classmethod
    def now(cls):
        return cls(2026, 11, 1, 10, 0)


@pytest.fixture(scope="module")
def sources():
    old = subprocess.check_output(["git", "show", "3160cd93:app.py"], cwd=ROOT, encoding="utf-8")
    return approved_audit_changes(old), (ROOT / "app.py").read_text(encoding="utf-8-sig")


def report(kind):
    index = pd.date_range("2026-01-31", periods=4, freq="ME")
    assets = pd.DataFrame({"자산명": ["Core", ""], "티커": ["AAA", "BBB"],
        "전체비중": [50., 35.], "목표비중": [35., 45.], "비중차이": [-15., 10.],
        "운용비중": [58.8, 41.2], "기간수익률": [-10., 5.], "원화환산": [500., 350.],
        "연환산변동성": [25., 15.], "MDD": [-20., -8.]})
    notes = pd.DataFrame({"항목": ["집중"], "내용": ["fixture"]})
    corr = pd.DataFrame([[1, .7], [.7, 1]], columns=["AAA", "BBB"], index=["AAA", "BBB"])
    curve = pd.Series([1., 1.1, .9, 1.2], index=index)
    contrib = assets[["자산명", "티커", "운용비중", "연환산변동성"]].assign(
        리스크기여도=[70., 30.], 비중대비리스크=[1.2, .7])
    benchmark = {"beta": 1.2, "alpha": -3., "tracking_error": 5., "info_ratio": -.6,
                 "bm_period_return": 6., "n_common_days": 120}
    metrics = {"reserve_summary": {"waiting_pct": 15., "cash_value": 150.}, "risk_color": "#ef4444", "risk_grade": "위험",
        "risk_index": 80., "portfolio_vol": 25., "portfolio_mdd": -28., "top1_weight": 50.,
        "top3_weight": 85., "portfolio_annual_return": -10., "portfolio_period_return": -5.,
        "sharpe_ratio": -1.2, "sortino_ratio": -1.4, "calmar_ratio": -.4,
        "daily_var_95": -3., "daily_cvar_95": -4., "monthly_var_95": -6.,
        "active_var_95_krw": 30., "active_cvar_95_krw": 40., "portfolio_observation_count": 120,
        "avg_corr": .7, "total_asset": 1000., "active_value": 850.,
        "leverage_summary": {"leveraged_principal_pct": 20., "effective_exposure_pct": 125., "extra_exposure_pct": 40.},
        "drawdown_details": {"underwater": pd.Series([0., -2., -8., -3.], index=index),
            "avg_drawdown": -4., "mdd_duration_days": 40, "mdd_recovery_days": np.nan, "n_drawdown_periods": 1},
        "rolling_df": pd.DataFrame({"rolling_vol": [20., 25., 22., 23.],
            "rolling_sharpe": [-1., -1.1, -1.2, -.8]}, index=index),
        "benchmark_blended": benchmark, "blended_benchmark_spec": {"description": "fixture mix"},
        "benchmark_voo": dict(benchmark, alpha=2.), "benchmark_kr": {},
        "stress_results": [{"시나리오": "Crash", "기간": "fixture", "설명": "synthetic",
            "포트 추정 손익(%)": -30., "추정 손실액(원)": 300., "asset_breakdown": [
                {"자산명": "Core", "개별충격(%)": -40., "기여(%)": -20.}]}]}
    if kind == "minimal":
        metrics = {key: value for key, value in metrics.items() if key in {
            "reserve_summary", "risk_color", "risk_grade", "risk_index", "portfolio_vol",
            "portfolio_mdd", "top1_weight", "top3_weight", "total_asset", "active_value"}}
        metrics.update(portfolio_vol=np.nan, portfolio_mdd=np.nan)
        notes, corr, contrib, curve = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=float)
    elif kind == "healthy":
        metrics.update(risk_grade="정상", risk_index=20., portfolio_vol=10., portfolio_mdd=-5.,
            portfolio_annual_return=10., sharpe_ratio=1.2, top1_weight=20., top3_weight=50.,
            avg_corr=.2, portfolio_observation_count=300, leverage_summary={})
    elif kind == "empty":
        assets = pd.DataFrame()
    return metrics, assets, notes, corr, curve, contrib


def run(source, app, payload, *, detail, ready, monthly):
    ui = UI(detail)
    namespace = dict(vars(app), st=ui, datetime=FixedDateTime,
        should_run_heavy_analysis=lambda *a, **k: ready,
        get_portfolio_analysis_start_date=lambda _: pd.Timestamp("2026-01-01") if monthly else None,
        get_cached_portfolio_signal_details=lambda: pd.DataFrame(),
        build_portfolio_analysis_report=lambda *a, **k: deepcopy(payload),
        prepare_monthly_performance_df=lambda _: pd.DataFrame({"month_end": ["2026-01-31", "2026-03-31"],
            "relative_return_pct": [0., -3.]}) if monthly else pd.DataFrame())
    for name in ("render_portfolio_decision_summary", "render_portfolio_action_decision_panel",
                 "render_portfolio_market_alignment_panel", "render_ten_year_project_fit_panel",
                 "render_portfolio_final_summary_card", "render_portfolio_data_coverage_notice",
                 "render_portfolio_risk_breakdown", "render_leverage_exposure_panel",
                 "render_portfolio_sample_warning", "render_long_term_goal_simulator", "render_correlation_interpretation"):
        def record(*args, _name=name, **kwargs):
            ui.record(_name, *args, **kwargs)
            return {}
        namespace[name] = record
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
             and node.name in (MAIN, *HELPERS, "render_portfolio_review_summary")]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<portfolio-renderer>", "exec"), namespace)
    with patch("stock_lab_core.account_performance_view.render_account_performance",
               side_effect=lambda *a, **kw: ui.record("render_account_performance", **kw)):
        namespace[MAIN](pd.DataFrame(), 0., 0., 1300., 5., monthly_logs_df=pd.DataFrame())
    return ui.log, ui.session_state


@pytest.mark.parametrize("kind", ["rich", "minimal", "healthy", "empty"])
@pytest.mark.parametrize("detail,monthly", [(False, False), (True, False), (True, True)])
def test_portfolio_ui_values_figures_keys_and_state_are_identical(sources, app_module, kind, detail, monthly):
    payload = report(kind)
    expected = run(sources[0], app_module, payload, detail=detail, ready=True, monthly=monthly)
    actual = run(sources[1], app_module, payload, detail=detail, ready=True, monthly=monthly)
    assert freeze(actual) == freeze(expected)


def test_lazy_early_return_is_identical(sources, app_module):
    assert run(sources[0], app_module, report("empty"), detail=True, ready=False, monthly=False) == run(
        sources[1], app_module, report("empty"), detail=True, ready=False, monthly=False)


def test_extracted_statement_trees_and_literals_are_exactly_unchanged(sources):
    old = next(node for node in ast.parse(sources[0]).body if isinstance(node, ast.FunctionDef) and node.name == MAIN)
    current = {node.name: node for node in ast.parse(sources[1]).body
               if isinstance(node, ast.FunctionDef) and node.name in (MAIN, *HELPERS)}
    start = next(i for i, node in enumerate(old.body) if isinstance(node, ast.Expr)
                 and isinstance(node.value, ast.Call) and node.value.args
                 and isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == "#### 리스크 기여도")
    extracted = [node for name in HELPERS for node in current[name].body]
    assert ast.dump(ast.Module(body=old.body[start:], type_ignores=[]), include_attributes=False) == ast.dump(
        ast.Module(body=extracted, type_ignores=[]), include_attributes=False)
    assert current[MAIN].end_lineno - current[MAIN].lineno + 1 < 200
