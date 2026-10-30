"""Regression boundaries for missing market data, invalid R/R and zero cash."""

from copy import deepcopy
import ast
import math
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core.decision_engine import build_core_dca_context_values
from stock_lab_core.decision_workflow import attach_market_execution_context, build_decision_workflow
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT, apply_execution_gate_columns,
)
from stock_lab_core.today_queue import build_today_queue_execution_snapshot
from stock_lab_core.today_snapshot import TODAY_QUEUE_LOGIC_VERSION, invalidate_incompatible_summary_state


def candidate():
    return dict(grade="A", t_score=8, dec="신규진입: 대장주 포착",
                decision_code="NEW_ENTRY_LEADER", decision_group="buyish",
                cur_p=100, rr_stop=90, rr_target=120, rr_ratio=2, ma20=98, atr=5)


def gated(guard, ticker="MSFT", decision=None):
    row = build_decision_workflow(ticker, ticker, decision or candidate())
    return apply_execution_gate_columns(
        attach_market_execution_context(pd.DataFrame([row]), guard)
    ).iloc[0]


@pytest.mark.parametrize("guard", [
    None, {}, {"mode": "정상"}, {"kr_stats": {"mode": "정상"}},
    {"us_stats": {}}, {"us_stats": None}, {"us_stats": {"mode": "데이터부족"}},
    {"mode": "정상", "us_stats": {"mode": "데이터부족"}},
    {"us_stats": {"mode": float("nan")}},
])
def test_missing_regional_market_is_not_normal_or_executable(guard):
    row = gated(guard)
    assert row["시장실행상태"] != "정상"
    assert row["게이트상태"] == GATE_DATA_CHECK
    assert "시장정보" in row["게이트근거"]
    assert row["후보품질"] == "A" and row["판정코드"] == "NEW_ENTRY_LEADER"


@pytest.mark.parametrize("mode", ["정상", "주의", "방어", "위험장 반등"])
def test_available_market_keeps_ordinary_stock_policy(mode):
    assert gated({"us_stats": {"mode": mode}})["게이트상태"] == GATE_EXECUTABLE


def test_missing_other_region_does_not_override_known_local_data():
    guard = {"kr_stats": {"mode": "정상"}, "us_stats": {"mode": "데이터부족"}}
    assert gated(guard, "005930.KS")["게이트상태"] == GATE_EXECUTABLE
    assert gated(guard)["게이트상태"] == GATE_DATA_CHECK


def test_known_defense_still_takes_priority_over_missing_market():
    assert gated({"action": "신규매수 중단"})["게이트상태"] == GATE_DEFENSE
    assert gated({"mode": "위험"})["게이트상태"] == GATE_DEFENSE
    overweight = candidate()
    overweight.update(dec="비중 초과: 추매금지", decision_code="HARD_BLOCK_OVERWEIGHT")
    assert gated(None, decision=overweight)["게이트상태"] == GATE_DEFENSE
    assert gated({"us_stats": {"mode": "방어"}}, "SOXL")["게이트상태"] == GATE_DEFENSE


def test_market_recovery_rechecks_without_mutating_inputs():
    source = pd.DataFrame([build_decision_workflow("MSFT", "MSFT", candidate())])
    original = source.copy(deep=True)
    missing = apply_execution_gate_columns(attach_market_execution_context(source, None))
    recovered = apply_execution_gate_columns(attach_market_execution_context(
        missing, {"us_stats": {"mode": "정상"}},
    ))
    assert missing.iloc[0]["게이트상태"] == GATE_DATA_CHECK
    assert recovered.iloc[0]["게이트상태"] == GATE_EXECUTABLE
    pd.testing.assert_frame_equal(source, original)


@pytest.mark.parametrize("prices", [
    {"rr_target": 95}, {"rr_target": 100}, {"rr_target": 0},
    {"rr_target": None}, {"rr_target": float("nan")}, {"rr_target": float("inf")},
    {"rr_stop": 100}, {"rr_stop": 110}, {"rr_stop": 0}, {"cur_p": 0},
])
def test_invalid_prices_clear_old_positive_rr_in_text_and_numeric_fields(prices):
    decision = candidate()
    decision.update(prices)
    original = deepcopy(decision)
    snapshot = build_today_queue_execution_snapshot("MSFT", "MSFT", decision)
    assert snapshot["R/R"] == "-"
    assert math.isnan(snapshot["RR값"])
    assert snapshot["1차기준"] == "데이터확인"
    assert gated({"us_stats": {"mode": "정상"}}, decision=decision)["게이트상태"] == GATE_DATA_CHECK
    assert decision == original


@pytest.mark.parametrize("target,expected_rr,expected_gate", [
    (105, 0.5, GATE_WAIT), (110, 1.0, GATE_EXECUTABLE), (120, 2.0, GATE_EXECUTABLE),
])
def test_valid_rr_is_recalculated_with_existing_one_r_threshold(target, expected_rr, expected_gate):
    decision = candidate()
    decision.update(rr_target=target, rr_ratio=99)
    snapshot = build_today_queue_execution_snapshot("MSFT", "MSFT", decision)
    assert snapshot["RR값"] == expected_rr
    assert snapshot["R/R"] == f"{expected_rr:.2f}"
    assert gated({"us_stats": {"mode": "정상"}}, decision=decision)["게이트상태"] == expected_gate


@pytest.mark.parametrize("cash,reserve,drawdown,expected", [
    (0, 0, -0.1, 0), (1, 0, -0.1, 1), (-1, 0, -0.1, 0),
    (0, 500_000, -0.1999, 0), (0, 500_000, -0.20, 500_000),
    (300_000, 500_000, -0.25, 800_000), (2_000_000, 0, -0.1, 1_000_000),
])
def test_personal_dca_never_exceeds_available_pool(cash, reserve, drawdown, expected):
    result = build_core_dca_context_values(
        mode="개인모드", rate=1, label="unchanged", buy_amount=1_000_000,
        current_dd=drawdown, cash_available=cash, reserve_available=reserve,
    )
    assert result["core_dca_amt"] == expected
    assert result["core_dca_amt"] <= max(result["core_dca_pool"], 0)
    assert result["core_dca_rate"] == 1 and result["core_dca_label"] == "unchanged"


def test_nonpersonal_target_gap_plan_does_not_require_account_cash():
    result = build_core_dca_context_values(
        mode="자유모드", rate=1.5, label="unchanged", buy_amount=1_000_000,
        current_dd=-0.25, cash_available=0, reserve_available=0,
    )
    assert result["core_dca_amt"] == 1_000_000
    assert result["core_dca_pool_label"] == "목표비중 부족분"


@pytest.mark.parametrize("version", [None, "20261014_market_stop_basis_v8"])
def test_old_session_caches_cannot_restore_invalid_execution(version):
    stale = pd.DataFrame([{"RR값": 2, "게이트상태": GATE_EXECUTABLE}])
    state = {
        "_decision_summary_logic_version": version,
        "today_queue_summary_df": stale, "today_queue_summary_sig": "old",
        "today_queue_summary_last_run": "old time",
        "today_queue_summary_last_nonempty_df": stale, "today_queue_summary_last_nonempty_sig": "old",
        "dashboard_summary_df": stale, "dashboard_summary_sig": "old", "dashboard_summary_last_run": "old time",
        "watchlist": ["MSFT"], "krw_cash": 0,
    }
    assert invalidate_incompatible_summary_state(state)
    assert state == {"_decision_summary_logic_version": TODAY_QUEUE_LOGIC_VERSION,
                     "watchlist": ["MSFT"], "krw_cash": 0}
    state["today_queue_summary_df"] = stale
    assert not invalidate_incompatible_summary_state(state)
    assert state["today_queue_summary_df"] is stale


def test_app_invalidates_old_summaries_before_any_view_can_read_them():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    invalidate = next(node for node in tree.body if isinstance(node, ast.Expr)
                      and isinstance(node.value, ast.Call)
                      and ast.unparse(node.value.func) == "invalidate_incompatible_summary_state")
    assert ast.unparse(invalidate.value.args[0]) == "st.session_state"
    views = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and ast.unparse(node.func) in {"render_today_queue_tab", "resolve_today_market_memo_summary_df"}]
    assert views and all(invalidate.lineno < node.lineno for node in views)
