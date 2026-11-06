"""The board-to-portfolio handoff must keep one scoped, dated result intact."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.portfolio_signal_cache import (
    DASHBOARD_SIGNAL_KEY, capture_dashboard_signals, select_portfolio_signals,
)
from stock_lab_core.portfolio_holding_review import build_holding_review, capture_precision_review, PRECISION_KEY
from tests.test_portfolio_holding_review import snapshot


@pytest.mark.parametrize("ticker", ["379810.KS", "418660.KS", "0167A0.KS", "RAM", "SOXL", "CIBR", "BITX", "MAGS"])
@pytest.mark.parametrize("gate", ["방어우선", "대기/관찰", "실행가능", "데이터확인"])
def test_board_to_portfolio_keeps_all_evidence_and_original_time(ticker, gate):
    source = snapshot([{"티커": ticker, "🔥기술적 타점": "original"}])
    prepared = pd.DataFrame([{
        "티커": ticker, "🔥기술적 타점": "original", "판정코드": "unchanged",
        "게이트상태": gate, "게이트근거": "same reason", "가격자료기준일": "2026-11-03",
        "지표마지막봉": "2026-11-03", "가격반영": "가격 이력 기준", "계산시각": "2026-11-04 10:00 KST",
    }])
    before_source, before_prepared = deepcopy(source), deepcopy(prepared)
    state = {}
    assert capture_dashboard_signals(state, source, prepared, "account-a")
    signals = select_portfolio_signals(state, "account-a", detailed=True)
    row = signals.iloc[0]
    for key, value in prepared.iloc[0].items():
        assert row[key] == value
    assert row["연결출처"] == "전광판"
    assert row["저장시각"] == source.attrs["portfolio_signal_at"]
    capture_precision_review(state, "account-a", ticker, {
        "input_basis": {"가격자료기준일": row["가격자료기준일"]},
        "execution_workflow": {"게이트상태": gate, "게이트근거": "same reason"},
    }, {"execution_allowed": False, "block_count": 2, "final_label": "매수 금지"})
    overview, details = build_holding_review(pd.DataFrame([
        {"티커": ticker, "자산명": ticker, "보유량": 1},
    ]), signals, state[PRECISION_KEY], "account-a")
    assert overview.iloc[0]["점검 게이트"] == gate
    assert overview.iloc[0]["점검 기준일"] == overview.iloc[0]["정밀 기준일"]
    assert all(not d["ready"]["execution_allowed"] for d in details.values())
    pd.testing.assert_frame_equal(source, before_source)
    pd.testing.assert_frame_equal(prepared, before_prepared)
    assert source.attrs == before_source.attrs
    prepared.loc[0, "게이트상태"] = "mutated"
    assert state[DASHBOARD_SIGNAL_KEY].iloc[0]["게이트상태"] == gate


@pytest.mark.parametrize("context,attrs,empty", [
    ("account-b", {}, False), ("account-a", {"portfolio_signal_context": None}, False),
    ("account-a", {"portfolio_signal_at": None}, False),
    ("account-a", {"portfolio_signal_at": "invalid"}, False), ("account-a", {}, True),
])
def test_invalid_handoff_clears_only_board_copy(context, attrs, empty):
    source = snapshot([{"티커": "RAM", "기술적타점": "old"}])
    source.attrs.update(attrs)
    prepared = pd.DataFrame() if empty else pd.DataFrame([{"티커": "RAM", "게이트상태": "방어우선"}])
    state = {DASHBOARD_SIGNAL_KEY: source, "portfolio_today_signal_df": source}
    assert not capture_dashboard_signals(state, source, prepared, context)
    assert DASHBOARD_SIGNAL_KEY not in state
    assert state["portfolio_today_signal_df"] is source


def test_rerender_does_not_outrank_a_newer_today_calculation():
    source = snapshot([{"티커": "RAM", "기술적타점": "board"}])
    prepared = source.assign(게이트상태="방어우선")
    today = snapshot([{"티커": "RAM", "기술적타점": "today", "게이트상태": "대기/관찰"}], "2026-11-04T03:00Z")
    state = {"portfolio_today_signal_df": today}
    for _ in range(2):
        assert capture_dashboard_signals(state, source, prepared, "account-a")
        row = select_portfolio_signals(state, "account-a", detailed=True).iloc[0]
        assert row["연결출처"] == "오늘점검" and row["기술적타점"] == "today"
    assert select_portfolio_signals(state, "account-b", detailed=True).empty


def test_application_publishes_after_enrichment_and_stamps_only_calculated_source():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    branch = next(n for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) == "main_page == 'dashboard'")
    calls = list(n for n in ast.walk(branch) if isinstance(n, ast.Call))
    publish = next(n for n in calls if ast.unparse(n.func).endswith(".capture_dashboard_signals"))
    prepare = next(n for n in calls if ast.unparse(n.func) == "prepare_dashboard_display")
    assert publish.lineno > prepare.lineno
    assert [ast.unparse(a) for a in publish.args] == [
        "st.session_state", "_dash_signal_source", "summary_df", "portfolio_signal_input_context()",
    ]
    calculation = next(n for n in ast.walk(branch) if isinstance(n, ast.If) and ast.unparse(n.test) == "_run_dash or not _dash_valid")
    assert any(isinstance(n, ast.Call) and ast.unparse(n.func) == "stamp_portfolio_signal_context" for n in ast.walk(calculation))
    assert not any(isinstance(n, ast.Call) and ast.unparse(n.func) == "stamp_portfolio_signal_context" for s in calculation.orelse for n in ast.walk(s))
