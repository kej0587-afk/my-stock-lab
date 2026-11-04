"""Synthetic, read-only evidence tests; no market or brokerage calls."""

from copy import deepcopy

import pandas as pd
from pandas.testing import assert_frame_equal

from stock_lab_core.portfolio_holding_review import (
    PRECISION_KEY, build_holding_review, capture_precision_review,
    holding_choice_rows, render_portfolio_holding_review,
)
from stock_lab_core.portfolio_signal_cache import select_portfolio_signals


def snapshot(rows, at="2026-11-04T01:00Z", context="account-a"):
    frame = pd.DataFrame(rows)
    frame.attrs.update(portfolio_signal_context=context, portfolio_signal_at=at)
    return frame


def test_detailed_cache_keeps_gate_provenance_without_changing_legacy_columns():
    source = snapshot([{"티커": "RAM", "기술적타점": "분할 검토", "게이트상태": "방어우선", "가격자료기준일": "2026-11-03"}])
    before = source.copy(deep=True)
    state = {"portfolio_today_signal_df": source}
    old = select_portfolio_signals(state, "account-a")
    assert list(old) == ["티커", "기술적타점"]
    rich = select_portfolio_signals(state, "account-a", detailed=True)
    assert rich.iloc[0]["게이트상태"] == "방어우선"
    assert rich.iloc[0]["연결출처"] == "오늘점검"
    assert rich.iloc[0]["저장시각"] == "2026-11-04T01:00Z"
    assert_frame_equal(source, before)
    assert source.attrs == before.attrs
    assert select_portfolio_signals(state, "account-b", detailed=True).empty


def test_newer_row_is_not_filled_with_an_older_gate():
    state = {
        "portfolio_today_signal_df": snapshot([{"티커": "RAM", "기술적타점": "old", "게이트상태": "실행가능"}]),
        "_ticker_signal_detail_df": snapshot([{"티커": "RAM.US", "기술적타점": "new"}], "2026-11-04T02:00Z"),
    }
    row = select_portfolio_signals(state, "account-a", detailed=True).iloc[0]
    assert pd.isna(row["게이트상태"])
    assert row["연결출처"] == "전광판"


def test_complete_precision_is_scoped_and_deep_copied():
    state = {}
    decision = {"input_basis": {"가격자료기준일": "2026-11-03"}, "execution_workflow": {"게이트상태": "실행가능"}}
    final = {"final_label": "매수 금지", "execution_allowed": False, "block_count": 2, "core_missing_ids": []}
    capture_precision_review(state, "account-a", "RAM", decision, final, captured_at="2026-11-04T02:00Z")
    final["execution_allowed"] = True
    assert state[PRECISION_KEY]["reviews"]["RAM"]["final"]["execution_allowed"] is False
    holdings = pd.DataFrame([{"티커": "RAM", "자산명": "Memory", "보유량": 1}])
    signals = snapshot([{"티커": "RAM", "게이트상태": "실행가능", "가격자료기준일": "2026-11-02"}])
    overview, details = build_holding_review(holdings, signals, state[PRECISION_KEY], "account-a")
    assert overview.iloc[0]["정밀 최종 체크"] == "실행 보류"
    assert overview.iloc[0]["점검 기준일"] != overview.iloc[0]["정밀 기준일"]
    assert not details["RAM"]["ready"]["execution_allowed"]
    other, _ = build_holding_review(holdings, signals, state[PRECISION_KEY], "account-b")
    assert other.iloc[0]["정밀 최종 체크"] == "미점검"
    capture_precision_review(state, "account-b", "CIBR", {}, {})
    assert "RAM" not in state[PRECISION_KEY]["reviews"]


def test_missing_or_zero_quantity_and_duplicate_accounts_do_not_make_candidates():
    holdings = pd.DataFrame([
        {"티커": "RAM", "보유량": 1}, {"티커": "RAM.US", "보유량": 2},
        {"티커": "CIBR", "보유량": 0}, {"티커": "SOXL"},
    ])
    overview, _ = build_holding_review(holdings, pd.DataFrame(), None, "account-a")
    assert overview["티커"].tolist() == ["RAM"]
    assert overview.iloc[0]["점검 게이트"] == "미확인"


def test_choices_preserve_management_conditions_and_do_not_create_stop():
    detail = {"signal": {}, "precision": {"stop": float("nan")}}
    management = {"판정": "existing", "재개/해제 조건": "existing release", "근거": "existing reason"}
    before = deepcopy(management)
    rows = holding_choice_rows(detail, management)
    assert rows.iloc[0]["현재 근거"] == "existing · 밸류 미점검"
    assert "existing release" in rows.iloc[1]["확인할 조건"]
    assert "차트 기준선 미확인" in rows.iloc[1]["확인할 조건"]
    assert "판단 불가" in rows.iloc[2]["확인할 조건"]
    assert "교체 승인 아님" in rows.iloc[3]["확인할 조건"]
    assert management == before


class FakeUI:
    def __init__(self):
        self.session_state = {}
        self.tables = []
        self.messages = []

    def markdown(self, value): self.messages.append(value)
    def caption(self, value): self.messages.append(value)
    def warning(self, value): self.messages.append(value)
    def dataframe(self, value, **kwargs): self.tables.append(value)
    def selectbox(self, label, options, **kwargs): return options[0]
    def button(self, *args, **kwargs): return False


def test_renderer_does_not_fetch_or_mutate_account_and_discloses_daily_leverage():
    ui = FakeUI()
    holding = pd.DataFrame([{"티커": "RAM", "자산명": "RAM", "보유량": 1}])
    before = holding.copy(deep=True)
    render_portfolio_holding_review(ui, holding, context="account-a")
    assert len(ui.tables) == 2
    assert "일간 2배" in " ".join(ui.messages)
    assert "매도 명령이 아니" in " ".join(ui.messages)
    assert ui.session_state == {}
    assert_frame_equal(holding, before)


def test_app_cache_refactor_equals_previous_implementation(app_module, monkeypatch):
    # Frozen output of the former selector, including column order and NaNs.
    context = "account-a"
    state = {
        "_ticker_signal_detail_df": snapshot([{"티커": "RAM.US", "기술적타점": "old", "후보등급": "B"}]),
        "portfolio_today_signal_df": snapshot([{"티커": "RAM", "🔥기술적 타점": "new", "📌후보등급": "A", "게이트상태": "방어우선"}], "2026-11-04T02:00Z"),
    }
    from types import SimpleNamespace
    expected = pd.DataFrame([{"티커": "RAM", "기술적타점": "new", "후보등급": "A"}])
    monkeypatch.setattr(app_module, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(app_module, "portfolio_signal_input_context", lambda: context)
    assert_frame_equal(expected, app_module.get_cached_portfolio_signal_details())


def test_streamlit_panel_renders_and_switches_holdings():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string('''
import pandas as pd
import streamlit as st
from stock_lab_core.portfolio_holding_review import render_portfolio_holding_review
holdings = pd.DataFrame([
    {"티커": "RAM", "자산명": "RAM", "보유량": 1},
    {"티커": "0167A0.KS", "자산명": "SOL AI반도체TOP2플러스", "보유량": 1},
])
render_portfolio_holding_review(st, holdings, context="synthetic")
''').run(timeout=30)
    assert not at.exception
    assert len(at.dataframe) == 2
    assert "일간 2배" in " ".join(v.value for v in at.markdown)
    at.selectbox[0].select("0167A0.KS").run(timeout=30)
    assert not at.exception
    assert "국내 반도체 10종목" in " ".join(v.value for v in at.markdown)
