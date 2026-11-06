"""Candidate ranking is not execution permission; presentation cannot rescore."""

import ast
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core.portfolio_candidate_view import (
    alignment_candidate_summary, candidate_execution_view,
)
from stock_lab_core.portfolio_signal_cache import select_portfolio_signals


def signals(gate="방어우선", ticker="BITX"):
    frame = pd.DataFrame([{"티커": ticker, "기술적타점": "original", "게이트상태": gate,
                           "게이트근거": "시장방어: 신규매수 중단", "가격자료기준일": "2026-11-05"}])
    frame.attrs.update(portfolio_signal_context="account-a", portfolio_signal_at="2026-11-06T01:00Z")
    return select_portfolio_signals({"portfolio_dashboard_signal_df": frame}, "account-a", detailed=True)


def candidates():
    return pd.DataFrame([{"티커": "BITX", "자산": "Bitcoin ETF", "포트판정": "조건부 소액",
                          "우선점수": 68.5, "현재비중": 3.6, "제안금액": 120000., "주수": 7.5}])


@pytest.mark.parametrize("gate,status", [
    ("방어우선", "추가매수 보류"), ("대기/관찰", "대기/관찰"),
    ("데이터확인", "데이터 확인"), ("실행가능", "정밀 최종 확인"),
    (None, "게이트 미연결"), ("unknown", "게이트 미연결"),
])
def test_candidates_keep_original_decision_score_order_weights_money_and_shares(gate, status):
    frame, evidence = candidates(), signals(gate)
    before, evidence_before = deepcopy(frame), deepcopy(evidence)
    view, counts = alignment_candidate_summary(frame, evidence)
    pd.testing.assert_frame_equal(view[frame.columns], before)
    pd.testing.assert_frame_equal(frame, before)
    pd.testing.assert_frame_equal(evidence, evidence_before)
    assert view.iloc[0]["실행 확인"] == status
    assert view.iloc[0]["판정 출처"] == "전광판"
    assert view.iloc[0]["판정 기준일"] == "2026-11-05"
    assert counts["candidates"] == counts["restricted"] + counts["check"] + counts["unconfirmed"] == 1
    if gate == "실행가능":
        assert "비중·현금 확인 필요" in view.iloc[0]["제한·확인 사유"]
    if gate == "방어우선":
        assert counts["restricted"] == 1 and counts["check"] == 0


def test_missing_scope_does_not_reuse_other_account_gate():
    frame = signals()
    frame.attrs["portfolio_signal_context"] = "account-a"
    scoped = select_portfolio_signals({"portfolio_today_signal_df": frame}, "account-b", detailed=True)
    view = candidate_execution_view(candidates(), scoped)
    assert view.iloc[0]["실행 확인"] == "게이트 미연결"


@pytest.mark.parametrize("representative", ["BITX · MAGS", "Bitcoin ETF", "BITX,MAGS", "", None])
def test_theme_representatives_do_not_inherit_a_member_gate(representative):
    frame = pd.DataFrame([{"티커/대표": representative, "우선점수": 99}])
    view = candidate_execution_view(frame, signals("실행가능"), ticker_column="티커/대표")
    assert view.iloc[0]["실행 확인"] == "게이트 미연결"
    assert view.iloc[0]["우선점수"] == 99


@pytest.mark.parametrize("ticker", ["bitx", "BITX.US"])
def test_exact_shared_ticker_aliases_connect(ticker):
    assert candidate_execution_view(candidates().assign(티커=ticker), signals()).iloc[0]["실행 확인"] == "추가매수 보류"


def test_unknown_date_and_duplicate_rows_never_show_check_pass():
    evidence = signals("실행가능")
    evidence["가격자료기준일"] = None
    assert candidate_execution_view(candidates(), evidence).iloc[0]["실행 확인"] == "기준일 확인"
    duplicate = pd.concat([signals(), signals("실행가능")], ignore_index=True)
    row = candidate_execution_view(candidates(), duplicate).iloc[0]
    assert row["실행 확인"] == "게이트 미연결" and "중복" in row["제한·확인 사유"]


def test_empty_frames_are_supported():
    assert candidate_execution_view(None, None).empty
    assert candidate_execution_view(pd.DataFrame(), signals()).empty
    _, counts = alignment_candidate_summary(pd.DataFrame(), None)
    assert sum(counts.values()) == 0


def test_same_scoped_signals_feed_all_four_actual_panels():
    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_portfolio_market_alignment_panel")
    src = ast.unparse(fn)
    assert "select_portfolio_signals(st.session_state, portfolio_signal_input_context(), detailed=True)" in src
    assert "render_alignment_overview(st, align_df, signal_details)" in src
    for name in ("render_portfolio_recommendation_panel", "render_portfolio_next_check_candidates_panel", "render_portfolio_rebalance_playbook_panel"):
        call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == name)
        assert any(k.arg == "signal_details" and ast.unparse(k.value) == "signal_details" for k in call.keywords)
    assert "늘릴/적립 후보" not in src and "확대/분할 후보" not in src


def test_streamlit_candidate_panel_shows_restriction_before_raw_plan():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string('''
import streamlit as st
from tests.test_portfolio_candidate_view import candidates, signals
from stock_lab_core.portfolio_candidate_view import render_alignment_overview, render_recommendation_candidates
frame = candidates()
render_alignment_overview(st, frame, signals())
rec = frame.rename(columns={"티커": "티커/대표", "자산": "후보"}).assign(추천구분="조건부 보강", 실행강도="분할", 다음행동="old plan")
render_recommendation_candidates(st, rec, signals())
''').run(timeout=30)
    assert not at.exception
    assert "보류/대기 1개" in at.info[0].value
    assert "정밀 최종 확인 0개" in at.info[0].value
    assert at.dataframe[0].value.columns[:3].tolist() == ["자산", "실행 확인", "제한·확인 사유"]
    assert at.dataframe[1].value.iloc[0]["실행 확인"] == "추가매수 보류"
    assert "실행강도" not in at.dataframe[1].value.columns
    assert "원래 계획강도" in at.dataframe[2].value.columns
    assert not at.expander[-1].proto.expanded
